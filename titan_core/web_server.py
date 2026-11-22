from __future__ import annotations

import fnmatch
import hashlib
import json
import mimetypes
import os
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from titan_core.ai_router import obtener_ai_router
from titan_core.db_engine import ROOT_DIR, TitanDBEngine, obtener_db_engine
from titan_core.event_bus import EventoSistema, TitanEventBus, obtener_event_bus
from titan_core.http_shield import obtener_http_shield
from titan_core.telemetry import RotatingJSONLLogger, TitanTelemetry, obtener_logger, obtener_telemetry
from titan_core.web_router import (
    TitanRequest,
    TitanResponse,
    TitanRouter,
    error_response,
    json_response,
    middleware_auth_opcional,
    middleware_gzip,
    middleware_rate_guard,
    middleware_seguridad_y_cors,
    middleware_telemetria,
    parsear_path_y_query,
)


# ==================== SERVIDOR DE ARCHIVOS ESTATICOS SEGURO (ETAG + ANTI-TRAVERSAL) ====================
MIME_EXTRAS = {
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".webp": "image/webp",
    ".woff2": "font/woff2",
}


class StaticFileServer:
    """
    Sirve archivos estaticos de carpetas permitidas con:
    - Proteccion estricta anti path-traversal via realpath + commonpath
    - ETag debil (mtime + size) + HTTP 304 Not Modified
    - Compresion Gzip automatica en JS/CSS/HTML/SVG
    """

    def __init__(self, ui_dir: str | None = None) -> None:
        self.ui_dir = os.path.realpath(ui_dir or os.path.join(ROOT_DIR, "web_ui"))

    def resolver_archivo_seguro(self, base_dir: str, rel_path: str) -> str | None:
        base_real = os.path.realpath(base_dir)
        limpio = (rel_path or "").lstrip("/\\")
        if not limpio or "\x00" in limpio:
            return None
        candidato = os.path.realpath(os.path.join(base_real, limpio))
        try:
            if os.path.commonpath([base_real, candidato]) != base_real:
                return None
        except ValueError:
            return None
        if not os.path.isfile(candidato):
            return None
        return candidato

    def servir(self, req: TitanRequest, base_dir: str, rel_path: str, cache_control: str = "no-cache") -> TitanResponse:
        # Si detecta intentos explicitos de traversal, responder 403
        if ".." in rel_path or "\\" in rel_path:
            return error_response("Acceso denegado (path traversal)", status=403, codigo="forbidden_path")

        ruta = self.resolver_archivo_seguro(base_dir, rel_path)
        if ruta is None:
            return error_response(f"Archivo no encontrado: {rel_path}", status=404, codigo="file_not_found")

        try:
            st = os.stat(ruta)
            etag = f'W/"{st.st_size:x}-{int(st.st_mtime_ns):x}"'
            inm = req.header("if-none-match", "").strip()
            if inm and inm == etag:
                return TitanResponse(
                    status=304,
                    body=b"",
                    content_type="text/plain",
                    headers={"ETag": etag, "Cache-Control": cache_control},
                    compress_ok=False,
                )

            with open(ruta, "rb") as f:
                raw = f.read()

            ext = os.path.splitext(ruta)[1].lower()
            ctype = MIME_EXTRAS.get(ext) or mimetypes.guess_type(ruta)[0] or "application/octet-stream"
            comp_ok = ext in (".html", ".css", ".js", ".mjs", ".json", ".svg", ".txt", ".md")
            return TitanResponse(
                status=200,
                body=raw,
                content_type=ctype,
                headers={"ETag": etag, "Cache-Control": cache_control},
                compress_ok=comp_ok,
            )
        except OSError as e:
            return error_response(f"Error leyendo archivo: {e}", status=500, codigo="io_error")


# ==================== GESTOR DE STREAMING SSE CONECTADO A TITANEVENTBUS ====================
class SSEStreamManager:
    """
    Servidor Server-Sent Events (SSE) en tiempo real sobre TitanEventBus:
    - Reconexion sin perdida de eventos via Last-Event-ID o ?last_id=
    - Filtrado multi-topico (?topics=radar.*,crm.*,finanzas.*)
    - Heartbeats periodicos y cierre instantaneo al apagar el servidor
    """

    def __init__(self, bus: TitanEventBus, heartbeat_seg: float = 15.0) -> None:
        self.bus = bus
        self.heartbeat_seg = max(0.5, float(heartbeat_seg))
        self.shutdown_event = threading.Event()
        self._lock = threading.Lock()
        self._clientes_activos = 0
        self._total_conexiones = 0
        self._eventos_enviados = 0

    def detener_todos(self) -> None:
        self.shutdown_event.set()

    def estado(self) -> dict[str, Any]:
        with self._lock:
            return {
                "clientes_activos": self._clientes_activos,
                "total_conexiones": self._total_conexiones,
                "eventos_enviados": self._eventos_enviados,
                "heartbeat_seg": self.heartbeat_seg,
            }

    @staticmethod
    def _coincide_topicos(topico: str, patrones: list[str]) -> bool:
        if not patrones or "*" in patrones:
            return True
        return any(fnmatch.fnmatchcase(topico, p) for p in patrones)

    def atender_conexion(self, handler: BaseHTTPRequestHandler, req: TitanRequest) -> None:
        # Parsear Last-Event-ID (header estandar SSE o query param)
        desde_seq = req.qint("last_id", 0)
        if desde_seq <= 0:
            hdr_id = req.header("last-event-id", "").strip()
            if hdr_id.isdigit():
                desde_seq = int(hdr_id)

        topics_raw = req.qparam("topics", "*").strip()
        patrones = [p.strip().lower() for p in topics_raw.split(",") if p.strip()] or ["*"]
        max_eventos = req.qint("max_events", 0)  # Util para clientes puntuales o pruebas automatizadas

        # Enviar cabeceras SSE
        handler.close_connection = True
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
        handler.send_header("Cache-Control", "no-cache, no-transform")
        handler.send_header("Connection", "keep-alive")
        handler.send_header("X-Accel-Buffering", "no")
        handler.send_header("X-Titan-OS", "16.0")
        origin = req.header("origin", "")
        if origin.startswith(("http://127.0.0.1", "http://localhost")):
            handler.send_header("Access-Control-Allow-Origin", origin)
        handler.end_headers()

        stream = self.bus.abrir_stream("*", desde_seq=desde_seq)
        with self._lock:
            self._clientes_activos += 1
            self._total_conexiones += 1

        enviados_esta_conn = 0
        ultimo_hb = time.monotonic()

        try:
            # Frame inicial de bienvenida con retry hint y seq actual
            hello = {
                "status": "connected",
                "sub_id": stream.sub_id,
                "patrones": patrones,
                "seq_actual": self.bus.estadisticas().get("seq_actual", 0),
                "ts": round(time.time(), 3),
            }
            init_frame = f"retry: 3000\nevent: system.connected\ndata: {json.dumps(hello, ensure_ascii=False)}\n\n"
            handler.wfile.write(init_frame.encode("utf-8"))
            handler.wfile.flush()

            while not self.shutdown_event.is_set():
                try:
                    evt: EventoSistema = stream.cola.get(timeout=0.4)
                    if not self._coincide_topicos(evt.topico, patrones):
                        continue
                    frame = evt.to_sse().encode("utf-8")
                    handler.wfile.write(frame)
                    handler.wfile.flush()
                    enviados_esta_conn += 1
                    ultimo_hb = time.monotonic()
                    with self._lock:
                        self._eventos_enviados += 1
                    if max_eventos > 0 and enviados_esta_conn >= max_eventos:
                        break
                except queue.Empty:
                    ahora = time.monotonic()
                    if (ahora - ultimo_hb) >= self.heartbeat_seg:
                        hb = f": heartbeat {int(time.time())}\n\n".encode("utf-8")
                        handler.wfile.write(hb)
                        handler.wfile.flush()
                        ultimo_hb = ahora
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            self.bus.cerrar_stream(stream)
            with self._lock:
                self._clientes_activos = max(0, self._clientes_activos - 1)


# ==================== SERVIDOR WEB TITAN-OS v16 (REST + SSE + ESTATICOS + DIAGNOSTICO) ====================
class _TitanThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64


class TitanWebServer:
    """
    Servidor HTTP/REST/SSE empresarial de TITAN-OS v16.0:
    - Enrutador REST modular con parametros tipados y middlewares (Seguridad, CORS, Auth, Gzip, Telemetria)
    - Streaming SSE en tiempo real desde TitanEventBus con Last-Event-ID replay
    - Estaticos seguros (web_ui/) con ETag/304 y anti path-traversal
    - Endpoints base de observabilidad (/api/v2/health, /routes, /events/*, /system/*)
    - Gancho opcional 'fallback_handler' para coexistir con rutas legacy de dashboard_web.py
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        *,
        db: TitanDBEngine | None = None,
        bus: TitanEventBus | None = None,
        logger: RotatingJSONLLogger | None = None,
        telemetry: TitanTelemetry | None = None,
        ui_dir: str | None = None,
        api_token: str | None = None,
        heartbeat_sse_seg: float = 15.0,
        max_body_bytes: int = 4_194_304,
        fallback_handler: Callable[[TitanRequest], TitanResponse | None] | None = None,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.db = db or obtener_db_engine()
        self.bus = bus or obtener_event_bus()
        self.logger = logger or obtener_logger()
        self.telemetry = telemetry or obtener_telemetry()
        self.static = StaticFileServer(ui_dir=ui_dir)
        self.sse = SSEStreamManager(bus=self.bus, heartbeat_seg=heartbeat_sse_seg)
        self.max_body_bytes = max(65536, int(max_body_bytes))
        self.fallback_handler = fallback_handler
        self._token_override = api_token
        self._inicio_ts = time.time()

        self.router = TitanRouter()
        self._configurar_middlewares()
        self._registrar_rutas_sistema()

        self._httpd: _TitanThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def _obtener_api_token(self) -> str:
        if self._token_override is not None:
            return self._token_override
        return (os.getenv("TITAN_API_TOKEN") or "").strip()

    def _configurar_middlewares(self) -> None:
        self.router.use(middleware_seguridad_y_cors())
        self.router.use(middleware_telemetria(self.telemetry))
        self.router.use(middleware_rate_guard(max_reqs_por_min=480))
        self.router.use(
            middleware_auth_opcional(
                token_provider=self._obtener_api_token,
                rutas_publicas_prefijos=("/", "/ui/", "/api/v2/health"),
            )
        )
        self.router.use(middleware_gzip(min_bytes=1024, nivel=6))

    def _registrar_rutas_sistema(self) -> None:
        r = self.router

        # 1. Raiz y estaticos de Web UI
        @r.get("/", nombre="ui_index", resumen="Sirve web_ui/index.html", tags=("ui",))
        def _index(req: TitanRequest) -> TitanResponse:
            return self.static.servir(req, self.static.ui_dir, "index.html", cache_control="no-cache")

        @r.get("/ui/{filepath:path}", nombre="ui_static", resumen="Sirve archivos estaticos web_ui/", tags=("ui",))
        def _static_ui(req: TitanRequest) -> TitanResponse:
            fp = str(req.path_params.get("filepath") or "")
            return self.static.servir(req, self.static.ui_dir, fp, cache_control="no-cache")

        # 2. Salud integral TITAN-OS v16
        @r.get("/api/v2/health", nombre="system_health", resumen="Diagnostico de salud integral", tags=("system",))
        def _health(req: TitanRequest) -> dict[str, Any]:
            salud_db = self.db.verificar_salud().to_dict()
            bus_st = self.bus.estadisticas()
            sse_st = self.sse.estado()
            detallado = req.qbool("full", False)
            out: dict[str, Any] = {
                "ok": bool(salud_db.get("integridad_ok")),
                "version": "16.0.0-titan",
                "uptime_seg": round(time.time() - self._inicio_ts, 1),
                "auth_habilitada": bool(self._obtener_api_token()),
                "db": {
                    "integridad_ok": salud_db["integridad_ok"],
                    "version_esquema": salud_db["version_esquema"],
                    "tamano_kb": salud_db["tamano_kb"],
                    "tablas_count": len(salud_db["tablas"]),
                },
                "event_bus": bus_st,
                "sse": sse_st,
            }
            if detallado:
                out["db"]["tablas"] = salud_db["tablas"]
                try:
                    out["http_shield"] = obtener_http_shield().estado_salud()
                except Exception:
                    out["http_shield"] = {}
                try:
                    out["ai_router"] = obtener_ai_router().estado_salud()
                except Exception:
                    out["ai_router"] = {}
                out["telemetry"] = self.telemetry.snapshot()
            return out

        # 3. Catalogo introspectivo de rutas REST
        @r.get("/api/v2/routes", nombre="system_routes", resumen="Lista todas las rutas REST registradas", tags=("system",))
        def _routes(req: TitanRequest) -> dict[str, Any]:
            rutas = self.router.listar_rutas()
            return {"ok": True, "total": len(rutas), "routes": rutas}

        # 4. Historial y emision de eventos EventBus
        @r.get("/api/v2/events/history", nombre="events_history", resumen="Historial reciente del EventBus", tags=("events",))
        def _evt_hist(req: TitanRequest) -> dict[str, Any]:
            patron = req.qparam("patron", "*")
            limite = max(1, min(300, req.qint("limit", 80)))
            desde = req.qint("since_seq", 0)
            evs = self.bus.historial(patron=patron, limite=limite, desde_seq=desde)
            return {
                "ok": True,
                "seq_actual": self.bus.estadisticas().get("seq_actual", 0),
                "count": len(evs),
                "events": [e.to_dict() for e in evs],
            }

        @r.post("/api/v2/events/emit", nombre="events_emit", resumen="Emite un evento al EventBus", tags=("events",))
        def _evt_emit(req: TitanRequest) -> dict[str, Any]:
            data = req.json_dict()
            topico = str(data.get("topico") or "").strip()
            if not topico:
                raise ValueError("El campo 'topico' es obligatorio")
            payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
            nivel = str(data.get("nivel") or "info")
            ev = self.bus.publicar(topico, payload, origen="api_v2", nivel=nivel)
            return {"ok": True, "event": ev.to_dict()}

        # 5. Logs estructurados y Telemetria p50/p95/p99
        @r.get("/api/v2/system/logs", nombre="system_logs", resumen="Logs estructurados JSONL recientes", tags=("system",))
        def _logs(req: TitanRequest) -> dict[str, Any]:
            lim = max(1, min(250, req.qint("limit", 80)))
            niv = req.qparam("nivel", "")
            return {"ok": True, "logs": self.logger.recientes(limite=lim, nivel=niv)}

        @r.get("/api/v2/system/telemetry", nombre="system_telemetry", resumen="Snapshot de telemetria del servidor", tags=("system",))
        def _tel(req: TitanRequest) -> dict[str, Any]:
            return {"ok": True, "telemetry": self.telemetry.snapshot(), "sse": self.sse.estado()}

        # 6. Mantenimiento DB (Optimizar + Backup SHA-256)
        @r.post("/api/v2/system/db/optimize", nombre="db_optimize", resumen="Ejecuta WAL checkpoint, ANALYZE y poda", tags=("system",))
        def _db_opt(req: TitanRequest) -> dict[str, Any]:
            res = self.db.optimizar()
            self.bus.publicar("system.db.optimized", res, origen="web_server", nivel="ok")
            return res

        @r.post("/api/v2/system/db/backup", nombre="db_backup", resumen="Crea backup atomico SQLite verificado SHA-256", tags=("system",))
        def _db_bkp(req: TitanRequest) -> dict[str, Any]:
            data = req.json_dict()
            max_b = max(2, min(50, int(data.get("max_backups") or 10)))
            meta = self.db.crear_backup_verificado(max_backups=max_b)
            self.bus.publicar("system.db.backup", {"archivo": meta.get("archivo"), "sha256": meta.get("sha256", "")[:16]}, origen="web_server", nivel="ok")
            return {"ok": True, "backup": meta}

    def _crear_handler_class(self) -> type[BaseHTTPRequestHandler]:
        servidor_ref = self

        class _TitanHTTPHandler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt: str, *args: Any) -> None:
                pass

            def _construir_request(self, method: str) -> tuple[TitanRequest | None, TitanResponse | None]:
                path, query = parsear_path_y_query(self.path)
                hdrs = {str(k).lower(): str(v) for k, v in self.headers.items()}
                cl_raw = hdrs.get("content-length", "0").strip()
                try:
                    cl = max(0, int(cl_raw)) if cl_raw else 0
                except ValueError:
                    cl = 0
                if cl > servidor_ref.max_body_bytes:
                    return None, error_response(
                        f"Payload excede el limite ({servidor_ref.max_body_bytes} bytes)",
                        status=413,
                        codigo="payload_too_large",
                    )
                body = self.rfile.read(cl) if cl > 0 else b""
                client_ip = str(self.client_address[0]) if self.client_address else "127.0.0.1"
                return (
                    TitanRequest(
                        method=method,
                        raw_path=self.path,
                        path=path,
                        query=query,
                        headers=hdrs,
                        client_ip=client_ip,
                        body=body,
                    ),
                    None,
                )

            def _enviar_respuesta(self, resp: TitanResponse, solo_head: bool = False) -> None:
                body = b"" if solo_head else (resp.body or b"")
                self.send_response(int(resp.status))
                self.send_header("Content-Type", resp.content_type)
                self.send_header("Content-Length", str(len(resp.body or b"")))
                self.send_header("Connection", "close")
                for k, v in resp.headers.items():
                    if k.lower() not in ("content-length", "content-type", "connection"):
                        self.send_header(k, v)
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def _manejar(self, method: str) -> None:
                req, err_resp = self._construir_request(method)
                if err_resp is not None or req is None:
                    self._enviar_respuesta(err_resp or error_response("Bad Request", 400))
                    return

                # Canal SSE dedicado (verificando auth opcional antes de abrir el stream)
                if method == "GET" and req.path == "/api/v2/events/stream":
                    tok_esp = servidor_ref._obtener_api_token()
                    if tok_esp:
                        cand = req.header("x-titan-token", "") or req.qparam("token", "")
                        auth_h = req.header("authorization", "")
                        if not cand and auth_h.lower().startswith("bearer "):
                            cand = auth_h[7:].strip()
                        import hmac as _hmac
                        if not (cand and _hmac.compare_digest(cand, tok_esp)):
                            self._enviar_respuesta(error_response("No autorizado para SSE", status=401, codigo="unauthorized"))
                            return
                    servidor_ref.sse.atender_conexion(self, req)
                    return

                resp = servidor_ref.router.despachar(req, fallback=servidor_ref.fallback_handler)
                self._enviar_respuesta(resp, solo_head=(method == "HEAD"))

            def do_GET(self) -> None:
                self._manejar("GET")

            def do_POST(self) -> None:
                self._manejar("POST")

            def do_PUT(self) -> None:
                self._manejar("PUT")

            def do_PATCH(self) -> None:
                self._manejar("PATCH")

            def do_DELETE(self) -> None:
                self._manejar("DELETE")

            def do_OPTIONS(self) -> None:
                self._manejar("OPTIONS")

            def do_HEAD(self) -> None:
                self._manejar("HEAD")

        return _TitanHTTPHandler

    def iniciar_en_hilo(self) -> tuple[str, int]:
        if self._httpd is not None:
            return self.host, self.port
        self.sse.shutdown_event.clear()
        handler_cls = self._crear_handler_class()
        self._httpd = _TitanThreadingHTTPServer((self.host, self.port), handler_cls)
        self.port = int(self._httpd.server_address[1])
        self._thread = threading.Thread(target=self._httpd.serve_forever, kwargs={"poll_interval": 0.25}, daemon=True)
        self._thread.start()
        self.logger.ok("web_server", f"TITAN Web Server v16 activo en http://{self.host}:{self.port}")
        return self.host, self.port

    def servir_bloqueante(self) -> None:
        self.sse.shutdown_event.clear()
        handler_cls = self._crear_handler_class()
        self._httpd = _TitanThreadingHTTPServer((self.host, self.port), handler_cls)
        self.port = int(self._httpd.server_address[1])
        self.logger.ok("web_server", f"TITAN Web Server v16 escuchando en http://{self.host}:{self.port}")
        try:
            self._httpd.serve_forever(poll_interval=0.25)
        finally:
            self.detener()

    def detener(self) -> None:
        self.sse.detener_todos()
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            self._thread = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"