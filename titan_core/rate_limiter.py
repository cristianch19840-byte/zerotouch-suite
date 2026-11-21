from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse


@dataclass(slots=True)
class PoliticaDominio:
    dominio: str
    tasa_por_seg: float = 4.0
    capacidad_rafaga: float = 6.0
    max_ventana_60s: int = 120
    pausa_min_seg: float = 0.08
    factor_penalizacion_429: float = 0.55
    factor_recuperacion: float = 1.06
    tasa_min_seg: float = 0.25


# Presets calibrados por plataforma (evitan 429/403 en las 12+ fuentes y APIs IA/TG)
POLITICAS_DEFECTO: dict[str, PoliticaDominio] = {
    "oauth.reddit.com": PoliticaDominio("oauth.reddit.com", tasa_por_seg=1.5, capacidad_rafaga=4.0, max_ventana_60s=55, pausa_min_seg=0.25),
    "www.reddit.com": PoliticaDominio("www.reddit.com", tasa_por_seg=0.8, capacidad_rafaga=2.0, max_ventana_60s=25, pausa_min_seg=0.45),
    "arctic-shift.photon-reddit.com": PoliticaDominio("arctic-shift.photon-reddit.com", tasa_por_seg=4.5, capacidad_rafaga=8.0, max_ventana_60s=160, pausa_min_seg=0.12),
    "api.pullpush.io": PoliticaDominio("api.pullpush.io", tasa_por_seg=2.5, capacidad_rafaga=5.0, max_ventana_60s=90, pausa_min_seg=0.20),
    "api.rss2json.com": PoliticaDominio("api.rss2json.com", tasa_por_seg=1.2, capacidad_rafaga=3.0, max_ventana_60s=35, pausa_min_seg=0.45),
    "www.freelancer.com": PoliticaDominio("www.freelancer.com", tasa_por_seg=2.5, capacidad_rafaga=5.0, max_ventana_60s=80, pausa_min_seg=0.25),
    "api.github.com": PoliticaDominio("api.github.com", tasa_por_seg=1.0, capacidad_rafaga=4.0, max_ventana_60s=28, pausa_min_seg=0.40),
    "hn.algolia.com": PoliticaDominio("hn.algolia.com", tasa_por_seg=5.0, capacidad_rafaga=10.0, max_ventana_60s=180, pausa_min_seg=0.10),
    "remoteok.com": PoliticaDominio("remoteok.com", tasa_por_seg=1.5, capacidad_rafaga=3.0, max_ventana_60s=40, pausa_min_seg=0.35),
    "weworkremotely.com": PoliticaDominio("weworkremotely.com", tasa_por_seg=2.0, capacidad_rafaga=4.0, max_ventana_60s=50, pausa_min_seg=0.30),
    "remotive.com": PoliticaDominio("remotive.com", tasa_por_seg=2.0, capacidad_rafaga=4.0, max_ventana_60s=50, pausa_min_seg=0.30),
    "jobicy.com": PoliticaDominio("jobicy.com", tasa_por_seg=2.0, capacidad_rafaga=4.0, max_ventana_60s=50, pausa_min_seg=0.30),
    "himalayas.app": PoliticaDominio("himalayas.app", tasa_por_seg=2.0, capacidad_rafaga=4.0, max_ventana_60s=50, pausa_min_seg=0.30),
    "www.workingnomads.com": PoliticaDominio("www.workingnomads.com", tasa_por_seg=2.0, capacidad_rafaga=4.0, max_ventana_60s=50, pausa_min_seg=0.30),
    "www.arbeitnow.com": PoliticaDominio("www.arbeitnow.com", tasa_por_seg=2.0, capacidad_rafaga=4.0, max_ventana_60s=50, pausa_min_seg=0.30),
    "generativelanguage.googleapis.com": PoliticaDominio("generativelanguage.googleapis.com", tasa_por_seg=1.8, capacidad_rafaga=4.0, max_ventana_60s=45, pausa_min_seg=0.25),
    "api.telegram.org": PoliticaDominio("api.telegram.org", tasa_por_seg=10.0, capacidad_rafaga=20.0, max_ventana_60s=240, pausa_min_seg=0.05),
}


@dataclass(slots=True)
class _EstadoCubeta:
    politica: PoliticaDominio
    tasa_actual: float
    tokens: float
    ultimo_relleno: float
    ultimo_hit: float = 0.0
    bloqueado_hasta: float = 0.0
    ventana_60s: deque[float] = field(default_factory=deque)
    total_permitidos: int = 0
    total_esperas: int = 0
    total_tiempo_espera_seg: float = 0.0
    total_throttles_429: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


def extraer_dominio(url_o_dominio: str) -> str:
    raw = (url_o_dominio or "").strip().lower()
    if not raw:
        return "default"
    if "://" in raw:
        host = urlparse(raw).netloc.lower()
    else:
        host = raw.split("/", 1)[0]
    return host.split(":", 1)[0] or "default"


class TitanRateLimiter:
    """
    Rate Limiter hibrido adaptativo por dominio:
    - Token Bucket (permite rafagas controladas + refill continuo)
    - Sliding Window de 60 segundos (respeta cuotas estrictas por minuto)
    - Pausa minima inter-peticion por dominio
    - AIMD adaptativo (Additive Increase / Multiplicative Decrease ante 429/503 + Retry-After)
    """

    def __init__(self, politicas_extra: dict[str, PoliticaDominio] | None = None) -> None:
        self._lock = threading.RLock()
        self._politicas: dict[str, PoliticaDominio] = dict(POLITICAS_DEFECTO)
        if politicas_extra:
            self._politicas.update(politicas_extra)
        self._cubetas: dict[str, _EstadoCubeta] = {}

    def configurar_dominio(self, politica: PoliticaDominio) -> None:
        dom = extraer_dominio(politica.dominio)
        with self._lock:
            self._politicas[dom] = politica
            if dom in self._cubetas:
                st = self._cubetas[dom]
                with st.lock:
                    st.politica = politica
                    st.tasa_actual = min(politica.tasa_por_seg, max(politica.tasa_min_seg, st.tasa_actual))
                    st.tokens = min(st.tokens, politica.capacidad_rafaga)

    def _obtener_cubeta(self, dominio: str) -> _EstadoCubeta:
        dom = extraer_dominio(dominio)
        with self._lock:
            st = self._cubetas.get(dom)
            if st is None:
                pol = self._politicas.get(dom) or PoliticaDominio(dominio=dom)
                ahora = time.monotonic()
                st = _EstadoCubeta(
                    politica=pol,
                    tasa_actual=pol.tasa_por_seg,
                    tokens=pol.capacidad_rafaga,
                    ultimo_relleno=ahora,
                )
                self._cubetas[dom] = st
            return st

    def adquirir(
        self,
        url_o_dominio: str,
        costo: float = 1.0,
        pausa_min_override: float | None = None,
        max_espera_seg: float = 25.0,
    ) -> float:
        """
        Bloquea el hilo el tiempo minimo necesario hasta disponer de cuota.
        Devuelve los segundos totales esperados (0.0 si paso de inmediato).
        """
        st = self._obtener_cubeta(url_o_dominio)
        costo = max(0.1, float(costo))
        t_inicio = time.monotonic()
        esperado_total = 0.0

        while True:
            espera_req = 0.0
            with st.lock:
                ahora = time.monotonic()
                pol = st.politica

                # 1. Rellenar tokens acumulados desde ultimo chequeo
                dt = max(0.0, ahora - st.ultimo_relleno)
                if dt > 0.0:
                    st.tokens = min(pol.capacidad_rafaga, st.tokens + dt * st.tasa_actual)
                    st.ultimo_relleno = ahora

                # 2. Limpiar timestamps viejos (>60s) de la ventana deslizante
                corte_60 = ahora - 60.0
                while st.ventana_60s and st.ventana_60s[0] < corte_60:
                    st.ventana_60s.popleft()

                # 3. Verificar bloqueo explicito por Retry-After
                if st.bloqueado_hasta > ahora:
                    espera_req = max(espera_req, st.bloqueado_hasta - ahora)

                # 4. Verificar pausa minima entre hits al mismo dominio
                pausa_min = pol.pausa_min_seg if pausa_min_override is None else max(0.0, float(pausa_min_override))
                if st.ultimo_hit > 0.0 and pausa_min > 0.0:
                    falta_min = pausa_min - (ahora - st.ultimo_hit)
                    if falta_min > 0.0:
                        espera_req = max(espera_req, falta_min)

                # 5. Verificar cuota de ventana deslizante 60s
                if len(st.ventana_60s) >= pol.max_ventana_60s:
                    espera_win = (st.ventana_60s[0] + 60.02) - ahora
                    if espera_win > 0.0:
                        espera_req = max(espera_req, espera_win)

                # 6. Verificar tokens en la cubeta
                if st.tokens < costo:
                    deficit = costo - st.tokens
                    espera_tok = deficit / max(0.05, st.tasa_actual)
                    espera_req = max(espera_req, espera_tok)

                # Si no hay espera pendiente, consumir cuota y salir
                if espera_req <= 0.001:
                    st.tokens = max(0.0, st.tokens - costo)
                    st.ultimo_hit = ahora
                    st.ventana_60s.append(ahora)
                    st.total_permitidos += 1
                    if esperado_total > 0.0:
                        st.total_esperas += 1
                        st.total_tiempo_espera_seg += esperado_total
                    return round(esperado_total, 4)

            # Control de tope maximo de espera para no congelar el radar
            transcurrido = time.monotonic() - t_inicio
            if transcurrido + espera_req > max_espera_seg:
                restante = max(0.0, max_espera_seg - transcurrido)
                if restante > 0.0:
                    time.sleep(restante)
                    esperado_total += restante
                with st.lock:
                    st.ultimo_hit = time.monotonic()
                    st.total_permitidos += 1
                    st.total_esperas += 1
                    st.total_tiempo_espera_seg += esperado_total
                return round(esperado_total, 4)

            dormir = min(espera_req, 2.0)
            time.sleep(dormir)
            esperado_total += dormir

    def intentar_adquirir(self, url_o_dominio: str, costo: float = 1.0) -> bool:
        """Version no bloqueante: devuelve True si habia cuota inmediata, False en caso contrario."""
        st = self._obtener_cubeta(url_o_dominio)
        with st.lock:
            ahora = time.monotonic()
            pol = st.politica
            dt = max(0.0, ahora - st.ultimo_relleno)
            if dt > 0.0:
                st.tokens = min(pol.capacidad_rafaga, st.tokens + dt * st.tasa_actual)
                st.ultimo_relleno = ahora
            corte_60 = ahora - 60.0
            while st.ventana_60s and st.ventana_60s[0] < corte_60:
                st.ventana_60s.popleft()
            if (
                st.bloqueado_hasta > ahora
                or len(st.ventana_60s) >= pol.max_ventana_60s
                or st.tokens < costo
                or (st.ultimo_hit > 0.0 and (ahora - st.ultimo_hit) < pol.pausa_min_seg)
            ):
                return False
            st.tokens -= costo
            st.ultimo_hit = ahora
            st.ventana_60s.append(ahora)
            st.total_permitidos += 1
            return True

    def reportar_exito(self, url_o_dominio: str) -> None:
        """Recuperacion aditiva gradual de la tasa si el dominio respondio limpio."""
        st = self._obtener_cubeta(url_o_dominio)
        with st.lock:
            pol = st.politica
            if st.tasa_actual < pol.tasa_por_seg:
                st.tasa_actual = min(pol.tasa_por_seg, st.tasa_actual * pol.factor_recuperacion)

    def reportar_throttling(self, url_o_dominio: str, retry_after_seg: float | None = None) -> float:
        """Reduccion multiplicativa inmediata ante HTTP 429 / 503 y respeto a Retry-After."""
        st = self._obtener_cubeta(url_o_dominio)
        with st.lock:
            pol = st.politica
            st.total_throttles_429 += 1
            st.tasa_actual = max(pol.tasa_min_seg, st.tasa_actual * pol.factor_penalizacion_429)
            st.tokens = 0.0
            pausa = float(retry_after_seg) if (retry_after_seg and retry_after_seg > 0) else min(15.0, 1.5 / max(0.2, st.tasa_actual))
            pausa = max(0.5, min(90.0, pausa))
            st.bloqueado_hasta = max(st.bloqueado_hasta, time.monotonic() + pausa)
            return round(pausa, 2)

    def estadisticas(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            items = list(self._cubetas.items())
        out: dict[str, dict[str, Any]] = {}
        ahora = time.monotonic()
        for dom, st in items:
            with st.lock:
                corte = ahora - 60.0
                activos_60 = sum(1 for ts in st.ventana_60s if ts >= corte)
                out[dom] = {
                    "tasa_actual_rps": round(st.tasa_actual, 2),
                    "tasa_base_rps": st.politica.tasa_por_seg,
                    "tokens_disp": round(st.tokens, 2),
                    "reqs_ultimos_60s": activos_60,
                    "max_60s": st.politica.max_ventana_60s,
                    "bloqueado_seg": round(max(0.0, st.bloqueado_hasta - ahora), 2),
                    "total_permitidos": st.total_permitidos,
                    "total_esperas": st.total_esperas,
                    "tiempo_espera_seg": round(st.total_tiempo_espera_seg, 2),
                    "throttles_429": st.total_throttles_429,
                }
        return out


_RL_LOCK = threading.Lock()
_RL_SINGLETON: TitanRateLimiter | None = None


def obtener_rate_limiter() -> TitanRateLimiter:
    global _RL_SINGLETON
    with _RL_LOCK:
        if _RL_SINGLETON is None:
            _RL_SINGLETON = TitanRateLimiter()
        return _RL_SINGLETON