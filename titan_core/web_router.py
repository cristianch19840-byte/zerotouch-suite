from __future__ import annotations

import gzip
import hmac
import json
import mimetypes
import os
import re
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

from titan_core.telemetry import TitanTelemetry, obtener_telemetry


# ==================== CONTRATOS HTTP REQUEST / RESPONSE ====================
@dataclass(slots=True)
class TitanRequest:
    method: str
    raw_path: str
    path: str
    query: dict[str, list[str]] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    client_ip: str = "127.0.0.1"
    body: bytes = b""
    path_params: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
    received_ts: float = field(default_factory=time.perf_counter)
    _json_cache: Any = None
    _json_parsed: bool = False

    def header(self, nombre: str, default: str = "") -> str:
        return self.headers.get(nombre.lower(), default)

    def qparam(self, nombre: str, default: str = "") -> str:
        vals = self.query.get(nombre)
        if not vals:
            return default
        return str(vals[0])

    def qint(self, nombre: str, default: int = 0) -> int:
        raw = self.qparam(nombre, "")
        try:
            return int(raw) if raw != "" else default
        except ValueError:
            return default

    def qfloat(self, nombre: str, default: float = 0.0) -> float:
        raw = self.qparam(nombre, "")
        try:
            return float(raw) if raw != "" else default
        except ValueError:
            return default

    def qbool(self, nombre: str, default: bool = False) -> bool:
        raw = self.qparam(nombre, "").strip().lower()
        if not raw:
            return default
        return raw in ("1", "true", "yes", "si", "on")

    def json_body(self, default: Any = None) -> Any:
        if self._json_parsed:
            return self._json_cache if self._json_cache is not None else default
        self._json_parsed = True
        if not self.body:
            self._json_cache = None
            return default
        try:
            self._json_cache = json.loads(self.body.decode("utf-8", errors="replace"))
            return self._json_cache
        except Exception:
            self._json_cache = None
            return default

    def json_dict(self) -> dict[str, Any]:
        val = self.json_body(default={})
        return val if isinstance(val, dict) else {}

    def accepts_gzip(self) -> bool:
        return "gzip" in self.header("accept-encoding", "").lower()


@dataclass(slots=True)
class TitanResponse:
    status: int = 200
    body: bytes = b""
    content_type: str = "application/json; charset=utf-8"
    headers: dict[str, str] = field(default_factory=dict)
    compress_ok: bool = True
    is_stream: bool = False

    def set_header(self, k: str, v: str) -> TitanResponse:
        self.headers[str(k)] = str(v)
        return self


def json_response(data: Any, status: int = 200, headers: dict[str, str] | None = None) -> TitanResponse:
    raw = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    return TitanResponse(
        status=int(status),
        body=raw,
        content_type="application/json; charset=utf-8",
        headers=dict(headers or {}),
        compress_ok=True,
    )


def error_response(
    mensaje: str,
    status: int = 400,
    codigo: str = "bad_request",
    detalles: Any = None,
) -> TitanResponse:
    payload: dict[str, Any] = {
        "ok": False,
        "error": str(mensaje),
        "code": str(codigo),
        "status": int(status),
    }
    if detalles is not None:
        payload["detalles"] = detalles
    return json_response(payload, status=status)


def text_response(texto: str, status: int = 200, content_type: str = "text/plain; charset=utf-8", headers: dict[str, str] | None = None) -> TitanResponse:
    return TitanResponse(
        status=int(status),
        body=str(texto or "").encode("utf-8"),
        content_type=content_type,
        headers=dict(headers or {}),
        compress_ok=True,
    )


def html_response(html_str: str, status: int = 200, headers: dict[str, str] | None = None) -> TitanResponse:
    return text_response(html_str, status=status, content_type="text/html; charset=utf-8", headers=headers)


def bytes_response(
    raw: bytes,
    content_type: str = "application/octet-stream",
    status: int = 200,
    filename: str = "",
    compress_ok: bool = False,
    headers: dict[str, str] | None = None,
) -> TitanResponse:
    hdrs = dict(headers or {})
    if filename:
        safe_fn = re.sub(r'[^a-zA-Z0-9._\-]', "_", filename)
        hdrs["Content-Disposition"] = f'attachment; filename="{safe_fn}"'
    return TitanResponse(
        status=int(status),
        body=raw,
        content_type=content_type,
        headers=hdrs,
        compress_ok=compress_ok,
    )


# ==================== COMPILADOR DE RUTAS CON PARAMETROS TIPADOS ====================
# Soporta: /api/v2/leads/{id:int}, /api/v2/items/{slug}, /files/{path:path}
REGEX_SEGMENTO_PARAM = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)(?::([a-zA-Z]+))?\}")

TIPOS_PARAM: dict[str, tuple[str, Callable[[str], Any]]] = {
    "int": (r"\d+", int),
    "float": (r"\d+(?:\.\d+)?", float),
    "str": (r"[^/]+", str),
    "slug": (r"[a-zA-Z0-9_\-\.]+", str),
    "path": (r".+", str),
}

RouteHandler = Callable[[TitanRequest], TitanResponse | dict[str, Any] | list[Any] | str]
NextMiddleware = Callable[[TitanRequest], TitanResponse]
MiddlewareFn = Callable[[TitanRequest, NextMiddleware], TitanResponse]


@dataclass(slots=True)
class RutaCompilada:
    method: str
    patron_original: str
    regex: re.Pattern[str]
    conversores: dict[str, Callable[[str], Any]]
    handler: RouteHandler
    nombre: str = ""
    resumen: str = ""
    auth_requerida: bool = True
    tags: tuple[str, ...] = ()

    def match(self, path: str) -> dict[str, Any] | None:
        m = self.regex.fullmatch(path)
        if not m:
            return None
        params: dict[str, Any] = {}
        for k, v in m.groupdict().items():
            conv = self.conversores.get(k, str)
            try:
                params[k] = conv(unquote(v))
            except Exception:
                return None
        return params


def _compilar_ruta(patron: str) -> tuple[re.Pattern[str], dict[str, Callable[[str], Any]]]:
    p = "/" + patron.strip("/") if patron.strip("/") else "/"
    conversores: dict[str, Callable[[str], Any]] = {}
    partes_rx: list[str] = ["^"]
    pos = 0
    for m in REGEX_SEGMENTO_PARAM.finditer(p):
        if m.start() > pos:
            partes_rx.append(re.escape(p[pos:m.start()]))
        nombre = m.group(1)
        tipo = (m.group(2) or "str").lower()
        sub_rx, conv = TIPOS_PARAM.get(tipo, TIPOS_PARAM["str"])
        conversores[nombre] = conv
        partes_rx.append(f"(?P<{nombre}>{sub_rx})")
        pos = m.end()
    if pos < len(p):
        partes_rx.append(re.escape(p[pos:]))
    partes_rx.append("$")
    return re.compile("".join(partes_rx)), conversores


# ==================== MIDDLEWARES DE SEGURIDAD, CORS, AUTH, GZIP Y RATE-LIMIT ====================
COMPRESSIBLE_PREFIXES = (
    "application/json",
    "text/",
    "application/javascript",
    "image/svg+xml",
    "application/xml",
)


def middleware_seguridad_y_cors(
    *,
    cors_origins: tuple[str, ...] = ("http://127.0.0.1", "http://localhost"),
    csp_header: str = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "connect-src 'self' http://127.0.0.1:* http://localhost:*; "
        "frame-ancestors 'self';"
    ),
) -> MiddlewareFn:
    def _mw(req: TitanRequest, nxt: NextMiddleware) -> TitanResponse:
        origin = req.header("origin", "")
        origin_ok = bool(origin) and any(origin.startswith(p) for p in cors_origins)

        if req.method == "OPTIONS":
            resp = TitanResponse(status=204, body=b"", content_type="text/plain", compress_ok=False)
        else:
            resp = nxt(req)

        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("X-Titan-OS", "16.0")
        if resp.content_type.startswith("text/html"):
            resp.headers.setdefault("Content-Security-Policy", csp_header)

        if origin_ok:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Titan-Token, Last-Event-ID"
        return resp

    return _mw


def middleware_gzip(min_bytes: int = 1024, nivel: int = 6) -> MiddlewareFn:
    def _mw(req: TitanRequest, nxt: NextMiddleware) -> TitanResponse:
        resp = nxt(req)
        if (
            resp.is_stream
            or not resp.compress_ok
            or len(resp.body) < min_bytes
            or not req.accepts_gzip()
            or "Content-Encoding" in resp.headers
        ):
            return resp
        ct = resp.content_type.lower()
        if not any(ct.startswith(pref) for pref in COMPRESSIBLE_PREFIXES):
            return resp
        comprimido = gzip.compress(resp.body, compresslevel=nivel)
        if len(comprimido) < len(resp.body):
            resp.body = comprimido
            resp.headers["Content-Encoding"] = "gzip"
            vary_prev = resp.headers.get("Vary", "")
            if "Accept-Encoding" not in vary_prev:
                resp.headers["Vary"] = (f"{vary_prev}, Accept-Encoding").strip(", ")
        return resp

    return _mw


def middleware_auth_opcional(
    token_provider: Callable[[], str],
    rutas_publicas_prefijos: tuple[str, ...] = ("/", "/ui/", "/api/v2/health"),
) -> MiddlewareFn:
    """
    Si TITAN_API_TOKEN esta vacio, deja pasar todo en local (UX sin friccion).
    Si esta configurado, exige Authorization: Bearer <tok>, X-Titan-Token o ?token=<tok> en rutas protegidas.
    """
    def _es_publica(path: str) -> bool:
        if path == "/" or path == "/favicon.ico":
            return True
        for pref in rutas_publicas_prefijos:
            if pref != "/" and (path == pref or path.startswith(pref)):
                return True
        return False

    def _mw(req: TitanRequest, nxt: NextMiddleware) -> TitanResponse:
        esperado = (token_provider() or "").strip()
        if not esperado or req.method == "OPTIONS" or _es_publica(req.path):
            req.state["auth_ok"] = True
            return nxt(req)

        candidato = ""
        auth_hdr = req.header("authorization", "").strip()
        if auth_hdr.lower().startswith("bearer "):
            candidato = auth_hdr[7:].strip()
        if not candidato:
            candidato = req.header("x-titan-token", "").strip()
        if not candidato:
            candidato = req.qparam("token", "").strip()

        if candidato and hmac.compare_digest(candidato, esperado):
            req.state["auth_ok"] = True
            return nxt(req)

        return error_response(
            "No autorizado: envia 'Authorization: Bearer <TITAN_API_TOKEN>' o 'X-Titan-Token'",
            status=401,
            codigo="unauthorized",
        )

    return _mw


class _IPRateGuard:
    """Rate limiter ligero por IP para evitar bucles accidentales de la UI sobre endpoints API."""

    def __init__(self, max_reqs_por_min: int = 240) -> None:
        self.max_reqs = max(20, int(max_reqs_por_min))
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = {}

    def permitir(self, ip: str) -> tuple[bool, int]:
        ahora = time.monotonic()
        corte = ahora - 60.0
        with self._lock:
            lst = self._hits.get(ip)
            if lst is None:
                lst = []
                self._hits[ip] = lst
            # Limpiar ventana > 60s
            i = 0
            while i < len(lst) and lst[i] < corte:
                i += 1
            if i > 0:
                del lst[:i]
            if len(lst) >= self.max_reqs:
                return False, 0
            lst.append(ahora)
            return True, self.max_reqs - len(lst)


def middleware_rate_guard(max_reqs_por_min: int = 360) -> MiddlewareFn:
    guard = _IPRateGuard(max_reqs_por_min=max_reqs_por_min)

    def _mw(req: TitanRequest, nxt: NextMiddleware) -> TitanResponse:
        if not req.path.startswith("/api/"):
            return nxt(req)
        ok, restante = guard.permitir(req.client_ip)
        if not ok:
            resp = error_response("Demasiadas peticiones API por minuto", status=429, codigo="rate_limited")
            resp.set_header("Retry-After", "10")
            return resp
        resp = nxt(req)
        resp.headers.setdefault("X-RateLimit-Remaining", str(restante))
        return resp

    return _mw


def middleware_telemetria(telemetry: TitanTelemetry | None = None) -> MiddlewareFn:
    tel = telemetry or obtener_telemetry()

    def _mw(req: TitanRequest, nxt: NextMiddleware) -> TitanResponse:
        t0 = time.perf_counter()
        try:
            resp = nxt(req)
            dur = (time.perf_counter() - t0) * 1000.0
            resp.headers.setdefault("X-Response-Time-Ms", f"{dur:.2f}")
            op = f"{req.method}_{req.path.split('/')[2] if req.path.startswith('/api/') and len(req.path.split('/')) > 2 else 'web'}"
            tel.registrar_latencia("web", op, dur, exito=(resp.status < 500))
            return resp
        except Exception as e:
            dur = (time.perf_counter() - t0) * 1000.0
            tel.registrar_latencia("web", f"{req.method}_err", dur, exito=False)
            raise

    return _mw


# ==================== ROUTER REST MODULAR ====================
class TitanRouter:
    """
    Enrutador HTTP/REST de alto rendimiento sin dependencias externas:
    - Matching con parametros tipados ({id:int}, {slug}, {path:path})
    - Deteccion automatica de 405 Method Not Allowed con cabecera Allow
    - Soporte de sub-routers (mount) y cadena de middlewares
    - Introspeccion de catalogo de rutas para /api/v2/routes
    """

    def __init__(self, prefix: str = "") -> None:
        self.prefix = ("/" + prefix.strip("/")) if prefix.strip("/") else ""
        self._rutas: list[RutaCompilada] = []
        self._middlewares: list[MiddlewareFn] = []
        self._lock = threading.RLock()

    def use(self, mw: MiddlewareFn) -> None:
        with self._lock:
            self._middlewares.append(mw)

    def add_route(
        self,
        method: str,
        patron: str,
        handler: RouteHandler,
        *,
        nombre: str = "",
        resumen: str = "",
        auth_requerida: bool = True,
        tags: tuple[str, ...] = (),
    ) -> RutaCompilada:
        met = method.upper().strip()
        p_norm = "/" + patron.strip("/") if patron.strip("/") else "/"
        full_p = (self.prefix + ("" if p_norm == "/" and self.prefix else p_norm)) or "/"
        rx, conv = _compilar_ruta(full_p)
        rc = RutaCompilada(
            method=met,
            patron_original=full_p,
            regex=rx,
            conversores=conv,
            handler=handler,
            nombre=nombre or getattr(handler, "__name__", "handler"),
            resumen=resumen,
            auth_requerida=auth_requerida,
            tags=tags,
        )
        with self._lock:
            self._rutas.append(rc)
        return rc

    def route(
        self,
        patron: str,
        methods: tuple[str, ...] = ("GET",),
        **kwargs: Any,
    ) -> Callable[[RouteHandler], RouteHandler]:
        def _deco(fn: RouteHandler) -> RouteHandler:
            for m in methods:
                self.add_route(m, patron, fn, **kwargs)
            return fn

        return _deco

    def get(self, patron: str, **kwargs: Any) -> Callable[[RouteHandler], RouteHandler]:
        return self.route(patron, methods=("GET",), **kwargs)

    def post(self, patron: str, **kwargs: Any) -> Callable[[RouteHandler], RouteHandler]:
        return self.route(patron, methods=("POST",), **kwargs)

    def put(self, patron: str, **kwargs: Any) -> Callable[[RouteHandler], RouteHandler]:
        return self.route(patron, methods=("PUT",), **kwargs)

    def patch(self, patron: str, **kwargs: Any) -> Callable[[RouteHandler], RouteHandler]:
        return self.route(patron, methods=("PATCH",), **kwargs)

    def delete(self, patron: str, **kwargs: Any) -> Callable[[RouteHandler], RouteHandler]:
        return self.route(patron, methods=("DELETE",), **kwargs)

    def mount(self, sub_prefix: str, sub_router: TitanRouter) -> int:
        pref = "/" + sub_prefix.strip("/") if sub_prefix.strip("/") else ""
        n = 0
        for rc in sub_router._rutas:
            pat = pref + ("" if rc.patron_original == "/" and pref else rc.patron_original)
            self.add_route(
                rc.method,
                pat,
                rc.handler,
                nombre=rc.nombre,
                resumen=rc.resumen,
                auth_requerida=rc.auth_requerida,
                tags=rc.tags,
            )
            n += 1
        return n

    @staticmethod
    def _normalizar_resultado(res: Any) -> TitanResponse:
        if isinstance(res, TitanResponse):
            return res
        if isinstance(res, (dict, list)):
            return json_response(res)
        if isinstance(res, str):
            return text_response(res)
        if isinstance(res, bytes):
            return bytes_response(res)
        return json_response({"ok": True, "resultado": res})

    def resolver_ruta(self, method: str, path: str) -> tuple[RutaCompilada | None, dict[str, Any], list[str]]:
        met = method.upper()
        met_match = "GET" if met == "HEAD" else met
        metodos_permitidos: list[str] = []

        with self._lock:
            rutas = list(self._rutas)

        for rc in rutas:
            params = rc.match(path)
            if params is None:
                continue
            if rc.method == met_match:
                return rc, params, []
            if rc.method not in metodos_permitidos:
                metodos_permitidos.append(rc.method)

        return None, {}, sorted(metodos_permitidos)

    def despachar(
        self,
        req: TitanRequest,
        fallback: Callable[[TitanRequest], TitanResponse | None] | None = None,
    ) -> TitanResponse:
        def _nucleo(r: TitanRequest) -> TitanResponse:
            rc, params, permitidos = self.resolver_ruta(r.method, r.path)
            if rc is not None:
                r.path_params = params
                try:
                    return self._normalizar_resultado(rc.handler(r))
                except ValueError as ve:
                    return error_response(str(ve), status=400, codigo="validation_error")
                except KeyError as ke:
                    return error_response(f"Campo requerido faltante: {ke}", status=400, codigo="missing_field")
                except Exception as ex:
                    return error_response(
                        f"Error interno en {rc.nombre}: {ex}",
                        status=500,
                        codigo="internal_error",
                        detalles=traceback.format_exc(limit=3),
                    )
            if permitidos:
                resp = error_response(
                    f"Metodo {r.method} no permitido en {r.path}",
                    status=405,
                    codigo="method_not_allowed",
                    detalles={"allow": permitidos},
                )
                resp.set_header("Allow", ", ".join(permitidos))
                return resp

            if fallback is not None:
                fb = fallback(r)
                if fb is not None:
                    return fb

            return error_response(f"Ruta no encontrada: {r.path}", status=404, codigo="not_found")

        # Encadenar middlewares en orden FIFO
        with self._lock:
            mws = list(self._middlewares)

        cadena: NextMiddleware = _nucleo
        for mw in reversed(mws):
            prev = cadena
            cadena = lambda rq, m=mw, nx=prev: m(rq, nx)

        return cadena(req)

    def listar_rutas(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "method": rc.method,
                    "path": rc.patron_original,
                    "nombre": rc.nombre,
                    "resumen": rc.resumen,
                    "tags": list(rc.tags),
                }
                for rc in self._rutas
            ]


def parsear_path_y_query(raw_path: str) -> tuple[str, dict[str, list[str]]]:
    parsed = urlparse(raw_path)
    path = parsed.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    query = parse_qs(parsed.query, keep_blank_values=True)
    return path, query