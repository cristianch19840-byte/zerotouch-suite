from __future__ import annotations

import os
import re
import threading
import time
from typing import Any

from modulo_a_radar_whop.motor_filtrado.pipeline import PERFILES_AEGIS
from titan_core.api_v2_app import TitanServiceContainer, obtener_api_v2_bridge
from titan_core.event_bus import EventoSistema
from titan_core.http_shield import TitanHTTPShield, obtener_http_shield
from titan_core.telegram_callbacks import (
    RespuestaCallback,
    TitanTelegramCallbackRouter,
    btn,
    construir_lista_leads,
    construir_menu_principal,
    construir_tarjeta_lead,
    construir_vista_aegis,
    construir_vista_agenda,
    construir_vista_caja,
    construir_vista_salud,
    construir_vista_timer,
    construir_vista_workflows,
    dividir_mensajes_tg,
    esc_html,
    markup,
    truncar_tg,
)

COMANDOS_BOT_V16: list[dict[str, str]] = [
    {"command": "menu", "description": "Centro de Mando interactivo TITAN-OS v16"},
    {"command": "overview", "description": "Resumen maestro USD/COP, pipeline y salud"},
    {"command": "leads", "description": "Lista interactiva de leads con botones 1-toque"},
    {"command": "lead", "description": "Vista 360 de un lead (/lead <id>)"},
    {"command": "pitch", "description": "Generar Pitch A/B (/pitch <id|texto>)"},
    {"command": "timer", "description": "Cronómetro (/timer start|stop|status)"},
    {"command": "agenda", "description": "Tareas CRM con botones Completar/+24h"},
    {"command": "tarea", "description": "Crear tarea rápida (/tarea <título>)"},
    {"command": "caja", "description": "Finanzas, balance COP y facturas pendientes"},
    {"command": "gasto", "description": "Registrar gasto (/gasto <usd> <concepto>)"},
    {"command": "factura", "description": "Emitir factura (/factura <cliente> <usd> <concepto>)"},
    {"command": "aegis", "description": "Control forense AEGIS-X v16, drift y perfiles"},
    {"command": "wf", "description": "Activar/pausar Workflows IFTTT"},
    {"command": "salud", "description": "Salud SQLite, AI Router, Circuits y Backup"},
]


class TelegramAPIClient:
    """Cliente Telegram Bot API blindado sobre TitanHTTPShield (sin dependencias externas)."""

    def __init__(
        self,
        token: str,
        *,
        base_url: str = "https://api.telegram.org",
        shield: TitanHTTPShield | None = None,
    ) -> None:
        self.token = str(token or "").strip()
        self.base_url = base_url.rstrip("/")
        self.shield = shield or obtener_http_shield()

    def _endpoint(self, metodo: str) -> str:
        return f"{self.base_url}/bot{self.token}/{metodo}"

    def _call(self, metodo: str, payload: dict[str, Any], timeout: float = 15.0) -> tuple[bool, Any]:
        if not self.token:
            return False, "TELEGRAM_TOKEN vacío"
        data, resp = self.shield.post_json(
            self._endpoint(metodo),
            payload,
            timeout=timeout,
            reintentos=1,
            perfil_headers="api",
            usar_etag=False,
            cache_ttl_seg=0.0,
        )
        if resp.ok and isinstance(data, dict) and data.get("ok"):
            return True, data.get("result")
        err = data.get("description") if isinstance(data, dict) else (resp.error or f"HTTP {resp.status_code}")
        return False, err

    def send_message(
        self,
        chat_id: str | int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str = "HTML",
    ) -> tuple[bool, Any]:
        chunks = dividir_mensajes_tg(text)
        if not chunks:
            return False, "Mensaje vacío"
        ultimo_res = None
        for idx, ch in enumerate(chunks):
            payload: dict[str, Any] = {
                "chat_id": str(chat_id),
                "text": ch,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            }
            if reply_markup and idx == len(chunks) - 1:
                payload["reply_markup"] = reply_markup
            ok, res = self._call("sendMessage", payload)
            if not ok:
                return False, res
            ultimo_res = res
        return True, ultimo_res

    def edit_message_text(
        self,
        chat_id: str | int,
        message_id: int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str = "HTML",
    ) -> tuple[bool, Any]:
        payload: dict[str, Any] = {
            "chat_id": str(chat_id),
            "message_id": int(message_id),
            "text": truncar_tg(text),
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self._call("editMessageText", payload)

    def answer_callback_query(
        self,
        callback_query_id: str,
        text: str = "",
        *,
        show_alert: bool = False,
    ) -> tuple[bool, Any]:
        payload: dict[str, Any] = {
            "callback_query_id": str(callback_query_id),
            "text": str(text or "")[:190],
            "show_alert": bool(show_alert),
        }
        return self._call("answerCallbackQuery", payload)

    def set_my_commands(self, comandos: list[dict[str, str]]) -> tuple[bool, Any]:
        return self._call("setMyCommands", {"commands": comandos})

    def get_updates(self, offset: int = 0, timeout_poll: int = 20) -> list[dict[str, Any]]:
        ok, res = self._call(
            "getUpdates",
            {
                "offset": int(offset),
                "timeout": int(timeout_poll),
                "allowed_updates": ["message", "callback_query"],
            },
            timeout=float(timeout_poll) + 10.0,
        )
        return res if (ok and isinstance(res, list)) else []


class TitanTelegramBotV16:
    """
    Controlador interactivo de Telegram TITAN-OS v16.0:
    - Autorizacion estricta por chat_id (anti-intrusos)
    - 14 comandos interactivos con Inline Keyboards
    - Despacho de callbacks 't16:...' en 1 toque con edicion en sitio del mensaje
    - Puente proactivo desde TitanEventBus (alertas de leads oro, cobros, drift y circuit breakers)
    - Compatible como plugin dentro del loop legacy de telegram_bot_control.py o standalone
    """

    def __init__(
        self,
        svc: TitanServiceContainer,
        *,
        token: str | None = None,
        chat_id_autorizado: str | None = None,
        api_base_url: str = "https://api.telegram.org",
        perfil_getter: Any = None,
        perfil_setter: Any = None,
        score_min_alerta_proactiva: int = 8,
    ) -> None:
        self.svc = svc
        self.token = (token if token is not None else os.getenv("TELEGRAM_TOKEN", "")).strip()
        self.chat_id = str(chat_id_autorizado if chat_id_autorizado is not None else os.getenv("TELEGRAM_CHAT_ID", "")).strip()
        self.api = TelegramAPIClient(self.token, base_url=api_base_url, shield=svc.http_shield)
        self.callbacks = TitanTelegramCallbackRouter(svc, perfil_getter=perfil_getter, perfil_setter=perfil_setter)
        self.score_min_alerta = int(score_min_alerta_proactiva)

        self._stop_evt = threading.Event()
        self._thread: threading.Thread | None = None
        self._sub_ids: list[str] = []
        self._offset = 0
        self._cooldown_alertas: dict[str, float] = {}
        self._lock = threading.Lock()

    def _chat_autorizado(self, chat_id: str | int) -> bool:
        if not self.chat_id:
            return True
        return str(chat_id).strip() == self.chat_id

    # ==================== PUENTE PROACTIVO DESDE TITANEVENTBUS ====================
    def activar_alertas_event_bus(self) -> None:
        if self._sub_ids:
            return
        self._sub_ids.append(self.svc.bus.suscribir("crm.lead.nuevo", self._on_lead_nuevo))
        self._sub_ids.append(self.svc.bus.suscribir("finanzas.factura.pagada", self._on_factura_pagada))
        self._sub_ids.append(self.svc.bus.suscribir("aegis.drift.detectado", self._on_drift_critico))
        self._sub_ids.append(self.svc.bus.suscribir("http.circuit.open", self._on_circuit_open))

    def desactivar_alertas_event_bus(self) -> None:
        for sid in self._sub_ids:
            self.svc.bus.desuscribir(sid)
        self._sub_ids.clear()

    def _en_cooldown(self, clave: str, segs: float = 120.0) -> bool:
        ahora = time.time()
        with self._lock:
            if self._cooldown_alertas.get(clave, 0.0) > ahora:
                return True
            self._cooldown_alertas[clave] = ahora + segs
            return False

    def _on_lead_nuevo(self, evt: EventoSistema) -> None:
        if not self.token or not self.chat_id:
            return
        p = evt.payload or {}
        score = int(p.get("score") or 0)
        lid = p.get("lead_id") or p.get("id")
        if score < self.score_min_alerta or not lid:
            return
        if self._en_cooldown(f"lead:{lid}", 300.0):
            return
        lead = self.svc.crm.obtener_lead(int(lid))
        if not lead:
            return
        txt, kb = construir_tarjeta_lead(lead, timer_activo=self.svc.time_tracker.obtener_sesion_activa())
        self.api.send_message(self.chat_id, txt, reply_markup=kb)

    def _on_factura_pagada(self, evt: EventoSistema) -> None:
        if not self.token or not self.chat_id:
            return
        p = evt.payload or {}
        txt = (
            f"<b>💵 PAGO RECIBIDO — {esc_html(p.get('numero', ''))}</b>\n"
            f"👤 {esc_html(p.get('cliente', 'Cliente'))}\n"
            f"💰 Neto: <b>+${float(p.get('monto_neto_usd') or 0):,.2f} USD</b> "
            f"(≈ ${int(p.get('monto_neto_cop') or 0):,} COP) vía <b>{esc_html(p.get('pasarela', 'binance'))}</b>"
        )
        self.api.send_message(self.chat_id, txt, reply_markup=markup([[btn("💰 Ver Caja", "caja"), btn("🏠 Menú", "menu")]]))

    def _on_drift_critico(self, evt: EventoSistema) -> None:
        if not self.token or not self.chat_id or self._en_cooldown("aegis_drift", 600.0):
            return
        p = evt.payload or {}
        txt = (
            "<b>🚨 ALERTA AEGIS-X DRIFT CRÍTICO</b>\n"
            f"• PSI: <b>{p.get('psi', 0)}</b> | ΔTasa: <b>{p.get('delta_tasa_pct', 0)}%</b>\n"
            "• Revisa o recalibra tus perfiles desde el panel interactivo."
        )
        self.api.send_message(self.chat_id, txt, reply_markup=markup([[btn("🛡️ Abrir AEGIS-X", "aegis_view")]]))

    def _on_circuit_open(self, evt: EventoSistema) -> None:
        if not self.token or not self.chat_id:
            return
        p = evt.payload or {}
        dom = str(p.get("dominio") or "desconocido")
        if self._en_cooldown(f"cb:{dom}", 300.0):
            return
        txt = (
            f"<b>🔌 CIRCUIT BREAKER OPEN — {esc_html(dom)}</b>\n"
            f"• Cooldown: <b>{p.get('cooldown_seg', 0)}s</b> | Fallos: {p.get('fallos', 0)}\n"
            f"• Motivo: <code>{esc_html(p.get('motivo', ''))}</code>"
        )
        self.api.send_message(self.chat_id, txt, reply_markup=markup([[btn("🔌 Reset Circuits", "sys_cb"), btn("🩺 Salud", "salud")]]))

    # ==================== DESPACHO DE COMANDOS Y CALLBACKS ====================
    def procesar_comando(self, texto: str, chat_id: str | int) -> tuple[bool, str, dict[str, Any] | None]:
        """
        Evalua comandos TITAN-OS v16. Devuelve (handled, respuesta_html, reply_markup).
        Si devuelve handled=False, el bot legacy puede atender el comando normalmente.
        """
        raw = str(texto or "").strip()
        if not raw.startswith("/"):
            return False, "", None

        partes = raw.split(maxsplit=1)
        cmd = partes[0].lower().split("@", 1)[0]
        arg = partes[1].strip() if len(partes) > 1 else ""

        if cmd in ("/menu", "/titan", "/start", "/help"):
            txt, kb = construir_menu_principal(self.svc)
            return True, txt, kb

        if cmd == "/overview":
            pipe = self.svc.crm.resumen_pipeline()
            fin = self.svc.finance.resumen_financiero()
            prod = self.svc.time_tracker.resumen_productividad(dias=7)
            drift = self.svc.aegis.calibrador.analizar_drift()
            txt = (
                "<b>📊 TITAN-OS v16 — OVERVIEW EJECUTIVO</b>\n\n"
                f"💰 <b>Finanzas:</b> Mes ${fin['ingresos_mes_usd']:,.2f} ({fin['progreso_meta_pct']}% meta) | "
                f"Caja ${fin['balance_caja_usd']:,.2f} (≈ ${fin['balance_caja_cop']:,} COP)\n"
                f"🎯 <b>CRM:</b> {pipe['total_leads']} leads | {pipe['ganados']} ganados ({pipe['tasa_cierre_pct']}%) | "
                f"Forecast ${pipe['pipeline_ponderado_usd']:,.2f} | Clientes VIP/Rec: {pipe['clientes_recurrentes']}\n"
                f"⏱️ <b>Tiempo 7d:</b> {prod['horas_totales']}h (${prod['valor_devengado_usd']:,.2f}) | "
                f"Tarifa real 30d: ${fin['tarifa_efectiva_mes_usd_hr']}/hr\n"
                f"🛡️ <b>AEGIS-X:</b> Drift {drift.nivel_alerta.upper()} (PSI={drift.psi:.3f}) | "
                f"Workflows: {sum(1 for r in self.svc.workflows.listar_reglas() if r.activa)} activas"
            )
            kb = markup([
                [btn("🎯 Leads", "leads", "nuevo", "0"), btn("📋 Agenda", "agenda", "0"), btn("💰 Caja", "caja")],
                [btn("🛡️ AEGIS", "aegis_view"), btn("⚙️ Workflows", "wf_view"), btn("🩺 Salud", "salud")],
            ])
            return True, txt, kb

        if cmd == "/leads":
            est = arg.lower() if arg.lower() in ("nuevo", "contactado", "negociando", "ganado", "descartado", "todos") else "nuevo"
            txt, kb = construir_lista_leads(self.svc, estado=est, pagina=0)
            return True, txt, kb

        if cmd == "/lead":
            if not arg.isdigit():
                return True, "Uso: <code>/lead &lt;id&gt;</code> (ej. <code>/lead 12</code>)", None
            lid = int(arg)
            v360 = self.svc.crm.obtener_lead_360(lid)
            if not v360:
                return True, f"❌ Lead <b>#{lid}</b> no encontrado.", None
            txt, kb = construir_tarjeta_lead(v360["lead"], timer_activo=self.svc.time_tracker.obtener_sesion_activa(), vista_360=v360)
            return True, txt, kb

        if cmd == "/pitch":
            if not arg:
                return True, "Uso: <code>/pitch &lt;lead_id&gt;</code> o <code>/pitch &lt;descripción de oferta&gt;</code>", None
            if arg.isdigit():
                res_cb = self.callbacks.despachar(f"t16:pitch_gen:{arg}")
                return True, res_cb.edit_text or res_cb.toast, res_cb.edit_markup
            res = self.svc.pitch_engine.generar_pitch_ab(titulo=arg[:160], cuerpo=arg, plataforma="reddit", num_variantes=2)
            mejor = next((v for v in res.variantes if v.variante == res.mejor_variante), res.variantes[0])
            txt = (
                f"<b>✍️ PITCH A/B RÁPIDO</b> ({esc_html(res.proveedor_ia)})\n"
                f"🏆 Ganador: <b>Var {mejor.variante}</b> ({mejor.reporte.score_0_100}/100 · {mejor.reporte.grado})\n\n"
                f"<code>{esc_html(mejor.texto[:2600])}</code>"
            )
            return True, txt, markup([[btn("🏠 Menú", "menu")]])

        if cmd == "/timer":
            sub = arg.split(maxsplit=1)
            op = sub[0].lower() if sub else "status"
            rest = sub[1].strip() if len(sub) > 1 else ""
            if op in ("start", "iniciar", "play"):
                lid = int(rest) if rest.isdigit() else None
                proy = "" if lid else rest
                ses = self.svc.time_tracker.iniciar_sesion(proyecto_nombre=proy, lead_id=lid)
                txt, kb = construir_vista_timer(self.svc)
                return True, f"▶️ Iniciado: <b>{esc_html(ses['proyecto_nombre'])}</b>\n\n{txt}", kb
            if op in ("stop", "parar", "detener"):
                ses = self.svc.time_tracker.detener_sesion()
                txt, kb = construir_vista_timer(self.svc)
                hdr = f"⏹️ Guardado <b>{ses['formato_hms']}</b> (${ses['valor_devengado_usd']})\n\n" if ses else "⚪ No había sesión activa.\n\n"
                return True, hdr + txt, kb
            txt, kb = construir_vista_timer(self.svc)
            return True, txt, kb

        if cmd == "/agenda":
            txt, kb = construir_vista_agenda(self.svc, pagina=0)
            return True, txt, kb

        if cmd == "/tarea":
            if not arg:
                return True, "Uso: <code>/tarea &lt;título de tarea&gt;</code>", None
            t = self.svc.crm.crear_tarea(titulo=arg, prioridad="alta", vence_en_horas=24.0)
            txt, kb = construir_vista_agenda(self.svc, pagina=0)
            return True, f"✅ Tarea <b>#{t['id']}</b> creada (vence en 24h).\n\n{txt}", kb

        if cmd in ("/caja", "/finanzas"):
            txt, kb = construir_vista_caja(self.svc)
            return True, txt, kb

        if cmd == "/gasto":
            m = re.match(r"^\$?(\d+(?:\.\d+)?)\s+(.+)$", arg)
            if not m:
                return True, "Uso: <code>/gasto &lt;monto_usd&gt; &lt;descripción&gt;</code> (ej. <code>/gasto 12 VPS mensual</code>)", None
            monto = float(m.group(1))
            desc = m.group(2).strip()
            mov = self.svc.finance.registrar_movimiento("gasto", desc, monto, categoria="operativo")
            txt, kb = construir_vista_caja(self.svc)
            return True, f"💸 Gasto registrado (#{mov['id']}): <b>-${monto:.2f} USD</b> ({esc_html(desc)})\n\n{txt}", kb

        if cmd == "/factura":
            m = re.match(r"^(\S+)\s+\$?(\d+(?:\.\d+)?)\s+(.+)$", arg)
            if not m:
                return True, "Uso: <code>/factura &lt;cliente|lead_id&gt; &lt;monto_usd&gt; &lt;concepto&gt;</code>", None
            cli_ref, monto_s, conc = m.group(1), m.group(2), m.group(3).strip()
            lid = int(cli_ref) if cli_ref.isdigit() else None
            cli_nom = cli_ref
            if lid:
                ld = self.svc.crm.obtener_lead(lid)
                if ld:
                    cli_nom = str(ld.get("autor") or f"Lead_{lid}")
            fac = self.svc.finance.emitir_factura(cli_nom, conc, float(monto_s), lead_id=lid)
            txt, kb = construir_vista_caja(self.svc)
            return True, f"🧾 Factura <b>{fac['numero']}</b> emitida por <b>${float(monto_s):,.2f} USD</b>\n\n{txt}", kb

        if cmd == "/aegis":
            low = arg.lower()
            if low in PERFILES_AEGIS:
                self.callbacks._set_perfil(low)
                txt, kb = construir_vista_aegis(self.svc, low)
                return True, f"🛡️ Perfil cambiado a <b>{low.upper()}</b>\n\n{txt}", kb
            if low == "calibrar":
                res = self.svc.aegis.calibrar_automatico(perfil_nombre=self.callbacks._get_perfil(), aplicar=True)
                txt, kb = construir_vista_aegis(self.svc, self.callbacks._get_perfil())
                info = f"Calibrado OK (umbral {res['ajuste']['umbral_aprobacion']})" if res.get("calibrado") else str(res.get("motivo"))
                return True, f"🎛️ {esc_html(info)}\n\n{txt}", kb
            txt, kb = construir_vista_aegis(self.svc, self.callbacks._get_perfil())
            return True, txt, kb

        if cmd in ("/wf", "/workflows"):
            txt, kb = construir_vista_workflows(self.svc)
            return True, txt, kb

        if cmd in ("/salud", "/health"):
            txt, kb = construir_vista_salud(self.svc)
            return True, txt, kb

        return False, "", None

    def procesar_update(self, update: dict[str, Any]) -> bool:
        """Procesa un update individual de Telegram (message o callback_query). Devuelve True si fue manejado."""
        if "callback_query" in update:
            cq = update["callback_query"] or {}
            cq_id = str(cq.get("id") or "")
            msg = cq.get("message") or {}
            chat_id = (msg.get("chat") or {}).get("id")
            msg_id = msg.get("message_id")
            data = str(cq.get("data") or "")

            if chat_id is None or not self._chat_autorizado(chat_id):
                if cq_id:
                    self.api.answer_callback_query(cq_id, "No autorizado", show_alert=True)
                return True

            res: RespuestaCallback = self.callbacks.despachar(data)
            if not res.handled:
                return False

            if cq_id:
                self.api.answer_callback_query(cq_id, res.toast, show_alert=res.show_alert)
            if res.edit_text is not None and msg_id is not None:
                ok_ed, _ = self.api.edit_message_text(chat_id, int(msg_id), res.edit_text, reply_markup=res.edit_markup)
                if not ok_ed:
                    self.api.send_message(chat_id, res.edit_text, reply_markup=res.edit_markup)
            for extra_txt, extra_kb in res.extra_messages:
                self.api.send_message(chat_id, extra_txt, reply_markup=extra_kb)
            return True

        if "message" in update:
            msg = update["message"] or {}
            chat_id = (msg.get("chat") or {}).get("id")
            texto = str(msg.get("text") or "").strip()
            if chat_id is None or not texto:
                return False
            if not self._chat_autorizado(chat_id):
                return True
            handled, resp_txt, kb = self.procesar_comando(texto, chat_id)
            if handled and resp_txt:
                self.api.send_message(chat_id, resp_txt, reply_markup=kb)
                return True

        return False

    def poll_una_vez(self, timeout_poll: int = 1) -> int:
        updates = self.api.get_updates(offset=self._offset, timeout_poll=timeout_poll)
        procesados = 0
        for upd in updates:
            uid = int(upd.get("update_id") or 0)
            if uid >= self._offset:
                self._offset = uid + 1
            if self.procesar_update(upd):
                procesados += 1
        return procesados

    def iniciar_polling(self, registrar_comandos: bool = True) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self.activar_alertas_event_bus()
        if registrar_comandos and self.token:
            self.api.set_my_commands(COMANDOS_BOT_V16)

        def _loop() -> None:
            while not self._stop_evt.is_set():
                try:
                    self.poll_una_vez(timeout_poll=20)
                except Exception:
                    time.sleep(2.0)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def detener(self) -> None:
        self._stop_evt.set()
        self.desactivar_alertas_event_bus()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            self._thread = None


_TG_LOCK = threading.RLock()
_TG_SINGLETON: TitanTelegramBotV16 | None = None


def obtener_telegram_bot_v16() -> TitanTelegramBotV16:
    global _TG_SINGLETON
    with _TG_LOCK:
        if _TG_SINGLETON is None:
            _, svc = obtener_api_v2_bridge()
            def _get_p() -> str:
                try:
                    from core_ia import cargar_config
                    return str(cargar_config().get("aegis_perfil") or "equilibrado")
                except Exception:
                    return "equilibrado"
            def _set_p(p: str) -> None:
                try:
                    from core_ia import cargar_config, guardar_config
                    cfg = cargar_config()
                    cfg["aegis_perfil"] = p
                    guardar_config(cfg)
                except Exception:
                    pass
            _TG_SINGLETON = TitanTelegramBotV16(svc, perfil_getter=_get_p, perfil_setter=_set_p)
        return _TG_SINGLETON