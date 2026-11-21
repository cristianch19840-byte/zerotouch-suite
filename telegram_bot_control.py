import os
import sys
import html
import time
import threading
from urllib.parse import urlparse

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core_ia import (
    C,
    SESSION,
    DEFAULT_FUENTES_ACTIVAS,
    safe_float,
    safe_int,
    log_evento,
    cargar_config,
    guardar_config,
    preparar_db,
    obtener_salud_fuentes,
)
from modulo_a_radar_whop.motor_zerotouch_v4 import (
    ejecutar_ciclo,
    enviar_resumen_telegram,
    publicar_telegram,
    revisar_recordatorios_followup,
)
from modulo_b_ejecutor.copiloto import (
    descargar_oferta_universal,
    cargar_desde_crm_completo,
    analizar_oferta_completo,
)
from modulo_c_whop.empaquetador import empaquetar_producto_whop
from modulo_d_marketing.iman_clientes import responder_objecion_ia

TG_TOKEN = os.getenv("TELEGRAM_TOKEN")
TG_CHANNEL_ID = str(os.getenv("TELEGRAM_CHAT_ID") or "")

_BOT_SCAN_LOCK = threading.Lock()

ALIAS_FUENTES = {
    "rd": "reddit",
    "reddit": "reddit",
    "fl": "freelancer",
    "freelancer": "freelancer",
    "gh": "github_bounties",
    "github": "github_bounties",
    "bounties": "github_bounties",
    "github_bounties": "github_bounties",
    "hn": "hackernews",
    "hackernews": "hackernews",
    "rok": "remoteok",
    "remoteok": "remoteok",
    "wwr": "weworkremotely",
    "weworkremotely": "weworkremotely",
    "rem": "remotive",
    "remotive": "remotive",
    "jcy": "jobicy",
    "jobicy": "jobicy",
    "him": "himalayas",
    "himalayas": "himalayas",
    "wn": "workingnomads",
    "workingnomads": "workingnomads",
    "arb": "arbeitnow",
    "arbeitnow": "arbeitnow",
    "rss": "rss_custom",
    "rss_custom": "rss_custom",
    "devto": "devto",
    "lobsters": "lobsters",
    "lob": "lobsters",
    "pyorg": "python_org",
    "python_org": "python_org",
    "bpro": "bounties_pro",
    "bounties_pro": "bounties_pro",
    "ffeeds": "freelance_feeds",
    "freelance_feeds": "freelance_feeds",
}

AYUDA_HTML = (
    "<b>🤖 ZEROTOUCH OMNI-GRID v13.0 — CONTROL REMOTO</b>\n\n"
    "<b>📡 RADAR &amp; PLATAFORMAS</b>\n"
    "<code>/scan</code> — Barrido completo (12+ plataformas + Batch IA)\n"
    "<code>/dryrun</code> — Prueba todas las fuentes en vivo (0 tokens)\n"
    "<code>/fuentes</code> — Estado ON/OFF y salud de cada plataforma\n"
    "<code>/toggle &lt;fuente|corto&gt;</code> — Prende/apaga fuente (ej. <code>/toggle fl</code>)\n"
    "<code>/rss &lt;url&gt; [nombre]</code> — Agrega un feed RSS propio\n\n"
    "<b>🎯 LEADS &amp; CIERRE</b>\n"
    "<code>/top [freelance|bounty|remoto]</code> — Top 5 leads nuevos\n"
    "<code>/buscar &lt;palabra&gt;</code> — Busca en tu CRM (ej. <code>/buscar shopify</code>)\n"
    "<code>/pitch &lt;cualquier link o #ID&gt;</code> — Estrategia + Pitch A/B + Codigo\n"
    "<code>/negociar &lt;mensaje cliente&gt;</code> — Contraofertas + Red Flag\n"
    "<code>/pipeline</code> — Plata viva en negociacion\n"
    "<code>/followups</code> — Dispara recordatorios pendientes\n\n"
    "<b>💰 CRM &amp; NEGOCIO</b>\n"
    "<code>/estado &lt;ID&gt; &lt;contactado|negociando|descartado&gt;</code>\n"
    "<code>/ganado &lt;ID&gt; &lt;USD&gt;</code> — Marca ganado y suma ingresos\n"
    "<code>/borrar &lt;ID&gt;</code> — Elimina un lead\n"
    "<code>/whop &lt;nombre&gt;</code> — Empaqueta ultimo script a .ZIP\n"
    "<code>/stats</code> — Resumen global y tokens ahorrados"
)

def responder(chat_id: str, texto_html: str) -> None:
    publicar_telegram(texto_html, texto_html, chat_id=str(chat_id))

def resolver_clave_fuente(texto: str) -> str | None:
    k = (texto or "").strip().lower()
    if k in ("corto", "solo_corto", "solo_freelance", "solo_freelance_corto"):
        return "solo_freelance_corto"
    return ALIAS_FUENTES.get(k)

def construir_texto_fuentes() -> str:
    cfg = cargar_config()
    activas = cfg.get("fuentes_activas") or dict(DEFAULT_FUENTES_ACTIVAS)
    conn = preparar_db()
    try:
        salud = obtener_salud_fuentes(conn)
    finally:
        conn.close()

    por_clave: dict[str, dict] = {}
    for s in salud:
        kc = s.get("clave_config") or ""
        if kc not in por_clave:
            por_clave[kc] = {"ok": 0, "tot": 0, "bruto": 0, "tech": 0}
        por_clave[kc]["tot"] += 1
        if s.get("ok"):
            por_clave[kc]["ok"] += 1
        por_clave[kc]["bruto"] += safe_int(s.get("bruto", 0))
        por_clave[kc]["tech"] += safe_int(s.get("tech", 0))

    solo_c = bool(cfg.get("solo_freelance_corto", False))
    lineas = [
        "<b>🌐 PLATAFORMAS OMNI-GRID v13.0</b>",
        f"🎯 <b>Solo Freelance Corto/Bounties:</b> {'SI' if solo_c else 'NO (Incluye Remoto)'}\n",
    ]
    for clave in DEFAULT_FUENTES_ACTIVAS:
        on = activas.get(clave, True)
        st = por_clave.get(clave)
        ic = "🟢" if on else "⚪"
        if st:
            det = f"{st['ok']}/{st['tot']} OK | {st['bruto']} raw | {st['tech']} tech"
        else:
            det = "sin datos aun"
        lineas.append(f"{ic} <code>{clave:<15}</code> — {det}")

    feeds = cfg.get("feeds_rss_custom") or []
    lineas.append(f"\n📡 <b>Feeds RSS custom:</b> {len(feeds)}")
    lineas.append("<i>Usa /toggle &lt;nombre&gt; o /toggle corto para cambiar.</i>")
    return "\n".join(lineas)

def procesar_comando(chat_id: str, texto: str) -> None:
    partes = texto.strip().split(maxsplit=1)
    cmd = partes[0].lower().split("@")[0]
    arg = partes[1].strip() if len(partes) > 1 else ""
    print(f"{C.CYAN}[TG-CMD] ({chat_id}) -> {cmd} {arg[:55]}{C.RESET}", flush=True)

    try:
        if cmd in ("/start", "/help"):
            responder(chat_id, AYUDA_HTML)

        elif cmd == "/scan":
            if not _BOT_SCAN_LOCK.acquire(blocking=False):
                responder(chat_id, "⏳ Ya hay un escaneo corriendo ahorita mismo, bro. Espera a que termine.")
                return
            try:
                responder(chat_id, "🚀 <b>Escaneando 12+ plataformas en modo OMNI-GRID...</b>")
                res = ejecutar_ciclo(modo_sonido=True, dry_run=False)
                responder(
                    chat_id,
                    f"✅ <b>Barrido OMNI terminado en {res['segundos']}s</b>\n"
                    f"🌐 Fuentes OK: {res['fuentes_ok']}/{res['fuentes_total']}\n"
                    f"🛡️ Filtrados 0-Tokens: {res['descartados']}\n"
                    f"🤖 Evaluados por IA: {res['ia']}\n"
                    f"⚡ Alertas enviadas: {res['alertas']}",
                )
            finally:
                _BOT_SCAN_LOCK.release()

        elif cmd == "/dryrun":
            if not _BOT_SCAN_LOCK.acquire(blocking=False):
                responder(chat_id, "⏳ Ya hay un escaneo activo. Intenta en unos segundos.")
                return
            try:
                responder(chat_id, "🧪 <b>Corriendo Dry-Run de todas las plataformas (0 tokens IA)...</b>")
                res = ejecutar_ciclo(modo_sonido=False, dry_run=True)
                top = res.get("candidatas_preview") or []
                lineas = [
                    f"🧪 <b>DRY-RUN OMNI ({res['segundos']}s | 0 Tokens)</b>",
                    f"🌐 Fuentes OK: <b>{res['fuentes_ok']}/{res['fuentes_total']}</b> | Bruto: {res['bruto']}",
                    f"🛡️ Bloqueados: {res['descartados']} | Nuevas tech: {len(top)}\n",
                ]
                if top:
                    lineas.append("<b>Top candidatas nuevas:</b>")
                    for c in top[:6]:
                        lineas.append(f"• [{html.escape(c['plataforma'])} | {html.escape(c.get('presupuesto') or '$?')}] {html.escape(c['titulo'][:65])}")
                else:
                    lineas.append("<i>Todas las ofertas vigentes ya estan en cache de vistos.</i>")
                responder(chat_id, "\n".join(lineas))
            finally:
                _BOT_SCAN_LOCK.release()

        elif cmd == "/fuentes":
            responder(chat_id, construir_texto_fuentes())

        elif cmd == "/toggle":
            clave = resolver_clave_fuente(arg)
            if not clave:
                responder(
                    chat_id,
                    "⚠️ Plataforma no reconocida.\nOpciones: <code>reddit</code>, <code>fl</code>, <code>gh</code>, <code>hn</code>, "
                    "<code>remoteok</code>, <code>wwr</code>, <code>remotive</code>, <code>jobicy</code>, <code>himalayas</code>, "
                    "<code>workingnomads</code>, <code>arbeitnow</code>, <code>rss</code> o <code>corto</code>.",
                )
                return
            cfg = cargar_config()
            if clave == "solo_freelance_corto":
                nuevo = not bool(cfg.get("solo_freelance_corto", False))
                cfg["solo_freelance_corto"] = nuevo
                guardar_config(cfg)
                responder(chat_id, f"🎯 <b>Solo Freelance Corto/Bounties:</b> {'ACTIVADO ✅' if nuevo else 'DESACTIVADO 🌍'}")
            else:
                fa = dict(cfg.get("fuentes_activas") or DEFAULT_FUENTES_ACTIVAS)
                nuevo = not bool(fa.get(clave, True))
                fa[clave] = nuevo
                cfg["fuentes_activas"] = fa
                guardar_config(cfg)
                log_evento(f"TG-Bot toggle '{clave}' -> {'ON' if nuevo else 'OFF'}")
                responder(chat_id, f"{'🟢' if nuevo else '⚪'} Plataforma <b>{html.escape(clave)}</b> ahora esta <b>{'ACTIVA' if nuevo else 'PAUSADA'}</b>.")

        elif cmd == "/rss":
            toks = arg.split(maxsplit=1)
            if not toks or not toks[0].startswith(("http://", "https://")):
                responder(chat_id, "⚠️ Uso: <code>/rss https://ejemplo.com/jobs.rss NombreOpcional</code>")
                return
            url_rss = toks[0].strip()
            nom_rss = toks[1].strip()[:40] if len(toks) > 1 else (urlparse(url_rss).netloc.replace("www.", "") or "RSS-Custom")
            cfg = cargar_config()
            feeds = list(cfg.get("feeds_rss_custom") or [])
            existentes = {f if isinstance(f, str) else f.get("url") for f in feeds}
            if url_rss in existentes:
                responder(chat_id, "ℹ️ Ese feed RSS ya estaba guardado en tu radar.")
                return
            feeds.append({"nombre": nom_rss, "url": url_rss})
            cfg["feeds_rss_custom"] = feeds
            guardar_config(cfg)
            responder(chat_id, f"📡 Feed RSS <b>{html.escape(nom_rss)}</b> agregado!\nTotal feeds custom: <b>{len(feeds)}</b>.")

        elif cmd == "/stats":
            enviar_resumen_telegram(chat_id=chat_id)

        elif cmd == "/pipeline":
            conn = preparar_db()
            try:
                rows = conn.execute(
                    "SELECT id, estado, COALESCE(NULLIF(plataforma,''), fuente), presupuesto, titulo FROM leads WHERE estado IN ('contactado', 'negociando') ORDER BY presupuesto_num DESC, id DESC LIMIT 8"
                ).fetchall()
                total_pipe = conn.execute("SELECT COALESCE(SUM(presupuesto_num), 0) FROM leads WHERE estado IN ('contactado', 'negociando')").fetchone()[0]
            finally:
                conn.close()
            if not rows:
                responder(chat_id, "💼 Pipeline vacio. Marca leads como <code>contactado</code> o <code>negociando</code>.")
                return
            lineas = [f"<b>💼 PIPELINE VIVO (~${total_pipe:.0f} USD)</b>\n"]
            for lid, est, plat, pres, tit in rows:
                lineas.append(f"<b>#{lid}</b> [{est.upper()} | {html.escape(plat)} | {html.escape(pres)}] {html.escape(tit[:55])}")
            responder(chat_id, "\n".join(lineas))

        elif cmd == "/followups":
            conn = preparar_db()
            try:
                env = revisar_recordatorios_followup(conn, cargar_config())
            finally:
                conn.close()
            responder(chat_id, f"⏰ Revisados: <b>{env}</b> recordatorio(s) enviado(s).")

        elif cmd == "/whop":
            nombre = arg or "ZeroTouch Automation Tool"
            responder(chat_id, f"📦 <b>Empaquetando '{html.escape(nombre)}' en tu PC...</b>")
            res = empaquetar_producto_whop("", nombre)
            if res.get("error"):
                responder(chat_id, f"❌ {html.escape(res['error'])}")
            else:
                responder(chat_id, f"✅ <b>ZIP Whop generado en tu PC!</b>\n📁 <code>{html.escape(res['zip_path'])}</code>")

        elif cmd == "/top":
            filtro_tipo = arg.strip().lower()
            conn = preparar_db()
            try:
                if filtro_tipo in ("freelance", "bounty", "remoto"):
                    rows = conn.execute(
                        "SELECT id, COALESCE(NULLIF(plataforma,''), fuente), tipo_trabajo, score, presupuesto, titulo, link FROM leads WHERE estado = 'nuevo' AND tipo_trabajo = ? ORDER BY score DESC, presupuesto_num DESC, id DESC LIMIT 5",
                        (filtro_tipo,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT id, COALESCE(NULLIF(plataforma,''), fuente), tipo_trabajo, score, presupuesto, titulo, link FROM leads WHERE estado = 'nuevo' ORDER BY score DESC, presupuesto_num DESC, id DESC LIMIT 5"
                    ).fetchall()
            finally:
                conn.close()
            if not rows:
                responder(chat_id, f"📭 No hay leads nuevos{(' tipo ' + filtro_tipo) if filtro_tipo in ('freelance','bounty','remoto') else ''}. Manda <code>/scan</code>.")
                return
            cab = f"<b>🔥 TOP 5 LEADS NUEVOS{(' (' + filtro_tipo.upper() + ')') if filtro_tipo in ('freelance','bounty','remoto') else ''}</b>\n"
            lineas = [cab]
            for lid, plat, tipo, sc, pres, tit, link in rows:
                ic_t = {"bounty": "💎", "remoto": "🌍"}.get(tipo or "freelance", "💼")
                lineas.append(f"<b>#{lid}</b> {ic_t} [{sc}/10 | {html.escape(pres)} | {html.escape(plat)}]\n<a href=\"{html.escape(link)}\">{html.escape(tit[:75])}</a>")
            lineas.append("\n<i>Usa /pitch #ID para generar estrategia y pitch adaptado.</i>")
            responder(chat_id, "\n\n".join(lineas))

        elif cmd == "/buscar":
            if not arg:
                responder(chat_id, "⚠️ Uso: <code>/buscar python</code> o <code>/buscar freelancer</code>")
                return
            patron = f"%{arg.lower()}%"
            conn = preparar_db()
            try:
                rows = conn.execute(
                    """
                    SELECT id, estado, COALESCE(NULLIF(plataforma,''), fuente), score, presupuesto, titulo, link
                    FROM leads
                    WHERE lower(titulo) LIKE ? OR lower(fuente) LIKE ? OR lower(plataforma) LIKE ?
                       OR lower(categoria) LIKE ? OR lower(notas) LIKE ?
                    ORDER BY score DESC, id DESC LIMIT 6
                    """,
                    (patron, patron, patron, patron, patron),
                ).fetchall()
            finally:
                conn.close()
            if not rows:
                responder(chat_id, f"🔎 No encontre leads en tu CRM con <code>{html.escape(arg)}</code>.")
                return
            lineas = [f"<b>🔎 RESULTADOS CRM PARA '{html.escape(arg)}'</b>\n"]
            for lid, est, plat, sc, pres, tit, link in rows:
                lineas.append(f"<b>#{lid}</b> [{est.upper()} | {sc}/10 | {html.escape(plat)} | {html.escape(pres)}]\n<a href=\"{html.escape(link)}\">{html.escape(tit[:70])}</a>")
            responder(chat_id, "\n\n".join(lineas))

        elif cmd == "/pitch":
            if not arg:
                responder(chat_id, "⚠️ Uso: <code>/pitch https://...</code> (cualquier plataforma) o <code>/pitch #3</code>")
                return
            responder(chat_id, "🧠 <b>Extrayendo oferta y aplicando playbook de la plataforma...</b>")
            autor = titulo = plat = tipo = ""
            if arg.startswith("#") and arg[1:].isdigit():
                oferta, autor, titulo, plat, tipo = cargar_desde_crm_completo(int(arg[1:]))
            elif arg.startswith(("http://", "https://")):
                oferta, autor, titulo, plat = descargar_oferta_universal(arg)
            else:
                oferta = arg
            if not oferta:
                responder(chat_id, "❌ No pude extraer ese lead o enlace.")
                return
            res = analizar_oferta_completo(oferta, autor=autor, titulo=titulo, guardar_archivos=True, plataforma=plat, tipo_trabajo=tipo)
            if not res:
                responder(chat_id, "❌ Gemini no respondio en este intento.")
                return
            msg = (
                f"<b>🌐 {html.escape(res.get('plataforma', 'Auto').upper())}</b> | {html.escape((res.get('confianza') or '')[:80])}\n"
                f"<b>🎯 ESTRATEGIA:</b> {html.escape((res.get('estrategia') or '')[:260])}\n"
                f"<b>🚩 ALERTAS:</b> {html.escape((res.get('red_flags') or 'OK')[:220])}\n\n"
                f"<b>💵 PRECIOS:</b>\n{html.escape(res['precios'][:320])}\n\n"
                f"<b>📩 PITCH A (toca para copiar):</b>\n<code>{html.escape(res['pitch_a'][:950])}</code>\n\n"
                f"<b>💬 PITCH B (alternativa):</b>\n<code>{html.escape(res['pitch_b'][:900])}</code>\n\n"
                f"✅ <i>Script base guardado en tu PC (borrador_cliente.py).</i>"
            )
            responder(chat_id, msg)

        elif cmd == "/negociar":
            if not arg:
                responder(chat_id, "⚠️ Uso: <code>/negociar The client says $100 is too expensive</code>")
                return
            responder(chat_id, "⚔️ <b>Calculando contraofertas...</b>")
            res = responder_objecion_ia("Proyecto freelance Python/Automatizacion", arg)
            if not res:
                responder(chat_id, "❌ No se pudo generar respuesta ahora.")
                return
            msg = (
                f"<b>🚩 RIESGO:</b> {html.escape((res.get('red_flag') or '')[:200])}\n"
                f"<b>🧠 LECTURA:</b> {html.escape(res['consejo'][:400])}\n\n"
                f"<b>🛡️ OPCION FIRME (toca para copiar):</b>\n<code>{html.escape(res['firme'][:950])}</code>\n\n"
                f"<b>🤝 OPCION FLEXIBLE:</b>\n<code>{html.escape(res['flexible'][:950])}</code>"
            )
            responder(chat_id, msg)

        elif cmd == "/estado":
            p = arg.split()
            if len(p) < 2 or not p[0].lstrip("#").isdigit():
                responder(chat_id, "⚠️ Uso: <code>/estado 4 contactado</code>")
                return
            lid = safe_int(p[0].lstrip("#"))
            est = p[1].lower()
            conn = preparar_db()
            try:
                conn.execute(
                    """
                    UPDATE leads
                    SET estado = ?,
                        contactado_ts = CASE WHEN ? = 'contactado' AND estado != 'contactado' THEN CURRENT_TIMESTAMP ELSE contactado_ts END,
                        followup_enviado = CASE WHEN ? = 'contactado' AND estado != 'contactado' THEN 0 ELSE followup_enviado END
                    WHERE id = ?
                    """,
                    (est, est, est, lid),
                )
                conn.commit()
            finally:
                conn.close()
            responder(chat_id, f"✅ Lead <b>#{lid}</b> actualizado a <b>{html.escape(est.upper())}</b>.")

        elif cmd == "/ganado":
            p = arg.split()
            if len(p) < 2 or not p[0].lstrip("#").isdigit():
                responder(chat_id, "⚠️ Uso: <code>/ganado 4 120</code>")
                return
            lid = safe_int(p[0].lstrip("#"))
            usd = safe_float(p[1], -1.0)
            if usd < 0:
                responder(chat_id, "⚠️ Monto invalido.")
                return
            conn = preparar_db()
            try:
                conn.execute("UPDATE leads SET estado = 'ganado', ganancia_usd = ? WHERE id = ?", (usd, lid))
                conn.commit()
                total = conn.execute("SELECT COALESCE(SUM(ganancia_usd), 0) FROM leads WHERE estado = 'ganado'").fetchone()[0]
            finally:
                conn.close()
            responder(chat_id, f"🏆 <b>CORONASTE BRO!</b> Lead #{lid} marcado GANADO (+${usd:.2f} USD).\n💵 Total acumulado: <b>${total:.2f} USD</b>.")

        elif cmd == "/borrar":
            lid_s = arg.lstrip("#").strip()
            if not lid_s.isdigit():
                responder(chat_id, "⚠️ Uso: <code>/borrar 4</code>")
                return
            conn = preparar_db()
            try:
                conn.execute("DELETE FROM leads WHERE id = ?", (int(lid_s),))
                conn.commit()
            finally:
                conn.close()
            responder(chat_id, f"🗑️ Lead <b>#{lid_s}</b> eliminado del CRM.")
    except Exception as e:
        print(f"{C.RED}[!] Error procesando {cmd}: {e}{C.RESET}", flush=True)
        responder(chat_id, f"❌ Error ejecutando <code>{html.escape(cmd)}</code>: {html.escape(str(e)[:180])}")

def obtener_offset_inicial(url: str) -> int:
    try:
        r = SESSION.get(url, params={"timeout": 0}, timeout=8)
        if r.status_code == 200:
            res = r.json().get("result", [])
            if res:
                return res[-1]["update_id"] + 1
    except Exception:
        pass
    return 0

def obtener_chats_autorizados() -> set[str]:
    cfg = cargar_config()
    admin_id = str(cfg.get("telegram_admin_id") or "").strip()
    return {x for x in (TG_CHANNEL_ID, admin_id) if x}

def main() -> None:
    if not TG_TOKEN:
        print(f"{C.RED}[!] Falta TELEGRAM_TOKEN en .env{C.RESET}")
        return

    url = f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates"
    offset = obtener_offset_inicial(url)

    print(f"\n{C.BOLD}{C.GREEN}=== CONTROL REMOTO TELEGRAM 2-VIAS OMNI-GRID v13.0 ==={C.RESET}")
    print(f"{C.DIM}Chats autorizados: {obtener_chats_autorizados() or 'Solo canal .env'} | Cola vieja purgada.")
    print(f"Escribe /help o /fuentes en tu canal o DM privado. Ctrl+C para salir.{C.RESET}\n")

    try:
        while True:
            try:
                r = SESSION.get(url, params={"timeout": 25, "offset": offset}, timeout=32)
                if r.status_code == 200:
                    autorizados = obtener_chats_autorizados()
                    for upd in r.json().get("result", []):
                        offset = upd["update_id"] + 1
                        msg = upd.get("message") or upd.get("channel_post")
                        if not msg or not msg.get("text"):
                            continue
                        cid = str(msg["chat"]["id"])
                        txt = msg["text"].strip()
                        if not txt.startswith("/"):
                            continue
                        if cid not in autorizados:
                            print(f"{C.YELLOW}[!] Mensaje ignorado de chat_id={cid}. Agrega '{cid}' en Ajustes -> Telegram Admin ID.{C.RESET}", flush=True)
                            continue
                        procesar_comando(cid, txt)
                else:
                    time.sleep(3)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"{C.YELLOW}[~] Reconectando polling ({e})...{C.RESET}", flush=True)
                time.sleep(4)
    except KeyboardInterrupt:
        print(f"\n{C.YELLOW}[*] Bot de control remoto detenido.{C.RESET}\n")

if __name__ == "__main__":
    main()