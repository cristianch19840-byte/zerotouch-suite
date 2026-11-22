from __future__ import annotations

import functools
import json
import os
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, TypeVar

from titan_core.db_engine import ROOT_DIR, TitanDBEngine, obtener_db_engine
from titan_core.event_bus import TitanEventBus, obtener_event_bus

F = TypeVar("F", bound=Callable[..., Any])

LOGS_DIR = os.path.join(ROOT_DIR, "logs")
DEFAULT_LOG_FILE = os.path.join(LOGS_DIR, "titan.jsonl")


class RotatingJSONLLogger:
    """
    Logger estructurado en formato JSONL con rotacion automatica por tamano,
    buffer de lectura rapida en RAM y puente opcional hacia el EventBus.
    """

    def __init__(
        self,
        ruta_archivo: str = DEFAULT_LOG_FILE,
        max_bytes: int = 2_500_000,
        backups: int = 4,
        bus: TitanEventBus | None = None,
    ) -> None:
        self.ruta_archivo = os.path.abspath(ruta_archivo)
        self.max_bytes = max(32_768, int(max_bytes))
        self.backups = max(1, int(backups))
        self.bus = bus
        self._lock = threading.Lock()
        self._recientes: deque[dict[str, Any]] = deque(maxlen=250)
        os.makedirs(os.path.dirname(self.ruta_archivo), exist_ok=True)

    def _rotar_si_necesario(self) -> None:
        if not os.path.isfile(self.ruta_archivo):
            return
        if os.path.getsize(self.ruta_archivo) < self.max_bytes:
            return
        for idx in range(self.backups - 1, 0, -1):
            src = f"{self.ruta_archivo}.{idx}"
            dst = f"{self.ruta_archivo}.{idx + 1}"
            if os.path.exists(src):
                os.replace(src, dst)
        os.replace(self.ruta_archivo, f"{self.ruta_archivo}.1")

    def registrar(
        self,
        nivel: str,
        componente: str,
        mensaje: str,
        datos: dict[str, Any] | None = None,
        emitir_bus: bool = True,
    ) -> dict[str, Any]:
        nv = str(nivel or "info").lower()
        registro = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "hora": datetime.now().strftime("%H:%M:%S"),
            "nivel": nv,
            "componente": str(componente or "core"),
            "mensaje": str(mensaje or ""),
            "datos": datos or {},
        }
        linea = json.dumps(registro, ensure_ascii=False)
        with self._lock:
            self._recientes.append(registro)
            try:
                self._rotar_si_necesario()
                with open(self.ruta_archivo, "a", encoding="utf-8") as f:
                    f.write(linea + "\n")
            except OSError:
                pass

        if emitir_bus and self.bus is not None:
            self.bus.publicar(
                topico=f"log.{registro['componente'].lower()}",
                payload={"mensaje": registro["mensaje"], "datos": registro["datos"], "hora": registro["hora"]},
                origen=registro["componente"],
                nivel=nv,
            )
        return registro

    def info(self, comp: str, msg: str, **datos: Any) -> dict[str, Any]:
        return self.registrar("info", comp, msg, datos)

    def ok(self, comp: str, msg: str, **datos: Any) -> dict[str, Any]:
        return self.registrar("ok", comp, msg, datos)

    def warn(self, comp: str, msg: str, **datos: Any) -> dict[str, Any]:
        return self.registrar("warn", comp, msg, datos)

    def error(self, comp: str, msg: str, **datos: Any) -> dict[str, Any]:
        return self.registrar("error", comp, msg, datos)

    def recientes(self, limite: int = 80, nivel: str = "") -> list[dict[str, Any]]:
        nv = nivel.strip().lower()
        with self._lock:
            items = list(self._recientes)
        if nv:
            items = [x for x in items if x["nivel"] == nv]
        return items[-max(1, limite):]

    def recientes_texto(self, limite: int = 60) -> list[str]:
        return [f"[{r['hora']}] [{r['componente']}] {r['mensaje']}" for r in self.recientes(limite)]


def _percentil(ordenados: list[float], p: float) -> float:
    if not ordenados:
        return 0.0
    if len(ordenados) == 1:
        return ordenados[0]
    k = (len(ordenados) - 1) * (p / 100.0)
    f = int(k)
    c = min(len(ordenados) - 1, f + 1)
    if f == c:
        return ordenados[f]
    return ordenados[f] + (ordenados[c] - ordenados[f]) * (k - f)


class TitanTelemetry:
    """
    Registro de metricas de alto rendimiento:
    - Contadores monotonicos, gauges y ventanas deslizantes de latencia (p50/p95/p99)
    - Persistencia por lotes en SQLite (metricas_sistema)
    - Decorador @medir y context manager cronometro()
    """

    def __init__(
        self,
        db: TitanDBEngine | None = None,
        logger: RotatingJSONLLogger | None = None,
        ventana_latencias: int = 200,
    ) -> None:
        self.db = db
        self.logger = logger
        self._lock = threading.RLock()
        self._contadores: dict[str, float] = defaultdict(float)
        self._gauges: dict[str, float] = {}
        self._latencias: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=ventana_latencias))
        self._errores_op: dict[str, int] = defaultdict(int)
        self._buffer_db: list[tuple[Any, ...]] = []
        self._inicio_ts = time.time()

    def inc(self, nombre: str, valor: float = 1.0) -> float:
        with self._lock:
            self._contadores[nombre] += float(valor)
            return self._contadores[nombre]

    def set_gauge(self, nombre: str, valor: float) -> None:
        with self._lock:
            self._gauges[nombre] = float(valor)

    def registrar_latencia(
        self,
        componente: str,
        operacion: str,
        duracion_ms: float,
        exito: bool = True,
        meta: dict[str, Any] | None = None,
        persistir: bool = False,
    ) -> None:
        clave = f"{componente}.{operacion}"
        with self._lock:
            self._latencias[clave].append(float(duracion_ms))
            self._contadores[f"ops.{clave}"] += 1.0
            if not exito:
                self._errores_op[clave] += 1
            if persistir and self.db is not None:
                self._buffer_db.append((
                    time.time(),
                    componente[:60],
                    operacion[:80],
                    round(float(duracion_ms), 3),
                    1 if exito else 0,
                    json.dumps(meta or {}, ensure_ascii=False)[:400],
                ))
                if len(self._buffer_db) >= 30:
                    self.flush_db()

    @contextmanager
    def cronometro(
        self,
        componente: str,
        operacion: str,
        persistir: bool = False,
        meta: dict[str, Any] | None = None,
    ) -> Iterator[dict[str, Any]]:
        ctx_meta = dict(meta or {})
        t0 = time.perf_counter()
        exito = True
        try:
            yield ctx_meta
        except Exception as e:
            exito = False
            ctx_meta["error"] = str(e)[:160]
            raise
        finally:
            dur_ms = (time.perf_counter() - t0) * 1000.0
            self.registrar_latencia(componente, operacion, dur_ms, exito=exito, meta=ctx_meta, persistir=persistir)

    def medir(self, componente: str, operacion: str = "", persistir: bool = False) -> Callable[[F], F]:
        def _deco(fn: F) -> F:
            op_nom = operacion or fn.__name__

            @functools.wraps(fn)
            def _wrap(*args: Any, **kwargs: Any) -> Any:
                with self.cronometro(componente, op_nom, persistir=persistir):
                    return fn(*args, **kwargs)

            return _wrap  # type: ignore[return-value]

        return _deco

    def flush_db(self) -> int:
        if self.db is None:
            return 0
        with self._lock:
            if not self._buffer_db:
                return 0
            lote = list(self._buffer_db)
            self._buffer_db.clear()
        return self.db.ejecutar_lote(
            "INSERT INTO metricas_sistema (ts_epoch, componente, operacion, duracion_ms, exito, meta_json) VALUES (?, ?, ?, ?, ?, ?)",
            lote,
        )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            perfiles: dict[str, dict[str, Any]] = {}
            for clave, muestras in self._latencias.items():
                arr = sorted(muestras)
                perfiles[clave] = {
                    "n": len(arr),
                    "errores": self._errores_op.get(clave, 0),
                    "avg_ms": round(sum(arr) / max(1, len(arr)), 2),
                    "p50_ms": round(_percentil(arr, 50), 2),
                    "p95_ms": round(_percentil(arr, 95), 2),
                    "p99_ms": round(_percentil(arr, 99), 2),
                    "max_ms": round(arr[-1], 2) if arr else 0.0,
                }
            return {
                "uptime_seg": round(time.time() - self._inicio_ts, 1),
                "contadores": dict(self._contadores),
                "gauges": dict(self._gauges),
                "latencias": perfiles,
            }


_TEL_LOCK = threading.RLock()
_LOGGER_SINGLETON: RotatingJSONLLogger | None = None
_TEL_SINGLETON: TitanTelemetry | None = None


def obtener_logger() -> RotatingJSONLLogger:
    global _LOGGER_SINGLETON
    with _TEL_LOCK:
        if _LOGGER_SINGLETON is None:
            _LOGGER_SINGLETON = RotatingJSONLLogger(bus=obtener_event_bus())
        return _LOGGER_SINGLETON


def obtener_telemetry() -> TitanTelemetry:
    global _TEL_SINGLETON
    with _TEL_LOCK:
        if _TEL_SINGLETON is None:
            _TEL_SINGLETON = TitanTelemetry(db=obtener_db_engine(), logger=obtener_logger())
        return _TEL_SINGLETON