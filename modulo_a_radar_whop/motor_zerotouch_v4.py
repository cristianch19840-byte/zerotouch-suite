import os
import re
import sys
import json
import time
import sqlite3
import requests
from bs4 import BeautifulSoup

if os.path.exists(".env"):
    with open(".env", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

GEMINI_KEY = os.getenv("GEMINI_API_KEY_FREE")
TG_TOKEN = os.getenv("TELEGRAM_TOKEN")
TG_CHANNEL_ID = os.getenv("TELEGRAM_CHAT_ID")

WEB_HEADERS = {
    "User-Agent": "ZeroTouchRadar/5.2 (+https://github.com)",
    "Accept": "application/json,application/xml,text/xml;q=0.9,*/*;q=0.8"
}

REGEX_DESCARTAR = re.compile(r"(\[|\()\s*(for\s*hire\vert{}forhire\vert{}offer)\s*(\]\vert{}\))", re.IGNORECASE)
REGEX_ACEPTAR = re.compile(r"((\[|\()\s*(hiring\vert{}task)\s*(\]\vert{}\))|^hiring\b)", re.IGNORECASE)

def limpiar_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    texto = soup.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", texto)[:1600]

def publicar_telegram(mensaje: str) -> bool:
    if not TG_TOKEN or not TG_CHANNEL_ID:
        print("    [!] Faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID.", flush=True)
        return False
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        r = requests.post(
            url,
            json={"chat_id": TG_CHANNEL_ID, "text": mensaje, "disable_web_page_preview": True},
            timeout=15
        )
        if r.status_code == 200:
            print("    [TG] ✅ ¡Alerta publicada en Telegram!", flush=True)
            return True
        print(f"    [TG] ❌ Error Telegram {r.status_code}: {r.text}", flush=True)
        return False
    except Exception as e:
        print(f"    [TG] ❌ Excepción Telegram: {e}", flush=True)
        return False

def obtener_modelos_activos(headers: dict) -> list:
    prioritarios = ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemma-3-27b-it"]
    try:
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/models", headers=headers, timeout=10)
        if r.status_code == 200:
            candidatos = []
            ignorar = ("2.0", "2.5", "1.5", "embedding", "aqa", "imagen", "veo", "tts", "audio", "robotics", "computer-use", "deep-research")
            for m in r.json().get("models", []):
                nombre = m.get("name", "").replace("models/", "")
                metodos = m.get("supportedGenerationMethods", [])
                if "generateContent" not in metodos or any(bad in nombre.lower() for bad in ignorar):
                    continue
                if ("gemini" in nombre.lower() or "gemma" in nombre.lower()) and "image" not in nombre.lower():
                    candidatos.append(nombre)
            candidatos.sort(reverse=True)
            ordenados = [m for m in prioritarios if m in candidatos]
            for m in candidatos:
                if m not in ordenados:
                    ordenados.append(m)
            if ordenados:
                return ordenados
    except Exception:
        pass
    return prioritarios

def extraer_json_seguro(texto: str):
    match = re.search(r"\{.*\}", texto, re.DOTALL)
    if not match:
        return None
    return json.loads(match.group(0))

def consultar_ia_rest(prompt: str):
    if not GEMINI_KEY:
        print("    [!] Falta GEMINI_API_KEY_FREE.", flush=True)
        return None
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_KEY
    }
    modelos = obtener_modelos_activos(headers)

    for modelo in modelos:
        usa_json_nativo = "gemma" not in modelo.lower()
        gen_config = {"temperature": 0.2}
        if usa_json_nativo:
            gen_config["responseMimeType"] = "application/json"

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": gen_config
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=12)
            if r.status_code == 400 and "responseMimeType" in payload["generationConfig"]:
                payload["generationConfig"].pop("responseMimeType", None)
                r = requests.post(url, headers=headers, json=payload, timeout=12)

            if r.status_code == 200:
                data = r.json()
                texto_resp = data["candidates"][0]["content"]["parts"][0]["text"]
                parsed = extraer_json_seguro(texto_resp)
                if parsed:
                    print(f"    [AI] Respondido por {modelo}", flush=True)
                    return parsed
        except Exception:
            pass

    print("    [!] Ningún modelo respondió a tiempo en este intento.", flush=True)
    return None

def evaluar_y_enviar(fuente: str, titulo: str, texto_limpio: str, link: str) -> bool:
    print(f"  [>] Analizando ({fuente}): {titulo[:58]}...", flush=True)
    regla = (
        "En r/forhire NO ofrezcas trabajo gratis; demuestra diagnóstico técnico inmediato."
        if "forhire" in fuente.lower()
        else "Sé directo y profesional confirmando disponibilidad y entrega rápida."
    )
    prompt = (
        f"Evalúa esta publicación de Reddit ({fuente}) y responde ÚNICAMENTE con un objeto JSON válido.\n"
        f"Título: {titulo}\n"
        f"Contenido: {texto_limpio}\n"
        f"Contexto: {regla}\n"
        f"REGLAS ESTRICTAS DE FILTRADO:\n"
        f"- relevante=true SOLO si alguien busca contratar (Hiring/Task) para un proyecto freelance puntual o tarea técnica corta (web scraping, script Python, bot de Telegram/Discord, automatización, extracción/limpieza de datos, API o arreglo web).\n"
        f"- RECHAZA (relevante=false, score<=4) ofertas donde alguien ofrece sus propios servicios ([For Hire]), puestos presenciales, trabajos sin pago (equity/rev-share) o tareas académicas.\n"
        f"Estructura exacta requerida:\n"
        f'{{"relevante": true, "score": 8, "categoria": "Python", "presupuesto": "$150 USD", "resumen_es": "...", "pitch_en": "..."}}'
    )
    try:
        datos = consultar_ia_rest(prompt)
        if not datos:
            return False

        score = int(datos.get("score", 0))
        print(f"    [=] Relevante: {datos.get('relevante')} | Score: {score}/10", flush=True)
        if datos.get("relevante") and score >= 7:
            accion = (
                "Comentar $bid en el post de Reddit antes de enviar DM"
                if fuente.lower() in ("r/slavelabour", "r/donedirtcheap")
                else "Abrir el post en Reddit y enviar DM directo al autor"
            )
            mensaje = (
                f"⚡ [{datos.get('categoria', 'Tech')}] SCORE: {score}/10\n"
                f"💰 Presupuesto: {datos.get('presupuesto', 'Por definir')}  |  📍 Fuente: {fuente}\n\n"
                f"📌 {titulo}\n"
                f"📝 {datos.get('resumen_es', '')}\n"
                f"⚠️ Protocolo: {accion}\n"
                f"🔗 Reddit: {link}\n\n"
                f"📋 PITCH SUGERIDO:\n{datos.get('pitch_en', '')}"
            )
            publicar_telegram(mensaje)
        return True
    except Exception as e:
        print(f"    [!] Error evaluando oferta: {e}", flush=True)
        return False

def recolectar_ofertas() -> list:
    ofertas = []
    subreddits = ["forhire", "slavelabour", "hiring", "freelance_forhire", "DoneDirtCheap"]

    for sub in subreddits:
        try:
            rss_url = f"https://www.reddit.com/r/{sub}/new/.rss"
            api_url = f"https://api.rss2json.com/v1/api.json?rss_url={rss_url}"
            r = requests.get(api_url, headers=WEB_HEADERS, timeout=15)
            if r.status_code == 200 and r.json().get("status") == "ok":
                cont = 0
                for item in r.json().get("items", [])[:15]:
                    titulo = item.get("title", "")
                    if REGEX_DESCARTAR.search(titulo):
                        continue
                    if sub.lower() in ("forhire", "slavelabour", "freelance_forhire", "donedirtcheap") and not REGEX_ACEPTAR.search(titulo):












@'
import os
import re
import sys
import json
import time
import sqlite3
import requests
from bs4 import BeautifulSoup

if os.path.exists(".env"):
    with open(".env", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

GEMINI_KEY = os.getenv("GEMINI_API_KEY_FREE")
TG_TOKEN = os.getenv("TELEGRAM_TOKEN")
TG_CHANNEL_ID = os.getenv("TELEGRAM_CHAT_ID")

WEB_HEADERS = {
    "User-Agent": "ZeroTouchRadar/5.2 (+https://github.com)",
    "Accept": "application/json,application/xml,text/xml;q=0.9,*/*;q=0.8"
}

REGEX_DESCARTAR = re.compile(r"(\[|\()\s*(for\s*hire|forhire|offer)\s*(\]|\))", re.IGNORECASE)
REGEX_ACEPTAR = re.compile(r"((\[|\()\s*(hiring|task)\s*(\]|\))|^hiring\b)", re.IGNORECASE)

def limpiar_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    texto = soup.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", texto)[:1600]

def publicar_telegram(mensaje: str) -> bool:
    if not TG_TOKEN or not TG_CHANNEL_ID:
        print("    [!] Faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID.", flush=True)
        return False
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        r = requests.post(
            url,
            json={"chat_id": TG_CHANNEL_ID, "text": mensaje, "disable_web_page_preview": True},
            timeout=15
        )
        if r.status_code == 200:
            print("    [TG] ✅ ¡Alerta publicada en Telegram!", flush=True)
            return True
        print(f"    [TG] ❌ Error Telegram {r.status_code}: {r.text}", flush=True)
        return False
    except Exception as e:
        print(f"    [TG] ❌ Excepción Telegram: {e}", flush=True)
        return False

def obtener_modelos_activos(headers: dict) -> list:
    prioritarios = ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemma-3-27b-it"]
    try:
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/models", headers=headers, timeout=10)
        if r.status_code == 200:
            candidatos = []
            ignorar = ("2.0", "2.5", "1.5", "embedding", "aqa", "imagen", "veo", "tts", "audio", "robotics", "computer-use", "deep-research")
            for m in r.json().get("models", []):
                nombre = m.get("name", "").replace("models/", "")
                metodos = m.get("supportedGenerationMethods", [])
                if "generateContent" not in metodos or any(bad in nombre.lower() for bad in ignorar):
                    continue
                if ("gemini" in nombre.lower() or "gemma" in nombre.lower()) and "image" not in nombre.lower():
                    candidatos.append(nombre)
            candidatos.sort(reverse=True)
            ordenados = [m for m in prioritarios if m in candidatos]
            for m in candidatos:
                if m not in ordenados:
                    ordenados.append(m)
            if ordenados:
                return ordenados
    except Exception:
        pass
    return prioritarios

def extraer_json_seguro(texto: str):
    match = re.search(r"\{.*\}", texto, re.DOTALL)
    if not match:
        return None
    return json.loads(match.group(0))

def consultar_ia_rest(prompt: str):
    if not GEMINI_KEY:
        print("    [!] Falta GEMINI_API_KEY_FREE.", flush=True)
        return None
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_KEY
    }
    modelos = obtener_modelos_activos(headers)

    for modelo in modelos:
        usa_json_nativo = "gemma" not in modelo.lower()
        gen_config = {"temperature": 0.2}
        if usa_json_nativo:
            gen_config["responseMimeType"] = "application/json"

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": gen_config
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=12)
            if r.status_code == 400 and "responseMimeType" in payload["generationConfig"]:
                payload["generationConfig"].pop("responseMimeType", None)
                r = requests.post(url, headers=headers, json=payload, timeout=12)

            if r.status_code == 200:
                data = r.json()
                texto_resp = data["candidates"][0]["content"]["parts"][0]["text"]
                parsed = extraer_json_seguro(texto_resp)
                if parsed:
                    print(f"    [AI] Respondido por {modelo}", flush=True)
                    return parsed
        except Exception:
            pass

    print("    [!] Ningún modelo respondió a tiempo en este intento.", flush=True)
    return None

def evaluar_y_enviar(fuente: str, titulo: str, texto_limpio: str, link: str) -> bool:
    print(f"  [>] Analizando ({fuente}): {titulo[:58]}...", flush=True)
    regla = (
        "En r/forhire NO ofrezcas trabajo gratis; demuestra diagnóstico técnico inmediato."
        if "forhire" in fuente.lower()
        else "Sé directo y profesional confirmando disponibilidad y entrega rápida."
    )
    prompt = (
        f"Evalúa esta publicación de Reddit ({fuente}) y responde ÚNICAMENTE con un objeto JSON válido.\n"
        f"Título: {titulo}\n"
        f"Contenido: {texto_limpio}\n"
        f"Contexto: {regla}\n"
        f"REGLAS ESTRICTAS DE FILTRADO:\n"
        f"- relevante=true SOLO si alguien busca contratar (Hiring/Task) para un proyecto freelance puntual o tarea técnica corta (web scraping, script Python, bot de Telegram/Discord, automatización, extracción/limpieza de datos, API o arreglo web).\n"
        f"- RECHAZA (relevante=false, score<=4) ofertas donde alguien ofrece sus propios servicios ([For Hire]), puestos presenciales, trabajos sin pago (equity/rev-share) o tareas académicas.\n"
        f"Estructura exacta requerida:\n"
        f'{{"relevante": true, "score": 8, "categoria": "Python", "presupuesto": "$150 USD", "resumen_es": "...", "pitch_en": "..."}}'
    )
    try:
        datos = consultar_ia_rest(prompt)
        if not datos:
            return False

        score = int(datos.get("score", 0))
        print(f"    [=] Relevante: {datos.get('relevante')} | Score: {score}/10", flush=True)
        if datos.get("relevante") and score >= 7:
            accion = (
                "Comentar $bid en el post de Reddit antes de enviar DM"
                if fuente.lower() in ("r/slavelabour", "r/donedirtcheap")
                else "Abrir el post en Reddit y enviar DM directo al autor"
            )
            mensaje = (
                f"⚡ [{datos.get('categoria', 'Tech')}] SCORE: {score}/10\n"
                f"💰 Presupuesto: {datos.get('presupuesto', 'Por definir')}  |  📍 Fuente: {fuente}\n\n"
                f"📌 {titulo}\n"
                f"📝 {datos.get('resumen_es', '')}\n"
                f"⚠️ Protocolo: {accion}\n"
                f"🔗 Reddit: {link}\n\n"
                f"📋 PITCH SUGERIDO:\n{datos.get('pitch_en', '')}"
            )
            publicar_telegram(mensaje)
        return True
    except Exception as e:
        print(f"    [!] Error evaluando oferta: {e}", flush=True)
        return False

def recolectar_ofertas() -> list:
    ofertas = []
    subreddits = ["forhire", "slavelabour", "hiring", "freelance_forhire", "DoneDirtCheap"]

    for sub in subreddits:
        try:
            rss_url = f"https://www.reddit.com/r/{sub}/new/.rss"
            api_url = f"https://api.rss2json.com/v1/api.json?rss_url={rss_url}"
            r = requests.get(api_url, headers=WEB_HEADERS, timeout=15)
            if r.status_code == 200 and r.json().get("status") == "ok":
                cont = 0
                for item in r.json().get("items", [])[:15]:
                    titulo = item.get("title", "")
                    if REGEX_DESCARTAR.search(titulo):
                        continue
                    if sub.lower() in ("forhire", "slavelabour", "freelance_forhire", "donedirtcheap") and not REGEX_ACEPTAR.search(titulo):
                        continue
                    ofertas.append({
                        "id": item.get("guid", item.get("link")),
                        "fuente": f"r/{sub}",
                        "titulo": titulo,
                        "texto": limpiar_html(item.get("description", "")),
                        "link": item.get("link", "")
                    })
                    cont += 1
                print(f"[OK] Reddit r/{sub} -> {cont} candidatas", flush=True)
        except Exception as e:
            print(f"[!] Error Reddit r/{sub}: {e}", flush=True)

    return ofertas

def ejecutar_ciclo() -> None:
    print("🚀 Iniciando ciclo Radar Zero-Touch v5.2 (100% Reddit)...", flush=True)
    conn = sqlite3.connect("estado_radar_v4.db")
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS vistos (post_id TEXT PRIMARY KEY, ts DATETIME DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("DELETE FROM vistos WHERE post_id NOT IN (SELECT post_id FROM vistos ORDER BY ts DESC LIMIT 1500)")
        conn.commit()

        for item in recolectar_ofertas():
            if conn.execute("SELECT 1 FROM vistos WHERE post_id = ?", (item["id"],)).fetchone():
                continue

            procesado_ok = evaluar_y_enviar(item["fuente"], item["titulo"], item["texto"], item["link"])
            if procesado_ok:
                conn.execute("INSERT OR IGNORE INTO vistos (post_id) VALUES (?)", (item["id"],))
                conn.commit()
            time.sleep(1.5)

        print("🏁 Ciclo completado con éxito.", flush=True)
    finally:
        conn.close()

if __name__ == "__main__":
    if "--test" in sys.argv:
        evaluar_y_enviar(
            "r/forhire",
            "[Hiring] Need Python developer to scrape Shopify store prices ($150 USD)",
            "Looking for a clean Python script to extract product titles, variants, and prices from 5 Shopify stores into CSV.",
            "https://www.reddit.com/r/forhire/"
        )
    else:
        ejecutar_ciclo()
