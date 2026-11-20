import os
import re
import sys
import html
import time
import random
import threading
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
    safe_float,
    safe_bool,
    extraer_score,
    extraer_presupuesto_usd,
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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
}

GITHUB_HEADERS = {
    "User-Agent": "ZeroTouchOverdrive/12.7",
    "Accept": "application/vnd.github+json",
}
if os.getenv("GITHUB_TOKEN"):
    GITHUB_HEADERS["Authorization"] = f"Bearer {os.getenv('GITHUB_TOKEN')}"

RSS2JSON_LOCK = threading.Lock()
PULLPUSH_LOCK = threading.Lock()
_REDDIT_LOCK = threading.Lock()
_REDDIT_DIRECTO_403 = False

MULTIREDDIT_BATCHES = [
    ("Batch-Core", ["forhire", "slavelabour", "hiring", "freelance_forhire", "DoneDirtCheap"]),
    ("Batch-Tech", ["Jobs4Bitcoins", "Jobbit", "WebDevClassifieds", "requestabot", "ProgrammingTasks"]),
    ("Batch-Niche", ["PythonJobs", "automate", "webscraping", "Discord_Bots"]),
]

SUBS_SIN_TAG_OBLIGATORIO = {"hiring", "requestabot", "programmingtasks", "pythonjobs", "automate"}
SUBS_NICHO_ESTRICTO = {"webscraping", "discord_bots"}
SUBS_DEV_BONUS = {"pythonjobs", "programmingtasks", "requestabot", "webscraping", "discord_bots"}
SUBS_BLACKLIST = {
    "signupsforpay", "referrals", "beermoney", "beermoneyglobal", "freebies",
    "borrow", "assistance", "homeworkhelp", "domyhomework", "essaywriting",
    "cryptomoonshots", "airdrops", "dirtysnapchat", "onlyfansreviews",
}

REGEX_DESCARTAR = re.compile(
    r"((\[|\()\s*(for\s*hire|forhire|offer|selling)\s*(\]|\))|^\s*(for\s*hire|offer)\b|\bavailable\s+for\s+hire\b)",
    re.IGNORECASE,
)
REGEX_CERRADO = re.compile(
    r"((\[|\()\s*(closed|filled|completed|expired|found|hired|taken)\s*(\]|\))|\b(position\s+filled|no\s+longer\s+needed|closed|completed)\b)",
    re.IGNORECASE,
)
REGEX_ACEPTAR = re.compile(
    r"((\[|\()\s*(hiring|task|paid|request)\s*(\]|\))|^\s*(hiring|task|paid)\b|^\[h\]|\bhiring\b)",
    re.IGNORECASE,
)
REGEX_GLOBAL_HIRING = re.compile(
    r"((\[|\()\s*(hiring|task|paid|request)\s*(\]|\))|"
    r"\b(looking\s+to\s+hire|need\s+a\s+(python|dev|developer|freelancer|scraper|bot|programmer)|"
    r"will\s+pay|paying\s+\$?\d+|hire\s+someone\s+to|budget\s*(is|:)?\s*\$?\d+|paid\s+(task|project|gig))\b)",
    re.IGNORECASE,
)
REGEX_SPAM = re.compile(
    r"\b(kyc|referral|sign\s*up\s*bonus|verify\s*account|upvote|google\s*review|"
    r"trustpilot|onlyfans|chatter|dm\s*on\s*whatsapp|quick\s*\$[1-5]\b|clickworker|survey|betting\s*account|create\s+accounts?)\b",
    re.IGNORECASE,
)
REGEX_HN_DESCARTE = re.compile(r"\b(seeking\s+work|available\s+for\s+hire|for\s+hire|looking\s+for\s+work)\b", re.IGNORECASE)

REGEX_TECH_FUERTE = re.compile(
    r"\b(python|scrap\w*|selenium|playwright|beautifulsoup|bs4|puppeteer|telegram|discord|"
    r"webhook|apis?|rest\s*api|graphql|json|csv|sql|sqlite|postgres\w*|mysql|mongodb|pandas|"
    r"openpyxl|fastapi|flask|django|nodejs|node\.js|typescript|javascript|react|nextjs|next\.js|"
    r"php|laravel|n8n|zapier|make\.com|airtable|apps\s*script|chrome\s*extension|browser\s*extension|"
    r"crawler|crawling|automat\w*|script\w*|bots?|docker|linux|vps|deploy|shopify\s*api|"
    r"woocommerce|regex|ocr|llm|openai|gemini\s*api|langchain|github\s*actions?)\b",
    re.IGNORECASE,
)
REGEX_TECH_MEDIO = re.compile(
    r"\b(program\w*|develop\w*|dev|backend|frontend|fullstack|full-stack|database|software|"
    r"coding|code|bug|debug|excel|vba|macro|shopify|wordpress|plugin|saas|mvp|dashboard|"
    r"github|extract\w*|parse|parsing|integrat\w*)\b",
    re.IGNORECASE,
)
REGEX_NO_TECH_PENALIDAD = re.compile(
    r"\b(video\s*edit\w*|thumbnail\w*|photoshop|illustrator|after\s*effects|premiere|capcut|"
    r"logo\s*design|graphic\s*design|voice\s*over|voiceover|ugc\s*creator|tiktok\s*video|"
    r"instagram\s*reel|copywrit\w*|blog\s*post|ghostwrit\w*|essay|homework|assignment|"
    r"exam\s*help|tutor\w*|virtual\s*assistant|cold\s*call\w*|appointment\s*setter|"
    r"data\s*entry|transcrib\w*|translat\w*|resume\s*writ\w*|cover\s*letter|social\s*media\s*manager|"
    r"seo\s*backlinks?|guest\s*post)\b",
    re.IGNORECASE,
)
REGEX_URGENTE = re.compile(r"\b(urgent|asap|today|right\s*now|quick\s*job|within\s*\d+\s*hours?|immediately)\b", re.IGNORECASE)
REGEX_BALLENA = re.compile(r"\b(ongoing|retainer|long[\s-]*term|monthly|saas|agency|full\s*mvp)\b", re.IGNORECASE)

def limpiar_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    desescapado = html.unescape(raw_html)
    texto = BeautifulSoup(desescapado, "html.parser").get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", texto)[:1600]

def normalizar_titulo(titulo: str) -> str:
    limpio = re.sub(r"\[[^\]]*\]|\([^\)]*\)", "", titulo.lower())
    return re.sub(r"\W+", "", limpio)[:90]

def titulo_palabras_limpio(titulo: str) -> str:
    limpio = re.sub(r"\[[^\]]*\]|\([^\)]*\)", " ", titulo.lower())
    return " ".join(re.findall(r"[a-z0-9]{3,}", limpio))[:180]

def puntuar_relevancia_local(titulo: str, texto: str, sub: str = "") -> tuple[int, bool]:
    combinado = f"{titulo} {texto}"
    fuertes = {m.lower() for m in REGEX_TECH_FUERTE.findall(combinado)}
    medios = {m.lower() for m in REGEX_TECH_MEDIO.findall(combinado)}
    penalidades = {m.lower() for m in REGEX_NO_TECH_PENALIDAD.findall(combinado)}
    puntaje = (len(fuertes) * 3) + len(medios) - (len(penalidades) * 3)
    if sub.lower() in SUBS_DEV_BONUS and not penalidades:
        puntaje += 2
    return puntaje, (puntaje >= 2)

def detectar_prioridad_tag(combinado: str, dinero_local: float) -> str:
    tags = []
    if dinero_local >= 250 or REGEX_BALLENA.search(combinado):
        tags.append("🐋 HIGH-TICKET")
    if REGEX_URGENTE.search(combinado):
        tags.append("🚨 URGENTE")
    return " · ".join(tags)

def calcular_competencia(edad_min: int | None, comentarios: int | None) -> tuple[str, int]:
    if edad_min is None and comentarios is None:
        return "🔎 RSS en vivo", 0
    if edad_min is not None and comentarios is None:
        if edad_min <= 20:
            return f"⚡ RSS Fresco ({edad_min}m)", 1
        return f"⚡ RSS Nativo ({edad_min}m)", 0
    edad_m = edad_min if edad_min is not None else 999
    com = comentarios if comentarios is not None else 0
    if edad_m <= 20 and com <= 2:
        return f"🎯 SANGRE FRESCA ({edad_m}m | {com} com.)", 2
    if com <= 5:
        return f"🟢 Baja ({edad_m}m | {com} com.)", 1
    if com <= 12:
        return f"🟡 Media ({edad_m}m | {com} com.)", 0
    return f"🔴 Alta ({edad_m}m | {com} com.)", -1

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
        "text": mensaje_html[:4050],
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

def _evaluar_post_reddit_comun(
    post_id: str,
    sub: str,
    autor: str,
    titulo: str,
    cuerpo: str,
    flair: str,
    link: str,
    edad_min: int | None,
    comentarios: int | None,
    cfg: dict,
    es_global: bool = False,
    stats_descarte: dict | None = None,
) -> dict | None:
    def _contar(razon: str) -> None:
        if stats_descarte is not None:
            stats_descarte[razon] = stats_descarte.get(razon, 0) + 1

    sub_low = (sub or "").lower().strip()
    if not titulo or sub_low in SUBS_BLACKLIST:
        _contar("spam_basura")
        return None
    if autor.lower() in ("[deleted]", "automoderator") or cuerpo.strip().lower() in ("[removed]", "[deleted]"):
        _contar("cerrados_borrados")
        return None

    cabecera = f"{flair} {titulo}".strip()
    combinado = f"{cabecera} {cuerpo}".strip()

    if REGEX_CERRADO.search(cabecera):
        _contar("cerrados_borrados")
        return None
    if REGEX_DESCARTAR.search(cabecera):
        _contar("for_hire_offer")
        return None
    if REGEX_SPAM.search(combinado) or not pasa_blacklist_custom(combinado, cfg.get("palabras_extra_blacklist", [])):
        _contar("spam_basura")
        return None

    if es_global or sub_low in SUBS_NICHO_ESTRICTO:
        if not REGEX_GLOBAL_HIRING.search(combinado):
            _contar("sin_intencion_pago")
            return None
    elif sub_low not in SUBS_SIN_TAG_OBLIGATORIO:
        if not REGEX_ACEPTAR.search(cabecera):
            _contar("sin_intencion_pago")
            return None

    tech_score, es_tech = puntuar_relevancia_local(titulo, cuerpo, sub=sub_low)
    comp_txt, comp_bonus = calcular_competencia(edad_min, comentarios)
    dinero_local = extraer_presupuesto_usd(combinado)
    prio_tag = detectar_prioridad_tag(combinado, dinero_local)

    return {
        "id": post_id or link,
        "fuente": f"r/{sub}" if sub else "Reddit",
        "autor": autor,
        "titulo": titulo,
        "titulo_norm": normalizar_titulo(titulo),
        "titulo_palabras": titulo_palabras_limpio(titulo),
        "texto": cuerpo,
        "link": link,
        "es_tech": es_tech,
        "tech_score": tech_score,
        "edad_min": edad_min,
        "comentarios": comentarios,
        "comp_txt": comp_txt,
        "comp_bonus": comp_bonus + (2 if prio_tag else 0) + (1 if dinero_local >= 100 else 0) + (1 if tech_score >= 6 else 0),
        "dinero_local": dinero_local,
        "prioridad_tag": prio_tag,
        "origen": "reddit",
    }

def procesar_child_reddit(
    d: dict,
    cfg: dict,
    fuente_forzada: str | None = None,
    es_global: bool = False,
    stats_descarte: dict | None = None,
    max_horas_override: int | None = None,
) -> dict | None:
    if d.get("over_18") or d.get("removed_by_category"):
        if stats_descarte is not None:
            stats_descarte["cerrados_borrados"] = stats_descarte.get("cerrados_borrados", 0) + 1
        return None
    ahora = time.time()
    max_h = max_horas_override or max(1, safe_int(cfg.get("max_horas_post", 12), 12))
    creado = safe_float(d.get("created_utc"), ahora)
    edad_seg = max(0.0, ahora - creado)
    if edad_seg > (max_h * 3600):
        if stats_descarte is not None:
            stats_descarte["viejos"] = stats_descarte.get("viejos", 0) + 1
        return None

    sub = (d.get("subreddit") or "").strip()
    if not sub and fuente_forzada:
        sub = fuente_forzada.replace("r/", "")

    perm = d.get("permalink") or ""
    link = f"https://www.reddit.com{perm}" if perm.startswith("/") else (d.get("full_link") or d.get("url") or "")

    return _evaluar_post_reddit_comun(
        post_id=d.get("name") or d.get("id") or link,
        sub=sub,
        autor=d.get("author") or "",
        titulo=(d.get("title") or "").strip(),
        cuerpo=(d.get("selftext") or "")[:1600],
        flair=(d.get("link_flair_text") or "").strip(),
        link=link,
        edad_min=int(edad_seg // 60),
        comentarios=safe_int(d.get("num_comments", 0), 0),
        cfg=cfg,
        es_global=es_global,
        stats_descarte=stats_descarte,
    )

def parsear_atom_reddit(xml_text: str, sub_default: str, cfg: dict, stats_descarte: dict | None = None) -> list:
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
        sub_real = sub_default
        for ch in entry:
            tag = ch.tag.split("}", 1)[-1]
            if tag == "id" and ch.text:
                post_id = ch.text.strip()
            elif tag == "title" and ch.text:
                titulo = ch.text.strip()
            elif tag == "link":
                link = ch.attrib.get("href", link)
            elif tag == "category":
                term = (ch.attrib.get("term") or "").strip()
                if term:
                    sub_real = term
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
                    if stats_descarte is not None:
                        stats_descarte["viejos"] = stats_descarte.get("viejos", 0) + 1
                    continue
                edad_min = int(diff_seg // 60)
            except ValueError:
                pass

        item = _evaluar_post_reddit_comun(
            post_id=post_id or link,
            sub=sub_real,
            autor=autor,
            titulo=titulo,
            cuerpo=contenido,
            flair="",
            link=link,
            edad_min=edad_min,
            comentarios=None,
            cfg=cfg,
            es_global=False,
            stats_descarte=stats_descarte,
        )
        if item:
            resultados.append(item)
    return resultados

def marcar_reddit_403() -> None:
    global _REDDIT_DIRECTO_403
    with _REDDIT_LOCK:
        _REDDIT_DIRECTO_403 = True

def reddit_directo_disponible() -> bool:
    with _REDDIT_LOCK:
        return not _REDDIT_DIRECTO_403

def consultar_pullpush(params: dict) -> list | None:
    with PULLPUSH_LOCK:
        time.sleep(0.18)
        try:
            r = SESSION.get(
                "https://api.pullpush.io/reddit/search/submission/",
                params=params,
                headers={"User-Agent": REDDIT_HEADERS["User-Agent"]},
                timeout=12,
            )
            if r.status_code == 200:
                return r.json().get("data", [])
        except Exception:
            pass
    return None

def consultar_rss2json_seguro(rss_url: str) -> list | None:
    api_url = f"https://api.rss2json.com/v1/api.json?rss_url={quote(rss_url, safe='')}"
    with RSS2JSON_LOCK:
        time.sleep(0.45)
        try:
            r = SESSION.get(api_url, headers={"User-Agent": REDDIT_HEADERS["User-Agent"]}, timeout=10)
            if r.status_code == 200 and r.json().get("status") == "ok":
                return r.json().get("items", [])
        except Exception:
            pass
    return None

def obtener_lote_multireddit(nombre_lote: str, subs: list[str], cfg: dict) -> tuple[list, dict]:
    combo = "+".join(subs)
    stats_desc: dict[str, int] = {}
    items: list = []

    # Nivel 1 y 2: Reddit directo solo si no detectamos 403 en este ciclo
    if reddit_directo_disponible():
        try:
            r = SESSION.get(f"https://www.reddit.com/r/{combo}/new.json?limit=45&raw_json=1", headers=REDDIT_HEADERS, timeout=8)
            if r.status_code == 200:
                children = r.json().get("data", {}).get("children", [])
                for child in children:
                    it = procesar_child_reddit(child.get("data", {}), cfg, stats_descarte=stats_desc)
                    if it:
                        items.append(it)
                tech_n = sum(1 for x in items if x["es_tech"])
                print(f"{C.DIM}[OK] {nombre_lote:<16} (JSON {len(children):2d} raw) -> {len(items):2d} hiring ({tech_n} tech){C.RESET}", flush=True)
                return items, {"fuente": nombre_lote, "modo": "JSON", "ok": True, "bruto": len(children), "tech": tech_n, "descartes": stats_desc}
            if r.status_code == 403:
                marcar_reddit_403()
        except Exception:
            pass

    if reddit_directo_disponible():
        try:
            r = SESSION.get(f"https://www.reddit.com/r/{combo}/new/.rss", headers=REDDIT_HEADERS, timeout=8)
            if r.status_code == 200 and "<entry>" in r.text:
                items = parsear_atom_reddit(r.text, subs[0], cfg, stats_descarte=stats_desc)
                tech_n = sum(1 for x in items if x["es_tech"])
                print(f"{C.DIM}[OK] {nombre_lote:<16} (XML nativo) -> {len(items):2d} hiring ({tech_n} tech){C.RESET}", flush=True)
                return items, {"fuente": nombre_lote, "modo": "XML", "ok": True, "bruto": len(items) + sum(stats_desc.values()), "tech": tech_n, "descartes": stats_desc}
            if r.status_code == 403:
                marcar_reddit_403()
        except Exception:
            pass

    # Nivel 3: PullPush individual por subreddit (rapido y sin 403; ventana flexible por posible lag de indice)
    max_h_pp = max(36, safe_int(cfg.get("max_horas_post", 12), 12))
    bruto_tot = 0
    ok_subs = 0
    subs_fallidos = []

    for sub in subs:
        raw_list = consultar_pullpush({"subreddit": sub, "size": 15, "sort": "desc", "sort_type": "created_utc"})
        if raw_list is not None:
            ok_subs += 1
            bruto_tot += len(raw_list)
            for d in raw_list:
                it = procesar_child_reddit(d, cfg, fuente_forzada=f"r/{sub}", stats_descarte=stats_desc, max_horas_override=max_h_pp)
                if it:
                    items.append(it)
        else:
            subs_fallidos.append(sub)

    # Nivel 4: rss2json SOLO para algun subreddit puntual donde PullPush haya fallado
    for sub in subs_fallidos:
        raw_items = consultar_rss2json_seguro(f"https://www.reddit.com/r/{sub}/new/.rss")
        if raw_items is not None:
            ok_subs += 1
            bruto_tot += len(raw_items)
            for raw in raw_items[:12]:
                it = _evaluar_post_reddit_comun(
                    post_id=raw.get("guid", raw.get("link", "")),
                    sub=sub,
                    autor=(raw.get("author") or "").replace("/u/", "").strip(),
                    titulo=(raw.get("title") or "").strip(),
                    cuerpo=limpiar_html(raw.get("description", "")),
                    flair="",
                    link=raw.get("link", ""),
                    edad_min=None,
                    comentarios=None,
                    cfg=cfg,
                    es_global=False,
                    stats_descarte=stats_desc,
                )
                if it:
                    items.append(it)

    tech_n = sum(1 for x in items if x["es_tech"])
    modo_txt = f"PullPush {ok_subs}/{len(subs)} ({bruto_tot} raw)" if ok_subs else "ERROR"
    color = C.CYAN if ok_subs == len(subs) else (C.YELLOW if ok_subs else C.RED)
    print(f"{color}[{'OK' if ok_subs else '!'}] {nombre_lote:<16} ({modo_txt}) -> {len(items):2d} hiring ({tech_n} tech){C.RESET}", flush=True)
    return items, {"fuente": nombre_lote, "modo": modo_txt, "ok": ok_subs > 0, "bruto": bruto_tot, "tech": tech_n, "descartes": stats_desc}

def buscar_reddit_global(query_str: str, query_pp: str, etiqueta: str, cfg: dict) -> tuple[list, dict]:
    items = []
    stats_desc: dict[str, int] = {}

    if reddit_directo_disponible():
        try:
            url = f"https://www.reddit.com/search.json?q={quote(query_str)}&sort=new&t=day&limit=25&raw_json=1"
            r = SESSION.get(url, headers=REDDIT_HEADERS, timeout=9)
            if r.status_code == 200:
                children = r.json().get("data", {}).get("children", [])
                for child in children:
                    item = procesar_child_reddit(child.get("data", {}), cfg, es_global=True, stats_descarte=stats_desc)
                    if item and item["es_tech"]:
                        items.append(item)
                print(f"{C.CYAN}[OK] {etiqueta:<16} (JSON {len(children):2d} raw) -> {len(items):2d} joyas tech{C.RESET}", flush=True)
                return items, {"fuente": etiqueta, "modo": "JSON", "ok": True, "bruto": len(children), "tech": len(items), "descartes": stats_desc}
            if r.status_code == 403:
                marcar_reddit_403()
        except Exception:
            pass

    max_h_pp = max(48, safe_int(cfg.get("max_horas_post", 12), 12))
    raw_list = consultar_pullpush({"q": query_pp, "size": 30, "sort": "desc", "sort_type": "created_utc"})
    if raw_list is not None:
        for d in raw_list:
            item = procesar_child_reddit(d, cfg, es_global=True, stats_descarte=stats_desc, max_horas_override=max_h_pp)
            if item and item["es_tech"]:
                items.append(item)
        print(f"{C.CYAN}[OK] {etiqueta:<16} (PullPush {len(raw_list):2d}) -> {len(items):2d} joyas tech{C.RESET}", flush=True)
        return items, {"fuente": etiqueta, "modo": "PullPush", "ok": True, "bruto": len(raw_list), "tech": len(items), "descartes": stats_desc}

    print(f"{C.YELLOW}[!] {etiqueta:<16} Sin respuesta temporal{C.RESET}", flush=True)
    return items, {"fuente": etiqueta, "modo": "BLOQUEADO", "ok": False, "bruto": 0, "tech": 0, "descartes": stats_desc}

def buscar_github_bounties() -> tuple[list, dict]:
    items = []
    ahora = datetime.now(timezone.utc)
    desde = (ahora - timedelta(days=7)).strftime("%Y-%m-%d")
    q = quote(f"is:issue is:open (label:bounty OR algora) created:>={desde} (python OR scraper OR bot OR automation OR api)")
    url = f"https://api.github.com/search/issues?q={q}&sort=created&order=desc&per_page=15"
    try:
        r = SESSION.get(url, headers=GITHUB_HEADERS, timeout=12)
        if r.status_code == 200:
            crudos = r.json().get("items", [])
            for iss in crudos:
                titulo = iss.get("title", "")
                cuerpo = (iss.get("body") or "")[:1400]
                labels_list = [str(lb.get("name", "")) for lb in (iss.get("labels") or [])]
                labels_txt = " ".join(labels_list)
                combinado = f"{titulo} {labels_txt} {cuerpo}"
                dinero_local = extraer_presupuesto_usd(combinado)
                tiene_label_bounty = any("bounty" in lb.lower() or "algora" in lb.lower() or "$" in lb for lb in labels_list)
                tech_score, es_tech = puntuar_relevancia_local(titulo, cuerpo)
                if dinero_local <= 0 and not (tiene_label_bounty and es_tech):
                    continue
                edad_min = 120
                if iss.get("created_at"):
                    try:
                        dt = datetime.fromisoformat(iss["created_at"].replace("Z", "+00:00"))
                        edad_min = max(0, int((ahora - dt).total_seconds() // 60))
                    except ValueError:
                        pass
                comentarios = safe_int(iss.get("comments", 0), 0)
                prefijo_b = f"[Bounty ${int(dinero_local)}]" if dinero_local > 0 else "[Bounty]"
                items.append({
                    "id": f"gh_bounty_{iss.get('id')}",
                    "fuente": "GitHub Bounty",
                    "autor": "github",
                    "titulo": f"{prefijo_b} {titulo}",
                    "titulo_norm": normalizar_titulo(titulo),
                    "titulo_palabras": titulo_palabras_limpio(titulo),
                    "texto": f"Labels: {labels_txt}\n{cuerpo}"[:1500],
                    "link": iss.get("html_url", ""),
                    "es_tech": True,
                    "tech_score": max(6, tech_score),
                    "edad_min": edad_min,
                    "comentarios": comentarios,
                    "comp_txt": f"💎 Issue ({edad_min // 60}h | {comentarios} com.)",
                    "comp_bonus": 2 if comentarios <= 2 else 0,
                    "dinero_local": dinero_local,
                    "prioridad_tag": "🐋 HIGH-TICKET" if dinero_local >= 250 else "",
                    "origen": "github",
                })
            print(f"{C.MAGENTA}[OK] GitHub Bounties  (API  {len(crudos):2d} raw) -> {len(items):2d} recompensas{C.RESET}", flush=True)
            return items, {"fuente": "GitHub Bounties", "modo": "API", "ok": True, "bruto": len(crudos), "tech": len(items), "descartes": {}}
        return items, {"fuente": "GitHub Bounties", "modo": f"HTTP {r.status_code}", "ok": False, "bruto": 0, "tech": 0, "descartes": {}}
    except Exception as e:
        print(f"{C.YELLOW}[!] Error GitHub Bounties: {e}{C.RESET}", flush=True)
        return items, {"fuente": "GitHub Bounties", "modo": "ERROR", "ok": False, "bruto": 0, "tech": 0, "descartes": {}}

def buscar_hackernews_freelance() -> tuple[list, dict]:
    items = []
    ahora_ts = time.time()
    hace_14d = int(ahora_ts - 14 * 86400)
    vistos_hn = set()
    bruto = 0
    ok_alg = False
    for q in ("freelance python", "hiring python"):
        url = f"https://hn.algolia.com/api/v1/search_by_date?query={quote(q)}&tags=comment&numericFilters=created_at_i>{hace_14d}&hitsPerPage=12"
        try:
            r = SESSION.get(url, timeout=10)
            if r.status_code == 200:
                ok_alg = True
                hits = r.json().get("hits", [])
                bruto += len(hits)
                for hit in hits:
                    obj_id = hit.get("objectID")
                    if not obj_id or obj_id in vistos_hn:
                        continue
                    vistos_hn.add(obj_id)
                    texto = limpiar_html(hit.get("comment_text", ""))
                    if not texto or len(texto) < 60 or REGEX_HN_DESCARTE.search(texto):
                        continue
                    if not re.search(r"\b(seeking\s+freelancer|looking\s+to\s+hire|hiring\s+(a\s+)?(freelance|contract|python)|need\s+a\s+freelancer)\b", texto, re.IGNORECASE):
                        continue
                    tech_score, es_tech = puntuar_relevancia_local("", texto)
                    if not es_tech:
                        continue
                    creado_i = safe_int(hit.get("created_at_i", int(ahora_ts)), int(ahora_ts))
                    edad_min = max(0, int((ahora_ts - creado_i) // 60))
                    story_title = hit.get("story_title") or "HN Freelance Thread"
                    dinero_local = extraer_presupuesto_usd(texto) or 250.0
                    items.append({
                        "id": f"hn_{obj_id}",
                        "fuente": "HackerNews",
                        "autor": "hackernews",
                        "titulo": f"[HN] {story_title[:70]}",
                        "titulo_norm": normalizar_titulo(texto[:80]),
                        "titulo_palabras": titulo_palabras_limpio(texto[:120]),
                        "texto": texto,
                        "link": f"https://news.ycombinator.com/item?id={obj_id}",
                        "es_tech": True,
                        "tech_score": tech_score,
                        "edad_min": edad_min,
                        "comentarios": 0,
                        "comp_txt": f"🔥 Cliente HN ({edad_min // 60}h)",
                        "comp_bonus": 2,
                        "dinero_local": dinero_local,
                        "prioridad_tag": "🐋 HIGH-TICKET",
                        "origen": "hn",
                    })
        except Exception as e:
            print(f"{C.YELLOW}[!] Error HackerNews: {e}{C.RESET}", flush=True)
    print(f"{C.BLUE}[OK] HackerNews       (API  {bruto:2d} raw) -> {len(items):2d} leads freelance{C.RESET}", flush=True)
    return items, {"fuente": "HackerNews", "modo": "API" if ok_alg else "ERROR", "ok": ok_alg, "bruto": bruto, "tech": len(items), "descartes": {}}

def recolectar_todo(cfg: dict) -> tuple[list, dict]:
    global _REDDIT_DIRECTO_403
    with _REDDIT_LOCK:
        _REDDIT_DIRECTO_403 = False

    ofertas_raw = []
    detalle_fuentes = []
    q_g1 = '("Hiring" OR "looking to hire" OR "will pay") (python OR scraper OR scraping OR selenium OR playwright)'
    q_g2 = '("Hiring" OR "looking to hire" OR "will pay") (telegram OR discord OR bot OR automation OR shopify OR n8n)'

    with ThreadPoolExecutor(max_workers=4) as pool:
        futuros = [pool.submit(obtener_lote_multireddit, nom, subs, cfg) for nom, subs in MULTIREDDIT_BATCHES]
        futuros.append(pool.submit(buscar_reddit_global, q_g1, "hiring python", "Global-Python", cfg))
        futuros.append(pool.submit(buscar_reddit_global, q_g2, "hiring automation", "Global-Bots", cfg))
        futuros.append(pool.submit(buscar_github_bounties))
        futuros.append(pool.submit(buscar_hackernews_freelance))
        for fut in as_completed(futuros):
            try:
                its, meta = fut.result()
                ofertas_raw.extend(its)
                detalle_fuentes.append(meta)
            except Exception as e:
                detalle_fuentes.append({"fuente": "desconocida", "modo": f"ERR {e}", "ok": False, "bruto": 0, "tech": 0, "descartes": {}})

    ofertas_raw.sort(
        key=lambda x: (x.get("comp_bonus", 0), x.get("dinero_local", 0) > 0, x.get("tech_score", 0), -(x.get("edad_min") or 999)),
        reverse=True,
    )
    unicas = []
    vistos_ids = set()
    vistos_tit = set()
    dup_memoria = 0
    for it in ofertas_raw:
        pid = it.get("id")
        tn = it.get("titulo_norm")
        if pid in vistos_ids or (tn and tn in vistos_tit):
            dup_memoria += 1
            continue
        vistos_ids.add(pid)
        if tn:
            vistos_tit.add(tn)
        unicas.append(it)

    descartes_totales: dict[str, int] = {}
    for m in detalle_fuentes:
        for k, v in (m.get("descartes") or {}).items():
            descartes_totales[k] = descartes_totales.get(k, 0) + v

    telemetria = {
        "fuentes_ok": sum(1 for m in detalle_fuentes if m.get("ok")),
        "fuentes_total": len(detalle_fuentes),
        "bruto": sum(m.get("bruto", 0) for m in detalle_fuentes),
        "dup_memoria": dup_memoria,
        "descartes_pre": descartes_totales,
        "detalle_fuentes": sorted(detalle_fuentes, key=lambda x: x["fuente"]),
    }
    return unicas, telemetria

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
            f"📌 {html.escape(titulo[:140])}\n\n"
            f"📋 <b>SEGUIMIENTO LISTO (toca para copiar):</b>\n"
            f"<code>{html.escape(followup[:600])}</code>"
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
        categoria = str(datos.get("categoria") or "Tech")[:40]
        presupuesto = str(datos.get("presupuesto") or "Por definir")[:60]
        pres_num = extraer_presupuesto_usd(presupuesto) or float(item.get("dinero_local") or 0)
        resumen = str(datos.get("resumen_es") or "")[:500]
        pitch = str(datos.get("pitch_en") or "")[:1200]
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
            f"📌 <b>{html.escape(titulo[:180])}</b>\n"
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
        log_evento(f"Lead {score}/10 ({fuente} | ${pres_num:.0f}): {titulo[:52]}")
        if modo_sonido and score >= 7:
            alerta_sonora("ballena" if "HIGH-TICKET" in prio_tag else ("alta" if score >= 8 else "media"))

        if conn is not None:
            ya_existe = link and conn.execute("SELECT 1 FROM leads WHERE link = ?", (link,)).fetchone()
            if not ya_existe:
                conn.execute(
                    "INSERT INTO leads (fuente, autor, titulo, categoria, presupuesto, presupuesto_num, score, competencia, confianza, prioridad_tag, link) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (fuente, autor, titulo, categoria, presupuesto, pres_num, score, comp_txt, confianza, prio_tag, link),
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
        pipeline_usd = conn.execute("SELECT COALESCE(SUM(presupuesto_num), 0) FROM leads WHERE estado IN ('contactado', 'negociando')").fetchone()[0]
        total_leads = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        ganados = conn.execute("SELECT COUNT(*) FROM leads WHERE estado = 'ganado'").fetchone()[0]
        pendientes = conn.execute("SELECT COUNT(*) FROM leads WHERE estado IN ('nuevo', 'contactado', 'negociando')").fetchone()[0]

        msg = (
            f"<b>📊 RESUMEN ZEROTOUCH v12.7 ({hoy})</b>\n\n"
            f"🛡️ <b>Basura bloqueada sin IA:</b> {desc} (~{t_ah:,} tokens ahorrados)\n"
            f"🤖 <b>Ofertas analizadas hoy:</b> {ev} (~{t_us:,} tokens usados)\n"
            f"⚡ <b>Alertas enviadas hoy:</b> {al}\n"
            f"📂 <b>Leads activos en CRM:</b> {pendientes} (Total: {total_leads})\n"
            f"💼 <b>Pipeline en negociacion:</b> ~${pipeline_usd:.0f} USD\n"
            f"🏆 <b>Clientes ganados:</b> {ganados}\n"
            f"💵 <b>Total facturado:</b> ${total_usd:.2f} USD"
        )
        publicar_telegram(msg, msg, chat_id=chat_id)
        return msg
    finally:
        conn.close()

def ejecutar_ciclo(modo_sonido: bool = False, dry_run: bool = False) -> dict:
    cfg = cargar_config()
    max_ia = max(1, safe_int(cfg.get("max_ia_por_ciclo", 16), 16))
    t0 = time.time()
    hora = datetime.now().strftime("%H:%M:%S")
    etiqueta_modo = "DRY-RUN 0-TOKENS" if dry_run else "OVERDRIVE v12.7"
    log_evento(f"Iniciando escaneo {etiqueta_modo}")
    print(f"\n{C.BOLD}{C.CYAN}[{hora}] Iniciando Radar {etiqueta_modo} (Fast-403 + PullPush Per-Sub + Bounties + HN)...{C.RESET}", flush=True)

    conn = preparar_db()
    descartados_no_tech = 0
    duplicados_sem = 0
    ya_vistos_n = 0
    evaluadas_ia = 0
    alertas_enviadas = 0
    tok_usados = 0
    tok_ahorrados = 0
    fallos_ia_seguidos = 0
    candidatas_preview = []

    try:
        filas_v = conn.execute("SELECT post_id, titulo_norm, titulo_palabras FROM vistos ORDER BY ts DESC LIMIT 2500").fetchall()
        vistos_ids = {r[0] for r in filas_v if r[0]}
        vistos_norms = {r[1] for r in filas_v if r[1]}
        recientes = [r[2] for r in filas_v[:250] if r[2]]

        aprendizaje = "" if dry_run else contexto_aprendizaje_crm(conn)
        ofertas, telemetria = recolectar_todo(cfg)

        for item in ofertas:
            pid = item["id"]
            tn = item["titulo_norm"]
            if pid in vistos_ids or (tn and tn in vistos_norms):
                ya_vistos_n += 1
                continue

            palabras = item.get("titulo_palabras", "")
            if palabras and any(similitud_jaccard(palabras, prev) >= 0.76 for prev in recientes):
                if not dry_run:
                    conn.execute("INSERT OR IGNORE INTO vistos (post_id, titulo_norm, titulo_palabras) VALUES (?, ?, ?)", (pid, tn, palabras))
                    conn.commit()
                vistos_ids.add(pid)
                if tn:
                    vistos_norms.add(tn)
                duplicados_sem += 1
                tok_ahorrados += 420
                continue

            if not item["es_tech"]:
                if not dry_run:
                    conn.execute("INSERT OR IGNORE INTO vistos (post_id, titulo_norm, titulo_palabras) VALUES (?, ?, ?)", (pid, tn, palabras))
                    conn.commit()
                vistos_ids.add(pid)
                if tn:
                    vistos_norms.add(tn)
                descartados_no_tech += 1
                tok_ahorrados += 420
                continue

            if dry_run:
                candidatas_preview.append({
                    "fuente": item["fuente"],
                    "titulo": item["titulo"][:90],
                    "tech_score": item.get("tech_score", 0),
                    "dinero": item.get("dinero_local", 0),
                    "comp": item.get("comp_txt", ""),
                })
                continue

            if evaluadas_ia >= max_ia:
                print(f"{C.YELLOW}[~] Tope de {max_ia} analisis IA alcanzado (resto queda para el siguiente ciclo).{C.RESET}", flush=True)
                break

            ok, enviado, t_est = evaluar_y_enviar(item, cfg, conn=conn, modo_sonido=modo_sonido, aprendizaje=aprendizaje)
            tok_usados += t_est
            if ok:
                fallos_ia_seguidos = 0
                conn.execute("INSERT OR IGNORE INTO vistos (post_id, titulo_norm, titulo_palabras) VALUES (?, ?, ?)", (pid, tn, palabras))
                conn.commit()
                vistos_ids.add(pid)
                if tn:
                    vistos_norms.add(tn)
                if palabras:
                    recientes.append(palabras)
                evaluadas_ia += 1
                if enviado:
                    alertas_enviadas += 1
            else:
                fallos_ia_seguidos += 1
                if fallos_ia_seguidos >= 3:
                    log_evento("[!] Circuit Breaker IA activado (3 fallos seguidos)")
                    print(f"{C.RED}[!] Circuit Breaker IA: 3 fallos seguidos. Pausando resto del ciclo.{C.RESET}", flush=True)
                    break
            time.sleep(0.5)

        followups = 0 if dry_run else revisar_recordatorios_followup(conn, cfg)
        pre_desc = sum((telemetria.get("descartes_pre") or {}).values())
        total_desc = descartados_no_tech + duplicados_sem + telemetria.get("dup_memoria", 0) + pre_desc
        if not dry_run:
            registrar_metricas(
                conn,
                descartados=total_desc,
                ia=evaluadas_ia,
                alertas=alertas_enviadas,
                tok_usados=tok_usados,
                tok_ahorrados=tok_ahorrados + (pre_desc * 420),
            )

        dur = round(time.time() - t0, 1)
        f_ok = telemetria["fuentes_ok"]
        f_tot = telemetria["fuentes_total"]
        if dry_run:
            resumen_txt = f"DRY-RUN en {dur}s | Fuentes: {f_ok}/{f_tot} | Bruto: {telemetria['bruto']} | Nuevas candidatas tech: {len(candidatas_preview)} | Bloqueados 0-tokens: {total_desc}"
        else:
            resumen_txt = f"Ciclo v12.7 en {dur}s | Fuentes: {f_ok}/{f_tot} | Filtrados: {total_desc} | IA: {evaluadas_ia} | Alertas: {alertas_enviadas}"
        log_evento(resumen_txt)
        print(f"{C.GREEN}{resumen_txt}{C.RESET}", flush=True)
        if dry_run and candidatas_preview:
            print(f"\n{C.BOLD}Top candidatas nuevas que pasarian a Gemini:{C.RESET}")
            for c in candidatas_preview[:8]:
                print(f"  - [{c['fuente']} | Tech:{c['tech_score']} | ${c['dinero']:.0f}] {c['titulo']} ({c['comp']})")
            print()

        return {
            "dry_run": dry_run,
            "fuentes_ok": f_ok,
            "fuentes_total": f_tot,
            "bruto": telemetria["bruto"],
            "ya_vistos": ya_vistos_n,
            "descartados": total_desc,
            "descartes_pre": telemetria["descartes_pre"],
            "ia": evaluadas_ia,
            "alertas": alertas_enviadas,
            "followups": followups,
            "segundos": dur,
            "detalle_fuentes": telemetria["detalle_fuentes"],
            "candidatas_preview": candidatas_preview[:15],
        }
    finally:
        conn.close()

def modo_sniper() -> None:
    cfg = cargar_config()
    intervalo = max(45, safe_int(cfg.get("intervalo_sniper_seg", 70), 70))
    print(f"\n{C.BOLD}{C.MAGENTA}=== MODO FRANCOTIRADOR OVERDRIVE v12.7 (Cada {intervalo}s + Ballenas + Sonido) ==={C.RESET}")
    print(f"{C.DIM}Minimiza esta ventana mientras usas tu PC. Presiona Ctrl+C para salir.{C.RESET}")
    ciclo_n = 0
    try:
        while True:
            ciclo_n += 1
            print(f"\n{C.DIM}--- Barrido OVERDRIVE #{ciclo_n} ---{C.RESET}")
            ejecutar_ciclo(modo_sonido=True)
            print(f"{C.DIM}Esperando {intervalo}s para el proximo barrido...{C.RESET}", flush=True)
            time.sleep(intervalo)
    except KeyboardInterrupt:
        print(f"\n{C.YELLOW}[*] Modo Francotirador detenido.{C.RESET}\n")

if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        ejecutar_ciclo(modo_sonido=False, dry_run=True)
    elif "--test" in sys.argv:
        cfg_t = cargar_config()
        prueba = {
            "fuente": "r/forhire",
            "autor": "spez",
            "titulo": "[Hiring] Urgent Python developer to scrape Shopify stores ($300 USD ongoing)",
            "texto": "Looking for a clean Python script to extract product titles, variants, and prices from 5 Shopify stores into CSV. Need it today, potential ongoing work.",
            "link": "https://www.reddit.com/r/forhire/",
            "comp_txt": "🎯 SANGRE FRESCA (2m | 0 com.)",
            "prioridad_tag": "🐋 HIGH-TICKET · 🚨 URGENTE",
            "dinero_local": 300.0,
            "origen": "reddit",
        }
        evaluar_y_enviar(prueba, cfg_t, modo_sonido=True)
    elif "--sniper" in sys.argv:
        modo_sniper()
    elif "--resumen" in sys.argv:
        enviar_resumen_telegram()
    else:
        ejecutar_ciclo(modo_sonido=False)