from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from titan_core.db_engine import TitanDBEngine, obtener_db_engine
from titan_core.event_bus import TitanEventBus, obtener_event_bus


class EstadoLead(str, Enum):
    NUEVO = "nuevo"
    CONTACTADO = "contactado"
    NEGOCIANDO = "negociando"
    GANADO = "ganado"
    DESCARTADO = "descartado"


class PrioridadTarea(str, Enum):
    BAJA = "baja"
    MEDIA = "media"
    ALTA = "alta"
    CRITICA = "critica"


class EstadoTarea(str, Enum):
    PENDIENTE = "pendiente"
    EN_PROGRESO = "en_progreso"
    COMPLETADA = "completada"
    CANCELADA = "cancelada"


class EstadoPropuesta(str, Enum):
    ENVIADA = "enviada"
    VISTA = "vista"
    RESPONDIDA = "respondida"
    ENTREVISTA = "entrevista"
    GANADA = "ganada"
    RECHAZADA = "rechazada"
    SIN_RESPUESTA = "sin_respuesta"


HANDLES_NO_IDENTIFICABLES = {
    "", "none", "null", "unknown", "anon", "anonymous", "[deleted]",
    "automoderator", "github", "hackernews", "freelancer_client",
    "remoteok", "wwr", "weworkremotely", "remotive", "jobicy",
    "himalayas", "workingnomads", "arbeitnow", "rss", "web",
}

ESTADOS_LEAD_VALIDOS = {e.value for e in EstadoLead}
PRIORIDADES_TAREA_VALIDAS = {p.value for p in PrioridadTarea}
ESTADOS_TAREA_VALIDOS = {e.value for e in EstadoTarea}
ESTADOS_PROPUESTA_VALIDOS = {e.value for e in EstadoPropuesta}


def utc_now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def normalizar_handle(handle: str | None) -> str:
    s = (handle or "").strip()
    if s.lower().startswith("u/"):
        s = s[2:]
    elif s.startswith("@"):
        s = s[1:]
    return re.sub(r"\s+", "", s).lower()[:80]


def normalizar_plataforma(plat: str | None) -> str:
    raw = (plat or "").strip()
    if not raw:
        return "General"
    low = raw.lower()
    if low.startswith("r/") or "reddit" in low:
        return "Reddit"
    if "freelancer" in low:
        return "Freelancer"
    if "github" in low:
        return "GitHub"
    if "hackernews" in low or low == "hn":
        return "HackerNews"
    if "remoteok" in low:
        return "RemoteOK"
    if "weworkremotely" in low or low == "wwr":
        return "WWR"
    return raw[:40]


@dataclass(slots=True)
class FichaCliente:
    id: int
    nombre: str
    handle: str = ""
    plataforma_origen: str = ""
    email: str = ""
    canal_contacto: str = ""
    pais: str = ""
    reputacion_score: float = 50.0
    total_facturado_usd: float = 0.0
    proyectos_ganados: int = 0
    es_recurrente: bool = False
    notas: str = ""
    creado_ts: str = ""
    actualizado_ts: str = ""
    leads_totales: int = 0
    propuestas_totales: int = 0
    tareas_pendientes: int = 0

    def to_dict(self) -> dict[str, Any]:
        tier = "VIP" if self.total_facturado_usd >= 500 or self.es_recurrente else (
            "Activo" if self.proyectos_ganados >= 1 else "Prospecto"
        )
        return {
            "id": self.id,
            "nombre": self.nombre,
            "handle": self.handle,
            "plataforma_origen": self.plataforma_origen,
            "email": self.email,
            "canal_contacto": self.canal_contacto,
            "pais": self.pais,
            "reputacion_score": round(self.reputacion_score, 1),
            "total_facturado_usd": round(self.total_facturado_usd, 2),
            "proyectos_ganados": self.proyectos_ganados,
            "es_recurrente": self.es_recurrente,
            "tier": tier,
            "notas": self.notas,
            "creado_ts": self.creado_ts,
            "actualizado_ts": self.actualizado_ts,
            "leads_totales": self.leads_totales,
            "propuestas_totales": self.propuestas_totales,
            "tareas_pendientes": self.tareas_pendientes,
        }

    @classmethod
    def from_row(cls, r: dict[str, Any]) -> FichaCliente:
        return cls(
            id=int(r["id"]),
            nombre=str(r.get("nombre") or "Cliente"),
            handle=str(r.get("handle") or ""),
            plataforma_origen=str(r.get("plataforma_origen") or ""),
            email=str(r.get("email") or ""),
            canal_contacto=str(r.get("canal_contacto") or ""),
            pais=str(r.get("pais") or ""),
            reputacion_score=float(r.get("reputacion_score") or 50.0),
            total_facturado_usd=float(r.get("total_facturado_usd") or 0.0),
            proyectos_ganados=int(r.get("proyectos_ganados") or 0),
            es_recurrente=bool(r.get("es_recurrente") or 0),
            notas=str(r.get("notas") or ""),
            creado_ts=str(r.get("creado_ts") or ""),
            actualizado_ts=str(r.get("actualizado_ts") or ""),
            leads_totales=int(r.get("leads_totales") or 0),
            propuestas_totales=int(r.get("propuestas_totales") or 0),
            tareas_pendientes=int(r.get("tareas_pendientes") or 0),
        )


@dataclass(slots=True)
class PropuestaCRM:
    id: int
    lead_id: int | None
    cliente_id: int | None
    plataforma: str
    variante: str
    template_nombre: str
    precio_cotizado_usd: float
    texto_pitch: str
    estado_respuesta: str
    enviada_ts: str
    respondida_ts: str | None = None
    notas: str = ""
    lead_titulo: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "lead_id": self.lead_id,
            "cliente_id": self.cliente_id,
            "plataforma": self.plataforma,
            "variante": self.variante,
            "template_nombre": self.template_nombre,
            "precio_cotizado_usd": round(self.precio_cotizado_usd, 2),
            "texto_pitch": self.texto_pitch,
            "estado_respuesta": self.estado_respuesta,
            "enviada_ts": self.enviada_ts,
            "respondida_ts": self.respondida_ts,
            "notas": self.notas,
            "lead_titulo": self.lead_titulo,
        }

    @classmethod
    def from_row(cls, r: dict[str, Any]) -> PropuestaCRM:
        return cls(
            id=int(r["id"]),
            lead_id=int(r["lead_id"]) if r.get("lead_id") is not None else None,
            cliente_id=int(r["cliente_id"]) if r.get("cliente_id") is not None else None,
            plataforma=str(r.get("plataforma") or ""),
            variante=str(r.get("variante") or "A"),
            template_nombre=str(r.get("template_nombre") or ""),
            precio_cotizado_usd=float(r.get("precio_cotizado_usd") or 0.0),
            texto_pitch=str(r.get("texto_pitch") or ""),
            estado_respuesta=str(r.get("estado_respuesta") or "enviada"),
            enviada_ts=str(r.get("enviada_ts") or ""),
            respondida_ts=str(r["respondida_ts"]) if r.get("respondida_ts") else None,
            notas=str(r.get("notas") or ""),
            lead_titulo=str(r.get("lead_titulo") or ""),
        )


@dataclass(slots=True)
class TareaCRM:
    id: int
    lead_id: int | None
    cliente_id: int | None
    titulo: str
    descripcion: str = ""
    prioridad: str = "media"
    estado: str = "pendiente"
    vence_ts: str | None = None
    completada_ts: str | None = None
    creado_ts: str = ""
    vencida: bool = False
    lead_titulo: str = ""
    cliente_nombre: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "lead_id": self.lead_id,
            "cliente_id": self.cliente_id,
            "titulo": self.titulo,
            "descripcion": self.descripcion,
            "prioridad": self.prioridad,
            "estado": self.estado,
            "vence_ts": self.vence_ts,
            "completada_ts": self.completada_ts,
            "creado_ts": self.creado_ts,
            "vencida": self.vencida,
            "lead_titulo": self.lead_titulo,
            "cliente_nombre": self.cliente_nombre,
        }

    @classmethod
    def from_row(cls, r: dict[str, Any]) -> TareaCRM:
        vence = str(r["vence_ts"]) if r.get("vence_ts") else None
        est = str(r.get("estado") or "pendiente")
        es_vencida = False
        if vence and est in ("pendiente", "en_progreso"):
            es_vencida = vence < utc_now_str()
        return cls(
            id=int(r["id"]),
            lead_id=int(r["lead_id"]) if r.get("lead_id") is not None else None,
            cliente_id=int(r["cliente_id"]) if r.get("cliente_id") is not None else None,
            titulo=str(r.get("titulo") or ""),
            descripcion=str(r.get("descripcion") or ""),
            prioridad=str(r.get("prioridad") or "media"),
            estado=est,
            vence_ts=vence,
            completada_ts=str(r["completada_ts"]) if r.get("completada_ts") else None,
            creado_ts=str(r.get("creado_ts") or ""),
            vencida=es_vencida,
            lead_titulo=str(r.get("lead_titulo") or ""),
            cliente_nombre=str(r.get("cliente_nombre") or ""),
        )


# ==================== GESTOR EMPRESARIAL DE CLIENTES (LTV, REPUTACION, MERGE, TIMELINE) ====================
class ClienteService:
    """
    Gestion de cartera de clientes:
    - Resolucion automatica y deduplicacion desde leads multi-plataforma
    - Calculo de LTV real, recurrencia y score de reputacion (0..100)
    - Fusion atomica de clientes duplicados reasignando leads/propuestas/tareas/facturas
    - Timeline cronologico unificado por cliente
    """

    def __init__(
        self,
        db: TitanDBEngine | None = None,
        bus: TitanEventBus | None = None,
    ) -> None:
        self.db = db or obtener_db_engine()
        self.bus = bus or obtener_event_bus()
        self._lock = threading.RLock()

    def crear_cliente(
        self,
        nombre: str,
        *,
        handle: str = "",
        plataforma_origen: str = "",
        email: str = "",
        canal_contacto: str = "",
        pais: str = "",
        notas: str = "",
        reputacion_inicial: float = 50.0,
    ) -> FichaCliente:
        nom = str(nombre or "").strip()[:120] or "Cliente"
        h_norm = normalizar_handle(handle)
        plat = normalizar_plataforma(plataforma_origen)
        mail = str(email or "").strip().lower()[:120]
        rep = max(0.0, min(100.0, float(reputacion_inicial)))

        cid = self.db.ejecutar(
            """
            INSERT INTO clientes (
                nombre, handle, plataforma_origen, email, canal_contacto,
                pais, reputacion_score, notas, creado_ts, actualizado_ts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (nom, h_norm, plat, mail, str(canal_contacto or "")[:120], str(pais or "")[:60], rep, str(notas or "")[:600]),
        )
        ficha = self.obtener_cliente(cid)
        assert ficha is not None
        self.bus.publicar(
            "crm.cliente.creado",
            {"cliente_id": cid, "nombre": ficha.nombre, "plataforma": ficha.plataforma_origen},
            origen="crm",
            nivel="info",
        )
        return ficha

    def obtener_cliente(self, cliente_id: int) -> FichaCliente | None:
        row = self.db.consultar_uno(
            """
            SELECT c.*,
                (SELECT COUNT(*) FROM leads l WHERE l.cliente_id = c.id) AS leads_totales,
                (SELECT COUNT(*) FROM propuestas_enviadas p WHERE p.cliente_id = c.id) AS propuestas_totales,
                (SELECT COUNT(*) FROM tareas_crm t WHERE t.cliente_id = c.id AND t.estado IN ('pendiente', 'en_progreso')) AS tareas_pendientes
            FROM clientes c
            WHERE c.id = ?
            """,
            (int(cliente_id),),
        )
        return FichaCliente.from_row(row) if row else None

    def buscar_por_identidad(self, handle: str = "", plataforma: str = "", email: str = "") -> FichaCliente | None:
        mail = str(email or "").strip().lower()
        if mail:
            row = self.db.consultar_uno("SELECT id FROM clientes WHERE lower(email) = ? LIMIT 1", (mail,))
            if row:
                return self.obtener_cliente(int(row["id"]))

        h_norm = normalizar_handle(handle)
        if h_norm and h_norm not in HANDLES_NO_IDENTIFICABLES:
            plat = normalizar_plataforma(plataforma)
            row = self.db.consultar_uno(
                "SELECT id FROM clientes WHERE lower(handle) = ? AND lower(plataforma_origen) = ? LIMIT 1",
                (h_norm, plat.lower()),
            )
            if row:
                return self.obtener_cliente(int(row["id"]))
            # Fallback por handle exacto si vino de otra etiqueta de la misma red
            row2 = self.db.consultar_uno("SELECT id FROM clientes WHERE lower(handle) = ? LIMIT 1", (h_norm,))
            if row2:
                return self.obtener_cliente(int(row2["id"]))
        return None

    def resolver_o_crear_desde_lead(
        self,
        autor: str,
        plataforma: str,
        *,
        email: str = "",
        canal_contacto: str = "",
        confianza_txt: str = "",
    ) -> FichaCliente | None:
        h_norm = normalizar_handle(autor)
        mail = str(email or "").strip().lower()
        if (not h_norm or h_norm in HANDLES_NO_IDENTIFICABLES) and not mail:
            return None

        with self._lock:
            existente = self.buscar_por_identidad(handle=h_norm, plataforma=plataforma, email=mail)
            if existente is not None:
                return existente

            plat = normalizar_plataforma(plataforma)
            nombre_vis = f"u/{h_norm}" if (plat == "Reddit" and h_norm) else (h_norm or mail.split("@")[0])
            rep_ini = 55.0
            low_conf = (confianza_txt or "").lower()
            if "alta" in low_conf or "verificado" in low_conf:
                rep_ini = 68.0
            elif "riesgo" in low_conf or "nueva" in low_conf:
                rep_ini = 38.0

            return self.crear_cliente(
                nombre=nombre_vis,
                handle=h_norm,
                plataforma_origen=plat,
                email=mail,
                canal_contacto=canal_contacto,
                reputacion_inicial=rep_ini,
            )

    def actualizar_cliente(self, cliente_id: int, cambios: dict[str, Any]) -> FichaCliente | None:
        actual = self.obtener_cliente(cliente_id)
        if actual is None:
            return None

        nombre = str(cambios.get("nombre", actual.nombre)).strip()[:120] or actual.nombre
        handle = normalizar_handle(cambios.get("handle", actual.handle))
        plat = normalizar_plataforma(cambios.get("plataforma_origen", actual.plataforma_origen))
        email = str(cambios.get("email", actual.email)).strip().lower()[:120]
        canal = str(cambios.get("canal_contacto", actual.canal_contacto)).strip()[:120]
        pais = str(cambios.get("pais", actual.pais)).strip()[:60]
        notas = str(cambios.get("notas", actual.notas)).strip()[:600]
        rep = max(0.0, min(100.0, float(cambios.get("reputacion_score", actual.reputacion_score))))

        self.db.ejecutar(
            """
            UPDATE clientes
            SET nombre = ?, handle = ?, plataforma_origen = ?, email = ?,
                canal_contacto = ?, pais = ?, reputacion_score = ?, notas = ?,
                actualizado_ts = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (nombre, handle, plat, email, canal, pais, rep, notas, int(cliente_id)),
        )
        return self.obtener_cliente(cliente_id)

    def recalcular_metricas_cliente(self, cliente_id: int) -> FichaCliente | None:
        """Recalcula LTV real, proyectos ganados, recurrencia y score de reputacion (0..100)."""
        cid = int(cliente_id)
        if not self.db.escalar("SELECT 1 FROM clientes WHERE id = ?", (cid,)):
            return None

        row_leads = self.db.consultar_uno(
            """
            SELECT
                COUNT(*) AS tot_leads,
                SUM(CASE WHEN estado = 'ganado' THEN 1 ELSE 0 END) AS ganados,
                SUM(CASE WHEN estado = 'negociando' THEN 1 ELSE 0 END) AS negociando,
                SUM(CASE WHEN estado = 'descartado' THEN 1 ELSE 0 END) AS descartados,
                COALESCE(SUM(CASE WHEN estado = 'ganado' THEN ganancia_usd ELSE 0 END), 0) AS usd_leads,
                AVG(COALESCE(aegis_riesgo, 0)) AS riesgo_prom
            FROM leads
            WHERE cliente_id = ?
            """,
            (cid,),
        ) or {}

        usd_facturas = float(
            self.db.escalar(
                "SELECT COALESCE(SUM(monto_neto_usd), 0) FROM facturas_db WHERE cliente_id = ? AND estado_pago = 'pagada'",
                (cid,),
                default=0.0,
            )
            or 0.0
        )

        row_props = self.db.consultar_uno(
            """
            SELECT
                COUNT(*) AS tot_props,
                SUM(CASE WHEN estado_respuesta IN ('respondida', 'entrevista', 'ganada') THEN 1 ELSE 0 END) AS respondidas,
                SUM(CASE WHEN estado_respuesta = 'sin_respuesta' THEN 1 ELSE 0 END) AS ghosted
            FROM propuestas_enviadas
            WHERE cliente_id = ?
            """,
            (cid,),
        ) or {}

        ganados = int(row_leads.get("ganados") or 0)
        negociando = int(row_leads.get("negociando") or 0)
        descartados = int(row_leads.get("descartados") or 0)
        usd_leads = float(row_leads.get("usd_leads") or 0.0)
        riesgo_prom = float(row_leads.get("riesgo_prom") or 0.0)
        tot_props = int(row_props.get("tot_props") or 0)
        resp_props = int(row_props.get("respondidas") or 0)
        ghosted = int(row_props.get("ghosted") or 0)

        ltv = round(max(usd_leads, usd_facturas), 2)
        es_rec = 1 if (ganados >= 2 or ltv >= 600.0) else 0

        # Formula deterministica de reputacion (0..100)
        rep = 50.0
        rep += min(30.0, ganados * 14.0)
        rep += min(12.0, ltv / 120.0)
        rep += min(8.0, negociando * 4.0)
        if tot_props > 0:
            tasa_resp = resp_props / tot_props
            rep += (tasa_resp - 0.35) * 18.0
        rep -= min(18.0, descartados * 4.5)
        rep -= min(12.0, ghosted * 4.0)
        rep -= min(25.0, riesgo_prom * 0.35)
        rep = round(max(5.0, min(100.0, rep)), 1)

        self.db.ejecutar(
            """
            UPDATE clientes
            SET total_facturado_usd = ?, proyectos_ganados = ?, es_recurrente = ?,
                reputacion_score = ?, actualizado_ts = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (ltv, ganados, es_rec, rep, cid),
        )
        return self.obtener_cliente(cid)

    def vincular_leads_huerfanos(self, limite: int = 500) -> dict[str, int]:
        """Enlaza leads historicos que aun no tienen cliente_id y recalcula metricas."""
        rows = self.db.consultar_todos(
            """
            SELECT id, autor, COALESCE(NULLIF(plataforma,''), fuente) AS plat, confianza
            FROM leads
            WHERE cliente_id IS NULL AND autor IS NOT NULL AND trim(autor) != ''
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, int(limite)),),
        )
        vinculados = 0
        clientes_afectados: set[int] = set()
        for r in rows:
            cli = self.resolver_o_crear_desde_lead(
                autor=str(r.get("autor") or ""),
                plataforma=str(r.get("plat") or ""),
                confianza_txt=str(r.get("confianza") or ""),
            )
            if cli is not None:
                self.db.ejecutar("UPDATE leads SET cliente_id = ? WHERE id = ?", (cli.id, int(r["id"])))
                vinculados += 1
                clientes_afectados.add(cli.id)

        for cid in clientes_afectados:
            self.recalcular_metricas_cliente(cid)

        return {"leads_vinculados": vinculados, "clientes_actualizados": len(clientes_afectados)}

    def fusionar_clientes(self, origen_id: int, destino_id: int) -> FichaCliente | None:
        """Fusion atomica: mueve leads, propuestas, tareas y facturas del cliente origen al destino."""
        oid, did = int(origen_id), int(destino_id)
        if oid == did:
            return self.obtener_cliente(did)

        orig = self.obtener_cliente(oid)
        dest = self.obtener_cliente(did)
        if orig is None or dest is None:
            return None

        email_final = dest.email or orig.email
        canal_final = dest.canal_contacto or orig.canal_contacto
        pais_final = dest.pais or orig.pais
        notas_final = " | ".join(p for p in (dest.notas.strip(), orig.notas.strip()) if p)[:600]

        with self.db.transaccion() as tx:
            tx.execute("UPDATE leads SET cliente_id = ? WHERE cliente_id = ?", (did, oid))
            tx.execute("UPDATE propuestas_enviadas SET cliente_id = ? WHERE cliente_id = ?", (did, oid))
            tx.execute("UPDATE tareas_crm SET cliente_id = ? WHERE cliente_id = ?", (did, oid))
            tx.execute("UPDATE facturas_db SET cliente_id = ? WHERE cliente_id = ?", (did, oid))
            tx.execute(
                "UPDATE clientes SET email = ?, canal_contacto = ?, pais = ?, notas = ?, actualizado_ts = CURRENT_TIMESTAMP WHERE id = ?",
                (email_final, canal_final, pais_final, notas_final, did),
            )
            tx.execute("DELETE FROM clientes WHERE id = ?", (oid,))

        ficha = self.recalcular_metricas_cliente(did)
        self.bus.publicar(
            "crm.cliente.fusionado",
            {"origen_id": oid, "destino_id": did, "ltv": ficha.total_facturado_usd if ficha else 0.0},
            origen="crm",
            nivel="info",
        )
        return ficha

    def eliminar_cliente(self, cliente_id: int) -> bool:
        cid = int(cliente_id)
        with self.db.transaccion() as tx:
            tx.execute("UPDATE leads SET cliente_id = NULL WHERE cliente_id = ?", (cid,))
            cur = tx.execute("DELETE FROM clientes WHERE id = ?", (cid,))
            return (cur.rowcount or 0) > 0

    def listar_clientes(
        self,
        *,
        busqueda: str = "",
        plataforma: str = "",
        solo_recurrentes: bool = False,
        ordenar_por: str = "ltv",
        limite: int = 80,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        filtros: list[str] = ["1=1"]
        params: list[Any] = []
        if busqueda.strip():
            pat = f"%{busqueda.strip().lower()}%"
            filtros.append("(lower(c.nombre) LIKE ? OR lower(c.handle) LIKE ? OR lower(c.email) LIKE ? OR lower(c.notas) LIKE ?)")
            params.extend([pat, pat, pat, pat])
        if plataforma.strip():
            filtros.append("lower(c.plataforma_origen) = ?")
            params.append(plataforma.strip().lower())
        if solo_recurrentes:
            filtros.append("c.es_recurrente = 1")

        orden_sql = {
            "ltv": "c.total_facturado_usd DESC, c.proyectos_ganados DESC, c.reputacion_score DESC",
            "reputacion": "c.reputacion_score DESC, c.total_facturado_usd DESC",
            "proyectos": "c.proyectos_ganados DESC, c.total_facturado_usd DESC",
            "reciente": "c.actualizado_ts DESC, c.id DESC",
        }.get(ordenar_por, "c.total_facturado_usd DESC, c.id DESC")

        params.extend([max(1, min(300, int(limite))), max(0, int(offset))])
        rows = self.db.consultar_todos(
            f"""
            SELECT c.*,
                (SELECT COUNT(*) FROM leads l WHERE l.cliente_id = c.id) AS leads_totales,
                (SELECT COUNT(*) FROM propuestas_enviadas p WHERE p.cliente_id = c.id) AS propuestas_totales,
                (SELECT COUNT(*) FROM tareas_crm t WHERE t.cliente_id = c.id AND t.estado IN ('pendiente', 'en_progreso')) AS tareas_pendientes
            FROM clientes c
            WHERE {' AND '.join(filtros)}
            ORDER BY {orden_sql}
            LIMIT ? OFFSET ?
            """,
            params,
        )
        return [FichaCliente.from_row(r).to_dict() for r in rows]

    def timeline_cliente(self, cliente_id: int, limite: int = 40) -> list[dict[str, Any]]:
        cid = int(cliente_id)
        eventos: list[dict[str, Any]] = []

        for r in self.db.consultar_todos(
            "SELECT id, fecha, titulo, estado, presupuesto, ganancia_usd, score, plataforma FROM leads WHERE cliente_id = ? ORDER BY fecha DESC LIMIT 25",
            (cid,),
        ):
            eventos.append({
                "ts": str(r.get("fecha") or ""),
                "tipo": "lead",
                "ref_id": int(r["id"]),
                "titulo": f"Lead #{r['id']} ({r['estado']}): {str(r.get('titulo') or '')[:90]}",
                "meta": {"score": r.get("score"), "presupuesto": r.get("presupuesto"), "ganancia_usd": r.get("ganancia_usd")},
            })

        for r in self.db.consultar_todos(
            "SELECT id, enviada_ts, variante, precio_cotizado_usd, estado_respuesta, template_nombre FROM propuestas_enviadas WHERE cliente_id = ? ORDER BY enviada_ts DESC LIMIT 25",
            (cid,),
        ):
            eventos.append({
                "ts": str(r.get("enviada_ts") or ""),
                "tipo": "propuesta",
                "ref_id": int(r["id"]),
                "titulo": f"Propuesta #{r['id']} [Var {r['variante']}] -> {r['estado_respuesta']} (${float(r.get('precio_cotizado_usd') or 0):.0f})",
                "meta": {"variante": r.get("variante"), "template": r.get("template_nombre")},
            })

        for r in self.db.consultar_todos(
            "SELECT id, COALESCE(completada_ts, creado_ts) AS ts, titulo, prioridad, estado, vence_ts FROM tareas_crm WHERE cliente_id = ? ORDER BY ts DESC LIMIT 25",
            (cid,),
        ):
            eventos.append({
                "ts": str(r.get("ts") or ""),
                "tipo": "tarea",
                "ref_id": int(r["id"]),
                "titulo": f"Tarea #{r['id']} [{r['prioridad']}/{r['estado']}]: {str(r.get('titulo') or '')[:90]}",
                "meta": {"vence_ts": r.get("vence_ts")},
            })

        for r in self.db.consultar_todos(
            "SELECT id, emitida_ts, numero, concepto, monto_neto_usd, estado_pago FROM facturas_db WHERE cliente_id = ? ORDER BY emitida_ts DESC LIMIT 25",
            (cid,),
        ):
            eventos.append({
                "ts": str(r.get("emitida_ts") or ""),
                "tipo": "factura",
                "ref_id": int(r["id"]),
                "titulo": f"Factura {r['numero']} ({r['estado_pago']}): ${float(r.get('monto_neto_usd') or 0):.2f} USD",
                "meta": {"concepto": r.get("concepto")},
            })

        eventos.sort(key=lambda x: x["ts"], reverse=True)
        return eventos[:max(1, int(limite))]