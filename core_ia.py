import os
import re
import sys
import json
import subprocess
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def cargar_env(ruta: str = ".env") -> None:
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

cargar_env()

MODELOS_PREFERIDOS = [
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemma-3-27b-it",
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
]

def crear_sesion_http() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=2, backoff_factor=0.5, status_forcelist=[500, 502, 504])
    adapter = HTTPAdapter(max_retries=retry, pool_connections=12, pool_maxsize=12)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s

SESSION = crear_sesion_http()

def extraer_etiqueta(texto: str, tag: str) -> str:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", texto, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""

def limpiar_bloque_codigo(texto: str) -> str:
    return re.sub(r"^```[a-zA-Z0-9_-]*\s*|\s*```$", "", texto.strip())

def copiar_al_portapapeles(texto: str) -> bool:
    if not texto or os.name != "nt":
        return False
    try:
        subprocess.run(["clip"], input=texto, text=True, check=True)
        return True
    except Exception:
        return False

def generar_texto_ia(prompt: str, temperatura: float = 0.2, json_mode: bool = False, timeout: int = 20) -> str | None:
    api_key = os.getenv("GEMINI_API_KEY_FREE")
    if not api_key:
        print("    [!] Falta GEMINI_API_KEY_FREE.", flush=True)
        return None

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }

    for modelo in MODELOS_PREFERIDOS:
        gen_config: dict = {"temperature": temperatura}
        if json_mode and "gemma" not in modelo.lower():
            gen_config["responseMimeType"] = "application/json"

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": gen_config,
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
        try:
            r = SESSION.post(url, headers=headers, json=payload, timeout=timeout)
            if r.status_code == 400 and "responseMimeType" in payload["generationConfig"]:
                payload["generationConfig"].pop("responseMimeType", None)
                r = SESSION.post(url, headers=headers, json=payload, timeout=timeout)

            if r.status_code == 200:
                candidatos = r.json().get("candidates", [])
                if candidatos:
                    partes = candidatos[0].get("content", {}).get("parts", [])
                    if partes and "text" in partes[0]:
                        print(f"    [AI] OK con {modelo}", flush=True)
                        return partes[0]["text"]
            else:
                print(f"    [~] {modelo} HTTP {r.status_code}, probando respaldo...", flush=True)
        except Exception:
            print(f"    [~] {modelo} timeout/error, probando respaldo...", flush=True)

    return None

def generar_json_ia(prompt: str, temperatura: float = 0.2, timeout: int = 15) -> dict | None:
    texto = generar_texto_ia(prompt, temperatura=temperatura, json_mode=True, timeout=timeout)
    if not texto:
        return None
    match = re.search(r"\{.*\}", texto, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None