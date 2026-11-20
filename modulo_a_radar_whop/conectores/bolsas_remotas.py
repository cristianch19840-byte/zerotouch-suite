import re
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

from core_ia import C, SESSION, safe_int, safe_float
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

REGEX_CONTRATO = re.compile(r"\b(contract|freelance|part[\s-]*time|gig|consultant|short[\s-]*term|project[\s-]*based)\b", re.IGNORECASE)

def _edad_desde_iso(fecha_str: str | None) -> int | None:
    if not fecha_str:
        return None
    try:
        limpia = str(fecha_str).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(limpia)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - dt).total_seconds() // 60))
    except Exception:
        return None

def _tipo_job(titulo: str, job_type: str = "", texto: str = "") -> str:
    if REGEX_CONTRATO.search(f"{titulo} {job_type} {texto[:300]}"):
        return "freelance"
    return "remoto"

def escanear_remoteok(cfg: dict) -> tuple[list[dict], dict]:
    items: list[dict] = []
    descartes: dict[str, int] = {}
    max_h = max(96, safe_int(cfg.get("max_horas_post", 18), 18))
    esperar_dominio("remoteok.com", 0.4)
    try:
        r = SESSION.get("https://remoteok.com/api", headers=BROWSER_HEADERS, timeout=12)
        if r.status_code != 200:
            err = f"HTTP {r.status_code}"
            print(f"{C.YELLOW}[!] {'RemoteOK':<16} ({err}){C.RESET}", flush=True)
            return items, crear_meta_fuente("RemoteOK", "remoteok", False, err, error=err)

        raw = r.json()
        if not isinstance(raw, list):
            return items, crear_meta_fuente("RemoteOK", "remoteok", False, "JSON invalido", error="No es lista")

        trabajos = [j for j in raw if isinstance(j, dict) and j.get("position")][:45]
        ahora = time.time()
        for j in trabajos:
            epoch = safe_float(j.get("epoch"), 0.0)
            edad_min = max(0, int((ahora - epoch) // 60)) if epoch > 0 else _edad_desde_iso(j.get("date"))
            if edad_min is not None and edad_min > max_h * 60:
                descartes["viejos"] = descartes.get("viejos", 0) + 1
                continue

            titulo = (j.get("position") or "").strip()
            empresa = (j.get("company") or "").strip()
            tags = " ".join(str(t) for t in (j.get("tags") or []))
            desc = limpiar_html(j.get("description", ""), 1400)
            combinado = f"{titulo} {empresa} {tags} {desc}"

            if not titulo or REGEX_SPAM.search(combinado) or not pasa_blacklist_custom(combinado, cfg.get("palabras_extra_blacklist", [])):
                descartes["spam_basura"] = descartes.get("spam_basura", 0) + 1
                continue

            s_min = safe_float(j.get("salary_min"), 0.0)
            s_max = safe_float(j.get("salary_max"), 0.0)
            monto = round((s_min + s_max) / 2.0, 2) if (s_min > 0 and s_max > 0) else max(s_min, s_max)
            pres = f"${int(s_min):,}-${int(s_max):,}/yr" if (s_min > 0 and s_max > 0) else (f"${int(monto):,}" if monto > 0 else "Remoto")
            link = j.get("apply_url") or j.get("url") or f"https://remoteok.com/remote-jobs/{j.get('id', '')}"
            if link.startswith("/"):
                link = "https://remoteok.com" + link

            of = crear_oferta(
                post_id=f"rok_{j.get('id') or link}",
                fuente="RemoteOK",
                plataforma="RemoteOK",
                tipo_trabajo=_tipo_job(titulo, tags, desc),
                titulo=f"{titulo} @ {empresa}" if empresa else titulo,
                texto=f"Tags: {tags}\n{desc}".strip(),
                link=link,
                autor=empresa or "RemoteOK",
                edad_min=edad_min,
                monto_directo=monto,
                presupuesto_txt=pres,
                tags_extra=tags,
                origen="remoteok",
            )
            items.append(of)

        tech_n = sum(1 for x in items if x["es_tech"])
        print(f"{C.GREEN}[OK] {'RemoteOK':<16} (API  {len(trabajos):2d} raw) -> {len(items):2d} vigentes ({tech_n} tech){C.RESET}", flush=True)
        return items, crear_meta_fuente("RemoteOK", "remoteok", True, "API", len(trabajos), tech_n, descartes)
    except Exception as e:
        print(f"{C.YELLOW}[!] {'RemoteOK':<16} ({e}){C.RESET}", flush=True)
        return items, crear_meta_fuente("RemoteOK", "remoteok", False, "ERROR", error=str(e)[:100])

def escanear_remotive(cfg: dict) -> tuple[list[dict], dict]:
    items: list[dict] = []
    descartes: dict[str, int] = {}
    max_h = max(96, safe_int(cfg.get("max_horas_post", 18), 18))
    esperar_dominio("remotive.com", 0.35)
    try:
        r = SESSION.get(
            "https://remotive.com/api/remote-jobs",
            params={"category": "software-dev", "limit": 35},
            headers=BROWSER_HEADERS,
            timeout=12,
        )
        if r.status_code != 200:
            err = f"HTTP {r.status_code}"
            print(f"{C.YELLOW}[!] {'Remotive':<16} ({err}){C.RESET}", flush=True)
            return items, crear_meta_fuente("Remotive", "remotive", False, err, error=err)

        jobs = r.json().get("jobs", [])
        for j in jobs:
            edad_min = _edad_desde_iso(j.get("publication_date"))
            if edad_min is not None and edad_min > max_h * 60:
                descartes["viejos"] = descartes.get("viejos", 0) + 1
                continue

            titulo = (j.get("title") or "").strip()
            empresa = (j.get("company_name") or "").strip()
            tags = " ".join(str(t) for t in (j.get("tags") or []))
            jtype = str(j.get("job_type") or "")
            desc = limpiar_html(j.get("description", ""), 1400)
            combinado = f"{titulo} {empresa} {tags} {desc}"

            if not titulo or REGEX_SPAM.search(combinado) or not pasa_blacklist_custom(combinado, cfg.get("palabras_extra_blacklist", [])):
                descartes["spam_basura"] = descartes.get("spam_basura", 0) + 1
                continue

            sal = (j.get("salary") or "").strip()
            of = crear_oferta(
                post_id=f"rem_{j.get('id') or j.get('url')}",
                fuente="Remotive",
                plataforma="Remotive",
                tipo_trabajo=_tipo_job(titulo, jtype, desc),
                titulo=f"{titulo} @ {empresa}" if empresa else titulo,
                texto=f"Tipo: {jtype} | Tags: {tags}\n{desc}".strip(),
                link=j.get("url", ""),
                autor=empresa or "Remotive",
                edad_min=edad_min,
                presupuesto_txt=sal or jtype or "Remoto",
                tags_extra=f"{tags} {jtype}",
                origen="remotive",
            )
            items.append(of)

        tech_n = sum(1 for x in items if x["es_tech"])
        print(f"{C.GREEN}[OK] {'Remotive':<16} (API  {len(jobs):2d} raw) -> {len(items):2d} vigentes ({tech_n} tech){C.RESET}", flush=True)
        return items, crear_meta_fuente("Remotive", "remotive", True, "API", len(jobs), tech_n, descartes)
    except Exception as e:
        print(f"{C.YELLOW}[!] {'Remotive':<16} ({e}){C.RESET}", flush=True)
        return items, crear_meta_fuente("Remotive", "remotive", False, "ERROR", error=str(e)[:100])

def escanear_jobicy(cfg: dict) -> tuple[list[dict], dict]:
    items: list[dict] = []
    descartes: dict[str, int] = {}
    max_h = max(96, safe_int(cfg.get("max_horas_post", 18), 18))
    esperar_dominio("jobicy.com", 0.35)
    try:
        r = SESSION.get(
            "https://jobicy.com/api/v2/remote-jobs",
            params={"count": 30, "industry": "dev"},
            headers=BROWSER_HEADERS,
            timeout=12,
        )
        if r.status_code != 200:
            err = f"HTTP {r.status_code}"
            print(f"{C.YELLOW}[!] {'Jobicy':<16} ({err}){C.RESET}", flush=True)
            return items, crear_meta_fuente("Jobicy", "jobicy", False, err, error=err)

        jobs = r.json().get("jobs", [])
        for j in jobs:
            edad_min = _edad_desde_iso(j.get("pubDate"))
            if edad_min is not None and edad_min > max_h * 60:
                descartes["viejos"] = descartes.get("viejos", 0) + 1
                continue

            titulo = limpiar_html(j.get("jobTitle", ""), 180)
            empresa = limpiar_html(j.get("companyName", ""), 80)
            jtype = " ".join(j.get("jobType") or []) if isinstance(j.get("jobType"), list) else str(j.get("jobType") or "")
            desc = limpiar_html(j.get("jobDescription") or j.get("jobExcerpt") or "", 1400)
            combinado = f"{titulo} {empresa} {jtype} {desc}"

            if not titulo or REGEX_SPAM.search(combinado) or not pasa_blacklist_custom(combinado, cfg.get("palabras_extra_blacklist", [])):
                descartes["spam_basura"] = descartes.get("spam_basura", 0) + 1
                continue

            s_min = safe_float(j.get("annualSalaryMin"), 0.0)
            s_max = safe_float(j.get("annualSalaryMax"), 0.0)
            monto = round((s_min + s_max) / 2.0, 2) if (s_min > 0 and s_max > 0) else max(s_min, s_max)
            cur = j.get("salaryCurrency") or "USD"
            pres = f"${int(s_min):,}-${int(s_max):,} {cur}" if (s_min > 0 and s_max > 0) else (jtype or "Remoto")

            of = crear_oferta(
                post_id=f"jcy_{j.get('id') or j.get('url')}",
                fuente="Jobicy",
                plataforma="Jobicy",
                tipo_trabajo=_tipo_job(titulo, jtype, desc),
                titulo=f"{titulo} @ {empresa}" if empresa else titulo,
                texto=f"Tipo: {jtype}\n{desc}".strip(),
                link=j.get("url", ""),
                autor=empresa or "Jobicy",
                edad_min=edad_min,
                monto_directo=monto,
                presupuesto_txt=pres,
                tags_extra=f"dev {jtype}",
                origen="jobicy",
            )
            items.append(of)

        tech_n = sum(1 for x in items if x["es_tech"])
        print(f"{C.GREEN}[OK] {'Jobicy':<16} (API  {len(jobs):2d} raw) -> {len(items):2d} vigentes ({tech_n} tech){C.RESET}", flush=True)
        return items, crear_meta_fuente("Jobicy", "jobicy", True, "API", len(jobs), tech_n, descartes)
    except Exception as e:
        print(f"{C.YELLOW}[!] {'Jobicy':<16} ({e}){C.RESET}", flush=True)
        return items, crear_meta_fuente("Jobicy", "jobicy", False, "ERROR", error=str(e)[:100])

def escanear_himalayas(cfg: dict) -> tuple[list[dict], dict]:
    items: list[dict] = []
    descartes: dict[str, int] = {}
    max_h = max(96, safe_int(cfg.get("max_horas_post", 18), 18))
    esperar_dominio("himalayas.app", 0.35)
    try:
        r = SESSION.get(
            "https://himalayas.app/jobs/api",
            params={"limit": 35},
            headers=BROWSER_HEADERS,
            timeout=12,
        )
        if r.status_code != 200:
            err = f"HTTP {r.status_code}"
            print(f"{C.YELLOW}[!] {'Himalayas':<16} ({err}){C.RESET}", flush=True)
            return items, crear_meta_fuente("Himalayas", "himalayas", False, err, error=err)

        jobs = r.json().get("jobs", [])
        ahora = time.time()
        for j in jobs:
            pub = safe_float(j.get("pubDate"), 0.0)
            edad_min = max(0, int((ahora - pub) // 60)) if pub > 0 else None
            if edad_min is not None and edad_min > max_h * 60:
                descartes["viejos"] = descartes.get("viejos", 0) + 1
                continue

            titulo = (j.get("title") or "").strip()
            empresa = (j.get("companyName") or "").strip()
            cats = " ".join(str(c) for c in (j.get("categories") or []))
            jtype = str(j.get("employmentType") or "")
            desc = limpiar_html(j.get("description") or j.get("excerpt") or "", 1400)
            combinado = f"{titulo} {empresa} {cats} {desc}"

            if not titulo or REGEX_SPAM.search(combinado) or not pasa_blacklist_custom(combinado, cfg.get("palabras_extra_blacklist", [])):
                descartes["spam_basura"] = descartes.get("spam_basura", 0) + 1
                continue

            s_min = safe_float(j.get("minSalary"), 0.0)
            s_max = safe_float(j.get("maxSalary"), 0.0)
            monto = round((s_min + s_max) / 2.0, 2) if (s_min > 0 and s_max > 0) else max(s_min, s_max)
            cur = j.get("currency") or "USD"
            pres = f"${int(s_min):,}-${int(s_max):,} {cur}" if (s_min > 0 and s_max > 0) else (jtype or "Remoto")

            of = crear_oferta(
                post_id=f"him_{j.get('guid') or j.get('applicationLink')}",
                fuente="Himalayas",
                plataforma="Himalayas",
                tipo_trabajo=_tipo_job(titulo, jtype, desc),
                titulo=f"{titulo} @ {empresa}" if empresa else titulo,
                texto=f"Categorias: {cats} | Tipo: {jtype}\n{desc}".strip(),
                link=j.get("applicationLink") or j.get("guid") or "",
                autor=empresa or "Himalayas",
                edad_min=edad_min,
                monto_directo=monto,
                presupuesto_txt=pres,
                tags_extra=cats,
                origen="himalayas",
            )
            items.append(of)

        tech_n = sum(1 for x in items if x["es_tech"])
        print(f"{C.GREEN}[OK] {'Himalayas':<16} (API  {len(jobs):2d} raw) -> {len(items):2d} vigentes ({tech_n} tech){C.RESET}", flush=True)
        return items, crear_meta_fuente("Himalayas", "himalayas", True, "API", len(jobs), tech_n, descartes)
    except Exception as e:
        print(f"{C.YELLOW}[!] {'Himalayas':<16} ({e}){C.RESET}", flush=True)
        return items, crear_meta_fuente("Himalayas", "himalayas", False, "ERROR", error=str(e)[:100])

def escanear_workingnomads(cfg: dict) -> tuple[list[dict], dict]:
    items: list[dict] = []
    descartes: dict[str, int] = {}
    max_h = max(96, safe_int(cfg.get("max_horas_post", 18), 18))
    esperar_dominio("www.workingnomads.com", 0.35)
    try:
        r = SESSION.get("https://www.workingnomads.com/api/exposed_jobs/", headers=BROWSER_HEADERS, timeout=14)
        if r.status_code != 200:
            err = f"HTTP {r.status_code}"
            print(f"{C.YELLOW}[!] {'WorkingNomads':<16} ({err}){C.RESET}", flush=True)
            return items, crear_meta_fuente("WorkingNomads", "workingnomads", False, err, error=err)

        raw = r.json()
        jobs = raw[:55] if isinstance(raw, list) else []
        for j in jobs:
            edad_min = _edad_desde_iso(j.get("pub_date"))
            if edad_min is not None and edad_min > max_h * 60:
                descartes["viejos"] = descartes.get("viejos", 0) + 1
                continue

            titulo = (j.get("title") or "").strip()
            empresa = (j.get("company_name") or "").strip()
            tags = str(j.get("tags") or "")
            cat = str(j.get("category_name") or "")
            desc = limpiar_html(j.get("description", ""), 1400)
            combinado = f"{titulo} {empresa} {tags} {cat} {desc}"

            if not titulo or REGEX_SPAM.search(combinado) or not pasa_blacklist_custom(combinado, cfg.get("palabras_extra_blacklist", [])):
                descartes["spam_basura"] = descartes.get("spam_basura", 0) + 1
                continue

            of = crear_oferta(
                post_id=f"wn_{j.get('url') or titulo}",
                fuente="WorkingNomads",
                plataforma="WorkingNomads",
                tipo_trabajo=_tipo_job(titulo, f"{cat} {tags}", desc),
                titulo=f"{titulo} @ {empresa}" if empresa else titulo,
                texto=f"Categoria: {cat} | Tags: {tags}\n{desc}".strip(),
                link=j.get("url", ""),
                autor=empresa or "WorkingNomads",
                edad_min=edad_min,
                presupuesto_txt="Remoto",
                tags_extra=f"{cat} {tags}",
                origen="workingnomads",
            )
            items.append(of)

        tech_n = sum(1 for x in items if x["es_tech"])
        print(f"{C.GREEN}[OK] {'WorkingNomads':<16} (API  {len(jobs):2d} raw) -> {len(items):2d} vigentes ({tech_n} tech){C.RESET}", flush=True)
        return items, crear_meta_fuente("WorkingNomads", "workingnomads", True, "API", len(jobs), tech_n, descartes)
    except Exception as e:
        print(f"{C.YELLOW}[!] {'WorkingNomads':<16} ({e}){C.RESET}", flush=True)
        return items, crear_meta_fuente("WorkingNomads", "workingnomads", False, "ERROR", error=str(e)[:100])

def escanear_arbeitnow(cfg: dict) -> tuple[list[dict], dict]:
    items: list[dict] = []
    descartes: dict[str, int] = {}
    max_h = max(96, safe_int(cfg.get("max_horas_post", 18), 18))
    esperar_dominio("www.arbeitnow.com", 0.35)
    try:
        r = SESSION.get("https://www.arbeitnow.com/api/job-board-api", headers=BROWSER_HEADERS, timeout=12)
        if r.status_code != 200:
            err = f"HTTP {r.status_code}"
            print(f"{C.YELLOW}[!] {'Arbeitnow':<16} ({err}){C.RESET}", flush=True)
            return items, crear_meta_fuente("Arbeitnow", "arbeitnow", False, err, error=err)

        jobs = r.json().get("data", [])[:50]
        ahora = time.time()
        for j in jobs:
            if not j.get("remote"):
                descartes["no_remoto"] = descartes.get("no_remoto", 0) + 1
                continue
            creado = safe_float(j.get("created_at"), 0.0)
            edad_min = max(0, int((ahora - creado) // 60)) if creado > 0 else None
            if edad_min is not None and edad_min > max_h * 60:
                descartes["viejos"] = descartes.get("viejos", 0) + 1
                continue

            titulo = (j.get("title") or "").strip()
            empresa = (j.get("company_name") or "").strip()
            tags = " ".join(str(t) for t in (j.get("tags") or []))
            jtype = " ".join(str(t) for t in (j.get("job_types") or []))
            desc = limpiar_html(j.get("description", ""), 1400)
            combinado = f"{titulo} {empresa} {tags} {desc}"

            if not titulo or REGEX_SPAM.search(combinado) or not pasa_blacklist_custom(combinado, cfg.get("palabras_extra_blacklist", [])):
                descartes["spam_basura"] = descartes.get("spam_basura", 0) + 1
                continue

            of = crear_oferta(
                post_id=f"arb_{j.get('slug') or j.get('url')}",
                fuente="Arbeitnow",
                plataforma="Arbeitnow",
                tipo_trabajo=_tipo_job(titulo, jtype, desc),
                titulo=f"{titulo} @ {empresa}" if empresa else titulo,
                texto=f"Tags: {tags} | Tipo: {jtype}\n{desc}".strip(),
                link=j.get("url", ""),
                autor=empresa or "Arbeitnow",
                edad_min=edad_min,
                presupuesto_txt="Remoto EU/Global",
                tags_extra=tags,
                origen="arbeitnow",
            )
            items.append(of)

        tech_n = sum(1 for x in items if x["es_tech"])
        print(f"{C.GREEN}[OK] {'Arbeitnow':<16} (API  {len(jobs):2d} raw) -> {len(items):2d} remotos ({tech_n} tech){C.RESET}", flush=True)
        return items, crear_meta_fuente("Arbeitnow", "arbeitnow", True, "API", len(jobs), tech_n, descartes)
    except Exception as e:
        print(f"{C.YELLOW}[!] {'Arbeitnow':<16} ({e}){C.RESET}", flush=True)
        return items, crear_meta_fuente("Arbeitnow", "arbeitnow", False, "ERROR", error=str(e)[:100])

MAPA_BOLSAS = {
    "remoteok": escanear_remoteok,
    "remotive": escanear_remotive,
    "jobicy": escanear_jobicy,
    "himalayas": escanear_himalayas,
    "workingnomads": escanear_workingnomads,
    "arbeitnow": escanear_arbeitnow,
}

def escanear_bolsas_remotas(cfg: dict) -> tuple[list[dict], list[dict]]:
    activas = cfg.get("fuentes_activas") or {}
    ofertas: list[dict] = []
    metas: list[dict] = []
    tareas = [fn for clave, fn in MAPA_BOLSAS.items() if activas.get(clave, True)]
    if not tareas:
        return ofertas, metas

    with ThreadPoolExecutor(max_workers=4) as pool:
        futuros = [pool.submit(fn, cfg) for fn in tareas]
        for fut in as_completed(futuros):
            try:
                its, mt = fut.result()
                ofertas.extend(its)
                metas.append(mt)
            except Exception as e:
                metas.append(crear_meta_fuente("Bolsa-Err", "remoteok", False, "ERR", error=str(e)[:100]))
    return ofertas, metas