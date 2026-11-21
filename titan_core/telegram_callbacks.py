from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Any

from modulo_a_radar_whop.motor_filtrado.pipeline import PERFILES_AEGIS
from titan_core.api_v2_app import TitanServiceContainer
from titan_core.time_tracker import formatear_hms

MAX_CALLBACK_BYTES = 64
MAX_TG_MSG_LEN = 3950


def esc_html(val: Any) -> str:
    return html.escape(str(val if val is not None else ""), quote=False)


def truncar_tg(texto: str, max_len: int = MAX_TG_MSG_LEN) -> str:
    s = str(texto or "")
    if len(s) <= max_len:
        return s
    return s[: max_len - 18] + "\n...[truncado]..."


def dividir_mensajes_tg(texto: str, max_len: int = MAX_TG_MSG_LEN) -> list[str]:
    s = str(texto or "").strip()
    if not s:
        return []
    if len(s) <= max_len:
        return [s]
    partes: list[str] = []
    actual = ""
    for linea in s.splitlines(keepends=True):
        if len(actual) + len(linea) > max_len:
            if actual:
                partes.append(actual.rstrip())
                actual = ""
            while len(linea) > max_len:
                partes.append(linea[:max_len])
                linea = linea[max_len:]
        actual += linea
    if actual.strip():
        partes.append(actual.rstrip())
    return partes


# ==================== CODEC COMPACTO DE CALLBACK_DATA (<= 64 BYTES UTF-8) ====================
def encode_cb(accion: str, *args: Any) -> str:
    partes = ["t16", re.sub(r"[^a-z0-9_]", "", str(accion).lower())[:14]]
    for a in args:
        clean = str(a if a is not None else "").replace(":", "_").strip()
        partes.append(clean)
    data = ":".join(partes)
    raw = data.encode("utf-8")
    if len(raw) > MAX_CALLBACK_BYTES:
        # Recorta el ultimo argumento para garantizar cumplimiento estricto de Telegram
        exceso = len(raw) - MAX_CALLBACK_BYTES
        partes[-1] = partes[-1][: max(0, len(partes[-1]) - exceso - 2)]
        data = ":".join(partes)
    return data


def decode_cb(data: str) -> tuple[str, list[str]] | None:
    s = str(data or "").strip()
    if not s.startswith("t16:"):
        return None
    partes = s.split(":")
    if len(partes) < 2 or not partes[1]:
        return None
    return partes[1].lower(), partes[2:]


def btn(texto: str, accion: str, *args: Any) -> dict[str, str]:
    return {"text": str(texto)[:40], "callback_data": encode_cb(accion, *args)}


def btn_url(texto: str, url: str) -> dict[str, str]:
    return {"text": str(texto)[:40], "url": str(url)}


def markup(filas: list[list[dict[str, str]]]) -> dict[str, Any]:
    limpias = [[b for b in fila if b] for fila in filas if fila]
    return {"inline_keyboard": [f for f in limpias if f]}


# ==================== CONSTRUCTORES DE TARJETAS Y TECLADOS INTERACTIVOS ====================
def construir_menu_principal(svc: TitanServiceContainer) -> tuple[str, dict[str, Any]]:
    pipe = svc.crm.resumen_pipeline()
    fin = svc.finance.resumen_financiero()
    act = svc.time_tracker.obtener_sesion_activa()
    ag = pipe.get("agenda") or {}
    timer_txt = f"⏱️ Activo: <b>{esc_html(act['proyecto_nombre'][:32])}</b> ({act['formato_hms']})" if act else "⏱️ Cronómetro en pausa"

    txt = (
        "<b>⚡ ZEROTOUCH TITAN-OS v16.0 — CENTRO DE MANDO</b>\n"
        f"💰 Mes: <b>${fin['ingresos_mes_usd']:,.2f} USD</b> ({fin['progreso_meta_pct']}% meta) | Caja: <b>${fin['balance_caja_usd']:,.2f}</b>\n"
        f"🎯 Pipeline Ponderado: <b>${pipe['pipeline_ponderado_usd']:,.2f}</b> | Ganados: <b>{pipe['ganados']}</b> ({pipe['tasa_cierre_pct']}%)\n"
        f"📋 Tareas Pendientes: <b>{ag.get('pendientes_totales', 0)}</b> (Vencidas: <b>{ag.get('vencidas', 0)}</b>)\n"
        f"{timer_txt}"
    )
    kb = markup([
        [btn("🎯 Leads Activos", "leads", "nuevo", "0"), btn("📋 Agenda", "agenda", "0")],
        [btn("💰 Caja & Facturas", "caja"), btn("⏱️ Time Tracker", "timer_view")],
        [btn("🛡️ AEGIS-X v16", "aegis_view"), btn("⚙️ Workflows IFTTT", "wf_view")],
        [btn("🩺 Salud & Backup", "salud"), btn("🔄 Refrescar", "menu")],
    ])
    return txt, kb


def construir_tarjeta_lead(
    lead: dict[str, Any],
    *,
    timer_activo: dict[str, Any] | None = None,
    vista_360: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    lid = int(lead["id"])
    est = str(lead.get("estado") or "nuevo").upper()
    est_emoji = {
        "NUEVO": "🆕", "CONTACTADO": "📨", "NEGOCIANDO": "🤝",
        "GANADO": "🏆", "DESCARTADO": "🗑️",
    }.get(est, "📌")
    prio = f"\n🏷️ <i>{esc_html(lead['prioridad_tag'])}</i>" if lead.get("prioridad_tag") else ""
    aegis_info = ""
    if lead.get("aegis_score"):
        aegis_info = f" | AEGIS: <b>{float(lead['aegis_score']):.0f}/100</b>"
    extra_360 = ""
    if vista_360:
        cli = vista_360.get("cliente")
        cli_s = f"{esc_html(cli['nombre'])} (LTV ${cli['total_facturado_usd']:,.0f}, Rep {cli['reputacion_score']})" if cli else "Sin ficha"
        extra_360 = (
            f"\n👤 Cliente: {cli_s}"
            f"\n📨 Propuestas: <b>{len(vista_360.get('propuestas') or [])}</b> | "
            f"📋 Tareas: <b>{len(vista_360.get('tareas') or [])}</b> | "
            f"⏱️ Horas: <b>{vista_360.get('horas_registradas', 0)}h</b>"
        )
    notas_s = f"\n📝 <i>{esc_html(str(lead['notas'])[:160])}</i>" if lead.get("notas") else ""

    txt = (
        f"{est_emoji} <b>LEAD #{lid} [{est}]</b> — {esc_html(lead.get('plataforma') or lead.get('fuente'))}\n"
        f"📌 <b>{esc_html(str(lead.get('titulo') or '')[:140])}</b>\n"
        f"💵 {esc_html(lead.get('presupuesto') or 'Por definir')} | ⭐ Score: <b>{lead.get('score', 0)}/10</b>{aegis_info}"
        f"{prio}{extra_360}{notas_s}"
    )

    es_timer_este = bool(timer_activo and timer_activo.get("lead_id") == lid)
    b_timer = btn("⏹️ Stop Timer", "t_stop", lid) if es_timer_este else btn("⏱️ Iniciar Timer", "t_start", lid)

    fila_links: list[dict[str, str]] = []
    if str(lead.get("link") or "").startswith(("http://", "https://")):
        fila_links.append(btn_url("🔗 Abrir Oferta", str(lead["link"])))
    if str(lead.get("dm_url") or "").startswith(("http://", "https://")):
        fila_links.append(btn_url("💬 DM Directo", str(lead["dm_url"])))

    filas: list[list[dict[str, str]]] = [
        [btn("📨 Contactado", "st", lid, "contactado"), btn("🤝 Negociando", "st", lid, "negociando")],
        [btn("🏆 Ganado", "st", lid, "ganado"), btn("🗑️ Descartar", "st", lid, "descartado")],
        [btn("✍️ Pitch A/B", "pitch_gen", lid), b_timer],
        [btn("🔍 Vista 360", "l360", lid), btn("🧾 Factura Rápida", "fac_quick", lid)],
    ]
    if fila_links:
        filas.append(fila_links)
    filas.append([btn("⬅️ Leads", "leads", "nuevo", "0"), btn("🏠 Menú", "menu")])
    return truncar_tg(txt), markup(filas)


def construir_lista_leads(svc: TitanServiceContainer, estado: str = "nuevo", pagina: int = 0) -> tuple[str, dict[str, Any]]:
    pag = max(0, int(pagina))
    por_pag = 5
    est_q = "" if estado in ("", "todos", "*") else estado
    res = svc.crm.buscar_leads(estado=est_q, ordenar_por="score", limite=por_pag, offset=pag * por_pag)
    items = res["items"]
    tot = res["total"]

    etq = est_q.upper() if est_q else "TODOS"
    lineas = [f"<b>🎯 LEADS [{etq}]</b> ({tot} total | Pág {pag + 1})\n"]
    filas: list[list[dict[str, str]]] = []
    if not items:
        lineas.append("<i>No hay leads en esta vista.</i>")
    else:
        for it in items:
            lid = int(it["id"])
            lineas.append(
                f"• <b>#{lid}</b> [{it['score']}/10 | {esc_html(it['presupuesto'])}] "
                f"{esc_html(str(it['titulo'])[:58])} <i>({esc_html(it['plataforma'])})</i>"
            )
            filas.append([
                btn(f"#{lid} Abrir", "l360", lid),
                btn("✍️ Pitch", "pitch_gen", lid),
                btn("📨", "st", lid, "contactado"),
                btn("🗑️", "st", lid, "descartado"),
            ])

    filas.append([
        btn("🆕 Nuevos", "leads", "nuevo", "0"),
        btn("🤝 Negoc.", "leads", "negociando", "0"),
        btn("🏆 Ganados", "leads", "ganado", "0"),
    ])
    nav: list[dict[str, str]] = []
    if pag > 0:
        nav.append(btn("⬅️ Ant", "leads", estado or "todos", pag - 1))
    if (pag + 1) * por_pag < tot:
        nav.append(btn("Sig ➡️", "leads", estado or "todos", pag + 1))
    nav.append(btn("🏠 Menú", "menu"))
    filas.append(nav)
    return truncar_tg("\n".join(lineas)), markup(filas)


def construir_vista_agenda(svc: TitanServiceContainer, pagina: int = 0) -> tuple[str, dict[str, Any]]:
    pag = max(0, int(pagina))
    todas = svc.crm.listar_tareas(solo_pendientes=True, limite=50)
    por_pag = 5
    slice_t = todas[pag * por_pag : (pag + 1) * por_pag]
    vencidas = sum(1 for t in todas if t.get("vencida"))

    lineas = [f"<b>📋 AGENDA CRM</b> — Pendientes: <b>{len(todas)}</b> | Vencidas: <b>{vencidas}</b>\n"]
    filas: list[list[dict[str, str]]] = []
    if not slice_t:
        lineas.append("<i>🎉 Bandeja de tareas 100% limpia.</i>")
    else:
        for t in slice_t:
            tid = int(t["id"])
            ic = "🔴" if t.get("vencida") else ("🟠" if t["prioridad"] in ("critica", "alta") else "🔵")
            vence_s = f" (vence {str(t['vence_ts'])[:16]})" if t.get("vence_ts") else ""
            lineas.append(f"{ic} <b>#{tid}</b> [{t['prioridad'].upper()}] {esc_html(t['titulo'][:70])}{vence_s}")
            filas.append([
                btn(f"✅ #{tid} Hecha", "t_done", tid),
                btn("⏰ +24h", "t_snooze", tid),
            ])

    nav: list[dict[str, str]] = []
    if pag > 0:
        nav.append(btn("⬅️ Ant", "agenda", pag - 1))
    if (pag + 1) * por_pag < len(todas):
        nav.append(btn("Sig ➡️", "agenda", pag + 1))
    nav.append(btn("🔄 Refrescar", "agenda", pag))
    nav.append(btn("🏠 Menú", "menu"))
    filas.append(nav)
    return truncar_tg("\n".join(lineas)), markup(filas)


def construir_vista_caja(svc: TitanServiceContainer) -> tuple[str, dict[str, Any]]:
    fin = svc.finance.resumen_financiero()
    pendientes = svc.finance.listar_facturas(estado_pago="emitida", limite=4)
    lineas = [
        "<b>💰 FINANZAS &amp; CAJA TITAN-OS</b>\n",
        f"• Mes ({fin['mes_actual']}): <b>${fin['ingresos_mes_usd']:,.2f} USD</b> (≈ ${fin['ingresos_mes_cop']:,} COP)",
        f"• Meta mensual: <b>{fin['progreso_meta_pct']}%</b> de ${fin['meta_mensual_usd']:,.0f} USD",
        f"• Balance caja: <b>${fin['balance_caja_usd']:,.2f} USD</b> (≈ ${fin['balance_caja_cop']:,} COP)",
        f"• Por cobrar: <b>${fin['cuentas_por_cobrar_usd']:,.2f}</b> ({fin['facturas_pendientes']} facturas) | Comisiones: ${fin['comisiones_perdidas_usd']:,.2f}",
        f"• Reserva ({fin['reserva_pct']}%): <b>${fin['reserva_sugerida_mes_usd']:,.2f}</b> | Tarifa real 30d: <b>${fin['tarifa_efectiva_mes_usd_hr']}/hr</b>",
    ]
    filas: list[list[dict[str, str]]] = []
    if pendientes:
        lineas.append("\n<b>🧾 Facturas Pendientes (1-toque para marcar cobrada):</b>")
        for f in pendientes:
            fid = int(f["id"])
            lineas.append(f"• {esc_html(f['numero'])} — {esc_html(f['cliente_nombre'][:24])} (<b>${float(f['monto_bruto_usd']):,.0f}</b>)")
            filas.append([btn(f"💵 Cobrar {f['numero']} (${float(f['monto_bruto_usd']):.0f})", "fac_pay", fid)])

    filas.append([btn("🔄 Refrescar Caja", "caja"), btn("🏠 Menú", "menu")])
    return truncar_tg("\n".join(lineas)), markup(filas)


def construir_vista_timer(svc: TitanServiceContainer) -> tuple[str, dict[str, Any]]:
    prod = svc.time_tracker.resumen_productividad(dias=7)
    act = prod.get("sesion_activa")
    lineas = [
        "<b>⏱️ TIME TRACKER TITAN-OS (Últimos 7 días)</b>\n",
        f"• Horas totales: <b>{prod['horas_totales']}h</b> ({prod['formato_total_hms']}) | Facturable: <b>{prod['pct_facturable']}%</b>",
        f"• Valor devengado: <b>${prod['valor_devengado_usd']:,.2f} USD</b> (≈ ${prod['valor_devengado_cop']:,} COP)",
    ]
    filas: list[list[dict[str, str]]] = []
    if act:
        lineas.append(f"\n🟢 <b>EN CURSO:</b> {esc_html(act['proyecto_nombre'])} — <code>{act['formato_hms']}</code> (${act['valor_devengado_usd']})")
        filas.append([btn("⏹️ Detener Cronómetro", "t_stop", act.get("lead_id") or 0)])
    else:
        lineas.append("\n⚪ <i>Sin cronómetro activo ahora.</i>")
        filas.append([btn("▶️ Iniciar Sesión Libre", "t_start", 0)])
    filas.append([btn("🔄 Actualizar", "timer_view"), btn("🏠 Menú", "menu")])
    return truncar_tg("\n".join(lineas)), markup(filas)


def construir_vista_aegis(svc: TitanServiceContainer, perfil_activo: str = "equilibrado") -> tuple[str, dict[str, Any]]:
    drift = svc.aegis.calibrador.analizar_drift()
    ml = svc.aegis.ml.estado_actual()
    vc = svc.aegis.verdict_cache.stats()
    alerta_ic = {"normal": "🟢", "moderado": "🟡", "critico": "🔴"}.get(drift.nivel_alerta, "⚪")
    txt = (
        "<b>🛡️ AEGIS-X v16 — CONTROL FORENSE</b>\n\n"
        f"• Perfil activo: <b>{esc_html(perfil_activo.upper())}</b>\n"
        f"• Drift PSI: {alerta_ic} <b>{drift.psi:.3f}</b> ({drift.nivel_alerta.upper()} | Δtasa {drift.delta_tasa_pct:+.1f}%)\n"
        f"• ML Naive Bayes: <b>{'ACTIVO' if ml.habilitado else 'COLD-START'}</b> ({ml.muestras_pos}+ / {ml.muestras_neg}- | F1={ml.cv_f1:.2f})\n"
        f"• Caché Veredictos: {vc['entradas']} items ({vc['hit_rate_pct']}% hit)\n"
        f"• <i>{esc_html(drift.recomendacion)}</i>"
    )
    filas = [
        [btn("⚖️ Equilibrado", "aegis_prof", "equilibrado"), btn("🎯 Francotirador", "aegis_prof", "francotirador")],
        [btn("🐋 Caza Ballenas", "aegis_prof", "caza_ballenas"), btn("🌍 Remoto Pro", "aegis_prof", "remoto_pro")],
        [btn("🎛️ Auto-Calibrar F-beta", "aegis_cal"), btn("🧠 Re-entrenar ML", "aegis_ml")],
        [btn("🏠 Menú", "menu")],
    ]
    return txt, markup(filas)


def construir_vista_workflows(svc: TitanServiceContainer) -> tuple[str, dict[str, Any]]:
    reglas = svc.workflows.listar_reglas()
    lineas = [f"<b>⚙️ WORKFLOWS IFTTT</b> ({sum(1 for r in reglas if r.activa)}/{len(reglas)} activas)\n"]
    filas: list[list[dict[str, str]]] = []
    for r in reglas[:8]:
        ic = "🟢" if r.activa else "⚪"
        lineas.append(f"{ic} <b>#{r.id}</b> {esc_html(r.nombre[:48])} (<code>{esc_html(r.evento_disparador)}</code> | {r.ejecuciones}x)")
        filas.append([btn(f"{'⏸️ Pausar' if r.activa else '▶️ Activar'} #{r.id} {r.nombre[:20]}", "wf_tog", r.id)])
    filas.append([btn("🔄 Refrescar", "wf_view"), btn("🏠 Menú", "menu")])
    return truncar_tg("\n".join(lineas)), markup(filas)


def construir_vista_salud(svc: TitanServiceContainer) -> tuple[str, dict[str, Any]]:
    db_s = svc.db.verificar_salud()
    ai_s = svc.ai_router.estado_salud()
    bus_s = svc.bus.estadisticas()
    cbs = svc.circuit_breaker.resumen_todos()
    abiertos = [c["dominio"] for c in cbs if c["estado"] == "open"]
    txt = (
        "<b>🩺 SALUD DEL SISTEMA TITAN-OS v16</b>\n\n"
        f"• SQLite WAL: <b>{'OK' if db_s.integridad_ok else 'ERROR'}</b> (v{db_s.version_esquema} | {db_s.tamano_bytes/1024:.1f} KB | {len(db_s.tablas)} tablas)\n"
        f"• AI Router: <b>{esc_html(ai_s['estrategia'])}</b> | Cloud hoy: {ai_s['budget_cloud_hoy']['pct']}% | Cache hit: {ai_s['cache']['hit_rate_pct']}%\n"
        f"• EventBus: {bus_s['publicados']} publicados | {bus_s['callbacks_activos']} hooks | {bus_s['streams_activos']} SSE\n"
        f"• Circuit Breakers OPEN: <b>{len(abiertos)}</b> {esc_html(', '.join(abiertos[:3]))}"
    )
    kb = markup([
        [btn("💾 Backup SHA-256", "sys_bkp"), btn("🧹 Optimizar DB", "sys_opt")],
        [btn("🔌 Reset Circuits", "sys_cb"), btn("🔄 Refrescar", "salud")],
        [btn("🏠 Menú", "menu")],
    ])
    return txt, kb


# ==================== RESULTADO & ROUTER DE CALLBACKS 1-TOQUE ====================
@dataclass(slots=True)
class RespuestaCallback:
    handled: bool
    toast: str = ""
    show_alert: bool = False
    edit_text: str | None = None
    edit_markup: dict[str, Any] | None = None
    extra_messages: list[tuple[str, dict[str, Any] | None]] = field(default_factory=list)


class TitanTelegramCallbackRouter:
    """
    Despacha cualquier callback_data 't16:...' directamente contra TitanServiceContainer.
    100% determinista y testeable sin depender de red real.
    """

    def __init__(self, svc: TitanServiceContainer, perfil_getter: Any = None, perfil_setter: Any = None) -> None:
        self.svc = svc
        self._perfil_getter = perfil_getter
        self._perfil_setter = perfil_setter
        self._perfil_local = "equilibrado"
        self._pitch_cache: dict[str, dict[str, Any]] = {}  # "{lead_id}:{var}" -> info

    def _get_perfil(self) -> str:
        if callable(self._perfil_getter):
            try:
                return str(self._perfil_getter() or "equilibrado")
            except Exception:
                pass
        return self._perfil_local

    def _set_perfil(self, p: str) -> None:
        self._perfil_local = p
        if callable(self._perfil_setter):
            try:
                self._perfil_setter(p)
            except Exception:
                pass

    def despachar(self, callback_data: str) -> RespuestaCallback:
        parsed = decode_cb(callback_data)
        if parsed is None:
            return RespuestaCallback(handled=False)

        accion, args = parsed
        try:
            # --- MENU & VISTAS PRINCIPALES ---
            if accion == "menu":
                txt, kb = construir_menu_principal(self.svc)
                return RespuestaCallback(True, "Menú actualizado", edit_text=txt, edit_markup=kb)

            if accion == "leads":
                est = args[0] if len(args) >= 1 else "nuevo"
                pag = int(args[1]) if len(args) >= 2 and args[1].isdigit() else 0
                txt, kb = construir_lista_leads(self.svc, estado=est, pagina=pag)
                return RespuestaCallback(True, f"Leads [{est}]", edit_text=txt, edit_markup=kb)

            if accion == "l360" and args and args[0].isdigit():
                lid = int(args[0])
                v360 = self.svc.crm.obtener_lead_360(lid)
                if not v360:
                    return RespuestaCallback(True, f"Lead #{lid} no existe", show_alert=True)
                act = self.svc.time_tracker.obtener_sesion_activa()
                txt, kb = construir_tarjeta_lead(v360["lead"], timer_activo=act, vista_360=v360)
                return RespuestaCallback(True, f"Vista 360 Lead #{lid}", edit_text=txt, edit_markup=kb)

            # --- TRANSICION DE ESTADO DE LEAD (1-TOQUE) ---
            if accion == "st" and len(args) >= 2 and args[0].isdigit():
                lid = int(args[0])
                nuevo_est = args[1].lower()
                lead_prev = self.svc.crm.obtener_lead(lid)
                if not lead_prev:
                    return RespuestaCallback(True, f"Lead #{lid} no encontrado", show_alert=True)
                gan = float(lead_prev.get("presupuesto_num") or 0.0) if (nuevo_est == "ganado" and not lead_prev.get("ganancia_usd")) else None
                upd = self.svc.crm.actualizar_lead(lid, estado=nuevo_est, ganancia_usd=gan)
                if not upd:
                    return RespuestaCallback(True, "Estado inválido", show_alert=True)
                v360 = self.svc.crm.obtener_lead_360(lid)
                act = self.svc.time_tracker.obtener_sesion_activa()
                txt, kb = construir_tarjeta_lead(upd, timer_activo=act, vista_360=v360)
                return RespuestaCallback(True, f"Lead #{lid} -> {nuevo_est.upper()}", edit_text=txt, edit_markup=kb)

            # --- PITCH A/B 1-TOQUE + ENVIO AL CRM ---
            if accion == "pitch_gen" and args and args[0].isdigit():
                lid = int(args[0])
                res = self.svc.pitch_engine.generar_pitch_ab(lead_id=lid, num_variantes=2, auto_refinar=True)
                if not res.ok or not res.variantes:
                    return RespuestaCallback(True, "No se pudo generar pitch", show_alert=True)
                mejor = next((v for v in res.variantes if v.variante == res.mejor_variante), res.variantes[0])
                for v in res.variantes:
                    self._pitch_cache[f"{lid}:{v.variante}"] = {
                        "texto": v.texto, "precio": v.precio_sugerido_usd,
                        "template": v.template_base, "plat": res.plataforma,
                    }
                lineas = [
                    f"<b>✍️ PITCH A/B — LEAD #{lid}</b> ({esc_html(res.proveedor_ia)})\n",
                    f"🏆 Mejor: <b>Var {mejor.variante}</b> ({mejor.reporte.score_0_100}/100 · Grado <b>{mejor.reporte.grado}</b>)\n",
                ]
                fila_send: list[dict[str, str]] = []
                for v in res.variantes[:2]:
                    lineas.append(f"<b>--- VARIANTE {v.variante} ({v.reporte.score_0_100}/100) ---</b>\n<code>{esc_html(v.texto[:1200])}</code>\n")
                    fila_send.append(btn(f"📤 Registrar Envío {v.variante}", "pitch_send", lid, v.variante))
                kb = markup([fila_send, [btn("⬅️ Volver al Lead", "l360", lid), btn("🏠 Menú", "menu")]])
                return RespuestaCallback(True, f"Pitch A/B listo (Var {mejor.variante})", edit_text=truncar_tg("\n".join(lineas)), edit_markup=kb)

            if accion == "pitch_send" and len(args) >= 2 and args[0].isdigit():
                lid = int(args[0])
                var = args[1].upper()
                cached = self._pitch_cache.get(f"{lid}:{var}")
                if not cached:
                    return RespuestaCallback(True, "Genera el pitch primero", show_alert=True)
                prop = self.svc.pitch_engine.enviar_y_registrar_pitch(
                    lead_id=lid, texto_pitch=cached["texto"], variante=var,
                    precio_cotizado_usd=cached["precio"], template_nombre=cached["template"], plataforma=cached["plat"],
                )
                v360 = self.svc.crm.obtener_lead_360(lid)
                txt, kb = construir_tarjeta_lead(v360["lead"], timer_activo=self.svc.time_tracker.obtener_sesion_activa(), vista_360=v360)
                return RespuestaCallback(True, f"Propuesta #{prop['id']} (Var {var}) registrada en CRM ✅", edit_text=txt, edit_markup=kb)

            # --- TIME TRACKER 1-TOQUE ---
            if accion == "timer_view":
                txt, kb = construir_vista_timer(self.svc)
                return RespuestaCallback(True, "Time Tracker", edit_text=txt, edit_markup=kb)

            if accion == "t_start":
                lid = int(args[0]) if args and args[0].isdigit() and int(args[0]) > 0 else None
                ses = self.svc.time_tracker.iniciar_sesion(lead_id=lid)
                if lid:
                    v360 = self.svc.crm.obtener_lead_360(lid)
                    if v360:
                        txt, kb = construir_tarjeta_lead(v360["lead"], timer_activo=ses, vista_360=v360)
                        return RespuestaCallback(True, f"⏱️ Timer iniciado en Lead #{lid}", edit_text=txt, edit_markup=kb)
                txt, kb = construir_vista_timer(self.svc)
                return RespuestaCallback(True, f"⏱️ Timer iniciado ({ses['proyecto_nombre'][:24]})", edit_text=txt, edit_markup=kb)

            if accion == "t_stop":
                ses = self.svc.time_tracker.detener_sesion()
                if not ses:
                    return RespuestaCallback(True, "No había cronómetro activo", show_alert=True)
                lid = int(args[0]) if args and args[0].isdigit() and int(args[0]) > 0 else None
                if lid:
                    v360 = self.svc.crm.obtener_lead_360(lid)
                    if v360:
                        txt, kb = construir_tarjeta_lead(v360["lead"], timer_activo=None, vista_360=v360)
                        return RespuestaCallback(True, f"⏹️ Guardado {ses['formato_hms']} (${ses['valor_devengado_usd']})", edit_text=txt, edit_markup=kb)
                txt, kb = construir_vista_timer(self.svc)
                return RespuestaCallback(True, f"⏹️ Detenido: {ses['formato_hms']}", edit_text=txt, edit_markup=kb)

            # --- AGENDA / TAREAS ---
            if accion == "agenda":
                pag = int(args[0]) if args and args[0].isdigit() else 0
                txt, kb = construir_vista_agenda(self.svc, pagina=pag)
                return RespuestaCallback(True, "Agenda CRM", edit_text=txt, edit_markup=kb)

            if accion == "t_done" and args and args[0].isdigit():
                tid = int(args[0])
                t = self.svc.crm.completar_tarea(tid)
                txt, kb = construir_vista_agenda(self.svc, pagina=0)
                return RespuestaCallback(True, f"✅ Tarea #{tid} completada" if t else "Tarea no encontrada", edit_text=txt, edit_markup=kb)

            if accion == "t_snooze" and args and args[0].isdigit():
                tid = int(args[0])
                t = self.svc.crm.posponer_tarea(tid, horas=24.0)
                txt, kb = construir_vista_agenda(self.svc, pagina=0)
                return RespuestaCallback(True, f"⏰ Tarea #{tid} pospuesta +24h" if t else "Tarea no encontrada", edit_text=txt, edit_markup=kb)

            # --- FINANZAS & FACTURAS ---
            if accion == "caja":
                txt, kb = construir_vista_caja(self.svc)
                return RespuestaCallback(True, "Finanzas & Caja", edit_text=txt, edit_markup=kb)

            if accion == "fac_quick" and args and args[0].isdigit():
                lid = int(args[0])
                lead = self.svc.crm.obtener_lead(lid)
                if not lead:
                    return RespuestaCallback(True, f"Lead #{lid} no existe", show_alert=True)
                monto = float(lead.get("ganancia_usd") or lead.get("presupuesto_num") or 100.0)
                fac = self.svc.finance.emitir_factura(
                    cliente_nombre=str(lead.get("autor") or "Client"),
                    concepto=str(lead.get("titulo") or f"Project #{lid}")[:120],
                    monto_bruto_usd=monto,
                    pasarela="binance",
                    lead_id=lid,
                )
                txt, kb = construir_vista_caja(self.svc)
                return RespuestaCallback(True, f"🧾 Factura {fac['numero']} emitida (${monto:.0f})", edit_text=txt, edit_markup=kb)

            if accion == "fac_pay" and args and args[0].isdigit():
                fid = int(args[0])
                fac = self.svc.finance.marcar_factura_pagada(fid)
                txt, kb = construir_vista_caja(self.svc)
                return RespuestaCallback(
                    True,
                    f"💵 Cobrada {fac['numero']} (+${fac['monto_neto_usd']:.2f})" if fac else "No se pudo cobrar",
                    edit_text=txt, edit_markup=kb,
                )

            # --- AEGIS-X v16 ---
            if accion == "aegis_view":
                txt, kb = construir_vista_aegis(self.svc, self._get_perfil())
                return RespuestaCallback(True, "AEGIS-X v16", edit_text=txt, edit_markup=kb)

            if accion == "aegis_prof" and args:
                p = args[0].lower()
                if p not in PERFILES_AEGIS:
                    return RespuestaCallback(True, f"Perfil inválido: {p}", show_alert=True)
                self._set_perfil(p)
                txt, kb = construir_vista_aegis(self.svc, p)
                return RespuestaCallback(True, f"🛡️ Perfil cambiado a {p.upper()}", edit_text=txt, edit_markup=kb)

            if accion == "aegis_cal":
                p = self._get_perfil()
                res = self.svc.aegis.calibrar_automatico(perfil_nombre=p, aplicar=True)
                msg = f"Calibrado {p}: umbral={res['ajuste']['umbral_aprobacion']}" if res.get("calibrado") else str(res.get("motivo") or "Sin cambios")[:120]
                txt, kb = construir_vista_aegis(self.svc, p)
                return RespuestaCallback(True, msg, show_alert=not res.get("calibrado"), edit_text=txt, edit_markup=kb)

            if accion == "aegis_ml":
                st = self.svc.aegis.ml.entrenar_desde_db(forzar=True)
                txt, kb = construir_vista_aegis(self.svc, self._get_perfil())
                return RespuestaCallback(True, f"🧠 ML entrenado ({st.muestras_pos}+/{st.muestras_neg}-)", edit_text=txt, edit_markup=kb)

            # --- WORKFLOWS IFTTT ---
            if accion == "wf_view":
                txt, kb = construir_vista_workflows(self.svc)
                return RespuestaCallback(True, "Workflows IFTTT", edit_text=txt, edit_markup=kb)

            if accion == "wf_tog" and args and args[0].isdigit():
                rid = int(args[0])
                reg = self.svc.workflows.toggle_regla(rid)
                txt, kb = construir_vista_workflows(self.svc)
                st_s = "ACTIVA" if (reg and reg.activa) else "PAUSADA"
                return RespuestaCallback(True, f"Regla #{rid} -> {st_s}" if reg else "No encontrada", edit_text=txt, edit_markup=kb)

            # --- SALUD & MANTENIMIENTO ---
            if accion == "salud":
                txt, kb = construir_vista_salud(self.svc)
                return RespuestaCallback(True, "Salud TITAN-OS", edit_text=txt, edit_markup=kb)

            if accion == "sys_bkp":
                meta = self.svc.db.crear_backup_verificado()
                txt, kb = construir_vista_salud(self.svc)
                return RespuestaCallback(True, f"💾 Backup OK: {meta['archivo']}", edit_text=txt, edit_markup=kb)

            if accion == "sys_opt":
                opt = self.svc.db.optimizar()
                txt, kb = construir_vista_salud(self.svc)
                return RespuestaCallback(True, f"🧹 DB optimizada ({opt['duracion_ms']}ms)", edit_text=txt, edit_markup=kb)

            if accion == "sys_cb":
                n = self.svc.circuit_breaker.reiniciar()
                txt, kb = construir_vista_salud(self.svc)
                return RespuestaCallback(True, f"🔌 {n} circuit breaker(s) reiniciados", edit_text=txt, edit_markup=kb)

            return RespuestaCallback(True, f"Acción no soportada: {accion}")
        except Exception as e:
            return RespuestaCallback(True, f"Error: {str(e)[:120]}", show_alert=True)