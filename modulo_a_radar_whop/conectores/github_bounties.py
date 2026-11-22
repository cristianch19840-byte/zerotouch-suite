import os
import time
import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from core_ia import C, SESSION, safe_int, extraer_presupuesto_usd
from modulo_a_radar_whop.conectores.base import (
    esperar_dominio,
    crear_oferta,
    crear_meta_fuente,
)
from modulo_a_radar_whop.conectores.filtros import puntuar_relevancia_local

GITHUB_HEADERS = {
    "User-Agent": "ZeroTouchOmni/13.0",
    "Accept": "application/vnd.github+json",
}
if os.getenv("GITHUB_TOKEN"):
    GITHUB_HEADERS["Authorization"] = f"Bearer {os.getenv('GITHUB_TOKEN')}"

_GH_LOCK = threading.Lock()
_GH_CACHE_TS = 0.0
_GH_CACHE_RES: tuple[list[dict], dict] | None = None

def escanear_github_bounties(cfg: dict, forzar: bool = False) -> tuple[list[dict], dict]:
    global _GH_CACHE_TS, _GH_CACHE_RES
    ahora_ts = time.time()
    with _GH_LOCK:
        if not forzar and _GH_CACHE_RES is not None and (ahora_ts - _GH_CACHE_TS) < 180:
            its_c, meta_c = _GH_CACHE_RES
            print(f"{C.MAGENTA}[OK] {'GitHub Bounties':<16} (Cache {meta_c['bruto']:2d} raw) -> {len(its_c):2d} recompensas{C.RESET}", flush=True)
            return list(its_c), dict(meta_c)

    items: list[dict] = []
    vistos_ids: set[int] = set()
    ahora = datetime.now(timezone.utc)
    max_h = max(1, safe_int(cfg.get("max_horas_post", 12), 12))
    max_edad_min = max_h * 60
    desde = (ahora - timedelta(hours=max(24, max_h + 12))).strftime("%Y-%m-%d")

    # 2 consultas simples que GitHub Search API siempre acepta (0 errores HTTP 422)
    queries = [
        f"is:issue is:open label:bounty created:>={desde}",
        f"is:issue is:open algora created:>={desde}",
    ]

    bruto_total = 0
    ok_alguna = False
    ultimo_err = ""

    for q_raw in queries:
        esperar_dominio("api.github.com", 0.5)
        url = f"https://api.github.com/search/issues?q={quote(q_raw)}&sort=created&order=desc&per_page=15"
        try:
            r = SESSION.get(url, headers=GITHUB_HEADERS, timeout=12)
            if r.status_code != 200:
                ultimo_err = f"HTTP {r.status_code}"
                continue
            ok_alguna = True
            crudos = r.json().get("items", [])
            bruto_total += len(crudos)
            for iss in crudos:
                iid = iss.get("id")
                if not iid or iid in vistos_ids:
                    continue
                vistos_ids.add(iid)

                titulo = (iss.get("title") or "").strip()
                cuerpo = (iss.get("body") or "")[:1400]
                labels_list = [str(lb.get("name", "")) for lb in (iss.get("labels") or [])]
                labels_txt = ", ".join(labels_list)
                combinado = f"{titulo} {labels_txt} {cuerpo}"
                dinero_local = extraer_presupuesto_usd(combinado)
                tiene_label_bounty = any(k in lb.lower() for lb in labels_list for k in ("bounty", "algora", "opire", "reward", "$"))
                tech_score, es_tech = puntuar_relevancia_local(titulo, cuerpo, sub_o_tags=labels_txt)

                if not es_tech and dinero_local <= 0:
                    continue
                if dinero_local <= 0 and not tiene_label_bounty:
                    continue

                edad_min = 120
                if iss.get("created_at"):
                    try:
                        dt = datetime.fromisoformat(iss["created_at"].replace("Z", "+00:00"))
                        edad_min = max(0, int((ahora - dt).total_seconds() // 60))
                    except ValueError:
                        pass

                repo_url = iss.get("repository_url") or ""
                repo_nom = "/".join(repo_url.split("/")[-2:]) if "/repos/" in repo_url else "GitHub"
                if edad_min > max_edad_min:
                    continue
                comentarios = safe_int(iss.get("comments", 0), 0)
                pref = f"[Bounty ${int(dinero_local)}]" if dinero_local > 0 else "[Bounty]"
                comp_txt = f"💎 {repo_nom} ({edad_min // 60}h | {comentarios} com.)"

                of = crear_oferta(
                    post_id=f"gh_bounty_{iid}",
                    fuente="GitHub Bounty",
                    plataforma="GitHub",
                    tipo_trabajo="bounty",
                    titulo=f"{pref} {titulo}",
                    texto=f"Repo: {repo_nom}\nLabels: {labels_txt}\n{cuerpo}"[:1500],
                    link=iss.get("html_url", ""),
                    autor="github",
                    edad_min=edad_min,
                    comentarios=comentarios,
                    monto_directo=dinero_local,
                    presupuesto_txt=f"${int(dinero_local)} USD Bounty" if dinero_local > 0 else "Bounty (ver issue)",
                    tags_extra=f"python api {labels_txt}",
                    comp_txt_override=comp_txt,
                    bonus_extra=2 if comentarios <= 2 else 0,
                    origen="github",
                )
                of["es_tech"] = True
                of["tech_score"] = max(6, tech_score)
                items.append(of)
        except Exception as e:
            ultimo_err = str(e)[:90]

    col = C.MAGENTA if ok_alguna else C.YELLOW
    print(f"{col}[{'OK' if ok_alguna else '!'}] {'GitHub Bounties':<16} (API  {bruto_total:2d} raw) -> {len(items):2d} recompensas{C.RESET}", flush=True)
    meta = crear_meta_fuente("GitHub Bounties", "github_bounties", ok_alguna, "API" if ok_alguna else (ultimo_err or "ERROR"), bruto_total, len(items), error=ultimo_err)
    if ok_alguna:
        with _GH_LOCK:
            _GH_CACHE_TS = time.time()
            _GH_CACHE_RES = (list(items), dict(meta))
    return items, meta