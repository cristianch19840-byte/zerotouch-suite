import os
import re
import sys
import html
import time
import random
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core_ia import (
    C,
    SESSION,
    safe_int,
    safe_bool,
    extraer_score,
    log_evento,
    cargar_config,
    preparar_db,
    registrar_metricas,
    similitud_jaccard,
    verificar_confianza_reddit,
    generar_json_ia,
    alerta_sonora,
)

TG_TOKEN = os.getenv("TELEGRAM_TOKEN")
TG_CHANNEL_ID = os.getenv("TELEGRAM_CHAT_ID")

REDDIT_HEADERS = {
    "User-Agent": "python:zerotouch-titan:v11.5 (by /u/zerotouch_freelance)",
    "Accept": "application/json,application/atom+xml,text/xml;q=0.9,*/*;q=0.8",
}

GITHUB_HEADERS = {
    "User-Agent": "ZeroTouchTitan/11.5",
    "Accept": "application/vnd.github+json",
}
if os.getenv("GITHUB_TOKEN"):
    GITHUB_HEADERS["Authorization"] = f"Bearer {os.getenv('GITHUB_TOKEN')}"

SUBREDDITS = [
    "forhire",
    "slavelabour",
    "hiring",
    "freelance_forhire",
    "DoneDirtCheap",
    "Jobs4Bitcoins",
    "Jobbit",
    "WebDevClassifieds",
    "requestabot",
    "ProgrammingTasks",
    "PythonJobs",
    "automate",
]

SUBS_SIN_TAG_OBLIGATORIO = {"hiring", "requestabot", "programmingtasks", "pythonjobs", "automate"}

REGEX_DESCARTAR = re.compile(r"(\[|\()\s*(for\s*hire|forhire|offer)\s*(\]|\))", re.IGNORECASE)
REGEX_ACEPTAR = re.compile(r"((\[|\()\s*(hiring|task|paid|request)\s*(\]|\))|^hiring\b|^\[h\])", re.IGNORECASE)
REGEX_SPAM = re.compile(
    r"\b(kyc|referral|sign\s*up\s*bonus|verify\s*account|upvote|google\s*review|"
    r"trustpilot|onlyfans|chatter|dm\s*on\s*whatsapp|quick\s*\$[1-5]\b|clickworker|survey|betting\s*account)\b",
    re.IGNORECASE,
)
REGEX_TECH = re.compile(
    r"\b(python|scrap\w*|bot\w*|script\w*|automat\w*|api\w*|selenium|playwright|beautifulsoup|"
    r"telegram|discord|excel|csv|json|sql|database|data|extract\w*|crawl\w*|web\w*|site|app|"
    r"software|cod\w+|program\w*|dev\w*|backend|frontend|react|node|php|wordpress|shopify|"
    r"plugin|extension|webhook|ai|llm|gpt|gemini|bug|fix|linux|server|deploy|n8n|zapier|make\.com|airtable)\b",
    re.IGNORECASE,
)
REGEX_DINERO = re.compile(r"(?:\$|€|USD\s*|USDT\s*)(\d{2,5})\b", re.IGNORECASE)
REGEX_URGENTE = re.compile(r"\b(urgent|asap|today|right\s*now|quick\s*job|within\s*\d+\s*hours?|immediately)\b", re.IGNORECASE)
REGEX_BALLENA = re.compile(r"\b(ongoing|retainer|long[\s-]*term|monthly|saas|agency|full\s*mvp)\b", re.IGNORECASE)

def limpiar_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    texto = BeautifulSoup(raw_html, "html.parser").get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", texto)[:1600]

def normalizar_titulo(titulo: str) -> str:
    limpio = re.sub(r"\[[^\]]*\]|\([^\)]*\)", "", titulo.lower())
    return re.sub(r"\W+", "", limpio)[:90]

def titulo_palabras_limpio(titulo: str) -> str:
    limpio = re.sub(r"\[[^\]]*\]|\([^\)]*\)", " ", titulo.lower())
    return " ".join(re.findall(r"[a-z0-9]{3,}", limpio))[:180]

def detectar_prioridad_tag(combinado: str, dinero_local: int) -> str:
    tags = []
    if dinero_local >= 250 or REGEX_BALLENA.search(combinado):
        tags.append("🐋 HIGH-TICKET")
    if REGEX_URGENTE.search(combinado):
        tags.append("🚨 URGENTE")
    return " · ".join(tags)

def calcular_competencia(edad_min: int | None, comentarios: int | None) -> tuple[str, int]:
    if edad_min is None or comentarios is None:
        return "🔎 RSS en vivo", 0
    if edad_min <= 20 and comentarios <= 2:
        return f"🎯 SANGRE FRESCA ({edad_min}m | {comentarios} com.)", 2
    if comentarios <= 5:
        return f"🟢 Baja ({edad_min}m | {comentarios} com.)", 1
    if comentarios <= 12:
        return f"🟡 Media ({edad_min}m | {comentarios} com.)", 0
    return f"🔴 Alta ({edad_min}m | {comentarios} com.)", -1

def construir_dm_reddit(autor: str, titulo: str, pitch: str) -> str | None:
    if not autor or autor.lower() in ("[deleted]", "automoderator", "none", "github", "hackernews"):
        return None
    asunto = quote(f"Re: {titulo[:65]}")
    cuerpo = quote(pitch[:380])
    return f"https://www.reddit.com/message/compose/?to={quote(autor)}&subject={asunto}&message={cuerpo}"

def publicar_telegram(mensaje_html: str, fallback_texto: str, botones: list | None = None, chat_id: str | None = None) -> bool:
    destino = chat_id or TG_CHANNEL_ID
    if not TG_TOKEN or not destino:
        log_evento("[!] Faltan credenciales de Telegram")
        print(f"    {C.RED}[!] Faltan credenciales de Telegram.{C.RESET}", flush=True)
        return False
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {
        "chat_id": destino,
        "text": mensaje_html[:4000],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if botones:
        payload["reply_markup"] = {"inline_keyboard": botones}
    try:
        r = SESSION.post(url, json=payload, timeout=15)
        if r.status_code == 200:
            print(f"    {C.GREEN}[TG] Alerta enviada!{C.RESET}", flush=True)
            return True
        payload.pop("reply_markup", None)
        r2 = SESSION.post(url, json=payload, timeout=15)
        if r2.status_code == 200:
            return True
        plano_limpio = re.sub(r"<[^>]+>", "", fallback_texto)[:4000]
        r3 = SESSION.post(url, json={"chat_id": destino, "text": plano_limpio, "disable_web_page_preview": True}, timeout=15)
        return r3.status_code == 200
    except Exception as e:
        log_evento(f"[TG] Excepcion: {e}")
        print(f"    {C.RED}[TG] Excepcion: {e}{C.RESET}", flush=True)
    return False

def pasa_blacklist_custom(texto: str, extras) -> bool:
    if not extras:
        return True
    if isinstance(extras, str):
        extras = [w.strip() for w in extras.split(",") if w.strip()]
    low = texto.lower()
    return not any(str(w).strip().lower() in low for w in extras if str(w).strip())

def procesar_child_reddit(d: dict, cfg: dict, fuente_forzada: str | None = None) -> dict | None:
    ahora = time.time()
    max_h = max(1, safe_int(cfg.get("max_horas_post", 12), 12))
    creado = d.get("created_utc", ahora)
    edad_seg = max(0, ahora - creado)
    if edad_seg > (max_h * 3600):
        return None
    titulo = (d.get("title") or "").strip()
    cuerpo = (d.get("selftext") or "")[:1600]
    sub = d.get("subreddit") or ""
    fuente = fuente_forzada or (f"r/{sub}" if sub else "Reddit")
    combinado = f"{titulo} {cuerpo}"
    if not titulo or REGEX_DESCARTAR.search(titulo) or REGEX_SPAM.search(combinado):
        return None
    if not pasa_blacklist_custom(combinado, cfg.get("palabras_extra_blacklist", [])):
        return None
    if sub.lower() not in SUBS_SIN_TAG_OBLIGATORIO and not REGEX_ACEPTAR.search(titulo):
        return None

    es_tech = bool(REGEX_TECH.search(combinado))
    edad_min = int(edad_seg // 60)
    comentarios = safe_int(d.get("num_comments", 0), 0)
    comp_txt, comp_bonus = calcular_competencia(edad_min, comentarios)
    dinero_match = REGEX_DINERO.search(combinado)
    dinero_local = safe_int(dinero_match.group(1), 0) if dinero_match else 0
    prio_tag = detectar_prioridad_tag(combinado, dinero_local)

    return {
        "id": d.get("name") or d.get("id") or d.get("permalink"),
        "fuente": fuente,
        "autor": d.get("author") or "",
        "titulo": titulo,
        "titulo_norm": normalizar_titulo(titulo),
        "titulo_palabras": titulo_palabras_limpio(titulo),
        "texto": cuerpo,
        "link": f"https://www.reddit.com{d.get('permalink', '')}",
        "es_tech": es_tech,
        "edad_min": edad_min,
        "comentarios": comentarios,
        "comp_txt": comp_txt,
        "comp_bonus": comp_bonus + (2 if prio_tag else 0),
        "dinero_local": dinero_local,
        "prioridad_tag": prio_tag,
        "origen": "reddit",
    }

def parsear_atom_reddit(xml_text: str, sub: str, cfg: dict) -> list:
    resultados = []
    max_h = max(1, safe_int(cfg.get("max_horas_post", 12), 12))
    ahora = datetime.now(timezone.utc)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return resultados

    for entry in root:
        if not entry.tag.endswith("entry"):
            continue
        post_id = titulo = link = autor = contenido = actualizado = ""
        for ch in entry:
            tag = ch.tag.split("}", 1)[-1]
            if tag == "id" and ch.text:
                post_id = ch.text.strip()
            elif tag == "title" and ch.text:
                titulo = ch.text.strip()
            elif tag == "link":
                link = ch.attrib.get("href", link)
            elif tag == "content" and ch.text:
                contenido = limpiar_html(ch.text)
            elif tag == "updated" and ch.text:
                actualizado = ch.text.strip()
            elif tag == "author":
                for sub_ch in ch:
                    if sub_ch.tag.endswith("name") and sub_ch.text:
                        autor = sub_ch.text.replace("/u/", "").strip()

        edad_min = None
        if actualizado:
            try:
                dt = datetime.fromisoformat(actualizado.replace("Z", "+00:00"))
                diff_seg = max(0, (ahora - dt).total_seconds())
                if diff_seg > max_h * 3600:
                    continue
                edad_min = int(diff_seg // 60)
            except ValueError:
                pass

        combinado = f"{titulo} {contenido}"
        if not titulo or REGEX_DESCARTAR.search(titulo) or REGEX_SPAM.search(combinado):
            continue
        if not pasa_blacklist_custom(combinado, cfg.get("palabras_extra_blacklist", [])):
            continue
        if sub.lower() not in SUBS_SIN_TAG_OBLIGATORIO and not REGEX_ACEPTAR.search(titulo):
            continue

        dinero_m = REGEX_DINERO.search(combinado)
        dinero_local = safe_int(dinero_m.group(1), 0) if dinero_m else 0
        prio_tag = detectar_prioridad_tag(combinado, dinero_local)
        resultados.append({
            "id": post_id or link,
            "fuente": f"r/{sub}",
            "autor": autor,
            "titulo": titulo,
            "titulo_norm": normalizar_titulo(titulo),
            "titulo_palabras": titulo_palabras_limpio(titulo),
            "texto": contenido,
            "link": link,
            "es_tech": bool(REGEX_TECH.search(combinado)),
            "edad_min": edad_min,
            "comentarios": None,
            "comp_txt": f"⚡ RSS Nativo ({edad_min}m)" if edad_min is not None else "⚡ RSS Nativo",
            "comp_bonus": (1 if (edad_min is not None and edad_min <= 20) else 0) + (2 if prio_tag else 0),
            "dinero_local": dinero_local,
            "prioridad_tag": prio_tag,
            "origen": "reddit",
        })
    return resultados

def obtener_posts_subreddit(sub: str, cfg: dict) -> list:
    time.sleep(random.uniform(0.10, 0.35))
    items_validos = []

    try:
        r = SESSION.get(f"https://www.reddit.com/r/{sub}/new.json?limit=15&raw_json=1", headers=REDDIT_HEADERS, timeout=10)
        if r.status_code == 200:
            for child in r.json().get("data", {}).get("children", []):
                item = procesar_child_reddit(child.get("data", {}), cfg, fuente_forzada=f"r/{sub}")
                if item:
                    items_validos.append(item)
            tech_n = sum(1 for x in items_validos if x["es_tech"])
            print(f"{C.DIM}[OK] r/{sub:<18} (JSON) -> {len(items_validos):2d} hiring ({tech_n} tech){C.RESET}", flush=True)
            return items_validos
    except Exception:
        pass

    try:
        r = SESSION.get(f"https://www.reddit.com/r/{sub}/new/.rss", headers=REDDIT_HEADERS, timeout=10)
        if r.status_code == 200 and "<entry>" in r.text:
            items_validos = parsear_atom_reddit(r.text, sub, cfg)
            tech_n = sum(1 for x in items_validos if x["es_tech"])
            print(f"{C.DIM}[OK] r/{sub:<18} (XML)  -> {len(items_validos):2d} hiring ({tech_n} tech){C.RESET}", flush=True)
            return items_validos
    except Exception:
        pass

    try:
        api_url = f"https://api.rss2json.com/v1/api.json?rss_url=https://www.reddit.com/r/{sub}/new/.rss"
        r = SESSION.get(api_url, headers=REDDIT_HEADERS, timeout=10)
        if r.status_code == 200 and r.json().get("status") == "ok":
            for raw in r.json().get("items", [])[:15]:
                titulo = raw.get("title", "")
                texto = limpiar_html(raw.get("description", ""))
                combinado = f"{titulo} {texto}"
                if not titulo or REGEX_DESCARTAR.search(titulo) or REGEX_SPAM.search(combinado):
                    continue
                if not pasa_blacklist_custom(combinado, cfg.get("palabras_extra_blacklist", [])):
                    continue
                if sub.lower() not in SUBS_SIN_TAG_OBLIGATORIO and not REGEX_ACEPTAR.search(titulo):
                    continue
                autor_raw = (raw.get("author") or "").replace("/u/", "").strip()
                dinero_m = REGEX_DINERO.search(combinado)
                dinero_local = safe_int(dinero_m.group(1), 0) if dinero_m else 0
                items_validos.append({
                    "id": raw.get("guid", raw.get("link")),
                    "fuente": f"r/{sub}",
                    "autor": autor_raw,
                    "titulo": titulo,
                    "titulo_norm": normalizar_titulo(titulo),
                    "titulo_palabras": titulo_palabras_limpio(titulo),
                    "texto": texto,
                    "link": raw.get("link", ""),
                    "es_tech": bool(REGEX_TECH.search(combinado)),
                    "edad_min": None,
                    "comentarios": None,
                    "comp_txt": "🔎 Via RSS2JSON",
                    "comp_bonus": 0,
                    "dinero_local": dinero_local,
                    "prioridad_tag": detectar_prioridad_tag(combinado, dinero_local),
                    "origen": "reddit",
                })
    except Exception as e:
        print(f"{C.YELLOW}[!] Error r/{sub}: {e}{C.RESET}", flush=True)

    tech_n = sum(1 for x in items_validos if x["es_tech"])
    print(f"{C.DIM}[OK] r/{sub:<18} (RSS)  -> {len(items_validos):2d} hiring ({tech_n} tech){C.RESET}", flush=True)
    return items_validos

def buscar_reddit_global(query_str: str, etiqueta: str, cfg: dict) -> list:
    items = []
    url = f"https://www.reddit.com/search.json?q={quote(query_str)}&sort=new&t=day&limit=18&raw_json=1"
    try:
        r = SESSION.get(url, headers=REDDIT_HEADERS, timeout=12)
        if r.status_code == 200:
            for child in r.json().get("data", {}).get("children", []):
                item = procesar_child_reddit(child.get("data", {}), cfg)
                if item and item["es_tech"]:
                    items.append(item)
            print(f"{C.CYAN}[OK] {etiqueta:<20} -> {len(items):2d} joyas tech{C.RESET}", flush=True)
    except Exception as e:
        print(f"{C.YELLOW}[!] Error {etiqueta}: {e}{C.RESET}", flush=True)
    return items

def buscar_github_bounties() -> list:
    items = []
    desde = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
    q = quote(f"is:issue is:open label:bounty created:>={desde} (python OR scraper OR bot OR automation)")
    url = f"https://api.github.com/search/issues?q={q}&sort=created&order=desc&per_page=8"
    try:
        r = SESSION.get(url, headers=GITHUB_HEADERS, timeout=12)
        if r.status_code == 200:
            for iss in r.json().get("items", []):
                titulo = iss.get("title", "")
                cuerpo = (iss.get("body") or "")[:1400]
                combinado = f"{titulo} {cuerpo}"
                m_dinero = REGEX_DINERO.search(combinado)
                if not m_dinero:
                    continue
                comentarios = safe_int(iss.get("comments", 0), 0)
                dinero_local = safe_int(m_dinero.group(1), 0)
                items.append({
                    "id": f"gh_bounty_{iss.get('id')}",
                    "fuente": "GitHub Bounty",
                    "autor": "github",
                    "titulo": f"[Bounty] {titulo}",
                    "titulo_norm": normalizar_titulo(titulo),
                    "titulo_palabras": titulo_palabras_limpio(titulo),
                    "texto": cuerpo,
                    "link": iss.get("html_url", ""),
                    "es_tech": True,
                    "edad_min": 60,
                    "comentarios": comentarios,
                    "comp_txt": f"💎 Issue abierto ({comentarios} com.)",
                    "comp_bonus": 2 if comentarios <= 2 else 0,
                    "dinero_local": dinero_local,
                    "prioridad_tag": "🐋 HIGH-TICKET" if dinero_local >= 250 else "",
                    "origen": "github",
                })
            print(f"{C.MAGENTA}[OK] GitHub Bounties      -> {len(items):2d} recompensas{C.RESET}", flush=True)
    except Exception as e:
        print(f"{C.YELLOW}[!] Error GitHub Bounties: {e}{C.RESET}", flush=True)
    return items

def buscar_hackernews_freelance() -> list:
    items = []
    hace_48h = int(time.time() - 48 * 3600)
    url = f"https://hn.algolia.com/api/v1/search_by_date?query=freelance+python+automation&tags=comment&numericFilters=created_at_i>{hace_48h}&hitsPerPage=8"
    try:
        r = SESSION.get(url, timeout=10)
        if r.status_code == 200:
            for hit in r.json().get("hits", []):
                texto = limpiar_html(hit.get("comment_text", ""))
                if not texto or len(texto) < 60:
                    continue
                if not re.search(r"\b(hiring|looking for|need a|contract|freelancer|paid)\b", texto, re.IGNORECASE):
                    continue
                obj_id = hit.get("objectID")
                story_title = hit.get("story_title") or "HN Freelance Thread"
                items.append({
                    "id": f"hn_{obj_id}",
                    "fuente": "HackerNews",
                    "autor": "hackernews",
                    "titulo": f"[HN] {story_title[:70]}",
                    "titulo_norm": normalizar_titulo(texto[:80]),
                    "titulo_palabras": titulo_palabras_limpio(texto[:120]),
                    "texto": texto,
                    "link": f"https://news.ycombinator.com/item?id={obj_id}",
                    "es_tech": bool(REGEX_TECH.search(texto)),
                    "edad_min": 120,
                    "comentarios": 0,
                    "comp_txt": "🔥 Cliente HN (Ticket alto)",
                    "comp_bonus": 2,
                    "dinero_local": 250,
                    "prioridad_tag": "🐋 HIGH-TICKET",
                    "origen": "hn",
                })
            print(f"{C.BLUE}[OK] HackerNews High-$    -> {len(items):2d} leads freelance{C.RESET}", flush=True)
    except Exception as e:
        print(f"{C.YELLOW}[!] Error HackerNews: {e}{C.RESET}", flush=True)
    return items

def recolectar_todo(cfg: dict) -> list:
    ofertas_raw = []
    q_global_1 = '("[Hiring]" OR "[Task]") (python OR scraper OR scraping OR selenium OR playwright OR csv OR data)'
    q_global_2 = '("[Hiring]" OR "[Task]") (telegram OR discord OR bot OR automation OR shopify OR n8n OR zapier OR api)'

    with ThreadPoolExecutor(max_workers=5) as pool:
        futuros = [pool.submit(obtener_posts_subreddit, sub, cfg) for sub in SUBREDDITS]
        futuros.append(pool.submit(buscar_reddit_global, q_global_1, "Global Python/Data", cfg))
        futuros.append(pool.submit(buscar_reddit_global, q_global_2, "Global Bots/Auto", cfg))
        futuros.append(pool.submit(buscar_github_bounties))
        futuros.append(pool.submit(buscar_hackernews_freelance))
        for fut in as_completed(futuros):
            try:
                ofertas_raw.extend(fut.result())
            except Exception:
                pass

    # Deduplicacion inmediata en memoria (evita procesar el mismo post en subs + global)
    ofertas_raw.sort(key=lambda x: (x["comp_bonus"], x["dinero_local"] > 0, -(x["edad_min"] or 999)), reverse=True)
    unicas = []
    vistos_ids = set()
    vistos_tit = set()
    for it in ofertas_raw:
        pid = it.get("id")
        tn = it.get("titulo_norm")
        if pid in vistos_ids or (tn and tn in vistos_tit):
            continue
        vistos_ids.add(pid)
        if tn:
            vistos_tit.add(tn)
        unicas.append(it)
    return unicas

def contexto_aprendizaje_crm(conn) -> str:
    if conn is None:
        return ""
    try:
        gan = [r[0][:50] for r in conn.execute("SELECT titulo FROM leads WHERE estado = 'ganado' ORDER BY id DESC LIMIT 4").fetchall()]
        desc = [r[0][:50] for r in conn.execute("SELECT titulo FROM leads WHERE estado = 'descartado' ORDER BY id DESC LIMIT 4").fetchall()]
        partes = []
        if gan:
            partes.append(f"Proyectos similares a los que el dev YA GANO (subir score): {gan}")
        if desc:
            partes.append(f"Proyectos que el dev DESCARTO (bajar score): {desc}")
        return "\n".join(partes)
    except Exception:
        return ""

def revisar_recordatorios_followup(conn, cfg: dict) -> int:
    horas = max(1, safe_int(cfg.get("recordatorio_followup_horas", 20), 20))
    pendientes = conn.execute(
        f"""
        SELECT id, autor, titulo, link FROM leads
        WHERE estado = 'contactado'
          AND followup_enviado = 0
          AND COALESCE(contactado_ts, fecha) <= datetime('now', '-{horas} hours')
        LIMIT 3
        """
    ).fetchall()
    enviados = 0
    for lid, autor, titulo, link in pendientes:
        followup = f"Hey! Just following up on your post about {titulo[:50]} — I still have availability to build and deliver a clean working prototype today if you haven't picked someone yet."
        msg = (
            f"<b>⏰ RECORDATORIO FOLLOW-UP (Lead #{lid})</b>\n"
            f"Hace mas de {horas}h contactaste a <b>u/{html.escape(autor or 'cliente')}</b>:\n"
            f"📌 {html.escape(titulo)}\n\n"
            f"📋 <b>SEGUIMIENTO LISTO (toca para copiar):</b>\n"
            f"<code>{html.escape(followup)}</code>"
        )
        botones = [[{"text": "🚀 Abrir Post", "url": link}]] if link and link.startswith("http") else None
        if publicar_telegram(msg, msg, botones=botones):
            conn.execute("UPDATE leads SET followup_enviado = 1 WHERE id = ?", (lid,))
            conn.commit()
            enviados += 1
    return enviados

def evaluar_y_enviar(item: dict, cfg: dict, conn=None, modo_sonido: bool = False, aprendizaje: str = "") -> tuple[bool, bool, int]:
    fuente = item["fuente"]
    titulo = item["titulo"]
    texto_limpio = item["texto"]
    link = item["link"]
    autor = item.get("autor", "")
    comp_txt = item.get("comp_txt", "🔎 En radar")
    prio_tag = item.get("prioridad_tag", "")
    score_min = safe_int(cfg.get("score_minimo", 6), 6)

    print(f"  {C.CYAN}[>] IA ({fuente}):{C.RESET} {titulo[:62]}...", flush=True)
    regla = (
        "En r/forhire NO ofrezcas trabajo gratis; demuestra diagnostico tecnico inmediato."
        if "forhire" in fuente.lower()
        else "Se directo confirmando disponibilidad, solucion concreta y entrega rapida."
    )
    prompt = (
        f"Evalua esta oportunidad de {fuente} y responde UNICAMENTE con JSON valido.\n"
        f"Titulo: {titulo}\nContenido: {texto_limpio}\nContexto: {regla}\n"
        f"Especialidad: {cfg.get('especialidad')}\n"
        f"{aprendizaje}\n"
        f"REGLAS: relevante=true SOLO si buscan contratar (Hiring/Task/Bounty) para un proyecto freelance puntual o tarea tecnica corta (scraping, script Python, bot Telegram/Discord, automatizacion, datos, API, n8n/Zapier o arreglo web). "
        f"Rechaza [For Hire], puestos corporativos full-time fijos, trabajos presenciales, sin pago, estafas o tareas escolares.\n"
        f'Formato exacto: {{"relevante": true, "score": 8, "categoria": "Python", "presupuesto": "$100 USD", "resumen_es": "...", "pitch_en": "..."}}'
    )
    datos = generar_json_ia(prompt, temperatura=0.2, timeout=16)
    tok_est = (len(prompt) + 320) // 4
    if not datos:
        return False, False, tok_est

    es_relevante = safe_bool(datos.get("relevante"))
    score = extraer_score(datos.get("score", 0))
    print(f"    [=] Relevante: {es_relevante} | Score: {score}/10 | {comp_txt} {prio_tag}", flush=True)
    enviado = False

    if es_relevante and score >= score_min:
        categoria = str(datos.get("categoria") or "Tech")
        presupuesto = str(datos.get("presupuesto") or "Por definir")
        resumen = str(datos.get("resumen_es") or "")
        pitch = str(datos.get("pitch_en") or "")
        confianza = verificar_confianza_reddit(autor) if item.get("origen") == "reddit" else "🔎 Plataforma externa"
        etiqueta = "🔥🔥 PRIORIDAD MAXIMA" if score >= 8 else "⚡ OPORTUNIDAD"
        linea_prio = f"🏷 <b>Alerta:</b> {html.escape(prio_tag)}\n" if prio_tag else ""

        if item.get("origen") == "github":
            accion = "Comentar en el Issue de GitHub reclamando el bounty"
        elif item.get("origen") == "hn":
            accion = "Entrar al hilo de HackerNews y contactar al correo/perfil indicado"
        elif fuente.lower() in ("r/slavelabour", "r/donedirtcheap"):
            accion = "Comentar $bid en el post ANTES de tocar el boton de DM"
        else:
            accion = "Toca 'DM Pre-llenado' abajo y envia directo al cliente"

        msg_html = (
            f"<b>{etiqueta} | [{html.escape(categoria)}] {score}/10</b>\n"
            f"{linea_prio}"
            f"💰 <b>Presupuesto:</b> {html.escape(presupuesto)}  |  📍 <b>{html.escape(fuente)}</b>\n"
            f"⏱ <b>Competencia:</b> {html.escape(comp_txt)}\n"
            f"👤 <b>Cliente:</b> {html.escape(confianza)}\n\n"
            f"📌 <b>{html.escape(titulo)}</b>\n"
            f"📝 {html.escape(resumen)}\n"
            f"⚠️ <i>{html.escape(accion)}</i>\n\n"
            f"📋 <b>PITCH (toca para copiar):</b>\n"
            f"<code>{html.escape(pitch)}</code>"
        )
        msg_plano = (
            f"{etiqueta} [{categoria}] {score}/10 {prio_tag}\nPresupuesto: {presupuesto} | {fuente} | {comp_txt} | {confianza}\n\n"
            f"{titulo}\n{resumen}\nProtocolo: {accion}\nLink: {link}\n\nPITCH:\n{pitch}"
        )

        botones = []
        fila = []
        if link.startswith("http"):
            texto_btn = "💎 Abrir Bounty" if item.get("origen") == "github" else ("🔥 Abrir HN" if item.get("origen") == "hn" else "🚀 Abrir Post")
            fila.append({"text": texto_btn, "url": link})
        dm_url = construir_dm_reddit(autor, titulo, pitch)
        if dm_url and len(dm_url) < 1800:
            fila.append({"text": "⚡ DM Pre-llenado", "url": dm_url})
        if fila:
            botones.append(fila)

        enviado = publicar_telegram(msg_html, msg_plano, botones=botones)
        log_evento(f"Lead {score}/10 ({fuente}): {titulo[:55]}")
        if modo_sonido and score >= 7:
            alerta_sonora("ballena" if "HIGH-TICKET" in prio_tag else ("alta" if score >= 8 else "media"))

        if conn is not None:
            conn.execute(
                "INSERT INTO leads (fuente, autor, titulo, categoria, presupuesto, score, competencia, confianza, prioridad_tag, link) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (fuente, autor, titulo, categoria, presupuesto, score, comp_txt, confianza, prio_tag, link),
            )
            conn.commit()
    return True, enviado, tok_est

def enviar_resumen_telegram(chat_id: str | None = None) -> str:
    conn = preparar_db()
    try:
        hoy = datetime.now().strftime("%Y-%m-%d")
        row = conn.execute(
            "SELECT descartados_local, evaluados_ia, alertas_enviadas, tokens_est_usados, tokens_est_ahorrados FROM stats_diarias WHERE fecha = ?",
            (hoy,),
        ).fetchone()
        desc, ev, al, t_us, t_ah = row if row else (0, 0, 0, 0, 0)
        total_usd = conn.execute("SELECT COALESCE(SUM(ganancia_usd), 0) FROM leads WHERE estado = 'ganado'").fetchone()[0]
        total_leads = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        ganados = conn.execute("SELECT COUNT(*) FROM leads WHERE estado = 'ganado'").fetchone()[0]
        pendientes = conn.execute("SELECT COUNT(*) FROM leads WHERE estado IN ('nuevo', 'contactado', 'negociando')").fetchone()[0]

        msg = (
            f"<b>📊 RESUMEN ZEROTOUCH TITAN ({hoy})</b>\n\n"
            f"🛡️ <b>Basura bloqueada sin IA:</b> {desc} (~{t_ah:,} tokens ahorrados)\n"
            f"🤖 <b>Ofertas analizadas hoy:</b> {ev} (~{t_us:,} tokens usados)\n"
            f"⚡ <b>Alertas enviadas hoy:</b> {al}\n"
            f"📂 <b>Leads activos en CRM:</b> {pendientes} (Total: {total_leads})\n"
            f"🏆 <b>Clientes ganados:</b> {ganados}\n"
            f"💵 <b>Total facturado:</b> ${total_usd:.2f} USD"
        )
        publicar_telegram(msg, msg, chat_id=chat_id)
        return msg
    finally:
        conn.close()

def ejecutar_ciclo(modo_sonido: bool = False) -> dict:
    cfg = cargar_config()
    max_ia = max(1, safe_int(cfg.get("max_ia_por_ciclo", 16), 16))
    t0 = time.time()
    hora = datetime.now().strftime("%H:%M:%S")
    log_evento("Iniciando barrido TITAN (16 fuentes)")
    print(f"\n{C.BOLD}{C.CYAN}[{hora}] Iniciando Radar TITAN v11.5 (16 Fuentes + Dedup + Trust)...{C.RESET}", flush=True)

    conn = preparar_db()
    descartados_local = 0
    duplicados_sem = 0
    evaluadas_ia = 0
    alertas_enviadas = 0
    tok_usados = 0
    tok_ahorrados = 0
    try:
        aprendizaje = contexto_aprendizaje_crm(conn)
        recientes = [
            r[0]
            for r in conn.execute("SELECT titulo_palabras FROM vistos WHERE titulo_palabras != '' ORDER BY ts DESC LIMIT 250").fetchall()
        ]

        for item in recolectar_todo(cfg):
            ya_visto = conn.execute(
                "SELECT 1 FROM vistos WHERE post_id = ? OR (titulo_norm != '' AND titulo_norm = ?)",
                (item["id"], item["titulo_norm"]),
            ).fetchone()
            if ya_visto:
                continue

            palabras = item.get("titulo_palabras", "")
            if palabras and any(similitud_jaccard(palabras, prev) >= 0.72 for prev in recientes):
                conn.execute("INSERT OR IGNORE INTO vistos (post_id, titulo_norm, titulo_palabras) VALUES (?, ?, ?)", (item["id"], item["titulo_norm"], palabras))
                conn.commit()
                duplicados_sem += 1
                tok_ahorrados += 420
                continue

            if not item["es_tech"]:
                conn.execute("INSERT OR IGNORE INTO vistos (post_id, titulo_norm, titulo_palabras) VALUES (?, ?, ?)", (item["id"], item["titulo_norm"], palabras))
                conn.commit()
                descartados_local += 1
                tok_ahorrados += 420
                continue

            if evaluadas_ia >= max_ia:
                print(f"{C.YELLOW}[~] Tope de {max_ia} analisis IA alcanzado (resto queda para el siguiente ciclo).{C.RESET}", flush=True)
                break

            ok, enviado, t_est = evaluar_y_enviar(item, cfg, conn=conn, modo_sonido=modo_sonido, aprendizaje=aprendizaje)
            tok_usados += t_est
            if ok:
                conn.execute("INSERT OR IGNORE INTO vistos (post_id, titulo_norm, titulo_palabras) VALUES (?, ?, ?)", (item["id"], item["titulo_norm"], palabras))
                conn.commit()
                if palabras:
                    recientes.append(palabras)
                evaluadas_ia += 1
                if enviado:
                    alertas_enviadas += 1
            time.sleep(0.55)

        followups = revisar_recordatorios_followup(conn, cfg)
        registrar_metricas(
            conn,
            descartados=descartados_local + duplicados_sem,
            ia=evaluadas_ia,
            alertas=alertas_enviadas,
            tok_usados=tok_usados,
            tok_ahorrados=tok_ahorrados,
        )
        dur = round(time.time() - t0, 1)
        resumen_txt = f"Ciclo terminado en {dur}s | Filtrados: {descartados_local + duplicados_sem} | IA: {evaluadas_ia} | Alertas: {alertas_enviadas}"
        log_evento(resumen_txt)
        print(f"{C.GREEN}{resumen_txt} | Followups: {followups}{C.RESET}", flush=True)
        return {
            "descartados": descartados_local + duplicados_sem,
            "ia": evaluadas_ia,
            "alertas": alertas_enviadas,
            "followups": followups,
            "segundos": dur,
        }
    finally:
        conn.close()

def modo_sniper() -> None:
    cfg = cargar_config()
    intervalo = max(45, safe_int(cfg.get("intervalo_sniper_seg", 70), 70))
    print(f"\n{C.BOLD}{C.MAGENTA}=== MODO FRANCOTIRADOR TITAN (Cada {intervalo}s + Ballenas + Sonido) ==={C.RESET}")
    print(f"{C.DIM}Minimiza esta ventana mientras usas tu PC. Presiona Ctrl+C para salir.{C.RESET}")
    ciclo_n = 0
    try:
        while True:
            ciclo_n += 1
            print(f"\n{C.DIM}--- Barrido TITAN #{ciclo_n} ---{C.RESET}")
            ejecutar_ciclo(modo_sonido=True)
            print(f"{C.DIM}Esperando {intervalo}s para el proximo barrido...{C.RESET}", flush=True)
            time.sleep(intervalo)
    except KeyboardInterrupt:
        print(f"\n{C.YELLOW}[*] Modo Francotirador detenido.{C.RESET}\n")

if __name__ == "__main__":
    if "--test" in sys.argv:
        cfg_t = cargar_config()
        prueba = {
            "fuente": "r/forhire",
            "autor": "spez",
            "titulo": "[Hiring] Urgent Python developer to scrape Shopify stores ($300 USD ongoing)",
            "texto": "Looking for a clean Python script to extract product titles, variants, and prices from 5 Shopify stores into CSV. Need it today, potential ongoing work.",
            "link": "https://www.reddit.com/r/forhire/",
            "comp_txt": "🎯 SANGRE FRESCA (2m | 0 com.)",
            "prioridad_tag": "🐋 HIGH-TICKET · 🚨 URGENTE",
            "origen": "reddit",
        }
        evaluar_y_enviar(prueba, cfg_t, modo_sonido=True)
    elif "--sniper" in sys.argv:
        modo_sniper()
    elif "--resumen" in sys.argv:
        enviar_resumen_telegram()
    else:
        ejecutar_ciclo(modo_sonido=False)