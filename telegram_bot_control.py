import os
import sys
import html
import time

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core_ia import C, SESSION, cargar_config, preparar_db
from modulo_a_radar_whop.motor_zerotouch_v4 import ejecutar_ciclo, enviar_resumen_telegram, publicar_telegram
from modulo_b_ejecutor.copiloto import descargar_post_reddit, cargar_desde_crm, analizar_oferta_completo
from modulo_d_marketing.iman_clientes import responder_objecion_ia

TG_TOKEN = os.getenv("TELEGRAM_TOKEN")
TG_CHANNEL_ID = str(os.getenv("TELEGRAM_CHAT_ID") or "")

AYUDA_HTML = (
    "<b>🤖 ZEROTOUCH PRIME — CONTROL REMOTO TELEGRAM</b>\n\n"
    "<code>/scan</code> — Lanza un barrido inmediato de 16 fuentes\n"
    "<code>/stats</code> — KPIs en vivo, USD ganados y tokens ahorrados\n"
    "<code>/top</code> — Muestra tus 5 mejores leads nuevos\n"
    "<code>/pitch &lt;link Reddit o #ID&gt;</code> — Genera Pitch A/B + Precios\n"
    "<code>/negociar &lt;mensaje cliente&gt;</code> — Respuestas anti-objecion\n"
    "<code>/estado &lt;ID&gt; &lt;contactado|negociando|descartado&gt;</code>\n"
    "<code>/ganado &lt;ID&gt; &lt;USD&gt;</code> — Marca lead ganado y suma plata\n"
    "<code>/help</code> — Muestra este menu"
)

def responder(chat_id: str, texto_html: str) -> None:
    publicar_telegram(texto_html, texto_html, chat_id=str(chat_id))

def procesar_comando(chat_id: str, texto: str) -> None:
    partes = texto.strip().split(maxsplit=1)
    cmd = partes[0].lower().split("@")[0]
    arg = partes[1].strip() if len(partes) > 1 else ""
    print(f"{C.CYAN}[TG-CMD] ({chat_id}) -> {cmd} {arg[:50]}{C.RESET}", flush=True)

    if cmd in ("/start", "/help"):
        responder(chat_id, AYUDA_HTML)

    elif cmd == "/scan":
        responder(chat_id, "⏳ <b>Escaneando 16 fuentes en modo PRIME...</b>")
        res = ejecutar_ciclo(modo_sonido=True)
        responder(
            chat_id,
            f"✅ <b>Barrido terminado en {res['segundos']}s</b>\n"
            f"🛡️ Filtrados 0-Tokens: {res['descartados']}\n"
            f"🤖 Analizados por IA: {res['ia']}\n"
            f"⚡ Alertas enviadas: {res['alertas']}",
        )

    elif cmd == "/stats":
        enviar_resumen_telegram(chat_id=chat_id)

    elif cmd == "/top":
        conn = preparar_db()
        try:
            rows = conn.execute(
                "SELECT id, fuente, score, presupuesto, titulo, link FROM leads WHERE estado = 'nuevo' ORDER BY score DESC, id DESC LIMIT 5"
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            responder(chat_id, "📭 No tienes leads nuevos pendientes. Manda <code>/scan</code>.")
            return
        lineas = ["<b>🔥 TOP 5 LEADS NUEVOS EN TU CRM</b>\n"]
        for lid, fuente, sc, pres, tit, link in rows:
            lineas.append(f"<b>#{lid}</b> [{sc}/10 | {html.escape(pres)} | {html.escape(fuente)}]\n<a href=\"{html.escape(link)}\">{html.escape(tit[:75])}</a>")
        lineas.append("\n<i>Usa /pitch #ID para generar estrategia y pitch.</i>")
        responder(chat_id, "\n\n".join(lineas))

    elif cmd == "/pitch":
        if not arg:
            responder(chat_id, "⚠️ Uso: <code>/pitch https://reddit.com/...</code> o <code>/pitch #3</code>")
            return
        responder(chat_id, "🧠 <b>Generando Pitch A/B, precios y estrategia...</b>")
        autor = titulo = ""
        if arg.startswith("#") and arg[1:].isdigit():
            oferta, autor, titulo = cargar_desde_crm(int(arg[1:]))
        elif arg.startswith("http") and "reddit.com" in arg:
            oferta, autor, titulo = descargar_post_reddit(arg)
        else:
            oferta = arg
        if not oferta:
            responder(chat_id, "❌ No pude cargar ese lead o enlace.")
            return
        res = analizar_oferta_completo(oferta, autor=autor, titulo=titulo, guardar_archivos=True)
        if not res:
            responder(chat_id, "❌ Gemini no respondio en este intento.")
            return
        msg = (
            f"<b>🎯 DIAGNOSTICO:</b>\n{html.escape(res['diagnostico'])}\n\n"
            f"<b>💵 PRECIOS:</b>\n{html.escape(res['precios'])}\n\n"
            f"<b>📩 PITCH A (toca para copiar):</b>\n<code>{html.escape(res['pitch_a'])}</code>\n\n"
            f"<b>💬 PITCH B (alternativa):</b>\n<code>{html.escape(res['pitch_b'])}</code>\n\n"
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
            f"<b>🧠 LECTURA:</b> {html.escape(res['consejo'])}\n\n"
            f"<b>🛡️ OPCION FIRME (toca para copiar):</b>\n<code>{html.escape(res['firme'])}</code>\n\n"
            f"<b>🤝 OPCION FLEXIBLE:</b>\n<code>{html.escape(res['flexible'])}</code>"
        )
        responder(chat_id, msg)

    elif cmd == "/estado":
        p = arg.split()
        if len(p) < 2 or not p[0].lstrip("#").isdigit():
            responder(chat_id, "⚠️ Uso: <code>/estado 4 contactado</code>")
            return
        lid = int(p[0].lstrip("#"))
        est = p[1].lower()
        conn = preparar_db()
        try:
            conn.execute("UPDATE leads SET estado = ? WHERE id = ?", (est, lid))
            conn.commit()
        finally:
            conn.close()
        responder(chat_id, f"✅ Lead <b>#{lid}</b> actualizado a <b>{html.escape(est.upper())}</b>.")

    elif cmd == "/ganado":
        p = arg.split()
        if len(p) < 2 or not p[0].lstrip("#").isdigit():
            responder(chat_id, "⚠️ Uso: <code>/ganado 4 120</code>")
            return
        lid = int(p[0].lstrip("#"))
        try:
            usd = float(p[1].replace("$", ""))
        except ValueError:
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

def main() -> None:
    if not TG_TOKEN:
        print(f"{C.RED}[!] Falta TELEGRAM_TOKEN en .env{C.RESET}")
        return
    cfg = cargar_config()
    admin_id = str(cfg.get("telegram_admin_id") or "").strip()
    autorizados = {x for x in (TG_CHANNEL_ID, admin_id) if x}

    print(f"\n{C.BOLD}{C.GREEN}=== CONTROL REMOTO TELEGRAM 2-VIAS ACTIVO (v10.0 PRIME) ==={C.RESET}")
    print(f"{C.DIM}Chats autorizados: {autorizados or 'Solo canal .env'}")
    print(f"Escribe /help en tu canal o chat privado con el bot. Ctrl+C para salir.{C.RESET}\n")

    offset = 0
    url = f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates"
    try:
        while True:
            try:
                r = SESSION.get(url, params={"timeout": 25, "offset": offset}, timeout=32)
                if r.status_code == 200:
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
                            print(f"{C.YELLOW}[!] Mensaje ignorado de chat_id={cid}. Si eres tu en DM privado, agrega '{cid}' en config.json -> telegram_admin_id.{C.RESET}", flush=True)
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