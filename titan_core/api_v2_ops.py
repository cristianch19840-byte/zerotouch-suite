from __future__ import annotations

from typing import Any

from modulo_a_radar_whop.motor_filtrado.modelos import ContextoFiltro
from modulo_a_radar_whop.motor_filtrado.pipeline import (
    PERFILES_AEGIS,
    PipelineAEGIS,
    formatear_radiografia_texto,
)
from titan_core.ai_providers import SolicitudIA
from titan_core.ai_router import ESTRATEGIAS_ROUTING, TitanAIRouter
from titan_core.code_autofix import TitanCodeAutoFixer
from titan_core.code_sanitizer import CodeSanitizer
from titan_core.http_shield import TitanHTTPShield
from titan_core.license_engine import TitanLicenseEngine
from titan_core.pitch_engine import TitanPitchEngine
from titan_core.pitch_scorer import auditar_pitch
from titan_core.product_factory import EspecificacionProducto, TitanProductFactory
from titan_core.sandbox_runner import TitanSandboxRunner
from titan_core.web_router import TitanRequest, TitanRouter, error_response
from titan_core.workflow_engine import TitanWorkflowEngine


def _f(val: Any, default: float = 0.0) -> float:
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _i(val: Any, default: int = 0) -> int:
    if val is None or val == "":
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _b(val: Any, default: bool = False) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("1", "true", "yes", "si", "on")


def construir_router_operaciones(
    aegis: PipelineAEGIS,
    ai_router: TitanAIRouter,
    http_shield: TitanHTTPShield,
    workflows: TitanWorkflowEngine,
    sandbox: TitanSandboxRunner,
    autofixer: TitanCodeAutoFixer,
    pitch_engine: TitanPitchEngine,
    factory: TitanProductFactory,
    license_engine: TitanLicenseEngine,
) -> TitanRouter:
    """
    Router REST v2 para AEGIS-X v16, AI Router Multi-Modelo, HTTP Shield,
    Workflows IFTTT, Sandbox/Auto-Fix IA, Pitch Engine A/B y Whop Factory.
    """
    r = TitanRouter()

    # ==================== 1. AEGIS-X v16 (CALIBRACION, DRIFT, WHAT-IF, CONTRF) ====================
    @r.get("/aegis/resumen", nombre="aegis_v2_resumen", resumen="Telemetria completa de AEGIS-X v16, perfiles, calibracion y ML", tags=("aegis",))
    def _aegis_resumen(req: TitanRequest) -> dict[str, Any]:
        perfiles_info = []
        for nom, base in PERFILES_AEGIS.items():
            eff = aegis.resolver_perfil_efectivo(nom)
            perfiles_info.append({
                "nombre": nom,
                "descripcion": base.descripcion,
                "umbral_base": base.umbral_aprobacion,
                "umbral_efectivo": eff.umbral_aprobacion,
                "umbral_prioritario": eff.umbral_prioritario,
                "max_riesgo": eff.max_riesgo_permitido,
                "presupuesto_minimo_usd": base.presupuesto_minimo_usd,
                "tarifa_minima_usd_hr": base.tarifa_minima_usd_hr,
                "calibrado_dinamico": aegis.calibrador.obtener_ajuste(nom) is not None,
            })
        return {
            "ok": True,
            "perfiles": perfiles_info,
            "calibracion": aegis.calibrador.resumen_estado(),
            "verdict_cache": aegis.verdict_cache.stats(),
            "dedup_stats": aegis.dedup.estadisticas(),
            "ml_insights": aegis.ml.generar_insights_rentabilidad(),
            "auditoria": aegis.auditoria.obtener_resumen(req.qint("limit", 30)) if aegis.auditoria else {},
        }

    @r.post("/aegis/simular", nombre="aegis_v2_simular", resumen="Radiografia forense de 7 capas + SHAP + Contrafactuales (0 tokens)", tags=("aegis",))
    def _aegis_simular(req: TitanRequest) -> Any:
        d = req.json_dict()
        tit = str(d.get("titulo") or "")
        cue = str(d.get("cuerpo") or d.get("texto") or "")
        if not tit.strip() and not cue.strip():
            return error_response("Se requiere 'titulo' o 'cuerpo'", 400)
        plat = str(d.get("plataforma") or d.get("fuente") or "Reddit")
        perfil = str(d.get("perfil") or "equilibrado")
        ctx = ContextoFiltro(
            fuente=str(d.get("fuente") or plat),
            plataforma=plat,
            sub_o_categoria=str(d.get("fuente") or plat),
            monto_api_usd=_f(d.get("monto_api"), 0.0),
            perfil_nombre=perfil,
            tarifa_minima_usd_hr=_f(d.get("tarifa_minima_usd_hr"), 15.0),
            presupuesto_minimo_usd=_f(d.get("presupuesto_minimo_usd"), 20.0),
            solo_freelance_corto=_b(d.get("solo_freelance_corto"), False),
            palabras_blacklist_usuario=d.get("blacklist") or [],
            palabras_whitelist_usuario=d.get("whitelist") or [],
        )
        v = aegis.evaluar(
            titulo=tit, cuerpo=cue, tags=str(d.get("tags") or ""), flair=str(d.get("flair") or ""),
            post_id="sim_v2", ctx=ctx, simular_sin_dedup=True, registrar_dedup=False, registrar_auditoria=False,
        )
        return {
            "ok": True,
            "radiografia": aegis.radiografia_dict(v),
            "texto_reporte": formatear_radiografia_texto(v),
        }

    @r.post("/aegis/comparar-perfiles", nombre="aegis_v2_cmp", resumen="Compara la misma oferta contra los 4 perfiles AEGIS-X", tags=("aegis",))
    def _aegis_cmp(req: TitanRequest) -> Any:
        d = req.json_dict()
        tit = str(d.get("titulo") or "")
        cue = str(d.get("cuerpo") or d.get("texto") or "")
        if not tit.strip() and not cue.strip():
            return error_response("Se requiere 'titulo' o 'cuerpo'", 400)
        plat = str(d.get("plataforma") or "Reddit")
        ctx = ContextoFiltro(fuente=plat, plataforma=plat, sub_o_categoria=plat, monto_api_usd=_f(d.get("monto_api"), 0.0))
        res = aegis.comparar_perfiles(tit, cue, tags=str(d.get("tags") or ""), flair=str(d.get("flair") or ""), ctx_base=ctx)
        return {"ok": True, "comparativa": res}

    @r.post("/aegis/calibrar", nombre="aegis_v2_calibrar", resumen="Ejecuta auto-calibracion dinamica F-beta desde leads del CRM", tags=("aegis",))
    def _aegis_calibrar(req: TitanRequest) -> dict[str, Any]:
        d = req.json_dict()
        perf = str(d.get("perfil") or "").strip().lower() or None
        aplicar = _b(d.get("aplicar"), True)
        res = aegis.calibrar_automatico(perfil_nombre=perf, aplicar=aplicar)
        return {"ok": True, "resultado": res}

    @r.post("/aegis/calibracion/manual", nombre="aegis_v2_cal_manual", resumen="Fija umbrales y pesos manuales para un perfil", tags=("aegis",))
    def _aegis_cal_manual(req: TitanRequest) -> Any:
        d = req.json_dict()
        perf = str(d.get("perfil") or "equilibrado").strip().lower()
        if perf not in PERFILES_AEGIS:
            return error_response(f"Perfil invalido: {perf}", 400)
        aj = aegis.calibrador.guardar_ajuste_manual(
            perf,
            umbral_aprobacion=_f(d.get("umbral_aprobacion"), PERFILES_AEGIS[perf].umbral_aprobacion),
            umbral_prioritario=_f(d["umbral_prioritario"]) if d.get("umbral_prioritario") is not None else None,
            max_riesgo_permitido=_f(d.get("max_riesgo_permitido"), PERFILES_AEGIS[perf].max_riesgo_permitido),
            peso_taxonomia=_f(d.get("peso_taxonomia"), PERFILES_AEGIS[perf].peso_taxonomia),
            peso_economia=_f(d.get("peso_economia"), PERFILES_AEGIS[perf].peso_economia),
            peso_intencion=_f(d.get("peso_intencion"), PERFILES_AEGIS[perf].peso_intencion),
            peso_calidad=_f(d.get("peso_calidad"), PERFILES_AEGIS[perf].peso_calidad),
        )
        aegis.verdict_cache.limpiar()
        return {"ok": True, "ajuste": aj.to_dict()}

    @r.delete("/aegis/calibracion/{perfil}", nombre="aegis_v2_cal_reset", resumen="Restaura un perfil AEGIS-X a sus valores base", tags=("aegis",))
    def _aegis_cal_reset(req: TitanRequest) -> dict[str, Any]:
        perf = str(req.path_params["perfil"]).strip().lower()
        ok = aegis.calibrador.resetear_perfil(perf)
        aegis.verdict_cache.limpiar()
        return {"ok": True, "perfil": perf, "reseteado": ok}

    @r.get("/aegis/what-if", nombre="aegis_v2_whatif", resumen="Simula impacto de cambiar umbral sobre el historial de auditoria", tags=("aegis",))
    def _aegis_whatif(req: TitanRequest) -> dict[str, Any]:
        u = req.qfloat("umbral", 50.0)
        win = req.qint("ventana", 300)
        return {"ok": True, "what_if": aegis.calibrador.simular_impacto_umbral(u, ventana_ultimas=win)}

    @r.get("/aegis/drift", nombre="aegis_v2_drift", resumen="Calcula PSI Drift sobre la distribucion reciente de ofertas", tags=("aegis",))
    def _aegis_drift(req: TitanRequest) -> dict[str, Any]:
        rep = aegis.calibrador.analizar_drift(
            ventana_reciente=req.qint("reciente", 80),
            ventana_base=req.qint("base", 240),
        )
        return {"ok": True, "drift": rep.to_dict()}

    @r.post("/aegis/feedback", nombre="aegis_v2_feedback", resumen="Entrena el clasificador ML Naive Bayes con ejemplo manual", tags=("aegis",))
    def _aegis_fb(req: TitanRequest) -> Any:
        d = req.json_dict()
        tit = str(d.get("titulo") or "").strip()
        if not tit:
            return error_response("El campo 'titulo' es obligatorio", 400)
        st = aegis.ml.registrar_feedback(
            titulo=tit,
            etiqueta=1 if _b(d.get("etiqueta"), True) else 0,
            cuerpo=str(d.get("cuerpo") or ""),
            plataforma=str(d.get("plataforma") or "Manual"),
            categoria=str(d.get("categoria") or "Tech"),
            ganancia_usd=_f(d.get("ganancia_usd"), 0.0),
            reentrenar=True,
        )
        aegis.verdict_cache.limpiar()
        return {"ok": True, "habilitado": st.habilitado, "muestras_pos": st.muestras_pos, "muestras_neg": st.muestras_neg, "cv_f1": round(st.cv_f1, 4)}

    @r.post("/aegis/ml/reentrenar", nombre="aegis_v2_ml_retrain", resumen="Re-entrena Naive Bayes desde SQLite", tags=("aegis",))
    def _aegis_retrain(req: TitanRequest) -> dict[str, Any]:
        st = aegis.ml.entrenar_desde_db(forzar=True)
        aegis.verdict_cache.limpiar()
        return {"ok": True, "habilitado": st.habilitado, "muestras_pos": st.muestras_pos, "muestras_neg": st.muestras_neg, "cv_f1": round(st.cv_f1, 4)}

    # ==================== 2. AI ROUTER MULTI-MODELO & HTTP SHIELD ====================
    @r.get("/ai/salud", nombre="ai_v2_salud", resumen="Estado de Gemini, Ollama, OpenAI-Compat, cache y cuota diaria", tags=("ai",))
    def _ai_salud(req: TitanRequest) -> dict[str, Any]:
        return {"ok": True, "ai": ai_router.estado_salud(), "estrategias": sorted(ESTRATEGIAS_ROUTING.keys())}

    @r.post("/ai/estrategia", nombre="ai_v2_estrategia", resumen="Cambia estrategia de enrutamiento IA o budget cloud diario", tags=("ai",))
    def _ai_estrategia(req: TitanRequest) -> Any:
        d = req.json_dict()
        estr = str(d.get("estrategia") or "").strip().lower() or None
        if estr and estr not in ESTRATEGIAS_ROUTING:
            return error_response(f"Estrategia invalida. Opciones: {sorted(ESTRATEGIAS_ROUTING.keys())}", 400)
        bud = _i(d["budget_tokens_cloud_dia"], 0) if d.get("budget_tokens_cloud_dia") is not None else None
        ai_router.configurar(estrategia=estr, budget_tokens_cloud_dia=bud if (bud and bud > 0) else None)
        return {"ok": True, "estrategia": ai_router.estrategia_default, "budget_tokens_cloud_dia": ai_router.budget_tokens_cloud_dia}

    @r.post("/ai/test", nombre="ai_v2_test", resumen="Ejecuta un prompt de prueba via TitanAIRouter", tags=("ai",))
    def _ai_test(req: TitanRequest) -> Any:
        d = req.json_dict()
        prompt = str(d.get("prompt") or "").strip()
        if not prompt:
            return error_response("El campo 'prompt' es obligatorio", 400)
        resp = ai_router.ejecutar(
            SolicitudIA(
                prompt=prompt,
                system_prompt=str(d.get("system_prompt") or ""),
                temperatura=_f(d.get("temperatura"), 0.2),
                json_mode=_b(d.get("json_mode"), False),
                max_tokens=max(64, min(4096, _i(d.get("max_tokens"), 512))),
                tarea=str(d.get("tarea") or "general"),
                usar_cache=_b(d.get("usar_cache"), True),
                forzar_proveedor=str(d.get("forzar_proveedor") or ""),
            )
        )
        return {"ok": resp.ok, "texto": resp.texto, "json_data": resp.json_data, "meta": resp.to_dict()}

    @r.post("/ai/cache/podar", nombre="ai_v2_cache_podar", resumen="Poda entradas expiradas de ai_cache", tags=("ai",))
    def _ai_podar(req: TitanRequest) -> dict[str, Any]:
        return {"ok": True, "borradas": ai_router.cache.podar()}

    @r.post("/ai/cache/limpiar", nombre="ai_v2_cache_limpiar", resumen="Limpia completamente la cache IA L1/L2", tags=("ai",))
    def _ai_limpiar(req: TitanRequest) -> dict[str, Any]:
        return {"ok": True, "borradas": ai_router.cache.limpiar()}

    @r.get("/http/salud", nombre="http_v2_salud", resumen="Estado de HTTP Shield, Circuit Breakers y Rate Limiters", tags=("http",))
    def _http_salud(req: TitanRequest) -> dict[str, Any]:
        return {"ok": True, "http": http_shield.estado_salud()}

    @r.post("/http/circuit/reset", nombre="http_v2_cb_reset", resumen="Reinicia circuit breakers (todos o un dominio)", tags=("http",))
    def _http_cb_reset(req: TitanRequest) -> dict[str, Any]:
        d = req.json_dict()
        dom = str(d.get("dominio") or "").strip() or None
        n = http_shield.circuit_breaker.reiniciar(dom)
        return {"ok": True, "reiniciados": n, "dominio": dom or "*"}

    @r.post("/http/cache/limpiar", nombre="http_v2_cache_clear", resumen="Limpia cache ETag/HTTP en RAM", tags=("http",))
    def _http_cache_clear(req: TitanRequest) -> dict[str, Any]:
        return {"ok": True, "borradas": http_shield.limpiar_cache()}

    # ==================== 3. WORKFLOWS IFTTT ====================
    @r.post("/workflows/simular", nombre="wf_v2_simular", resumen="Simula un evento Dry-Run contra las reglas IFTTT", tags=("workflows",))
    def _wf_sim(req: TitanRequest) -> Any:
        d = req.json_dict()
        topico = str(d.get("topico") or "").strip()
        if not topico:
            return error_response("El campo 'topico' es obligatorio", 400)
        payload = d.get("payload") if isinstance(d.get("payload"), dict) else {}
        res = workflows.simular_evento(topico, payload)
        return {"ok": True, "topico": topico, "resultados": res}

    @r.post("/workflows/presets", nombre="wf_v2_presets", resumen="Instala presets IFTTT faltantes", tags=("workflows",))
    def _wf_presets(req: TitanRequest) -> dict[str, Any]:
        return {"ok": True, "instaladas": workflows.instalar_presets_defecto()}

    @r.get("/workflows", nombre="wf_v2_list", resumen="Lista reglas IFTTT, operadores, acciones e historial", tags=("workflows",))
    def _wf_list(req: TitanRequest) -> dict[str, Any]:
        return {"ok": True, **workflows.estado_resumen()}

    @r.post("/workflows", nombre="wf_v2_create", resumen="Crea una nueva regla IFTTT", tags=("workflows",))
    def _wf_create(req: TitanRequest) -> Any:
        d = req.json_dict()
        nom = str(d.get("nombre") or "").strip()
        evt = str(d.get("evento_disparador") or "").strip()
        if not nom or not evt:
            return error_response("Se requieren 'nombre' y 'evento_disparador'", 400)
        reg = workflows.crear_regla(
            nombre=nom,
            evento_disparador=evt,
            condiciones=d.get("condiciones") if d.get("condiciones") is not None else [],
            acciones=d.get("acciones") if isinstance(d.get("acciones"), list) else [],
            activa=_b(d.get("activa"), True),
            cooldown_seg=_i(d.get("cooldown_seg"), 60),
        )
        return {"ok": True, "regla": reg.to_dict()}

    @r.post("/workflows/{regla_id:int}/toggle", nombre="wf_v2_toggle", resumen="Activa o pausa una regla IFTTT", tags=("workflows",))
    def _wf_toggle(req: TitanRequest) -> Any:
        d = req.json_dict()
        est = _b(d["activa"]) if "activa" in d and d["activa"] is not None else None
        reg = workflows.toggle_regla(req.path_params["regla_id"], activa=est)
        if reg is None:
            return error_response("Regla no encontrada", 404, "not_found")
        return {"ok": True, "regla": reg.to_dict()}

    @r.patch("/workflows/{regla_id:int}", nombre="wf_v2_update", resumen="Modifica una regla IFTTT", tags=("workflows",))
    def _wf_update(req: TitanRequest) -> Any:
        reg = workflows.actualizar_regla(req.path_params["regla_id"], req.json_dict())
        if reg is None:
            return error_response("Regla no encontrada", 404, "not_found")
        return {"ok": True, "regla": reg.to_dict()}

    @r.delete("/workflows/{regla_id:int}", nombre="wf_v2_delete", resumen="Elimina una regla IFTTT", tags=("workflows",))
    def _wf_delete(req: TitanRequest) -> Any:
        if not workflows.eliminar_regla(req.path_params["regla_id"]):
            return error_response("Regla no encontrada", 404, "not_found")
        return {"ok": True, "eliminado_id": req.path_params["regla_id"]}

    # ==================== 4. SANDBOX PYTHON & AUTO-FIX IA ====================
    @r.post("/sandbox/auditar", nombre="sbx_v2_auditar", resumen="Auditoria estatica AST y deteccion de paquetes pip faltantes", tags=("sandbox",))
    def _sbx_aud(req: TitanRequest) -> dict[str, Any]:
        d = req.json_dict()
        rep = sandbox.auditar_codigo(
            str(d.get("codigo") or ""),
            permitir_subprocesos_seguros=_b(d.get("permitir_subprocesos_seguros"), False),
        )
        return {"ok": True, "auditoria": rep.to_dict()}

    @r.post("/sandbox/ejecutar", nombre="sbx_v2_exec", resumen="Ejecuta codigo Python aislado en Sandbox con timeout y entorno limpio", tags=("sandbox",))
    def _sbx_exec(req: TitanRequest) -> Any:
        d = req.json_dict()
        codigo = str(d.get("codigo") or "")
        ruta = str(d.get("ruta_archivo") or "").strip()
        timeout = _f(d.get("timeout_seg"), 10.0)
        args = d.get("args") if isinstance(d.get("args"), list) else None
        stdin_t = str(d.get("stdin") or "")
        if ruta and not codigo:
            res = sandbox.ejecutar_archivo(ruta, args=args, stdin_texto=stdin_t, timeout_seg=timeout)
        elif codigo.strip():
            res = sandbox.ejecutar_codigo(
                codigo,
                nombre_ref=str(d.get("nombre_ref") or "<sandbox_web.py>"),
                args=args,
                stdin_texto=stdin_t,
                timeout_seg=timeout,
                persistir=_b(d.get("persistir"), True),
            )
        else:
            return error_response("Proporciona 'codigo' o 'ruta_archivo'", 400)
        return {"ok": res.ok, "resultado": res.to_dict()}

    @r.post("/sandbox/autofix", nombre="sbx_v2_autofix", resumen="Ejecuta bucle de auto-reparacion IA + verificacion Sandbox", tags=("sandbox",))
    def _sbx_autofix(req: TitanRequest) -> Any:
        d = req.json_dict()
        codigo = str(d.get("codigo") or "")
        ruta = str(d.get("ruta_archivo") or "").strip()
        max_it = _i(d.get("max_iteraciones"), 3)
        timeout = _f(d.get("timeout_seg"), 10.0)
        inst = str(d.get("instruccion") or "")
        if ruta and not codigo:
            res = autofixer.reparar_archivo(
                ruta, guardar_si_ok=_b(d.get("guardar_si_ok"), True),
                instruccion_extra=inst, max_iteraciones=max_it, timeout_seg=timeout,
            )
        elif codigo.strip():
            res = autofixer.reparar_codigo(
                codigo, nombre_ref=str(d.get("nombre_ref") or "script.py"),
                instruccion_extra=inst, max_iteraciones=max_it, timeout_seg=timeout,
            )
        else:
            return error_response("Proporciona 'codigo' o 'ruta_archivo'", 400)
        return {"ok": res.exito, "codigo_final": res.codigo_final, "autofix": res.to_dict()}

    @r.post("/sandbox/refinar", nombre="sbx_v2_refinar", resumen="Refina un script con instruccion IA y verifica en Sandbox", tags=("sandbox",))
    def _sbx_refinar(req: TitanRequest) -> Any:
        d = req.json_dict()
        codigo = str(d.get("codigo") or "")
        inst = str(d.get("instruccion") or "").strip()
        if not codigo.strip() or not inst:
            return error_response("Se requieren 'codigo' e 'instruccion'", 400)
        res = autofixer.refinar_y_verificar(
            codigo, inst,
            nombre_ref=str(d.get("nombre_ref") or "script.py"),
            ejecutar_sandbox=_b(d.get("ejecutar_sandbox"), True),
            auto_fix_si_falla=_b(d.get("auto_fix_si_falla"), True),
            timeout_seg=_f(d.get("timeout_seg"), 10.0),
        )
        return {"ok": res.exito, "codigo_final": res.codigo_final, "autofix": res.to_dict()}

    @r.get("/sandbox/historial", nombre="sbx_v2_historial", resumen="Historial de ejecuciones del Sandbox", tags=("sandbox",))
    def _sbx_hist(req: TitanRequest) -> dict[str, Any]:
        items = sandbox.historial_ejecuciones(ruta_script=req.qparam("ruta", ""), limite=req.qint("limit", 30))
        return {"ok": True, "count": len(items), "items": items}

    @r.get("/sandbox/estadisticas", nombre="sbx_v2_stats", resumen="Metricas de exito y auto-reparacion del Sandbox", tags=("sandbox",))
    def _sbx_stats(req: TitanRequest) -> dict[str, Any]:
        return {"ok": True, "estadisticas": sandbox.estadisticas()}

    @r.get("/sandbox/snapshots", nombre="sbx_v2_snaps", resumen="Lista snapshots disponibles para rollback", tags=("sandbox",))
    def _sbx_snaps(req: TitanRequest) -> dict[str, Any]:
        items = autofixer.snapshots.listar_snapshots(req.qparam("archivo", ""))
        return {"ok": True, "count": len(items), "items": items}

    @r.post("/sandbox/snapshots/restaurar", nombre="sbx_v2_snap_restore", resumen="Restaura un snapshot previo", tags=("sandbox",))
    def _sbx_snap_restore(req: TitanRequest) -> Any:
        d = req.json_dict()
        snap = str(d.get("snapshot_ruta") or "").strip()
        dest = str(d.get("destino_ruta") or "").strip()
        if not snap or not dest:
            return error_response("Se requieren 'snapshot_ruta' y 'destino_ruta'", 400)
        ok = autofixer.snapshots.restaurar_snapshot(snap, dest)
        if not ok:
            return error_response("No se pudo restaurar el snapshot", 400)
        return {"ok": True, "restaurado_en": dest}

    # ==================== 5. PITCH ENGINE A/B & TEMPLATES ====================
    @r.get("/pitch/stats", nombre="pitch_v2_stats", resumen="Metricas del Pitch Engine, recomendaciones Bandit y A/B CRM", tags=("pitch",))
    def _pitch_stats(req: TitanRequest) -> dict[str, Any]:
        return {"ok": True, **pitch_engine.estadisticas_engine()}

    @r.post("/pitch/templates/render", nombre="pitch_v2_tpl_render", resumen="Renderiza un template con variables y lo audita en 0-tokens", tags=("pitch",))
    def _pitch_tpl_render(req: TitanRequest) -> Any:
        d = req.json_dict()
        ref = d.get("template_id") if d.get("template_id") is not None else d.get("nombre")
        if ref is None or str(ref).strip() == "":
            return error_response("Se requiere 'template_id' o 'nombre'", 400)
        res = pitch_engine.renderizar_template(ref, d.get("variables") if isinstance(d.get("variables"), dict) else {})
        if res is None:
            return error_response("Template no encontrado", 404, "not_found")
        return {"ok": True, **res}

    @r.get("/pitch/templates", nombre="pitch_v2_tpl_list", resumen="Lista templates con ranking Bandit UCB1/Thompson", tags=("pitch",))
    def _pitch_tpl_list(req: TitanRequest) -> dict[str, Any]:
        items = pitch_engine.listar_templates(
            plataforma=req.qparam("plataforma", ""),
            categoria=req.qparam("categoria", ""),
            incluir_bandit=req.qbool("bandit", True),
        )
        return {"ok": True, "count": len(items), "items": items}

    @r.post("/pitch/templates", nombre="pitch_v2_tpl_create", resumen="Crea un nuevo template de propuesta", tags=("pitch",))
    def _pitch_tpl_create(req: TitanRequest) -> Any:
        d = req.json_dict()
        tpl = pitch_engine.crear_template(
            nombre=str(d.get("nombre") or ""),
            cuerpo=str(d.get("cuerpo") or ""),
            plataforma=str(d.get("plataforma") or "general"),
            categoria=str(d.get("categoria") or "Python"),
        )
        return {"ok": True, "template": tpl}

    @r.patch("/pitch/templates/{tpl_id:int}", nombre="pitch_v2_tpl_update", resumen="Edita un template existente", tags=("pitch",))
    def _pitch_tpl_update(req: TitanRequest) -> Any:
        tpl = pitch_engine.actualizar_template(req.path_params["tpl_id"], req.json_dict())
        if tpl is None:
            return error_response("Template no encontrado", 404, "not_found")
        return {"ok": True, "template": tpl}

    @r.delete("/pitch/templates/{tpl_id:int}", nombre="pitch_v2_tpl_delete", resumen="Elimina un template", tags=("pitch",))
    def _pitch_tpl_delete(req: TitanRequest) -> Any:
        if not pitch_engine.eliminar_template(req.path_params["tpl_id"]):
            return error_response("Template no encontrado", 404, "not_found")
        return {"ok": True, "eliminado_id": req.path_params["tpl_id"]}

    @r.post("/pitch/auditar", nombre="pitch_v2_auditar", resumen="Auditoria anti-cliche y scoring 0-100 en 0-tokens", tags=("pitch",))
    def _pitch_auditar(req: TitanRequest) -> dict[str, Any]:
        d = req.json_dict()
        rep = auditar_pitch(
            str(d.get("texto") or d.get("texto_pitch") or ""),
            plataforma=str(d.get("plataforma") or "general"),
            oferta_texto=str(d.get("oferta_texto") or ""),
        )
        return {"ok": True, "auditoria": rep.to_dict()}

    @r.post("/pitch/generar", nombre="pitch_v2_generar", resumen="Genera variantes A/B/C con IA + auto-refinamiento + fallback local", tags=("pitch",))
    def _pitch_generar(req: TitanRequest) -> dict[str, Any]:
        d = req.json_dict()
        lid_raw = d.get("lead_id")
        lid = _i(lid_raw, 0) if lid_raw not in (None, "") else None
        res = pitch_engine.generar_pitch_ab(
            lead_id=lid if (lid and lid > 0) else None,
            titulo=str(d.get("titulo") or ""),
            cuerpo=str(d.get("cuerpo") or d.get("texto") or ""),
            plataforma=str(d.get("plataforma") or "reddit"),
            cliente=str(d.get("cliente") or ""),
            precio_objetivo_usd=_f(d.get("precio_objetivo_usd"), 0.0),
            categoria=str(d.get("categoria") or "Python"),
            idioma=str(d.get("idioma") or "auto"),
            num_variantes=_i(d.get("num_variantes"), 2),
            auto_refinar=_b(d.get("auto_refinar"), True),
            umbral_refino=_f(d.get("umbral_refino"), 72.0),
            modo_bandit=str(d.get("modo_bandit") or "ucb1"),
        )
        return res.to_dict()

    @r.post("/pitch/mejorar", nombre="pitch_v2_mejorar", resumen="Reescribe un pitch manual eliminando cliches y mejorando score", tags=("pitch",))
    def _pitch_mejorar(req: TitanRequest) -> Any:
        d = req.json_dict()
        txt = str(d.get("texto") or d.get("texto_pitch") or "").strip()
        if not txt:
            return error_response("El campo 'texto' es obligatorio", 400)
        res = pitch_engine.mejorar_pitch_manual(
            txt,
            plataforma=str(d.get("plataforma") or "general"),
            oferta_texto=str(d.get("oferta_texto") or ""),
        )
        return {"ok": True, **res}

    @r.post("/pitch/enviar", nombre="pitch_v2_enviar", resumen="Registra envio de pitch en CRM y alimenta estadisticas Bandit A/B", tags=("pitch",))
    def _pitch_enviar(req: TitanRequest) -> Any:
        d = req.json_dict()
        txt = str(d.get("texto_pitch") or d.get("texto") or "").strip()
        if not txt:
            return error_response("El campo 'texto_pitch' es obligatorio", 400)
        lid_raw = d.get("lead_id")
        lid = _i(lid_raw, 0) if lid_raw not in (None, "") else None
        prop = pitch_engine.enviar_y_registrar_pitch(
            lead_id=lid if (lid and lid > 0) else None,
            texto_pitch=txt,
            variante=str(d.get("variante") or "A"),
            precio_cotizado_usd=_f(d.get("precio_cotizado_usd"), 0.0),
            template_nombre=str(d.get("template_nombre") or ""),
            plataforma=str(d.get("plataforma") or ""),
            notas=str(d.get("notas") or ""),
        )
        return {"ok": True, "propuesta": prop}

    # ==================== 6. WHOP / SAAS FACTORY & LICENCIAS HMAC-SHA256 ====================
    @r.post("/factory/sanitizar", nombre="fac_v2_sanitizar", resumen="Previsualiza sanitizacion AST anti-secretos y deteccion PIP", tags=("factory",))
    def _fac_san(req: TitanRequest) -> dict[str, Any]:
        d = req.json_dict()
        rep = CodeSanitizer().sanitizar(str(d.get("codigo") or ""))
        return {"ok": rep.ast_valido, "codigo_limpio": rep.codigo_limpio, "reporte": rep.to_dict()}

    @r.post("/factory/construir", nombre="fac_v2_build", resumen="Empaqueta script en producto comercial .ZIP con licencias y Marketing Kit", tags=("factory",))
    def _fac_build(req: TitanRequest) -> Any:
        d = req.json_dict()
        nom = str(d.get("nombre") or "").strip()
        if not nom:
            return error_response("El campo 'nombre' es obligatorio", 400)
        spec = EspecificacionProducto(
            nombre=nom,
            version=str(d.get("version") or "1.0.0"),
            descripcion_corta=str(d.get("descripcion_corta") or "Automated Python tool ready for production."),
            precio_starter_usd=_f(d.get("precio_starter_usd"), 29.0),
            precio_pro_usd=_f(d.get("precio_pro_usd"), 79.0),
            precio_agency_usd=_f(d.get("precio_agency_usd"), 199.0),
            licencia_tipo=str(d.get("licencia_tipo") or "Commercial-Single"),
            incluir_license_guard=_b(d.get("incluir_license_guard"), True),
            generar_marketing_ia=_b(d.get("generar_marketing_ia"), True),
            autor=str(d.get("autor") or ""),
        )
        res = factory.construir_producto(
            spec,
            codigo_fuente=str(d.get("codigo_fuente") or d.get("codigo") or ""),
            ruta_script=str(d.get("ruta_script") or ""),
            emitir_licencia_demo=_b(d.get("emitir_licencia_demo"), True),
        )
        if not res.ok:
            return error_response(res.error or "Fallo construyendo producto", 400, detalles=res.to_dict())
        return res.to_dict()

    @r.post("/factory/verificar-zip", nombre="fac_v2_verify_zip", resumen="Verifica integridad criptografica SHA-256 de un paquete .ZIP", tags=("factory",))
    def _fac_vzip(req: TitanRequest) -> Any:
        d = req.json_dict()
        ruta = str(d.get("ruta_zip") or "").strip()
        if not ruta:
            return error_response("El campo 'ruta_zip' es obligatorio", 400)
        return factory.verificar_paquete_zip(ruta)

    @r.get("/factory/productos", nombre="fac_v2_prods_list", resumen="Lista productos empaquetados en Whop Factory", tags=("factory",))
    def _fac_prods(req: TitanRequest) -> dict[str, Any]:
        items = factory.listar_productos(limite=req.qint("limit", 50))
        return {"ok": True, "count": len(items), "items": items}

    @r.delete("/factory/productos/{prod_id:int}", nombre="fac_v2_prods_del", resumen="Elimina registro de producto empaquetado", tags=("factory",))
    def _fac_prod_del(req: TitanRequest) -> Any:
        ok = factory.eliminar_producto(req.path_params["prod_id"], borrar_archivos=req.qbool("borrar_archivos", False))
        if not ok:
            return error_response("Producto no encontrado", 404, "not_found")
        return {"ok": True, "eliminado_id": req.path_params["prod_id"]}

    @r.post("/factory/licencias/emitir", nombre="fac_v2_lic_emit", resumen="Emite una clave de licencia offline HMAC-SHA256", tags=("licencias",))
    def _lic_emit(req: TitanRequest) -> Any:
        d = req.json_dict()
        slug = str(d.get("producto_slug") or "").strip()
        cli = str(d.get("cliente") or "").strip()
        if not slug or not cli:
            return error_response("Se requieren 'producto_slug' y 'cliente'", 400)
        lic = license_engine.emitir_licencia(
            producto_slug=slug,
            cliente=cli,
            tier=str(d.get("tier") or "pro"),
            dias_validez=_i(d.get("dias_validez"), 0),
            seats=_i(d.get("seats"), 1),
            hwid=str(d.get("hwid") or ""),
            notas=str(d.get("notas") or ""),
        )
        return {"ok": True, "licencia": lic}

    @r.post("/factory/licencias/verificar", nombre="fac_v2_lic_verify", resumen="Verifica una clave de licencia HMAC-SHA256", tags=("licencias",))
    def _lic_verify(req: TitanRequest) -> Any:
        d = req.json_dict()
        clave = str(d.get("clave_licencia") or "").strip()
        slug = str(d.get("producto_slug") or "").strip()
        if not clave or not slug:
            return error_response("Se requieren 'clave_licencia' y 'producto_slug'", 400)
        ver = license_engine.verificar_licencia(
            clave, slug,
            hwid_actual=str(d.get("hwid_actual") or ""),
            comprobar_revocacion=_b(d.get("comprobar_revocacion"), True),
        )
        return {"ok": ver.valida, "verificacion": ver.to_dict()}

    @r.get("/factory/licencias", nombre="fac_v2_lic_list", resumen="Lista licencias emitidas", tags=("licencias",))
    def _lic_list(req: TitanRequest) -> dict[str, Any]:
        items = license_engine.listar_licencias(
            producto_slug=req.qparam("slug", ""),
            solo_activas=req.qbool("solo_activas", False),
            limite=req.qint("limit", 100),
        )
        return {"ok": True, "count": len(items), "items": items}

    @r.post("/factory/licencias/{lic_id}/revocar", nombre="fac_v2_lic_revoke", resumen="Revoca una licencia emitida", tags=("licencias",))
    def _lic_revoke(req: TitanRequest) -> Any:
        d = req.json_dict()
        lid = str(req.path_params["lic_id"]).strip()
        ok = license_engine.revocar_licencia(lid, motivo=str(d.get("motivo") or "revocada"))
        if not ok:
            return error_response("Licencia no encontrada", 404, "not_found")
        return {"ok": True, "licencia_id": lid, "revocada": True}

    return r