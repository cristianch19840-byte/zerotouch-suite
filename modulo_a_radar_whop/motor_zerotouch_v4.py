import os
import re
import sys
import html
import time
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core_ia import SESSION, generar_json_ia

TG_TOKEN = os.getenv("TELEGRAM_TOKEN")
TG_CHANNEL_ID = os.getenv("TELEGRAM_CHAT_ID")

REDDIT_HEADERS = {
    "User-Agent": "python:zerotouch-radar:v7.0 (by /u/zerotouch_freelance)",
    "Accept": "application/json",
}

SUBREDDITS = ["forhire", "slavelabour", "hiring", "freelance_forhire", "DoneDirtCheap", "Jobs4Bitcoins"]
MAX_HORAS_ANTIGUEDAD = 12

REGEX_DESCARTAR = re.compile(r"(\[|\()\s*(for\s*hire|forhire|offer)\s*(\]|\))", re.IGNORECASE)
REGEX_ACEPTAR = re.compile(r"((\[|\()\s*(hiring|task)\s*(\]|\))|^hiring\b)", re.IGNORECASE)
REGEX_SPAM = re.compile(
    r"\b(kyc|referral|sign\s*up\s*bonus|verify\s*account|upvote|google\s*review|"
    r"trustpilot|onlyfans|chatter|dm\s*on\s*whatsapp|quick\s*\$[1-5]\b)\b",
    re.IGNORECASE,
)
REGEX_TECH = re.compile(
    r"\b(python|scrap\w*|bot\w*|script\w*|automat\w*|api\w*|selenium|playwright|beautifulsoup|"
    r"telegram|discord|excel|csv|json|sql|database|data|extract\w*|crawl\w*|web\w*|site|app|"
    r"software|cod\w+|program\w*|dev\w*|backend|frontend|react|node|php|wordpress|shopify|"
    r"plugin|extension|webhook|ai|llm|gpt|gemini|bug|fix|linux|server|deploy|n8n|zapier)\b",
    re.IGNORECASE,
)

def limpiar_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    texto = BeautifulSoup(raw_html, "html.parser").get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", texto)[:1600]

def normalizar_titulo(titulo: str) -> str:
    limpio = re.sub(r"\[[^\]]*\]|\([^\)]*\)", "", titulo.lower())
    return re.sub(r"\W+", "", limpio)[:90]

def publicar_telegram(mensaje_html: str, fallback_texto: str) -> bool:
    if not TG_TOKEN or not TG_CHANNEL_ID:
        print("    [!] Faltan credenciales de Telegram.", flush=True)
        return False
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        r = SESSION.post(
            url,
            json={
                "chat_id": TG_CHANNEL_ID,
                "text": mensaje_html,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        if r.status_code == 200:
            print("    [TG] Alerta HTML publicada en Telegram!", flush=True)
            return True
        r2 = SESSION.post(
            url,
            json={"chat_id": TG_CHANNEL_ID, "text": fallback_texto, "disable_web_page_preview": True},
            timeout=15,
        )
        if r2.status_code == 200:
            print("    [TG] Alerta enviada (texto plano).", flush=True)
            return True
        print(f"    [TG] Error {r2.status_code}: {r2.text}", flush=True)
    except Exception as e:
        print(f"    [TG] Excepcion: {e}", flush=True)
    return False

def obtener_posts_subreddit(sub: str) -> list:
    items_validos = []
    crudos = []
    ahora = time.time()

    try:
        url_json = f"https://www.reddit.com/r/{sub}/new.json?limit=15&raw_json=1"
        r = SESSION.get(url_json, headers=REDDIT_HEADERS, timeout=12)
        if r.status_code == 200:
            for child in r.json().get("data", {}).get("children", []):
                d = child.get("data", {})
                creado = d.get("created_utc", ahora)
                if (ahora - creado) > (MAX_HORAS_ANTIGUEDAD * 3600):
                    continue
                crudos.append({
                    "id": d.get("name") or d.get("id"),
                    "titulo": d.get("title", ""),
                    "texto": (d.get("selftext") or "")[:1600],
                    "link": f"https://www.reddit.com{d.get('permalink', '')}",
                })
    except Exception:
        pass

    if not crudos:
        try:
            api_url = f"https://api.rss2json.com/v1/api.json?rss_url=https://www.reddit.com/r/{sub}/new/.rss"
            r = SESSION.get(api_url, headers=REDDIT_HEADERS, timeout=12)
            if r.status_code == 200 and r.json().get("status") == "ok":
                for item in r.json().get("items", [])[:15]:
                    crudos.append({
                        "id": item.get("guid", item.get("link")),
                        "titulo": item.get("title", ""),
                        "texto": limpiar_html(item.get("description", "")),
                        "link": item.get("link", ""),
                    })
        except Exception as e:
            print(f"[!] Error Reddit r/{sub}: {e}", flush=True)

    for p in crudos:
        titulo = p["titulo"]
        combinado = f"{titulo} {p['texto']}"
        if not titulo or REGEX_DESCARTAR.search(titulo) or REGEX_SPAM.search(combinado):
            continue
        if sub.lower() != "hiring" and not REGEX_ACEPTAR.search(titulo):
            continue
        es_tech = bool(REGEX_TECH.search(combinado))
        items_validos.append({
            "id": p["id"],
            "fuente": f"r/{sub}",
            "titulo": titulo,
            "titulo_norm": normalizar_titulo(titulo),
            "texto": p["texto"],
            "link": p["link"],
            "es_tech": es_tech,
        })

    print(f"[OK] r/{sub} -> {len(items_validos)} hiring ({sum(1 for x in items_validos if x['es_tech'])} tech)", flush=True)
    return items_validos

def recolectar_ofertas() -> list:
    ofertas = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futuros = {pool.submit(obtener_posts_subreddit, sub): sub for sub in SUBREDDITS}
        for fut in as_completed(futuros):
            ofertas.extend(fut.result())
    return ofertas

def preparar_db() -> sqlite3.Connection:
    conn = sqlite3.connect(os.path.join(ROOT_DIR, "estado_radar_v4.db"))
    conn.execute("CREATE TABLE IF NOT EXISTS vistos (post_id TEXT PRIMARY KEY, titulo_norm TEXT DEFAULT '', ts DATETIME DEFAULT CURRENT_TIMESTAMP)")
    cols = [row[1] for row in conn.execute("PRAGMA table_info(vistos)").fetchall()]
    if "titulo_norm" not in cols:
        conn.execute("ALTER TABLE vistos ADD COLUMN titulo_norm TEXT DEFAULT ''")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha DATETIME DEFAULT CURRENT_TIMESTAMP,
            fuente TEXT,
            titulo TEXT,
            categoria TEXT,
            presupuesto TEXT,
            score INTEGER,
            link TEXT,
            estado TEXT DEFAULT 'nuevo',
            ganancia_usd REAL DEFAULT 0
        )
        """
    )
    conn.execute("DELETE FROM vistos WHERE post_id NOT IN (SELECT post_id FROM vistos ORDER BY ts DESC LIMIT 2000)")
    conn.commit()
    return conn

def evaluar_y_enviar(fuente: str, titulo: str, texto_limpio: str, link: str, conn: sqlite3.Connection | None = None) -> bool:
    print(f"  [>] IA ({fuente}): {titulo[:58]}...", flush=True)
    regla = (
        "En r/forhire NO ofrezcas trabajo gratis; demuestra diagnostico tecnico inmediato."
        if "forhire" in fuente.lower()
        else "Se directo confirmando disponibilidad y entrega rapida."
    )
    prompt = (
        f"Evalua esta publicacion de Reddit ({fuente}) y responde UNICAMENTE con JSON valido.\n"
        f"Titulo: {titulo}\nContenido: {texto_limpio}\nContexto: {regla}\n"
        f"REGLAS: relevante=true SOLO si buscan contratar (Hiring/Task) para un proyecto freelance puntual o tarea tecnica corta (scraping, script Python, bot Telegram/Discord, automatizacion, datos, API, n8n/Zapier o arreglo web). "
        f"Rechaza [For Hire], puestos presenciales, sin pago, estafas o tareas escolares.\n"
        f'Formato exacto: {{"relevante": true, "score": 8, "categoria": "Python", "presupuesto": "$100 USD", "resumen_es": "...", "pitch_en": "..."}}'
    )
    datos = generar_json_ia(prompt, temperatura=0.2, timeout=15)
    if not datos:
        return False

    score = int(datos.get("score", 0))
    print(f"    [=] Relevante: {datos.get('relevante')} | Score: {score}/10", flush=True)
    if datos.get("relevante") and score >= 6:
        categoria = str(datos.get("categoria", "Tech"))
        presupuesto = str(datos.get("presupuesto", "Por definir"))
        resumen = str(datos.get("resumen_es", ""))
        pitch = str(datos.get("pitch_en", ""))
        etiqueta_prio = "🔥 PRIORIDAD ALTA" if score >= 8 else "⚡ OPORTUNIDAD"
        accion = (
            "Comentar $bid en el post antes de enviar DM"
            if fuente.lower() in ("r/slavelabour", "r/donedirtcheap")
            else "Abrir el post y enviar DM directo al autor"
        )

        msg_html = (
            f"<b>{etiqueta_prio} | [{html.escape(categoria)}] {score}/10</b>\n"
            f"💰 <b>Presupuesto:</b> {html.escape(presupuesto)}  |  📍 <b>{html.escape(fuente)}</b>\n\n"
            f"📌 <b>{html.escape(titulo)}</b>\n"
            f"📝 {html.escape(resumen)}\n"
            f"⚠️ <i>{html.escape(accion)}</i>\n"
            f"🔗 <a href=\"{html.escape(link)}\">Abrir post en Reddit</a>\n\n"
            f"📋 <b>PITCH (toca para copiar):</b>\n"
            f"<code>{html.escape(pitch)}</code>"
        )
        msg_plano = (
            f"{etiqueta_prio} [{categoria}] {score}/10\n"
            f"Presupuesto: {presupuesto} | {fuente}\n\n"
            f"{titulo}\n{resumen}\nProtocolo: {accion}\nReddit: {link}\n\nPITCH:\n{pitch}"
        )
        publicar_telegram(msg_html, msg_plano)

        if conn is not None:
            conn.execute(
                "INSERT INTO leads (fuente, titulo, categoria, presupuesto, score, link) VALUES (?, ?, ?, ?, ?, ?)",
                (fuente, titulo, categoria, presupuesto, score, link),
            )
            conn.commit()
    return True

def mostrar_estadisticas() -> None:
    conn = preparar_db()
    try:
        total_vistos = conn.execute("SELECT COUNT(*) FROM vistos").fetchone()[0]
        total_leads = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        ganado = conn.execute("SELECT COALESCE(SUM(ganancia_usd), 0) FROM leads WHERE estado = 'ganado'").fetchone()[0]
        print(f"\n=== ESTADISTICAS ZEROTOUCH v7.0 ===")
        print(f"Posts filtrados en cache : {total_vistos}")
        print(f"Leads buenos guardados   : {total_leads}")
        print(f"Ingresos registrados     : ${ganado:.2f} USD\n")
    finally:
        conn.close()

def ejecutar_ciclo() -> None:
    print("Iniciando ciclo Radar Zero-Touch v7.0 (Paralelo + Anti-Spam + HTML)...", flush=True)
    conn = preparar_db()
    try:
        for item in recolectar_ofertas():
            ya_visto = conn.execute(
                "SELECT 1 FROM vistos WHERE post_id = ? OR (titulo_norm != '' AND titulo_norm = ?)",
                (item["id"], item["titulo_norm"]),
            ).fetchone()
            if ya_visto:
                continue

            if not item["es_tech"]:
                conn.execute("INSERT OR IGNORE INTO vistos (post_id, titulo_norm) VALUES (?, ?)", (item["id"], item["titulo_norm"]))
                conn.commit()
                continue

            if evaluar_y_enviar(item["fuente"], item["titulo"], item["texto"], item["link"], conn=conn):
                conn.execute("INSERT OR IGNORE INTO vistos (post_id, titulo_norm) VALUES (?, ?)", (item["id"], item["titulo_norm"]))
                conn.commit()
            time.sleep(0.8)

        print("Ciclo v7.0 completado con exito.", flush=True)
    finally:
        conn.close()

if __name__ == "__main__":
    if "--test" in sys.argv:
        evaluar_y_enviar(
            "r/forhire",
            "[Hiring] Need Python developer to scrape Shopify store prices ($150 USD)",
            "Looking for a clean Python script to extract product titles, variants, and prices from 5 Shopify stores into CSV.",
            "https://www.reddit.com/r/forhire/",
        )
    elif "--stats" in sys.argv:
        mostrar_estadisticas()
    else:
        ejecutar_ciclo()