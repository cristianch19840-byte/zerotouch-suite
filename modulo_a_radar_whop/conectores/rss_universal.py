import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from core_ia import C, SESSION, safe_int
from modulo_a_radar_whop.conectores.base import (
    BROWSER_HEADERS,
    esperar_dominio,
    crear_oferta,
    crear_meta_fuente,
)
from modulo_a_radar_whop.conectores.filtros import (
    REGEX_SPAM,
    limpiar_html,
    pasa_blacklist_custom,
)

WWR_FEEDS = [
    ("WWR-Prog", "https://weworkremotely.com/categories/remote-programming-jobs.rss"),
    ("WWR-BackEnd", "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss"),
]

REGEX_CONTRATO = re.compile(r"\b(contract|freelance|part[\s-]*time|gig|consultant)\b", re.IGNORECASE)

def _parsear_fecha_rss(fecha_txt: str | None) -> int | None:
    if not fecha_txt:
        return None
    s = fecha_txt.strip()
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - dt).total_seconds() // 60))
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - dt).total_seconds() // 60))
    except Exception:
        return None

def parsear_feed_universal(
    xml_text: str,
    nombre_fuente: str,
    plataforma: str,
    cfg: dict,
    max_horas: int = 96,
    tipo_default: str = "remoto",
    descartes: dict | None = None,
) -> tuple[list[dict], int]:
    items: list[dict] = []
    bruto = 0
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items, 0

    nodos = []
    for elem in root.iter():
        tag = elem.tag.split("}", 1)[-1].lower()
        if tag in ("item", "entry"):
            nodos.append(elem)

    for nodo in nodos[:35]:
        bruto += 1
        post_id = titulo = link = desc = fecha_raw = autor = ""
        cats = []
        for ch in nodo:
            tag = ch.tag.split("}", 1)[-1].lower()
            txt = (ch.text or "").strip()
            if tag == "title" and txt:
                titulo = limpiar_html(txt, 200)
            elif tag == "link":
                link = ch.attrib.get("href", "") or txt or link
            elif tag in ("guid", "id") and txt:
                post_id = txt
            elif tag in ("description", "summary", "content", "encoded") and txt and len(txt) > len(desc):
                desc = txt
            elif tag in ("pubdate", "published", "updated", "date") and txt:
                fecha_raw = txt
            elif tag == "category":
                cval = ch.attrib.get("term") or txt
                if cval:
                    cats.append(cval.strip())
            elif tag in ("author", "creator"):
                autor = txt or autor

        edad_min = _parsear_fecha_rss(fecha_raw)
        if edad_min is not None and edad_min > max_horas * 60:
            if descartes is not None:
                descartes["viejos"] = descartes.get("viejos", 0) + 1
            continue

        desc_limpia = limpiar_html(desc, 1400)
        cats_txt = " ".join(cats[:8])
        combinado = f"{titulo} {cats_txt} {desc_limpia}"
        if not titulo or REGEX_SPAM.search(combinado) or not pasa_blacklist_custom(combinado, cfg.get("palabras_extra_blacklist", [])):
            if descartes is not None:
                descartes["spam_basura"] = descartes.get("spam_basura", 0) + 1
            continue

        tipo = "freelance" if REGEX_CONTRATO.search(combinado[:400]) else tipo_default
        of = crear_oferta(
            post_id=f"rss_{post_id or link}",
            fuente=nombre_fuente,
            plataforma=plataforma,
            tipo_trabajo=tipo,
            titulo=titulo,
            texto=f"{('Tags: ' + cats_txt + chr(10)) if cats_txt else ''}{desc_limpia}".strip(),
            link=link,
            autor=autor or plataforma,
            edad_min=edad_min,
            presupuesto_txt="Remoto / RSS",
            tags_extra=cats_txt,
            origen="rss",
        )
        items.append(of)
    return items, bruto

def escanear_weworkremotely(cfg: dict) -> tuple[list[dict], dict]:
    items: list[dict] = []
    vistos: set[str] = set()
    descartes: dict[str, int] = {}
    bruto_tot = 0
    ok_n = 0
    ultimo_err = ""
    max_h = max(96, safe_int(cfg.get("max_horas_post", 18), 18))

    for _, url in WWR_FEEDS:
        esperar_dominio("weworkremotely.com", 0.35)
        try:
            r = SESSION.get(url, headers=BROWSER_HEADERS, timeout=12)
            if r.status_code != 200:
                ultimo_err = f"HTTP {r.status_code}"
                continue
            ok_n += 1
            its, br = parsear_feed_universal(r.text, "WeWorkRemotely", "WWR", cfg, max_horas=max_h, descartes=descartes)
            bruto_tot += br
            for it in its:
                if it["link"] not in vistos:
                    vistos.add(it["link"])
                    items.append(it)
        except Exception as e:
            ultimo_err = str(e)[:90]

    tech_n = sum(1 for x in items if x["es_tech"])
    col = C.CYAN if ok_n else C.YELLOW
    print(f"{col}[{'OK' if ok_n else '!'}] {'WeWorkRemotely':<16} (RSS  {bruto_tot:2d} raw) -> {len(items):2d} vigentes ({tech_n} tech){C.RESET}", flush=True)
    meta = crear_meta_fuente("WeWorkRemotely", "weworkremotely", ok_n > 0, "RSS" if ok_n else (ultimo_err or "ERROR"), bruto_tot, tech_n, descartes, ultimo_err)
    return items, meta

def escanear_rss_custom(cfg: dict) -> tuple[list[dict], list[dict]]:
    feeds = cfg.get("feeds_rss_custom") or []
    items: list[dict] = []
    metas: list[dict] = []
    max_h = max(72, safe_int(cfg.get("max_horas_post", 18), 18))

    for entry in feeds:
        if isinstance(entry, str):
            url = entry.strip()
            nombre = urlparse(url).netloc.replace("www.", "") or "RSS-Custom"
        elif isinstance(entry, dict):
            url = str(entry.get("url") or "").strip()
            nombre = str(entry.get("nombre") or urlparse(url).netloc.replace("www.", "") or "RSS-Custom").strip()
        else:
            continue
        if not url.startswith("http"):
            continue

        dom = urlparse(url).netloc or "rss"
        esperar_dominio(dom, 0.35)
        descartes: dict[str, int] = {}
        try:
            r = SESSION.get(url, headers=BROWSER_HEADERS, timeout=12)
            if r.status_code != 200:
                err = f"HTTP {r.status_code}"
                metas.append(crear_meta_fuente(f"RSS:{nombre}", "rss_custom", False, err, error=err))
                continue
            its, br = parsear_feed_universal(r.text, f"RSS:{nombre}", "RSS", cfg, max_horas=max_h, tipo_default="freelance", descartes=descartes)
            items.extend(its)
            tech_n = sum(1 for x in its if x["es_tech"])
            print(f"{C.CYAN}[OK] {('RSS:' + nombre)[:16]:<16} (RSS  {br:2d} raw) -> {len(its):2d} vigentes ({tech_n} tech){C.RESET}", flush=True)
            metas.append(crear_meta_fuente(f"RSS:{nombre}", "rss_custom", True, "RSS", br, tech_n, descartes))
        except Exception as e:
            metas.append(crear_meta_fuente(f"RSS:{nombre}", "rss_custom", False, "ERROR", error=str(e)[:90]))
    return items, metas