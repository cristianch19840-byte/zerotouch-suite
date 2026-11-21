from __future__ import annotations

import os
import re
from typing import Any

from modulo_a_radar_whop.conectores.shield_adapter import (
    REGEX_CONTRATO_TAG,
    REGEX_REMOTO_TAG,
    TitanConnectorAdapter,
    calcular_edad_min,
    construir_oferta_titan,
    extraer_bounty_usd,
    parsear_fecha_epoch,
    parsear_feed_xml_pro,
)

REGEX_SENAL_COMPRA_DEVTO = re.compile(
    r"\b(?:hiring|looking\s+to\s+hire|freelance\s+(?:job|gig|developer|opportunity)|"
    r"bounty|paid\s+(?:gig|project|task)|we\s+are\s+hiring|we'?re\s+hiring|contract\s+role|"
    r"budget\s*[:$]?\s*\d+|seeking\s+(?:a\s+)?(?:python|backend|automation|freelance))\b",
    re.IGNORECASE,
)
REGEX_FORHIRE_EXCLUIR = re.compile(
    r"(?:\[\s*for\s*hire\s*\]|\bavailable\s+for\s+hire\b|\bhire\s+me\b|\bseeking\s+work\b|\blooking\s+for\s+a\s+job\b)",
    re.IGNORECASE,
)
REGEX_BOUNTY_TITULO = re.compile(
    r"(?:\$\d+|bounty|algora|opire|polar|reward|usdc|usdt)",
    re.IGNORECASE,
)


# ==================== 1. CONECTOR DEV.TO (API REST OFICIAL) ====================
class ConectorDevTo:
    clave_config = "devto"
    nombre_fuente = "Dev.to"

    def __init__(
        self,
        adapter: TitanConnectorAdapter | None = None,
        base_url: str = "https://dev.to/api",
        tags_objetivo: tuple[str, ...] = ("hiring", "freelance", "bounty"),
    ) -> None:
        self.adapter = adapter or TitanConnectorAdapter()
        self.base_url = base_url.rstrip("/")
        self.tags_objetivo = tags_objetivo

    def recolectar(self, cfg: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        ofertas: list[dict[str, Any]] = []
        vistos: set[str] = set()
        max_horas = max(24, int(cfg.get("max_horas_post") or 72) * 3)
        bruto = 0
        ok_alguno = False
        modo = "API"
        ultimo_err = ""

        for tag in self.tags_objetivo:
            url = f"{self.base_url}/articles"
            data, resp = self.adapter.get_json(
                url,
                params={"tag": tag, "per_page": 25, "state": "fresh"},
                timeout=12.0,
                cache_ttl_seg=180.0,
            )
            if not resp.ok or not isinstance(data, list):
                ultimo_err = resp.error or f"HTTP {resp.status_code}"
                continue
            ok_alguno = True
            if resp.hit_304:
                modo = "API-304"

            for art in data:
                if not isinstance(art, dict):
                    continue
                bruto += 1
                aid = str(art.get("id") or "")
                if not aid or aid in vistos:
                    continue
                vistos.add(aid)

                tit = str(art.get("title") or "").strip()
                desc = str(art.get("description") or "").strip()
                tag_list = art.get("tag_list") or art.get("tags") or []
                if isinstance(tag_list, str):
                    tag_list = [x.strip() for x in tag_list.split(",") if x.strip()]
                combinado = f"{tit} {desc} {' '.join(tag_list)}"

                if REGEX_FORHIRE_EXCLUIR.search(combinado):
                    continue
                if tag != "hiring" and not REGEX_SENAL_COMPRA_DEVTO.search(combinado):
                    continue

                ep = parsear_fecha_epoch(art.get("published_at") or art.get("created_at"))
                edad_min = calcular_edad_min(ep)
                if edad_min is not None and edad_min > max_horas * 60:
                    continue

                user = art.get("user") or {}
                autor = str(user.get("username") or user.get("name") or "devto")
                link = str(art.get("url") or art.get("canonical_url") or "")
                coms = int(art.get("comments_count") or 0)
                tipo = "bounty" if ("bounty" in [t.lower() for t in tag_list] or "bounty" in tit.lower()) else (
                    "freelance" if REGEX_CONTRATO_TAG.search(combinado) else "remoto"
                )
                if cfg.get("solo_freelance_corto") and tipo == "remoto":
                    continue

                of = construir_oferta_titan(
                    post_id=f"devto_{aid}",
                    fuente=self.nombre_fuente,
                    plataforma="Dev.to",
                    tipo_trabajo=tipo,
                    titulo=tit,
                    texto=desc,
                    link=link,
                    autor=autor,
                    tags=tag_list,
                    edad_min=edad_min,
                    comentarios=coms,
                    origen="devto",
                    cfg=cfg,
                )
                if of is not None:
                    ofertas.append(of)

        meta = self.adapter.crear_meta(
            self.nombre_fuente, self.clave_config, ok_alguno, modo, ofertas,
            error="" if ok_alguno else ultimo_err, bruto_override=bruto,
        )
        return ofertas, meta


# ==================== 2. CONECTOR LOBSTE.RS (JSON OFICIAL) ====================
class ConectorLobsters:
    clave_config = "lobsters"
    nombre_fuente = "Lobste.rs"

    def __init__(
        self,
        adapter: TitanConnectorAdapter | None = None,
        base_url: str = "https://lobste.rs",
    ) -> None:
        self.adapter = adapter or TitanConnectorAdapter()
        self.base_url = base_url.rstrip("/")

    def recolectar(self, cfg: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        ofertas: list[dict[str, Any]] = []
        vistos: set[str] = set()
        max_horas = max(48, int(cfg.get("max_horas_post") or 72) * 4)
        bruto = 0
        ok_alguno = False
        modo = "JSON"
        ultimo_err = ""

        endpoints = (
            (f"{self.base_url}/t/job.json", True),
            (f"{self.base_url}/t/python.json", False),
        )

        for url, es_job_feed in endpoints:
            data, resp = self.adapter.get_json(url, timeout=12.0, cache_ttl_seg=240.0)
            if not resp.ok or not isinstance(data, list):
                ultimo_err = resp.error or f"HTTP {resp.status_code}"
                continue
            ok_alguno = True
            if resp.hit_304:
                modo = "JSON-304"

            for st in data[:30]:
                if not isinstance(st, dict):
                    continue
                bruto += 1
                sid = str(st.get("short_id") or "")
                if not sid or sid in vistos:
                    continue
                vistos.add(sid)

                tit = str(st.get("title") or "").strip()
                desc = str(st.get("description_plain") or st.get("description") or "").strip()
                tags = [str(t) for t in (st.get("tags") or [])]
                combinado = f"{tit} {desc} {' '.join(tags)}"

                if REGEX_FORHIRE_EXCLUIR.search(combinado):
                    continue
                if not es_job_feed and not REGEX_SENAL_COMPRA_DEVTO.search(combinado):
                    continue

                ep = parsear_fecha_epoch(st.get("created_at"))
                edad_min = calcular_edad_min(ep)
                if edad_min is not None and edad_min > max_horas * 60:
                    continue

                autor_raw = st.get("submitter_user")
                if isinstance(autor_raw, dict):
                    autor = str(autor_raw.get("username") or "lobsters")
                else:
                    autor = str(autor_raw or "lobsters")

                link = str(st.get("comments_url") or st.get("url") or f"{self.base_url}/s/{sid}")
                coms = int(st.get("comment_count") or 0)
                tipo = "freelance" if REGEX_CONTRATO_TAG.search(combinado) else "remoto"
                if cfg.get("solo_freelance_corto") and tipo == "remoto":
                    continue

                of = construir_oferta_titan(
                    post_id=f"lob_{sid}",
                    fuente=self.nombre_fuente,
                    plataforma="Lobsters",
                    tipo_trabajo=tipo,
                    titulo=tit,
                    texto=desc,
                    link=link,
                    autor=autor,
                    tags=tags,
                    edad_min=edad_min,
                    comentarios=coms,
                    origen="lobsters",
                    cfg=cfg,
                )
                if of is not None:
                    ofertas.append(of)

        meta = self.adapter.crear_meta(
            self.nombre_fuente, self.clave_config, ok_alguno, modo, ofertas,
            error="" if ok_alguno else ultimo_err, bruto_override=bruto,
        )
        return ofertas, meta


# ==================== 3. CONECTOR PYTHON.ORG JOB BOARD (RSS OFICIAL) ====================
class ConectorPythonOrg:
    clave_config = "python_org"
    nombre_fuente = "Python.org Jobs"

    def __init__(
        self,
        adapter: TitanConnectorAdapter | None = None,
        feed_url: str = "https://www.python.org/jobs/feed/rss/",
    ) -> None:
        self.adapter = adapter or TitanConnectorAdapter()
        self.feed_url = feed_url

    def recolectar(self, cfg: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        resp = self.adapter.get_text(self.feed_url, timeout=12.0, cache_ttl_seg=300.0, perfil_headers="api")
        if not resp.ok:
            return [], self.adapter.crear_meta(
                self.nombre_fuente, self.clave_config, False, "RSS", [], error=resp.error or f"HTTP {resp.status_code}",
            )

        items = parsear_feed_xml_pro(resp.texto, fuente_id_prefix="pyorg", limite=40)
        ofertas: list[dict[str, Any]] = []
        max_horas = max(72, int(cfg.get("max_horas_post") or 72) * 5)

        for it in items:
            edad_min = calcular_edad_min(it.publicado_epoch)
            if edad_min is not None and edad_min > max_horas * 60:
                continue

            comb = f"{it.titulo} {it.descripcion} {' '.join(it.tags)}"
            # Python.org mezcla puestos presenciales con remotos -> exigimos senal remota o freelance
            es_remoto = bool(REGEX_REMOTO_TAG.search(comb))
            es_contrato = bool(REGEX_CONTRATO_TAG.search(comb))
            if not (es_remoto or es_contrato):
                continue

            tipo = "freelance" if es_contrato else "remoto"
            if cfg.get("solo_freelance_corto") and tipo == "remoto":
                continue

            of = construir_oferta_titan(
                post_id=it.item_id,
                fuente=self.nombre_fuente,
                plataforma="Python.org",
                tipo_trabajo=tipo,
                titulo=it.titulo,
                texto=it.descripcion,
                link=it.link,
                autor=it.autor or "Python.org",
                tags=it.tags + ["python"],
                edad_min=edad_min,
                origen="python_org",
                cfg=cfg,
            )
            if of is not None:
                ofertas.append(of)

        modo = "RSS-304" if resp.hit_304 else "RSS"
        return ofertas, self.adapter.crear_meta(
            self.nombre_fuente, self.clave_config, True, modo, ofertas, bruto_override=len(items),
        )


# ==================== 4. CONECTOR BOUNTIES PRO (ALGORA + OPIRE + POLAR + GITHUB MULTI-QUERY) ====================
class ConectorBountiesPro:
    clave_config = "bounties_pro"
    nombre_fuente = "Bounties Pro"

    QUERIES_GITHUB: tuple[str, ...] = (
        'is:issue is:open no:assignee label:"💎 Bounty" language:python',
        'is:issue is:open no:assignee "algora.io" (python OR scraper OR automation OR bot OR fastapi)',
        'is:issue is:open no:assignee label:bounty (python OR playwright OR telegram OR discord OR scraper)',
        'is:issue is:open no:assignee ("/bounty" OR "opire" OR "polar.sh") (python OR typescript OR automation)',
    )

    def __init__(
        self,
        adapter: TitanConnectorAdapter | None = None,
        github_api_base: str = "https://api.github.com",
    ) -> None:
        self.adapter = adapter or TitanConnectorAdapter()
        self.github_api_base = github_api_base.rstrip("/")

    def _headers_github(self) -> dict[str, str]:
        hdrs = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        tok = (os.getenv("GITHUB_TOKEN") or "").strip()
        if tok:
            hdrs["Authorization"] = f"Bearer {tok}"
        return hdrs

    def recolectar(self, cfg: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        ofertas: list[dict[str, Any]] = []
        vistos: set[str] = set()
        hdrs = self._headers_github()
        bruto = 0
        ok_alguno = False
        modo = "GH-Auth" if "Authorization" in hdrs else "GH-Public"
        ultimo_err = ""

        # Sin token, limitamos a 2 queries mas rentables para no agotar cuota publica de GitHub (10 req/min)
        queries = self.QUERIES_GITHUB if "Authorization" in hdrs else self.QUERIES_GITHUB[:2]

        for q in queries:
            url = f"{self.github_api_base}/search/issues"
            data, resp = self.adapter.get_json(
                url,
                params={"q": q, "sort": "created", "order": "desc", "per_page": 20},
                headers=hdrs,
                timeout=12.0,
                cache_ttl_seg=240.0,
            )
            if not resp.ok or not isinstance(data, dict):
                ultimo_err = resp.error or f"HTTP {resp.status_code}"
                continue
            ok_alguno = True
            if resp.hit_304:
                modo = f"{modo}-304"

            for issue in (data.get("items") or []):
                if not isinstance(issue, dict):
                    continue
                bruto += 1
                # Saltar pull requests o issues ya asignados a otro dev
                if issue.get("pull_request") or issue.get("assignee") or (issue.get("assignees") or []):
                    continue

                iid = str(issue.get("id") or "")
                if not iid or iid in vistos:
                    continue
                vistos.add(iid)

                tit = str(issue.get("title") or "").strip()
                body = str(issue.get("body") or "")[:2000]
                labels = [str(lb.get("name") or "") for lb in (issue.get("labels") or []) if isinstance(lb, dict)]
                if not REGEX_BOUNTY_TITULO.search(f"{tit} {' '.join(labels)} {body[:400]}"):
                    continue

                monto = extraer_bounty_usd(tit, body, labels)
                pres_txt = f"${int(round(monto)):,} Bounty" if monto > 0 else "Bounty Pago"
                ep = parsear_fecha_epoch(issue.get("created_at"))
                edad_min = calcular_edad_min(ep)
                coms = int(issue.get("comments") or 0)
                link = str(issue.get("html_url") or "")
                user = issue.get("user") or {}
                autor = str(user.get("login") or "github")
                repo_url = str(issue.get("repository_url") or "")
                repo_nom = "/".join(repo_url.rstrip("/").split("/")[-2:]) if "/" in repo_url else ""

                titulo_full = f"[Bounty{' $' + str(int(monto)) if monto > 0 else ''}] {tit}"
                if repo_nom and repo_nom.lower() not in titulo_full.lower():
                    titulo_full = f"{titulo_full} ({repo_nom})"

                of = construir_oferta_titan(
                    post_id=f"bpro_{iid}",
                    fuente=self.nombre_fuente,
                    plataforma="GitHub",
                    tipo_trabajo="bounty",
                    titulo=titulo_full,
                    texto=body,
                    link=link,
                    autor=autor,
                    tags=labels + ["bounty"],
                    edad_min=edad_min,
                    comentarios=coms,
                    monto_directo_usd=monto,
                    presupuesto_txt=pres_txt,
                    origen="bounties_pro",
                    cfg=cfg,
                )
                if of is not None:
                    ofertas.append(of)

        meta = self.adapter.crear_meta(
            self.nombre_fuente, self.clave_config, ok_alguno, modo, ofertas,
            error="" if ok_alguno else ultimo_err, bruto_override=bruto,
        )
        return ofertas, meta