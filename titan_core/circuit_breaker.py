from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from titan_core.db_engine import TitanDBEngine, obtener_db_engine
from titan_core.event_bus import TitanEventBus, obtener_event_bus
from titan_core.rate_limiter import extraer_dominio


class EstadoCircuito(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(slots=True)
class RegistroCircuito:
    dominio: str
    estado: EstadoCircuito = EstadoCircuito.CLOSED
    fallos_consecutivos: int = 0
    exitos_totales: int = 0
    fallos_totales: int = 0
    abierto_hasta_epoch: float = 0.0
    ultimo_error: str = ""
    latencia_ema_ms: float = 0.0
    actualizado_ts: float = 0.0
    probes_en_curso: int = 0
    exitos_half_open: int = 0

    def to_dict(self) -> dict[str, Any]:
        restante = max(0.0, self.abierto_hasta_epoch - time.time()) if self.estado == EstadoCircuito.OPEN else 0.0
        tot = self.exitos_totales + self.fallos_totales
        tasa_ok = round((self.exitos_totales / max(1, tot)) * 100.0, 1) if tot > 0 else 100.0
        return {
            "dominio": self.dominio,
            "estado": self.estado.value,
            "fallos_consecutivos": self.fallos_consecutivos,
            "exitos_totales": self.exitos_totales,
            "fallos_totales": self.fallos_totales,
            "tasa_exito_pct": tasa_ok,
            "cooldown_restante_seg": round(restante, 1),
            "ultimo_error": self.ultimo_error,
            "latencia_ema_ms": round(self.latencia_ema_ms, 1),
            "actualizado_ts": round(self.actualizado_ts, 2),
        }


class TitanCircuitBreakerManager:
    """
    Gestor de Circuit Breakers de 3 estados (CLOSED -> OPEN -> HALF_OPEN) por dominio:
    - Persistencia automatica en tabla SQLite 'circuit_breakers' (sobrevive reinicios)
    - Cooldown exponencial progresivo con jitter (evita tormenta de reconexiones)
    - Control estricto de sondas HALF_OPEN (solo 1 peticion de prueba a la vez)
    - Emision de eventos al EventBus en cada transicion de estado
    - Seguimiento EMA (Exponential Moving Average) de latencia por dominio
    """

    def __init__(
        self,
        db: TitanDBEngine | None = None,
        bus: TitanEventBus | None = None,
        umbral_fallos: int = 4,
        cooldown_base_seg: float = 45.0,
        cooldown_max_seg: float = 600.0,
        exitos_para_cerrar: int = 2,
        usar_sqlite: bool = True,
    ) -> None:
        self._lock = threading.RLock()
        self.usar_sqlite = usar_sqlite
        self.db = db if db is not None else (obtener_db_engine() if usar_sqlite else None)
        self.bus = bus if bus is not None else obtener_event_bus()
        self.umbral_fallos = max(1, int(umbral_fallos))
        self.cooldown_base_seg = max(0.05, float(cooldown_base_seg))
        self.cooldown_max_seg = max(self.cooldown_base_seg, float(cooldown_max_seg))
        self.exitos_para_cerrar = max(1, int(exitos_para_cerrar))
        self._circuitos: dict[str, RegistroCircuito] = {}

        if self.usar_sqlite and self.db is not None:
            self._cargar_desde_db()

    def _cargar_desde_db(self) -> None:
        if self.db is None:
            return
        try:
            rows = self.db.consultar_todos("SELECT * FROM circuit_breakers")
            with self._lock:
                for r in rows:
                    try:
                        est = EstadoCircuito(str(r.get("estado") or "closed"))
                    except ValueError:
                        est = EstadoCircuito.CLOSED
                    # Si estaba HALF_OPEN al apagarse, al reiniciar puede probar de nuevo
                    if est == EstadoCircuito.HALF_OPEN:
                        est = EstadoCircuito.CLOSED
                    reg = RegistroCircuito(
                        dominio=str(r["dominio"]),
                        estado=est,
                        fallos_consecutivos=int(r.get("fallos_consecutivos") or 0),
                        exitos_totales=int(r.get("exitos_totales") or 0),
                        fallos_totales=int(r.get("fallos_totales") or 0),
                        abierto_hasta_epoch=float(r.get("abierto_hasta_epoch") or 0.0),
                        ultimo_error=str(r.get("ultimo_error") or ""),
                        latencia_ema_ms=float(r.get("latencia_ema_ms") or 0.0),
                        actualizado_ts=float(r.get("actualizado_ts") or time.time()),
                    )
                    self._circuitos[reg.dominio] = reg
        except Exception:
            pass

    def _persistir(self, reg: RegistroCircuito) -> None:
        if not self.usar_sqlite or self.db is None:
            return
        try:
            self.db.ejecutar(
                """
                INSERT INTO circuit_breakers (
                    dominio, estado, fallos_consecutivos, exitos_totales, fallos_totales,
                    abierto_hasta_epoch, ultimo_error, latencia_ema_ms, actualizado_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dominio) DO UPDATE SET
                    estado = excluded.estado,
                    fallos_consecutivos = excluded.fallos_consecutivos,
                    exitos_totales = excluded.exitos_totales,
                    fallos_totales = excluded.fallos_totales,
                    abierto_hasta_epoch = excluded.abierto_hasta_epoch,
                    ultimo_error = excluded.ultimo_error,
                    latencia_ema_ms = excluded.latencia_ema_ms,
                    actualizado_ts = excluded.actualizado_ts
                """,
                (
                    reg.dominio,
                    reg.estado.value,
                    reg.fallos_consecutivos,
                    reg.exitos_totales,
                    reg.fallos_totales,
                    reg.abierto_hasta_epoch,
                    reg.ultimo_error[:200],
                    round(reg.latencia_ema_ms, 2),
                    reg.actualizado_ts,
                ),
            )
        except Exception:
            pass

    def _obtener_o_crear(self, url_o_dominio: str) -> RegistroCircuito:
        dom = extraer_dominio(url_o_dominio)
        reg = self._circuitos.get(dom)
        if reg is None:
            reg = RegistroCircuito(dominio=dom, actualizado_ts=time.time())
            self._circuitos[dom] = reg
        return reg

    def permitir(self, url_o_dominio: str) -> tuple[bool, str]:
        """
        Consulta si se puede emitir una peticion hacia el dominio.
        Si OPEN ya cumplio cooldown, promueve exactamente 1 sonda a HALF_OPEN.
        """
        evento_emitir: tuple[str, dict[str, Any], str] | None = None
        with self._lock:
            reg = self._obtener_o_crear(url_o_dominio)
            ahora = time.time()

            if reg.estado == EstadoCircuito.CLOSED:
                return True, "closed"

            if reg.estado == EstadoCircuito.OPEN:
                if ahora < reg.abierto_hasta_epoch:
                    rest = round(reg.abierto_hasta_epoch - ahora, 1)
                    return False, f"circuit_open ({rest}s restantes | {reg.ultimo_error[:60]})"
                # Cooldown vencido -> pasa a HALF_OPEN y deja pasar 1 sola sonda
                reg.estado = EstadoCircuito.HALF_OPEN
                reg.probes_en_curso = 1
                reg.exitos_half_open = 0
                reg.actualizado_ts = ahora
                self._persistir(reg)
                evento_emitir = ("http.circuit.half_open", {"dominio": reg.dominio}, "info")
                ok_res = (True, "half_open_probe")
            else:
                # Ya esta en HALF_OPEN: solo permite 1 sonda concurrente
                if reg.probes_en_curso == 0:
                    reg.probes_en_curso = 1
                    ok_res = (True, "half_open_probe")
                else:
                    ok_res = (False, "half_open_probe_busy")

        if evento_emitir and self.bus is not None:
            self.bus.publicar(evento_emitir[0], evento_emitir[1], origen="circuit_breaker", nivel=evento_emitir[2])
        return ok_res

    def registrar_exito(self, url_o_dominio: str, latencia_ms: float = 0.0) -> RegistroCircuito:
        evento_emitir: tuple[str, dict[str, Any], str] | None = None
        with self._lock:
            reg = self._obtener_o_crear(url_o_dominio)
            ahora = time.time()
            reg.exitos_totales += 1
            reg.fallos_consecutivos = 0
            reg.actualizado_ts = ahora
            if latencia_ms > 0.0:
                reg.latencia_ema_ms = latencia_ms if reg.latencia_ema_ms <= 0.0 else (0.25 * latencia_ms + 0.75 * reg.latencia_ema_ms)

            if reg.estado == EstadoCircuito.HALF_OPEN:
                reg.probes_en_curso = max(0, reg.probes_en_curso - 1)
                reg.exitos_half_open += 1
                if reg.exitos_half_open >= self.exitos_para_cerrar:
                    reg.estado = EstadoCircuito.CLOSED
                    reg.abierto_hasta_epoch = 0.0
                    reg.ultimo_error = ""
                    evento_emitir = (
                        "http.circuit.closed",
                        {"dominio": reg.dominio, "latencia_ema_ms": round(reg.latencia_ema_ms, 1)},
                        "ok",
                    )
            self._persistir(reg)

        if evento_emitir and self.bus is not None:
            self.bus.publicar(evento_emitir[0], evento_emitir[1], origen="circuit_breaker", nivel=evento_emitir[2])
        return reg

    def registrar_fallo(
        self,
        url_o_dominio: str,
        motivo: str = "error",
        peso_fallo: int = 1,
        forzar_apertura: bool = False,
    ) -> RegistroCircuito:
        evento_emitir: tuple[str, dict[str, Any], str] | None = None
        with self._lock:
            reg = self._obtener_o_crear(url_o_dominio)
            ahora = time.time()
            estado_prev = reg.estado
            reg.fallos_totales += 1
            reg.fallos_consecutivos += max(1, int(peso_fallo))
            reg.ultimo_error = str(motivo or "error")[:200]
            reg.actualizado_ts = ahora

            debe_abrir = forzar_apertura or estado_prev == EstadoCircuito.HALF_OPEN or reg.fallos_consecutivos >= self.umbral_fallos
            if debe_abrir:
                exponente = max(0, min(5, reg.fallos_consecutivos - self.umbral_fallos))
                cooldown = min(self.cooldown_max_seg, self.cooldown_base_seg * (1.7 ** exponente))
                jitter = random.uniform(0.85, 1.15)
                reg.estado = EstadoCircuito.OPEN
                reg.probes_en_curso = 0
                reg.exitos_half_open = 0
                reg.abierto_hasta_epoch = ahora + (cooldown * jitter)
                if estado_prev != EstadoCircuito.OPEN:
                    evento_emitir = (
                        "http.circuit.open",
                        {
                            "dominio": reg.dominio,
                            "cooldown_seg": round(cooldown * jitter, 1),
                            "fallos": reg.fallos_consecutivos,
                            "motivo": reg.ultimo_error,
                        },
                        "warn",
                    )
            self._persistir(reg)

        if evento_emitir and self.bus is not None:
            self.bus.publicar(evento_emitir[0], evento_emitir[1], origen="circuit_breaker", nivel=evento_emitir[2])
        return reg

    def reiniciar(self, url_o_dominio: str | None = None) -> int:
        with self._lock:
            objetivos = [self._obtener_o_crear(url_o_dominio)] if url_o_dominio else list(self._circuitos.values())
            for reg in objetivos:
                reg.estado = EstadoCircuito.CLOSED
                reg.fallos_consecutivos = 0
                reg.abierto_hasta_epoch = 0.0
                reg.probes_en_curso = 0
                reg.exitos_half_open = 0
                reg.ultimo_error = ""
                reg.actualizado_ts = time.time()
                self._persistir(reg)
            return len(objetivos)

    def estado_dominio(self, url_o_dominio: str) -> dict[str, Any]:
        with self._lock:
            return self._obtener_o_crear(url_o_dominio).to_dict()

    def resumen_todos(self) -> list[dict[str, Any]]:
        with self._lock:
            lista = [r.to_dict() for r in self._circuitos.values()]
        lista.sort(key=lambda x: (x["estado"] != "open", x["estado"] != "half_open", x["dominio"]))
        return lista


_CB_LOCK = threading.RLock()
_CB_SINGLETON: TitanCircuitBreakerManager | None = None


def obtener_circuit_breaker() -> TitanCircuitBreakerManager:
    global _CB_SINGLETON
    with _CB_LOCK:
        if _CB_SINGLETON is None:
            _CB_SINGLETON = TitanCircuitBreakerManager()
        return _CB_SINGLETON