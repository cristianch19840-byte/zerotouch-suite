from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from modulo_a_radar_whop.motor_filtrado.pipeline import PipelineAEGIS
from titan_core.ai_cache import TitanAICache
from titan_core.ai_router import TitanAIRouter
from titan_core.api_v2_crm import construir_router_crm_finanzas
from titan_core.api_v2_ops import construir_router_operaciones
from titan_core.circuit_breaker import TitanCircuitBreakerManager
from titan_core.code_autofix import SnapshotManager, TitanCodeAutoFixer
from titan_core.crm_clientes import ClienteService
from titan_core.crm_service import TitanCRMService
from titan_core.db_engine import TitanDBEngine, obtener_db_engine
from titan_core.event_bus import TitanEventBus, obtener_event_bus
from titan_core.finance_service import TitanFinanceService
from titan_core.http_shield import TitanHTTPShield
from titan_core.license_engine import TitanLicenseEngine
from titan_core.pitch_engine import TitanPitchEngine
from titan_core.product_factory import TitanProductFactory
from titan_core.rate_limiter import TitanRateLimiter
from titan_core.sandbox_runner import TitanSandboxRunner
from titan_core.telemetry import RotatingJSONLLogger, TitanTelemetry, obtener_logger, obtener_telemetry
from titan_core.time_tracker import TitanTimeTracker
from titan_core.web_router import TitanRequest, TitanResponse, TitanRouter
from titan_core.web_server import TitanWebServer
from titan_core.workflow_engine import TitanWorkflowEngine


@dataclass(slots=True)
class TitanServiceContainer:
    """Contenedor de inyeccion de dependencias con todos los servicios de TITAN-OS v16.0."""
    db: TitanDBEngine
    bus: TitanEventBus
    logger: RotatingJSONLLogger
    telemetry: TitanTelemetry
    rate_limiter: TitanRateLimiter
    circuit_breaker: TitanCircuitBreakerManager
    http_shield: TitanHTTPShield
    ai_router: TitanAIRouter
    workflows: TitanWorkflowEngine
    clientes: ClienteService
    crm: TitanCRMService
    time_tracker: TitanTimeTracker
    finance: TitanFinanceService
    aegis: PipelineAEGIS
    sandbox: TitanSandboxRunner
    autofixer: TitanCodeAutoFixer
    pitch_engine: TitanPitchEngine
    license_engine: TitanLicenseEngine
    factory: TitanProductFactory

    def cerrar(self) -> None:
        try:
            self.workflows.detener()
        except Exception:
            pass
        try:
            self.aegis.flush_todo()
        except Exception:
            pass
        try:
            self.telemetry.flush_db()
        except Exception:
            pass
        try:
            self.db.cerrar_todo()
        except Exception:
            pass


def construir_servicios_titan(
    *,
    db_path: str | None = None,
    log_path: str | None = None,
    carpeta_facturas: str | None = None,
    carpeta_productos: str | None = None,
    carpeta_snapshots: str | None = None,
    secret_file: str | None = None,
    ai_router_override: TitanAIRouter | None = None,
    iniciar_workflows: bool = True,
) -> TitanServiceContainer:
    aislado = db_path is not None
    db = TitanDBEngine(db_path=db_path) if aislado else obtener_db_engine()
    bus = TitanEventBus() if aislado else obtener_event_bus()
    logger = RotatingJSONLLogger(ruta_archivo=log_path, bus=bus) if log_path else (
        RotatingJSONLLogger(bus=bus) if aislado else obtener_logger()
    )
    tel = TitanTelemetry(db=db, logger=logger) if aislado else obtener_telemetry()

    rl = TitanRateLimiter()
    cb = TitanCircuitBreakerManager(db=db, bus=bus, usar_sqlite=True)
    shield = TitanHTTPShield(rate_limiter=rl, circuit_breaker=cb, telemetry=tel)

    if ai_router_override is not None:
        ai_rt = ai_router_override
    else:
        ai_rt = TitanAIRouter(
            db=db, bus=bus, telemetry=tel,
            cache=TitanAICache(db=db, usar_sqlite=True),
            usar_sqlite=True,
        )

    wf = TitanWorkflowEngine(db=db, bus=bus, shield=shield, logger=logger, telemetry=tel, auto_presets=True)
    if iniciar_workflows:
        wf.iniciar()

    cli_svc = ClienteService(db=db, bus=bus)
    crm = TitanCRMService(db=db, bus=bus, clientes=cli_svc)
    tt = TitanTimeTracker(db=db, bus=bus)
    fin = TitanFinanceService(db=db, bus=bus, clientes=cli_svc, time_tracker=tt, carpeta_facturas=carpeta_facturas)

    aegis = PipelineAEGIS(db_path=db.db_path, usar_sqlite=True, guardar_auditoria=True)
    aegis.bus = bus

    sbx = TitanSandboxRunner(db=db, bus=bus, telemetry=tel, usar_sqlite=True)
    snaps = SnapshotManager(carpeta=carpeta_snapshots)
    fixer = TitanCodeAutoFixer(sandbox=sbx, ai_router=ai_rt, bus=bus, snapshots=snaps)

    pitch = TitanPitchEngine(db=db, bus=bus, ai_router=ai_rt, crm=crm, auto_presets=True)
    lic = TitanLicenseEngine(db=db, bus=bus, secret_file=secret_file, usar_sqlite=True)
    fac = TitanProductFactory(
        db=db, bus=bus, ai_router=ai_rt, license_engine=lic,
        carpeta_salida=carpeta_productos, usar_sqlite=True,
    )

    return TitanServiceContainer(
        db=db,
        bus=bus,
        logger=logger,
        telemetry=tel,
        rate_limiter=rl,
        circuit_breaker=cb,
        http_shield=shield,
        ai_router=ai_rt,
        workflows=wf,
        clientes=cli_svc,
        crm=crm,
        time_tracker=tt,
        finance=fin,
        aegis=aegis,
        sandbox=sbx,
        autofixer=fixer,
        pitch_engine=pitch,
        license_engine=lic,
        factory=fac,
    )


def _generar_openapi_v2(rutas: list[dict[str, Any]]) -> dict[str, Any]:
    paths: dict[str, dict[str, Any]] = {}
    for rc in rutas:
        p = str(rc["path"])
        if not p.startswith("/api/v2"):
            continue
        # Normalizar {id:int} -> {id} para especificacion OpenAPI 3.0
        import re as _re
        p_oa = _re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*):[a-zA-Z]+\}", r"{\1}", p)
        met = str(rc["method"]).lower()
        paths.setdefault(p_oa, {})[met] = {
            "operationId": rc["nombre"],
            "summary": rc["resumen"] or rc["nombre"],
            "tags": rc.get("tags") or ["general"],
            "responses": {"200": {"description": "OK"}},
        }
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "ZeroTouch TITAN-OS REST API v2",
            "version": "16.0.0-titan",
            "description": "API unificada CRM, Finanzas, Time Tracker, AEGIS-X v16, AI Router, Workflows IFTTT, Sandbox, Pitch A/B y Whop Factory.",
        },
        "paths": paths,
    }


def montar_api_v2_en_router(router: TitanRouter, svc: TitanServiceContainer) -> int:
    """Monta todos los endpoints /api/v2/* (CRM + Finanzas + Operaciones + Overview + OpenAPI)."""
    r_crm = construir_router_crm_finanzas(svc.crm, svc.finance, svc.time_tracker)
    r_ops = construir_router_operaciones(
        aegis=svc.aegis,
        ai_router=svc.ai_router,
        http_shield=svc.http_shield,
        workflows=svc.workflows,
        sandbox=svc.sandbox,
        autofixer=svc.autofixer,
        pitch_engine=svc.pitch_engine,
        factory=svc.factory,
        license_engine=svc.license_engine,
    )
    n1 = router.mount("/api/v2", r_crm)
    n2 = router.mount("/api/v2", r_ops)

    @router.get("/api/v2/overview", nombre="titan_v2_overview", resumen="Snapshot maestro consolidado para Dashboard TITAN-OS v16", tags=("system",))
    def _overview(req: TitanRequest) -> dict[str, Any]:
        trm = req.qfloat("trm_cop", 4200.0)
        return {
            "ok": True,
            "version": "16.0.0-titan",
            "ts_epoch": round(time.time(), 2),
            "pipeline": svc.crm.resumen_pipeline(trm_cop=trm),
            "finanzas": svc.finance.resumen_financiero(trm_cop=trm),
            "tiempo": svc.time_tracker.resumen_productividad(dias=14, trm_cop=trm),
            "workflows": {
                "activo": svc.workflows._sub_id is not None,
                "reglas_activas": sum(1 for x in svc.workflows.listar_reglas() if x.activa),
                "total_reglas": len(svc.workflows.listar_reglas()),
            },
            "aegis_drift": svc.aegis.calibrador.analizar_drift().to_dict(),
            "ai": {
                "estrategia": svc.ai_router.estrategia_default,
                "budget_hoy": svc.ai_router.tokens_cloud_usados_hoy(),
                "cache_hit_rate": svc.ai_router.cache.estadisticas().get("hit_rate_pct", 0.0),
            },
            "sandbox": svc.sandbox.estadisticas(),
            "factory": {
                "productos_total": len(svc.factory.listar_productos(200)),
                "licencias_activas": len(svc.license_engine.listar_licencias(solo_activas=True, limite=300)),
            },
        }

    @router.get("/api/v2/openapi.json", nombre="titan_v2_openapi", resumen="Especificacion OpenAPI 3.0 autogenerada", tags=("system",))
    def _openapi(req: TitanRequest) -> dict[str, Any]:
        return _generar_openapi_v2(router.listar_rutas())

    return n1 + n2 + 2


def crear_app_titan_v16(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    db_path: str | None = None,
    log_path: str | None = None,
    carpeta_facturas: str | None = None,
    carpeta_productos: str | None = None,
    carpeta_snapshots: str | None = None,
    secret_file: str | None = None,
    ui_dir: str | None = None,
    api_token: str | None = None,
    ai_router_override: TitanAIRouter | None = None,
    iniciar_workflows: bool = True,
    fallback_handler: Callable[[TitanRequest], TitanResponse | None] | None = None,
) -> tuple[TitanWebServer, TitanServiceContainer]:
    svc = construir_servicios_titan(
        db_path=db_path,
        log_path=log_path,
        carpeta_facturas=carpeta_facturas,
        carpeta_productos=carpeta_productos,
        carpeta_snapshots=carpeta_snapshots,
        secret_file=secret_file,
        ai_router_override=ai_router_override,
        iniciar_workflows=iniciar_workflows,
    )
    srv = TitanWebServer(
        host=host,
        port=port,
        db=svc.db,
        bus=svc.bus,
        logger=svc.logger,
        telemetry=svc.telemetry,
        ui_dir=ui_dir,
        api_token=api_token,
        fallback_handler=fallback_handler,
    )
    montar_api_v2_en_router(srv.router, svc)
    from titan_core.radar_cleaner import registrar_rutas_limpieza
    registrar_rutas_limpieza(srv.router, svc)
    return srv, svc


# ==================== SINGLETON BRIDGE PARA COEXISTENCIA CON dashboard_web.py ====================
_BRIDGE_LOCK = threading.RLock()
_BRIDGE_SRV: TitanWebServer | None = None
_BRIDGE_SVC: TitanServiceContainer | None = None


def obtener_api_v2_bridge() -> tuple[TitanWebServer, TitanServiceContainer]:
    global _BRIDGE_SRV, _BRIDGE_SVC
    with _BRIDGE_LOCK:
        if _BRIDGE_SRV is None or _BRIDGE_SVC is None:
            _BRIDGE_SRV, _BRIDGE_SVC = crear_app_titan_v16(port=0, iniciar_workflows=True)
        return _BRIDGE_SRV, _BRIDGE_SVC


def despachar_en_handler_legacy(http_handler: Any, method: str, raw_body: bytes | None = None) -> bool:
    """
    Puente completo TITAN-OS v16 para dashboard_web.py:
    - GET / y /index.html -> web_ui/index.html (UI v16 sin cache)
    - GET /ui/* -> archivos estaticos en web_ui/ (con soporte ?v=16 y MIME types)
    - ANY /api/v2/* y GET /api/v2/events/stream -> Router REST v2 + SSE Live
    Cualquier otra ruta (/api/* legacy) devuelve False para seguir en dashboard_web.py.
    """
    import mimetypes
    import os
    from titan_core.db_engine import ROOT_DIR
    from titan_core.web_router import parsear_path_y_query

    met = method.upper()
    path_raw = str(getattr(http_handler, "path", "") or "")
    path, query = parsear_path_y_query(path_raw)
    ui_root = os.path.realpath(os.path.join(ROOT_DIR, "web_ui"))

    # A) Pagina principal v16 y estaticos /ui/*
    if met in ("GET", "HEAD"):
        target_file = None
        no_cache = False
        if path in ("/", "/index.html"):
            cand = os.path.join(ui_root, "index.html")
            if os.path.isfile(cand):
                target_file = cand
                no_cache = True
        elif path.startswith("/ui/"):
            rel = path[len("/ui/"):].lstrip("/")
            cand = os.path.realpath(os.path.join(ui_root, rel))
            if cand.startswith(ui_root + os.sep) and os.path.isfile(cand):
                target_file = cand

        if target_file is not None:
            with open(target_file, "rb") as f:
                data = f.read()
            ctype, _ = mimetypes.guess_type(target_file)
            if target_file.endswith(".js"):
                ctype = "application/javascript; charset=utf-8"
            elif target_file.endswith(".css"):
                ctype = "text/css; charset=utf-8"
            elif target_file.endswith(".html"):
                ctype = "text/html; charset=utf-8"
            elif not ctype:
                ctype = "application/octet-stream"

            http_handler.send_response(200)
            http_handler.send_header("Content-Type", ctype)
            http_handler.send_header("Content-Length", str(len(data)))
            http_handler.send_header("Cache-Control", "no-store" if no_cache else "no-cache")
            http_handler.end_headers()
            if met != "HEAD":
                http_handler.wfile.write(data)
            return True

    # B) API REST v2 + SSE Live
    if not path.startswith("/api/v2"):
        return False

    srv, _ = obtener_api_v2_bridge()
    hdrs = {str(k).lower(): str(v) for k, v in http_handler.headers.items()}
    if raw_body is None:
        cl = int(hdrs.get("content-length") or 0)
        body = http_handler.rfile.read(cl) if cl > 0 else b""
    else:
        body = raw_body
    cip = str(http_handler.client_address[0]) if getattr(http_handler, "client_address", None) else "127.0.0.1"
    req = TitanRequest(method=met, raw_path=path_raw, path=path, query=query, headers=hdrs, client_ip=cip, body=body)

    if met == "GET" and path == "/api/v2/events/stream":
        srv.sse.atender_conexion(http_handler, req)
        return True

    resp = srv.router.despachar(req)
    http_handler.send_response(int(resp.status))
    http_handler.send_header("Content-Type", resp.content_type)
    http_handler.send_header("Content-Length", str(len(resp.body or b"")))
    for k, v in resp.headers.items():
        if k.lower() not in ("content-length", "content-type"):
            http_handler.send_header(k, v)
    http_handler.end_headers()
    if met != "HEAD" and resp.body:
        http_handler.wfile.write(resp.body)
    return True
