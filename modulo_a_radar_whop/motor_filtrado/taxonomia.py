from __future__ import annotations

import math
import re
from dataclasses import dataclass

from modulo_a_radar_whop.motor_filtrado.modelos import (
    CategoriaSenal,
    DocumentoNormalizado,
    MatchTaxonomia,
    ResultadoTaxonomia,
    SenalDetectada,
)


@dataclass(frozen=True, slots=True)
class DefinicionSkill:
    clave: str
    familia: str
    es_tech: bool
    peso: float
    alias: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReglaSinergia:
    nombre: str
    familias_requeridas: tuple[str, ...]
    bonus: float
    descripcion: str


# ==================== GRAFO TAXONOMICO: 12 FAMILIAS TECH (140+ SKILLS/ALIAS) ====================
CATALOGO_TECH: tuple[DefinicionSkill, ...] = (
    # 1. SCRAPING & EXTRACCION WEB
    DefinicionSkill("web_scraping", "scraping", True, 4.5, (
        "web scraping", "web scraper", "webscraping", "scrape", "scraper", "scraping",
        "data scraping", "site scraping", "screen scraping", "price scraping", "lead scraping",
    )),
    DefinicionSkill("playwright", "scraping", True, 4.5, ("playwright", "playwright-python", "headless browser")),
    DefinicionSkill("selenium", "scraping", True, 4.2, ("selenium", "webdriver", "chromedriver", "undetected-chromedriver")),
    DefinicionSkill("scrapy", "scraping", True, 4.5, ("scrapy", "scrapy-playwright", "splash")),
    DefinicionSkill("beautifulsoup", "scraping", True, 4.0, ("beautifulsoup", "beautifulsoup4", "bs4", "lxml", "xpath", "css selectors")),
    DefinicionSkill("puppeteer", "scraping", True, 3.8, ("puppeteer", "cheerio", "crawlee", "apify", "firecrawl", "crawl4ai")),
    DefinicionSkill("crawler", "scraping", True, 3.6, ("web crawler", "crawler", "crawling", "spider", "data extraction", "extract data")),
    DefinicionSkill("anti_bot_bypass", "scraping", True, 4.0, ("cloudflare bypass", "captcha solver", "rotating proxies", "residential proxy", "tls fingerprint", "curl_cffi", "cloudscraper")),

    # 2. BOTS & MENSAJERIA
    DefinicionSkill("telegram_bot", "bots_messaging", True, 4.6, (
        "telegram bot", "telegram scraper", "telegram automation", "python-telegram-bot",
        "aiogram", "telethon", "pyrogram", "telegram mini app", "telegram channel",
    )),
    DefinicionSkill("discord_bot", "bots_messaging", True, 4.5, (
        "discord bot", "discord.py", "pycord", "nextcord", "discord.js",
        "discord webhook", "discord automation", "slash commands",
    )),
    DefinicionSkill("whatsapp_slack_bot", "bots_messaging", True, 4.0, (
        "whatsapp bot", "whatsapp api", "baileys", "twilio", "slack bot", "slack app",
        "chatbot", "trading bot", "sniper bot", "monitor bot", "alert bot", "restock bot",
    )),
    DefinicionSkill("bot_generico", "bots_messaging", True, 2.8, ("custom bot", "build a bot", "need a bot", "automated bot", "bots")),

    # 3. PYTHON CORE & SCRIPTING
    DefinicionSkill("python", "python_core", True, 4.4, ("python", "python3", "python 3", "py3", "python script", "python dev", "python developer")),
    DefinicionSkill("scripting", "python_core", True, 3.6, ("automation script", "custom script", "cli tool", "command line tool", "desktop script", "cron job", "scheduled script")),
    DefinicionSkill("python_async", "python_core", True, 3.5, ("asyncio", "aiohttp", "httpx", "requests", "multiprocessing", "threading", "celery")),
    DefinicionSkill("python_gui", "python_core", True, 3.2, ("tkinter", "pyqt", "pyqt6", "pyside6", "customtkinter", "pyinstaller", "exe tool", "streamlit", "gradio")),

    # 4. AUTOMATIZACION & NO-CODE / LOW-CODE
    DefinicionSkill("workflow_automation", "automation", True, 4.2, (
        "workflow automation", "process automation", "business automation", "task automation",
        "automate", "automation", "rpa", "browser automation", "auto-fill", "auto-post",
    )),
    DefinicionSkill("n8n", "automation", True, 4.4, ("n8n", "n8n workflow", "n8n agent", "self-hosted n8n")),
    DefinicionSkill("zapier_make", "automation", True, 4.0, ("zapier", "make.com", "integromat", "pipedream", "activepieces", "windmill")),
    DefinicionSkill("google_apps_script", "automation", True, 3.9, ("apps script", "google apps script", "google sheets automation", "sheets api", "google workspace api")),
    DefinicionSkill("airtable_notion", "automation", True, 3.5, ("airtable api", "airtable automation", "notion api", "hubspot api", "crm integration", "sync data")),
    DefinicionSkill("excel_vba", "automation", True, 3.3, ("openpyxl", "xlwings", "excel automation", "excel macro", "vba macro", "pdf parser", "pdf extraction", "pymupdf", "pdfplumber")),

    # 5. BACKEND, APIs & INTEGRACIONES
    DefinicionSkill("api_integration", "backend_api", True, 4.1, (
        "api integration", "rest api", "restful api", "graphql", "webhook", "webhooks",
        "third-party api", "api wrapper", "api endpoint", "oauth", "oauth2", "jwt",
    )),
    DefinicionSkill("fastapi", "backend_api", True, 4.3, ("fastapi", "uvicorn", "pydantic", "starlette")),
    DefinicionSkill("flask_django", "backend_api", True, 4.0, ("flask", "django", "django rest framework", "drf")),
    DefinicionSkill("nodejs_ts", "backend_api", True, 3.6, ("node.js", "nodejs", "express.js", "nestjs", "typescript", "javascript", "bun", "deno")),
    DefinicionSkill("php_go_rust", "backend_api", True, 3.2, ("laravel", "php", "golang", "rust", "c#", ".net", "spring boot", "ruby on rails")),
    DefinicionSkill("backend_dev", "backend_api", True, 3.0, ("backend", "back-end", "microservices", "server-side", "saas backend", "mvp")),

    # 6. DATA ENGINEERING, ETL & OCR
    DefinicionSkill("pandas_etl", "data_etl", True, 4.1, ("pandas", "polars", "numpy", "etl", "data pipeline", "data cleaning", "data processing", "data transformation")),
    DefinicionSkill("formatos_datos", "data_etl", True, 2.7, ("csv", "json", "jsonl", "parquet", "xml", "yaml", "spreadsheet", "tsv", "regex")),
    DefinicionSkill("ocr_vision", "data_etl", True, 3.8, ("ocr", "tesseract", "pytesseract", "easyocr", "paddleocr", "opencv", "pillow", "image processing")),

    # 7. BASES DE DATOS
    DefinicionSkill("sql_dbs", "databases", True, 3.6, ("sqlite", "postgresql", "postgres", "mysql", "mariadb", "sql", "sqlalchemy", "supabase", "prisma")),
    DefinicionSkill("nosql_dbs", "databases", True, 3.4, ("mongodb", "redis", "firebase", "firestore", "dynamodb", "elasticsearch", "qdrant", "pinecone", "chromadb")),

    # 8. IA, LLMs & AGENTES
    DefinicionSkill("llm_apis", "ai_llm", True, 4.3, (
        "openai api", "gemini api", "claude api", "anthropic", "llm", "llms",
        "gpt-4", "chatgpt api", "deepseek", "openrouter", "ollama", "vllm",
    )),
    DefinicionSkill("ai_agents_rag", "ai_llm", True, 4.2, (
        "ai agent", "ai agents", "rag", "langchain", "langgraph", "llamaindex",
        "crewai", "autogen", "vector database", "embeddings", "mcp server", "function calling",
    )),
    DefinicionSkill("ml_voice", "ai_llm", True, 3.4, ("whisper", "elevenlabs", "hugging face", "pytorch", "scikit-learn", "fine-tuning", "voice agent", "vapi")),

    # 9. E-COMMERCE & PAGOS
    DefinicionSkill("shopify", "ecommerce", True, 3.9, ("shopify", "shopify api", "shopify app", "shopify scraper", "liquid", "shopify store")),
    DefinicionSkill("woocommerce_stripe", "ecommerce", True, 3.6, ("woocommerce", "stripe api", "stripe webhook", "paypal api", "checkout integration", "whop", "lemonsqueezy", "gumroad")),
    DefinicionSkill("marketplaces", "ecommerce", True, 3.4, ("amazon scraper", "amazon sp-api", "ebay api", "etsy api", "walmart api", "inventory sync", "price monitor")),

    # 10. FRONTEND & EXTENSIONES DE NAVEGADOR
    DefinicionSkill("browser_ext", "browser_ext", True, 4.2, ("chrome extension", "browser extension", "firefox addon", "manifest v3", "userscript", "tampermonkey")),
    DefinicionSkill("frontend_modern", "frontend_web", True, 3.3, ("react", "next.js", "nextjs", "vue", "svelte", "tailwind", "html/css", "dashboard", "web app", "full-stack", "fullstack")),
    DefinicionSkill("wordpress_tech", "frontend_web", True, 2.4, ("wordpress plugin", "custom plugin", "wp-json", "fix bug", "bug fix", "debugging")),

    # 11. DEVOPS, SERVIDORES & GITHUB
    DefinicionSkill("devops_deploy", "devops", True, 3.5, (
        "docker", "docker-compose", "linux", "ubuntu", "vps", "nginx", "systemd",
        "github actions", "ci/cd", "aws lambda", "ec2", "s3", "cloudflare workers", "railway", "render", "fly.io",
    )),
    DefinicionSkill("git_bounty", "devops", True, 3.0, ("pull request", "github issue", "open source", "bounty", "unit test", "pytest", "refactor")),

    # 12. TERMINOS GENERALES DE INGENIERIA (peso moderado para evitar falsos positivos solos)
    DefinicionSkill("dev_general", "engineering_gen", True, 1.8, (
        "programmer", "software engineer", "software developer", "web developer",
        "coding", "codebase", "source code", "algorithm", "parse", "parsing",
    )),
)


# ==================== GRAFO ANTI-TECH: 8 FAMILIAS DE RUIDO (PENALIZACION) ====================
CATALOGO_NO_TECH: tuple[DefinicionSkill, ...] = (
    # 1. VIDEO & AUDIO
    DefinicionSkill("video_editing", "video_audio", False, -5.0, (
        "video editor", "video editing", "premiere pro", "after effects", "davinci resolve",
        "capcut", "final cut", "youtube editor", "tiktok editor", "reels editor", "shorts editor",
        "motion graphics", "color grading", "subtitles", "captions", "faceless youtube",
    )),
    DefinicionSkill("audio_voice", "video_audio", False, -4.5, (
        "voice over", "voiceover", "voice actor", "podcast editor", "audio mixing",
        "music producer", "beatmaker", "sound design", "narrator", "singer",
    )),

    # 2. DISENO GRAFICO & 3D
    DefinicionSkill("graphic_design", "graphic_design", False, -4.8, (
        "graphic designer", "graphic design", "logo design", "photoshop", "illustrator",
        "canva", "thumbnail designer", "youtube thumbnail", "flyer", "brochure", "banner design",
        "brand identity", "t-shirt design", "illustration", "character art", "anime art", "nsfw art",
    )),
    DefinicionSkill("modeling_3d", "graphic_design", False, -4.2, (
        "blender", "3d model", "3d artist", "cad designer", "autocad", "solidworks",
        "interior design", "architectural render", "sketchup",
    )),

    # 3. REDACCION, TRADUCCION & CONTENIDO
    DefinicionSkill("copywriting", "copywriting", False, -4.5, (
        "copywriter", "copywriting", "ghostwriter", "blog writer", "article writer",
        "content writer", "scriptwriter", "youtube script", "proofreading", "ebook writer",
        "resume writer", "cv writing", "cover letter", "translator", "translation", "transcription",
    )),

    # 4. VENTAS, MARKETING & REDES SOCIALES
    DefinicionSkill("sales_marketing", "sales_marketing", False, -4.5, (
        "cold caller", "cold calling", "appointment setter", "telemarketer", "sales rep",
        "commission only", "account executive", "door to door", "social media manager",
        "ugc creator", "influencer", "onlyfans chatter", "chatter", "community moderator",
        "seo backlinks", "link building", "guest post", "facebook ads", "meta ads", "google ads manager",
    )),

    # 5. ASISTENCIA VIRTUAL & DATA ENTRY MANUAL
    DefinicionSkill("va_data_entry", "virtual_assistant", False, -4.6, (
        "virtual assistant", "data entry", "copy paste", "copy-paste", "manual entry",
        "customer support", "live chat support", "call center", "bookkeeping", "accounting",
        "personal assistant", "travel planner", "email management",
    )),

    # 6. TAREAS ESCOLARES / TRAMPA ACADEMICA
    DefinicionSkill("academic_cheating", "academic", False, -6.5, (
        "do my homework", "homework help", "write my essay", "college essay", "take my exam",
        "online exam", "proctored exam", "thesis writing", "dissertation", "school assignment",
        "math homework", "calculus exam", "tutoring", "private tutor",
    )),

    # 7. MICROTAREAS BASURA & REVIEWS FALSAS
    DefinicionSkill("microtasks_spam", "microtasks", False, -7.0, (
        "google review", "trustpilot review", "amazon review", "leave a review", "upvote",
        "sign up bonus", "referral bonus", "survey", "surveys", "clickworker",
        "watch videos", "like and subscribe", "follow my instagram", "create accounts",
    )),

    # 8. ESTAFAS KYC / CUENTAS / APUESTAS
    DefinicionSkill("kyc_scam_niche", "scam_niche", False, -8.5, (
        "kyc", "verify account", "account verification", "rent upwork", "upwork account",
        "betting account", "bet365", "sports betting", "gambling account", "crypto airdrop",
        "sugar daddy", "feet pics", "escort",
    )),
)


# ==================== MATRIZ DE SINERGIAS (COMBOS DE ORO PARA FREELANCE) ====================
REGLAS_SINERGIA: tuple[ReglaSinergia, ...] = (
    ReglaSinergia("COMBO_SCRAPER_PYTHON", ("scraping", "python_core"), 3.2, "Scraping directo en Python (tu zona de oro)"),
    ReglaSinergia("COMBO_SCRAPER_ECOM", ("scraping", "ecommerce"), 3.5, "Scraper/Monitor E-commerce (Shopify/Amazon — ticket alto)"),
    ReglaSinergia("COMBO_BOT_PYTHON", ("bots_messaging", "python_core"), 3.2, "Bot Telegram/Discord en Python"),
    ReglaSinergia("COMBO_BOT_API", ("bots_messaging", "backend_api"), 2.8, "Bot conectado a APIs/Webhooks"),
    ReglaSinergia("COMBO_AI_AUTO", ("ai_llm", "automation"), 3.6, "Agente IA / Automatizacion LLM (alta demanda actual)"),
    ReglaSinergia("COMBO_AI_PYTHON", ("ai_llm", "python_core"), 3.0, "Desarrollo IA/LLM en Python"),
    ReglaSinergia("COMBO_ETL_SCRAPE", ("scraping", "data_etl"), 2.8, "Extraccion + limpieza/exportacion de datos"),
    ReglaSinergia("COMBO_API_DB", ("backend_api", "databases"), 2.6, "Backend API + Base de datos"),
    ReglaSinergia("COMBO_AUTO_ECOM", ("automation", "ecommerce"), 3.0, "Automatizacion para tienda E-commerce"),
    ReglaSinergia("COMBO_EXT_SCRAPE", ("browser_ext", "scraping"), 2.9, "Extension de navegador + extraccion"),
    ReglaSinergia("COMBO_DEVOPS_API", ("devops", "backend_api"), 2.0, "Deploy y arquitectura de backend"),
)


# Palabras de negacion en ventana previa (evitan falsos positivos tipo "no wordpress", "not looking for video editing")
REGEX_NEGACION_PREVIA = re.compile(
    r"\b(?:no|not|without|don'?t\s+(?:need|want)|avoid|except|instead\s+of|sin|nada\s+de|no\s+busco|no\s+necesito)\s*$",
    re.IGNORECASE,
)

SUBS_BONUS_DEV = {
    "pythonjobs": 2.5,
    "programmingtasks": 2.5,
    "requestabot": 3.0,
    "webscraping": 3.5,
    "discord_bots": 3.0,
    "n8n": 2.8,
    "hireaprogrammer": 2.2,
    "automate": 2.0,
}

# Multiplicadores segun donde aparece el termino
PESO_ZONA = {
    "titulo": 1.55,
    "tags": 1.20,
    "cuerpo": 1.00,
}


def _compilar_patron_alias(alias: tuple[str, ...]) -> re.Pattern[str]:
    # Ordena de mas largo a mas corto para priorizar frases compuestas sobre palabras sueltas
    ordenados = sorted(set(alias), key=len, reverse=True)
    cuerpo_alt = "|".join(re.escape(a) for a in ordenados)
    # Limite seguro que funciona incluso con c++, c#, .net, node.js, make.com
    return re.compile(rf"(?<![A-Za-z0-9_])(?:{cuerpo_alt})(?![A-Za-z0-9_])", re.IGNORECASE)


class MotorTaxonomia:
    """
    Capa 2 de AEGIS-X: Evalua relevancia tecnica mediante grafo de 180+ skills,
    ponderacion por zona (titulo/tags/cuerpo), ventana de negacion y combos de sinergia.
    """

    def __init__(self) -> None:
        self._reglas_compiladas: list[tuple[DefinicionSkill, re.Pattern[str]]] = [
            (d, _compilar_patron_alias(d.alias))
            for d in (CATALOGO_TECH + CATALOGO_NO_TECH)
        ]

    @staticmethod
    def _esta_negado(texto: str, inicio_match: int) -> bool:
        ventana = texto[max(0, inicio_match - 26):inicio_match]
        return bool(REGEX_NEGACION_PREVIA.search(ventana))

    def evaluar(
        self,
        doc: DocumentoNormalizado,
        sub_o_categoria: str = "",
        whitelist_usuario: list[str] | None = None,
    ) -> ResultadoTaxonomia:
        res = ResultadoTaxonomia()
        zonas = (
            ("titulo", doc.titulo_limpio),
            ("tags", doc.tags_limpio),
            ("cuerpo", doc.cuerpo_limpio),
        )

        # Deduplicacion por skill: nos quedamos con la mejor zona donde aparecio cada skill
        mejores_matches: dict[str, MatchTaxonomia] = {}

        for definicion, patron in self._reglas_compiladas:
            for zona, texto_zona in zonas:
                if not texto_zona:
                    continue
                for m in patron.finditer(texto_zona):
                    negado = self._esta_negado(texto_zona, m.start())
                    mult = PESO_ZONA[zona]
                    peso_eff = 0.0 if negado else (definicion.peso * mult)
                    cand = MatchTaxonomia(
                        clave=definicion.clave,
                        familia=definicion.familia,
                        es_tech=definicion.es_tech,
                        peso_base=definicion.peso,
                        peso_efectivo=peso_eff,
                        zona=zona,
                        fragmento=m.group(0),
                        negado=negado,
                    )
                    prev = mejores_matches.get(definicion.clave)
                    if prev is None:
                        mejores_matches[definicion.clave] = cand
                    elif prev.negado and not cand.negado:
                        mejores_matches[definicion.clave] = cand
                    elif (not cand.negado) and abs(cand.peso_efectivo) > abs(prev.peso_efectivo):
                        mejores_matches[definicion.clave] = cand
                    break  # Una ocurrencia por zona es suficiente por definicion

        # Procesar resultados acumulados
        for mt in mejores_matches.values():
            res.matches_detalle.append(mt)
            if mt.negado:
                res.matches_negados.append(f"{mt.clave} ({mt.fragmento})")
                continue

            if mt.es_tech:
                res.score_tech_bruto += mt.peso_efectivo
                res.skills_encontradas.append(mt.clave)
                res.familias_detectadas[mt.familia] = res.familias_detectadas.get(mt.familia, 0.0) + mt.peso_efectivo
                res.senales.append(SenalDetectada(
                    codigo=f"TECH_{mt.clave.upper()}",
                    categoria=CategoriaSenal.TAXONOMIA_TECH,
                    descripcion=f"Skill tecnica '{mt.clave}' ({mt.familia}) en {mt.zona}",
                    peso=mt.peso_efectivo,
                    evidencia=mt.fragmento,
                    zona=mt.zona,
                ))
            else:
                res.score_penalidad_bruto += mt.peso_efectivo  # negativo
                res.no_tech_encontradas.append(mt.clave)
                res.familias_no_tech[mt.familia] = res.familias_no_tech.get(mt.familia, 0.0) + mt.peso_efectivo
                res.senales.append(SenalDetectada(
                    codigo=f"NOTECH_{mt.clave.upper()}",
                    categoria=CategoriaSenal.TAXONOMIA_NO_TECH,
                    descripcion=f"Oficio/ruido no-tech '{mt.clave}' en {mt.zona}",
                    peso=mt.peso_efectivo,
                    evidencia=mt.fragmento,
                    zona=mt.zona,
                ))

        # Bonus por combos de sinergia (cuando se combinan 2 familias complementarias)
        fams_activas = set(res.familias_detectadas.keys())
        for regla in REGLAS_SINERGIA:
            if all(f in fams_activas for f in regla.familias_requeridas):
                res.score_sinergias += regla.bonus
                res.combos_activados.append(regla.nombre)
                res.senales.append(SenalDetectada(
                    codigo=regla.nombre,
                    categoria=CategoriaSenal.SINERGIA_COMBO,
                    descripcion=regla.descripcion,
                    peso=regla.bonus,
                    evidencia="+".join(regla.familias_requeridas),
                    zona="combinado",
                ))

        # Bonus por nicho/subreddit especializado (si no hay penalidad fuerte)
        sub_low = (sub_o_categoria or "").lower().replace("r/", "").strip()
        bonus_sub = SUBS_BONUS_DEV.get(sub_low, 0.0)
        if bonus_sub > 0 and res.score_penalidad_bruto > -4.0:
            res.score_tech_bruto += bonus_sub
            res.senales.append(SenalDetectada(
                codigo="NICHO_DEV_BONUS",
                categoria=CategoriaSenal.TAXONOMIA_TECH,
                descripcion=f"Nicho especializado tech ({sub_low})",
                peso=bonus_sub,
                evidencia=sub_low,
                zona="metadata",
            ))

        # Whitelist personalizada del usuario (palabras VIP que siempre dan boost)
        if whitelist_usuario:
            low_busq = doc.texto_busqueda
            for w in whitelist_usuario:
                wl = str(w).strip().lower()
                if wl and wl in low_busq:
                    res.score_tech_bruto += 4.5
                    res.skills_encontradas.append(f"vip:{wl}")
                    res.senales.append(SenalDetectada(
                        codigo="WHITELIST_VIP",
                        categoria=CategoriaSenal.TAXONOMIA_TECH,
                        descripcion=f"Palabra VIP del usuario detectada: {wl}",
                        peso=4.5,
                        evidencia=wl,
                        zona="cuerpo",
                    ))

        # Puntaje neto y normalizacion sigmoide suave a escala 0..100
        res.score_neto = res.score_tech_bruto + res.score_sinergias + res.score_penalidad_bruto

        if res.score_neto <= 0:
            res.score_normalizado_0_100 = max(0.0, 20.0 + res.score_neto * 2.5)
        else:
            # Curva logaritmica que diferencia bien entre 3 pts (~45), 8 pts (~72) y 18+ pts (~95)
            res.score_normalizado_0_100 = min(100.0, 22.0 + 78.0 * (1.0 - math.exp(-res.score_neto / 10.5)))

        # Familia principal
        if res.familias_detectadas:
            res.familia_principal = max(res.familias_detectadas.items(), key=lambda kv: kv[1])[0]
        elif res.familias_no_tech:
            res.familia_principal = "no_tech:" + min(res.familias_no_tech.items(), key=lambda kv: kv[1])[0]

        # Decision tecnica estricta:
        # 1) Debe tener puntaje neto >= 3.0 y al menos una señal tech real
        # 2) Si hay penalidad no-tech severa (<= -6.0) necesita dominio tech aplastante (>= 10 bruto)
        if res.score_penalidad_bruto <= -6.0 and res.score_tech_bruto < 10.0:
            res.es_tech = False
        else:
            res.es_tech = (res.score_neto >= 3.0) and (len(res.skills_encontradas) >= 1)

        res.skills_encontradas = sorted(set(res.skills_encontradas))
        res.no_tech_encontradas = sorted(set(res.no_tech_encontradas))
        return res


_TAXONOMIA_SINGLETON = MotorTaxonomia()


def evaluar_taxonomia(
    doc: DocumentoNormalizado,
    sub_o_categoria: str = "",
    whitelist_usuario: list[str] | None = None,
) -> ResultadoTaxonomia:
    return _TAXONOMIA_SINGLETON.evaluar(doc, sub_o_categoria=sub_o_categoria, whitelist_usuario=whitelist_usuario)