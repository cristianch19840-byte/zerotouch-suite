from __future__ import annotations

import inspect
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

ESTADOS_DESCARTABLES = ("nuevo", "descartado", "ignorado", "rechazado", "")
TABLAS_VISTOS_CANDIDATAS = (
    "vistos",
    "ofertas_vistas",
    "posts_vistos",
    "aegis_dedup",
    "aegis_auditoria",
    "dedup_cache",
)
TABLAS_REF_LEAD = ("tareas_crm", "propuestas", "facturas", "sesiones_tiempo")


def _tablas_existentes(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {str(r[0]) for r in rows}


def _columnas_tabla(conn: sqlite3.Connection, tabla: str) -> dict[str, dict[str, Any]]:
    rows = conn.execute(f"PRAGMA table_info({tabla})").fetchall()
    return {
        str(r[1]): {"type": str(r[2]), "notnull": bool(r[3]), "default": r[4]}
        for r in rows
    }


def _crear_backup_pre_limpieza(db_path: str) -> str | None:
    if not db_path or db_path == ":memory:" or not os.path.isfile(db_path):
        return None
    bkp_dir = os.path.join(os.path.dirname(os.path.abspath(db_path)), "backups")
    os.makedirs(bkp_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dst_path = os.path.join(bkp_dir, f"pre_limpieza_{stamp}.db")
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(dst_path)
    try:
        src.backup(dst, pages=256)
    finally:
        dst.close()
        src.close()
    return dst_path


class RadarCleanerService:
    """
    Limpiador seguro y auditable de detecciones del Radar/OMNI:
    - preview(): muestra conteo exacto por categoria antes de borrar
    - limpiar(modo, ...): soporta 'nuevos', 'bajo_score', 'todos' o 'estado'
      con backup automatico previo, limpieza opcional de tablas de vistos/dedup
      y preservacion segura de referencias en facturas/tiempo/tareas.
    """

    def __init__(self, svc: Any) -> None:
        self.svc = svc
        self.db = svc.db
        self.bus = getattr(svc, "bus", None)

    def preview(self, score_max: int = 6) -> dict[str, Any]:
        conn = self.db.obtener_conexion()
        tablas = _tablas_existentes(conn)
        if "leads" not in tablas:
            return {
                "ok": True,
                "total": 0,
                "nuevos_y_descartados": 0,
                "protegidos": 0,
                "bajo_score": 0,
                "por_estado": {},
                "vistos_registrados": 0,
            }

        total = int(conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0])
        placeholders = ",".join("?" for _ in ESTADOS_DESCARTABLES)
        nuevos_y_desc = int(
            conn.execute(
                f"SELECT COUNT(*) FROM leads WHERE COALESCE(LOWER(TRIM(estado)), '') IN ({placeholders})",
                ESTADOS_DESCARTABLES,
            ).fetchone()[0]
        )
        bajo_score = int(
            conn.execute(
                f"SELECT COUNT(*) FROM leads WHERE COALESCE(score, 0) <= ? "
                f"AND COALESCE(LOWER(TRIM(estado)), '') IN ({placeholders})",
                (int(score_max), *ESTADOS_DESCARTABLES),
            ).fetchone()[0]
        )

        por_estado: dict[str, int] = {}
        for st, cnt in conn.execute(
            "SELECT COALESCE(NULLIF(LOWER(TRIM(estado)), ''), 'nuevo') AS est, COUNT(*) FROM leads GROUP BY est"
        ).fetchall():
            por_estado[str(st)] = int(cnt)

        vistos_total = 0
        for tbl in TABLAS_VISTOS_CANDIDATAS:
            if tbl in tablas:
                try:
                    vistos_total += int(conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0])
                except sqlite3.Error:
                    pass

        return {
            "ok": True,
            "total": total,
            "nuevos_y_descartados": nuevos_y_desc,
            "protegidos": max(0, total - nuevos_y_desc),
            "bajo_score": bajo_score,
            "score_max_ref": int(score_max),
            "por_estado": por_estado,
            "vistos_registrados": vistos_total,
        }

    def limpiar(
        self,
        *,
        modo: str = "nuevos",
        score_max: int = 6,
        estados: list[str] | None = None,
        limpiar_vistos: bool = False,
        backup_previo: bool = True,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        modo_norm = (modo or "nuevos").strip().lower()
        if modo_norm not in ("nuevos", "bajo_score", "todos", "estado"):
            return {"ok": False, "error": f"Modo invalido: {modo}. Usa nuevos | bajo_score | todos | estado"}

        conn = self.db.obtener_conexion()
        tablas = _tablas_existentes(conn)
        if "leads" not in tablas:
            return {"ok": True, "modo": modo_norm, "eliminados": 0, "restantes": 0, "vistos_limpiados": 0}

        # 1. Determinar IDs de leads a eliminar
        placeholders = ",".join("?" for _ in ESTADOS_DESCARTABLES)
        if modo_norm == "todos":
            ids = [int(r[0]) for r in conn.execute("SELECT id FROM leads").fetchall()]
        elif modo_norm == "nuevos":
            ids = [
                int(r[0])
                for r in conn.execute(
                    f"SELECT id FROM leads WHERE COALESCE(LOWER(TRIM(estado)), '') IN ({placeholders})",
                    ESTADOS_DESCARTABLES,
                ).fetchall()
            ]
        elif modo_norm == "bajo_score":
            ids = [
                int(r[0])
                for r in conn.execute(
                    f"SELECT id FROM leads WHERE COALESCE(score, 0) <= ? "
                    f"AND COALESCE(LOWER(TRIM(estado)), '') IN ({placeholders})",
                    (int(score_max), *ESTADOS_DESCARTABLES),
                ).fetchall()
            ]
        else:
            est_list = [str(e).strip().lower() for e in (estados or []) if str(e).strip()]
            if not est_list:
                return {"ok": False, "error": "Especifica al menos un estado en 'estados'"}
            ph_e = ",".join("?" for _ in est_list)
            ids = [
                int(r[0])
                for r in conn.execute(
                    f"SELECT id FROM leads WHERE COALESCE(LOWER(TRIM(estado)), 'nuevo') IN ({ph_e})",
                    est_list,
                ).fetchall()
            ]

        backup_path = None
        if backup_previo and (ids or limpiar_vistos):
            try:
                backup_path = _crear_backup_pre_limpieza(getattr(self.db, "db_path", ""))
            except Exception:
                backup_path = None

        eliminados = 0
        vistos_limpiados = 0
        tablas_vistos_tocadas: list[str] = []

        with conn:
            # 2. Desacoplar referencias en tablas dependientes para no violar FK ni borrar facturas/horas
            if ids:
                chunk_size = 400
                for i in range(0, len(ids), chunk_size):
                    lote = ids[i : i + chunk_size]
                    ph_l = ",".join("?" for _ in lote)
                    for ref_tbl in TABLAS_REF_LEAD:
                        if ref_tbl not in tablas:
                            continue
                        cols = _columnas_tabla(conn, ref_tbl)
                        if "lead_id" not in cols:
                            continue
                        if cols["lead_id"]["notnull"]:
                            if ref_tbl == "propuestas":
                                conn.execute(f"DELETE FROM {ref_tbl} WHERE lead_id IN ({ph_l})", lote)
                        else:
                            conn.execute(f"UPDATE {ref_tbl} SET lead_id = NULL WHERE lead_id IN ({ph_l})", lote)

                    cur = conn.execute(f"DELETE FROM leads WHERE id IN ({ph_l})", lote)
                    eliminados += int(cur.rowcount or 0)

            # 3. Limpiar opcionalmente tablas de deduplicacion/vistos si el usuario quiere re-escanear de cero
            if limpiar_vistos:
                for tbl in TABLAS_VISTOS_CANDIDATAS:
                    if tbl in tablas:
                        try:
                            cur_v = conn.execute(f"DELETE FROM {tbl}")
                            c_v = int(cur_v.rowcount or 0)
                            vistos_limpiados += c_v
                            tablas_vistos_tocadas.append(tbl)
                        except sqlite3.Error:
                            pass

        # Limpiar caches en memoria de AEGIS si se pidio limpiar vistos
        if limpiar_vistos and getattr(self.svc, "aegis", None) is not None:
            vc = getattr(self.svc.aegis, "verdict_cache", None)
            if vc is not None and hasattr(vc, "limpiar"):
                try:
                    vc.limpiar()
                except Exception:
                    pass

        restantes = int(conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0])
        dur_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        res = {
            "ok": True,
            "modo": modo_norm,
            "eliminados": eliminados,
            "restantes": restantes,
            "vistos_limpiados": vistos_limpiados,
            "tablas_vistos_tocadas": tablas_vistos_tocadas,
            "backup_archivo": os.path.basename(backup_path) if backup_path else None,
            "backup_ruta": backup_path,
            "duracion_ms": dur_ms,
        }

        if self.bus is not None:
            try:
                self.bus.publicar(
                    "crm.leads.limpiados",
                    {
                        "modo": modo_norm,
                        "eliminados": eliminados,
                        "restantes": restantes,
                        "vistos_limpiados": vistos_limpiados,
                    },
                    origen="radar_cleaner",
                    nivel="warn" if eliminados > 0 else "info",
                )
            except Exception:
                pass

        return res


def _leer_json_req(req: Any) -> dict[str, Any]:
    if hasattr(req, "json") and callable(req.json):
        try:
            d = req.json()
            if isinstance(d, dict):
                return d
        except Exception:
            pass
    raw = getattr(req, "body", b"") or b""
    if isinstance(raw, (bytes, bytearray)) and raw.strip():
        try:
            d = json.loads(raw.decode("utf-8"))
            if isinstance(d, dict):
                return d
        except Exception:
            pass
    return {}


def _leer_query_int(req: Any, key: str, default: int) -> int:
    q = getattr(req, "query", None) or {}
    val = q.get(key)
    if isinstance(val, list):
        val = val[0] if val else None
    try:
        return int(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def _montar_ruta(router: Any, method: str, path: str, handler: Any, nombre: str) -> None:
    m_low = method.lower()
    if hasattr(router, m_low):
        fn = getattr(router, m_low)
        params = list(inspect.signature(fn).parameters.values())
        kw = {"nombre": nombre} if any(p.name == "nombre" for p in params) else {}
        if len(params) >= 2 and params[1].name in ("handler", "fn", "func", "callback"):
            fn(path, handler, **kw)
            return
        res = fn(path, **kw)
        if callable(res):
            res(handler)
            return
    for attr in ("registrar", "add_route", "agregar", "route"):
        if hasattr(router, attr):
            fn = getattr(router, attr)
            params = list(inspect.signature(fn).parameters.values())
            kw = {"nombre": nombre} if any(p.name == "nombre" for p in params) else {}
            if len(params) >= 3:
                fn(method.upper(), path, handler, **kw)
                return
    raise RuntimeError(f"No se pudo montar ruta {method} {path} en {type(router).__name__}")


def registrar_rutas_limpieza(router: Any, svc: Any) -> RadarCleanerService:
    cleaner = RadarCleanerService(svc)
    try:
        setattr(svc, "radar_cleaner", cleaner)
    except AttributeError:
        pass

    def _preview(req: Any) -> dict[str, Any]:
        smax = _leer_query_int(req, "score_max", 6)
        return cleaner.preview(score_max=smax)

    def _limpiar(req: Any) -> dict[str, Any]:
        body = _leer_json_req(req)
        return cleaner.limpiar(
            modo=str(body.get("modo") or "nuevos"),
            score_max=int(body.get("score_max", 6)),
            estados=body.get("estados") if isinstance(body.get("estados"), list) else None,
            limpiar_vistos=bool(body.get("limpiar_vistos", False)),
            backup_previo=bool(body.get("backup_previo", True)),
        )

    _montar_ruta(router, "GET", "/api/v2/leads/limpiar/preview", _preview, "leads_v2_limpiar_preview")
    _montar_ruta(router, "POST", "/api/v2/leads/limpiar", _limpiar, "leads_v2_limpiar")
    return cleaner