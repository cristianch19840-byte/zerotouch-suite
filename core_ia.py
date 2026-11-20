import os
import re
import ast
import sys
import json
import time
import shutil
import sqlite3
import threading
import subprocess
import importlib.util
from collections import deque
from datetime import datetime
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

if os.name == "nt":
    os.system("")

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT_DIR, "estado_radar_v4.db")
CONFIG_PATH = os.path.join(ROOT_DIR, "config.json")

class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    DIM = "\033[90m"

DEFAULT_CONFIG = {
    "nombre_marca": "Cristian Dev | ZeroTouch Automation",
    "especialidad": "Python Scripting, Web Scraping, Telegram/Discord Bots, Data Extraction & Workflow Automation",
    "metodos_pago": "Binance Pay (USDT TRC20/BEP20), Airtm, or PayPal",
    "detalle_pago_factura": "Binance Pay / USDT (TRC20) | Airtm | PayPal (request email/ID via chat)",
    "github_url": "https://github.com/cristianch19840-byte",
    "whop_url": "",
    "tarifa_hora_usd": 25,
    "trm_cop": 4200,
    "score_minimo": 6,
    "max_horas_post": 12,
    "intervalo_sniper_seg": 70,
    "max_ia_por_ciclo": 16,
    "recordatorio_followup_horas": 20,
    "telegram_admin_id": "",
    "palabras_extra_blacklist": []
}

STOPWORDS_FREELANCE = {
    "hiring", "task", "paid", "request", "need", "looking", "for", "dev", "developer",
    "programmer", "freelancer", "someone", "help", "with", "python", "script", "bot",
    "code", "coding", "project", "usd", "usdt", "quick", "simple", "small", "make",
    "build", "create", "want", "that", "this", "from", "into", "and", "the", "you",
    "can", "will", "pay", "paying", "work", "job", "urgently", "urgent", "asap",
}

MAPA_PIP = {
    "bs4": "beautifulsoup4",
    "PIL": "pillow",
    "cv2": "opencv-python",
    "yaml": "pyyaml",
    "dotenv": "python-dotenv",
    "sklearn": "scikit-learn",
    "telegram": "python-telegram-bot",
    "discord": "discord.py",
    "docx": "python-docx",
    "openpyxl": "openpyxl",
    "pandas": "pandas",
    "selenium": "selenium",
    "playwright": "playwright",
    "requests": "requests",
    "httpx": "httpx",
    "aiohttp": "aiohttp",
    "lxml": "lxml",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "flask": "flask",
    "pydantic": "pydantic",
    "tweepy": "tweepy",
    "praw": "praw",
    "telethon": "telethon",
    "pyrogram": "pyrogram",
}

_LOG_LOCK = threading.Lock()
_LOG_BUFFER: deque[str] = deque(maxlen=120)

def log_evento(msg: str, imprimir: bool = False) -> None:
    linea = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    with _LOG_LOCK:
        _LOG_BUFFER.append(linea)
    if imprimir:
        print(linea, flush=True)

def obtener_logs(limite: int = 50) -> list[str]:
    with _LOG_LOCK:
        return list(_LOG_BUFFER)[-limite:]

def safe_float(val, default: float = 0.0) -> float:
    try:
        if val is None or val == "":
            return default
        return float(str(val).replace("$", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return default

def safe_int(val, default: int = 0) -> int:
    try:
        if val is None or val == "":
            return default
        return int(float(str(val).strip()))
    except (ValueError, TypeError):
        return default

def safe_bool(val) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    return str(val or "").strip().lower() in ("true", "1", "yes", "si", "sí")

def extraer_score(val) -> int:
    if isinstance(val, (int, float)):
        return max(0, min(10, int(round(val))))
    m = re.search(r"(\d+(?:\.\d+)?)", str(val or ""))
    if not m:
        return 0
    return max(0, min(10, int(round(float(m.group(1))))))

def _parse_monto_k(num_str: str, suf_k: str | None) -> float:
    val = safe_float(num_str, 0.0)
    if suf_k and suf_k.lower() == "k":
        val *= 1000.0
    return val

def extraer_presupuesto_usd(texto: str) -> float:
    if not texto:
        return 0.0
    t = str(texto)

    # 1. Rango con prefijo de moneda: $80-$120, $1k-$2k, USD 100-200
    m_r1 = re.search(
        r"(?:\$|€|USD\s*|USDT\s*)(\d{1,5}(?:,\d{3})*(?:\.\d+)?)(k)?\s*(?:-|–|to)\s*(?:\$|€)?(\d{1,5}(?:,\d{3})*(?:\.\d+)?)(k)?",
        t,
        re.IGNORECASE,
    )
    if m_r1:
        a = _parse_monto_k(m_r1.group(1), m_r1.group(2))
        b = _parse_monto_k(m_r1.group(3), m_r1.group(4))
        prom = round((a + b) / 2.0, 2)
        if 5 <= prom <= 50000:
            return prom

    # 2. Rango con moneda al final: 50-150 USD, 1k-2k USDT
    m_r2 = re.search(
        r"\b(\d{1,5}(?:,\d{3})*(?:\.\d+)?)(k)?\s*(?:-|–|to)\s*(\d{1,5}(?:,\d{3})*(?:\.\d+)?)(k)?\s*(?:USD|USDT|bucks|\$|€)\b",
        t,
        re.IGNORECASE,
    )
    if m_r2:
        a = _parse_monto_k(m_r2.group(1), m_r2.group(2))
        b = _parse_monto_k(m_r2.group(3), m_r2.group(4))
        prom = round((a + b) / 2.0, 2)
        if 5 <= prom <= 50000:
            return prom

    # 3. Valor unico con prefijo: $1.5k, $150, USD 200
    m_pref = re.search(r"(?:\$|€|USD\s*|USDT\s*)(\d{1,5}(?:,\d{3})*(?:\.\d+)?)(k)?\b", t, re.IGNORECASE)
    if m_pref:
        v = _parse_monto_k(m_pref.group(1), m_pref.group(2))
        if 5 <= v <= 50000:
            return round(v, 2)

    # 4. Valor unico con sufijo: 250 USDT, 1.5k USD, 100$
    m_suf = re.search(r"\b(\d{1,5}(?:,\d{3})*(?:\.\d+)?)(k)?\s*(?:USD|USDT|bucks|\$|€)\b", t, re.IGNORECASE)
    if m_suf:
        v = _parse_monto_k(m_suf.group(1), m_suf.group(2))
        if 5 <= v <= 50000:
            return round(v, 2)

    return 0.0

def cargar_env(ruta: str | None = None) -> None:
    archivo = ruta or os.path.join(ROOT_DIR, ".env")
    if os.path.exists(archivo):
        with open(archivo, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

cargar_env()

def cargar_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8-sig") as f:
                user_cfg = json.load(f)
                if isinstance(user_cfg, dict):
                    cfg.update(user_cfg)
        except Exception as e:
            log_evento(f"Aviso leyendo config.json: {e}")
    else:
        if not os.getenv("GITHUB_ACTIONS"):
            guardar_config(cfg)
    return cfg

def guardar_config(cfg: dict) -> None:
    tmp_path = CONFIG_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, CONFIG_PATH)

MODELOS_PREFERIDOS = [
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemma-3-27b-it",
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
]

_CACHE_LOCK = threading.Lock()
MODEL_COOLDOWNS: dict[str, float] = {}
TRUST_CACHE: dict[str, tuple[float, str]] = {}

def crear_sesion_http() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=2, backoff_factor=0.6, status_forcelist=[500, 502, 504])
    adapter = HTTPAdapter(max_retries=retry, pool_connections=28, pool_maxsize=28)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s

SESSION = crear_sesion_http()

def extraer_etiqueta(texto: str, tag: str) -> str:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", texto, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""

def limpiar_bloque_codigo(texto: str) -> str:
    return re.sub(r"^```[a-zA-Z0-9_-]*\s*|\s*```$", "", texto.strip())

def parsear_json_seguro(texto: str) -> dict | None:
    if not texto:
        return None
    limpio = limpiar_bloque_codigo(texto)
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", limpio):
        try:
            obj, _ = decoder.raw_decode(limpio[match.start():])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None

def copiar_al_portapapeles(texto: str) -> bool:
    if not texto or os.name != "nt":
        return False
    try:
        subprocess.run(["clip"], input=texto, text=True, check=True)
        return True
    except Exception:
        return False

def alerta_sonora(prioridad: str = "alta") -> None:
    if os.name != "nt":
        return
    try:
        import winsound
        if prioridad == "ballena":
            for freq in (1000, 1300, 1650):
                winsound.Beep(freq, 120)
        elif prioridad == "alta":
            winsound.Beep(1150, 120)
            winsound.Beep(1550, 160)
        else:
            winsound.Beep(900, 110)
    except Exception:
        pass

def similitud_jaccard(texto_a: str, texto_b: str) -> float:
    raw_a = set(re.findall(r"[a-z0-9]{3,}", texto_a.lower()))
    raw_b = set(re.findall(r"[a-z0-9]{3,}", texto_b.lower()))
    sa = raw_a - STOPWORDS_FREELANCE
    sb = raw_b - STOPWORDS_FREELANCE
    if len(sa) < 2 or len(sb) < 2:
        sa, sb = raw_a, raw_b
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)

def preparar_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS vistos (post_id TEXT PRIMARY KEY, titulo_norm TEXT DEFAULT '', titulo_palabras TEXT DEFAULT '', ts DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    cols_v = [row[1] for row in conn.execute("PRAGMA table_info(vistos)").fetchall()]
    if "titulo_norm" not in cols_v:
        conn.execute("ALTER TABLE vistos ADD COLUMN titulo_norm TEXT DEFAULT ''")
    if "titulo_palabras" not in cols_v:
        conn.execute("ALTER TABLE vistos ADD COLUMN titulo_palabras TEXT DEFAULT ''")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha DATETIME DEFAULT CURRENT_TIMESTAMP,
            fuente TEXT,
            autor TEXT DEFAULT '',
            titulo TEXT,
            categoria TEXT,
            presupuesto TEXT,
            presupuesto_num REAL DEFAULT 0,
            score INTEGER,
            competencia TEXT DEFAULT '',
            confianza TEXT DEFAULT '',
            prioridad_tag TEXT DEFAULT '',
            link TEXT,
            estado TEXT DEFAULT 'nuevo',
            ganancia_usd REAL DEFAULT 0,
            notas TEXT DEFAULT '',
            followup_enviado INTEGER DEFAULT 0,
            contactado_ts DATETIME DEFAULT NULL
        )
        """
    )
    cols_l = [row[1] for row in conn.execute("PRAGMA table_info(leads)").fetchall()]
    for col_name, col_def in [
        ("autor", "TEXT DEFAULT ''"),
        ("presupuesto_num", "REAL DEFAULT 0"),
        ("competencia", "TEXT DEFAULT ''"),
        ("confianza", "TEXT DEFAULT ''"),
        ("prioridad_tag", "TEXT DEFAULT ''"),
        ("notas", "TEXT DEFAULT ''"),
        ("followup_enviado", "INTEGER DEFAULT 0"),
        ("contactado_ts", "DATETIME DEFAULT NULL"),
    ]:
        if col_name not in cols_l:
            conn.execute(f"ALTER TABLE leads ADD COLUMN {col_name} {col_def}")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_estado ON leads(estado)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_link ON leads(link)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stats_diarias (
            fecha TEXT PRIMARY KEY,
            descartados_local INTEGER DEFAULT 0,
            evaluados_ia INTEGER DEFAULT 0,
            alertas_enviadas INTEGER DEFAULT 0,
            tokens_est_usados INTEGER DEFAULT 0,
            tokens_est_ahorrados INTEGER DEFAULT 0
        )
        """
    )
    cols_s = [row[1] for row in conn.execute("PRAGMA table_info(stats_diarias)").fetchall()]
    for col_name, col_def in [("tokens_est_usados", "INTEGER DEFAULT 0"), ("tokens_est_ahorrados", "INTEGER DEFAULT 0")]:
        if col_name not in cols_s:
            conn.execute(f"ALTER TABLE stats_diarias ADD COLUMN {col_name} {col_def}")

    conn.execute("DELETE FROM vistos WHERE post_id NOT IN (SELECT post_id FROM vistos ORDER BY ts DESC LIMIT 6000)")
    conn.commit()
    return conn

def registrar_metricas(conn: sqlite3.Connection, descartados: int = 0, ia: int = 0, alertas: int = 0, tok_usados: int = 0, tok_ahorrados: int = 0) -> None:
    hoy = datetime.now().strftime("%Y-%m-%d")
    conn.execute("INSERT OR IGNORE INTO stats_diarias (fecha) VALUES (?)", (hoy,))
    conn.execute(
        """
        UPDATE stats_diarias
        SET descartados_local = descartados_local + ?,
            evaluados_ia = evaluados_ia + ?,
            alertas_enviadas = alertas_enviadas + ?,
            tokens_est_usados = tokens_est_usados + ?,
            tokens_est_ahorrados = tokens_est_ahorrados + ?
        WHERE fecha = ?
        """,
        (descartados, ia, alertas, tok_usados, tok_ahorrados, hoy),
    )
    conn.commit()

def crear_backup_rotativo(max_backups: int = 7) -> str | None:
    if not os.path.exists(DB_PATH):
        return None
    bdir = os.path.join(ROOT_DIR, "backups")
    os.makedirs(bdir, exist_ok=True)
    dst = os.path.join(bdir, f"zerotouch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
    conn = preparar_db()
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    finally:
        conn.close()
    shutil.copy2(DB_PATH, dst)
    archivos = sorted([os.path.join(bdir, f) for f in os.listdir(bdir) if f.endswith(".db")], key=os.path.getmtime)
    while len(archivos) > max_backups:
        viejo = archivos.pop(0)
        try:
            os.remove(viejo)
        except OSError:
            pass
    log_evento(f"Backup seguro creado: {os.path.basename(dst)}")
    return dst

def listar_scripts_disponibles() -> list[dict]:
    encontrados = []
    borrador = os.path.join(ROOT_DIR, "modulo_b_ejecutor", "borrador_cliente.py")
    if os.path.isfile(borrador):
        encontrados.append({
            "label": "borrador_cliente.py (Actual)",
            "ruta": "modulo_b_ejecutor/borrador_cliente.py",
            "mtime": os.path.getmtime(borrador),
        })
    pdir = os.path.join(ROOT_DIR, "proyectos")
    if os.path.isdir(pdir):
        for carpeta in os.listdir(pdir):
            cand = os.path.join(pdir, carpeta, "script.py")
            if os.path.isfile(cand):
                encontrados.append({
                    "label": f"proyectos/{carpeta}/script.py",
                    "ruta": f"proyectos/{carpeta}/script.py",
                    "mtime": os.path.getmtime(cand),
                })
    encontrados.sort(key=lambda x: x["mtime"], reverse=True)
    return [{"label": x["label"], "ruta": x["ruta"]} for x in encontrados[:25]]

def verificar_confianza_reddit(autor: str) -> str:
    if not autor or autor.lower() in ("[deleted]", "automoderator", "none", "github", "hackernews"):
        return "🔎 Fuente externa"
    clave = autor.lower()
    ahora = time.time()
    with _CACHE_LOCK:
        if clave in TRUST_CACHE and (ahora - TRUST_CACHE[clave][0]) < 3600:
            return TRUST_CACHE[clave][1]
    res = "🔎 Sin historial publico"
    try:
        r = SESSION.get(
            f"https://www.reddit.com/user/{autor}/about.json",
            headers={"User-Agent": "python:zerotouch-trust:v12.5 (by /u/zerotouch_freelance)"},
            timeout=6,
        )
        if r.status_code == 200:
            d = r.json().get("data", {})
            creado = d.get("created_utc")
            karma = safe_int(d.get("total_karma", 0), 0)
            if creado:
                dias = max(0, int((ahora - creado) / 86400))
                edad_txt = f"{dias // 365}a" if dias >= 365 else (f"{dias // 30}m" if dias >= 30 else f"{dias}d")
                karma_txt = f"{karma / 1000:.1f}k" if karma >= 1000 else str(karma)
                if dias >= 180 and karma >= 100:
                    res = f"🛡️ Confiable ({edad_txt} | {karma_txt} karma)"
                elif dias >= 30 and karma >= 15:
                    res = f"🟢 Normal ({edad_txt} | {karma_txt} karma)"
                else:
                    res = f"🚨 OJO cuenta nueva ({edad_txt} | {karma_txt} karma) — pide 50%"
    except Exception:
        pass
    with _CACHE_LOCK:
        TRUST_CACHE[clave] = (ahora, res)
    return res

def generar_texto_ia(prompt: str, temperatura: float = 0.2, json_mode: bool = False, timeout: int = 26) -> str | None:
    api_key = os.getenv("GEMINI_API_KEY_FREE")
    if not api_key:
        log_evento("[!] Falta GEMINI_API_KEY_FREE en .env")
        print(f"    {C.RED}[!] Falta GEMINI_API_KEY_FREE.{C.RESET}", flush=True)
        return None

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }
    ahora = time.time()
    with _CACHE_LOCK:
        candidatos = [m for m in MODELOS_PREFERIDOS if MODEL_COOLDOWNS.get(m, 0) <= ahora]
    if not candidatos:
        candidatos = list(MODELOS_PREFERIDOS)

    for modelo in candidatos:
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
                cands = r.json().get("candidates", [])
                if cands:
                    partes = cands[0].get("content", {}).get("parts", [])
                    if partes and "text" in partes[0]:
                        print(f"    {C.DIM}[AI] OK con {modelo}{C.RESET}", flush=True)
                        return partes[0]["text"]
            elif r.status_code in (429, 503):
                with _CACHE_LOCK:
                    MODEL_COOLDOWNS[modelo] = time.time() + 60
                log_evento(f"Modelo {modelo} en limite ({r.status_code}), cooldown 60s")
                print(f"    {C.YELLOW}[~] {modelo} ocupado ({r.status_code}), cooldown 60s...{C.RESET}", flush=True)
            else:
                print(f"    {C.YELLOW}[~] {modelo} HTTP {r.status_code}, saltando...{C.RESET}", flush=True)
        except Exception:
            print(f"    {C.YELLOW}[~] {modelo} timeout/error, saltando...{C.RESET}", flush=True)

    log_evento("[!] Ningun modelo de Gemini respondio en este intento")
    return None

def generar_json_ia(prompt: str, temperatura: float = 0.2, timeout: int = 16) -> dict | None:
    texto = generar_texto_ia(prompt, temperatura=temperatura, json_mode=True, timeout=timeout)
    return parsear_json_seguro(texto) if texto else None

def analizar_dependencias(codigo: str) -> tuple[list[str], list[str]]:
    todos_pip = set()
    faltantes_pip = set()
    stdlib = getattr(sys, "stdlib_module_names", set())
    try:
        tree = ast.parse(codigo)
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mods.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                mods.add(node.module.split(".")[0])
        for mod in mods:
            if mod in stdlib or mod in ("core_ia", "__future__"):
                continue
            pip_name = MAPA_PIP.get(mod, mod)
            todos_pip.add(pip_name)
            if importlib.util.find_spec(mod) is None:
                faltantes_pip.add(pip_name)
    except SyntaxError:
        pass
    return sorted(todos_pip), sorted(faltantes_pip)

def validar_y_reparar_python(codigo: str, descripcion: str = "") -> tuple[str, bool]:
    codigo = limpiar_bloque_codigo(codigo)
    if not codigo:
        return "", False
    try:
        ast.parse(codigo)
        return codigo, True
    except SyntaxError as e:
        log_evento(f"SyntaxError linea {e.lineno}, auto-reparando con IA")
        print(f"    {C.YELLOW}[!] SyntaxError en linea {e.lineno} ({e.msg}). Auto-reparando con IA...{C.RESET}", flush=True)
        fix_prompt = (
            f"Corrige este error de sintaxis en Python 3.12: linea {e.lineno}, error: {e.msg}.\n"
            f"Contexto: {descripcion[:200]}\n"
            "Devuelve UNICAMENTE el codigo Python corregido dentro de <CODIGO_FIX>...</CODIGO_FIX>:\n\n"
            f"{codigo}"
        )
        resp = generar_texto_ia(fix_prompt, temperatura=0.1, json_mode=False, timeout=22)
        if resp:
            fijo = limpiar_bloque_codigo(extraer_etiqueta(resp, "CODIGO_FIX") or resp)
            try:
                ast.parse(fijo)
                print(f"    {C.GREEN}[+] Codigo auto-reparado y validado con AST!{C.RESET}", flush=True)
                return fijo, True
            except SyntaxError:
                return fijo, False
        return codigo, False