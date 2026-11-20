import re
import html
from bs4 import BeautifulSoup
from core_ia import extraer_presupuesto_usd

SUBS_DEV_BONUS = {"pythonjobs", "programmingtasks", "requestabot", "webscraping", "discord_bots"}

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
    r"woocommerce|regex|ocr|llm|openai|gemini\s*api|langchain|github\s*actions?|etl|pipeline)\b",
    re.IGNORECASE,
)
REGEX_TECH_MEDIO = re.compile(
    r"\b(program\w*|develop\w*|dev|backend|frontend|fullstack|full-stack|database|software|"
    r"coding|code|bug|debug|excel|vba|macro|shopify|wordpress|plugin|saas|mvp|dashboard|"
    r"github|extract\w*|parse|parsing|integrat\w*|remote\s*contract|freelance)\b",
    re.IGNORECASE,
)
REGEX_NO_TECH_PENALIDAD = re.compile(
    r"\b(video\s*edit\w*|thumbnail\w*|photoshop|illustrator|after\s*effects|premiere|capcut|"
    r"logo\s*design|graphic\s*design|voice\s*over|voiceover|ugc\s*creator|tiktok\s*video|"
    r"instagram\s*reel|copywrit\w*|blog\s*post|ghostwrit\w*|essay|homework|assignment|"
    r"exam\s*help|tutor\w*|virtual\s*assistant|cold\s*call\w*|appointment\s*setter|"
    r"data\s*entry|transcrib\w*|translat\w*|resume\s*writ\w*|cover\s*letter|social\s*media\s*manager|"
    r"seo\s*backlinks?|guest\s*post|account\s*executive|sales\s*rep|customer\s*support)\b",
    re.IGNORECASE,
)
REGEX_URGENTE = re.compile(r"\b(urgent|asap|today|right\s*now|quick\s*job|within\s*\d+\s*hours?|immediately)\b", re.IGNORECASE)
REGEX_BALLENA = re.compile(r"\b(ongoing|retainer|long[\s-]*term|monthly|saas|agency|full\s*mvp)\b", re.IGNORECASE)

def limpiar_html(raw_html: str, max_len: int = 1600) -> str:
    if not raw_html:
        return ""
    desescapado = html.unescape(raw_html)
    texto = BeautifulSoup(desescapado, "html.parser").get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", texto)[:max_len]

def normalizar_titulo(titulo: str) -> str:
    limpio = re.sub(r"\[[^\]]*\]|\([^\)]*\)", "", (titulo or "").lower())
    return re.sub(r"\W+", "", limpio)[:90]

def titulo_palabras_limpio(titulo: str) -> str:
    limpio = re.sub(r"\[[^\]]*\]|\([^\)]*\)", " ", (titulo or "").lower())
    return " ".join(re.findall(r"[a-z0-9]{3,}", limpio))[:180]

def pasa_blacklist_custom(texto: str, extras) -> bool:
    if not extras:
        return True
    if isinstance(extras, str):
        extras = [w.strip() for w in extras.split(",") if w.strip()]
    low = (texto or "").lower()
    return not any(str(w).strip().lower() in low for w in extras if str(w).strip())

def puntuar_relevancia_local(titulo: str, texto: str, sub_o_tags: str = "") -> tuple[int, bool]:
    combinado = f"{titulo} {texto} {sub_o_tags}"
    fuertes = {m.lower() for m in REGEX_TECH_FUERTE.findall(combinado)}
    medios = {m.lower() for m in REGEX_TECH_MEDIO.findall(combinado)}
    penalidades = {m.lower() for m in REGEX_NO_TECH_PENALIDAD.findall(combinado)}
    puntaje = (len(fuertes) * 3) + len(medios) - (len(penalidades) * 3)
    if sub_o_tags.lower().strip() in SUBS_DEV_BONUS and not penalidades:
        puntaje += 2
    return puntaje, (puntaje >= 2)

def detectar_prioridad_tag(combinado: str, dinero_local: float) -> str:
    tags = []
    if dinero_local >= 250 or REGEX_BALLENA.search(combinado):
        tags.append("🐋 HIGH-TICKET")
    if REGEX_URGENTE.search(combinado):
        tags.append("🚨 URGENTE")
    return " · ".join(tags)

def calcular_competencia(edad_min: int | None, comentarios: int | None, etiqueta_fallback: str = "🔎 En vivo") -> tuple[str, int]:
    if edad_min is None and comentarios is None:
        return etiqueta_fallback, 0
    if edad_min is not None and comentarios is None:
        if edad_min <= 25:
            return f"⚡ Fresco ({edad_min}m)", 1
        hrs = edad_min // 60
        return (f"⚡ Reciente ({hrs}h)" if hrs >= 1 else f"⚡ Reciente ({edad_min}m)"), 0
    edad_m = edad_min if edad_min is not None else 999
    com = comentarios if comentarios is not None else 0
    if edad_m <= 25 and com <= 2:
        return f"🎯 SANGRE FRESCA ({edad_m}m | {com} com.)", 2
    if com <= 5:
        return f"🟢 Baja ({edad_m}m | {com} com.)", 1
    if com <= 12:
        return f"🟡 Media ({edad_m}m | {com} com.)", 0
    return f"🔴 Alta ({edad_m}m | {com} com.)", -1

def extraer_dinero_combinado(titulo: str, texto: str, monto_directo: float = 0.0) -> float:
    if monto_directo and monto_directo > 0:
        return round(float(monto_directo), 2)
    return extraer_presupuesto_usd(f"{titulo} {texto}")