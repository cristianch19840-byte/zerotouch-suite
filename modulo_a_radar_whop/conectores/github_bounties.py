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
    ahora = datetime.now(timezone.utc)
    desde = (ahora - timedelta(days=10)).strftime("%Y-%m-%d")
    q = quote(f'is:issue is:open (label:bounty OR "algora" OR "opire" OR "polar.sh") created:>={desde} (python OR scraper OR bot OR automation OR api)')
    url = f"https://api.github.com/search/issues?q={q}&sort=created&order=desc&per_page=18"

    esperar_dominio("api.github.com", 0.5)
    try:
        r = SESSION.get(url, headers=GITHUB_HEADERS, timeout=12)
        if r.status_code != 200:
            err = f"HTTP {r.status_code}"
            print(f"{C.YELLOW}[!] {'GitHub Bounties':<16} ({err}){C.RESET}", flush=True)
            return items, crear_meta_fuente("GitHub Bounties", "github_bounties", False, err, error=err)

        crudos = r.json().get("items", [])
        for iss in crudos:
            titulo = (iss.get("title") or "").strip()
            cuerpo = (iss.get("body") or "")[:1400]
            labels_list = [str(lb.get("name", "")) for lb in (iss.get("labels") or [])]
            labels_txt = ", ".join(labels_list)
            combinado = f"{titulo} {labels_txt} {cuerpo}"
            dinero_local = extraer_presupuesto_usd(combinado)
            tiene_label_bounty = any(k in lb.lower() for lb in labels_list for k in ("bounty", "algora", "opire", "reward", "$"))
            tech_score, es_tech = puntuar_relevancia_local(titulo, cuerpo, sub_o_tags=labels_txt)
            if dinero_local <= 0 and not (tiene_label_bounty and es_tech):
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
            comentarios = safe_int(iss.get("comments", 0), 0)
            pref = f"[Bounty ${int(dinero_local)}]" if dinero_local > 0 else "[Bounty]"
            comp_txt = f"💎 {repo_nom} ({edad_min // 60}h | {comentarios} com.)"

            of = crear_oferta(
                post_id=f"gh_bounty_{iss.get('id')}",
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

        print(f"{C.MAGENTA}[OK] {'GitHub Bounties':<16} (API  {len(crudos):2d} raw) -> {len(items):2d} recompensas{C.RESET}", flush=True)
        meta = crear_meta_fuente("GitHub Bounties", "github_bounties", True, "API", len(crudos), len(items))
        with _GH_LOCK:
            _GH_CACHE_TS = time.time()
            _GH_CACHE_RES = (list(items), dict(meta))
        return items, meta
    except Exception as e:
        print(f"{C.YELLOW}[!] Error GitHub Bounties: {e}{C.RESET}", flush=True)
        return items, crear_meta_fuente("GitHub Bounties", "github_bounties", False, "ERROR", error=str(e)[:100])