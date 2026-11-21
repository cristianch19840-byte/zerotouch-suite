from __future__ import annotations

import html
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from titan_core.db_engine import TitanDBEngine, obtener_db_engine
from titan_core.event_bus import EventoSistema, TitanEventBus, obtener_event_bus
from titan_core.http_shield import TitanHTTPShield, obtener_http_shield
from titan_core.telemetry import RotatingJSONLLogger, obtener_logger

REGEX_TEMPLATE_VAR = re.compile(r"\{\{\s*([a-zA-Z0-9_.\-]+)(?:\|([^}]+))?\s*\}\}")


def resolver_ruta_dato(data: Any, ruta: str, default: Any = None) -> Any:
    """Resuelve rutas dot-notation sobre dicts/listas/objetos (ej. 'payload.economia.medio_usd' o 'payload.tags.0')."""
    if not ruta:
        return default
    actual = data
    for parte in str(ruta).strip().split("."):
        if actual is None:
            return default
        if isinstance(actual, dict):
            if parte in actual:
                actual = actual[parte]
            else:
                return default
        elif isinstance(actual, (list, tuple)):
            if parte.isdigit():
                idx = int(parte)
                if 0 <= idx < len(actual):
                    actual = actual[idx]
                else:
                    return default
            else:
                return default
        elif hasattr(actual, parte):
            actual = getattr(actual, parte)
        else:
            return default
    return actual


def interpolar_texto(plantilla: str, contexto: dict[str, Any], escapar_html: bool = False) -> str:
    """Interpola {{ruta|default}} dentro de una plantilla usando el contexto del evento."""
    if not plantilla or "{{" not in plantilla:
        return str(plantilla or "")

    def _rep(m: re.Match[str]) -> str:
        ruta = m.group(1)
        fallback = m.group(2) if m.group(2) is not None else ""
        val = resolver_ruta_dato(contexto, ruta, default=None)
        if val is None or val == "":
            txt = fallback
        elif isinstance(val, (list, tuple)):
            txt = ", ".join(str(x) for x in val)
        elif isinstance(val, dict):
            txt = json.dumps(val, ensure_ascii=False)
        else:
            txt = str(val)
        return html.escape(txt) if escapar_html else txt

    return REGEX_TEMPLATE_VAR.sub(_rep, str(plantilla))


def interpolar_estructura(obj: Any, contexto: dict[str, Any], escapar_html: bool = False) -> Any:
    if isinstance(obj, str):
        return interpolar_texto(obj, contexto, escapar_html=escapar_html)
    if isinstance(obj, list):
        return [interpolar_estructura(x, contexto, escapar_html=escapar_html) for x in obj]
    if isinstance(obj, dict):
        return {str(k): interpolar_estructura(v, contexto, escapar_html=escapar_html) for k, v in obj.items()}
    return obj


@dataclass(slots=True)
class ContextoAccion:
    regla_id: int
    regla_nombre: str
    evento: EventoSistema
    variables: dict[str, Any]
    db: TitanDBEngine
    bus: TitanEventBus
    shield: TitanHTTPShield
    logger: RotatingJSONLLogger
    dry_run: bool = False
    profundidad: int = 0


@dataclass(slots=True)
class ResultadoAccion:
    tipo: str
    ok: bool
    detalle: str = ""
    datos: dict[str, Any] = field(default_factory=dict)
    duracion_ms: float = 0.0
    simulada: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "tipo": self.tipo,
            "ok": self.ok,
            "detalle": self.detalle[:240],
            "datos": self.datos,
            "duracion_ms": round(self.duracion_ms, 2),
            "simulada": self.simulada,
        }


HandlerAccion = Callable[[dict[str, Any], ContextoAccion], ResultadoAccion]


# ==================== IMPLEMENTACION DE ACCIONES NATIVAS ====================
def _accion_log_evento(params: dict[str, Any], ctx: ContextoAccion) -> ResultadoAccion:
    nivel = str(params.get("nivel") or "info").lower()
    comp = str(params.get("componente") or "workflow")
    msg = interpolar_texto(str(params.get("mensaje") or "Regla {{regla.nombre}} ejecutada"), ctx.variables)
    if ctx.dry_run:
        return ResultadoAccion("log_evento", True, f"[DRY] ({nivel}) {msg}", {"mensaje": msg}, simulada=True)
    ctx.logger.registrar(nivel, comp, msg, {"regla_id": ctx.regla_id, "topico": ctx.evento.topico}, emitir_bus=False)
    return ResultadoAccion("log_evento", True, msg, {"nivel": nivel})


def _accion_telegram_alert(params: dict[str, Any], ctx: ContextoAccion) -> ResultadoAccion:
    plantilla = str(params.get("mensaje") or "<b>⚡ Workflow {{regla.nombre}}</b>\nEvento: <code>{{topico}}</code>")
    msg_html = interpolar_texto(plantilla, ctx.variables, escapar_html=bool(params.get("escapar_html", False)))
    chat_id = interpolar_texto(str(params.get("chat_id") or ""), ctx.variables).strip() or os.getenv("TELEGRAM_CHAT_ID", "")
    token = os.getenv("TELEGRAM_TOKEN", "").strip()

    btn_url = interpolar_texto(str(params.get("boton_url") or ""), ctx.variables).strip()
    btn_txt = interpolar_texto(str(params.get("boton_texto") or "🚀 Abrir"), ctx.variables).strip()
    botones = [[{"text": btn_txt, "url": btn_url}]] if btn_url.startswith(("http://", "https://")) else None

    if ctx.dry_run:
        return ResultadoAccion(
            "telegram_alert", True, "[DRY] Alerta Telegram preparada",
            {"chat_id": chat_id or "env_default", "preview": msg_html[:180], "tiene_boton": bool(botones)},
            simulada=True,
        )

    if not token or not chat_id:
        return ResultadoAccion("telegram_alert", False, "Faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID")

    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": msg_html[:4050],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if botones:
        payload["reply_markup"] = {"inline_keyboard": botones}

    _, resp = ctx.shield.post_json(
        f"https://api.telegram.org/bot{token}/sendMessage",
        payload,
        timeout=12.0,
        reintentos=1,
        perfil_headers="api",
        usar_etag=False,
    )
    if resp.ok:
        return ResultadoAccion("telegram_alert", True, f"Enviada a chat {chat_id}", {"status": resp.status_code})
    return ResultadoAccion("telegram_alert", False, resp.error or f"HTTP {resp.status_code}")


def _accion_webhook_http(params: dict[str, Any], ctx: ContextoAccion) -> ResultadoAccion:
    url = interpolar_texto(str(params.get("url") or ""), ctx.variables).strip()
    metodo = str(params.get("metodo") or "POST").upper()
    if metodo not in ("GET", "POST", "PUT", "PATCH"):
        metodo = "POST"
    headers = interpolar_estructura(params.get("headers") or {}, ctx.variables)
    body_raw = params.get("body")
    if body_raw is None:
        body = {
            "regla": ctx.regla_nombre,
            "evento": ctx.evento.to_dict(),
        }
    else:
        body = interpolar_estructura(body_raw, ctx.variables)

    if not url.startswith(("http://", "https://")):
        return ResultadoAccion("webhook_http", False, "URL de webhook invalida o vacia")

    if ctx.dry_run:
        return ResultadoAccion(
            "webhook_http", True, f"[DRY] {metodo} {url}",
            {"url": url, "metodo": metodo, "body": body},
            simulada=True,
        )

    resp = ctx.shield.solicitar(
        metodo,
        url,
        headers=headers if isinstance(headers, dict) else None,
        json_body=body if metodo != "GET" else None,
        timeout=float(params.get("timeout_seg", 10.0)),
        reintentos=int(params.get("reintentos", 1)),
        perfil_headers="api",
        usar_etag=False,
    )
    return ResultadoAccion(
        "webhook_http",
        resp.ok,
        f"{metodo} {url} -> HTTP {resp.status_code}" if resp.ok else (resp.error or f"HTTP {resp.status_code}"),
        {"status_code": resp.status_code, "latencia_ms": resp.latencia_ms},
    )


def _accion_crear_tarea_crm(params: dict[str, Any], ctx: ContextoAccion) -> ResultadoAccion:
    titulo = interpolar_texto(str(params.get("titulo") or "Seguimiento: {{payload.titulo|Lead}}"), ctx.variables).strip()[:180]
    desc = interpolar_texto(str(params.get("descripcion") or ""), ctx.variables).strip()[:600]
    prioridad = str(params.get("prioridad") or "media").lower()
    if prioridad not in ("baja", "media", "alta", "critica"):
        prioridad = "media"

    lead_id_val = resolver_ruta_dato(ctx.variables, str(params.get("lead_id_campo") or "payload.lead_id"))
    if lead_id_val is None:
        lead_id_val = resolver_ruta_dato(ctx.variables, "payload.id")
    cliente_id_val = resolver_ruta_dato(ctx.variables, str(params.get("cliente_id_campo") or "payload.cliente_id"))

    try:
        lead_id = int(lead_id_val) if lead_id_val not in (None, "") else None
    except (TypeError, ValueError):
        lead_id = None
    try:
        cliente_id = int(cliente_id_val) if cliente_id_val not in (None, "") else None
    except (TypeError, ValueError):
        cliente_id = None

    # Validar existencia de FK para evitar IntegrityError si el evento trae un ID sintetico
    if lead_id is not None and not ctx.db.escalar("SELECT 1 FROM leads WHERE id = ?", (lead_id,)):
        lead_id = None
    if cliente_id is not None and not ctx.db.escalar("SELECT 1 FROM clientes WHERE id = ?", (cliente_id,)):
        cliente_id = None

    vence_hrs = float(params.get("vence_en_horas") or 0)
    vence_ts = (
        (datetime.now(timezone.utc) + timedelta(hours=vence_hrs)).strftime("%Y-%m-%d %H:%M:%S")
        if vence_hrs > 0 else None
    )

    if ctx.dry_run:
        return ResultadoAccion(
            "crear_tarea_crm", True, f"[DRY] Tarea '{titulo}' ({prioridad})",
            {"titulo": titulo, "prioridad": prioridad, "lead_id": lead_id, "vence_ts": vence_ts},
            simulada=True,
        )

    # Evitar duplicar exactamente la misma tarea pendiente para el mismo lead
    if lead_id is not None:
        existe = ctx.db.escalar(
            "SELECT id FROM tareas_crm WHERE lead_id = ? AND titulo = ? AND estado = 'pendiente'",
            (lead_id, titulo),
        )
        if existe:
            return ResultadoAccion("crear_tarea_crm", True, f"Tarea ya existente (#{existe})", {"tarea_id": int(existe), "duplicada": True})

    tid = ctx.db.ejecutar(
        """
        INSERT INTO tareas_crm (lead_id, cliente_id, titulo, descripcion, prioridad, estado, vence_ts)
        VALUES (?, ?, ?, ?, ?, 'pendiente', ?)
        """,
        (lead_id, cliente_id, titulo, desc, prioridad, vence_ts),
    )
    return ResultadoAccion("crear_tarea_crm", True, f"Tarea #{tid} creada: {titulo}", {"tarea_id": tid, "lead_id": lead_id})


def _accion_actualizar_lead(params: dict[str, Any], ctx: ContextoAccion) -> ResultadoAccion:
    lead_id_val = params.get("lead_id") or resolver_ruta_dato(ctx.variables, "payload.lead_id") or resolver_ruta_dato(ctx.variables, "payload.id")
    try:
        lead_id = int(lead_id_val)
    except (TypeError, ValueError):
        return ResultadoAccion("actualizar_lead", False, "No se encontro lead_id valido en el evento")

    nuevo_estado = str(params.get("estado") or "").strip().lower()
    nota_extra = interpolar_texto(str(params.get("anexar_nota") or ""), ctx.variables).strip()
    tag_extra = interpolar_texto(str(params.get("prioridad_tag") or ""), ctx.variables).strip()

    if ctx.dry_run:
        return ResultadoAccion(
            "actualizar_lead", True, f"[DRY] Actualizar lead #{lead_id}",
            {"lead_id": lead_id, "estado": nuevo_estado, "anexar_nota": nota_extra, "prioridad_tag": tag_extra},
            simulada=True,
        )

    row = ctx.db.consultar_uno("SELECT id, estado, notas, prioridad_tag FROM leads WHERE id = ?", (lead_id,))
    if not row:
        return ResultadoAccion("actualizar_lead", False, f"Lead #{lead_id} no existe en DB")

    est_final = nuevo_estado if nuevo_estado in ("nuevo", "contactado", "negociando", "ganado", "descartado") else str(row["estado"])
    notas_prev = str(row["notas"] or "").strip()
    notas_final = f"{notas_prev} | {nota_extra}".strip(" |") if nota_extra else notas_prev
    tag_prev = str(row["prioridad_tag"] or "").strip()
    tag_final = f"{tag_prev} · {tag_extra}".strip(" ·") if (tag_extra and tag_extra not in tag_prev) else tag_prev

    ctx.db.ejecutar(
        "UPDATE leads SET estado = ?, notas = ?, prioridad_tag = ?, actualizado_ts = CURRENT_TIMESTAMP WHERE id = ?",
        (est_final, notas_final[:300], tag_final[:120], lead_id),
    )
    return ResultadoAccion("actualizar_lead", True, f"Lead #{lead_id} actualizado ({est_final})", {"lead_id": lead_id, "estado": est_final})


def _accion_sonido_alerta(params: dict[str, Any], ctx: ContextoAccion) -> ResultadoAccion:
    tipo = str(params.get("tipo") or "alta").lower()
    if ctx.dry_run:
        return ResultadoAccion("sonido_alerta", True, f"[DRY] Sonido '{tipo}'", {"tipo": tipo}, simulada=True)
    try:
        from core_ia import alerta_sonora
        threading.Thread(target=alerta_sonora, args=(tipo,), daemon=True).start()
        return ResultadoAccion("sonido_alerta", True, f"Sonido '{tipo}' reproducido")
    except Exception as e:
        return ResultadoAccion("sonido_alerta", False, str(e)[:120])


def _accion_emitir_evento(params: dict[str, Any], ctx: ContextoAccion) -> ResultadoAccion:
    topico = interpolar_texto(str(params.get("topico") or ""), ctx.variables).strip().lower()
    if not topico:
        return ResultadoAccion("emitir_evento", False, "Falta topico destino")
    if ctx.profundidad >= 3:
        return ResultadoAccion("emitir_evento", False, "Profundidad maxima de encadenamiento alcanzada (anti-bucle)")

    nivel = str(params.get("nivel") or "info").lower()
    payload = interpolar_estructura(params.get("payload") or {}, ctx.variables)
    if not isinstance(payload, dict):
        payload = {"valor": payload}
    payload["_wf_depth"] = ctx.profundidad + 1
    payload["_wf_parent_rule"] = ctx.regla_id

    if ctx.dry_run:
        return ResultadoAccion("emitir_evento", True, f"[DRY] Emitir '{topico}'", {"topico": topico, "payload": payload}, simulada=True)

    ev = ctx.bus.publicar(topico, payload, origen=f"workflow:{ctx.regla_id}", nivel=nivel)
    return ResultadoAccion("emitir_evento", True, f"Evento '{topico}' (#{ev.seq_id}) emitido", {"seq_id": ev.seq_id})


def _accion_auto_copiloto(params: dict[str, Any], ctx: ContextoAccion) -> ResultadoAccion:
    lead_id_val = resolver_ruta_dato(ctx.variables, "payload.lead_id") or resolver_ruta_dato(ctx.variables, "payload.id")
    link = interpolar_texto(str(params.get("link") or "{{payload.link}}"), ctx.variables).strip()
    titulo = interpolar_texto(str(params.get("titulo") or "{{payload.titulo}}"), ctx.variables).strip()
    cuerpo = interpolar_texto(str(params.get("texto") or "{{payload.texto}}"), ctx.variables).strip()

    if ctx.dry_run:
        return ResultadoAccion(
            "auto_copiloto", True, f"[DRY] Auto-Copiloto para '{titulo[:50]}'",
            {"lead_id": lead_id_val, "link": link},
            simulada=True,
        )

    def _run_bg() -> None:
        try:
            from modulo_b_ejecutor.copiloto import analizar_oferta_completo, cargar_desde_crm_completo
            oferta = f"Titulo: {titulo}\nLink: {link}\n\n{cuerpo}".strip()
            autor = str(resolver_ruta_dato(ctx.variables, "payload.autor") or "")
            plat = str(resolver_ruta_dato(ctx.variables, "payload.plataforma") or "")
            tipo = str(resolver_ruta_dato(ctx.variables, "payload.tipo_trabajo") or "")
            if lead_id_val and str(lead_id_val).isdigit():
                of_crm, au_c, ti_c, pl_c, tp_c = cargar_desde_crm_completo(int(lead_id_val))
                if of_crm:
                    oferta, autor, titulo_eff, plat, tipo = of_crm, au_c, ti_c, pl_c, tp_c
                else:
                    titulo_eff = titulo
            else:
                titulo_eff = titulo
            res = analizar_oferta_completo(oferta, autor=autor, titulo=titulo_eff, guardar_archivos=True, plataforma=plat, tipo_trabajo=tipo)
            if res:
                ctx.bus.publicar(
                    "workflow.copiloto.listo",
                    {
                        "lead_id": lead_id_val,
                        "titulo": titulo_eff[:120],
                        "plataforma": res.get("plataforma", plat),
                        "pitch_a": (res.get("pitch_a") or "")[:900],
                        "_wf_depth": ctx.profundidad + 1,
                    },
                    origen=f"workflow:{ctx.regla_id}",
                    nivel="ok",
                )
        except Exception as e:
            ctx.logger.error("workflow", f"Error en auto_copiloto: {e}")

    threading.Thread(target=_run_bg, daemon=True).start()
    return ResultadoAccion("auto_copiloto", True, "Auto-Copiloto lanzado en segundo plano", {"lead_id": lead_id_val})


def _accion_ejecutar_backup(params: dict[str, Any], ctx: ContextoAccion) -> ResultadoAccion:
    max_b = int(params.get("max_backups", 10))
    if ctx.dry_run:
        return ResultadoAccion("ejecutar_backup", True, "[DRY] Backup atomico SQLite SHA-256", simulada=True)
    meta = ctx.db.crear_backup_verificado(max_backups=max_b)
    return ResultadoAccion("ejecutar_backup", bool(meta.get("integridad_ok")), f"Backup {meta.get('archivo')} OK", {"archivo": meta.get("archivo"), "sha256": str(meta.get("sha256", ""))[:16]})


class ActionRegistry:
    """Registro extensible de acciones ejecutables por el Workflow Engine."""

    def __init__(self) -> None:
        self._handlers: dict[str, HandlerAccion] = {}
        self._registrar_nativas()

    def _registrar_nativas(self) -> None:
        self.registrar("log_evento", _accion_log_evento)
        self.registrar("telegram_alert", _accion_telegram_alert)
        self.registrar("webhook_http", _accion_webhook_http)
        self.registrar("crear_tarea_crm", _accion_crear_tarea_crm)
        self.registrar("actualizar_lead", _accion_actualizar_lead)
        self.registrar("sonido_alerta", _accion_sonido_alerta)
        self.registrar("emitir_evento", _accion_emitir_evento)
        self.registrar("auto_copiloto", _accion_auto_copiloto)
        self.registrar("ejecutar_backup", _accion_ejecutar_backup)

    def registrar(self, tipo: str, handler: HandlerAccion) -> None:
        self._handlers[str(tipo).strip().lower()] = handler

    def disponibles(self) -> list[str]:
        return sorted(self._handlers.keys())

    def ejecutar(self, accion_spec: dict[str, Any], ctx: ContextoAccion) -> ResultadoAccion:
        tipo = str(accion_spec.get("tipo") or "").strip().lower()
        params = accion_spec.get("params") if isinstance(accion_spec.get("params"), dict) else accion_spec
        handler = self._handlers.get(tipo)
        if handler is None:
            return ResultadoAccion(tipo or "desconocida", False, f"Tipo de accion no registrado: '{tipo}'")
        t0 = time.perf_counter()
        try:
            res = handler(params, ctx)
            res.duracion_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            return res
        except Exception as e:
            return ResultadoAccion(
                tipo=tipo,
                ok=False,
                detalle=f"Excepcion en accion '{tipo}': {str(e)[:180]}",
                duracion_ms=round((time.perf_counter() - t0) * 1000.0, 2),
                simulada=ctx.dry_run,
            )