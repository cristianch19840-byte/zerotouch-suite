from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, Sequence

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_DB_PATH = os.path.join(ROOT_DIR, "estado_radar_v4.db")


@dataclass(frozen=True, slots=True)
class MigracionDB:
    version: int
    nombre: str
    aplicar: Callable[[sqlite3.Connection], None]


@dataclass(slots=True)
class EstadoSaludDB:
    ruta: str
    tamano_bytes: int
    wal_bytes: int
    version_esquema: int
    tablas: dict[str, int] = field(default_factory=dict)
    integridad_ok: bool = True
    detalle_integridad: str = "ok"
    journal_mode: str = "wal"
    foreign_keys: bool = True
    tiempo_check_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ruta": self.ruta,
            "tamano_kb": round(self.tamano_bytes / 1024.0, 2),
            "wal_kb": round(self.wal_bytes / 1024.0, 2),
            "version_esquema": self.version_esquema,
            "tablas": self.tablas,
            "integridad_ok": self.integridad_ok,
            "detalle_integridad": self.detalle_integridad,
            "journal_mode": self.journal_mode,
            "foreign_keys": self.foreign_keys,
            "tiempo_check_ms": round(self.tiempo_check_ms, 2),
        }


def _columnas_tabla(conn: sqlite3.Connection, tabla: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({tabla})").fetchall()}


def _asegurar_columna(conn: sqlite3.Connection, tabla: str, col: str, definicion: str) -> None:
    if col not in _columnas_tabla(conn, tabla):
        conn.execute(f"ALTER TABLE {tabla} ADD COLUMN {col} {definicion}")


# ==================== MIGRACIONES VERSIONADAS (v1 .. v6) ====================
def _mig_001_tablas_base(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS vistos (
            post_id TEXT PRIMARY KEY,
            titulo_norm TEXT DEFAULT '',
            titulo_palabras TEXT DEFAULT '',
            ts DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    _asegurar_columna(conn, "vistos", "titulo_norm", "TEXT DEFAULT ''")
    _asegurar_columna(conn, "vistos", "titulo_palabras", "TEXT DEFAULT ''")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha DATETIME DEFAULT CURRENT_TIMESTAMP,
            fuente TEXT,
            plataforma TEXT DEFAULT '',
            tipo_trabajo TEXT DEFAULT 'freelance',
            autor TEXT DEFAULT '',
            titulo TEXT,
            categoria TEXT,
            presupuesto TEXT,
            presupuesto_num REAL DEFAULT 0,
            score INTEGER,
            competencia TEXT DEFAULT '',
            confianza TEXT DEFAULT '',
            prioridad_tag TEXT DEFAULT '',
            link TEXT,
            estado TEXT DEFAULT 'nuevo',
            ganancia_usd REAL DEFAULT 0,
            notas TEXT DEFAULT '',
            followup_enviado INTEGER DEFAULT 0,
            contactado_ts DATETIME DEFAULT NULL
        )
        """
    )
    for col, df in (
        ("plataforma", "TEXT DEFAULT ''"),
        ("tipo_trabajo", "TEXT DEFAULT 'freelance'"),
        ("autor", "TEXT DEFAULT ''"),
        ("presupuesto_num", "REAL DEFAULT 0"),
        ("competencia", "TEXT DEFAULT ''"),
        ("confianza", "TEXT DEFAULT ''"),
        ("prioridad_tag", "TEXT DEFAULT ''"),
        ("notas", "TEXT DEFAULT ''"),
        ("followup_enviado", "INTEGER DEFAULT 0"),
        ("contactado_ts", "DATETIME DEFAULT NULL"),
        ("cliente_id", "INTEGER DEFAULT NULL"),
        ("aegis_score", "REAL DEFAULT 0"),
        ("aegis_riesgo", "REAL DEFAULT 0"),
        ("horas_estimadas", "TEXT DEFAULT ''"),
        ("tarifa_eff_usd", "REAL DEFAULT 0"),
        ("actualizado_ts", "DATETIME DEFAULT CURRENT_TIMESTAMP"),
    ):
        _asegurar_columna(conn, "leads", col, df)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_estado ON leads(estado)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_link ON leads(link)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_tipo ON leads(tipo_trabajo)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_cliente ON leads(cliente_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_score ON leads(score DESC, id DESC)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stats_diarias (
            fecha TEXT PRIMARY KEY,
            descartados_local INTEGER DEFAULT 0,
            evaluados_ia INTEGER DEFAULT 0,
            alertas_enviadas INTEGER DEFAULT 0,
            tokens_est_usados INTEGER DEFAULT 0,
            tokens_est_ahorrados INTEGER DEFAULT 0
        )
        """
    )
    _asegurar_columna(conn, "stats_diarias", "tokens_est_usados", "INTEGER DEFAULT 0")
    _asegurar_columna(conn, "stats_diarias", "tokens_est_ahorrados", "INTEGER DEFAULT 0")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS salud_fuentes (
            fuente TEXT PRIMARY KEY,
            clave_config TEXT DEFAULT '',
            ok INTEGER DEFAULT 1,
            modo TEXT DEFAULT '',
            bruto INTEGER DEFAULT 0,
            tech INTEGER DEFAULT 0,
            ultimo_error TEXT DEFAULT '',
            actualizado_ts DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _mig_002_crm_empresarial(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            handle TEXT DEFAULT '',
            plataforma_origen TEXT DEFAULT '',
            email TEXT DEFAULT '',
            canal_contacto TEXT DEFAULT '',
            pais TEXT DEFAULT '',
            reputacion_score REAL DEFAULT 50.0,
            total_facturado_usd REAL DEFAULT 0.0,
            proyectos_ganados INTEGER DEFAULT 0,
            es_recurrente INTEGER DEFAULT 0,
            notas TEXT DEFAULT '',
            creado_ts DATETIME DEFAULT CURRENT_TIMESTAMP,
            actualizado_ts DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_clientes_handle ON clientes(handle)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_clientes_plat ON clientes(plataforma_origen)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS propuestas_enviadas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER,
            cliente_id INTEGER,
            plataforma TEXT DEFAULT '',
            variante TEXT DEFAULT 'A',
            template_nombre TEXT DEFAULT '',
            precio_cotizado_usd REAL DEFAULT 0.0,
            texto_pitch TEXT NOT NULL,
            estado_respuesta TEXT DEFAULT 'enviada',
            enviada_ts DATETIME DEFAULT CURRENT_TIMESTAMP,
            respondida_ts DATETIME DEFAULT NULL,
            notas TEXT DEFAULT '',
            FOREIGN KEY(lead_id) REFERENCES leads(id) ON DELETE SET NULL,
            FOREIGN KEY(cliente_id) REFERENCES clientes(id) ON DELETE SET NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_prop_lead ON propuestas_enviadas(lead_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_prop_variante ON propuestas_enviadas(variante, estado_respuesta)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tareas_crm (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER,
            cliente_id INTEGER,
            titulo TEXT NOT NULL,
            descripcion TEXT DEFAULT '',
            prioridad TEXT DEFAULT 'media',
            estado TEXT DEFAULT 'pendiente',
            vence_ts DATETIME DEFAULT NULL,
            completada_ts DATETIME DEFAULT NULL,
            creado_ts DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(lead_id) REFERENCES leads(id) ON DELETE CASCADE,
            FOREIGN KEY(cliente_id) REFERENCES clientes(id) ON DELETE SET NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tareas_estado ON tareas_crm(estado, vence_ts)")


def _mig_003_finanzas_y_tiempo(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS facturas_db (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero TEXT UNIQUE NOT NULL,
            lead_id INTEGER,
            cliente_id INTEGER,
            cliente_nombre TEXT NOT NULL,
            concepto TEXT NOT NULL,
            modalidad TEXT DEFAULT 'Final Payment',
            pasarela TEXT DEFAULT 'binance',
            monto_bruto_usd REAL NOT NULL,
            comision_usd REAL DEFAULT 0.0,
            monto_neto_usd REAL NOT NULL,
            trm_cop REAL DEFAULT 4200.0,
            monto_neto_cop REAL DEFAULT 0.0,
            estado_pago TEXT DEFAULT 'emitida',
            ruta_html TEXT DEFAULT '',
            emitida_ts DATETIME DEFAULT CURRENT_TIMESTAMP,
            pagada_ts DATETIME DEFAULT NULL,
            notas TEXT DEFAULT '',
            FOREIGN KEY(lead_id) REFERENCES leads(id) ON DELETE SET NULL,
            FOREIGN KEY(cliente_id) REFERENCES clientes(id) ON DELETE SET NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_facturas_estado ON facturas_db(estado_pago, emitida_ts DESC)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sesiones_tiempo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER,
            proyecto_nombre TEXT NOT NULL,
            inicio_epoch REAL NOT NULL,
            fin_epoch REAL DEFAULT NULL,
            duracion_seg INTEGER DEFAULT 0,
            tarifa_hora_usd REAL DEFAULT 25.0,
            facturable INTEGER DEFAULT 1,
            notas TEXT DEFAULT '',
            FOREIGN KEY(lead_id) REFERENCES leads(id) ON DELETE SET NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tiempo_lead ON sesiones_tiempo(lead_id, inicio_epoch DESC)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS movimientos_caja (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL,
            categoria TEXT DEFAULT 'freelance',
            descripcion TEXT NOT NULL,
            monto_usd REAL NOT NULL,
            trm_cop REAL DEFAULT 4200.0,
            pasarela TEXT DEFAULT 'binance',
            factura_id INTEGER DEFAULT NULL,
            fecha_ts DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(factura_id) REFERENCES facturas_db(id) ON DELETE SET NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_caja_fecha ON movimientos_caja(fecha_ts DESC, tipo)")


def _mig_004_automatizacion_y_resiliencia(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reglas_automatizacion (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            activa INTEGER DEFAULT 1,
            evento_disparador TEXT NOT NULL,
            condiciones_json TEXT NOT NULL DEFAULT '[]',
            acciones_json TEXT NOT NULL DEFAULT '[]',
            cooldown_seg INTEGER DEFAULT 60,
            ejecuciones INTEGER DEFAULT 0,
            ultima_ejecucion_ts REAL DEFAULT 0,
            creado_ts DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reglas_evt ON reglas_automatizacion(evento_disparador, activa)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS circuit_breakers (
            dominio TEXT PRIMARY KEY,
            estado TEXT NOT NULL DEFAULT 'closed',
            fallos_consecutivos INTEGER DEFAULT 0,
            exitos_totales INTEGER DEFAULT 0,
            fallos_totales INTEGER DEFAULT 0,
            abierto_hasta_epoch REAL DEFAULT 0,
            ultimo_error TEXT DEFAULT '',
            latencia_ema_ms REAL DEFAULT 0,
            actualizado_ts REAL NOT NULL
        )
        """
    )


def _mig_005_cache_ia_y_telemetria(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_cache (
            clave_hash TEXT PRIMARY KEY,
            proveedor TEXT DEFAULT '',
            modelo TEXT DEFAULT '',
            prompt_preview TEXT DEFAULT '',
            respuesta TEXT NOT NULL,
            tokens_in INTEGER DEFAULT 0,
            tokens_out INTEGER DEFAULT 0,
            hits INTEGER DEFAULT 0,
            creado_epoch REAL NOT NULL,
            expira_epoch REAL NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_cache_exp ON ai_cache(expira_epoch)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_uso_diario (
            fecha TEXT NOT NULL,
            proveedor TEXT NOT NULL,
            modelo TEXT NOT NULL,
            llamadas INTEGER DEFAULT 0,
            cache_hits INTEGER DEFAULT 0,
            errores INTEGER DEFAULT 0,
            tokens_in INTEGER DEFAULT 0,
            tokens_out INTEGER DEFAULT 0,
            latencia_total_ms REAL DEFAULT 0,
            PRIMARY KEY (fecha, proveedor, modelo)
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS metricas_sistema (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_epoch REAL NOT NULL,
            componente TEXT NOT NULL,
            operacion TEXT NOT NULL,
            duracion_ms REAL DEFAULT 0,
            exito INTEGER DEFAULT 1,
            meta_json TEXT DEFAULT '{}'
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_met_ts ON metricas_sistema(ts_epoch DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_met_comp ON metricas_sistema(componente, operacion)")


def _mig_006_sandbox_y_templates(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sandbox_ejecuciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ruta_script TEXT NOT NULL,
            exit_code INTEGER NOT NULL,
            duracion_ms REAL DEFAULT 0,
            stdout_txt TEXT DEFAULT '',
            stderr_txt TEXT DEFAULT '',
            auto_reparado INTEGER DEFAULT 0,
            ts_epoch REAL NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sbx_ts ON sandbox_ejecuciones(ts_epoch DESC)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pitch_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            plataforma TEXT DEFAULT 'general',
            categoria TEXT DEFAULT 'Python',
            cuerpo TEXT NOT NULL,
            usos INTEGER DEFAULT 0,
            respuestas INTEGER DEFAULT 0,
            ganados INTEGER DEFAULT 0,
            creado_ts DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


MIGRACIONES_TITAN: tuple[MigracionDB, ...] = (
    MigracionDB(1, "tablas_base_compat_v15", _mig_001_tablas_base),
    MigracionDB(2, "crm_empresarial_clientes_propuestas_tareas", _mig_002_crm_empresarial),
    MigracionDB(3, "finanzas_facturas_tiempo_caja", _mig_003_finanzas_y_tiempo),
    MigracionDB(4, "automatizacion_workflows_circuit_breakers", _mig_004_automatizacion_y_resiliencia),
    MigracionDB(5, "cache_ia_uso_y_telemetria", _mig_005_cache_ia_y_telemetria),
    MigracionDB(6, "sandbox_y_pitch_templates", _mig_006_sandbox_y_templates),
)


# ==================== MOTOR SQLITE CON POOL THREAD-LOCAL Y REINTENTOS ====================
class TitanDBEngine:
    """
    Gestor centralizado SQLite WAL para TITAN-OS v16.0:
    - Conexiones thread-local reutilizables (cero overhead de reconexion)
    - Transacciones de escritura con BEGIN IMMEDIATE + backoff exponencial ante SQLITE_BUSY
    - Migraciones versionadas idempotentes (schema_migrations)
    - Backups atomicos con sqlite3.backup() + verificacion SHA-256
    """

    def __init__(self, db_path: str | None = None, timeout_seg: float = 20.0) -> None:
        self.db_path = os.path.abspath(db_path or DEFAULT_DB_PATH)
        self.timeout_seg = max(5.0, float(timeout_seg))
        self._local = threading.local()
        self._init_lock = threading.RLock()
        self._write_lock = threading.RLock()
        self._all_conns: set[sqlite3.Connection] = set()
        self._conns_lock = threading.Lock()
        self._migrado = False
        self._asegurar_migraciones()

    def _crear_conexion(self) -> sqlite3.Connection:
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        conn = sqlite3.connect(
            self.db_path,
            timeout=self.timeout_seg,
            isolation_level=None,  # autocommit explicito para controlar BEGIN IMMEDIATE
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute(f"PRAGMA busy_timeout={int(self.timeout_seg * 1000)};")
        conn.execute("PRAGMA temp_store=MEMORY;")
        conn.execute("PRAGMA cache_size=-16000;")
        with self._conns_lock:
            self._all_conns.add(conn)
        return conn

    def obtener_conexion(self) -> sqlite3.Connection:
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.execute("SELECT 1")
                return conn
            except sqlite3.Error:
                self._descartar_conexion_actual()
        conn = self._crear_conexion()
        self._local.conn = conn
        return conn

    def _descartar_conexion_actual(self) -> None:
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is not None:
            with self._conns_lock:
                self._all_conns.discard(conn)
            try:
                conn.close()
            except Exception:
                pass
            self._local.conn = None

    def _asegurar_migraciones(self) -> None:
        with self._init_lock:
            if self._migrado:
                return
            conn = self.obtener_conexion()
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    nombre TEXT NOT NULL,
                    aplicada_ts DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            aplicadas = {
                int(r[0]) for r in conn.execute("SELECT version FROM schema_migrations").fetchall()
            }
            for mig in MIGRACIONES_TITAN:
                if mig.version in aplicadas:
                    continue
                with self.transaccion() as tx:
                    mig.aplicar(tx)
                    tx.execute(
                        "INSERT OR IGNORE INTO schema_migrations (version, nombre) VALUES (?, ?)",
                        (mig.version, mig.nombre),
                    )
            self._migrado = True

    @contextmanager
    def lectura(self) -> Iterator[sqlite3.Connection]:
        conn = self.obtener_conexion()
        yield conn

    @contextmanager
    def transaccion(self, reintentos: int = 6) -> Iterator[sqlite3.Connection]:
        """Transaccion atomica BEGIN IMMEDIATE con reintento ante bloqueo concurrente."""
        with self._write_lock:
            conn = self.obtener_conexion()
            ya_en_tx = conn.in_transaction
            if not ya_en_tx:
                for intento in range(max(1, reintentos)):
                    try:
                        conn.execute("BEGIN IMMEDIATE")
                        break
                    except sqlite3.OperationalError as e:
                        if ("locked" in str(e).lower() or "busy" in str(e).lower()) and intento < reintentos - 1:
                            time.sleep(0.04 * (2 ** intento))
                            continue
                        raise
            try:
                yield conn
                if not ya_en_tx and conn.in_transaction:
                    conn.execute("COMMIT")
            except Exception:
                if not ya_en_tx and conn.in_transaction:
                    try:
                        conn.execute("ROLLBACK")
                    except Exception:
                        pass
                raise

    def consultar_todos(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self.lectura() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def consultar_uno(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        with self.lectura() as conn:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row is not None else None

    def escalar(self, sql: str, params: Sequence[Any] = (), default: Any = None) -> Any:
        with self.lectura() as conn:
            row = conn.execute(sql, params).fetchone()
            if row is None or row[0] is None:
                return default
            return row[0]

    def ejecutar(self, sql: str, params: Sequence[Any] = ()) -> int:
        with self.transaccion() as tx:
            cur = tx.execute(sql, params)
            return int(cur.lastrowid or cur.rowcount or 0)

    def ejecutar_lote(self, sql: str, seq_params: Sequence[Sequence[Any]]) -> int:
        if not seq_params:
            return 0
        with self.transaccion() as tx:
            cur = tx.executemany(sql, seq_params)
            return int(cur.rowcount or len(seq_params))

    def version_esquema(self) -> int:
        val = self.escalar("SELECT COALESCE(MAX(version), 0) FROM schema_migrations", default=0)
        return int(val or 0)

    def verificar_salud(self) -> EstadoSaludDB:
        t0 = time.perf_counter()
        with self.lectura() as conn:
            integ = conn.execute("PRAGMA quick_check").fetchone()
            integ_txt = str(integ[0]) if integ else "unknown"
            jmode = str(conn.execute("PRAGMA journal_mode").fetchone()[0])
            fks = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
            tablas_raw = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            conteos: dict[str, int] = {}
            for r in tablas_raw:
                tname = r[0]
                try:
                    conteos[tname] = int(conn.execute(f"SELECT COUNT(*) FROM \"{tname}\"").fetchone()[0])
                except sqlite3.Error:
                    conteos[tname] = -1

        wal_path = self.db_path + "-wal"
        tam = os.path.getsize(self.db_path) if os.path.isfile(self.db_path) else 0
        wal_tam = os.path.getsize(wal_path) if os.path.isfile(wal_path) else 0

        return EstadoSaludDB(
            ruta=self.db_path,
            tamano_bytes=tam,
            wal_bytes=wal_tam,
            version_esquema=self.version_esquema(),
            tablas=conteos,
            integridad_ok=(integ_txt.lower() == "ok"),
            detalle_integridad=integ_txt,
            journal_mode=jmode,
            foreign_keys=fks,
            tiempo_check_ms=(time.perf_counter() - t0) * 1000.0,
        )

    def optimizar(self) -> dict[str, Any]:
        t0 = time.perf_counter()
        with self._write_lock:
            conn = self.obtener_conexion()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            conn.execute("PRAGMA optimize;")
            conn.execute("ANALYZE;")
            # Poda automatica de metricas viejas (>14 dias) y cache IA expirada
            corte_met = time.time() - (14 * 86400)
            with self.transaccion() as tx:
                d_met = tx.execute("DELETE FROM metricas_sistema WHERE ts_epoch < ?", (corte_met,)).rowcount or 0
                d_ai = tx.execute("DELETE FROM ai_cache WHERE expira_epoch < ?", (time.time(),)).rowcount or 0
                d_vis = tx.execute(
                    "DELETE FROM vistos WHERE post_id NOT IN (SELECT post_id FROM vistos ORDER BY ts DESC LIMIT 15000)"
                ).rowcount or 0
        return {
            "ok": True,
            "metricas_podadas": int(d_met),
            "cache_ia_podada": int(d_ai),
            "vistos_podados": int(d_vis),
            "duracion_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def crear_backup_verificado(self, carpeta_destino: str | None = None, max_backups: int = 10) -> dict[str, Any]:
        bdir = carpeta_destino or os.path.join(ROOT_DIR, "backups")
        os.makedirs(bdir, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dst = os.path.join(bdir, f"titan_v16_{stamp}.db")

        with self._write_lock:
            src_conn = self.obtener_conexion()
            dst_conn = sqlite3.connect(dst)
            try:
                src_conn.backup(dst_conn, pages=256)
                chk = dst_conn.execute("PRAGMA quick_check").fetchone()
                ok_chk = bool(chk and str(chk[0]).lower() == "ok")
            finally:
                dst_conn.close()

        sha = hashlib.sha256()
        with open(dst, "rb") as f:
            while bloque := f.read(65536):
                sha.update(bloque)
        sha_hex = sha.hexdigest()

        meta_path = dst + ".meta.json"
        meta = {
            "archivo": os.path.basename(dst),
            "sha256": sha_hex,
            "bytes": os.path.getsize(dst),
            "integridad_ok": ok_chk,
            "version_esquema": self.version_esquema(),
            "creado_utc": datetime.now(timezone.utc).isoformat(),
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        # Rotacion limpia (borra db + .meta.json viejos)
        archivos = sorted(
            [os.path.join(bdir, f) for f in os.listdir(bdir) if f.endswith(".db")],
            key=os.path.getmtime,
        )
        while len(archivos) > max_backups:
            viejo = archivos.pop(0)
            for p_rm in (viejo, viejo + ".meta.json"):
                if os.path.exists(p_rm):
                    try:
                        os.remove(p_rm)
                    except OSError:
                        pass

        meta["ruta"] = dst
        return meta

    def cerrar_todo(self) -> None:
        with self._conns_lock:
            conns = list(self._all_conns)
            self._all_conns.clear()
        for c in conns:
            try:
                c.close()
            except Exception:
                pass
        self._local.conn = None


_ENGINE_LOCK = threading.Lock()
_ENGINE_SINGLETON: TitanDBEngine | None = None


def obtener_db_engine(db_path: str | None = None) -> TitanDBEngine:
    global _ENGINE_SINGLETON
    if db_path is not None:
        return TitanDBEngine(db_path=db_path)
    with _ENGINE_LOCK:
        if _ENGINE_SINGLETON is None:
            _ENGINE_SINGLETON = TitanDBEngine()
        return _ENGINE_SINGLETON