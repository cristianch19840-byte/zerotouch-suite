"""
ZeroTouch TITAN-OS v16.0 — Plataforma Modular Empresarial de Automatizacion Freelance.
"""
from __future__ import annotations

__version__ = "16.0.0-titan"

__all__ = [
    "__version__",
    "obtener_db_engine",
    "obtener_event_bus",
    "obtener_logger",
    "obtener_telemetry",
    "obtener_http_shield",
    "obtener_ai_router",
    "obtener_workflow_engine",
    "obtener_crm_service",
    "obtener_finance_service",
    "obtener_time_tracker",
    "obtener_sandbox_runner",
    "obtener_code_autofixer",
    "obtener_pitch_engine",
    "obtener_license_engine",
    "obtener_product_factory",
    "crear_app_titan_v16",
]


def __getattr__(name: str):
    mapa = {
        "obtener_db_engine": ("titan_core.db_engine", "obtener_db_engine"),
        "obtener_event_bus": ("titan_core.event_bus", "obtener_event_bus"),
        "obtener_logger": ("titan_core.telemetry", "obtener_logger"),
        "obtener_telemetry": ("titan_core.telemetry", "obtener_telemetry"),
        "obtener_http_shield": ("titan_core.http_shield", "obtener_http_shield"),
        "obtener_ai_router": ("titan_core.ai_router", "obtener_ai_router"),
        "obtener_workflow_engine": ("titan_core.workflow_engine", "obtener_workflow_engine"),
        "obtener_crm_service": ("titan_core.crm_service", "obtener_crm_service"),
        "obtener_finance_service": ("titan_core.finance_service", "obtener_finance_service"),
        "obtener_time_tracker": ("titan_core.time_tracker", "obtener_time_tracker"),
        "obtener_sandbox_runner": ("titan_core.sandbox_runner", "obtener_sandbox_runner"),
        "obtener_code_autofixer": ("titan_core.code_autofix", "obtener_code_autofixer"),
        "obtener_pitch_engine": ("titan_core.pitch_engine", "obtener_pitch_engine"),
        "obtener_license_engine": ("titan_core.license_engine", "obtener_license_engine"),
        "obtener_product_factory": ("titan_core.product_factory", "obtener_product_factory"),
        "crear_app_titan_v16": ("titan_core.api_v2_app", "crear_app_titan_v16"),
    }
    if name in mapa:
        mod_name, attr = mapa[name]
        mod = __import__(mod_name, fromlist=[attr])
        return getattr(mod, attr)
    raise AttributeError(f"module 'titan_core' has no attribute {name!r}")