from __future__ import annotations

import hashlib
import html
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from modulo_a_radar_whop.conectores.base import crear_meta_fuente
from modulo_a_radar_whop.conectores.filtros import (
    calcular_competencia,
    detectar_prioridad_tag,
    extraer_dinero_combinado,
    limpiar_html,
    normalizar_titulo,
    pasa_blacklist_custom,
    puntuar_relevancia_local,
    titulo_palabras_limpio,
)
from titan_core.event_bus import TitanEventBus, obtener_event_bus
from titan_core.http_shield import RespuestaHTTP, TitanHTTPShield, obtener_http_shield
from titan_core.telemetry import TitanTelemetry, obtener_telemetry


REGEX_BOUNTY_MONTO = re.compile(
    r"(?:bounty|reward|prize|payout|algora|opire|polar)[^\n\r]{0,28}?\$\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?)(k)?|"
    r"\$\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?)(k)?\s*(?:usd|usdc|usdt)?\s*(?:bounty|reward|prize)",
    re.IGNORECASE,
)
REGEX_REMOTO_TAG = re.compile(
    r"\b(?:remote|worldwide|anywhere|distributed|work\s+from\s+home|wfh|latam|global|async)\b",
    re.IGNORECASE,
)
REGEX_CONTRATO_TAG = re.compile(
    r"\b(?:freelance|contract|contractor|part[\s-]*time|b2b|hourly|fixed[\s-]*price|project[\s-]*based|gig|bounty|consulting)\b",
    re.IGNORECASE,
)
REGEX_MALFORMED_AMP = re.compile(r"&(?!#?\w+;)")


@dataclass(slots=True)
class ItemFeedNormalizado:
    item_id: str
    titulo: str
    link: str
    descripcion: str = ""
    autor: str = ""
    tags: list[str] = field(default_factory=list)
    publicado_epoch: float | None = None
    comentarios: int | None = None
    monto_usd: float = 0.0
    presupuesto_txt: str = ""


def _strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1].lower()
    return tag.lower()


def parsear_fecha_epoch(valor: Any) -> float | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, (int, float)):
        val = float(valor)
        if val > 1e12:
            val /= 1000.0
        return val if val > 946684800.0 else None

    s = str(valor).strip()
    if not s:
        return None
    if s.isdigit():
        return parsear_fecha_epoch(float(s))

    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        pass

    iso_clean = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso_clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d %b %Y %H:%M:%S"):
        try:
            dt = datetime.strptime(s[:19], fmt).replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            pass
    return None


def calcular_edad_min(epoch: float | None) -> int | None:
    if epoch is None:
        return None
    diff = (time.time() - float(epoch)) / 60.0
    if diff < 0:
        return 0
    return int(diff)


def extraer_bounty_usd(titulo: str, texto: str = "", labels: list[str] | None = None) -> float:
    bloque = f"{titulo} {' '.join(labels or [])} {texto[:600]}"
    m = REGEX_BOUNTY_MONTO.search(bloque)
    if m:
        num = m.group(1) or m.group(3)
        suf = m.group(2) or m.group(4)
        if num:
            try:
                v = float(num.replace(",", ""))
                if suf and suf.lower() == "k":
                    v *= 1000.0
                if 5.0 <= v <= 100000.0:
                    return round(v, 2)
            except ValueError:
                pass
    return extraer_dinero_combinado(titulo, texto, 0.0)


def parsear_feed_xml_pro(raw_xml: str, fuente_id_prefix: str = "feed", limite: int = 40) -> list[ItemFeedNormalizado]:
    """
    Parser universal RSS 2.0 + Atom 1.0 tolerante a XML malformado (falla seguro a BeautifulSoup).
    """
    if not raw_xml or len(raw_xml) < 30:
        return []

    items: list[ItemFeedNormalizado] = []
    xml_sano = REGEX_MALFORMED_AMP.sub("&amp;", raw_xml.strip())

    try:
        root = ET.fromstring(xml_sano.encode("utf-8", errors="ignore"))
        nodos = []
        for elem in root.iter():
            t = _strip_ns(elem.tag)
            if t in ("item", "entry"):
                nodos.append(elem)

        for elem in nodos[:limite]:
            titulo = ""
            link = ""
            desc = ""
            autor = ""
            guid = ""
            fecha_raw = ""
            tags: list[str] = []

            for child in elem:
                ct = _strip_ns(child.tag)
                txt = (child.text or "").strip()
                if ct == "title" and not titulo:
                    titulo = html.unescape(txt)
                elif ct == "link":
                    href = (child.attrib.get("href") or "").strip()
                    rel = (child.attrib.get("rel") or "alternate").lower()
                    if href and (not link or rel == "alternate"):
                        link = href
                    elif txt and not link:
                        link = txt
                elif ct in ("description", "summary", "content", "encoded"):
                    if len(txt) > len(desc):
                        desc = txt
                elif ct in ("guid", "id") and not guid:
                    guid = txt
                elif ct in ("pubdate", "published", "updated", "date") and not fecha_raw:
                    fecha_raw = txt
                elif ct in ("author", "creator"):
                    if txt:
                        autor = txt
                    else:
                        for sub in child:
                            if _strip_ns(sub.tag) == "name" and sub.text:
                                autor = sub.text.strip()
                                break
                elif ct == "category":
                    term = (child.attrib.get("term") or txt).strip()
                    if term and term not in tags:
                        tags.append(term[:40])

            if not titulo or not link:
                continue
            uid = guid or link or titulo
            hid = f"{fuente_id_prefix}_{hashlib.blake2b(uid.encode('utf-8', errors='ignore'), digest_size=6).hexdigest()}"
            items.append(
                ItemFeedNormalizado(
                    item_id=hid,
                    titulo=titulo[:240],
                    link=link[:500],
                    descripcion=limpiar_html(desc, 1800),
                    autor=autor[:80],
                    tags=tags[:12],
                    publicado_epoch=parsear_fecha_epoch(fecha_raw),
                )
            )
        if items:
            return items
    except ET.ParseError:
        pass

    # Fallback ultra tolerante con BeautifulSoup para feeds RSS/Atom rotos
    try:
        soup = BeautifulSoup(raw_xml, "html.parser")
        nodos_bs = soup.find_all(["item", "entry"])
        for n in nodos_bs[:limite]:
            tit_el = n.find("title")
            titulo = html.unescape(tit_el.get_text(" ", strip=True)) if tit_el else ""
            lnk_el = n.find("link")
            link = ""
            if lnk_el:
                link = (lnk_el.get("href") or lnk_el.get_text(strip=True) or "").strip()
                if not link and lnk_el.next_sibling:
                    sib = str(lnk_el.next_sibling).strip()
                    if sib.startswith(("http://", "https://")):
                        link = sib
            if not link:
                guid_el = n.find("guid")
                if guid_el and guid_el.get_text(strip=True).startswith(("http://", "https://")):
                    link = guid_el.get_text(strip=True)
            if not titulo or not link:
                continue
            desc_el = n.find(["content:encoded", "content", "description", "summary"])
            desc = limpiar_html(desc_el.get_text(" ", strip=True), 1800) if desc_el else ""
            aut_el = n.find(["dc:creator", "author", "name"])
            autor = aut_el.get_text(" ", strip=True)[:80] if aut_el else ""
            dt_el = n.find(["pubdate", "published", "updated"])
            ep = parsear_fecha_epoch(dt_el.get_text(strip=True)) if dt_el else None
            tags = [c.get("term") or c.get_text(strip=True) for c in n.find_all("category")][:12]
            tags = [t for t in tags if t]
            hid = f"{fuente_id_prefix}_{hashlib.blake2b(link.encode('utf-8', errors='ignore'), digest_size=6).hexdigest()}"
            items.append(
                ItemFeedNormalizado(
                    item_id=hid,
                    titulo=titulo[:240],
                    link=link[:500],
                    descripcion=desc,
                    autor=autor,
                    tags=tags,
                    publicado_epoch=ep,
                )
            )
    except Exception:
        pass
    return items


def construir_oferta_titan(
    *,
    post_id: str,
    fuente: str,
    plataforma: str,
    tipo_trabajo: str,
    titulo: str,
    texto: str,
    link: str,
    autor: str = "",
    tags: list[str] | str = "",
    flair: str = "",
    edad_min: int | None = None,
    comentarios: int | None = None,
    monto_directo_usd: float = 0.0,
    presupuesto_txt: str = "",
    origen: str = "pro",
    es_global: bool = False,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """
    Fabrica estandar de ofertas compatible con motor_zerotouch_v4.py y AEGIS-X v15/v16.
    """
    cfg = cfg or {}
    tit_c = re.sub(r"\s+", " ", (titulo or "")).strip()
    txt_c = (texto or "").strip()
    lnk_c = (link or "").strip()
    if not tit_c or not lnk_c:
        return None

    tags_str = ", ".join(str(t) for t in tags if t) if isinstance(tags, (list, tuple, set)) else str(tags or "")
    combinado = f"{tit_c} {txt_c} {tags_str}".strip()

    extras_bl = cfg.get("palabras_extra_blacklist") or []
    if not pasa_blacklist_custom(combinado, extras_bl):
        return None

    dinero = extraer_dinero_combinado(tit_c, txt_c, monto_directo_usd)
    pres_out = presupuesto_txt.strip()
    if not pres_out:
        if dinero > 0:
            pres_out = f"${int(round(dinero)):,} USD"
        elif tipo_trabajo == "bounty":
            pres_out = "Bounty"
        elif tipo_trabajo == "remoto":
            pres_out = "Remoto"
        else:
            pres_out = "Por definir"

    score_loc, es_tech = puntuar_relevancia_local(tit_c, txt_c, f"{fuente} {tags_str}")
    comp_txt, comp_bonus = calcular_competencia(edad_min, comentarios, etiqueta_fallback=f"🌐 {plataforma}")
    prio_tag = detectar_prioridad_tag(combinado, dinero)

    return {
        "id": str(post_id)[:120],
        "fuente": str(fuente)[:60],
        "plataforma": str(plataforma)[:40],
        "tipo_trabajo": tipo_trabajo if tipo_trabajo in ("freelance", "bounty", "remoto") else "freelance",
        "autor": str(autor or plataforma)[:80],
        "titulo": tit_c[:240],
        "titulo_norm": normalizar_titulo(tit_c),
        "titulo_palabras": titulo_palabras_limpio(tit_c),
        "texto": txt_c[:2600],
        "tags": tags_str[:300],
        "flair": str(flair or "")[:80],
        "link": lnk_c[:500],
        "edad_min": edad_min,
        "comentarios": comentarios,
        "comp_txt": comp_txt,
        "comp_bonus": comp_bonus,
        "dinero_local": dinero,
        "presupuesto_txt": pres_out[:60],
        "prioridad_tag": prio_tag,
        "es_tech": es_tech,
        "score_local": score_loc,
        "origen": origen,
        "es_global": es_global,
    }


class TitanConnectorAdapter:
    """
    Adaptador HTTP unificado para conectores sobre TitanHTTPShield:
    - ETag / 304 condicional automatico
    - Circuit Breaker + Rate Limiter AIMD
    - Telemetria p50/p95 y eventos Pub/Sub
    """

    def __init__(
        self,
        shield: TitanHTTPShield | None = None,
        bus: TitanEventBus | None = None,
        telemetry: TitanTelemetry | None = None,
    ) -> None:
        self.shield = shield or obtener_http_shield()
        self.bus = bus or obtener_event_bus()
        self.telemetry = telemetry or obtener_telemetry()

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 12.0,
        cache_ttl_seg: float = 90.0,
        perfil_headers: str = "api",
    ) -> tuple[Any, RespuestaHTTP]:
        return self.shield.get_json(
            url,
            params=params,
            headers=headers,
            timeout=timeout,
            reintentos=1,
            perfil_headers=perfil_headers,
            cache_ttl_seg=cache_ttl_seg,
            usar_etag=True,
        )

    def get_text(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 12.0,
        cache_ttl_seg: float = 120.0,
        perfil_headers: str = "browser",
    ) -> RespuestaHTTP:
        return self.shield.get(
            url,
            params=params,
            headers=headers,
            timeout=timeout,
            reintentos=1,
            perfil_headers=perfil_headers,
            cache_ttl_seg=cache_ttl_seg,
            usar_etag=True,
        )

    def crear_meta(
        self,
        fuente: str,
        clave_config: str,
        ok: bool,
        modo: str,
        ofertas: list[dict[str, Any]],
        error: str = "",
        bruto_override: int | None = None,
    ) -> dict[str, Any]:
        bruto = len(ofertas) if bruto_override is None else int(bruto_override)
        tech = sum(1 for o in ofertas if o.get("es_tech"))
        return crear_meta_fuente(fuente, clave_config, ok, modo, bruto, tech, error=error)