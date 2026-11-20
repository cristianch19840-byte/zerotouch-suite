import re
import time
from urllib.parse import quote

from core_ia import C, SESSION, safe_int, extraer_presupuesto_usd
from modulo_a_radar_whop.conectores.base import (
    esperar_dominio,
    crear_oferta,
    crear_meta_fuente,
)
from modulo_a_radar_whop.conectores.filtros import (
    REGEX_HN_DESCARTE,
    limpiar_html,
    puntuar_relevancia_local,
)

REGEX_HN_CONTRATACION = re.compile(
    r"\b(seeking\s+freelancer|looking\s+to\s+hire|hiring\s+(a\s+)?(freelance|contract|python|developer|engineer)|"
    r"need\s+a\s+(freelancer|contractor|python)|freelance\s+role|contract\s+role|paid\s+project)\b",
    re.IGNORECASE,
)

def escanear_hackernews(cfg: dict) -> tuple[list[dict], dict]:
    items: list[dict] = []
    ahora_ts = time.time()
    hace_14d = int(ahora_ts - 14 * 86400)
    vistos_hn: set[str] = set()
    bruto = 0
    ok_alg = False
    ultimo_err = ""

    for q in ("freelance python", "hiring python", "contract automation python"):
        esperar_dominio("hn.algolia.com", 0.2)
        url = f"https://hn.algolia.com/api/v1/search_by_date?query={quote(q)}&tags=comment&numericFilters=created_at_i>{hace_14d}&hitsPerPage=12"
        try:
            r = SESSION.get(url, timeout=10)
            if r.status_code != 200:
                ultimo_err = f"HTTP {r.status_code}"
                continue
            ok_alg = True
            hits = r.json().get("hits", [])
            bruto += len(hits)
            for hit in hits:
                obj_id = str(hit.get("objectID") or "")
                if not obj_id or obj_id in vistos_hn:
                    continue
                vistos_hn.add(obj_id)

                texto = limpiar_html(hit.get("comment_text", ""))
                if not texto or len(texto) < 60 or REGEX_HN_DESCARTE.search(texto):
                    continue
                if not REGEX_HN_CONTRATACION.search(texto):
                    continue
                tech_score, es_tech = puntuar_relevancia_local("", texto)
                if not es_tech:
                    continue

                creado_i = safe_int(hit.get("created_at_i", int(ahora_ts)), int(ahora_ts))
                edad_min = max(0, int((ahora_ts - creado_i) // 60))
                story_title = hit.get("story_title") or "HN Freelance Thread"
                dinero_local = extraer_presupuesto_usd(texto) or 250.0

                of = crear_oferta(
                    post_id=f"hn_{obj_id}",
                    fuente="HackerNews",
                    plataforma="HackerNews",
                    tipo_trabajo="freelance",
                    titulo=f"[HN] {story_title[:70]}",
                    texto=texto,
                    link=f"https://news.ycombinator.com/item?id={obj_id}",
                    autor="hackernews",
                    edad_min=edad_min,
                    comentarios=0,
                    monto_directo=dinero_local,
                    presupuesto_txt=f"${int(dinero_local)} USD+" if dinero_local else "High-Ticket HN",
                    comp_txt_override=f"🔥 Cliente HN ({edad_min // 60}h)",
                    bonus_extra=2,
                    origen="hn",
                )
                of["es_tech"] = True
                of["tech_score"] = tech_score
                items.append(of)
        except Exception as e:
            ultimo_err = str(e)[:100]

    print(f"{C.BLUE}[OK] {'HackerNews':<16} (API  {bruto:2d} raw) -> {len(items):2d} leads freelance{C.RESET}", flush=True)
    meta = crear_meta_fuente("HackerNews", "hackernews", ok_alg, "API" if ok_alg else "ERROR", bruto, len(items), error=ultimo_err)
    return items, meta