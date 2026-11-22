import os
import re
import time
import threading
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed

from core_ia import (
    C,
    SESSION,
    cargar_env,
    safe_int,
    safe_float,
)
from modulo_a_radar_whop.conectores.base import (
    BROWSER_HEADERS,
    esperar_dominio,
    crear_oferta,
    crear_meta_fuente,
)
from modulo_a_radar_whop.conectores.filtros import (
    REGEX_DESCARTAR,
    REGEX_CERRADO,
    REGEX_ACEPTAR,
    REGEX_GLOBAL_HIRING,
    REGEX_SPAM,
    limpiar_html,
    pasa_blacklist_custom,
)

OAUTH_UA = "windows:zerotouch-omni:v13.0 (by /u/zerotouch_freelance)"

_REDDIT_LOCK = threading.Lock()
_REDDIT_DIRECTO_403 = False
_OAUTH_TOKEN: str | None = None
_OAUTH_EXPIRA: float = 0.0
_OAUTH_LAST_ERR: str = ""

MULTIREDDIT_BATCHES = [
    ("Reddit-Core", ["forhire", "slavelabour", "hiring", "freelance_forhire", "DoneDirtCheap", "HireAProgrammer"]),
    ("Reddit-Tech", ["Jobs4Bitcoins", "Jobbit", "WebDevClassifieds", "requestabot", "ProgrammingTasks"]),
    ("Reddit-Niche", ["PythonJobs", "automate", "webscraping", "Discord_Bots", "n8n"]),
]

SUBS_SIN_TAG_OBLIGATORIO = {"hiring", "requestabot", "programmingtasks", "pythonjobs", "automate", "hireaprogrammer"}
SUBS_NICHO_ESTRICTO = {"webscraping", "discord_bots", "n8n"}
SUBS_BLACKLIST = {
    "signupsforpay", "referrals", "beermoney", "beermoneyglobal", "freebies",
    "borrow", "assistance", "homeworkhelp", "domyhomework", "essaywriting",
    "cryptomoonshots", "airdrops", "dirtysnapchat", "onlyfansreviews",
}

def marcar_reddit_403() -> None:
    global _REDDIT_DIRECTO_403
    with _REDDIT_LOCK:
        _REDDIT_DIRECTO_403 = True

def reddit_directo_disponible() -> bool:
    with _REDDIT_LOCK:
        return not _REDDIT_DIRECTO_403

def obtener_headers_reddit_oauth() -> dict | None:
    global _OAUTH_TOKEN, _OAUTH_EXPIRA, _OAUTH_LAST_ERR
    cid = (os.getenv("REDDIT_CLIENT_ID") or "").strip()
    csec = (os.getenv("REDDIT_CLIENT_SECRET") or "").strip()
    if not cid or not csec:
        return None
    ahora = time.time()
    with _REDDIT_LOCK:
        if _OAUTH_TOKEN and ahora < _OAUTH_EXPIRA:
            return {"Authorization": f"Bearer {_OAUTH_TOKEN}", "User-Agent": OAUTH_UA}
        try:
            r = SESSION.post(
                "https://www.reddit.com/api/v1/access_token",
                auth=(cid, csec),
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": OAUTH_UA},
                timeout=10,
            )
            if r.status_code == 200:
                tok = r.json().get("access_token")
                if tok:
                    _OAUTH_TOKEN = tok
                    _OAUTH_EXPIRA = ahora + max(300, safe_int(r.json().get("expires_in", 3600), 3600) - 120)
                    _OAUTH_LAST_ERR = ""
                    return {"Authorization": f"Bearer {_OAUTH_TOKEN}", "User-Agent": OAUTH_UA}
            else:
                _OAUTH_LAST_ERR = f"HTTP {r.status_code}"
        except Exception as e:
            _OAUTH_LAST_ERR = str(e)[:80]
    return None

def consultar_arctic_shift(params: dict) -> list | None:
    esperar_dominio("arctic-shift.photon-reddit.com", 0.40)
    try:
        r = SESSION.get(
            "https://arctic-shift.photon-reddit.com/api/posts/search",
            params=params,
            headers={"User-Agent": BROWSER_HEADERS["User-Agent"], "Accept": "application/json"},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json().get("data")
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return None

def consultar_pullpush(params: dict) -> list | None:
    esperar_dominio("api.pullpush.io", 0.20)
    try:
        r = SESSION.get(
            "https://api.pullpush.io/reddit/search/submission/",
            params=params,
            headers={"User-Agent": BROWSER_HEADERS["User-Agent"]},
            timeout=11,
        )
        if r.status_code == 200:
            data = r.json().get("data")
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return None

def consultar_rss2json_seguro(rss_url: str) -> list | None:
    esperar_dominio("api.rss2json.com", 0.45)
    api_url = f"https://api.rss2json.com/v1/api.json?rss_url={quote(rss_url, safe='')}"
    try:
        r = SESSION.get(api_url, headers={"User-Agent": BROWSER_HEADERS["User-Agent"]}, timeout=10)
        if r.status_code == 200 and r.json().get("status") == "ok":
            return r.json().get("items", [])
    except Exception:
        pass
    return None

def _evaluar_post_reddit(
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

    return crear_oferta(
        post_id=post_id or link,
        fuente=f"r/{sub}" if sub else "Reddit",
        plataforma="Reddit",
        tipo_trabajo="freelance",
        titulo=titulo,
        texto=cuerpo,
        link=link,
        autor=autor,
        edad_min=edad_min,
        comentarios=comentarios,
        tags_extra=sub_low,
        origen="reddit",
    )

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
    max_h = max_horas_override or max(1, safe_int(cfg.get("max_horas_post", 18), 18))
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
    link = (
        f"https://www.reddit.com{perm}"
        if perm.startswith("/")
        else (d.get("full_link") or (f"https://www.reddit.com/r/{sub}/comments/{d.get('id', '')}/" if sub and d.get("id") else (d.get("url") or "")))
    )

    return _evaluar_post_reddit(
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

def parsear_atom_reddit(xml_text: str, sub_default: str, cfg: dict, stats_descarte: dict | None = None) -> list[dict]:
    resultados = []
    max_h = max(1, safe_int(cfg.get("max_horas_post", 18), 18))
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

        it = _evaluar_post_reddit(
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
        if it:
            resultados.append(it)
    return resultados

def _obtener_lote(nombre_lote: str, subs: list[str], cfg: dict) -> tuple[list[dict], dict]:
    combo = "+".join(subs)
    stats_desc: dict[str, int] = {}
    items: list[dict] = []

    h_oauth = obtener_headers_reddit_oauth()
    if h_oauth:
        try:
            r = SESSION.get(f"https://oauth.reddit.com/r/{combo}/new?limit=50&raw_json=1", headers=h_oauth, timeout=10)
            if r.status_code == 200:
                children = r.json().get("data", {}).get("children", [])
                for child in children:
                    it = procesar_child_reddit(child.get("data", {}), cfg, stats_descarte=stats_desc)
                    if it:
                        items.append(it)
                tech_n = sum(1 for x in items if x["es_tech"])
                print(f"{C.GREEN}[OK] {nombre_lote:<16} (OAuth2 {len(children):2d} raw) -> {len(items):2d} hiring ({tech_n} tech){C.RESET}", flush=True)
                return items, crear_meta_fuente(nombre_lote, "reddit", True, "OAuth2", len(children), tech_n, stats_desc)
        except Exception:
            pass

    if reddit_directo_disponible():
        try:
            r = SESSION.get(f"https://www.reddit.com/r/{combo}/new.json?limit=50&raw_json=1", headers=BROWSER_HEADERS, timeout=8)
            if r.status_code == 200:
                children = r.json().get("data", {}).get("children", [])
                for child in children:
                    it = procesar_child_reddit(child.get("data", {}), cfg, stats_descarte=stats_desc)
                    if it:
                        items.append(it)
                tech_n = sum(1 for x in items if x["es_tech"])
                print(f"{C.DIM}[OK] {nombre_lote:<16} (JSON {len(children):2d} raw) -> {len(items):2d} hiring ({tech_n} tech){C.RESET}", flush=True)
                return items, crear_meta_fuente(nombre_lote, "reddit", True, "JSON", len(children), tech_n, stats_desc)
            if r.status_code == 403:
                marcar_reddit_403()
        except Exception:
            pass

    if reddit_directo_disponible():
        try:
            r = SESSION.get(f"https://www.reddit.com/r/{combo}/new/.rss", headers=BROWSER_HEADERS, timeout=8)
            if r.status_code == 200 and "<entry>" in r.text:
                items = parsear_atom_reddit(r.text, subs[0], cfg, stats_descarte=stats_desc)
                tech_n = sum(1 for x in items if x["es_tech"])
                print(f"{C.DIM}[OK] {nombre_lote:<16} (XML nativo) -> {len(items):2d} hiring ({tech_n} tech){C.RESET}", flush=True)
                return items, crear_meta_fuente(nombre_lote, "reddit", True, "XML", len(items) + sum(stats_desc.values()), tech_n, stats_desc)
            if r.status_code == 403:
                marcar_reddit_403()
        except Exception:
            pass

    max_h_mirror = max(24, safe_int(cfg.get("max_horas_post", 18), 18))
    bruto_tot = 0
    ok_subs = 0
    subs_fallidos = []
    fuente_usada = "ArcticShift"

    for sub in subs:
        raw_list = consultar_arctic_shift({"subreddit": sub, "limit": 15, "sort": "desc"})
        if raw_list is None:
            raw_list = consultar_pullpush({"subreddit": sub, "size": 15, "sort": "desc", "sort_type": "created_utc"})
            if raw_list is not None:
                fuente_usada = "PullPush"
        if raw_list is not None:
            ok_subs += 1
            bruto_tot += len(raw_list)
            for d in raw_list:
                it = procesar_child_reddit(d, cfg, fuente_forzada=f"r/{sub}", stats_descarte=stats_desc, max_horas_override=max_h_mirror)
                if it:
                    items.append(it)
        else:
            subs_fallidos.append(sub)

    for sub in subs_fallidos:
        raw_items = consultar_rss2json_seguro(f"https://www.reddit.com/r/{sub}/new/.rss")
        if raw_items is not None:
            ok_subs += 1
            bruto_tot += len(raw_items)
            for raw in raw_items[:12]:
                it = _evaluar_post_reddit(
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
    modo_txt = f"{fuente_usada} {ok_subs}/{len(subs)}" if ok_subs else "ERROR"
    col = C.CYAN if ok_subs == len(subs) else (C.YELLOW if ok_subs else C.RED)
    print(f"{col}[{'OK' if ok_subs else '!'}] {nombre_lote:<16} ({modo_txt:<15} {bruto_tot:2d} raw) -> {len(items):2d} hiring ({tech_n} tech){C.RESET}", flush=True)
    return items, crear_meta_fuente(nombre_lote, "reddit", ok_subs > 0, modo_txt, bruto_tot, tech_n, stats_desc, "" if ok_subs else "Sin respuesta")

def _buscar_global(query_str: str, query_simple: str, etiqueta: str, cfg: dict) -> tuple[list[dict], dict]:
    items: list[dict] = []
    stats_desc: dict[str, int] = {}

    h_oauth = obtener_headers_reddit_oauth()
    if h_oauth:
        try:
            url = f"https://oauth.reddit.com/search?q={quote(query_str)}&sort=new&t=day&limit=25&raw_json=1"
            r = SESSION.get(url, headers=h_oauth, timeout=10)
            if r.status_code == 200:
                children = r.json().get("data", {}).get("children", [])
                for child in children:
                    it = procesar_child_reddit(child.get("data", {}), cfg, es_global=True, stats_descarte=stats_desc)
                    if it and it["es_tech"]:
                        items.append(it)
                print(f"{C.GREEN}[OK] {etiqueta:<16} (OAuth2 {len(children):2d} raw) -> {len(items):2d} joyas tech{C.RESET}", flush=True)
                return items, crear_meta_fuente(etiqueta, "reddit", True, "OAuth2", len(children), len(items), stats_desc)
        except Exception:
            pass

    if reddit_directo_disponible():
        try:
            url = f"https://www.reddit.com/search.json?q={quote(query_str)}&sort=new&t=day&limit=25&raw_json=1"
            r = SESSION.get(url, headers=BROWSER_HEADERS, timeout=8)
            if r.status_code == 200:
                children = r.json().get("data", {}).get("children", [])
                for child in children:
                    it = procesar_child_reddit(child.get("data", {}), cfg, es_global=True, stats_descarte=stats_desc)
                    if it and it["es_tech"]:
                        items.append(it)
                print(f"{C.CYAN}[OK] {etiqueta:<16} (JSON {len(children):2d} raw) -> {len(items):2d} joyas tech{C.RESET}", flush=True)
                return items, crear_meta_fuente(etiqueta, "reddit", True, "JSON", len(children), len(items), stats_desc)
            if r.status_code == 403:
                marcar_reddit_403()
        except Exception:
            pass

    max_h_m = max(1, safe_int(cfg.get("max_horas_post", 12), 12))
    _q_low = (query_simple or "").lower()
    if "automation" in _q_low or etiqueta == "Reddit-Global2":
        _pares_as = [
            ("forhire", "automation"),
            ("slavelabour", "bot"),
        ]
    else:
        _pares_as = [
            ("forhire", "python"),
            ("slavelabour", "script"),
        ]
    _acum_as, _vistos_as, _ok_as = [], set(), 0
    for _sub_as, _kw_as in _pares_as:
        _chunk = consultar_arctic_shift({"subreddit": _sub_as, "title": _kw_as, "limit": 10, "sort": "desc"})
        if _chunk is not None:
            _ok_as += 1
            for _p_as in _chunk:
                _pid = str(_p_as.get("id") or "")
                if _pid and _pid in _vistos_as:
                    continue
                if _pid:
                    _vistos_as.add(_pid)
                _acum_as.append(_p_as)
    raw_list = _acum_as if _ok_as > 0 else None
    modo_g = f"ArcticShift {_ok_as}/{len(_pares_as)}"
    if raw_list is None:
        raw_list = consultar_pullpush({"q": query_simple, "size": 25, "sort": "desc", "sort_type": "created_utc"})
        modo_g = "PullPush"

    if raw_list is not None:
        for d in raw_list:
            it = procesar_child_reddit(d, cfg, es_global=True, stats_descarte=stats_desc, max_horas_override=max_h_m)
            if it and it["es_tech"]:
                items.append(it)
        print(f"{C.CYAN}[OK] {etiqueta:<16} ({modo_g:<11} {len(raw_list):2d} raw) -> {len(items):2d} joyas tech{C.RESET}", flush=True)
        return items, crear_meta_fuente(etiqueta, "reddit", True, modo_g, len(raw_list), len(items), stats_desc)

    print(f"{C.YELLOW}[!] {etiqueta:<16} Sin respuesta temporal{C.RESET}", flush=True)
    return items, crear_meta_fuente(etiqueta, "reddit", False, "ERROR", 0, 0, stats_desc, "Espejos ocupados")

def escanear_reddit(cfg: dict) -> tuple[list[dict], list[dict]]:
    global _REDDIT_DIRECTO_403
    with _REDDIT_LOCK:
        _REDDIT_DIRECTO_403 = False

    ofertas: list[dict] = []
    metas: list[dict] = []
    q_g1 = '("Hiring" OR "looking to hire" OR "will pay") (python OR scraper OR scraping OR selenium OR playwright)'
    q_g2 = '("Hiring" OR "looking to hire" OR "will pay") (telegram OR discord OR bot OR automation OR shopify OR n8n)'

    with ThreadPoolExecutor(max_workers=2) as pool:
        futuros = [pool.submit(_obtener_lote, nom, subs, cfg) for nom, subs in MULTIREDDIT_BATCHES]
        futuros.append(pool.submit(_buscar_global, q_g1, "hiring python", "Reddit-Global1", cfg))
        futuros.append(pool.submit(_buscar_global, q_g2, "hiring automation", "Reddit-Global2", cfg))
        for fut in as_completed(futuros):
            try:
                its, mt = fut.result()
                ofertas.extend(its)
                metas.append(mt)
            except Exception as e:
                metas.append(crear_meta_fuente("Reddit-Err", "reddit", False, "ERR", error=str(e)))
    return ofertas, metas

def diagnosticar_reddit_real() -> str:
    cargar_env(override=True)
    cid = (os.getenv("REDDIT_CLIENT_ID") or "").strip()
    csec = (os.getenv("REDDIT_CLIENT_SECRET") or "").strip()
    if cid and csec:
        h_oa = obtener_headers_reddit_oauth()
        if h_oa:
            try:
                ro = SESSION.get("https://oauth.reddit.com/r/forhire/new?limit=1", headers=h_oa, timeout=6)
                if ro.status_code == 200:
                    return "OK (OAuth2 Oficial en vivo)"
                return f"OAuth2 HTTP {ro.status_code} (revisa ID/Secret en .env)"
            except Exception as e:
                return f"Error OAuth2 ({e})"
        return f"Llaves .env rechazadas ({_OAUTH_LAST_ERR or 'revisa ID/Secret'})"

    if consultar_arctic_shift({"subreddit": "forhire", "limit": 1, "sort": "desc"}) is not None:
        return "OK via Arctic Shift (Sin 403 | tiempo real)"
    if consultar_pullpush({"subreddit": "forhire", "size": 1}) is not None:
        return "OK via PullPush (Respaldo activo)"
    if consultar_rss2json_seguro("https://www.reddit.com/r/forhire/new/.rss") is not None:
        return "OK via RSS-Bridge (Respaldo activo)"
    return "Sin conexion a Reddit ni espejos"