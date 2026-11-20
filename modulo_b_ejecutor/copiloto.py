import os
import re
import ast
import sys
import subprocess
from datetime import datetime
from urllib.parse import quote, urlparse, parse_qs
from bs4 import BeautifulSoup

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core_ia import (
    C,
    SESSION,
    safe_float,
    log_evento,
    cargar_config,
    preparar_db,
    verificar_confianza_reddit,
    generar_texto_ia,
    extraer_etiqueta,
    copiar_al_portapapeles,
    validar_y_reparar_python,
    analizar_dependencias,
)
from modulo_a_radar_whop.conectores.base import BROWSER_HEADERS
from modulo_a_radar_whop.conectores.filtros import limpiar_html
from modulo_a_radar_whop.conectores.reddit import obtener_headers_reddit_oauth

PLAYBOOKS_PLATAFORMA = {
    "Reddit": (
        "Plataforma: Reddit. Tono directo de desarrollador independiente (nada corporativo). "
        "Demuestra diagnostico tecnico en la primera frase, propone entrega rapida y, si es r/slavelabour o r/DoneDirtCheap, recuerda comentar $bid antes del DM."
    ),
    "Freelancer": (
        "Plataforma: Freelancer.com (caja de pujas/bids). REGLA CRITICA: el cliente solo ve las primeras 2 lineas en la vista previa, "
        "asi que arranca con un gancho tecnico exacto mencionando su problema concreto. Incluye plan en 3 pasos cortos, plazo estimado y propuesta de milestone."
    ),
    "GitHub": (
        "Plataforma: GitHub Issue / Bounty. CERO tono de vendedor. Escribe un comentario tecnico de ingenieria: "
        "diagnostico del bug/feature, enfoque de implementacion en 3 puntos, archivos/modulos a tocar y pregunta directa para reclamar/asignar el issue (/attempt o confirmacion del maintainer)."
    ),
    "HackerNews": (
        "Plataforma: Hacker News. Tono peer-to-peer entre ingenieros y founders: ultra conciso, alta senal tecnica, "
        "menciona experiencia concreta en Python/scraping/automatizacion, link a GitHub y disponibilidad inmediata para una llamada breve o prueba paga."
    ),
    "Remoto": (
        "Plataforma: Bolsa de trabajo remoto / contrato tech. Redacta una nota de aplicacion (cover note) concisa y ejecutiva: "
        "conecta tu stack (Python, APIs, automatizacion, bots, scraping) con el rol, destaca comunicacion asincrona y cierra proponiendo una llamada corta o tarea de prueba."
    ),
}

def detectar_plataforma_url(url: str) -> str:
    low = (url or "").lower()
    if "reddit.com" in low or "redd.it" in low:
        return "Reddit"
    if "freelancer.com" in low:
        return "Freelancer"
    if "github.com" in low:
        return "GitHub"
    if "news.ycombinator.com" in low:
        return "HackerNews"
    if "remoteok.com" in low:
        return "RemoteOK"
    if "weworkremotely.com" in low:
        return "WWR"
    if "remotive.com" in low:
        return "Remotive"
    if "jobicy.com" in low:
        return "Jobicy"
    if "himalayas.app" in low:
        return "Himalayas"
    if "workingnomads.com" in low:
        return "WorkingNomads"
    if "arbeitnow.com" in low:
        return "Arbeitnow"
    return "Web"

def detectar_plataforma_texto(oferta: str) -> str:
    cab = (oferta or "")[:450].lower()
    if "freelancer.com" in cab or "plataforma: freelancer" in cab:
        return "Freelancer"
    if "github.com" in cab or "github bounty" in cab or "plataforma: github" in cab:
        return "GitHub"
    if "news.ycombinator.com" in cab or "hackernews" in cab or "[hn]" in cab:
        return "HackerNews"
    if "reddit.com" in cab or "fuente: r/" in cab or "plataforma: reddit" in cab:
        return "Reddit"
    for p in ("remoteok", "weworkremotely", "remotive", "jobicy", "himalayas", "workingnomads", "arbeitnow"):
        if p in cab:
            return "Remoto"
    return "Reddit"

def _playbook_para(plataforma: str) -> str:
    if plataforma in PLAYBOOKS_PLATAFORMA:
        return PLAYBOOKS_PLATAFORMA[plataforma]
    return PLAYBOOKS_PLATAFORMA["Remoto"]

def _descargar_reddit_con_rescate(url: str) -> tuple[str | None, str, str]:
    objetivo = url.strip()
    try:
        if "/s/" in objetivo or "redd.it" in objetivo or "old.reddit.com" in objetivo or "m.reddit.com" in objetivo:
            r_res = SESSION.get(objetivo, headers=BROWSER_HEADERS, allow_redirects=True, timeout=10)
            if r_res.url:
                objetivo = r_res.url

        limpia = objetivo.split("?")[0].rstrip("/")
        # Intento 1: OAuth2 si el usuario tiene llaves
        h_oa = obtener_headers_reddit_oauth()
        if h_oa:
            path_part = urlparse(limpia).path.rstrip("/")
            r_oa = SESSION.get(f"https://oauth.reddit.com{path_part}.json?raw_json=1", headers=h_oa, timeout=10)
            if r_oa.status_code == 200:
                payload = r_oa.json()
                if isinstance(payload, list) and payload:
                    ch = payload[0].get("data", {}).get("children", [])
                    if ch:
                        d = ch[0].get("data", {})
                        return f"Plataforma: Reddit\nFuente: {d.get('subreddit_name_prefixed', 'Reddit')}\nAutor: u/{d.get('author', '')}\nTitulo: {d.get('title', '')}\n\n{d.get('selftext', '')}".strip(), d.get("author", ""), d.get("title", "")

        # Intento 2: JSON directo con Browser UA
        json_url = limpia if limpia.endswith(".json") else f"{limpia}.json?raw_json=1"
        r = SESSION.get(json_url, headers=BROWSER_HEADERS, timeout=10)
        if r.status_code == 200:
            payload = r.json()
            if isinstance(payload, list) and payload:
                ch = payload[0].get("data", {}).get("children", [])
                if ch:
                    d = ch[0].get("data", {})
                    return f"Plataforma: Reddit\nFuente: {d.get('subreddit_name_prefixed', 'Reddit')}\nAutor: u/{d.get('author', '')}\nTitulo: {d.get('title', '')}\n\n{d.get('selftext', '')}".strip(), d.get("author", ""), d.get("title", "")

        # Intento 3: Rescate Anti-403 via Arctic Shift por ID del post
        m_id = re.search(r"/comments/([a-z0-9]+)", limpia, re.IGNORECASE)
        if m_id:
            post_id = m_id.group(1)
            r_as = SESSION.get(
                "https://arctic-shift.photon-reddit.com/api/posts/ids",
                params={"ids": post_id},
                headers={"User-Agent": BROWSER_HEADERS["User-Agent"], "Accept": "application/json"},
                timeout=10,
            )
            if r_as.status_code == 200:
                data_list = r_as.json().get("data") or []
                if isinstance(data_list, list) and data_list:
                    d = data_list[0]
                    sub = d.get("subreddit", "Reddit")
                    autor = d.get("author", "")
                    titulo = d.get("title", "")
                    cuerpo = d.get("selftext", "")
                    return f"Plataforma: Reddit\nFuente: r/{sub}\nAutor: u/{autor}\nTitulo: {titulo}\n\n{cuerpo}".strip(), autor, titulo
    except Exception as e:
        log_evento(f"Copiloto Reddit aviso: {e}")
    return None, "", ""

def _descargar_github_issue(url: str) -> tuple[str | None, str, str]:
    m = re.search(r"github\.com/([^/]+)/([^/]+)/issues/(\d+)", url, re.IGNORECASE)
    if not m:
        return None, "", ""
    owner, repo, num = m.group(1), m.group(2), m.group(3)
    headers = {"User-Agent": "ZeroTouchOmni/13.0", "Accept": "application/vnd.github+json"}
    if os.getenv("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.getenv('GITHUB_TOKEN')}"
    try:
        r = SESSION.get(f"https://api.github.com/repos/{owner}/{repo}/issues/{num}", headers=headers, timeout=10)
        if r.status_code == 200:
            d = r.json()
            titulo = (d.get("title") or "").strip()
            autor = (d.get("user") or {}).get("login", owner)
            labels = ", ".join(str(lb.get("name", "")) for lb in (d.get("labels") or []))
            cuerpo = (d.get("body") or "")[:2400]
            txt = f"Plataforma: GitHub\nRepo: {owner}/{repo} (Issue #{num})\nLabels: {labels}\nAutor: {autor}\nTitulo: {titulo}\n\n{cuerpo}".strip()
            return txt, autor, titulo
    except Exception as e:
        log_evento(f"Copiloto GitHub aviso: {e}")
    return None, "", ""

def _descargar_hackernews(url: str) -> tuple[str | None, str, str]:
    qs = parse_qs(urlparse(url).query)
    item_id = (qs.get("id") or [""])[0]
    if not item_id.isdigit():
        return None, "", ""
    try:
        r = SESSION.get(f"https://hn.algolia.com/api/v1/items/{item_id}", timeout=10)
        if r.status_code == 200:
            d = r.json()
            autor = d.get("author") or "hackernews"
            titulo = d.get("title") or f"HN Item #{item_id}"
            texto = limpiar_html(d.get("text") or "", 2200)
            txt = f"Plataforma: HackerNews\nAutor: {autor}\nTitulo: {titulo}\nLink: {url}\n\n{texto}".strip()
            return txt, autor, titulo
    except Exception as e:
        log_evento(f"Copiloto HN aviso: {e}")
    return None, "", ""

def _descargar_freelancer(url: str) -> tuple[str | None, str, str]:
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    params: dict = {"full_description": "true", "job_details": "true", "compact": "true"}
    m_num = re.search(r"/projects/(\d+)(?:/|$)", parsed.path)
    if m_num:
        params["projects[]"] = m_num.group(1)
    elif path.startswith("projects/"):
        seo = path[len("projects/"):].strip("/")
        if seo:
            params["seo_urls[]"] = seo
    try:
        r = SESSION.get(
            "https://www.freelancer.com/api/projects/0.1/projects/",
            params=params,
            headers=BROWSER_HEADERS,
            timeout=10,
        )
        if r.status_code == 200:
            projs = r.json().get("result", {}).get("projects", [])
            if projs:
                p = projs[0]
                titulo = (p.get("title") or "").strip()
                desc = (p.get("description") or p.get("preview_description") or "")[:2400]
                jobs = ", ".join(str(j.get("name", "")) for j in (p.get("jobs") or []) if isinstance(j, dict))
                bud = p.get("budget") or {}
                cur = p.get("currency") or {}
                rate = safe_float(cur.get("exchange_rate"), 1.0) or 1.0
                bmin = int(safe_float(bud.get("minimum"), 0) * rate)
                bmax = int(safe_float(bud.get("maximum"), 0) * rate)
                pres = f"${bmin}-${bmax} USD" if bmax > 0 else "Por definir"
                bids = (p.get("bid_stats") or {}).get("bid_count", 0)
                txt = f"Plataforma: Freelancer\nFuente: Freelancer.com\nPresupuesto: {pres} | Pujas actuales: {bids}\nSkills: {jobs}\nTitulo: {titulo}\n\n{desc}".strip()
                return txt, "freelancer_client", titulo
    except Exception as e:
        log_evento(f"Copiloto Freelancer API aviso: {e}")
    return None, "", ""

def _descargar_web_generica(url: str, plataforma: str) -> tuple[str | None, str, str]:
    try:
        r = SESSION.get(url, headers=BROWSER_HEADERS, timeout=12)
        if r.status_code != 200:
            return None, "", ""
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav"]):
            tag.decompose()
        h1 = soup.find("h1")
        titulo = (h1.get_text(" ", strip=True) if h1 else (soup.title.get_text(" ", strip=True) if soup.title else plataforma))[:180]
        main_el = soup.find("main") or soup.find("article") or soup.body or soup
        cuerpo = re.sub(r"\s+", " ", main_el.get_text(" ", strip=True))[:2400]
        if len(cuerpo) < 40:
            return None, "", ""
        txt = f"Plataforma: {plataforma}\nLink: {url}\nTitulo: {titulo}\n\n{cuerpo}".strip()
        return txt, plataforma, titulo
    except Exception as e:
        log_evento(f"Copiloto Web aviso ({plataforma}): {e}")
    return None, "", ""

def descargar_oferta_universal(url: str) -> tuple[str | None, str, str, str]:
    """Extrae el contenido de cualquier link soportado y devuelve (texto, autor, titulo, plataforma)."""
    plat = detectar_plataforma_url(url)
    oferta: str | None = None
    autor = ""
    titulo = ""

    if plat == "Reddit":
        oferta, autor, titulo = _descargar_reddit_con_rescate(url)
    elif plat == "GitHub":
        oferta, autor, titulo = _descargar_github_issue(url)
    elif plat == "HackerNews":
        oferta, autor, titulo = _descargar_hackernews(url)
    elif plat == "Freelancer":
        oferta, autor, titulo = _descargar_freelancer(url)

    if not oferta:
        oferta, autor, titulo = _descargar_web_generica(url, plat)

    return oferta, autor, titulo, plat

def descargar_post_reddit(url: str) -> tuple[str | None, str, str]:
    """Compatibilidad con v12.x: ahora tambien resuelve cualquier link universal."""
    oferta, autor, titulo, _ = descargar_oferta_universal(url)
    return oferta, autor, titulo

def cargar_desde_crm_completo(lead_id: int) -> tuple[str | None, str, str, str, str]:
    conn = preparar_db()
    try:
        row = conn.execute(
            "SELECT fuente, plataforma, tipo_trabajo, autor, titulo, presupuesto, link FROM leads WHERE id = ?",
            (lead_id,),
        ).fetchone()
        if not row:
            return None, "", "", "", ""
        fuente, plataforma, tipo_trabajo, autor, titulo, pres, link = row
        plat = plataforma or detectar_plataforma_url(link or "") or fuente or "Reddit"
        tipo = tipo_trabajo or "freelance"
        if link and link.startswith("http"):
            oferta, a_ext, t_ext, p_ext = descargar_oferta_universal(link)
            if oferta:
                return oferta, (a_ext or autor or ""), (t_ext or titulo or ""), (p_ext or plat), tipo
        respaldo = f"Plataforma: {plat}\nTipo: {tipo}\nFuente: {fuente}\nPresupuesto: {pres}\nTitulo: {titulo}\nLink: {link}"
        return respaldo, (autor or ""), (titulo or ""), plat, tipo
    finally:
        conn.close()

def cargar_desde_crm(lead_id: int) -> tuple[str | None, str, str]:
    """Compatibilidad 3-tupla con dashboard_web.py y telegram_bot_control.py."""
    oferta, autor, titulo, _, _ = cargar_desde_crm_completo(lead_id)
    return oferta, autor, titulo

def crear_slug(texto: str) -> str:
    palabras = re.sub(r"[^a-zA-Z0-9\s]", "", (texto or "").lower()).split()[:5]
    return "_".join(palabras) or "proyecto"

def resolver_ruta_script(ruta_script: str = "") -> str:
    ruta = (ruta_script or "").strip() or os.path.join("modulo_b_ejecutor", "borrador_cliente.py")
    if not os.path.isabs(ruta):
        ruta = os.path.join(ROOT_DIR, ruta)
    return ruta

def leer_borrador_actual(ruta_script: str = "") -> dict:
    ruta = resolver_ruta_script(ruta_script)
    if not os.path.isfile(ruta):
        return {"error": f"No existe todavia: {ruta}", "codigo": "", "ast_valido": False, "todos_pip": [], "faltantes_pip": []}
    with open(ruta, "r", encoding="utf-8") as f:
        codigo = f.read()
    try:
        ast.parse(codigo)
        valido = True
    except SyntaxError:
        valido = False
    todos_pip, faltantes_pip = analizar_dependencias(codigo)
    return {
        "ruta": os.path.relpath(ruta, ROOT_DIR).replace("\\", "/"),
        "codigo": codigo,
        "lineas": len(codigo.splitlines()),
        "ast_valido": valido,
        "todos_pip": todos_pip,
        "faltantes_pip": faltantes_pip,
    }

def refinar_borrador_ia(instruccion: str, ruta_script: str = "") -> dict:
    info = leer_borrador_actual(ruta_script)
    if info.get("error"):
        return info
    if not (instruccion or "").strip():
        return {"error": "Escribe que cambio o mejora quieres hacerle al codigo."}

    prompt = (
        "Eres un ingeniero senior de Python 3.12.\n"
        "Aplica la instruccion solicitada al siguiente script manteniendo codigo limpio, modular, sin errores de sintaxis y listo para ejecutar.\n"
        f"INSTRUCCION DEL DEV:\n{instruccion}\n\n"
        "Responde UNICAMENTE usando estas 2 etiquetas XML:\n"
        "<RESUMEN_CAMBIOS>Resumen de 2 lineas en espanol explicando que mejoraste.</RESUMEN_CAMBIOS>\n"
        "<CODIGO_NUEVO>Codigo completo actualizado en Python 3.12.</CODIGO_NUEVO>\n\n"
        f"CODIGO ACTUAL:\n{info['codigo']}"
    )
    resp = generar_texto_ia(prompt, temperatura=0.2, json_mode=False, timeout=34)
    if not resp:
        return {"error": "Gemini no respondio al refinar el codigo."}

    resumen = extraer_etiqueta(resp, "RESUMEN_CAMBIOS") or "Codigo actualizado."
    nuevo_raw = extraer_etiqueta(resp, "CODIGO_NUEVO") or resp
    codigo_ok, valido = validar_y_reparar_python(nuevo_raw, descripcion=instruccion)
    if not codigo_ok:
        return {"error": "No se pudo extraer codigo valido."}

    ruta_abs = resolver_ruta_script(ruta_script)
    with open(ruta_abs, "w", encoding="utf-8") as f:
        f.write(codigo_ok)

    todos_pip, faltantes_pip = analizar_dependencias(codigo_ok)
    log_evento(f"Codigo refinado ({os.path.basename(ruta_abs)} | {'AST OK' if valido else 'Revisar'})")
    return {
        "ruta": info["ruta"],
        "resumen": resumen,
        "codigo": codigo_ok,
        "lineas": len(codigo_ok.splitlines()),
        "ast_valido": valido,
        "todos_pip": todos_pip,
        "faltantes_pip": faltantes_pip,
    }

def analizar_oferta_completo(
    oferta: str,
    autor: str = "",
    titulo: str = "",
    guardar_archivos: bool = True,
    plataforma: str = "",
    tipo_trabajo: str = "",
) -> dict | None:
    cfg = cargar_config()
    plat = plataforma or detectar_plataforma_texto(oferta)
    playbook = _playbook_para(plat)
    confianza = verificar_confianza_reddit(autor) if (plat == "Reddit" and autor) else f"🌐 Plataforma: {plat}"
    tarifa = cfg.get("tarifa_hora_usd", 25)

    prompt = (
        "Eres un desarrollador senior y cerrador freelance de Python/Automatizacion.\n"
        f"PLAYBOOK DE PLATAFORMA: {playbook}\n"
        f"Tarifa base de referencia del dev: ${tarifa} USD/hora.\n"
        f"Metodos de pago: {cfg.get('metodos_pago')}\n"
        f"GitHub: {cfg.get('github_url')}\n"
        "Analiza esta oferta y responde UNICAMENTE usando estas 11 etiquetas XML (sin texto fuera):\n\n"
        "<ESTRATEGIA_PLATAFORMA>\n"
        f"Consejo tactico exacto (2 lineas en espanol) sobre como destacar y cerrar esta oferta especificamente en {plat}.\n"
        "</ESTRATEGIA_PLATAFORMA>\n\n"
        "<DIAGNOSTICO>\n"
        "Que pide el cliente, stack exacto y el detalle tecnico clave para demostrar dominio (2-3 lineas en espanol).\n"
        "</DIAGNOSTICO>\n\n"
        "<RED_FLAGS>\n"
        "Senales de alerta (presupuesto bajo, alcance vago, bloqueos anti-bot o riesgo de impago) o escribe 'Ninguna alerta critica — buena oportunidad' (1-2 lineas en espanol).\n"
        "</RED_FLAGS>\n\n"
        "<PRECIOS>\n"
        "3 opciones en USD en 3 lineas (o rango mensual/hora si es contrato remoto): Basico, Estandar y Premium.\n"
        "</PRECIOS>\n\n"
        "<PITCH_A>\n"
        f"Pitch estilo A en ingles natural (50-75 palabras) siguiendo al pie de la letra el PLAYBOOK de {plat}. Directo, tecnico y sin sonar a IA.\n"
        "</PITCH_A>\n\n"
        "<PITCH_B>\n"
        f"Pitch estilo B alternativo en ingles (50-75 palabras) mas consultivo y enfocado en impacto de negocio para {plat}.\n"
        "</PITCH_B>\n\n"
        "<PREGUNTAS_CIERRE>\n"
        "2 preguntas tecnicas cortas en ingles para cerrar alcance y precio cuando responda.\n"
        "</PREGUNTAS_CIERRE>\n\n"
        "<FOLLOWUP>\n"
        "Mensaje corto de seguimiento en ingles (25-35 palabras) para enviar 24-48h despues si no hay respuesta.\n"
        "</FOLLOWUP>\n\n"
        "<MENSAJE_COBRO>\n"
        f"Mensaje profesional en ingles (35-50 palabras) para enviar con prueba de avance pidiendo hito/50% o pago final via {cfg.get('metodos_pago')}.\n"
        "</MENSAJE_COBRO>\n\n"
        "<MICRO_CONTRATO>\n"
        "Acuerdo de alcance (Scope of Work) de 4 vinetas cortas en ingles: entregables exactos, 1 ronda de ajustes incluida, extras se cotizan aparte, entrega tras confirmar pago.\n"
        "</MICRO_CONTRATO>\n\n"
        "<CODIGO>\n"
        "Script base completo, modular y limpio en Python 3.12 listo como punto de partida funcional para resolver este proyecto, con manejo de errores y exportacion ordenada.\n"
        "</CODIGO>\n\n"
        f"OFERTA:\n{oferta[:2600]}"
    )

    texto = generar_texto_ia(prompt, temperatura=0.25, json_mode=False, timeout=38)
    if not texto:
        return None

    estrategia = extraer_etiqueta(texto, "ESTRATEGIA_PLATAFORMA")
    diag = extraer_etiqueta(texto, "DIAGNOSTICO")
    red_flags = extraer_etiqueta(texto, "RED_FLAGS")
    precios = extraer_etiqueta(texto, "PRECIOS")
    pitch_a = extraer_etiqueta(texto, "PITCH_A")
    pitch_b = extraer_etiqueta(texto, "PITCH_B")
    preguntas = extraer_etiqueta(texto, "PREGUNTAS_CIERRE")
    followup = extraer_etiqueta(texto, "FOLLOWUP")
    cobro = extraer_etiqueta(texto, "MENSAJE_COBRO")
    contrato = extraer_etiqueta(texto, "MICRO_CONTRATO")
    codigo_raw = extraer_etiqueta(texto, "CODIGO")

    codigo, valido = validar_y_reparar_python(codigo_raw, descripcion=diag)
    todos_pip, faltantes_pip = analizar_dependencias(codigo) if codigo else ([], [])

    dm_url = ""
    if plat == "Reddit" and autor and autor.lower() not in ("[deleted]", "automoderator", "github", "hackernews", "freelancer_client"):
        dm_url = f"https://www.reddit.com/message/compose/?to={quote(autor)}&subject={quote('Re: ' + (titulo or 'Project')[:65])}&message={quote(pitch_a[:380])}"

    ruta_borrador = ""
    carpeta_proj = ""
    if guardar_archivos and codigo:
        ruta_borrador = os.path.join(ROOT_DIR, "modulo_b_ejecutor", "borrador_cliente.py")
        with open(ruta_borrador, "w", encoding="utf-8") as f:
            f.write(codigo)

        carpeta_proj = os.path.join(
            ROOT_DIR,
            "proyectos",
            f"{datetime.now().strftime('%Y%m%d_%H%M')}_{plat.lower()}_{crear_slug(titulo or oferta.splitlines()[0])}",
        )
        os.makedirs(carpeta_proj, exist_ok=True)
        with open(os.path.join(carpeta_proj, "script.py"), "w", encoding="utf-8") as f:
            f.write(codigo)
        with open(os.path.join(carpeta_proj, "kit_cierre_omni.txt"), "w", encoding="utf-8") as f:
            f.write(
                f"PLATAFORMA: {plat} ({tipo_trabajo or 'auto'})\nCONFIANZA: {confianza}\n"
                f"ESTRATEGIA: {estrategia}\nRED FLAGS: {red_flags}\n\n"
                f"DIAGNOSTICO:\n{diag}\n\nPRECIOS:\n{precios}\n\n"
                f"PITCH A:\n{pitch_a}\n\nPITCH B:\n{pitch_b}\n\n"
                f"PREGUNTAS:\n{preguntas}\n\nMICRO-CONTRATO:\n{contrato}\n\n"
                f"FOLLOWUP:\n{followup}\n\nCOBRO:\n{cobro}\n"
            )
        log_evento(f"Copiloto OMNI ({plat}) genero kit + borrador ({'AST OK' if valido else 'Revisar'})")

    return {
        "plataforma": plat,
        "estrategia": estrategia,
        "confianza": confianza,
        "red_flags": red_flags,
        "diagnostico": diag,
        "precios": precios,
        "pitch_a": pitch_a,
        "pitch_b": pitch_b,
        "preguntas": preguntas,
        "followup": followup,
        "cobro": cobro,
        "micro_contrato": contrato,
        "codigo": codigo,
        "ast_valido": valido,
        "todos_pip": todos_pip,
        "faltantes_pip": faltantes_pip,
        "dm_url": dm_url,
        "ruta_borrador": ruta_borrador,
        "carpeta_proj": carpeta_proj,
    }

def main() -> None:
    print(f"\n{C.BOLD}{C.CYAN}=== MODULO B: COPILOTO UNIVERSAL OMNI v13.0 ==={C.RESET}")
    print("Opcion 1: Pega CUALQUIER LINK (Reddit, Freelancer, GitHub, HN, RemoteOK, WWR...) y Enter.")
    print("Opcion 2: Escribe #<ID> de tu CRM (ej. #4) y Enter.")
    print("Opcion 3: Escribe REFINAR para mejorar tu borrador_cliente.py actual.")
    print("Opcion 4: Pega el texto manual, escribe FIN en linea nueva y Enter.\n")

    primera = input(f"{C.GREEN}> {C.RESET}").strip()
    if not primera:
        print("[!] No ingresaste nada.")
        return

    if primera.upper() == "REFINAR":
        instr = input("Que mejora o cambio le metemos a borrador_cliente.py?: ").strip()
        r = refinar_borrador_ia(instr)
        if r.get("error"):
            print(f"{C.RED}[!] {r['error']}{C.RESET}")
        else:
            print(f"\n{C.GREEN}[+] {r['resumen']} ({r['lineas']} lineas | {'AST OK' if r['ast_valido'] else 'Revisar'}){C.RESET}\n")
        return

    autor = ""
    titulo = ""
    plat = ""
    tipo = ""
    if primera.startswith("#") and primera[1:].isdigit():
        print(f"{C.DIM}[*] Cargando lead {primera} desde tu CRM...{C.RESET}", flush=True)
        oferta, autor, titulo, plat, tipo = cargar_desde_crm_completo(int(primera[1:]))
        if not oferta:
            print(f"{C.RED}[!] No existe el lead {primera} en tu CRM.{C.RESET}")
            return
    elif primera.startswith("http"):
        plat_det = detectar_plataforma_url(primera)
        print(f"{C.DIM}[*] Extrayendo oferta desde {plat_det}...{C.RESET}", flush=True)
        oferta, autor, titulo, plat = descargar_oferta_universal(primera)
        if not oferta:
            print("[!] No pude leer ese link automatico. Pega el texto manual mejor.")
            return
        print(f"{C.GREEN}[+] Oferta de {plat} descargada ({len(oferta)} chars).{C.RESET}\n")
    else:
        lineas = [primera]
        while True:
            try:
                linea = input()
            except EOFError:
                break
            if linea.strip().upper() == "FIN":
                break
            lineas.append(linea)
        oferta = "\n".join(lineas).strip()

    print(f"{C.CYAN}[*] Ejecutando Copiloto OMNI ({plat or 'Auto'})...{C.RESET}", flush=True)
    res = analizar_oferta_completo(oferta, autor=autor, titulo=titulo, guardar_archivos=True, plataforma=plat, tipo_trabajo=tipo)
    if not res:
        print(f"{C.RED}[!] No se pudo generar respuesta en este momento.{C.RESET}")
        return

    copiado = copiar_al_portapapeles(res["pitch_a"])

    print("\n" + "=" * 72)
    print(f"{C.MAGENTA}PLATAFORMA:{C.RESET} {res['plataforma']} | {res['confianza']}")
    if res.get("estrategia"):
        print(f"{C.CYAN}ESTRATEGIA:{C.RESET} {res['estrategia']}")
    if res.get("red_flags"):
        print(f"{C.YELLOW}RED FLAGS :{C.RESET} {res['red_flags']}\n")
    print(f"{C.BOLD}DIAGNOSTICO TECNICO:{C.RESET}\n{res['diagnostico']}\n")
    print(f"{C.BOLD}{C.GREEN}ESCALERA DE PRECIOS:{C.RESET}\n{res['precios']}\n")
    print("-" * 72)
    print(f"{C.BOLD}{C.CYAN}PITCH A — ADAPTADO A {res['plataforma'].upper()}:{C.RESET}\n{res['pitch_a']}\n")
    if copiado:
        print(f"{C.GREEN}[+] Pitch A copiado automaticamente al portapapeles (Ctrl+V)!{C.RESET}\n")
    print(f"{C.BOLD}{C.BLUE}PITCH B — CONSULTIVO:{C.RESET}\n{res['pitch_b']}\n")
    if res["dm_url"]:
        print(f"{C.MAGENTA}DM DIRECTO PRE-LLENADO:\n{res['dm_url']}{C.RESET}\n")
    print("-" * 72)
    print(f"{C.BOLD}MICRO-CONTRATO:{C.RESET}\n{res['micro_contrato']}\n")
    print(f"{C.BOLD}MENSAJE DE COBRO:{C.RESET}\n{res['cobro']}")
    print("=" * 72)

    if res["ruta_borrador"]:
        estado_ast = f"{C.GREEN}AST VALIDO{C.RESET}" if res["ast_valido"] else f"{C.YELLOW}REVISAR SINTAXIS{C.RESET}"
        print(f"\nScript base [{estado_ast}] -> {res['ruta_borrador']}")
        print(f"{C.DIM}Respaldo guardado en      -> {res['carpeta_proj']}{C.RESET}")
        if res["faltantes_pip"]:
            pkgs = " ".join(res["faltantes_pip"])
            print(f"{C.YELLOW}[!] Paquetes faltantes en tu PC: {pkgs}{C.RESET}")
            if input("Quieres instalarlos automaticamente ahora? [s/N]: ").strip().lower() == "s":
                subprocess.run([sys.executable, "-m", "pip", "install", *res["faltantes_pip"]])
        elif res["todos_pip"]:
            print(f"{C.GREEN}[+] Librerias ({', '.join(res['todos_pip'])}) ya instaladas!{C.RESET}")
        print()

if __name__ == "__main__":
    main()