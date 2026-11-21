from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from modulo_a_radar_whop.conectores.dev_communities import (
    ConectorBountiesPro,
    ConectorDevTo,
    ConectorLobsters,
    ConectorPythonOrg,
)
from modulo_a_radar_whop.conectores.shield_adapter import (
    REGEX_CONTRATO_TAG,
    TitanConnectorAdapter,
    calcular_edad_min,
    construir_oferta_titan,
    parsear_fecha_epoch,
    parsear_feed_xml_pro,
)
from titan_core.db_engine import TitanDBEngine, obtener_db_engine
from titan_core.event_bus import TitanEventBus, obtener_event_bus


@dataclass(frozen=True, slots=True)
class DefinicionFeedPro:
    clave: str
    nombre: str
    url: str
    plataforma: str
    tipo_default: str  # freelance | remoto | bounty
    formato: str = "rss"  # rss | hn_algolia
    tags_extra: tuple[str, ...] = ()


FEEDS_FREELANCE_PRO_DEFECTO: tuple[DefinicionFeedPro, ...] = (
    DefinicionFeedPro(
        clave="pyjobs_rss",
        nombre="PyJobs RSS",
        url="https://www.pyjobs.com/rss/",
        plataforma="PyJobs",
        tipo_default="remoto",
        formato="rss",
        tags_extra=("python",),
    ),
    DefinicionFeedPro(
        clave="remotepython_rss",
        nombre="RemotePython",
        url="https://www.remotepython.com/latest/jobs/feed/",
        plataforma="RemotePython",
        tipo_default="remoto",
        formato="rss",
        tags_extra=("python", "remote"),
    ),
    DefinicionFeedPro(
        clave="authentic_rss",
        nombre="AuthenticJobs",
        url="https://authenticjobs.com/feed/",
        plataforma="AuthenticJobs",
        tipo_default="remoto",
        formato="rss",
    ),
    DefinicionFeedPro(
        clave="hn_freelancer_algolia",
        nombre="HN Freelancer Thread",
        url="https://hn.algolia.com/api/v1/search_by_date",
        plataforma="HackerNews",
        tipo_default="freelance",
        formato="hn_algolia",
        tags_extra=("freelance", "python"),
    ),
)


class ConectorFreelanceFeeds:
    """
    Pack curado de feeds RSS/Atom + HN Freelance Algolia con ejecucion paralela,
    ETag/304 y aislamiento por Circuit Breaker.
    """

    clave_config = "freelance_feeds"
    nombre_fuente = "Freelance Feeds Pro"

    def __init__(
        self,
        adapter: TitanConnectorAdapter | None = None,
        feeds: tuple[DefinicionFeedPro, ...] | list[DefinicionFeedPro] | None = None,
    ) -> None:
        self.adapter = adapter or TitanConnectorAdapter()
        self.feeds = tuple(feeds) if feeds is not None else FEEDS_FREELANCE_PRO_DEFECTO

    def _leer_feed_rss(self, fd: DefinicionFeedPro, cfg: dict[str, Any]) -> tuple[list[dict[str, Any]], int, bool, str, str]:
        resp = self.adapter.get_text(fd.url, timeout=11.0, cache_ttl_seg=240.0, perfil_headers="api")
        if not resp.ok:
            return [], 0, False, "RSS", resp.error or f"HTTP {resp.status_code}"

        items = parsear_feed_xml_pro(resp.texto, fuente_id_prefix=fd.clave, limite=30)
        max_horas = max(72, int(cfg.get("max_horas_post") or 72) * 4)
        ofertas: list[dict[str, Any]] = []

        for it in items:
            edad_min = calcular_edad_min(it.publicado_epoch)
            if edad_min is not None and edad_min > max_horas * 60:
                continue
            comb = f"{it.titulo} {it.descripcion}"
            tipo = "freelance" if REGEX_CONTRATO_TAG.search(comb) else fd.tipo_default
            if cfg.get("solo_freelance_corto") and tipo == "remoto":
                continue

            of = construir_oferta_titan(
                post_id=it.item_id,
                fuente=fd.nombre,
                plataforma=fd.plataforma,
                tipo_trabajo=tipo,
                titulo=it.titulo,
                texto=it.descripcion,
                link=it.link,
                autor=it.autor or fd.plataforma,
                tags=list(it.tags) + list(fd.tags_extra),
                edad_min=edad_min,
                origen="freelance_feeds",
                cfg=cfg,
            )
            if of is not None:
                ofertas.append(of)

        return ofertas, len(items), True, ("RSS-304" if resp.hit_304 else "RSS"), ""

    def _leer_hn_algolia(self, fd: DefinicionFeedPro, cfg: dict[str, Any]) -> tuple[list[dict[str, Any]], int, bool, str, str]:
        corte_epoch = int(time.time() - max(48, int(cfg.get("max_horas_post") or 48) * 3) * 3600)
        data, resp = self.adapter.get_json(
            fd.url,
            params={
                "query": '"SEEKING FREELANCER" python OR automation OR scraper OR bot',
                "tags": "comment",
                "numericFilters": f"created_at_i>{corte_epoch}",
                "hitsPerPage": 25,
            },
            timeout=11.0,
            cache_ttl_seg=180.0,
        )
        if not resp.ok or not isinstance(data, dict):
            return [], 0, False, "Algolia", resp.error or f"HTTP {resp.status_code}"

        hits = data.get("hits") or []
        ofertas: list[dict[str, Any]] = []
        for h in hits:
            if not isinstance(h, dict):
                continue
            oid = str(h.get("objectID") or "")
            raw_txt = str(h.get("comment_text") or "")
            if not oid or not raw_txt or "seeking work" in raw_txt.lower():
                continue
            from modulo_a_radar_whop.conectores.filtros import limpiar_html
            limpio = limpiar_html(raw_txt, 1800)
            primera = limpio.split(".")[0][:120] or f"HN Freelance #{oid}"
            ep = parsear_fecha_epoch(h.get("created_at_i") or h.get("created_at"))
            edad_min = calcular_edad_min(ep)
            of = construir_oferta_titan(
                post_id=f"hnfl_{oid}",
                fuente=fd.nombre,
                plataforma="HackerNews",
                tipo_trabajo="freelance",
                titulo=f"[HN Freelancer] {primera}",
                texto=limpio,
                link=f"https://news.ycombinator.com/item?id={oid}",
                autor=str(h.get("author") or "hackernews"),
                tags=list(fd.tags_extra),
                edad_min=edad_min,
                origen="freelance_feeds",
                cfg=cfg,
            )
            if of is not None:
                ofertas.append(of)

        return ofertas, len(hits), True, ("Algolia-304" if resp.hit_304 else "Algolia"), ""

    def recolectar(self, cfg: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        ofertas_tot: list[dict[str, Any]] = []
        metas: list[dict[str, Any]] = []

        with ThreadPoolExecutor(max_workers=min(4, max(1, len(self.feeds)))) as pool:
            futs = {}
            for fd in self.feeds:
                fn = self._leer_hn_algolia if fd.formato == "hn_algolia" else self._leer_feed_rss
                futs[pool.submit(fn, fd, cfg)] = fd

            for fut in as_completed(futs):
                fd = futs[fut]
                try:
                    ofs, bruto, ok, modo, err = fut.result()
                    ofertas_tot.extend(ofs)
                    metas.append(
                        self.adapter.crear_meta(
                            fd.nombre, self.clave_config, ok, modo, ofs, error=err, bruto_override=bruto,
                        )
                    )
                except Exception as e:
                    metas.append(
                        self.adapter.crear_meta(fd.nombre, self.clave_config, False, fd.formato.upper(), [], error=str(e)[:120])
                    )

        return ofertas_tot, metas


# ==================== ORQUESTADOR CONCURRENTE DE CONECTORES PRO ====================
class OrquestadorConectoresPro:
    """
    Ejecuta los 5 conectores Pro de TITAN-OS v16.0 en paralelo, persiste salud en SQLite
    y publica eventos en TitanEventBus.
    """

    def __init__(
        self,
        adapter: TitanConnectorAdapter | None = None,
        db: TitanDBEngine | None = None,
        bus: TitanEventBus | None = None,
        devto: ConectorDevTo | None = None,
        lobsters: ConectorLobsters | None = None,
        python_org: ConectorPythonOrg | None = None,
        bounties_pro: ConectorBountiesPro | None = None,
        freelance_feeds: ConectorFreelanceFeeds | None = None,
    ) -> None:
        self.adapter = adapter or TitanConnectorAdapter()
        self.db = db or obtener_db_engine()
        self.bus = bus or obtener_event_bus()
        self.devto = devto or ConectorDevTo(adapter=self.adapter)
        self.lobsters = lobsters or ConectorLobsters(adapter=self.adapter)
        self.python_org = python_org or ConectorPythonOrg(adapter=self.adapter)
        self.bounties_pro = bounties_pro or ConectorBountiesPro(adapter=self.adapter)
        self.freelance_feeds = freelance_feeds or ConectorFreelanceFeeds(adapter=self.adapter)

    def _persistir_salud(self, metas: list[dict[str, Any]]) -> None:
        if not metas:
            return
        datos = [
            (
                str(m.get("fuente") or "Pro")[:60],
                str(m.get("clave_config") or "")[:40],
                1 if m.get("ok") else 0,
                str(m.get("modo") or "")[:30],
                int(m.get("bruto") or 0),
                int(m.get("tech") or 0),
                str(m.get("error") or m.get("ultimo_error") or "")[:200],
            )
            for m in metas
        ]
        try:
            self.db.ejecutar_lote(
                """
                INSERT INTO salud_fuentes (fuente, clave_config, ok, modo, bruto, tech, ultimo_error, actualizado_ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(fuente) DO UPDATE SET
                    clave_config = excluded.clave_config,
                    ok = excluded.ok,
                    modo = excluded.modo,
                    bruto = excluded.bruto,
                    tech = excluded.tech,
                    ultimo_error = excluded.ultimo_error,
                    actualizado_ts = CURRENT_TIMESTAMP
                """,
                datos,
            )
        except Exception:
            pass

    def recolectar_todos(
        self,
        cfg: dict[str, Any],
        *,
        persistir_salud: bool = True,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        t0 = time.perf_counter()
        activas = cfg.get("fuentes_activas") or {}
        tareas: list[tuple[str, Any]] = []

        if activas.get("devto", True):
            tareas.append(("devto", self.devto.recolectar))
        if activas.get("lobsters", True):
            tareas.append(("lobsters", self.lobsters.recolectar))
        if activas.get("python_org", True):
            tareas.append(("python_org", self.python_org.recolectar))
        if activas.get("bounties_pro", True):
            tareas.append(("bounties_pro", self.bounties_pro.recolectar))
        if activas.get("freelance_feeds", True):
            tareas.append(("freelance_feeds", self.freelance_feeds.recolectar))

        if not tareas:
            return [], []

        ofertas: list[dict[str, Any]] = []
        metas: list[dict[str, Any]] = []

        with ThreadPoolExecutor(max_workers=min(5, len(tareas))) as pool:
            futs = {pool.submit(fn, cfg): nombre for nombre, fn in tareas}
            for fut in as_completed(futs):
                nom = futs[fut]
                try:
                    ofs, meta_o_lista = fut.result()
                    ofertas.extend(ofs)
                    if isinstance(meta_o_lista, list):
                        metas.extend(meta_o_lista)
                    elif isinstance(meta_o_lista, dict):
                        metas.append(meta_o_lista)
                except Exception as e:
                    metas.append(self.adapter.crear_meta(nom, nom, False, "ERROR", [], error=str(e)[:120]))

        if persistir_salud:
            self._persistir_salud(metas)

        dur_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        self.bus.publicar(
            "radar.conectores_pro.completado",
            {
                "ofertas": len(ofertas),
                "fuentes_ok": sum(1 for m in metas if m.get("ok")),
                "fuentes_total": len(metas),
                "duracion_ms": dur_ms,
            },
            origen="conectores_pro",
            nivel="info",
        )
        return ofertas, metas


def recolectar_conectores_pro(cfg: dict[str, Any], persistir_salud: bool = True) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return OrquestadorConectoresPro().recolectar_todos(cfg, persistir_salud=persistir_salud)