from __future__ import annotations

from typing import Any

from titan_core.crm_service import TitanCRMService
from titan_core.finance_service import (
    TitanFinanceService,
    calcular_desglose_pasarela,
    comparar_pasarelas,
)
from titan_core.time_tracker import TitanTimeTracker
from titan_core.web_router import (
    TitanRequest,
    TitanRouter,
    bytes_response,
    error_response,
    html_response,
)


def _to_int_opt(val: Any) -> int | None:
    if val is None or val == "":
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _to_float(val: Any, default: float = 0.0) -> float:
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _to_bool(val: Any, default: bool = False) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("1", "true", "yes", "si", "on")


def construir_router_crm_finanzas(
    crm: TitanCRMService,
    fin: TitanFinanceService,
    tt: TitanTimeTracker,
) -> TitanRouter:
    """
    Router REST v2 para CRM Empresarial, Clientes, Propuestas A/B,
    Agenda/Tareas, Facturacion, Ledger de Caja y Time Tracker.
    """
    r = TitanRouter()

    # ==================== 1. LEADS & PIPELINE ====================
    @r.get("/leads/estancados", nombre="crm_leads_estancados", resumen="Leads en riesgo por falta de seguimiento", tags=("crm",))
    def _leads_estancados(req: TitanRequest) -> dict[str, Any]:
        items = crm.detectar_leads_estancados(
            horas_nuevo=req.qint("h_nuevo", 24),
            horas_contactado=req.qint("h_contactado", 36),
            horas_negociando=req.qint("h_negociando", 72),
            limite=req.qint("limit", 25),
        )
        return {"ok": True, "count": len(items), "items": items}

    @r.post("/leads/batch-estado", nombre="crm_leads_batch_estado", resumen="Actualiza estado de multiples leads (Kanban/bulk)", tags=("crm",))
    def _leads_batch(req: TitanRequest) -> Any:
        d = req.json_dict()
        raw_ids = d.get("lead_ids") or d.get("ids") or []
        if not isinstance(raw_ids, list) or not raw_ids:
            return error_response("Se requiere lista no vacia 'lead_ids'", 400)
        estado = str(d.get("estado") or "").strip().lower()
        res = crm.actualizar_lote_estado([int(x) for x in raw_ids], estado)
        if not res.get("ok"):
            return error_response(str(res.get("error") or "Error en batch"), 400)
        return res

    @r.get("/leads", nombre="crm_leads_list", resumen="Busqueda paginada y filtrada de leads", tags=("crm",))
    def _leads_list(req: TitanRequest) -> dict[str, Any]:
        cid = req.qint("cliente_id", 0)
        res = crm.buscar_leads(
            q=req.qparam("q", ""),
            estado=req.qparam("estado", ""),
            plataforma=req.qparam("plataforma", ""),
            tipo_trabajo=req.qparam("tipo_trabajo", ""),
            cliente_id=cid if cid > 0 else None,
            score_min=req.qint("score_min", 0),
            presupuesto_min=req.qfloat("presupuesto_min", 0.0),
            ordenar_por=req.qparam("sort", "reciente"),
            limite=req.qint("limit", 120),
            offset=req.qint("offset", 0),
        )
        return {"ok": True, **res}

    @r.post("/leads", nombre="crm_leads_create", resumen="Crea un lead en CRM con auto-vinculacion de cliente", tags=("crm",))
    def _leads_create(req: TitanRequest) -> Any:
        d = req.json_dict()
        titulo = str(d.get("titulo") or "").strip()
        if not titulo:
            return error_response("El campo 'titulo' es obligatorio", 400)
        lead = crm.crear_lead(
            fuente=str(d.get("fuente") or d.get("plataforma") or "Manual"),
            titulo=titulo,
            link=str(d.get("link") or ""),
            plataforma=str(d.get("plataforma") or ""),
            tipo_trabajo=str(d.get("tipo_trabajo") or "freelance"),
            autor=str(d.get("autor") or ""),
            categoria=str(d.get("categoria") or "Tech"),
            presupuesto=str(d.get("presupuesto") or "Por definir"),
            presupuesto_num=_to_float(d.get("presupuesto_num"), 0.0),
            score=int(_to_float(d.get("score"), 7)),
            competencia=str(d.get("competencia") or ""),
            confianza=str(d.get("confianza") or ""),
            prioridad_tag=str(d.get("prioridad_tag") or ""),
            notas=str(d.get("notas") or ""),
            aegis_score=_to_float(d.get("aegis_score"), 0.0),
            aegis_riesgo=_to_float(d.get("aegis_riesgo"), 0.0),
            horas_estimadas=str(d.get("horas_estimadas") or ""),
            tarifa_eff_usd=_to_float(d.get("tarifa_eff_usd"), 0.0),
            auto_vincular_cliente=_to_bool(d.get("auto_vincular_cliente"), True),
        )
        return {"ok": True, "lead": lead}

    @r.get("/leads/{lead_id:int}/360", nombre="crm_lead_360", resumen="Vista 360 completa del lead", tags=("crm",))
    def _lead_360(req: TitanRequest) -> Any:
        v360 = crm.obtener_lead_360(req.path_params["lead_id"])
        if v360 is None:
            return error_response("Lead no encontrado", 404, "not_found")
        return {"ok": True, **v360}

    @r.get("/leads/{lead_id:int}", nombre="crm_lead_get", resumen="Obtiene un lead por ID", tags=("crm",))
    def _lead_get(req: TitanRequest) -> Any:
        lead = crm.obtener_lead(req.path_params["lead_id"])
        if lead is None:
            return error_response("Lead no encontrado", 404, "not_found")
        return {"ok": True, "lead": lead}

    @r.patch("/leads/{lead_id:int}", nombre="crm_lead_update", resumen="Actualiza estado, ganancia, notas o tag de un lead", tags=("crm",))
    def _lead_update(req: TitanRequest) -> Any:
        d = req.json_dict()
        lead = crm.actualizar_lead(
            req.path_params["lead_id"],
            estado=d.get("estado"),
            ganancia_usd=_to_float(d["ganancia_usd"]) if "ganancia_usd" in d and d["ganancia_usd"] is not None else None,
            notas=d.get("notas"),
            prioridad_tag=d.get("prioridad_tag"),
            cliente_id=_to_int_opt(d.get("cliente_id")) if "cliente_id" in d else None,
        )
        if lead is None:
            return error_response("Lead no encontrado", 404, "not_found")
        return {"ok": True, "lead": lead}

    @r.delete("/leads/{lead_id:int}", nombre="crm_lead_delete", resumen="Elimina un lead", tags=("crm",))
    def _lead_delete(req: TitanRequest) -> Any:
        ok = crm.eliminar_lead(req.path_params["lead_id"])
        if not ok:
            return error_response("Lead no encontrado", 404, "not_found")
        return {"ok": True, "eliminado_id": req.path_params["lead_id"]}

    @r.get("/pipeline", nombre="crm_pipeline", resumen="Resumen ejecutivo de pipeline, forecast ponderado y conversion", tags=("crm",))
    def _pipeline(req: TitanRequest) -> dict[str, Any]:
        trm = req.qfloat("trm_cop", 4200.0)
        return {"ok": True, "pipeline": crm.resumen_pipeline(trm_cop=trm)}

    # ==================== 2. CLIENTES (LTV, REPUTACION, MERGE, TIMELINE) ====================
    @r.post("/clientes/fusionar", nombre="crm_clientes_merge", resumen="Fusion atomica de dos clientes duplicados", tags=("clientes",))
    def _clientes_merge(req: TitanRequest) -> Any:
        d = req.json_dict()
        oid = _to_int_opt(d.get("origen_id"))
        did = _to_int_opt(d.get("destino_id"))
        if not oid or not did:
            return error_response("Se requieren 'origen_id' y 'destino_id'", 400)
        res = crm.clientes.fusionar_clientes(oid, did)
        if res is None:
            return error_response("Cliente origen o destino no encontrado", 404, "not_found")
        return {"ok": True, "cliente": res.to_dict()}

    @r.post("/clientes/vincular-huerfanos", nombre="crm_clientes_link_orphans", resumen="Vincula leads historicos sin cliente_id", tags=("clientes",))
    def _clientes_orphans(req: TitanRequest) -> dict[str, Any]:
        d = req.json_dict()
        res = crm.clientes.vincular_leads_huerfanos(limite=int(_to_float(d.get("limite"), 500)))
        return {"ok": True, **res}

    @r.get("/clientes", nombre="crm_clientes_list", resumen="Lista cartera de clientes con LTV y reputacion", tags=("clientes",))
    def _clientes_list(req: TitanRequest) -> dict[str, Any]:
        items = crm.clientes.listar_clientes(
            busqueda=req.qparam("q", ""),
            plataforma=req.qparam("plataforma", ""),
            solo_recurrentes=req.qbool("solo_recurrentes", False),
            ordenar_por=req.qparam("sort", "ltv"),
            limite=req.qint("limit", 80),
            offset=req.qint("offset", 0),
        )
        return {"ok": True, "count": len(items), "items": items}

    @r.post("/clientes", nombre="crm_clientes_create", resumen="Crea ficha manual de cliente", tags=("clientes",))
    def _clientes_create(req: TitanRequest) -> Any:
        d = req.json_dict()
        nom = str(d.get("nombre") or "").strip()
        if not nom:
            return error_response("El campo 'nombre' es obligatorio", 400)
        cli = crm.clientes.crear_cliente(
            nombre=nom,
            handle=str(d.get("handle") or ""),
            plataforma_origen=str(d.get("plataforma_origen") or "General"),
            email=str(d.get("email") or ""),
            canal_contacto=str(d.get("canal_contacto") or ""),
            pais=str(d.get("pais") or ""),
            notas=str(d.get("notas") or ""),
            reputacion_inicial=_to_float(d.get("reputacion_score"), 50.0),
        )
        return {"ok": True, "cliente": cli.to_dict()}

    @r.get("/clientes/{cliente_id:int}/timeline", nombre="crm_cliente_timeline", resumen="Timeline cronologico del cliente", tags=("clientes",))
    def _cliente_timeline(req: TitanRequest) -> Any:
        cid = req.path_params["cliente_id"]
        if crm.clientes.obtener_cliente(cid) is None:
            return error_response("Cliente no encontrado", 404, "not_found")
        evs = crm.clientes.timeline_cliente(cid, limite=req.qint("limit", 40))
        return {"ok": True, "cliente_id": cid, "count": len(evs), "timeline": evs}

    @r.post("/clientes/{cliente_id:int}/recalcular", nombre="crm_cliente_recalc", resumen="Recalcula LTV y reputacion del cliente", tags=("clientes",))
    def _cliente_recalc(req: TitanRequest) -> Any:
        cli = crm.clientes.recalcular_metricas_cliente(req.path_params["cliente_id"])
        if cli is None:
            return error_response("Cliente no encontrado", 404, "not_found")
        return {"ok": True, "cliente": cli.to_dict()}

    @r.get("/clientes/{cliente_id:int}", nombre="crm_cliente_get", resumen="Obtiene ficha completa del cliente", tags=("clientes",))
    def _cliente_get(req: TitanRequest) -> Any:
        cli = crm.clientes.obtener_cliente(req.path_params["cliente_id"])
        if cli is None:
            return error_response("Cliente no encontrado", 404, "not_found")
        return {"ok": True, "cliente": cli.to_dict()}

    @r.patch("/clientes/{cliente_id:int}", nombre="crm_cliente_update", resumen="Actualiza datos de cliente", tags=("clientes",))
    def _cliente_update(req: TitanRequest) -> Any:
        cli = crm.clientes.actualizar_cliente(req.path_params["cliente_id"], req.json_dict())
        if cli is None:
            return error_response("Cliente no encontrado", 404, "not_found")
        return {"ok": True, "cliente": cli.to_dict()}

    @r.delete("/clientes/{cliente_id:int}", nombre="crm_cliente_delete", resumen="Elimina ficha de cliente", tags=("clientes",))
    def _cliente_delete(req: TitanRequest) -> Any:
        ok = crm.clientes.eliminar_cliente(req.path_params["cliente_id"])
        if not ok:
            return error_response("Cliente no encontrado", 404, "not_found")
        return {"ok": True, "eliminado_id": req.path_params["cliente_id"]}

    # ==================== 3. PROPUESTAS A/B ====================
    @r.get("/propuestas/analytics", nombre="crm_propuestas_analytics", resumen="Analitica A/B de conversion por variante, plataforma y template", tags=("propuestas",))
    def _prop_analytics(req: TitanRequest) -> dict[str, Any]:
        return {"ok": True, "analytics": crm.analytics_ab_propuestas()}

    @r.get("/propuestas", nombre="crm_propuestas_list", resumen="Lista propuestas enviadas", tags=("propuestas",))
    def _prop_list(req: TitanRequest) -> dict[str, Any]:
        lid = req.qint("lead_id", 0)
        cid = req.qint("cliente_id", 0)
        items = crm.listar_propuestas(
            lead_id=lid if lid > 0 else None,
            cliente_id=cid if cid > 0 else None,
            variante=req.qparam("variante", ""),
            limite=req.qint("limit", 60),
        )
        return {"ok": True, "count": len(items), "items": items}

    @r.post("/propuestas", nombre="crm_propuestas_create", resumen="Registra envio de una propuesta A/B", tags=("propuestas",))
    def _prop_create(req: TitanRequest) -> Any:
        d = req.json_dict()
        txt = str(d.get("texto_pitch") or "").strip()
        if not txt:
            return error_response("El campo 'texto_pitch' es obligatorio", 400)
        prop = crm.registrar_propuesta(
            lead_id=_to_int_opt(d.get("lead_id")),
            texto_pitch=txt,
            variante=str(d.get("variante") or "A"),
            precio_cotizado_usd=_to_float(d.get("precio_cotizado_usd"), 0.0),
            template_nombre=str(d.get("template_nombre") or ""),
            plataforma=str(d.get("plataforma") or ""),
            notas=str(d.get("notas") or ""),
            marcar_lead_contactado=_to_bool(d.get("marcar_lead_contactado"), True),
        )
        return {"ok": True, "propuesta": prop}

    @r.patch("/propuestas/{prop_id:int}/respuesta", nombre="crm_propuesta_respuesta", resumen="Actualiza resultado de una propuesta (respondida/entrevista/ganada/rechazada)", tags=("propuestas",))
    def _prop_resp(req: TitanRequest) -> Any:
        d = req.json_dict()
        est = str(d.get("estado_respuesta") or "").strip().lower()
        if not est:
            return error_response("Falta 'estado_respuesta'", 400)
        gan = _to_float(d["ganancia_usd"]) if "ganancia_usd" in d and d["ganancia_usd"] is not None else None
        prop = crm.registrar_respuesta_propuesta(
            req.path_params["prop_id"],
            est,
            notas=d.get("notas"),
            ganancia_usd=gan,
        )
        if prop is None:
            return error_response("Propuesta no encontrada o estado invalido", 404)
        return {"ok": True, "propuesta": prop}

    # ==================== 4. TAREAS & AGENDA ====================
    @r.get("/agenda", nombre="crm_agenda", resumen="Resumen ejecutivo de tareas vencidas, proximas 24h y pendientes", tags=("tareas",))
    def _agenda(req: TitanRequest) -> dict[str, Any]:
        return {"ok": True, "agenda": crm.resumen_agenda()}

    @r.get("/tareas", nombre="crm_tareas_list", resumen="Lista tareas del CRM", tags=("tareas",))
    def _tareas_list(req: TitanRequest) -> dict[str, Any]:
        lid = req.qint("lead_id", 0)
        cid = req.qint("cliente_id", 0)
        items = crm.listar_tareas(
            estado=req.qparam("estado", ""),
            prioridad=req.qparam("prioridad", ""),
            lead_id=lid if lid > 0 else None,
            cliente_id=cid if cid > 0 else None,
            solo_pendientes=req.qbool("solo_pendientes", False),
            solo_vencidas=req.qbool("solo_vencidas", False),
            limite=req.qint("limit", 80),
        )
        return {"ok": True, "count": len(items), "items": items}

    @r.post("/tareas", nombre="crm_tareas_create", resumen="Crea una nueva tarea CRM", tags=("tareas",))
    def _tareas_create(req: TitanRequest) -> Any:
        d = req.json_dict()
        tit = str(d.get("titulo") or "").strip()
        if not tit:
            return error_response("El campo 'titulo' es obligatorio", 400)
        t = crm.crear_tarea(
            titulo=tit,
            descripcion=str(d.get("descripcion") or ""),
            prioridad=str(d.get("prioridad") or "media"),
            lead_id=_to_int_opt(d.get("lead_id")),
            cliente_id=_to_int_opt(d.get("cliente_id")),
            vence_en_horas=_to_float(d["vence_en_horas"]) if d.get("vence_en_horas") not in (None, "") else None,
            vence_ts=d.get("vence_ts"),
        )
        return {"ok": True, "tarea": t}

    @r.post("/tareas/{tarea_id:int}/completar", nombre="crm_tarea_complete", resumen="Marca una tarea como completada", tags=("tareas",))
    def _tarea_complete(req: TitanRequest) -> Any:
        t = crm.completar_tarea(req.path_params["tarea_id"])
        if t is None:
            return error_response("Tarea no encontrada", 404, "not_found")
        return {"ok": True, "tarea": t}

    @r.post("/tareas/{tarea_id:int}/posponer", nombre="crm_tarea_snooze", resumen="Pospone el vencimiento de una tarea N horas", tags=("tareas",))
    def _tarea_snooze(req: TitanRequest) -> Any:
        d = req.json_dict()
        hrs = _to_float(d.get("horas"), 24.0)
        t = crm.posponer_tarea(req.path_params["tarea_id"], horas=hrs)
        if t is None:
            return error_response("Tarea no encontrada", 404, "not_found")
        return {"ok": True, "tarea": t}

    @r.patch("/tareas/{tarea_id:int}", nombre="crm_tarea_update", resumen="Actualiza campos de una tarea", tags=("tareas",))
    def _tarea_update(req: TitanRequest) -> Any:
        t = crm.actualizar_tarea(req.path_params["tarea_id"], req.json_dict())
        if t is None:
            return error_response("Tarea no encontrada", 404, "not_found")
        return {"ok": True, "tarea": t}

    @r.delete("/tareas/{tarea_id:int}", nombre="crm_tarea_delete", resumen="Elimina una tarea", tags=("tareas",))
    def _tarea_delete(req: TitanRequest) -> Any:
        if not crm.eliminar_tarea(req.path_params["tarea_id"]):
            return error_response("Tarea no encontrada", 404, "not_found")
        return {"ok": True, "eliminado_id": req.path_params["tarea_id"]}

    # ==================== 5. FINANZAS, LEDGER DE CAJA & FACTURAS ====================
    @r.get("/finanzas/resumen", nombre="fin_resumen", resumen="Resumen financiero consolidado (USD/COP, meta, comisiones, caja)", tags=("finanzas",))
    def _fin_resumen(req: TitanRequest) -> dict[str, Any]:
        trm = req.qfloat("trm_cop", 0.0)
        meta = req.qfloat("meta_mensual_usd", 0.0)
        return {
            "ok": True,
            "resumen": fin.resumen_financiero(
                trm_cop=trm if trm > 0 else None,
                meta_mensual_usd=meta if meta > 0 else None,
            ),
        }

    @r.get("/finanzas/cashflow", nombre="fin_cashflow", resumen="Serie mensual de ingresos, gastos, retiros y neto", tags=("finanzas",))
    def _fin_cashflow(req: TitanRequest) -> dict[str, Any]:
        meses = req.qint("meses", 6)
        return {"ok": True, "meses": meses, "serie": fin.cashflow_mensual(meses)}

    @r.get("/finanzas/pasarelas", nombre="fin_pasarelas", resumen="Comparativa de comisiones y Gross-Up entre pasarelas", tags=("finanzas",))
    def _fin_pasarelas(req: TitanRequest) -> dict[str, Any]:
        monto = req.qfloat("monto_usd", 250.0)
        trm = req.qfloat("trm_cop", 4200.0)
        pas = req.qparam("pasarela", "")
        if pas:
            return {"ok": True, "desglose": calcular_desglose_pasarela(monto, pasarela=pas, trm_cop=trm)}
        return {"ok": True, "monto_usd": monto, "trm_cop": trm, "comparativa": comparar_pasarelas(monto, trm_cop=trm)}

    @r.get("/finanzas/export.csv", nombre="fin_export_csv", resumen="Exporta el libro mayor de caja en CSV", tags=("finanzas",))
    def _fin_csv(req: TitanRequest) -> Any:
        csv_txt = fin.exportar_libro_csv()
        return bytes_response(csv_txt.encode("utf-8"), content_type="text/csv; charset=utf-8", filename="libro_caja_titan.csv", compress_ok=True)

    @r.get("/finanzas/movimientos", nombre="fin_movs_list", resumen="Lista movimientos de caja", tags=("finanzas",))
    def _fin_movs_list(req: TitanRequest) -> dict[str, Any]:
        items = fin.listar_movimientos(
            tipo=req.qparam("tipo", ""),
            categoria=req.qparam("categoria", ""),
            limite=req.qint("limit", 120),
        )
        return {"ok": True, "count": len(items), "items": items}

    @r.post("/finanzas/movimientos", nombre="fin_movs_create", resumen="Registra un ingreso, gasto, retiro o ajuste en caja", tags=("finanzas",))
    def _fin_movs_create(req: TitanRequest) -> Any:
        d = req.json_dict()
        desc = str(d.get("descripcion") or "").strip()
        if not desc:
            return error_response("El campo 'descripcion' es obligatorio", 400)
        mov = fin.registrar_movimiento(
            tipo=str(d.get("tipo") or "ingreso"),
            descripcion=desc,
            monto_usd=_to_float(d.get("monto_usd"), 0.0),
            categoria=str(d.get("categoria") or "freelance"),
            pasarela=str(d.get("pasarela") or "binance"),
            trm_cop=_to_float(d["trm_cop"]) if d.get("trm_cop") else None,
            factura_id=_to_int_opt(d.get("factura_id")),
            fecha_ts=d.get("fecha_ts"),
        )
        return {"ok": True, "movimiento": mov}

    @r.delete("/finanzas/movimientos/{mov_id:int}", nombre="fin_mov_delete", resumen="Elimina un movimiento de caja", tags=("finanzas",))
    def _fin_mov_del(req: TitanRequest) -> Any:
        if not fin.eliminar_movimiento(req.path_params["mov_id"]):
            return error_response("Movimiento no encontrado", 404, "not_found")
        return {"ok": True, "eliminado_id": req.path_params["mov_id"]}

    @r.get("/facturas", nombre="fin_facturas_list", resumen="Lista facturas registradas en SQLite", tags=("facturas",))
    def _fac_list(req: TitanRequest) -> dict[str, Any]:
        cid = req.qint("cliente_id", 0)
        lid = req.qint("lead_id", 0)
        items = fin.listar_facturas(
            estado_pago=req.qparam("estado", ""),
            cliente_id=cid if cid > 0 else None,
            lead_id=lid if lid > 0 else None,
            limite=req.qint("limit", 80),
        )
        return {"ok": True, "count": len(items), "items": items}

    @r.post("/facturas", nombre="fin_facturas_create", resumen="Emite una nueva factura HTML/PDF y la guarda en DB", tags=("facturas",))
    def _fac_create(req: TitanRequest) -> Any:
        d = req.json_dict()
        cli = str(d.get("cliente_nombre") or d.get("cliente") or "").strip()
        conc = str(d.get("concepto") or "").strip()
        monto = _to_float(d.get("monto_bruto_usd", d.get("monto_usd")), 0.0)
        if not cli or not conc or monto <= 0:
            return error_response("Se requieren 'cliente_nombre', 'concepto' y 'monto_bruto_usd' > 0", 400)
        fac = fin.emitir_factura(
            cliente_nombre=cli,
            concepto=conc,
            monto_bruto_usd=monto,
            modalidad=str(d.get("modalidad") or "Final Payment (Full Delivery)"),
            pasarela=str(d.get("pasarela") or "binance"),
            trm_cop=_to_float(d["trm_cop"]) if d.get("trm_cop") else None,
            lead_id=_to_int_opt(d.get("lead_id")),
            cliente_id=_to_int_opt(d.get("cliente_id")),
            notas=str(d.get("notas") or ""),
            guardar_html=_to_bool(d.get("guardar_html"), True),
            marcar_pagada=_to_bool(d.get("marcar_pagada"), False),
        )
        incluir_html = _to_bool(d.get("incluir_html"), False)
        if not incluir_html:
            fac = {k: v for k, v in fac.items() if k != "html"}
        return {"ok": True, "factura": fac}

    @r.get("/facturas/{fac_id:int}/html", nombre="fin_factura_html", resumen="Devuelve el HTML imprimible de la factura", tags=("facturas",))
    def _fac_html(req: TitanRequest) -> Any:
        doc = fin.obtener_html_factura(req.path_params["fac_id"])
        if doc is None:
            return error_response("Factura no encontrada", 404, "not_found")
        return html_response(doc)

    @r.post("/facturas/{fac_id:int}/pagar", nombre="fin_factura_pagar", resumen="Marca factura pagada, registra caja y sincroniza CRM", tags=("facturas",))
    def _fac_pagar(req: TitanRequest) -> Any:
        d = req.json_dict()
        fac = fin.marcar_factura_pagada(
            req.path_params["fac_id"],
            pasarela=d.get("pasarela"),
            trm_cop=_to_float(d["trm_cop"]) if d.get("trm_cop") else None,
            registrar_en_caja=_to_bool(d.get("registrar_en_caja"), True),
            sincronizar_lead=_to_bool(d.get("sincronizar_lead"), True),
        )
        if fac is None:
            return error_response("Factura no encontrada o anulada", 404)
        return {"ok": True, "factura": fac}

    @r.post("/facturas/{fac_id:int}/anular", nombre="fin_factura_anular", resumen="Anula una factura y revierte su asiento de caja", tags=("facturas",))
    def _fac_anular(req: TitanRequest) -> Any:
        d = req.json_dict()
        fac = fin.anular_factura(req.path_params["fac_id"], motivo=str(d.get("motivo") or ""))
        if fac is None:
            return error_response("Factura no encontrada", 404, "not_found")
        return {"ok": True, "factura": fac}

    @r.get("/facturas/{fac_id:int}", nombre="fin_factura_get", resumen="Obtiene detalle de una factura", tags=("facturas",))
    def _fac_get(req: TitanRequest) -> Any:
        fac = fin.obtener_factura(req.path_params["fac_id"])
        if fac is None:
            return error_response("Factura no encontrada", 404, "not_found")
        return {"ok": True, "factura": fac}

    # ==================== 6. TIME TRACKER & RENTABILIDAD POR HORA ====================
    @r.get("/tiempo/resumen", nombre="tt_resumen", resumen="Productividad, horas 14d y sesion activa", tags=("tiempo",))
    def _tt_resumen(req: TitanRequest) -> dict[str, Any]:
        return {
            "ok": True,
            "productividad": tt.resumen_productividad(
                dias=req.qint("dias", 30),
                trm_cop=req.qfloat("trm_cop", 4200.0),
            ),
        }

    @r.get("/tiempo/activa", nombre="tt_activa", resumen="Obtiene la sesion de cronometro en curso", tags=("tiempo",))
    def _tt_activa(req: TitanRequest) -> dict[str, Any]:
        return {"ok": True, "sesion_activa": tt.obtener_sesion_activa()}

    @r.get("/tiempo/export.csv", nombre="tt_export_csv", resumen="Exporta timesheet en CSV", tags=("tiempo",))
    def _tt_csv(req: TitanRequest) -> Any:
        lid = req.qint("lead_id", 0)
        csv_txt = tt.exportar_timesheet_csv(lead_id=lid if lid > 0 else None, dias=req.qint("dias", 30))
        return bytes_response(csv_txt.encode("utf-8"), content_type="text/csv; charset=utf-8", filename="timesheet_titan.csv", compress_ok=True)

    @r.get("/tiempo/rentabilidad/{lead_id:int}", nombre="tt_rentabilidad_lead", resumen="Calcula tarifa efectiva USD/hr real de un lead", tags=("tiempo",))
    def _tt_rent(req: TitanRequest) -> dict[str, Any]:
        obj = req.qfloat("tarifa_objetivo", 0.0)
        return {
            "ok": True,
            "rentabilidad": tt.calcular_rentabilidad_lead(
                req.path_params["lead_id"],
                tarifa_objetivo_usd=obj if obj > 0 else None,
            ),
        }

    @r.get("/tiempo/sesiones", nombre="tt_sesiones_list", resumen="Lista sesiones de tiempo", tags=("tiempo",))
    def _tt_list(req: TitanRequest) -> dict[str, Any]:
        lid = req.qint("lead_id", 0)
        items = tt.listar_sesiones(
            lead_id=lid if lid > 0 else None,
            solo_facturables=req.qbool("solo_facturables", False),
            dias=req.qint("dias", 30),
            limite=req.qint("limit", 100),
        )
        return {"ok": True, "count": len(items), "items": items}

    @r.post("/tiempo/iniciar", nombre="tt_iniciar", resumen="Inicia una sesion de cronometro persistente", tags=("tiempo",))
    def _tt_iniciar(req: TitanRequest) -> dict[str, Any]:
        d = req.json_dict()
        ses = tt.iniciar_sesion(
            proyecto_nombre=str(d.get("proyecto_nombre") or d.get("proyecto") or ""),
            lead_id=_to_int_opt(d.get("lead_id")),
            tarifa_hora_usd=_to_float(d["tarifa_hora_usd"]) if d.get("tarifa_hora_usd") else None,
            facturable=_to_bool(d.get("facturable"), True),
            notas=str(d.get("notas") or ""),
            detener_previa=_to_bool(d.get("detener_previa"), True),
        )
        return {"ok": True, "sesion": ses}

    @r.post("/tiempo/detener", nombre="tt_detener", resumen="Detiene la sesion activa o indicada", tags=("tiempo",))
    def _tt_detener(req: TitanRequest) -> Any:
        d = req.json_dict()
        ses = tt.detener_sesion(sesion_id=_to_int_opt(d.get("sesion_id")), notas=d.get("notas"))
        if ses is None:
            return error_response("No hay sesion de tiempo activa", 404, "not_found")
        return {"ok": True, "sesion": ses}

    @r.post("/tiempo/manual", nombre="tt_manual", resumen="Registra una sesion manual en minutos", tags=("tiempo",))
    def _tt_manual(req: TitanRequest) -> Any:
        d = req.json_dict()
        mins = _to_float(d.get("duracion_minutos"), 0.0)
        if mins <= 0:
            return error_response("'duracion_minutos' debe ser mayor a 0", 400)
        ses = tt.registrar_sesion_manual(
            proyecto_nombre=str(d.get("proyecto_nombre") or d.get("proyecto") or "Desarrollo Freelance"),
            duracion_minutos=mins,
            lead_id=_to_int_opt(d.get("lead_id")),
            tarifa_hora_usd=_to_float(d["tarifa_hora_usd"]) if d.get("tarifa_hora_usd") else None,
            facturable=_to_bool(d.get("facturable"), True),
            notas=str(d.get("notas") or ""),
        )
        return {"ok": True, "sesion": ses}

    @r.patch("/tiempo/sesiones/{sesion_id:int}", nombre="tt_update", resumen="Edita una sesion de tiempo", tags=("tiempo",))
    def _tt_update(req: TitanRequest) -> Any:
        ses = tt.actualizar_sesion(req.path_params["sesion_id"], req.json_dict())
        if ses is None:
            return error_response("Sesion no encontrada", 404, "not_found")
        return {"ok": True, "sesion": ses}

    @r.delete("/tiempo/sesiones/{sesion_id:int}", nombre="tt_delete", resumen="Elimina una sesion de tiempo", tags=("tiempo",))
    def _tt_delete(req: TitanRequest) -> Any:
        if not tt.eliminar_sesion(req.path_params["sesion_id"]):
            return error_response("Sesion no encontrada", 404, "not_found")
        return {"ok": True, "eliminado_id": req.path_params["sesion_id"]}

    return r