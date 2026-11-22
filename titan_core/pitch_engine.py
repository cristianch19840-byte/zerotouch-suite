from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from titan_core.ai_providers import SolicitudIA
from titan_core.ai_router import TitanAIRouter, obtener_ai_router
from titan_core.crm_service import TitanCRMService, obtener_crm_service
from titan_core.db_engine import TitanDBEngine, obtener_db_engine
from titan_core.event_bus import TitanEventBus, obtener_event_bus
from titan_core.pitch_scorer import (
    BanditOptimizer,
    ReportePitchScore,
    auditar_pitch,
    wilson_lower_bound,
)

REGEX_VAR_PITCH = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)(?:\|([^}]+))?\s*\}\}")


# ==================== 8 TEMPLATES PRESET DE ALTA CONVERSION POR PLATAFORMA ====================
PRESETS_PITCH_TEMPLATES: tuple[dict[str, str], ...] = (
    {
        "nombre": "Reddit_Sniper_Direct",
        "plataforma": "reddit",
        "categoria": "Scraping",
        "cuerpo": (
            "Hey {{cliente|there}} — I can build your {{proyecto|Python automation}} using {{stack|Python + Playwright}} "
            "with clean {{entregable|CSV/JSON export and retry handling}}.\n\n"
            "• Delivery: {{tiempo_entrega|within 24-48 hours}}\n"
            "• Quote: {{precio|fixed price after checking the target site}} (50% milestone or pay after working demo)\n"
            "• Clean documented source code + setup guide included ({{github|portfolio on request}})\n\n"
            "Can you share the target URL or a quick sample of the fields you need?"
        ),
    },
    {
        "nombre": "Reddit_Consultative_Value",
        "plataforma": "reddit",
        "categoria": "Bots",
        "cuerpo": (
            "Hi {{cliente|there}}, saw your post about {{proyecto|your automation workflow}}. "
            "The main bottleneck here is usually {{riesgo_tecnico|rate limits, pagination, and silent failures}} — "
            "I solve that cleanly in {{stack|Python (asyncio + SQLite)}} with structured logging and auto-retries.\n\n"
            "I can ship a working demo {{tiempo_entrega|in 24 hours}} so you verify real output before final payment "
            "({{pagos|Binance USDT / PayPal / Wise}}).\n\n"
            "Want me to send a quick 5-row sample or architecture outline first?"
        ),
    },
    {
        "nombre": "Freelancer_2Line_Hook",
        "plataforma": "freelancer",
        "categoria": "Scraping",
        "cuerpo": (
            "I already build production {{stack|Python/Playwright}} scrapers & automation pipelines — "
            "I can deliver {{proyecto|this exact script}} {{tiempo_entrega|within 24-48h}} with clean {{entregable|CSV/JSON output}}.\n\n"
            "Before you award the project, share the target URL and I will run a quick proof-of-concept sample so you verify zero risk.\n\n"
            "What exact columns or triggers are highest priority for v1?"
        ),
    },
    {
        "nombre": "GitHub_Bounty_Engineer",
        "plataforma": "github",
        "categoria": "Bounty",
        "cuerpo": (
            "Taking a look at {{proyecto|this issue}} — my plan to resolve it cleanly:\n"
            "1. Reproduce the edge case with a minimal `pytest` unit test.\n"
            "2. Implement the fix in {{stack|Python}} keeping backward compatibility and clean typing.\n"
            "3. Verify full test suite passes and open a concise PR {{tiempo_entrega|within 24 hours}}.\n\n"
            "Are there any specific formatting/CI constraints I should follow before opening the PR?"
        ),
    },
    {
        "nombre": "HackerNews_Minimalist_Dev",
        "plataforma": "hackernews",
        "categoria": "Backend",
        "cuerpo": (
            "Hi {{cliente|there}} — Python backend/automation engineer ({{stack|Python, FastAPI, Playwright, SQLite/Postgres}}), "
            "UTC-5 (full US EST overlap). Built production scrapers, bots, and ETL pipelines.\n\n"
            "Available to start {{tiempo_entrega|today}} on {{proyecto|your project}} ({{precio|fixed milestone or hourly}}). "
            "GitHub: {{github|available via DM}}.\n\n"
            "Happy to share relevant code samples — what's the best way to sync on scope?"
        ),
    },
    {
        "nombre": "Remote_Contract_B2B",
        "plataforma": "remoto",
        "categoria": "Automation",
        "cuerpo": (
            "Hi {{cliente|team}} — Python Automation & Backend Engineer working remotely from LATAM (UTC-5 / EST overlap). "
            "My core focus matches {{proyecto|this contract}}: {{stack|Python 3.12, Playwright, FastAPI, n8n, SQLite/PostgreSQL, and LLM APIs}}.\n\n"
            "• Ship fast, well-tested PRs with zero hand-holding\n"
            "• Flexible B2B/contractor billing ({{pagos|Wise / PayPal / USDT}})\n"
            "• Available {{tiempo_entrega|immediately}} for trial milestone or ongoing retainer\n\n"
            "Would a quick async scope check or 10-min intro call work for you this week?"
        ),
    },
    {
        "nombre": "Espanol_Cierre_Directo",
        "plataforma": "general",
        "categoria": "Python",
        "cuerpo": (
            "Hola {{cliente|}}, puedo dejarte listo {{proyecto|este proyecto}} en {{stack|Python}} "
            "con {{entregable|exportacion limpia y manejo de errores}} {{tiempo_entrega|en 24-48 horas}}.\n\n"
            "Trabajo sin riesgo para ti: te muestro una demo real funcionando antes del pago final "
            "({{precio|presupuesto fijo a medida}}, {{pagos|Binance USDT / Transferencia / PayPal}}).\n\n"
            "Me pasas el enlace o un ejemplo rapido de los datos que necesitas para confirmarte alcance exacto?"
        ),
    },
    {
        "nombre": "FollowUp_24h_Nudge",
        "plataforma": "general",
        "categoria": "FollowUp",
        "cuerpo": (
            "Quick follow-up on {{proyecto|your Python project}} — still have a slot open {{tiempo_entrega|today}} "
            "if you want a quick working demo before committing.\n\n"
            "Did you already find someone or are you still reviewing options?"
        ),
    },
)


def _cargar_defaults_marca() -> dict[str, str]:
    defaults = {
        "marca": "ZeroTouch Automation Studio",
        "github": "https://github.com",
        "pagos": "Binance USDT / PayPal / Wise",
        "tarifa": "$25/hr",
    }
    try:
        from core_ia import cargar_config
        cfg = cargar_config()
        defaults["marca"] = str(cfg.get("nombre_marca") or defaults["marca"])
        defaults["github"] = str(cfg.get("github_url") or defaults["github"])
        defaults["pagos"] = str(cfg.get("metodos_pago") or defaults["pagos"])
        defaults["tarifa"] = f"${int(float(cfg.get('tarifa_hora_usd') or 25))}/hr"
    except Exception:
        pass
    return defaults


def renderizar_plantilla_texto(cuerpo: str, variables: dict[str, Any] | None = None) -> str:
    ctx = _cargar_defaults_marca()
    if variables:
        for k, v in variables.items():
            if v is not None and str(v).strip() != "":
                ctx[str(k).strip().lower()] = str(v).strip()

    def _rep(m: re.Match[str]) -> str:
        clave = m.group(1).strip().lower()
        fallback = m.group(2) if m.group(2) is not None else ""
        val = ctx.get(clave, "")
        return val if val else fallback

    out = REGEX_VAR_PITCH.sub(_rep, cuerpo or "")
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"Hola\s*,", "Hola,", out)
    return out.strip()


@dataclass(slots=True)
class PitchTemplate:
    id: int
    nombre: str
    plataforma: str
    categoria: str
    cuerpo: str
    usos: int = 0
    respuestas: int = 0
    ganados: int = 0
    creado_ts: str = ""

    def to_dict(self) -> dict[str, Any]:
        tasa_r = round((self.respuestas / max(1, self.usos)) * 100.0, 1) if self.usos > 0 else 0.0
        tasa_g = round((self.ganados / max(1, self.usos)) * 100.0, 1) if self.usos > 0 else 0.0
        rec = min(float(self.usos), 0.55 * self.respuestas + 0.45 * self.ganados) if self.usos > 0 else 0.0
        return {
            "id": self.id,
            "nombre": self.nombre,
            "plataforma": self.plataforma,
            "categoria": self.categoria,
            "cuerpo": self.cuerpo,
            "usos": self.usos,
            "respuestas": self.respuestas,
            "ganados": self.ganados,
            "tasa_respuesta_pct": tasa_r,
            "tasa_cierre_pct": tasa_g,
            "wilson_score": wilson_lower_bound(rec, self.usos),
            "creado_ts": self.creado_ts,
        }

    @classmethod
    def from_row(cls, r: dict[str, Any]) -> PitchTemplate:
        return cls(
            id=int(r["id"]),
            nombre=str(r["nombre"]),
            plataforma=str(r.get("plataforma") or "general"),
            categoria=str(r.get("categoria") or "Python"),
            cuerpo=str(r.get("cuerpo") or ""),
            usos=int(r.get("usos") or 0),
            respuestas=int(r.get("respuestas") or 0),
            ganados=int(r.get("ganados") or 0),
            creado_ts=str(r.get("creado_ts") or ""),
        )


@dataclass(slots=True)
class VariantePitch:
    variante: str  # A | B | C
    enfoque: str
    texto: str
    template_base: str
    precio_sugerido_usd: float
    reporte: ReportePitchScore

    def to_dict(self) -> dict[str, Any]:
        return {
            "variante": self.variante,
            "enfoque": self.enfoque,
            "texto": self.texto,
            "template_base": self.template_base,
            "precio_sugerido_usd": round(self.precio_sugerido_usd, 2),
            "score_0_100": self.reporte.score_0_100,
            "grado": self.reporte.grado,
            "auditoria": self.reporte.to_dict(),
        }


@dataclass(slots=True)
class ResultadoGeneracionPitch:
    ok: bool
    plataforma: str
    lead_id: int | None
    variantes: list[VariantePitch] = field(default_factory=list)
    mejor_variante: str = "A"
    template_recomendado: str = ""
    proveedor_ia: str = "template_local"
    modelo_ia: str = "bandit_fallback"
    auto_refinado: bool = False
    duracion_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "plataforma": self.plataforma,
            "lead_id": self.lead_id,
            "mejor_variante": self.mejor_variante,
            "template_recomendado": self.template_recomendado,
            "proveedor_ia": self.proveedor_ia,
            "modelo_ia": self.modelo_ia,
            "auto_refinado": self.auto_refinado,
            "duracion_ms": round(self.duracion_ms, 2),
            "variantes": [v.to_dict() for v in self.variantes],
        }


class TitanPitchEngine:
    """
    Motor de Propuestas A/B de TITAN-OS v16.0:
    - Biblioteca persistente de templates en SQLite ('pitch_templates') con 8 presets de conversion
    - Selector Multi-Armed Bandit (UCB1 / Thompson Sampling) que prioriza templates que realmente cierran
    - Generador IA multi-variante (A: Direct Sniper, B: Consultative, C: Risk-Reversal) via TitanAIRouter
    - Auditor 0-tokens + Auto-Refinamiento automatico si una variante baja de 72 pts o trae cliches
    - Fallback determinista a templates renderizados si ningun proveedor IA responde
    - Puente directo con TitanCRMService para registrar envios y alimentar el bucle A/B
    """

    SYSTEM_PITCH_GEN = (
        "Eres un closer freelance senior especializado en Python, scraping, bots y automatizacion. "
        "Genera propuestas cortas, especificas y de altisima conversion en JSON valido. "
        "PROHIBIDO usar cliches como 'Dear Sir', 'I hope this finds you well', 'I am very interested', "
        "'I have read your job description carefully', 'passionate', 'kindly', 'delve' o '100% satisfaction'. "
        "Cada propuesta debe: (1) abrir en linea 1 con el entregable/stack concreto, (2) mencionar tiempo estimado real, "
        "(3) incluir reductor de riesgo (demo/muestra/milestone), y (4) cerrar con una pregunta corta de baja friccion."
    )

    def __init__(
        self,
        db: TitanDBEngine | None = None,
        bus: TitanEventBus | None = None,
        ai_router: TitanAIRouter | None = None,
        crm: TitanCRMService | None = None,
        bandit: BanditOptimizer | None = None,
        auto_presets: bool = True,
    ) -> None:
        self.db = db or obtener_db_engine()
        self.bus = bus or obtener_event_bus()
        self.ai_router = ai_router or obtener_ai_router()
        self.crm = crm or obtener_crm_service()
        self.bandit = bandit or BanditOptimizer()
        self._lock = threading.RLock()
        if auto_presets:
            self.instalar_presets()

    # ==================== 1. BIBLIOTECA CRUD DE TEMPLATES ====================
    def instalar_presets(self) -> int:
        creados = 0
        for p in PRESETS_PITCH_TEMPLATES:
            existe = self.db.escalar("SELECT 1 FROM pitch_templates WHERE lower(nombre) = ?", (p["nombre"].lower(),))
            if existe:
                continue
            self.db.ejecutar(
                "INSERT INTO pitch_templates (nombre, plataforma, categoria, cuerpo) VALUES (?, ?, ?, ?)",
                (p["nombre"], p["plataforma"], p["categoria"], p["cuerpo"]),
            )
            creados += 1
        return creados

    def crear_template(
        self,
        nombre: str,
        cuerpo: str,
        *,
        plataforma: str = "general",
        categoria: str = "Python",
    ) -> dict[str, Any]:
        nom = str(nombre or "").strip()[:80]
        if not nom or not str(cuerpo or "").strip():
            raise ValueError("Nombre y cuerpo del template son obligatorios")
        plat = str(plataforma or "general").strip().lower()[:40]
        cat = str(categoria or "Python").strip()[:50]
        tid = self.db.ejecutar(
            "INSERT INTO pitch_templates (nombre, plataforma, categoria, cuerpo) VALUES (?, ?, ?, ?)",
            (nom, plat, cat, str(cuerpo).strip()[:3500]),
        )
        tpl = self.obtener_template(tid)
        assert tpl is not None
        return tpl

    def obtener_template(self, template_id: int) -> dict[str, Any] | None:
        row = self.db.consultar_uno("SELECT * FROM pitch_templates WHERE id = ?", (int(template_id),))
        return PitchTemplate.from_row(row).to_dict() if row else None

    def obtener_template_por_nombre(self, nombre: str) -> dict[str, Any] | None:
        row = self.db.consultar_uno("SELECT * FROM pitch_templates WHERE lower(nombre) = ?", (str(nombre or "").strip().lower(),))
        return PitchTemplate.from_row(row).to_dict() if row else None

    def actualizar_template(self, template_id: int, cambios: dict[str, Any]) -> dict[str, Any] | None:
        prev = self.obtener_template(template_id)
        if prev is None:
            return None
        nom = str(cambios.get("nombre", prev["nombre"])).strip()[:80] or prev["nombre"]
        plat = str(cambios.get("plataforma", prev["plataforma"])).strip().lower()[:40]
        cat = str(cambios.get("categoria", prev["categoria"])).strip()[:50]
        cuerpo = str(cambios.get("cuerpo", prev["cuerpo"])).strip()[:3500] or prev["cuerpo"]
        self.db.ejecutar(
            "UPDATE pitch_templates SET nombre = ?, plataforma = ?, categoria = ?, cuerpo = ? WHERE id = ?",
            (nom, plat, cat, cuerpo, int(template_id)),
        )
        return self.obtener_template(template_id)

    def eliminar_template(self, template_id: int) -> bool:
        return self.db.ejecutar("DELETE FROM pitch_templates WHERE id = ?", (int(template_id),)) > 0

    def listar_templates(
        self,
        *,
        plataforma: str = "",
        categoria: str = "",
        incluir_bandit: bool = True,
    ) -> list[dict[str, Any]]:
        where = ["1=1"]
        params: list[Any] = []
        if plataforma.strip():
            pl = plataforma.strip().lower()
            where.append("(lower(plataforma) = ? OR lower(plataforma) = 'general')")
            params.append(pl)
        if categoria.strip():
            where.append("lower(categoria) = ?")
            params.append(categoria.strip().lower())

        rows = self.db.consultar_todos(
            f"SELECT * FROM pitch_templates WHERE {' AND '.join(where)} ORDER BY ganados DESC, respuestas DESC, id ASC",
            params,
        )
        items = [PitchTemplate.from_row(r).to_dict() for r in rows]
        if incluir_bandit and items:
            brazos = {b.id: b for b in self.bandit.evaluar_brazos(items)}
            for it in items:
                b = brazos.get(it["id"])
                if b:
                    it["bandit_ucb1"] = b.score_ucb1
                    it["bandit_thompson"] = b.score_thompson
                    it["tasa_exito_ponderada_pct"] = b.tasa_exito_ponderada
            items.sort(key=lambda x: (x.get("bandit_ucb1", 0.0), x["wilson_score"]), reverse=True)
        return items

    def recomendar_template(
        self,
        plataforma: str = "general",
        categoria: str = "",
        modo: str = "ucb1",
    ) -> dict[str, Any] | None:
        cands = self.listar_templates(plataforma=plataforma, categoria=categoria, incluir_bandit=False)
        if not cands:
            cands = self.listar_templates(plataforma=plataforma, incluir_bandit=False)
        if not cands:
            cands = self.listar_templates(incluir_bandit=False)
        if not cands:
            return None
        # Priorizar coincidencia exacta de plataforma si hay al menos 2 candidatos especificos
        pl = plataforma.strip().lower()
        exactos = [c for c in cands if c["plataforma"].lower() == pl]
        pool = exactos if exactos else cands
        elegido = self.bandit.seleccionar(pool, modo=modo)
        if elegido is None:
            return pool[0]
        return next((c for c in pool if c["id"] == elegido.id), pool[0])

    def renderizar_template(self, template_id_o_nombre: int | str, variables: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if isinstance(template_id_o_nombre, int) or str(template_id_o_nombre).isdigit():
            tpl = self.obtener_template(int(template_id_o_nombre))
        else:
            tpl = self.obtener_template_por_nombre(str(template_id_o_nombre))
        if tpl is None:
            return None
        texto = renderizar_plantilla_texto(tpl["cuerpo"], variables)
        rep = auditar_pitch(texto, plataforma=tpl["plataforma"], oferta_texto=str((variables or {}).get("oferta_texto") or ""))
        return {
            "template_id": tpl["id"],
            "template_nombre": tpl["nombre"],
            "plataforma": tpl["plataforma"],
            "texto": texto,
            "auditoria": rep.to_dict(),
        }

    # ==================== 2. GENERADOR A/B IA + AUTO-REFINAMIENTO + FALLBACK LOCAL ====================
    def _fallback_variantes_locales(
        self,
        *,
        plataforma: str,
        titulo: str,
        cuerpo: str,
        cliente: str,
        precio: float,
        categoria: str,
        num_variantes: int,
    ) -> tuple[list[VariantePitch], str]:
        cands = self.listar_templates(plataforma=plataforma, incluir_bandit=True)
        if not cands:
            cands = self.listar_templates(incluir_bandit=True)
        seleccion = cands[:max(2, min(3, num_variantes))]
        vars_ctx = {
            "cliente": cliente or "there",
            "proyecto": titulo[:90] or "your Python automation project",
            "stack": "Python 3.12 + Playwright / FastAPI",
            "precio": f"${int(round(precio))} USD" if precio > 0 else "fixed milestone",
            "tiempo_entrega": "within 24-48 hours",
        }
        oferta_full = f"{titulo}\n{cuerpo}"
        letras = ("A", "B", "C")
        enfoques = ("Directo / Sniper", "Consultivo / Valor", "Cero Riesgo / Demo")
        out: list[VariantePitch] = []

        for idx, tpl in enumerate(seleccion):
            txt = renderizar_plantilla_texto(tpl["cuerpo"], vars_ctx)
            rep = auditar_pitch(txt, plataforma=plataforma, oferta_texto=oferta_full)
            out.append(VariantePitch(
                variante=letras[idx],
                enfoque=enfoques[idx],
                texto=txt,
                template_base=tpl["nombre"],
                precio_sugerido_usd=precio,
                reporte=rep,
            ))
        rec_nom = seleccion[0]["nombre"] if seleccion else ""
        return out, rec_nom

    def _auto_refinar_variante(
        self,
        variante: VariantePitch,
        plataforma: str,
        oferta_full: str,
    ) -> tuple[VariantePitch, bool]:
        prompt = (
            f"Reescribe este pitch para {plataforma} corrigiendo TODOS estos problemas:\n"
            f"- Cliches detectados: {', '.join(variante.reporte.cliches_detectados) or 'ninguno'}\n"
            f"- Mejoras obligatorias: {' | '.join(variante.reporte.mejoras_accionables)}\n\n"
            f"OFERTA DEL CLIENTE:\n{oferta_full[:1200]}\n\n"
            f"PITCH ACTUAL (score {variante.reporte.score_0_100}/100):\n{variante.texto}\n\n"
            'Devuelve JSON exacto: {"texto": "pitch mejorado sin cliches y con CTA final"}'
        )
        resp = self.ai_router.ejecutar(
            SolicitudIA(
                prompt=prompt,
                system_prompt=self.SYSTEM_PITCH_GEN,
                temperatura=0.25,
                json_mode=True,
                max_tokens=900,
                timeout_seg=22.0,
                tarea="copiloto",
                usar_cache=False,
            )
        )
        if not resp.ok or not isinstance(resp.json_data, dict):
            return variante, False
        nuevo_txt = str(resp.json_data.get("texto") or "").strip()
        if len(nuevo_txt) < 25:
            return variante, False
        rep_nuevo = auditar_pitch(nuevo_txt, plataforma=plataforma, oferta_texto=oferta_full)
        if rep_nuevo.score_0_100 > variante.reporte.score_0_100:
            variante.texto = nuevo_txt
            variante.reporte = rep_nuevo
            return variante, True
        return variante, False

    def generar_pitch_ab(
        self,
        *,
        lead_id: int | None = None,
        titulo: str = "",
        cuerpo: str = "",
        plataforma: str = "reddit",
        cliente: str = "",
        precio_objetivo_usd: float = 0.0,
        categoria: str = "Python",
        idioma: str = "auto",
        num_variantes: int = 2,
        auto_refinar: bool = True,
        umbral_refino: float = 72.0,
        modo_bandit: str = "ucb1",
    ) -> ResultadoGeneracionPitch:
        t0 = time.perf_counter()

        # Cargar contexto automaticamente desde CRM si pasan lead_id
        if lead_id is not None:
            lead = self.crm.obtener_lead(int(lead_id))
            if lead:
                titulo = titulo or str(lead.get("titulo") or "")
                plataforma = str(lead.get("plataforma") or lead.get("fuente") or plataforma)
                cliente = cliente or str(lead.get("autor") or "")
                categoria = str(lead.get("categoria") or categoria)
                if precio_objetivo_usd <= 0:
                    precio_objetivo_usd = float(lead.get("presupuesto_num") or 0.0)
                if not cuerpo and lead.get("notas"):
                    cuerpo = str(lead["notas"])

        plat_norm = str(plataforma or "general").strip().lower()
        tpl_rec = self.recomendar_template(plataforma=plat_norm, categoria=categoria, modo=modo_bandit)
        tpl_nom = tpl_rec["nombre"] if tpl_rec else "Custom_AI"
        n_var = max(2, min(3, int(num_variantes)))
        oferta_full = f"{titulo}\n{cuerpo}".strip()
        defaults_marca = _cargar_defaults_marca()

        claves_json = '"variante_a": {"enfoque": "Directo Sniper", "precio_usd": 150, "texto": "..."}, "variante_b": {"enfoque": "Consultivo Valor", "precio_usd": 180, "texto": "..."}'
        if n_var >= 3:
            claves_json += ', "variante_c": {"enfoque": "Cero Riesgo / Demo", "precio_usd": 150, "texto": "..."}'

        prompt = (
            f"PLATAFORMA: {plat_norm} | IDIOMA: {idioma} | CLIENTE: {cliente or 'desconocido'}\n"
            f"PRESUPUESTO REFERENCIA: ${precio_objetivo_usd:.0f} USD | MARCA: {defaults_marca['marca']} | PAGOS: {defaults_marca['pagos']}\n"
            f"TEMPLATE GANADOR DE REFERENCIA ({tpl_nom}):\n{(tpl_rec['cuerpo'] if tpl_rec else '')[:600]}\n\n"
            f"OFERTA:\nTitulo: {titulo}\nDetalles: {cuerpo[:1600]}\n\n"
            f"Devuelve UNICAMENTE JSON con esta estructura exacta: {{{claves_json}}}"
        )

        resp_ia = self.ai_router.ejecutar(
            SolicitudIA(
                prompt=prompt,
                system_prompt=self.SYSTEM_PITCH_GEN,
                temperatura=0.35,
                json_mode=True,
                max_tokens=1600,
                timeout_seg=28.0,
                tarea="copiloto",
                usar_cache=True,
                cache_ttl_seg=3600.0,
            )
        )

        variantes: list[VariantePitch] = []
        auto_refinado = False
        prov_usado = "template_local"
        mod_usado = "bandit_fallback"

        if resp_ia.ok and isinstance(resp_ia.json_data, dict):
            prov_usado = resp_ia.proveedor
            mod_usado = resp_ia.modelo
            mapa_vars = (("A", "variante_a", "Directo Sniper"), ("B", "variante_b", "Consultivo Valor"), ("C", "variante_c", "Cero Riesgo / Demo"))
            for letra, k_json, enf_def in mapa_vars[:n_var]:
                bloque = resp_ia.json_data.get(k_json)
                if isinstance(bloque, str) and bloque.strip():
                    txt = bloque.strip()
                    enf = enf_def
                    pr = precio_objetivo_usd
                elif isinstance(bloque, dict) and str(bloque.get("texto") or "").strip():
                    txt = str(bloque["texto"]).strip()
                    enf = str(bloque.get("enfoque") or enf_def)
                    try:
                        pr = float(bloque.get("precio_usd") or precio_objetivo_usd or 0.0)
                    except (TypeError, ValueError):
                        pr = precio_objetivo_usd
                else:
                    continue
                rep = auditar_pitch(txt, plataforma=plat_norm, oferta_texto=oferta_full)
                variantes.append(VariantePitch(
                    variante=letra, enfoque=enf, texto=txt,
                    template_base=tpl_nom, precio_sugerido_usd=pr, reporte=rep,
                ))

            # Auto-refinamiento si la mejor variante no alcanza calidad minima o tiene cliches
            if variantes and auto_refinar:
                variantes.sort(key=lambda v: v.reporte.score_0_100, reverse=True)
                top_v = variantes[0]
                if top_v.reporte.score_0_100 < umbral_refino or len(top_v.reporte.cliches_detectados) >= 2:
                    mejorada, cambio = self._auto_refinar_variante(top_v, plat_norm, oferta_full)
                    variantes[0] = mejorada
                    auto_refinado = cambio

        # Fallback limpio y garantizado si IA no respondio o devolvio vacio
        if not variantes:
            variantes, tpl_nom = self._fallback_variantes_locales(
                plataforma=plat_norm, titulo=titulo, cuerpo=cuerpo,
                cliente=cliente, precio=precio_objetivo_usd, categoria=categoria, num_variantes=n_var,
            )

        variantes.sort(key=lambda v: v.variante)
        mejor = max(variantes, key=lambda v: v.reporte.score_0_100) if variantes else None
        mejor_letra = mejor.variante if mejor else "A"
        dur_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        res = ResultadoGeneracionPitch(
            ok=bool(variantes),
            plataforma=plat_norm,
            lead_id=lead_id,
            variantes=variantes,
            mejor_variante=mejor_letra,
            template_recomendado=tpl_nom,
            proveedor_ia=prov_usado,
            modelo_ia=mod_usado,
            auto_refinado=auto_refinado,
            duracion_ms=dur_ms,
        )

        self.bus.publicar(
            "pitch.generado",
            {
                "lead_id": lead_id,
                "plataforma": plat_norm,
                "mejor_variante": mejor_letra,
                "score_mejor": mejor.reporte.score_0_100 if mejor else 0.0,
                "proveedor": prov_usado,
                "auto_refinado": auto_refinado,
            },
            origen="pitch_engine",
            nivel="ok",
        )
        return res

    def mejorar_pitch_manual(
        self,
        texto_pitch: str,
        *,
        plataforma: str = "general",
        oferta_texto: str = "",
    ) -> dict[str, Any]:
        antes = auditar_pitch(texto_pitch, plataforma=plataforma, oferta_texto=oferta_texto)
        dummy = VariantePitch("A", "Manual", texto_pitch, "Manual", 0.0, antes)
        despues_var, mejoro = self._auto_refinar_variante(dummy, plataforma, oferta_texto)
        return {
            "mejoro": mejoro,
            "score_antes": antes.score_0_100,
            "score_despues": despues_var.reporte.score_0_100,
            "delta_pts": round(despues_var.reporte.score_0_100 - antes.score_0_100, 1),
            "texto_original": texto_pitch,
            "texto_mejorado": despues_var.texto,
            "auditoria_antes": antes.to_dict(),
            "auditoria_despues": despues_var.reporte.to_dict(),
        }

    # ==================== 3. PUENTE CRM & ESTADISTICAS ====================
    def enviar_y_registrar_pitch(
        self,
        *,
        lead_id: int | None,
        texto_pitch: str,
        variante: str = "A",
        precio_cotizado_usd: float = 0.0,
        template_nombre: str = "",
        plataforma: str = "",
        notas: str = "",
    ) -> dict[str, Any]:
        aud = auditar_pitch(texto_pitch, plataforma=plataforma or "general")
        prop = self.crm.registrar_propuesta(
            lead_id=lead_id,
            texto_pitch=texto_pitch,
            variante=variante,
            precio_cotizado_usd=precio_cotizado_usd,
            template_nombre=template_nombre,
            plataforma=plataforma,
            notas=notas or f"Score pitch: {aud.score_0_100}/100 ({aud.grado})",
            marcar_lead_contactado=True,
        )
        prop["auditoria_pitch"] = aud.to_dict()
        self.bus.publicar(
            "pitch.enviado",
            {
                "propuesta_id": prop["id"],
                "lead_id": lead_id,
                "variante": prop["variante"],
                "template": template_nombre,
                "score_pitch": aud.score_0_100,
            },
            origen="pitch_engine",
            nivel="ok",
        )
        return prop

    def estadisticas_engine(self) -> dict[str, Any]:
        templates = self.listar_templates(incluir_bandit=True)
        ab = self.crm.analytics_ab_propuestas()
        return {
            "total_templates": len(templates),
            "top_templates": templates[:8],
            "recomendado_reddit": (self.recomendar_template("reddit") or {}).get("nombre", ""),
            "recomendado_freelancer": (self.recomendar_template("freelancer") or {}).get("nombre", ""),
            "recomendado_github": (self.recomendar_template("github") or {}).get("nombre", ""),
            "analytics_ab": ab,
        }


_PITCH_LOCK = threading.RLock()
_PITCH_SINGLETON: TitanPitchEngine | None = None


def obtener_pitch_engine() -> TitanPitchEngine:
    global _PITCH_SINGLETON
    with _PITCH_LOCK:
        if _PITCH_SINGLETON is None:
            _PITCH_SINGLETON = TitanPitchEngine()
        return _PITCH_SINGLETON