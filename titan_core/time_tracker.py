from __future__ import annotations

import csv
import io
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from titan_core.db_engine import TitanDBEngine, obtener_db_engine
from titan_core.event_bus import TitanEventBus, obtener_event_bus


def formatear_hms(segundos: int) -> str:
    s = max(0, int(segundos))
    hrs, rem = divmod(s, 3600)
    mins, seg = divmod(rem, 60)
    return f"{hrs:02d}:{mins:02d}:{seg:02d}"


def _tarifa_default_cfg() -> float:
    try:
        from core_ia import cargar_config, safe_float
        return max(1.0, safe_float(cargar_config().get("tarifa_hora_usd"), 25.0))
    except Exception:
        return 25.0


@dataclass(slots=True)
class SesionTiempo:
    id: int
    lead_id: int | None
    proyecto_nombre: str
    inicio_epoch: float
    fin_epoch: float | None
    duracion_seg: int
    tarifa_hora_usd: float
    facturable: bool
    notas: str = ""
    lead_titulo: str = ""

    @property
    def activa(self) -> bool:
        return self.fin_epoch is None

    def duracion_efectiva_seg(self, ahora: float | None = None) -> int:
        if self.fin_epoch is not None:
            return max(0, int(self.duracion_seg))
        ref = time.time() if ahora is None else float(ahora)
        return max(0, int(ref - self.inicio_epoch))

    def to_dict(self, ahora: float | None = None) -> dict[str, Any]:
        dur = self.duracion_efectiva_seg(ahora)
        horas = dur / 3600.0
        valor_usd = round(horas * self.tarifa_hora_usd, 2) if self.facturable else 0.0
        return {
            "id": self.id,
            "lead_id": self.lead_id,
            "proyecto_nombre": self.proyecto_nombre,
            "lead_titulo": self.lead_titulo,
            "inicio_epoch": round(self.inicio_epoch, 2),
            "fin_epoch": round(self.fin_epoch, 2) if self.fin_epoch is not None else None,
            "inicio_iso": datetime.fromtimestamp(self.inicio_epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "activa": self.activa,
            "duracion_seg": dur,
            "duracion_horas": round(horas, 3),
            "formato_hms": formatear_hms(dur),
            "tarifa_hora_usd": round(self.tarifa_hora_usd, 2),
            "facturable": self.facturable,
            "valor_devengado_usd": valor_usd,
            "notas": self.notas,
        }

    @classmethod
    def from_row(cls, r: dict[str, Any]) -> SesionTiempo:
        return cls(
            id=int(r["id"]),
            lead_id=int(r["lead_id"]) if r.get("lead_id") is not None else None,
            proyecto_nombre=str(r.get("proyecto_nombre") or "Proyecto"),
            inicio_epoch=float(r.get("inicio_epoch") or time.time()),
            fin_epoch=float(r["fin_epoch"]) if r.get("fin_epoch") is not None else None,
            duracion_seg=int(r.get("duracion_seg") or 0),
            tarifa_hora_usd=float(r.get("tarifa_hora_usd") or 25.0),
            facturable=bool(r.get("facturable", 1)),
            notas=str(r.get("notas") or ""),
            lead_titulo=str(r.get("lead_titulo") or ""),
        )


class TitanTimeTracker:
    """
    Cronometro persistente y motor de rentabilidad por hora (SQLite 'sesiones_tiempo'):
    - Sobrevive reinicios del servidor/PC (sesion abierta marcada con fin_epoch IS NULL)
    - Garantiza una sola sesion activa simultanea (auto-cierra la anterior si se inicia otra)
    - Cruza horas invertidas contra ingresos/facturas reales por Lead para medir USD/hr efectivos
    - Genera series diarias para graficos SVG y exporta timesheet en CSV
    """

    def __init__(
        self,
        db: TitanDBEngine | None = None,
        bus: TitanEventBus | None = None,
    ) -> None:
        self.db = db or obtener_db_engine()
        self.bus = bus or obtener_event_bus()
        self._lock = threading.RLock()

    def obtener_sesion(self, sesion_id: int) -> dict[str, Any] | None:
        row = self.db.consultar_uno(
            """
            SELECT s.*, COALESCE(l.titulo, '') AS lead_titulo
            FROM sesiones_tiempo s
            LEFT JOIN leads l ON l.id = s.lead_id
            WHERE s.id = ?
            """,
            (int(sesion_id),),
        )
        return SesionTiempo.from_row(row).to_dict() if row else None

    def obtener_sesion_activa(self) -> dict[str, Any] | None:
        row = self.db.consultar_uno(
            """
            SELECT s.*, COALESCE(l.titulo, '') AS lead_titulo
            FROM sesiones_tiempo s
            LEFT JOIN leads l ON l.id = s.lead_id
            WHERE s.fin_epoch IS NULL
            ORDER BY s.inicio_epoch DESC
            LIMIT 1
            """
        )
        return SesionTiempo.from_row(row).to_dict() if row else None

    def iniciar_sesion(
        self,
        proyecto_nombre: str = "",
        *,
        lead_id: int | None = None,
        tarifa_hora_usd: float | None = None,
        facturable: bool = True,
        notas: str = "",
        detener_previa: bool = True,
    ) -> dict[str, Any]:
        with self._lock:
            if detener_previa:
                activa = self.obtener_sesion_activa()
                if activa is not None:
                    self.detener_sesion(sesion_id=int(activa["id"]))

            lid_valid: int | None = None
            nombre = str(proyecto_nombre or "").strip()[:160]
            if lead_id is not None:
                row_l = self.db.consultar_uno("SELECT id, titulo FROM leads WHERE id = ?", (int(lead_id),))
                if row_l:
                    lid_valid = int(row_l["id"])
                    if not nombre:
                        nombre = str(row_l.get("titulo") or f"Lead #{lid_valid}")[:160]
            if not nombre:
                nombre = "Desarrollo Freelance"

            tarifa = float(tarifa_hora_usd) if (tarifa_hora_usd is not None and float(tarifa_hora_usd) > 0) else _tarifa_default_cfg()
            ahora = time.time()

            sid = self.db.ejecutar(
                """
                INSERT INTO sesiones_tiempo (
                    lead_id, proyecto_nombre, inicio_epoch, fin_epoch, duracion_seg,
                    tarifa_hora_usd, facturable, notas
                ) VALUES (?, ?, ?, NULL, 0, ?, ?, ?)
                """,
                (lid_valid, nombre, ahora, round(tarifa, 2), 1 if facturable else 0, str(notas or "")[:400]),
            )

        sesion = self.obtener_sesion(sid)
        assert sesion is not None
        self.bus.publicar(
            "tiempo.sesion.iniciada",
            {"sesion_id": sid, "lead_id": lid_valid, "proyecto": nombre, "tarifa_hora_usd": round(tarifa, 2)},
            origen="time_tracker",
            nivel="info",
        )
        return sesion

    def detener_sesion(
        self,
        sesion_id: int | None = None,
        *,
        notas: str | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            if sesion_id is None:
                activa = self.obtener_sesion_activa()
                if activa is None:
                    return None
                sid = int(activa["id"])
            else:
                sid = int(sesion_id)

            row = self.db.consultar_uno("SELECT * FROM sesiones_tiempo WHERE id = ?", (sid,))
            if not row:
                return None
            if row.get("fin_epoch") is not None:
                return self.obtener_sesion(sid)

            ahora = time.time()
            inicio = float(row["inicio_epoch"])
            dur = max(1, int(round(ahora - inicio)))
            notas_f = str(row.get("notas") or "") if notas is None else str(notas)[:400]

            self.db.ejecutar(
                "UPDATE sesiones_tiempo SET fin_epoch = ?, duracion_seg = ?, notas = ? WHERE id = ?",
                (ahora, dur, notas_f, sid),
            )

        sesion = self.obtener_sesion(sid)
        if sesion:
            self.bus.publicar(
                "tiempo.sesion.detenida",
                {
                    "sesion_id": sid,
                    "lead_id": sesion["lead_id"],
                    "proyecto": sesion["proyecto_nombre"],
                    "duracion_seg": sesion["duracion_seg"],
                    "formato_hms": sesion["formato_hms"],
                    "valor_devengado_usd": sesion["valor_devengado_usd"],
                },
                origen="time_tracker",
                nivel="ok",
            )
        return sesion

    def registrar_sesion_manual(
        self,
        proyecto_nombre: str,
        duracion_minutos: float,
        *,
        lead_id: int | None = None,
        tarifa_hora_usd: float | None = None,
        facturable: bool = True,
        notas: str = "",
        inicio_epoch: float | None = None,
    ) -> dict[str, Any]:
        dur_seg = max(60, int(round(float(duracion_minutos) * 60.0)))
        fin_ep = float(inicio_epoch) + dur_seg if inicio_epoch is not None else time.time()
        ini_ep = fin_ep - dur_seg
        tarifa = float(tarifa_hora_usd) if (tarifa_hora_usd is not None and float(tarifa_hora_usd) > 0) else _tarifa_default_cfg()

        lid_valid: int | None = None
        if lead_id is not None and self.db.escalar("SELECT 1 FROM leads WHERE id = ?", (int(lead_id),)):
            lid_valid = int(lead_id)

        sid = self.db.ejecutar(
            """
            INSERT INTO sesiones_tiempo (
                lead_id, proyecto_nombre, inicio_epoch, fin_epoch, duracion_seg,
                tarifa_hora_usd, facturable, notas
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lid_valid,
                str(proyecto_nombre or "Trabajo Freelance").strip()[:160],
                ini_ep,
                fin_ep,
                dur_seg,
                round(tarifa, 2),
                1 if facturable else 0,
                str(notas or "")[:400],
            ),
        )
        sesion = self.obtener_sesion(sid)
        assert sesion is not None
        self.bus.publicar(
            "tiempo.sesion.registrada",
            {"sesion_id": sid, "lead_id": lid_valid, "duracion_seg": dur_seg, "valor_usd": sesion["valor_devengado_usd"]},
            origen="time_tracker",
            nivel="info",
        )
        return sesion

    def actualizar_sesion(self, sesion_id: int, cambios: dict[str, Any]) -> dict[str, Any] | None:
        prev = self.db.consultar_uno("SELECT * FROM sesiones_tiempo WHERE id = ?", (int(sesion_id),))
        if not prev:
            return None
        proyecto = str(cambios.get("proyecto_nombre", prev["proyecto_nombre"])).strip()[:160] or str(prev["proyecto_nombre"])
        tarifa = max(0.0, float(cambios.get("tarifa_hora_usd", prev["tarifa_hora_usd"])))
        fact = 1 if bool(cambios.get("facturable", prev["facturable"])) else 0
        notas = str(cambios.get("notas", prev.get("notas") or ""))[:400]
        dur = int(prev["duracion_seg"] or 0)
        fin = prev.get("fin_epoch")
        if "duracion_minutos" in cambios and fin is not None:
            dur = max(60, int(round(float(cambios["duracion_minutos"]) * 60.0)))
            fin = float(prev["inicio_epoch"]) + dur

        self.db.ejecutar(
            "UPDATE sesiones_tiempo SET proyecto_nombre = ?, tarifa_hora_usd = ?, facturable = ?, notas = ?, duracion_seg = ?, fin_epoch = ? WHERE id = ?",
            (proyecto, round(tarifa, 2), fact, notas, dur, fin, int(sesion_id)),
        )
        return self.obtener_sesion(sesion_id)

    def eliminar_sesion(self, sesion_id: int) -> bool:
        return self.db.ejecutar("DELETE FROM sesiones_tiempo WHERE id = ?", (int(sesion_id),)) > 0

    def listar_sesiones(
        self,
        *,
        lead_id: int | None = None,
        solo_facturables: bool = False,
        dias: int = 30,
        limite: int = 100,
    ) -> list[dict[str, Any]]:
        where = ["1=1"]
        params: list[Any] = []
        if lead_id is not None:
            where.append("s.lead_id = ?")
            params.append(int(lead_id))
        if solo_facturables:
            where.append("s.facturable = 1")
        if dias > 0:
            corte = time.time() - (int(dias) * 86400)
            where.append("(s.inicio_epoch >= ? OR s.fin_epoch IS NULL)")
            params.append(corte)
        params.append(max(1, min(300, int(limite))))

        rows = self.db.consultar_todos(
            f"""
            SELECT s.*, COALESCE(l.titulo, '') AS lead_titulo
            FROM sesiones_tiempo s
            LEFT JOIN leads l ON l.id = s.lead_id
            WHERE {' AND '.join(where)}
            ORDER BY (s.fin_epoch IS NULL) DESC, s.inicio_epoch DESC
            LIMIT ?
            """,
            params,
        )
        ahora = time.time()
        return [SesionTiempo.from_row(r).to_dict(ahora) for r in rows]

    def calcular_rentabilidad_lead(self, lead_id: int, tarifa_objetivo_usd: float | None = None) -> dict[str, Any]:
        lid = int(lead_id)
        lead = self.db.consultar_uno("SELECT id, titulo, estado, presupuesto_num, ganancia_usd FROM leads WHERE id = ?", (lid,))
        sesiones = self.listar_sesiones(lead_id=lid, dias=3650, limite=200)
        tot_seg = sum(int(s["duracion_seg"]) for s in sesiones)
        fact_seg = sum(int(s["duracion_seg"]) for s in sesiones if s["facturable"])
        horas_tot = tot_seg / 3600.0
        horas_fact = fact_seg / 3600.0
        devengado = round(sum(float(s["valor_devengado_usd"]) for s in sesiones), 2)

        facturado_db = float(
            self.db.escalar(
                "SELECT COALESCE(SUM(monto_neto_usd), 0) FROM facturas_db WHERE lead_id = ? AND estado_pago = 'pagada'",
                (lid,), default=0.0,
            ) or 0.0
        )
        ganancia_lead = float(lead.get("ganancia_usd") or 0.0) if lead else 0.0
        ingreso_real = max(facturado_db, ganancia_lead)
        if ingreso_real <= 0 and lead:
            ingreso_estimado = float(lead.get("presupuesto_num") or 0.0)
        else:
            ingreso_estimado = ingreso_real

        tarifa_obj = float(tarifa_objetivo_usd) if tarifa_objetivo_usd else _tarifa_default_cfg()
        tarifa_eff = round(ingreso_estimado / horas_tot, 2) if horas_tot > 0.01 else 0.0
        ratio = (tarifa_eff / tarifa_obj) if (tarifa_obj > 0 and horas_tot > 0.01) else 0.0

        if horas_tot <= 0.01:
            veredicto = "sin_horas"
        elif ratio >= 1.25:
            veredicto = "excelente"
        elif ratio >= 0.90:
            veredicto = "saludable"
        elif ratio >= 0.60:
            veredicto = "ajustado"
        else:
            veredicto = "perdida"

        return {
            "lead_id": lid,
            "titulo": str(lead.get("titulo") or "") if lead else "",
            "sesiones_count": len(sesiones),
            "horas_totales": round(horas_tot, 2),
            "horas_facturables": round(horas_fact, 2),
            "formato_hms": formatear_hms(tot_seg),
            "devengado_tarifa_usd": devengado,
            "ingreso_real_usd": round(ingreso_real, 2),
            "ingreso_base_calculo_usd": round(ingreso_estimado, 2),
            "tarifa_objetivo_usd_hr": round(tarifa_obj, 2),
            "tarifa_efectiva_usd_hr": tarifa_eff,
            "veredicto": veredicto,
        }

    def resumen_productividad(self, dias: int = 30, trm_cop: float = 4200.0) -> dict[str, Any]:
        sesiones = self.listar_sesiones(dias=dias, limite=500)
        ahora = time.time()
        tot_seg = 0
        fact_seg = 0
        devengado_usd = 0.0
        por_proyecto: dict[str, dict[str, Any]] = {}
        por_dia: dict[str, float] = {}

        # Inicializar ultimos 14 dias en 0 para graficos continuos
        hoy = datetime.now(timezone.utc).date()
        for off in range(13, -1, -1):
            por_dia[(hoy - timedelta(days=off)).isoformat()] = 0.0

        for s in sesiones:
            dur = int(s["duracion_seg"])
            hrs = dur / 3600.0
            tot_seg += dur
            if s["facturable"]:
                fact_seg += dur
                devengado_usd += float(s["valor_devengado_usd"])

            pnom = s["proyecto_nombre"]
            if pnom not in por_proyecto:
                por_proyecto[pnom] = {"proyecto": pnom, "lead_id": s["lead_id"], "segundos": 0, "usd": 0.0, "sesiones": 0}
            por_proyecto[pnom]["segundos"] += dur
            por_proyecto[pnom]["usd"] += float(s["valor_devengado_usd"])
            por_proyecto[pnom]["sesiones"] += 1

            dia_k = datetime.fromtimestamp(float(s["inicio_epoch"]), tz=timezone.utc).date().isoformat()
            if dia_k in por_dia:
                por_dia[dia_k] = round(por_dia[dia_k] + hrs, 2)

        top_projs = sorted(por_proyecto.values(), key=lambda x: (x["usd"], x["segundos"]), reverse=True)[:8]
        for tp in top_projs:
            tp["horas"] = round(tp["segundos"] / 3600.0, 2)
            tp["formato_hms"] = formatear_hms(tp["segundos"])
            tp["usd"] = round(tp["usd"], 2)

        trm = max(1.0, float(trm_cop or 4200.0))
        return {
            "dias_ventana": int(dias),
            "sesion_activa": self.obtener_sesion_activa(),
            "total_sesiones": len(sesiones),
            "horas_totales": round(tot_seg / 3600.0, 2),
            "horas_facturables": round(fact_seg / 3600.0, 2),
            "formato_total_hms": formatear_hms(tot_seg),
            "pct_facturable": round((fact_seg / max(1, tot_seg)) * 100.0, 1) if tot_seg else 0.0,
            "valor_devengado_usd": round(devengado_usd, 2),
            "valor_devengado_cop": int(round(devengado_usd * trm)),
            "serie_14d": [[k, v] for k, v in por_dia.items()],
            "top_proyectos": top_projs,
            "ts_epoch": round(ahora, 2),
        }

    def exportar_timesheet_csv(self, lead_id: int | None = None, dias: int = 30) -> str:
        sesiones = self.listar_sesiones(lead_id=lead_id, dias=dias, limite=500)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["ID", "Fecha_UTC", "Lead_ID", "Proyecto", "Duracion_HMS", "Horas", "Tarifa_USD_Hr", "Facturable", "Valor_USD", "Notas"])
        for s in sesiones:
            w.writerow([
                s["id"], s["inicio_iso"], s["lead_id"] or "", s["proyecto_nombre"],
                s["formato_hms"], s["duracion_horas"], s["tarifa_hora_usd"],
                "SI" if s["facturable"] else "NO", s["valor_devengado_usd"], s["notas"],
            ])
        return "\ufeff" + buf.getvalue()


_TT_LOCK = threading.Lock()
_TT_SINGLETON: TitanTimeTracker | None = None


def obtener_time_tracker() -> TitanTimeTracker:
    global _TT_SINGLETON
    with _TT_LOCK:
        if _TT_SINGLETON is None:
            _TT_SINGLETON = TitanTimeTracker()
        return _TT_SINGLETON