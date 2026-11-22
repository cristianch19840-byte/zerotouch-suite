from __future__ import annotations

import hashlib
import json
import random
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlencode

import requests
from requests.adapters import HTTPAdapter

from titan_core.circuit_breaker import TitanCircuitBreakerManager, obtener_circuit_breaker
from titan_core.rate_limiter import TitanRateLimiter, extraer_dominio, obtener_rate_limiter
from titan_core.telemetry import TitanTelemetry, obtener_telemetry


# Perfiles realistas de navegadores modernos (rotacion coherente UA + Client Hints)
PERFILES_BROWSER: tuple[dict[str, str], ...] = (
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "Accept": "application/json, text/html, application/xhtml+xml, application/xml;q=0.9, */*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
        "Sec-CH-UA": '"Chromium";v="134", "Not:A-Brand";v="24", "Google Chrome";v="134"',
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"Windows"',
    },
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0",
        "Accept": "application/json, text/html, application/xhtml+xml, application/xml;q=0.9, */*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-CH-UA": '"Not(A:Brand";v="99", "Microsoft Edge";v="133", "Chromium";v="133"',
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"Windows"',
    },
    {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "Accept": "application/json, text/html, application/xhtml+xml, application/xml;q=0.9, */*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-CH-UA": '"Chromium";v="134", "Not:A-Brand";v="24", "Google Chrome";v="134"',
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"macOS"',
    },
    {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:135.0) Gecko/20100101 Firefox/135.0",
        "Accept": "application/json, text/html, application/xhtml+xml, application/xml;q=0.9, */*;q=0.8",
        "Accept-Language": "en-US,en;q=0.8",
    },
)

HEADERS_API_LIMPIA = {
    "User-Agent": "ZeroTouch-TITAN/16.0 (Automated Freelance Intelligence Suite)",
    "Accept": "application/json",
}

CODIGOS_REINTENTABLES = {408, 425, 429, 500, 502, 503, 504}
CODIGOS_CIRCUITO_FALLO = {429, 500, 502, 503, 504}


@dataclass(slots=True)
class RespuestaHTTP:
    ok: bool
    status_code: int
    url: str
    dominio: str
    texto: str = ""
    json_data: Any = None
    headers: dict[str, str] = field(default_factory=dict)
    latencia_ms: float = 0.0
    intentos: int = 1
    desde_cache: bool = False
    hit_304: bool = False
    bloqueado_circuito: bool = False
    error: str = ""

    def json_seguro(self) -> Any:
        if self.json_data is not None:
            return self.json_data
        if not self.texto:
            return None
        try:
            self.json_data = json.loads(self.texto)
            return self.json_data
        except Exception:
            return None


@dataclass(slots=True)
class _EntradaCacheHTTP:
    clave: str
    url: str
    status_code: int
    texto: str
    headers: dict[str, str]
    etag: str = ""
    last_modified: str = ""
    creado_epoch: float = 0.0
    expira_epoch: float = 0.0


class _CacheHTTPLRU:
    """Cache LRU acotada en RAM con soporte condicional ETag / Last-Modified (HTTP 304)."""

    def __init__(self, max_items: int = 320, max_bytes_item: int = 450_000) -> None:
        self._lock = threading.RLock()
        self._items: OrderedDict[str, _EntradaCacheHTTP] = OrderedDict()
        self._max_items = max(20, int(max_items))
        self._max_bytes_item = max(4096, int(max_bytes_item))
        self.hits_ttl = 0
        self.hits_304 = 0
        self.misses = 0

    def obtener(self, clave: str) -> tuple[_EntradaCacheHTTP | None, bool]:
        """Devuelve (entrada, vigente_por_ttl). Si no vigente pero tiene ETag/LM, sirve para revalidar 304."""
        with self._lock:
            ent = self._items.get(clave)
            if ent is None:
                self.misses += 1
                return None, False
            self._items.move_to_end(clave)
            ahora = time.time()
            if ent.expira_epoch > ahora:
                self.hits_ttl += 1
                return ent, True
            return ent, False

    def guardar(
        self,
        clave: str,
        url: str,
        status_code: int,
        texto: str,
        headers: dict[str, str],
        ttl_seg: float,
    ) -> None:
        if len(texto.encode("utf-8", errors="ignore")) > self._max_bytes_item:
            return
        etag = headers.get("ETag") or headers.get("etag") or ""
        lm = headers.get("Last-Modified") or headers.get("last-modified") or ""
        if ttl_seg <= 0.0 and not etag and not lm:
            return
        ahora = time.time()
        ent = _EntradaCacheHTTP(
            clave=clave,
            url=url,
            status_code=status_code,
            texto=texto,
            headers=dict(headers),
            etag=etag,
            last_modified=lm,
            creado_epoch=ahora,
            expira_epoch=ahora + max(0.0, float(ttl_seg)),
        )
        with self._lock:
            self._items[clave] = ent
            self._items.move_to_end(clave)
            while len(self._items) > self._max_items:
                self._items.popitem(last=False)

    def renovar_304(self, clave: str, ttl_seg: float, headers_nuevos: dict[str, str] | None = None) -> _EntradaCacheHTTP | None:
        with self._lock:
            ent = self._items.get(clave)
            if ent is None:
                return None
            self.hits_304 += 1
            ent.expira_epoch = time.time() + max(0.0, float(ttl_seg))
            if headers_nuevos:
                if headers_nuevos.get("ETag") or headers_nuevos.get("etag"):
                    ent.etag = headers_nuevos.get("ETag") or headers_nuevos.get("etag") or ent.etag
                if headers_nuevos.get("Last-Modified") or headers_nuevos.get("last-modified"):
                    ent.last_modified = headers_nuevos.get("Last-Modified") or headers_nuevos.get("last-modified") or ent.last_modified
            self._items.move_to_end(clave)
            return ent

    def limpiar(self) -> int:
        with self._lock:
            n = len(self._items)
            self._items.clear()
            return n

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "entradas": len(self._items),
                "hits_ttl": self.hits_ttl,
                "hits_304": self.hits_304,
                "misses": self.misses,
            }


def _parsear_retry_after(valor: str | None) -> float | None:
    if not valor:
        return None
    s = valor.strip()
    try:
        return max(0.2, min(120.0, float(s)))
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        diff = (dt - datetime.now(timezone.utc)).total_seconds()
        return max(0.5, min(120.0, diff))
    except Exception:
        return None


def _clave_cache_get(url: str, params: dict[str, Any] | None) -> str:
    base = url.strip()
    if params:
        p_norm = urlencode(sorted((str(k), str(v)) for k, v in params.items()))
        base = f"{base}?{p_norm}"
    return hashlib.blake2b(base.encode("utf-8", errors="ignore"), digest_size=16).hexdigest()


class TitanHTTPShield:
    """
    Cliente HTTP blindado para TITAN-OS v16.0:
    - Rate Limiter adaptativo por dominio (Token Bucket + Sliding Window 60s)
    - Circuit Breaker persistente de 3 estados por dominio
    - Rotacion coherente de perfiles Browser (User-Agent + Client Hints)
    - Cache condicional ETag / Last-Modified (HTTP 304 ahorra ancho de banda y cuota)
    - Backoff exponencial con decorrelated jitter y respeto estricto a Retry-After
    - Telemetria automatica p50/p95 por dominio
    """

    def __init__(
        self,
        rate_limiter: TitanRateLimiter | None = None,
        circuit_breaker: TitanCircuitBreakerManager | None = None,
        telemetry: TitanTelemetry | None = None,
        pool_size: int = 48,
        cache_max_items: int = 320,
    ) -> None:
        self.rate_limiter = rate_limiter or obtener_rate_limiter()
        self.circuit_breaker = circuit_breaker or obtener_circuit_breaker()
        self.telemetry = telemetry or obtener_telemetry()
        self._cache = _CacheHTTPLRU(max_items=cache_max_items)
        self._rot_lock = threading.Lock()
        self._rot_idx: dict[str, int] = {}
        self._session = requests.Session()
        adapter = HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size, max_retries=0)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    def _construir_headers(
        self,
        dominio: str,
        perfil: str = "browser",
        headers_extra: dict[str, str] | None = None,
    ) -> dict[str, str]:
        if perfil == "api":
            base = dict(HEADERS_API_LIMPIA)
        else:
            with self._rot_lock:
                idx = self._rot_idx.get(dominio, 0)
                self._rot_idx[dominio] = (idx + 1) % len(PERFILES_BROWSER)
            base = dict(PERFILES_BROWSER[idx])
        if headers_extra:
            base.update(headers_extra)
        return base

    def solicitar(
        self,
        metodo: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        json_body: Any = None,
        data: Any = None,
        auth: Any = None,
        timeout: float = 12.0,
        reintentos: int = 2,
        backoff_base_seg: float = 0.65,
        perfil_headers: str = "browser",
        cache_ttl_seg: float = 0.0,
        usar_etag: bool = True,
        usar_rate_limit: bool = True,
        usar_circuit_breaker: bool = True,
        abrir_circuito_en_403: bool = False,
        allow_redirects: bool = True,
    ) -> RespuestaHTTP:
        met = (metodo or "GET").upper()
        dom = extraer_dominio(url)
        es_get = (met == "GET")
        clave_cache = _clave_cache_get(url, params) if es_get else ""

        # 1. Revisar cache en RAM (TTL vigente o entrada stale con ETag/Last-Modified)
        ent_cache: _EntradaCacheHTTP | None = None
        if es_get and (cache_ttl_seg > 0.0 or usar_etag):
            ent_cache, vigente = self._cache.obtener(clave_cache)
            if ent_cache is not None and vigente:
                return RespuestaHTTP(
                    ok=True,
                    status_code=ent_cache.status_code,
                    url=ent_cache.url,
                    dominio=dom,
                    texto=ent_cache.texto,
                    headers=dict(ent_cache.headers),
                    latencia_ms=0.05,
                    intentos=0,
                    desde_cache=True,
                    hit_304=False,
                )

        # 2. Verificar Circuit Breaker antes de gastar tiempo/red
        if usar_circuit_breaker:
            permitido, motivo_cb = self.circuit_breaker.permitir(dom)
            if not permitido:
                self.telemetry.inc(f"http.cb_blocked.{dom}")
                return RespuestaHTTP(
                    ok=False,
                    status_code=0,
                    url=url,
                    dominio=dom,
                    bloqueado_circuito=True,
                    error=motivo_cb,
                    intentos=0,
                )

        # 3. Preparar cabeceras con rotacion anti-fingerprint + condicionales ETag/LM
        hdrs = self._construir_headers(dom, perfil=perfil_headers, headers_extra=headers)
        if es_get and usar_etag and ent_cache is not None:
            if ent_cache.etag:
                hdrs["If-None-Match"] = ent_cache.etag
            if ent_cache.last_modified:
                hdrs["If-Modified-Since"] = ent_cache.last_modified

        ultimo_err = ""
        ultimo_code = 0
        t_global = time.perf_counter()
        max_intentos = max(1, int(reintentos) + 1)

        for intento in range(1, max_intentos + 1):
            if usar_rate_limit:
                self.rate_limiter.adquirir(dom)

            t0 = time.perf_counter()
            try:
                r = self._session.request(
                    method=met,
                    url=url,
                    params=params,
                    headers=hdrs,
                    json=json_body,
                    data=data,
                    auth=auth,
                    timeout=timeout,
                    allow_redirects=allow_redirects,
                )
                lat_ms = (time.perf_counter() - t0) * 1000.0
                ultimo_code = int(r.status_code)
                r_headers = {str(k): str(v) for k, v in r.headers.items()}

                # 304 Not Modified -> recurso intacto, servimos desde cache sin bajar payload
                if ultimo_code == 304 and ent_cache is not None:
                    renovada = self._cache.renovar_304(clave_cache, max(cache_ttl_seg, 30.0), r_headers)
                    self.rate_limiter.reportar_exito(dom)
                    if usar_circuit_breaker:
                        self.circuit_breaker.registrar_exito(dom, lat_ms)
                    self.telemetry.registrar_latencia("http", dom, lat_ms, exito=True)
                    return RespuestaHTTP(
                        ok=True,
                        status_code=200,
                        url=renovada.url if renovada else url,
                        dominio=dom,
                        texto=renovada.texto if renovada else ent_cache.texto,
                        headers=dict(renovada.headers if renovada else ent_cache.headers),
                        latencia_ms=round(lat_ms, 2),
                        intentos=intento,
                        desde_cache=True,
                        hit_304=True,
                    )

                # 2xx Exito real
                if 200 <= ultimo_code < 300:
                    texto_resp = r.text
                    if es_get and (cache_ttl_seg > 0.0 or usar_etag):
                        self._cache.guardar(clave_cache, r.url or url, ultimo_code, texto_resp, r_headers, cache_ttl_seg)
                    self.rate_limiter.reportar_exito(dom)
                    if usar_circuit_breaker:
                        self.circuit_breaker.registrar_exito(dom, lat_ms)
                    self.telemetry.registrar_latencia("http", dom, lat_ms, exito=True)
                    return RespuestaHTTP(
                        ok=True,
                        status_code=ultimo_code,
                        url=r.url or url,
                        dominio=dom,
                        texto=texto_resp,
                        headers=r_headers,
                        latencia_ms=round(lat_ms, 2),
                        intentos=intento,
                    )

                # 429 Too Many Requests -> throttle adaptativo + Retry-After
                if ultimo_code == 429:
                    ra = _parsear_retry_after(r_headers.get("Retry-After") or r_headers.get("retry-after"))
                    pausa = self.rate_limiter.reportar_throttling(dom, retry_after_seg=ra)
                    ultimo_err = f"HTTP 429 (throttled {pausa}s)"
                    if intento < max_intentos:
                        time.sleep(min(pausa, 8.0))
                        continue
                    if usar_circuit_breaker:
                        self.circuit_breaker.registrar_fallo(dom, ultimo_err, peso_fallo=1)
                    self.telemetry.registrar_latencia("http", dom, lat_ms, exito=False)
                    return RespuestaHTTP(
                        ok=False, status_code=429, url=r.url or url, dominio=dom,
                        texto=r.text[:600], headers=r_headers, latencia_ms=round(lat_ms, 2),
                        intentos=intento, error=ultimo_err,
                    )

                # 403 Forbidden (opcionalmente abre circuito si el llamador lo pide, ej. Reddit directo)
                if ultimo_code == 403:
                    ultimo_err = "HTTP 403 Forbidden"
                    if usar_circuit_breaker and abrir_circuito_en_403:
                        self.circuit_breaker.registrar_fallo(dom, ultimo_err, forzar_apertura=True)
                    self.telemetry.registrar_latencia("http", dom, lat_ms, exito=False)
                    return RespuestaHTTP(
                        ok=False, status_code=403, url=r.url or url, dominio=dom,
                        texto=r.text[:600], headers=r_headers, latencia_ms=round(lat_ms, 2),
                        intentos=intento, error=ultimo_err,
                    )

                # 5xx u otros reintentables
                ultimo_err = f"HTTP {ultimo_code}"
                if ultimo_code in CODIGOS_REINTENTABLES and intento < max_intentos:
                    espera = min(12.0, backoff_base_seg * (2 ** (intento - 1)) * random.uniform(0.75, 1.35))
                    time.sleep(espera)
                    continue

                if usar_circuit_breaker and ultimo_code in CODIGOS_CIRCUITO_FALLO:
                    self.circuit_breaker.registrar_fallo(dom, ultimo_err, peso_fallo=1)
                self.telemetry.registrar_latencia("http", dom, lat_ms, exito=False)
                return RespuestaHTTP(
                    ok=False, status_code=ultimo_code, url=r.url or url, dominio=dom,
                    texto=r.text[:600], headers=r_headers, latencia_ms=round(lat_ms, 2),
                    intentos=intento, error=ultimo_err,
                )

            except (requests.Timeout, requests.ConnectionError) as e:
                lat_ms = (time.perf_counter() - t0) * 1000.0
                ultimo_err = f"{type(e).__name__}: {str(e)[:120]}"
                if intento < max_intentos:
                    espera = min(10.0, backoff_base_seg * (2 ** (intento - 1)) * random.uniform(0.7, 1.3))
                    time.sleep(espera)
                    continue
                if usar_circuit_breaker:
                    self.circuit_breaker.registrar_fallo(dom, ultimo_err, peso_fallo=1)
                self.telemetry.registrar_latencia("http", dom, lat_ms, exito=False)
            except Exception as e:
                lat_ms = (time.perf_counter() - t0) * 1000.0
                ultimo_err = f"{type(e).__name__}: {str(e)[:120]}"
                if usar_circuit_breaker:
                    self.circuit_breaker.registrar_fallo(dom, ultimo_err, peso_fallo=1)
                self.telemetry.registrar_latencia("http", dom, lat_ms, exito=False)
                break

        return RespuestaHTTP(
            ok=False,
            status_code=ultimo_code,
            url=url,
            dominio=dom,
            latencia_ms=round((time.perf_counter() - t_global) * 1000.0, 2),
            intentos=max_intentos,
            error=ultimo_err or "Error HTTP desconocido",
        )

    def get(self, url: str, **kwargs: Any) -> RespuestaHTTP:
        return self.solicitar("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> RespuestaHTTP:
        return self.solicitar("POST", url, **kwargs)

    def get_json(self, url: str, **kwargs: Any) -> tuple[Any, RespuestaHTTP]:
        resp = self.solicitar("GET", url, **kwargs)
        data = resp.json_seguro() if resp.ok else None
        return data, resp

    def post_json(self, url: str, payload: Any, **kwargs: Any) -> tuple[Any, RespuestaHTTP]:
        resp = self.solicitar("POST", url, json_body=payload, **kwargs)
        data = resp.json_seguro() if resp.ok else None
        return data, resp

    def estado_salud(self) -> dict[str, Any]:
        return {
            "cache_http": self._cache.stats(),
            "circuit_breakers": self.circuit_breaker.resumen_todos(),
            "rate_limiters": self.rate_limiter.estadisticas(),
        }

    def limpiar_cache(self) -> int:
        return self._cache.limpiar()


_SHIELD_LOCK = threading.RLock()
_SHIELD_SINGLETON: TitanHTTPShield | None = None


def obtener_http_shield() -> TitanHTTPShield:
    global _SHIELD_SINGLETON
    with _SHIELD_LOCK:
        if _SHIELD_SINGLETON is None:
            _SHIELD_SINGLETON = TitanHTTPShield()
        return _SHIELD_SINGLETON