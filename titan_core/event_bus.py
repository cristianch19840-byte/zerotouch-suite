from __future__ import annotations

import fnmatch
import json
import queue
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class EventoSistema:
    seq_id: int
    event_id: str
    topico: str
    origen: str
    nivel: str  # info | ok | warn | error | critico
    payload: dict[str, Any] = field(default_factory=dict)
    ts_epoch: float = field(default_factory=time.time)
    ts_iso: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq_id": self.seq_id,
            "event_id": self.event_id,
            "topico": self.topico,
            "origen": self.origen,
            "nivel": self.nivel,
            "payload": self.payload,
            "ts_epoch": round(self.ts_epoch, 3),
            "ts_iso": self.ts_iso,
        }

    def to_sse(self) -> str:
        data_json = json.dumps(self.to_dict(), ensure_ascii=False)
        return f"id: {self.seq_id}\nevent: {self.topico}\ndata: {data_json}\n\n"


@dataclass(slots=True)
class _SuscriptorCallback:
    sub_id: str
    patron: str
    callback: Callable[[EventoSistema], None]
    asincrono: bool = False
    errores: int = 0


@dataclass(slots=True)
class SuscripcionStream:
    sub_id: str
    patron: str
    cola: queue.Queue[EventoSistema]
    creado_ts: float = field(default_factory=time.time)
    descartados: int = 0


class TitanEventBus:
    """
    Bus de eventos thread-safe Pub/Sub con soporte nativo para:
    - Wildcards estilo glob ('radar.*', 'crm.lead.*', '*')
    - Ring buffer historico con replay desde last_event_id (para reconexiones SSE)
    - Colas acotadas no bloqueantes por cliente Web (protege RAM si un navegador se congela)
    - Dead-letter tracking de callbacks que lanzan excepciones
    """

    def __init__(self, historial_max: int = 600, max_cola_stream: int = 250) -> None:
        self._lock = threading.RLock()
        self._seq = 0
        self._historial: deque[EventoSistema] = deque(maxlen=max(50, historial_max))
        self._callbacks: dict[str, _SuscriptorCallback] = {}
        self._streams: dict[str, SuscripcionStream] = {}
        self._max_cola_stream = max(20, max_cola_stream)
        self._dead_letters: deque[dict[str, Any]] = deque(maxlen=100)
        self._stats: dict[str, int] = {
            "publicados": 0,
            "entregas_cb": 0,
            "entregas_stream": 0,
            "errores_cb": 0,
            "descartes_stream": 0,
        }

    def publicar(
        self,
        topico: str,
        payload: dict[str, Any] | None = None,
        origen: str = "sistema",
        nivel: str = "info",
    ) -> EventoSistema:
        topico_clean = str(topico or "sistema.log").strip().lower()
        with self._lock:
            self._seq += 1
            evt = EventoSistema(
                seq_id=self._seq,
                event_id=uuid.uuid4().hex[:12],
                topico=topico_clean,
                origen=str(origen or "sistema"),
                nivel=str(nivel or "info").lower(),
                payload=dict(payload or {}),
            )
            self._historial.append(evt)
            self._stats["publicados"] += 1

            cbs_match = [s for s in self._callbacks.values() if fnmatch.fnmatchcase(topico_clean, s.patron)]
            streams_match = [st for st in self._streams.values() if fnmatch.fnmatchcase(topico_clean, st.patron)]

        # Despacho a streams SSE (no bloqueante, descarta el mas viejo si la cola se llena)
        for st in streams_match:
            try:
                st.cola.put_nowait(evt)
                with self._lock:
                    self._stats["entregas_stream"] += 1
            except queue.Full:
                try:
                    st.cola.get_nowait()
                    st.cola.put_nowait(evt)
                except Exception:
                    pass
                st.descartados += 1
                with self._lock:
                    self._stats["descartes_stream"] += 1

        # Despacho a callbacks suscritos
        for sub in cbs_match:
            if sub.asincrono:
                threading.Thread(
                    target=self._invocar_callback_seguro,
                    args=(sub, evt),
                    daemon=True,
                ).start()
            else:
                self._invocar_callback_seguro(sub, evt)

        return evt

    def _invocar_callback_seguro(self, sub: _SuscriptorCallback, evt: EventoSistema) -> None:
        try:
            sub.callback(evt)
            with self._lock:
                self._stats["entregas_cb"] += 1
        except Exception as e:
            sub.errores += 1
            with self._lock:
                self._stats["errores_cb"] += 1
                self._dead_letters.append({
                    "ts": time.time(),
                    "sub_id": sub.sub_id,
                    "topico": evt.topico,
                    "error": str(e)[:200],
                })

    def suscribir(
        self,
        patron: str,
        callback: Callable[[EventoSistema], None],
        asincrono: bool = False,
    ) -> str:
        sub_id = f"cb_{uuid.uuid4().hex[:10]}"
        with self._lock:
            self._callbacks[sub_id] = _SuscriptorCallback(
                sub_id=sub_id,
                patron=str(patron or "*").strip().lower(),
                callback=callback,
                asincrono=asincrono,
            )
        return sub_id

    def desuscribir(self, sub_id: str) -> bool:
        with self._lock:
            if sub_id in self._callbacks:
                del self._callbacks[sub_id]
                return True
            if sub_id in self._streams:
                del self._streams[sub_id]
                return True
        return False

    def abrir_stream(self, patron: str = "*", desde_seq: int = 0) -> SuscripcionStream:
        sub_id = f"sse_{uuid.uuid4().hex[:10]}"
        pat = str(patron or "*").strip().lower()
        cola: queue.Queue[EventoSistema] = queue.Queue(maxsize=self._max_cola_stream)
        stream = SuscripcionStream(sub_id=sub_id, patron=pat, cola=cola)
        with self._lock:
            if desde_seq > 0:
                for ev in self._historial:
                    if ev.seq_id > desde_seq and fnmatch.fnmatchcase(ev.topico, pat):
                        try:
                            cola.put_nowait(ev)
                        except queue.Full:
                            break
            self._streams[sub_id] = stream
        return stream

    def cerrar_stream(self, stream_o_id: SuscripcionStream | str) -> None:
        sid = stream_o_id.sub_id if isinstance(stream_o_id, SuscripcionStream) else str(stream_o_id)
        self.desuscribir(sid)

    def historial(self, patron: str = "*", limite: int = 80, desde_seq: int = 0) -> list[EventoSistema]:
        pat = str(patron or "*").strip().lower()
        with self._lock:
            items = [
                ev for ev in self._historial
                if ev.seq_id > desde_seq and fnmatch.fnmatchcase(ev.topico, pat)
            ]
        return items[-max(1, limite):]

    def estadisticas(self) -> dict[str, Any]:
        with self._lock:
            return {
                **self._stats,
                "seq_actual": self._seq,
                "en_historial": len(self._historial),
                "callbacks_activos": len(self._callbacks),
                "streams_activos": len(self._streams),
                "dead_letters": len(self._dead_letters),
            }


_BUS_LOCK = threading.Lock()
_BUS_SINGLETON: TitanEventBus | None = None


def obtener_event_bus() -> TitanEventBus:
    global _BUS_SINGLETON
    with _BUS_LOCK:
        if _BUS_SINGLETON is None:
            _BUS_SINGLETON = TitanEventBus()
        return _BUS_SINGLETON