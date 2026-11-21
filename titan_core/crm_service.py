from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from titan_core.crm_clientes import (
    ESTADOS_LEAD_VALIDOS,
    ESTADOS_PROPUESTA_VALIDOS,
    ESTADOS_TAREA_VALIDOS,
    HANDLES_NO_IDENTIFICABLES,
    PRIORIDADES_TAREA_VALIDAS,
    ClienteService,
    PropuestaCRM,
    TareaCRM,
    normalizar_handle,
    normalizar_plataforma,
    utc_now_str,
)
from titan_core.db_engine import TitanDBEngine, obtener_db_engine
from titan_core.event_bus import TitanEventBus, obtener_event_bus


# Pesos probabilisticos por etapa para forecast ponderado del pipeline
PROBABILIDAD_ETAPA: dict[str, float] = {
    "nuevo": 0.08,
    "contactado": 0.24,
    "negociando": 0.58,
    "ganado": 1.00,
    "descartado": 0.00,
}

ESTADOS_PROP_RESPONDIDA = {"respondida", "entrevista", "ganada"}


def _construir_dm_url(plataforma: str, autor: str, titulo: str) -> str:
    if normalizar_plataforma(plataforma) != "Reddit":
        return ""
    h = normalizar_handle(autor)
    if not h or h in HANDLES_NO_IDENTIFICABLES:
        return ""
    return f"https://www.reddit.com/message/compose/?to={quote(h)}&subject={quote('Re: ' + (titulo or '')[:60])}"


class TitanCRMService:
    """
    Servicio CRM Empresarial unificado de TITAN-OS v16.0:
    - Gestion transaccional de Leads (creacion con dedup link, transiciones, batch Kanban, vista 360)
    - Integracion automatica con ClienteService (auto-resolucion, LTV, reputacion, timeline)
    - Seguimiento de Propuestas A/B (conversion real por variante, plataforma y template)
    - Gestor de Tareas y Agenda con deteccion de vencimientos y snooze
    - Pipeline Analytics con forecast ponderado y detector de leads estancados
    - Emision de eventos Pub/Sub para disparar WorkflowEngine IFTTT y SSE en vivo
    """

    def __init__(
        self,
        db: TitanDBEngine | None = None,
        bus: TitanEventBus | None = None,
        clientes: ClienteService | None = None,
    ) -> None:
        self.db = db or obtener_db_engine()
        self.bus = bus or obtener_event_bus()
        self.clientes = clientes or ClienteService(db=self.db, bus=self.bus)

    # ==================== 1. LEADS (CRUD, BATCH, VISTA 360, ESTANCADOS) ====================
    def crear_lead(
        self,
        *,
        fuente: str,
        titulo: str,
        link: str = "",
        plataforma: str = "",
        tipo_trabajo: str = "freelance",
        autor: str = "",
        categoria: str = "Tech",
        presupuesto: str = "Por definir",
        presupuesto_num: float = 0.0,
        score: int = 6,
        competencia: str = "",
        confianza: str = "",
        prioridad_tag: str = "",
        notas: str = "",
        aegis_score: float = 0.0,
        aegis_riesgo: float = 0.0,
        horas_estimadas: str = "",
        tarifa_eff_usd: float = 0.0,
        auto_vincular_cliente: bool = True,
    ) -> dict[str, Any]:
        lk = (link or "").strip()
        if lk:
            existente = self.db.consultar_uno("SELECT id FROM leads WHERE link = ? LIMIT 1", (lk,))
            if existente:
                ficha_ex = self.obtener_lead(int(existente["id"]))
                assert ficha_ex is not None
                ficha_ex["creado_nuevo"] = False
                return ficha_ex

        plat = normalizar_plataforma(plataforma or fuente)
        tipo = str(tipo_trabajo or "freelance").strip().lower()
        if tipo not in ("freelance", "bounty", "remoto"):
            tipo = "freelance"

        cliente_id: int | None = None
        if auto_vincular_cliente and autor:
            cli = self.clientes.resolver_o_crear_desde_lead(autor, plat, confianza_txt=confianza)
            if cli is not None:
                cliente_id = cli.id

        lid = self.db.ejecutar(
            """
            INSERT INTO leads (
                fuente, plataforma, tipo_trabajo, autor, titulo, categoria,
                presupuesto, presupuesto_num, score, competencia, confianza,
                prioridad_tag, link, estado, ganancia_usd, notas, cliente_id,
                aegis_score, aegis_riesgo, horas_estimadas, tarifa_eff_usd, actualizado_ts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'nuevo', 0, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                str(fuente or plat)[:80],
                plat,
                tipo,
                str(autor or "")[:100],
                str(titulo or "")[:240],
                str(categoria or "Tech")[:60],
                str(presupuesto or "Por definir")[:80],
                round(float(presupuesto_num or 0.0), 2),
                max(1, min(10, int(score or 6))),
                str(competencia or "")[:120],
                str(confianza or "")[:140],
                str(prioridad_tag or "")[:120],
                lk[:500],
                str(notas or "")[:500],
                cliente_id,
                round(float(aegis_score or 0.0), 1),
                round(float(aegis_riesgo or 0.0), 1),
                str(horas_estimadas or "")[:40],
                round(float(tarifa_eff_usd or 0.0), 2),
            ),
        )

        lead = self.obtener_lead(lid)
        assert lead is not None
        lead["creado_nuevo"] = True

        self.bus.publicar(
            "crm.lead.nuevo",
            {
                "lead_id": lid,
                "id": lid,
                "cliente_id": cliente_id,
                "fuente": lead["fuente"],
                "plataforma": lead["plataforma"],
                "tipo_trabajo": lead["tipo_trabajo"],
                "titulo": lead["titulo"],
                "categoria": lead["categoria"],
                "presupuesto": lead["presupuesto"],
                "presupuesto_num": lead["presupuesto_num"],
                "score": lead["score"],
                "prioridad_tag": lead["prioridad_tag"],
                "link": lead["link"],
                "autor": lead["autor"],
            },
            origen="crm",
            nivel="ok" if lead["score"] >= 8 else "info",
        )
        return lead

    def _enriquecer_lead_row(self, r: dict[str, Any]) -> dict[str, Any]:
        plat = str(r.get("plataforma") or r.get("fuente") or "")
        autor = str(r.get("autor") or "")
        titulo = str(r.get("titulo") or "")
        out = dict(r)
        out["plataforma"] = plat
        out["tipo_trabajo"] = str(r.get("tipo_trabajo") or "freelance")
        out["presupuesto_num"] = float(r.get("presupuesto_num") or 0.0)
        out["ganancia_usd"] = float(r.get("ganancia_usd") or 0.0)
        out["score"] = int(r.get("score") or 0)
        out["notas"] = str(r.get("notas") or "")
        out["dm_url"] = _construir_dm_url(plat, autor, titulo)
        return out

    def obtener_lead(self, lead_id: int) -> dict[str, Any] | None:
        row = self.db.consultar_uno(
            """
            SELECT l.*,
                   c.nombre AS cliente_nombre,
                   c.reputacion_score AS cliente_reputacion,
                   (SELECT COUNT(*) FROM propuestas_enviadas p WHERE p.lead_id = l.id) AS num_propuestas,
                   (SELECT COUNT(*) FROM tareas_crm t WHERE t.lead_id = l.id AND t.estado IN ('pendiente', 'en_progreso')) AS num_tareas_pend
            FROM leads l
            LEFT JOIN clientes c ON c.id = l.cliente_id
            WHERE l.id = ?
            """,
            (int(lead_id),),
        )
        return self._enriquecer_lead_row(row) if row else None

    def actualizar_lead(
        self,
        lead_id: int,
        *,
        estado: str | None = None,
        ganancia_usd: float | None = None,
        notas: str | None = None,
        prioridad_tag: str | None = None,
        cliente_id: int | None = None,
    ) -> dict[str, Any] | None:
        lid = int(lead_id)
        prev = self.obtener_lead(lid)
        if prev is None:
            return None

        est_prev = str(prev["estado"])
        est_nuevo = est_prev
        if estado is not None:
            cand = str(estado).strip().lower()
            if cand in ESTADOS_LEAD_VALIDOS:
                est_nuevo = cand

        usd_nuevo = float(prev["ganancia_usd"]) if ganancia_usd is None else max(0.0, round(float(ganancia_usd), 2))
        notas_nuevo = str(prev["notas"]) if notas is None else str(notas)[:500]
        tag_nuevo = str(prev.get("prioridad_tag") or "") if prioridad_tag is None else str(prioridad_tag)[:120]
        cid_nuevo = prev.get("cliente_id") if cliente_id is None else int(cliente_id)

        cambio_estado = est_nuevo != est_prev
        self.db.ejecutar(
            """
            UPDATE leads
            SET estado = ?,
                ganancia_usd = ?,
                notas = ?,
                prioridad_tag = ?,
                cliente_id = ?,
                contactado_ts = CASE WHEN ? = 'contactado' AND estado != 'contactado' THEN CURRENT_TIMESTAMP ELSE contactado_ts END,
                followup_enviado = CASE WHEN ? = 'contactado' AND estado != 'contactado' THEN 0 ELSE followup_enviado END,
                actualizado_ts = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (est_nuevo, usd_nuevo, notas_nuevo, tag_nuevo, cid_nuevo, est_nuevo, est_nuevo, lid),
        )

        # Recalcular reputacion y LTV del cliente asociado si cambio estado o dinero
        if cid_nuevo and (cambio_estado or usd_nuevo != float(prev["ganancia_usd"])):
            self.clientes.recalcular_metricas_cliente(int(cid_nuevo))

        actualizado = self.obtener_lead(lid)
        assert actualizado is not None

        if cambio_estado:
            self.bus.publicar(
                "crm.lead.estado_cambiado",
                {
                    "lead_id": lid,
                    "id": lid,
                    "cliente_id": cid_nuevo,
                    "titulo": actualizado["titulo"],
                    "plataforma": actualizado["plataforma"],
                    "estado_anterior": est_prev,
                    "estado": est_nuevo,
                    "ganancia_usd": usd_nuevo,
                    "presupuesto_num": actualizado["presupuesto_num"],
                },
                origen="crm",
                nivel="ok" if est_nuevo == "ganado" else "info",
            )
        return actualizado

    def actualizar_lote_estado(self, lead_ids: list[int], nuevo_estado: str) -> dict[str, Any]:
        est = str(nuevo_estado or "").strip().lower()
        if est not in ESTADOS_LEAD_VALIDOS:
            return {"ok": False, "error": f"Estado invalido: {est}", "actualizados": 0}
        count = 0
        for lid in lead_ids:
            if self.actualizar_lead(int(lid), estado=est) is not None:
                count += 1
        return {"ok": True, "estado": est, "actualizados": count}

    def eliminar_lead(self, lead_id: int) -> bool:
        lid = int(lead_id)
        prev = self.obtener_lead(lid)
        if prev is None:
            return False
        cid = prev.get("cliente_id")
        n = self.db.ejecutar("DELETE FROM leads WHERE id = ?", (lid,))
        if n > 0 and cid:
            self.clientes.recalcular_metricas_cliente(int(cid))
        if n > 0:
            self.bus.publicar("crm.lead.eliminado", {"lead_id": lid}, origen="crm", nivel="info")
        return n > 0

    def buscar_leads(
        self,
        *,
        q: str = "",
        estado: str = "",
        plataforma: str = "",
        tipo_trabajo: str = "",
        cliente_id: int | None = None,
        score_min: int = 0,
        presupuesto_min: float = 0.0,
        ordenar_por: str = "reciente",
        limite: int = 120,
        offset: int = 0,
    ) -> dict[str, Any]:
        where: list[str] = ["1=1"]
        params: list[Any] = []

        if q.strip():
            pat = f"%{q.strip().lower()}%"
            where.append("(lower(l.titulo) LIKE ? OR lower(l.fuente) LIKE ? OR lower(l.plataforma) LIKE ? OR lower(l.categoria) LIKE ? OR lower(l.notas) LIKE ? OR lower(l.autor) LIKE ?)")
            params.extend([pat] * 6)
        if estado.strip():
            where.append("lower(l.estado) = ?")
            params.append(estado.strip().lower())
        if plataforma.strip():
            where.append("lower(COALESCE(NULLIF(l.plataforma,''), l.fuente)) = ?")
            params.append(plataforma.strip().lower())
        if tipo_trabajo.strip():
            where.append("lower(COALESCE(l.tipo_trabajo, 'freelance')) = ?")
            params.append(tipo_trabajo.strip().lower())
        if cliente_id is not None:
            where.append("l.cliente_id = ?")
            params.append(int(cliente_id))
        if score_min > 0:
            where.append("l.score >= ?")
            params.append(int(score_min))
        if presupuesto_min > 0:
            where.append("COALESCE(l.presupuesto_num, 0) >= ?")
            params.append(float(presupuesto_min))

        where_sql = " AND ".join(where)
        total = int(self.db.escalar(f"SELECT COUNT(*) FROM leads l WHERE {where_sql}", params, default=0) or 0)

        orden_sql = {
            "score": "l.score DESC, l.presupuesto_num DESC, l.id DESC",
            "dinero": "COALESCE(l.presupuesto_num, 0) DESC, l.score DESC, l.id DESC",
            "aegis": "COALESCE(l.aegis_score, 0) DESC, l.score DESC, l.id DESC",
            "reciente": "l.id DESC",
        }.get(ordenar_por, "l.id DESC")

        lim = max(1, min(400, int(limite)))
        off = max(0, int(offset))
        rows = self.db.consultar_todos(
            f"""
            SELECT l.*,
                   c.nombre AS cliente_nombre,
                   c.reputacion_score AS cliente_reputacion,
                   (SELECT COUNT(*) FROM propuestas_enviadas p WHERE p.lead_id = l.id) AS num_propuestas,
                   (SELECT COUNT(*) FROM tareas_crm t WHERE t.lead_id = l.id AND t.estado IN ('pendiente', 'en_progreso')) AS num_tareas_pend
            FROM leads l
            LEFT JOIN clientes c ON c.id = l.cliente_id
            WHERE {where_sql}
            ORDER BY {orden_sql}
            LIMIT ? OFFSET ?
            """,
            params + [lim, off],
        )
        return {
            "total": total,
            "limite": lim,
            "offset": off,
            "items": [self._enriquecer_lead_row(r) for r in rows],
        }

    def obtener_lead_360(self, lead_id: int) -> dict[str, Any] | None:
        lead = self.obtener_lead(lead_id)
        if lead is None:
            return None
        cliente = self.clientes.obtener_cliente(int(lead["cliente_id"])) if lead.get("cliente_id") else None
        propuestas = self.listar_propuestas(lead_id=int(lead_id), limite=20)
        tareas = self.listar_tareas(lead_id=int(lead_id), limite=20)
        facturas = self.db.consultar_todos(
            "SELECT id, numero, concepto, monto_bruto_usd, monto_neto_usd, estado_pago, emitida_ts FROM facturas_db WHERE lead_id = ? ORDER BY id DESC",
            (int(lead_id),),
        )
        sesiones = self.db.consultar_todos(
            "SELECT id, proyecto_nombre, duracion_seg, tarifa_hora_usd, facturable FROM sesiones_tiempo WHERE lead_id = ? ORDER BY id DESC LIMIT 20",
            (int(lead_id),),
        )
        horas_trab = round(sum(int(s.get("duracion_seg") or 0) for s in sesiones) / 3600.0, 2)

        return {
            "lead": lead,
            "cliente": cliente.to_dict() if cliente else None,
            "propuestas": propuestas,
            "tareas": tareas,
            "facturas": facturas,
            "horas_registradas": horas_trab,
        }

    def detectar_leads_estancados(
        self,
        *,
        horas_nuevo: int = 24,
        horas_contactado: int = 36,
        horas_negociando: int = 72,
        limite: int = 25,
    ) -> list[dict[str, Any]]:
        """Detecta oportunidades con dinero en riesgo por falta de seguimiento."""
        now = datetime.now(timezone.utc)
        c_nuevo = (now - timedelta(hours=max(1, int(horas_nuevo)))).strftime("%Y-%m-%d %H:%M:%S")
        c_cont = (now - timedelta(hours=max(1, int(horas_contactado)))).strftime("%Y-%m-%d %H:%M:%S")
        c_neg = (now - timedelta(hours=max(1, int(horas_negociando)))).strftime("%Y-%m-%d %H:%M:%S")

        rows = self.db.consultar_todos(
            """
            SELECT id, titulo, plataforma, fuente, estado, score, presupuesto, presupuesto_num,
                   COALESCE(actualizado_ts, contactado_ts, fecha) AS ultima_actividad, link
            FROM leads
            WHERE (estado = 'nuevo' AND score >= 7 AND fecha <= ?)
               OR (estado = 'contactado' AND COALESCE(contactado_ts, actualizado_ts, fecha) <= ?)
               OR (estado = 'negociando' AND COALESCE(actualizado_ts, fecha) <= ?)
            ORDER BY presupuesto_num DESC, score DESC
            LIMIT ?
            """,
            (c_nuevo, c_cont, c_neg, max(1, int(limite))),
        )
        salida: list[dict[str, Any]] = []
        for r in rows:
            item = dict(r)
            est = str(r["estado"])
            item["accion_sugerida"] = {
                "nuevo": "Enviar Pitch A rapido antes de que cierre",
                "contactado": "Enviar Follow-Up corto (Dia 1/3)",
                "negociando": "Destrabar precio o proponer milestone 50%",
            }.get(est, "Revisar lead")
            salida.append(item)
        return salida

    # ==================== 2. PROPUESTAS A/B & ANALYTICS DE CONVERSION ====================
    def registrar_propuesta(
        self,
        *,
        lead_id: int | None,
        texto_pitch: str,
        variante: str = "A",
        precio_cotizado_usd: float = 0.0,
        template_nombre: str = "",
        plataforma: str = "",
        notas: str = "",
        marcar_lead_contactado: bool = True,
    ) -> dict[str, Any]:
        var = str(variante or "A").strip().upper()[:12]
        plat = normalizar_plataforma(plataforma)
        cliente_id: int | None = None
        lid_valid: int | None = None

        if lead_id is not None:
            lead = self.obtener_lead(int(lead_id))
            if lead is not None:
                lid_valid = int(lead["id"])
                cliente_id = int(lead["cliente_id"]) if lead.get("cliente_id") else None
                if not plataforma:
                    plat = normalizar_plataforma(lead.get("plataforma") or lead.get("fuente"))

        pid = self.db.ejecutar(
            """
            INSERT INTO propuestas_enviadas (
                lead_id, cliente_id, plataforma, variante, template_nombre,
                precio_cotizado_usd, texto_pitch, estado_respuesta, notas
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'enviada', ?)
            """,
            (
                lid_valid,
                cliente_id,
                plat,
                var,
                str(template_nombre or "")[:80],
                round(float(precio_cotizado_usd or 0.0), 2),
                str(texto_pitch or "")[:4000],
                str(notas or "")[:400],
            ),
        )

        if template_nombre.strip():
            self.db.ejecutar(
                "UPDATE pitch_templates SET usos = usos + 1 WHERE lower(nombre) = ?",
                (template_nombre.strip().lower(),),
            )

        if marcar_lead_contactado and lid_valid is not None:
            lead_act = self.obtener_lead(lid_valid)
            if lead_act and lead_act["estado"] == "nuevo":
                self.actualizar_lead(lid_valid, estado="contactado")

        prop = self.obtener_propuesta(pid)
        assert prop is not None
        self.bus.publicar(
            "crm.propuesta.enviada",
            {
                "propuesta_id": pid,
                "lead_id": lid_valid,
                "cliente_id": cliente_id,
                "variante": var,
                "plataforma": plat,
                "precio_cotizado_usd": prop["precio_cotizado_usd"],
            },
            origen="crm",
            nivel="info",
        )
        return prop

    def obtener_propuesta(self, propuesta_id: int) -> dict[str, Any] | None:
        row = self.db.consultar_uno(
            """
            SELECT p.*, COALESCE(l.titulo, '') AS lead_titulo
            FROM propuestas_enviadas p
            LEFT JOIN leads l ON l.id = p.lead_id
            WHERE p.id = ?
            """,
            (int(propuesta_id),),
        )
        return PropuestaCRM.from_row(row).to_dict() if row else None

    def registrar_respuesta_propuesta(
        self,
        propuesta_id: int,
        estado_respuesta: str,
        *,
        notas: str | None = None,
        ganancia_usd: float | None = None,
    ) -> dict[str, Any] | None:
        est = str(estado_respuesta or "").strip().lower()
        if est not in ESTADOS_PROPUESTA_VALIDOS:
            return None

        prev = self.obtener_propuesta(propuesta_id)
        if prev is None:
            return None

        est_prev = str(prev["estado_respuesta"])
        resp_ts = prev["respondida_ts"]
        if est in ESTADOS_PROP_RESPONDIDA and not resp_ts:
            resp_ts = utc_now_str()

        notas_f = prev["notas"] if notas is None else str(notas)[:400]
        self.db.ejecutar(
            "UPDATE propuestas_enviadas SET estado_respuesta = ?, respondida_ts = ?, notas = ? WHERE id = ?",
            (est, resp_ts, notas_f, int(propuesta_id)),
        )

        # Actualizar estadisticas de pitch_templates evitando doble conteo
        tpl = str(prev.get("template_nombre") or "").strip().lower()
        if tpl:
            if est in ESTADOS_PROP_RESPONDIDA and est_prev not in ESTADOS_PROP_RESPONDIDA:
                self.db.ejecutar("UPDATE pitch_templates SET respuestas = respuestas + 1 WHERE lower(nombre) = ?", (tpl,))
            if est == "ganada" and est_prev != "ganada":
                self.db.ejecutar("UPDATE pitch_templates SET ganados = ganados + 1 WHERE lower(nombre) = ?", (tpl,))

        # Sincronizar estado del Lead asociado
        lid = prev.get("lead_id")
        if lid is not None:
            if est == "ganada":
                monto_win = ganancia_usd if ganancia_usd is not None else float(prev.get("precio_cotizado_usd") or 0.0)
                self.actualizar_lead(int(lid), estado="ganado", ganancia_usd=monto_win)
            elif est in ("respondida", "entrevista"):
                lead_act = self.obtener_lead(int(lid))
                if lead_act and lead_act["estado"] in ("nuevo", "contactado"):
                    self.actualizar_lead(int(lid), estado="negociando")

        if prev.get("cliente_id"):
            self.clientes.recalcular_metricas_cliente(int(prev["cliente_id"]))

        actualizada = self.obtener_propuesta(propuesta_id)
        self.bus.publicar(
            "crm.propuesta.respondida",
            {
                "propuesta_id": int(propuesta_id),
                "lead_id": lid,
                "variante": prev["variante"],
                "estado_respuesta": est,
            },
            origen="crm",
            nivel="ok" if est in ("ganada", "entrevista") else "info",
        )
        return actualizada

    def listar_propuestas(
        self,
        *,
        lead_id: int | None = None,
        cliente_id: int | None = None,
        variante: str = "",
        limite: int = 60,
    ) -> list[dict[str, Any]]:
        where = ["1=1"]
        params: list[Any] = []
        if lead_id is not None:
            where.append("p.lead_id = ?")
            params.append(int(lead_id))
        if cliente_id is not None:
            where.append("p.cliente_id = ?")
            params.append(int(cliente_id))
        if variante.strip():
            where.append("upper(p.variante) = ?")
            params.append(variante.strip().upper())
        params.append(max(1, min(200, int(limite))))

        rows = self.db.consultar_todos(
            f"""
            SELECT p.*, COALESCE(l.titulo, '') AS lead_titulo
            FROM propuestas_enviadas p
            LEFT JOIN leads l ON l.id = p.lead_id
            WHERE {' AND '.join(where)}
            ORDER BY p.id DESC
            LIMIT ?
            """,
            params,
        )
        return [PropuestaCRM.from_row(r).to_dict() for r in rows]

    def analytics_ab_propuestas(self) -> dict[str, Any]:
        """Calcula tasa de respuesta, tasa de cierre y ticket promedio por variante A/B, plataforma y template."""
        def _agrupar(campo_sql: str) -> list[dict[str, Any]]:
            rows = self.db.consultar_todos(
                f"""
                SELECT
                    COALESCE(NULLIF({campo_sql}, ''), 'Sin definir') AS clave,
                    COUNT(*) AS enviadas,
                    SUM(CASE WHEN estado_respuesta IN ('respondida', 'entrevista', 'ganada') THEN 1 ELSE 0 END) AS respondidas,
                    SUM(CASE WHEN estado_respuesta = 'ganada' THEN 1 ELSE 0 END) AS ganadas,
                    ROUND(AVG(CASE WHEN precio_cotizado_usd > 0 THEN precio_cotizado_usd END), 2) AS precio_prom_usd
                FROM propuestas_enviadas
                GROUP BY clave
                ORDER BY ganadas DESC, respondidas DESC, enviadas DESC
                """
            )
            out = []
            for r in rows:
                env = int(r["enviadas"] or 0)
                resp = int(r["respondidas"] or 0)
                gan = int(r["ganadas"] or 0)
                out.append({
                    "clave": str(r["clave"]),
                    "enviadas": env,
                    "respondidas": resp,
                    "ganadas": gan,
                    "tasa_respuesta_pct": round((resp / max(1, env)) * 100.0, 1),
                    "tasa_cierre_pct": round((gan / max(1, env)) * 100.0, 1),
                    "precio_prom_usd": float(r["precio_prom_usd"] or 0.0),
                })
            return out

        tot = int(self.db.escalar("SELECT COUNT(*) FROM propuestas_enviadas", default=0) or 0)
        tot_resp = int(
            self.db.escalar(
                "SELECT COUNT(*) FROM propuestas_enviadas WHERE estado_respuesta IN ('respondida', 'entrevista', 'ganada')",
                default=0,
            ) or 0
        )
        tot_gan = int(
            self.db.escalar("SELECT COUNT(*) FROM propuestas_enviadas WHERE estado_respuesta = 'ganada'", default=0) or 0
        )
        por_var = _agrupar("variante")
        ganadora = max(por_var, key=lambda x: (x["tasa_cierre_pct"], x["tasa_respuesta_pct"], x["enviadas"]))["clave"] if por_var else ""

        return {
            "total_enviadas": tot,
            "total_respondidas": tot_resp,
            "total_ganadas": tot_gan,
            "tasa_respuesta_global_pct": round((tot_resp / max(1, tot)) * 100.0, 1) if tot else 0.0,
            "tasa_cierre_global_pct": round((tot_gan / max(1, tot)) * 100.0, 1) if tot else 0.0,
            "variante_ganadora": ganadora,
            "por_variante": por_var,
            "por_plataforma": _agrupar("plataforma"),
            "por_template": _agrupar("template_nombre"),
        }

    # ==================== 3. TAREAS & AGENDA CRM ====================
    def crear_tarea(
        self,
        titulo: str,
        *,
        descripcion: str = "",
        prioridad: str = "media",
        lead_id: int | None = None,
        cliente_id: int | None = None,
        vence_en_horas: float | None = None,
        vence_ts: str | None = None,
    ) -> dict[str, Any]:
        prio = str(prioridad or "media").strip().lower()
        if prio not in PRIORIDADES_TAREA_VALIDAS:
            prio = "media"

        lid_val: int | None = None
        cid_val: int | None = int(cliente_id) if cliente_id is not None else None
        if lead_id is not None:
            lead = self.obtener_lead(int(lead_id))
            if lead is not None:
                lid_val = int(lead["id"])
                if cid_val is None and lead.get("cliente_id"):
                    cid_val = int(lead["cliente_id"])

        v_ts = vence_ts
        if not v_ts and vence_en_horas is not None and float(vence_en_horas) > 0:
            v_ts = (datetime.now(timezone.utc) + timedelta(hours=float(vence_en_horas))).strftime("%Y-%m-%d %H:%M:%S")

        tid = self.db.ejecutar(
            """
            INSERT INTO tareas_crm (lead_id, cliente_id, titulo, descripcion, prioridad, estado, vence_ts)
            VALUES (?, ?, ?, ?, ?, 'pendiente', ?)
            """,
            (lid_val, cid_val, str(titulo or "Tarea")[:180], str(descripcion or "")[:600], prio, v_ts),
        )
        tarea = self.obtener_tarea(tid)
        assert tarea is not None
        self.bus.publicar(
            "crm.tarea.creada",
            {"tarea_id": tid, "titulo": tarea["titulo"], "prioridad": prio, "lead_id": lid_val},
            origen="crm",
            nivel="info",
        )
        return tarea

    def obtener_tarea(self, tarea_id: int) -> dict[str, Any] | None:
        row = self.db.consultar_uno(
            """
            SELECT t.*, COALESCE(l.titulo, '') AS lead_titulo, COALESCE(c.nombre, '') AS cliente_nombre
            FROM tareas_crm t
            LEFT JOIN leads l ON l.id = t.lead_id
            LEFT JOIN clientes c ON c.id = t.cliente_id
            WHERE t.id = ?
            """,
            (int(tarea_id),),
        )
        return TareaCRM.from_row(row).to_dict() if row else None

    def completar_tarea(self, tarea_id: int) -> dict[str, Any] | None:
        tid = int(tarea_id)
        if not self.db.escalar("SELECT 1 FROM tareas_crm WHERE id = ?", (tid,)):
            return None
        self.db.ejecutar(
            "UPDATE tareas_crm SET estado = 'completada', completada_ts = CURRENT_TIMESTAMP WHERE id = ?",
            (tid,),
        )
        tarea = self.obtener_tarea(tid)
        if tarea:
            self.bus.publicar("crm.tarea.completada", {"tarea_id": tid, "titulo": tarea["titulo"]}, origen="crm", nivel="ok")
        return tarea

    def posponer_tarea(self, tarea_id: int, horas: float = 24.0) -> dict[str, Any] | None:
        tid = int(tarea_id)
        if not self.db.escalar("SELECT 1 FROM tareas_crm WHERE id = ?", (tid,)):
            return None
        nuevo_vence = (datetime.now(timezone.utc) + timedelta(hours=max(1.0, float(horas)))).strftime("%Y-%m-%d %H:%M:%S")
        self.db.ejecutar(
            "UPDATE tareas_crm SET vence_ts = ?, estado = 'pendiente' WHERE id = ?",
            (nuevo_vence, tid),
        )
        return self.obtener_tarea(tid)

    def actualizar_tarea(self, tarea_id: int, cambios: dict[str, Any]) -> dict[str, Any] | None:
        prev = self.obtener_tarea(tarea_id)
        if prev is None:
            return None
        titulo = str(cambios.get("titulo", prev["titulo"])).strip()[:180] or prev["titulo"]
        desc = str(cambios.get("descripcion", prev["descripcion"])).strip()[:600]
        prio = str(cambios.get("prioridad", prev["prioridad"])).strip().lower()
        if prio not in PRIORIDADES_TAREA_VALIDAS:
            prio = prev["prioridad"]
        est = str(cambios.get("estado", prev["estado"])).strip().lower()
        if est not in ESTADOS_TAREA_VALIDOS:
            est = prev["estado"]
        vence = cambios.get("vence_ts", prev["vence_ts"])
        comp_ts = utc_now_str() if (est == "completada" and prev["estado"] != "completada") else prev["completada_ts"]

        self.db.ejecutar(
            "UPDATE tareas_crm SET titulo = ?, descripcion = ?, prioridad = ?, estado = ?, vence_ts = ?, completada_ts = ? WHERE id = ?",
            (titulo, desc, prio, est, vence, comp_ts, int(tarea_id)),
        )
        return self.obtener_tarea(tarea_id)

    def eliminar_tarea(self, tarea_id: int) -> bool:
        return self.db.ejecutar("DELETE FROM tareas_crm WHERE id = ?", (int(tarea_id),)) > 0

    def listar_tareas(
        self,
        *,
        estado: str = "",
        prioridad: str = "",
        lead_id: int | None = None,
        cliente_id: int | None = None,
        solo_pendientes: bool = False,
        solo_vencidas: bool = False,
        limite: int = 80,
    ) -> list[dict[str, Any]]:
        where = ["1=1"]
        params: list[Any] = []
        if solo_pendientes:
            where.append("t.estado IN ('pendiente', 'en_progreso')")
        elif estado.strip():
            where.append("t.estado = ?")
            params.append(estado.strip().lower())
        if prioridad.strip():
            where.append("t.prioridad = ?")
            params.append(prioridad.strip().lower())
        if lead_id is not None:
            where.append("t.lead_id = ?")
            params.append(int(lead_id))
        if cliente_id is not None:
            where.append("t.cliente_id = ?")
            params.append(int(cliente_id))
        if solo_vencidas:
            where.append("t.estado IN ('pendiente', 'en_progreso') AND t.vence_ts IS NOT NULL AND t.vence_ts < ?")
            params.append(utc_now_str())

        params.append(max(1, min(250, int(limite))))
        rows = self.db.consultar_todos(
            f"""
            SELECT t.*, COALESCE(l.titulo, '') AS lead_titulo, COALESCE(c.nombre, '') AS cliente_nombre
            FROM tareas_crm t
            LEFT JOIN leads l ON l.id = t.lead_id
            LEFT JOIN clientes c ON c.id = t.cliente_id
            WHERE {' AND '.join(where)}
            ORDER BY
                CASE t.estado WHEN 'pendiente' THEN 0 WHEN 'en_progreso' THEN 1 ELSE 2 END,
                CASE t.prioridad WHEN 'critica' THEN 0 WHEN 'alta' THEN 1 WHEN 'media' THEN 2 ELSE 3 END,
                COALESCE(t.vence_ts, '9999-12-31') ASC,
                t.id DESC
            LIMIT ?
            """,
            params,
        )
        return [TareaCRM.from_row(r).to_dict() for r in rows]

    def resumen_agenda(self) -> dict[str, Any]:
        ahora = utc_now_str()
        en_24h = (datetime.now(timezone.utc) + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        hace_7d = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")

        vencidas = int(self.db.escalar(
            "SELECT COUNT(*) FROM tareas_crm WHERE estado IN ('pendiente', 'en_progreso') AND vence_ts IS NOT NULL AND vence_ts < ?",
            (ahora,), default=0,
        ) or 0)
        hoy_24h = int(self.db.escalar(
            "SELECT COUNT(*) FROM tareas_crm WHERE estado IN ('pendiente', 'en_progreso') AND vence_ts IS NOT NULL AND vence_ts >= ? AND vence_ts <= ?",
            (ahora, en_24h), default=0,
        ) or 0)
        pendientes = int(self.db.escalar(
            "SELECT COUNT(*) FROM tareas_crm WHERE estado IN ('pendiente', 'en_progreso')", default=0,
        ) or 0)
        comp_7d = int(self.db.escalar(
            "SELECT COUNT(*) FROM tareas_crm WHERE estado = 'completada' AND completada_ts >= ?",
            (hace_7d,), default=0,
        ) or 0)
        return {
            "vencidas": vencidas,
            "proximas_24h": hoy_24h,
            "pendientes_totales": pendientes,
            "completadas_7d": comp_7d,
            "top_pendientes": self.listar_tareas(solo_pendientes=True, limite=10),
        }

    # ==================== 4. PIPELINE ANALYTICS & FORECAST PONDERADO ====================
    def resumen_pipeline(self, trm_cop: float = 4200.0) -> dict[str, Any]:
        filas_est = self.db.consultar_todos(
            """
            SELECT estado,
                   COUNT(*) AS cantidad,
                   COALESCE(SUM(presupuesto_num), 0) AS suma_presupuesto,
                   COALESCE(SUM(ganancia_usd), 0) AS suma_ganancia
            FROM leads
            GROUP BY estado
            """
        )
        por_estado: dict[str, dict[str, Any]] = {}
        pipeline_bruto = 0.0
        pipeline_ponderado = 0.0
        total_ganado = 0.0
        total_leads = 0
        ganados_n = 0
        atacados_n = 0

        for r in filas_est:
            est = str(r["estado"] or "nuevo")
            cant = int(r["cantidad"] or 0)
            pres = float(r["suma_presupuesto"] or 0.0)
            gan = float(r["suma_ganancia"] or 0.0)
            prob = PROBABILIDAD_ETAPA.get(est, 0.0)

            total_leads += cant
            if est == "ganado":
                total_ganado += gan
                ganados_n += cant
            if est in ("contactado", "negociando", "ganado"):
                atacados_n += cant
            if est in ("contactado", "negociando"):
                pipeline_bruto += pres
            if est in ("nuevo", "contactado", "negociando"):
                pipeline_ponderado += pres * prob

            por_estado[est] = {
                "cantidad": cant,
                "presupuesto_usd": round(pres, 2),
                "ganancia_usd": round(gan, 2),
                "ponderado_usd": round(pres * prob, 2),
                "probabilidad_pct": int(prob * 100),
            }

        conv_plat = self.db.consultar_todos(
            """
            SELECT COALESCE(NULLIF(plataforma,''), fuente) AS plat,
                   COUNT(*) AS total,
                   SUM(CASE WHEN estado = 'ganado' THEN 1 ELSE 0 END) AS ganados,
                   ROUND(COALESCE(SUM(CASE WHEN estado = 'ganado' THEN ganancia_usd ELSE 0 END), 0), 2) AS usd
            FROM leads
            GROUP BY plat
            ORDER BY usd DESC, ganados DESC, total DESC
            LIMIT 10
            """
        )
        trm = max(1.0, float(trm_cop or 4200.0))
        return {
            "total_leads": total_leads,
            "ganados": ganados_n,
            "tasa_cierre_pct": round((ganados_n / max(1, atacados_n)) * 100.0, 1) if atacados_n else 0.0,
            "facturado_usd": round(total_ganado, 2),
            "facturado_cop": int(round(total_ganado * trm)),
            "ticket_promedio_usd": round(total_ganado / max(1, ganados_n), 2) if ganados_n else 0.0,
            "pipeline_bruto_usd": round(pipeline_bruto, 2),
            "pipeline_ponderado_usd": round(pipeline_ponderado, 2),
            "pipeline_ponderado_cop": int(round(pipeline_ponderado * trm)),
            "por_estado": por_estado,
            "conversion_plataformas": [dict(r) for r in conv_plat],
            "clientes_totales": int(self.db.escalar("SELECT COUNT(*) FROM clientes", default=0) or 0),
            "clientes_recurrentes": int(self.db.escalar("SELECT COUNT(*) FROM clientes WHERE es_recurrente = 1", default=0) or 0),
            "estancados_count": len(self.detectar_leads_estancados(limite=50)),
            "agenda": self.resumen_agenda(),
            "propuestas_ab": self.analytics_ab_propuestas(),
        }


_CRM_LOCK = threading.Lock()
_CRM_SINGLETON: TitanCRMService | None = None


def obtener_crm_service() -> TitanCRMService:
    global _CRM_SINGLETON
    with _CRM_LOCK:
        if _CRM_SINGLETON is None:
            _CRM_SINGLETON = TitanCRMService()
        return _CRM_SINGLETON