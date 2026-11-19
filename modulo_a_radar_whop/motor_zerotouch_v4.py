import os
import re
import sys
import json
import time
import sqlite3
import requests
from bs4 import BeautifulSoup

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

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

WEB_HEADERS = {"User-Agent": "ZeroTouchRadar/5.2 (+https://github.com)"}
REGEX_DESCARTAR = re.compile(r"(\[|\()\s*(for\s*hire|forhire|offer)\s*(\]|\))", re.IGNORECASE)
REGEX_ACEPTAR = re.compile(r"((\[|\()\s*(hiring|task)\s*(\]|\))|^hiring\b)", re.IGNORECASE)

def limpiar_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    texto = BeautifulSoup(raw_html, "html.parser").get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", texto)[:1600]

def publicar_telegram(mensaje: str) -> bool:
    if not TG_TOKEN or not TG_CHANNEL_ID:
        print("    [!] Faltan credenciales de Telegram.", flush=True)
        return False
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TG_CHANNEL_ID, "text": mensaje, "disable_web_page_preview": True}, timeout=15)
        if r.status_code == 200:
            print("    [TG] Alerta publicada en Telegram!", flush=True)
            return True
        print(f"    [TG] Error {r.status_code}: {r.text}", flush=True)
    except Exception as e:
        print(f"    [TG] Excepcion: {e}", flush=True)
    return False

def obtener_modelos_activos(headers: dict) -> list:
    prioritarios = ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemma-3-27b-it"]
    try:
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/models", headers=headers, timeout=10)
        if r.status_code == 200:
            ignorar = ("2.0", "2.5", "1.5", "embedding", "aqa", "imagen", "veo", "tts", "audio", "robotics", "computer-use", "deep-research")
            candidatos = []
            for m in r.json().get("models", []):
                nombre = m.get("name", "").replace("models/", "")
                if "generateContent" in m.get("supportedGenerationMethods", []) and not any(b in nombre.lower() for b in ignorar):
                    if ("gemini" in nombre.lower() or "gemma" in nombre.lower()) and "image" not in nombre.lower():
                        candidatos.append(nombre)
            candidatos.sort(reverse=True)
            ordenados = [m for m in prioritarios if m in candidatos] + [m for m in candidatos if m not in prioritarios]
            if ordenados:
                return ordenados
    except Exception:
        pass
    return prioritarios

def consultar_ia_rest(prompt: str):
    if not GEMINI_KEY:
        print("    [!] Falta GEMINI_API_KEY_FREE.", flush=True)
        return None
    headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_KEY}
    for modelo in obtener_modelos_activos(headers):
        gen_config = {"temperature": 0.2}
        if "gemma" not in modelo.lower():
            gen_config["responseMimeType"] = "application/json"
        payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": gen_config}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=12)
            if r.status_code == 400 and "responseMimeType" in payload["generationConfig"]:
                payload["generationConfig"].pop("responseMimeType", None)
                r = requests.post(url, headers=headers, json=payload, timeout=12)
            if r.status_code == 200:
                texto = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                match = re.search(r"\{.*\}", texto, re.DOTALL)
                if match:
                    print(f"    [AI] Respondido por {modelo}", flush=True)
                    return json.loads(match.group(0))
        except Exception:
            pass
    return None

def evaluar_y_enviar(fuente: str, titulo: str, texto_limpio: str, link: str) -> bool:
    print(f"  [>] Analizando ({fuente}): {titulo[:58]}...", flush=True)
    regla = "En r/forhire NO ofrezcas trabajo gratis; demuestra diagnostico tecnico inmediato." if "forhire" in fuente.lower() else "Se directo confirmando disponibilidad y entrega rapida."
    prompt = (
        f"Evalua esta publicacion de Reddit ({fuente}) y responde UNICAMENTE con JSON valido.\n"
        f"Titulo: {titulo}\nContenido: {texto_limpio}\nContexto: {regla}\n"
        f"REGLAS: relevante=true SOLO si buscan contratar (Hiring/Task) para un proyecto freelance puntual o tarea tecnica corta (scraping, script Python, bot Telegram/Discord, automatizacion, datos, API o arreglo web). "
        f"Rechaza [For Hire], puestos presenciales, sin pago o tareas escolares.\n"
        f'Formato exacto: {{"relevante": true, "score": 8, "categoria": "Python", "presupuesto": "$150 USD", "resumen_es": "...", "pitch_en": "..."}}'
    )
    try:
        datos = consultar_ia_rest(prompt)
        if not datos:
            return False
        score = int(datos.get("score", 0))
        print(f"    [=] Relevante: {datos.get('relevante')} | Score: {score}/10", flush=True)
        if datos.get("relevante") and score >= 7:
            accion = "Comentar $bid en el post de Reddit antes de enviar DM" if fuente.lower() in ("r/slavelabour", "r/donedirtcheap") else "Abrir el post en Reddit y enviar DM directo al autor"
            mensaje = (
                f"[{datos.get('categoria', 'Tech')}] SCORE: {score}/10\n"
                f"Presupuesto: {datos.get('presupuesto', 'Por definir')} | Fuente: {fuente}\n\n"
                f"{titulo}\n{datos.get('resumen_es', '')}\n"
                f"Protocolo: {accion}\nReddit: {link}\n\n"
                f"PITCH SUGERIDO:\n{datos.get('pitch_en', '')}"
            )
            publicar_telegram(mensaje)
        return True
    except Exception as e:
        print(f"    [!] Error evaluando: {e}", flush=True)
        return False

def recolectar_ofertas() -> list:
    ofertas = []
    for sub in ["forhire", "slavelabour", "hiring", "freelance_forhire", "DoneDirtCheap"]:
        try:
            api_url = f"https://api.rss2json.com/v1/api.json?rss_url=https://www.reddit.com/r/{sub}/new/.rss"
            r = requests.get(api_url, headers=WEB_HEADERS, timeout=15)
            if r.status_code == 200 and r.json().get("status") == "ok":
                cont = 0
                for item in r.json().get("items", [])[:15]:
                    titulo = item.get("title", "")
                    if REGEX_DESCARTAR.search(titulo):
                        continue
                    if sub.lower() in ("forhire", "slavelabour", "freelance_forhire", "donedirtcheap") and not REGEX_ACEPTAR.search(titulo):
                        continue
                    ofertas.append({"id": item.get("guid", item.get("link")), "fuente": f"r/{sub}", "titulo": titulo, "texto": limpiar_html(item.get("description", "")), "link": item.get("link", "")})
                    cont += 1
                print(f"[OK] Reddit r/{sub} -> {cont} candidatas", flush=True)
        except Exception as e:
            print(f"[!] Error Reddit r/{sub}: {e}", flush=True)
    return ofertas

def ejecutar_ciclo() -> None:
    print("Iniciando ciclo Radar Zero-Touch v5.2 (100% Reddit)...", flush=True)
    conn = sqlite3.connect("estado_radar_v4.db")
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS vistos (post_id TEXT PRIMARY KEY, ts DATETIME DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("DELETE FROM vistos WHERE post_id NOT IN (SELECT post_id FROM vistos ORDER BY ts DESC LIMIT 1500)")
        conn.commit()
        for item in recolectar_ofertas():
            if conn.execute("SELECT 1 FROM vistos WHERE post_id = ?", (item["id"],)).fetchone():
                continue
            if evaluar_y_enviar(item["fuente"], item["titulo"], item["texto"], item["link"]):
                conn.execute("INSERT OR IGNORE INTO vistos (post_id) VALUES (?)", (item["id"],))
                conn.commit()
            time.sleep(1.5)
        print("Ciclo completado.", flush=True)
    finally:
        conn.close()

if __name__ == "__main__":
    if "--test" in sys.argv:
        evaluar_y_enviar("r/forhire", "[Hiring] Need Python developer to scrape Shopify store prices ($150 USD)", "Looking for a clean Python script to extract product titles, variants, and prices from 5 Shopify stores into CSV.", "https://www.reddit.com/r/forhire/")
    else:
        ejecutar_ciclo()