import time
from core_ia import C, SESSION, safe_int, safe_float
from modulo_a_radar_whop.conectores.base import (
    BROWSER_HEADERS,
    esperar_dominio,
    crear_oferta,
    crear_meta_fuente,
)
from modulo_a_radar_whop.conectores.filtros import (
    REGEX_SPAM,
    pasa_blacklist_custom,
)

FL_API_URL = "https://www.freelancer.com/api/projects/0.1/projects/active/"

CONSULTAS_FREELANCER = [
    "python scraping selenium playwright",
    "telegram discord bot automation api",
]

def escanear_freelancer(cfg: dict) -> tuple[list[dict], dict]:
    items: list[dict] = []
    vistos_ids: set[int] = set()
    descartes: dict[str, int] = {}
    bruto = 0
    ok_alguna = False
    ultimo_err = ""
    ahora = time.time()
    max_h = max(24, safe_int(cfg.get("max_horas_post", 18), 18))

    for q in CONSULTAS_FREELANCER:
        esperar_dominio("www.freelancer.com", 0.35)
        params = {
            "query": q,
            "or_search_query": "true",
            "limit": 25,
            "compact": "true",
            "full_description": "true",
            "job_details": "true",
            "sort_field": "time_submitted",
        }
        try:
            r = SESSION.get(FL_API_URL, params=params, headers=BROWSER_HEADERS, timeout=12)
            if r.status_code != 200:
                ultimo_err = f"HTTP {r.status_code}"
                continue
            ok_alguna = True
            proyectos = r.json().get("result", {}).get("projects", [])
            bruto += len(proyectos)

            for p in proyectos:
                pid = p.get("id")
                if not pid or pid in vistos_ids:
                    continue
                vistos_ids.add(pid)

                estado = str(p.get("status") or "active").lower()
                if estado not in ("active", "open", ""):
                    descartes["cerrados_borrados"] = descartes.get("cerrados_borrados", 0) + 1
                    continue

                ts_sub = safe_float(p.get("time_submitted"), ahora)
                edad_seg = max(0.0, ahora - ts_sub)
                if edad_seg > max_h * 3600:
                    descartes["viejos"] = descartes.get("viejos", 0) + 1
                    continue
                edad_min = int(edad_seg // 60)

                titulo = (p.get("title") or "").strip()
                desc = (p.get("description") or p.get("preview_description") or "").strip()[:1600]
                jobs = [str(j.get("name", "")) for j in (p.get("jobs") or []) if isinstance(j, dict)]
                skills_txt = ", ".join(jobs[:8])
                combinado = f"{titulo} {desc} {skills_txt}"

                if not titulo or REGEX_SPAM.search(combinado) or not pasa_blacklist_custom(combinado, cfg.get("palabras_extra_blacklist", [])):
                    descartes["spam_basura"] = descartes.get("spam_basura", 0) + 1
                    continue

                budget = p.get("budget") or {}
                cur = p.get("currency") or {}
                rate = safe_float(cur.get("exchange_rate"), 1.0)
                if rate <= 0:
                    rate = 1.0
                b_min = safe_float(budget.get("minimum"), 0.0) * rate
                b_max = safe_float(budget.get("maximum"), 0.0) * rate
                monto_usd = round((b_min + b_max) / 2.0, 2) if (b_min > 0 and b_max > 0) else round(max(b_min, b_max), 2)

                es_hora = str(p.get("type") or "").lower() == "hourly"
                if b_min > 0 and b_max > 0:
                    pres_txt = f"${int(b_min)}-${int(b_max)}{'/hr' if es_hora else ''} USD"
                elif monto_usd > 0:
                    pres_txt = f"${int(monto_usd)}{'/hr' if es_hora else ''} USD"
                else:
                    pres_txt = "Por definir"

                bids = safe_int((p.get("bid_stats") or {}).get("bid_count", 0), 0)
                if edad_min <= 25 and bids <= 5:
                    comp_txt, bonus = f"🎯 SANGRE FRESCA ({edad_min}m | {bids} bids)", 2
                elif bids <= 12:
                    comp_txt, bonus = f"🟢 Baja ({edad_min}m | {bids} bids)", 1
                elif bids <= 25:
                    comp_txt, bonus = f"🟡 Media ({edad_min}m | {bids} bids)", 0
                else:
                    comp_txt, bonus = f"🔴 Alta ({edad_min}m | {bids} bids)", -1

                seo_url = (p.get("seo_url") or "").lstrip("/")
                link = f"https://www.freelancer.com/projects/{seo_url}" if seo_url else f"https://www.freelancer.com/projects/{pid}"
                texto_full = f"Skills: {skills_txt}\n{desc}".strip() if skills_txt else desc

                oferta = crear_oferta(
                    post_id=f"fl_{pid}",
                    fuente="Freelancer.com",
                    plataforma="Freelancer",
                    tipo_trabajo="freelance",
                    titulo=titulo,
                    texto=texto_full,
                    link=link,
                    autor="freelancer_client",
                    edad_min=edad_min,
                    comentarios=bids,
                    monto_directo=monto_usd,
                    presupuesto_txt=pres_txt,
                    tags_extra=skills_txt,
                    comp_txt_override=comp_txt,
                    bonus_extra=bonus,
                    origen="freelancer",
                )
                items.append(oferta)
        except Exception as e:
            ultimo_err = str(e)[:100]

    tech_n = sum(1 for x in items if x["es_tech"])
    col = C.GREEN if ok_alguna else C.RED
    print(f"{col}[{'OK' if ok_alguna else '!'}] {'Freelancer.com':<16} (API  {bruto:2d} raw) -> {len(items):2d} activos ({tech_n} tech){C.RESET}", flush=True)
    meta = crear_meta_fuente("Freelancer.com", "freelancer", ok_alguna, "API" if ok_alguna else (ultimo_err or "ERROR"), bruto, tech_n, descartes, ultimo_err)
    return items, meta