from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from modulo_a_radar_whop.motor_filtrado.modelos import ContextoFiltro, VeredictoFiltro


@dataclass(slots=True)
class _EntradaVeredicto:
    clave: str
    veredicto: VeredictoFiltro
    creado_epoch: float
    expira_epoch: float
    hits: int = 0


def construir_clave_veredicto(
    *,
    titulo: str,
    cuerpo: str,
    tags: str,
    flair: str,
    ctx: ContextoFiltro,
    firma_calibracion: str,
    firma_ml: str,
) -> str:
    h = hashlib.blake2b(digest_size=16)
    partes = (
        ctx.perfil_nombre,
        ctx.plataforma,
        ctx.fuente,
        f"{ctx.monto_api_usd:.2f}",
        f"{ctx.tarifa_minima_usd_hr:.1f}",
        f"{ctx.presupuesto_minimo_usd:.1f}",
        "1" if ctx.solo_freelance_corto else "0",
        "1" if ctx.es_busqueda_global else "0",
        ",".join(ctx.idiomas_permitidos),
        ",".join(sorted(ctx.palabras_blacklist_usuario)),
        ",".join(sorted(ctx.palabras_whitelist_usuario)),
        firma_calibracion,
        firma_ml,
        titulo.strip(),
        cuerpo.strip(),
        tags.strip(),
        flair.strip(),
    )
    for p in partes:
        h.update(str(p).encode("utf-8", errors="ignore"))
        h.update(b"\x1f")
    return h.hexdigest()


class CacheVeredictosAEGIS:
    """
    Cache LRU en RAM para veredictos de simulacion / re-evaluacion rapida (<0.05ms).
    Invalida automaticamente cuando cambian perfil, calibracion dinamica o modelo ML (por clave compuesta).
    """

    def __init__(self, max_items: int = 512, ttl_seg: float = 900.0) -> None:
        self._lock = threading.RLock()
        self._max_items = max(32, int(max_items))
        self._ttl_seg = max(10.0, float(ttl_seg))
        self._store: OrderedDict[str, _EntradaVeredicto] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def obtener(self, clave: str) -> VeredictoFiltro | None:
        ahora = time.time()
        with self._lock:
            ent = self._store.get(clave)
            if ent is None:
                self.misses += 1
                return None
            if ent.expira_epoch <= ahora:
                del self._store[clave]
                self.misses += 1
                return None
            ent.hits += 1
            self.hits += 1
            self._store.move_to_end(clave)
            return ent.veredicto

    def guardar(self, clave: str, veredicto: VeredictoFiltro, ttl_override: float | None = None) -> None:
        ahora = time.time()
        ttl = self._ttl_seg if ttl_override is None else max(5.0, float(ttl_override))
        ent = _EntradaVeredicto(clave=clave, veredicto=veredicto, creado_epoch=ahora, expira_epoch=ahora + ttl)
        with self._lock:
            self._store[clave] = ent
            self._store.move_to_end(clave)
            while len(self._store) > self._max_items:
                self._store.popitem(last=False)

    def limpiar(self) -> int:
        with self._lock:
            n = len(self._store)
            self._store.clear()
            return n

    def stats(self) -> dict[str, Any]:
        with self._lock:
            tot = self.hits + self.misses
            return {
                "entradas": len(self._store),
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate_pct": round((self.hits / max(1, tot)) * 100.0, 1) if tot else 0.0,
            }