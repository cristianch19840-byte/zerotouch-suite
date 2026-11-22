from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from core_ia import DB_PATH, safe_float, safe_int
from modulo_a_radar_whop.motor_filtrado.aprendizaje import (
    MotorAprendizajeCRM,
    generar_senales_aprendizaje,
)
from modulo_a_radar_whop.motor_filtrado.dedup import MotorDedup
from modulo_a_radar_whop.motor_filtrado.economia import AnalizadorEconomico
from modulo_a_radar_whop.motor_filtrado.intencion import ClasificadorIntencion
from modulo_a_radar_whop.motor_filtrado.modelos import (
    AnalisisIntencion,
    AnalisisRiesgo,
    CategoriaSenal,
    ContextoFiltro,
    DecisionFiltro,
    DocumentoNormalizado,
    NivelRiesgo,
    PerfilEconomico,
    PrediccionAprendizaje,
    ResultadoDedup,
    ResultadoTaxonomia,
    SenalDetectada,
    TipoIntencion,
    VeredictoFiltro,
)
from modulo_a_radar_whop.motor_filtrado.normalizador import NormalizadorForense
from modulo_a_radar_whop.motor_filtrado.seguridad import EscudoSeguridad
from modulo_a_radar_whop.motor_filtrado.taxonomia import MotorTaxonomia
from modulo_a_radar_whop.motor_filtrado.calibrador import (
    CalibradorDinamicoAEGIS,
    calcular_contribuciones_capas,
    generar_contrafactuales,
)
from modulo_a_radar_whop.motor_filtrado.verdict_cache import (
    CacheVeredictosAEGIS,
    construir_clave_veredicto,
)
from titan_core.db_engine import TitanDBEngine, obtener_db_engine
from titan_core.event_bus import TitanEventBus, obtener_event_bus


# ==================== PERFILES OPERATIVOS AEGIS-X ====================
@dataclass(frozen=True, slots=True)
class PerfilAEGIS:
    nombre: str
    descripcion: str
    umbral_aprobacion: float
    umbral_prioritario: float
    max_riesgo_permitido: float
    bloquear_lowball: bool
    solo_freelance_corto: bool
    presupuesto_minimo_usd: float
    tarifa_minima_usd_hr: float
    peso_taxonomia: float = 0.36
    peso_economia: float = 0.26
    peso_intencion: float = 0.22
    peso_calidad: float = 0.16


PERFILES_AEGIS: dict[str, PerfilAEGIS] = {
    "equilibrado": PerfilAEGIS(
        nombre="equilibrado",
        descripcion="Balance ideal: freelance, bounties y contratos remotos solidos sin spam ni lowballers extremos.",
        umbral_aprobacion=46.0,
        umbral_prioritario=74.0,
        max_riesgo_permitido=64.0,
        bloquear_lowball=True,
        solo_freelance_corto=False,
        presupuesto_minimo_usd=20.0,
        tarifa_minima_usd_hr=15.0,
    ),
    "francotirador": PerfilAEGIS(
        nombre="francotirador",
        descripcion="Solo proyectos freelance puntuales, retainers y bounties pagos. Cero empleos full-time.",
        umbral_aprobacion=52.0,
        umbral_prioritario=76.0,
        max_riesgo_permitido=54.0,
        bloquear_lowball=True,
        solo_freelance_corto=True,
        presupuesto_minimo_usd=30.0,
        tarifa_minima_usd_hr=18.0,
        peso_taxonomia=0.38,
        peso_economia=0.28,
        peso_intencion=0.22,
        peso_calidad=0.12,
    ),
    "caza_ballenas": PerfilAEGIS(
        nombre="caza_ballenas",
        descripcion="Exige tickets altos ($120+), retainers o tarifas >=$25/hr. Descarta micro-tareas.",
        umbral_aprobacion=58.0,
        umbral_prioritario=80.0,
        max_riesgo_permitido=48.0,
        bloquear_lowball=True,
        solo_freelance_corto=False,
        presupuesto_minimo_usd=120.0,
        tarifa_minima_usd_hr=25.0,
        peso_taxonomia=0.30,
        peso_economia=0.38,
        peso_intencion=0.20,
        peso_calidad=0.12,
    ),
    "remoto_pro": PerfilAEGIS(
        nombre="remoto_pro",
        descripcion="Abre paso a empleos y contratos remotos dev bien pagos desde LATAM/Worldwide.",
        umbral_aprobacion=44.0,
        umbral_prioritario=72.0,
        max_riesgo_permitido=62.0,
        bloquear_lowball=True,
        solo_freelance_corto=False,
        presupuesto_minimo_usd=25.0,
        tarifa_minima_usd_hr=16.0,
        peso_taxonomia=0.36,
        peso_economia=0.24,
        peso_intencion=0.24,
        peso_calidad=0.16,
    ),
}


def obtener_perfil(nombre: str | None) -> PerfilAEGIS:
    clave = (nombre or "equilibrado").strip().lower()
    return PERFILES_AEGIS.get(clave, PERFILES_AEGIS["equilibrado"])


# ==================== ALMACEN DE AUDITORIA SQLITE (PARA AEGIS LAB) ====================
class AlmacenAuditoriaSQLite:
    def __init__(self, db_path: str | None = None, max_filas: int = 2500) -> None:
        self.db_path = db_path or DB_PATH
        self.max_filas = max(200, int(max_filas))
        self._lock = threading.Lock()
        self._esquema_ok = False
        self._buffer: list[tuple[Any, ...]] = []

    def _conectar(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def asegurar_esquema(self) -> None:
        if self._esquema_ok:
            return
        conn = self._conectar()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS aegis_auditoria (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_epoch REAL NOT NULL,
                    post_id TEXT DEFAULT '',
                    fuente TEXT DEFAULT '',
                    plataforma TEXT DEFAULT '',
                    titulo TEXT DEFAULT '',
                    aprobado INTEGER NOT NULL,
                    decision TEXT NOT NULL,
                    score_0_100 REAL DEFAULT 0,
                    riesgo_0_100 REAL DEFAULT 0,
                    tarifa_eff REAL DEFAULT 0,
                    razon TEXT DEFAULT '',
                    perfil TEXT DEFAULT 'equilibrado',
                    etiquetas_json TEXT DEFAULT '[]'
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_aegis_aud_ts ON aegis_auditoria(ts_epoch DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_aegis_aud_dec ON aegis_auditoria(decision)")
            conn.commit()
            self._esquema_ok = True
        finally:
            conn.close()

    def encolar(self, post_id: str, ctx: ContextoFiltro, titulo: str, veredicto: VeredictoFiltro) -> None:
        riesgo_val = veredicto.riesgo.score_riesgo_0_100 if veredicto.riesgo else 0.0
        tarifa_val = veredicto.economia.tarifa_efectiva_usd_hr if veredicto.economia else 0.0
        fila = (
            time.time(),
            str(post_id)[:120],
            str(ctx.fuente)[:60],
            str(ctx.plataforma or ctx.fuente)[:60],
            str(titulo)[:180],
            1 if veredicto.aprobado else 0,
            veredicto.decision.value,
            round(veredicto.score_compuesto_0_100, 1),
            round(riesgo_val, 1),
            round(tarifa_val, 2),
            str(veredicto.razon_principal)[:220],
            str(ctx.perfil_nombre or "equilibrado")[:30],
            json.dumps(veredicto.etiquetas[:8], ensure_ascii=False),
        )
        with self._lock:
            self._buffer.append(fila)
            if len(self._buffer) >= 50:
                self._flush_sin_lock()

    def _flush_sin_lock(self) -> int:
        if not self._buffer:
            return 0
        self.asegurar_esquema()
        lote = list(self._buffer)
        self._buffer.clear()
        conn = self._conectar()
        try:
            conn.executemany(
                """
                INSERT INTO aegis_auditoria
                (ts_epoch, post_id, fuente, plataforma, titulo, aprobado, decision, score_0_100, riesgo_0_100, tarifa_eff, razon, perfil, etiquetas_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                lote,
            )
            conn.execute(
                "DELETE FROM aegis_auditoria WHERE id NOT IN (SELECT id FROM aegis_auditoria ORDER BY id DESC LIMIT ?)",
                (self.max_filas,),
            )
            conn.commit()
            return len(lote)
        finally:
            conn.close()

    def flush(self) -> int:
        with self._lock:
            return self._flush_sin_lock()

    def obtener_resumen(self, limite_recientes: int = 40) -> dict[str, Any]:
        self.flush()
        self.asegurar_esquema()
        conn = self._conectar()
        try:
            por_dec = conn.execute(
                "SELECT decision, COUNT(*) FROM aegis_auditoria GROUP BY decision ORDER BY COUNT(*) DESC"
            ).fetchall()
            tot = sum(r[1] for r in por_dec)
            aprob = conn.execute("SELECT COUNT(*) FROM aegis_auditoria WHERE aprobado = 1").fetchone()[0]
            recientes = conn.execute(
                """
                SELECT ts_epoch, fuente, plataforma, titulo, aprobado, decision, score_0_100, riesgo_0_100, tarifa_eff, razon, perfil, etiquetas_json
                FROM aegis_auditoria
                ORDER BY id DESC
                LIMIT ?
                """,
                (limite_recientes,),
            ).fetchall()
            items = []
            for r in recientes:
                try:
                    etq = json.loads(r[11] or "[]")
                except Exception:
                    etq = []
                items.append({
                    "ts": r[0], "fuente": r[1], "plataforma": r[2], "titulo": r[3],
                    "aprobado": bool(r[4]), "decision": r[5], "score": r[6],
                    "riesgo": r[7], "tarifa_eff": r[8], "razon": r[9], "perfil": r[10],
                    "etiquetas": etq,
                })
            return {
                "total_auditadas": tot,
                "total_aprobadas": aprob,
                "tasa_aprobacion_pct": round((aprob / max(1, tot)) * 100.0, 1),
                "por_decision": [[r[0], r[1]] for r in por_dec],
                "recientes": items,
            }
        finally:
            conn.close()


# ==================== CONSTRUCTORES DE CONTEXTO DESDE CONFIG & OFERTA ====================
def _parsear_lista_palabras(val: Any) -> list[str]:
    if not val:
        return []
    if isinstance(val, str):
        return [w.strip() for w in val.split(",") if w.strip()]
    if isinstance(val, (list, tuple, set)):
        return [str(w).strip() for w in val if str(w).strip()]
    return []


def construir_contexto_desde_oferta(item: dict[str, Any], cfg: dict[str, Any]) -> ContextoFiltro:
    perfil_nom = str(cfg.get("aegis_perfil") or "equilibrado").strip().lower()
    perfil = obtener_perfil(perfil_nom)

    idiomas_raw = cfg.get("idiomas_permitidos") or ("en", "es", "mixto")
    idiomas_tup = tuple(str(x).strip().lower() for x in idiomas_raw if str(x).strip()) or ("en", "es", "mixto")

    solo_corto = bool(cfg.get("solo_freelance_corto", False)) or perfil.solo_freelance_corto
    tarifa_cfg = safe_float(cfg.get("tarifa_hora_usd"), 25.0)
    # Piso de tarifa efectiva: 60% de tu tarifa objetivo o el minimo del perfil
    tarifa_min = max(perfil.tarifa_minima_usd_hr, round(tarifa_cfg * 0.58, 1))
    pres_min = max(perfil.presupuesto_minimo_usd, safe_float(cfg.get("presupuesto_minimo_usd"), perfil.presupuesto_minimo_usd))

    return ContextoFiltro(
        fuente=str(item.get("fuente") or ""),
        plataforma=str(item.get("plataforma") or item.get("fuente") or ""),
        sub_o_categoria=str(item.get("fuente") or ""),
        autor=str(item.get("autor") or ""),
        link=str(item.get("link") or ""),
        edad_min=item.get("edad_min"),
        comentarios=item.get("comentarios"),
        monto_api_usd=safe_float(item.get("dinero_local"), 0.0),
        es_busqueda_global=bool(item.get("es_global", False)),
        perfil_nombre=perfil.nombre,
        tarifa_minima_usd_hr=tarifa_min,
        presupuesto_minimo_usd=pres_min,
        solo_freelance_corto=solo_corto,
        idiomas_permitidos=idiomas_tup,
        palabras_blacklist_usuario=_parsear_lista_palabras(cfg.get("palabras_extra_blacklist")),
        palabras_whitelist_usuario=_parsear_lista_palabras(cfg.get("palabras_extra_whitelist")),
    )


# ==================== ORQUESTADOR CENTRAL AEGIS-X (7 CAPAS EN CASCADA) ====================
class PipelineAEGIS:
    """
    Orquestador maestro AEGIS-X v15.0:
      Capa 1: NormalizadorForense (Unicode/homoglifos/HTML/entidades/entropia/idioma)
      Capa 2: MotorTaxonomia (180+ skills, 12 familias tech, 8 no-tech, negaciones, combos)
      Capa 3: ClasificadorIntencion (comprador real vs For Hire camuflado, modalidad, gatekeeper LATAM)
      Capa 4: AnalizadorEconomico (14 monedas, estimador de horas, tarifa efectiva, anti-lowball)
      Capa 5: EscudoSeguridad (40+ heuristicas anti-scam/malware/KYC + matriz correlacion)
      Capa 6: MotorDedup (SimHash 64-bit LSH O(1), Shingles, MinHash, Cross-Author, SQLite WAL)
      Capa 7: MotorAprendizajeCRM (TF-IDF L2 + Naive Bayes Multinomial calibrado desde tu CRM)
    """

    def __init__(
        self,
        db_path: str | None = None,
        usar_sqlite: bool = True,
        guardar_auditoria: bool = True,
    ) -> None:
        self.usar_sqlite = usar_sqlite
        self.guardar_auditoria = guardar_auditoria and usar_sqlite

        self.normalizador = NormalizadorForense()
        self.taxonomia = MotorTaxonomia()
        self.intencion = ClasificadorIntencion()
        self.economia = AnalizadorEconomico()
        self.seguridad = EscudoSeguridad()
        self.dedup = MotorDedup(db_path=db_path, usar_sqlite=usar_sqlite)
        self.ml = MotorAprendizajeCRM(db_path=db_path, usar_sqlite=usar_sqlite)
        self.auditoria = AlmacenAuditoriaSQLite(db_path=db_path) if self.guardar_auditoria else None
        self._db_engine = obtener_db_engine(db_path=db_path) if usar_sqlite else None
        self.bus = obtener_event_bus()
        self.calibrador = CalibradorDinamicoAEGIS(db=self._db_engine, bus=self.bus, usar_sqlite=usar_sqlite)
        self.verdict_cache = CacheVeredictosAEGIS(max_items=512, ttl_seg=900.0)

    @staticmethod
    def _score_intencion_y_competencia(intent: AnalisisIntencion, ctx: ContextoFiltro) -> float:
        base_tipo = {
            TipoIntencion.BOUNTY_PAGO: 86.0,
            TipoIntencion.CONTRATANDO_FREELANCE: 80.0,
            TipoIntencion.CONTRATO_REMOTO: 74.0,
            TipoIntencion.EMPLEO_FULLTIME: 58.0,
        }.get(intent.intencion, 20.0)

        score = base_tipo * (0.72 + 0.28 * intent.confianza)
        if intent.es_urgente:
            score += 6.0
        if intent.es_recurrente:
            score += 8.0

        # Ajuste por frescura y baja competencia (sangre fresca paga mas rapido)
        if ctx.edad_min is not None:
            if ctx.edad_min <= 25:
                score += 9.0
            elif ctx.edad_min <= 90:
                score += 4.5
            elif ctx.edad_min >= 720:
                score -= 5.0

        if ctx.comentarios is not None:
            if ctx.comentarios <= 2:
                score += 6.0
            elif ctx.comentarios <= 6:
                score += 2.0
            elif ctx.comentarios >= 25:
                score -= 9.0
            elif ctx.comentarios >= 14:
                score -= 4.5

        return max(0.0, min(100.0, score))

    @staticmethod
    def _construir_etiquetas(
        tax: ResultadoTaxonomia,
        intent: AnalisisIntencion,
        econ: PerfilEconomico,
        riesgo: AnalisisRiesgo,
        pred: PrediccionAprendizaje,
    ) -> list[str]:
        tags: list[str] = []
        if econ.es_high_ticket:
            tags.append("🐋 HIGH-TICKET")
        if intent.es_urgente:
            tags.append("🚨 URGENTE")
        if intent.es_recurrente:
            tags.append("♻️ RETAINER")
        if tax.combos_activados:
            tags.append("🎯 COMBO-ORO")
        if pred.habilitado and pred.probabilidad_ganar >= 0.68:
            tags.append("🧠 ML-MATCH")
        if riesgo.nivel == NivelRiesgo.PRECAUCION:
            tags.append("⚠️ PRECAUCION")
        elif riesgo.nivel == NivelRiesgo.ALTO:
            tags.append("🚩 RIESGO-ALTO")
        return tags

    def resolver_perfil_efectivo(self, nombre: str | None) -> PerfilAEGIS:
        base = obtener_perfil(nombre)
        aj = self.calibrador.obtener_ajuste(base.nombre)
        if aj is None:
            return base
        return PerfilAEGIS(
            nombre=base.nombre,
            descripcion=base.descripcion,
            umbral_aprobacion=aj.umbral_aprobacion,
            umbral_prioritario=aj.umbral_prioritario,
            max_riesgo_permitido=aj.max_riesgo_permitido,
            bloquear_lowball=base.bloquear_lowball,
            solo_freelance_corto=base.solo_freelance_corto,
            presupuesto_minimo_usd=base.presupuesto_minimo_usd,
            tarifa_minima_usd_hr=base.tarifa_minima_usd_hr,
            peso_taxonomia=aj.peso_taxonomia,
            peso_economia=aj.peso_economia,
            peso_intencion=aj.peso_intencion,
            peso_calidad=aj.peso_calidad,
        )

    def comparar_perfiles(
        self,
        titulo: str,
        cuerpo: str = "",
        tags: str = "",
        flair: str = "",
        ctx_base: ContextoFiltro | None = None,
    ) -> list[dict[str, Any]]:
        base_c = ctx_base or ContextoFiltro()
        salida: list[dict[str, Any]] = []
        for p_nom in PERFILES_AEGIS.keys():
            perf = self.resolver_perfil_efectivo(p_nom)
            ctx_p = ContextoFiltro(
                fuente=base_c.fuente,
                plataforma=base_c.plataforma,
                sub_o_categoria=base_c.sub_o_categoria,
                autor=base_c.autor,
                link=base_c.link,
                edad_min=base_c.edad_min,
                comentarios=base_c.comentarios,
                monto_api_usd=base_c.monto_api_usd,
                es_busqueda_global=base_c.es_busqueda_global,
                perfil_nombre=p_nom,
                tarifa_minima_usd_hr=perf.tarifa_minima_usd_hr,
                presupuesto_minimo_usd=perf.presupuesto_minimo_usd,
                solo_freelance_corto=perf.solo_freelance_corto,
                idiomas_permitidos=base_c.idiomas_permitidos,
                palabras_blacklist_usuario=list(base_c.palabras_blacklist_usuario),
                palabras_whitelist_usuario=list(base_c.palabras_whitelist_usuario),
            )
            v = self.evaluar(
                titulo=titulo, cuerpo=cuerpo, tags=tags, flair=flair,
                post_id=f"cmp_{p_nom}", ctx=ctx_p,
                registrar_dedup=False, simular_sin_dedup=True, registrar_auditoria=False,
            )
            salida.append({
                "perfil": p_nom,
                "aprobado": v.aprobado,
                "decision": v.decision.value,
                "score_0_100": round(v.score_compuesto_0_100, 1),
                "umbral_efectivo": perf.umbral_aprobacion,
                "razon": v.razon_principal,
            })
        return salida

    def calibrar_automatico(self, perfil_nombre: str | None = None, aplicar: bool = True) -> dict[str, Any]:
        if perfil_nombre:
            base = obtener_perfil(perfil_nombre)
            res = self.calibrador.calibrar_perfil(base, aplicar=aplicar)
            if res.get("calibrado") and aplicar:
                self.verdict_cache.limpiar()
            return res
        resultados = {}
        for p_nom, base in PERFILES_AEGIS.items():
            resultados[p_nom] = self.calibrador.calibrar_perfil(base, aplicar=aplicar)
        if aplicar:
            self.verdict_cache.limpiar()
        return {"perfiles": resultados}

    def evaluar(
        self,
        titulo: str,
        cuerpo: str = "",
        tags: str = "",
        flair: str = "",
        post_id: str = "",
        ctx: ContextoFiltro | None = None,
        registrar_dedup: bool = False,
        simular_sin_dedup: bool = False,
        registrar_auditoria: bool = False,
    ) -> VeredictoFiltro:
        clave_vc = ""
        t0 = time.perf_counter()
        ctx = ctx or ContextoFiltro()
        perfil = self.resolver_perfil_efectivo(ctx.perfil_nombre)
        if simular_sin_dedup and not registrar_dedup and not registrar_auditoria:
            clave_vc = construir_clave_veredicto(
                titulo=titulo, cuerpo=cuerpo, tags=tags, flair=flair, ctx=ctx,
                firma_calibracion=self.calibrador.firma_perfil(perfil.nombre),
                firma_ml=self.ml.estado_actual().firma_datos,
            )
            hit_vc = self.verdict_cache.obtener(clave_vc)
            if hit_vc is not None:
                from titan_core.filtro_perfil_gemini import aplicar_perfil_a_veredicto
                return aplicar_perfil_a_veredicto(hit_vc, titulo=titulo, cuerpo=cuerpo, plataforma="", ctx=ctx)
        pid = str(post_id or ctx.link or titulo[:80])

        # --- CAPA 1: NORMALIZACION FORENSE ---
        doc = self.normalizador.normalizar(titulo=titulo, cuerpo=cuerpo, tags=tags, flair=flair)

        # --- CAPA 2: TAXONOMIA 180+ SKILLS ---
        tax = self.taxonomia.evaluar(
            doc,
            sub_o_categoria=ctx.sub_o_categoria or ctx.fuente,
            whitelist_usuario=ctx.palabras_whitelist_usuario,
        )

        # --- CAPA 3: INTENCION, MODALIDAD & GATEKEEPER LATAM ---
        intent = self.intencion.clasificar(doc, ctx=ctx)

        # --- CAPA 4: ECONOMIA MULTI-MONEDA & ESTIMADOR HORAS ---
        econ = self.economia.analizar(doc, tax=tax, intent=intent, ctx=ctx)

        # --- CAPA 5: ESCUDO DE SEGURIDAD ANTI-SCAM ---
        riesgo = self.seguridad.analizar(doc, ctx=ctx, econ=econ, intent=intent)

        # --- CAPA 6: DEDUPLICACION SEMANTICA (SIMHASH 64 LSH) ---
        if simular_sin_dedup:
            dedup_res = ResultadoDedup(es_duplicado=False, simhash_64=self.dedup.preparar_registro(pid, doc, ctx).simhash_64)
        else:
            dedup_res = self.dedup.verificar(pid, doc, ctx=ctx, registrar_si_nuevo=False)

        # --- CAPA 7: MACHINE LEARNING LOCAL DESDE CRM ---
        pred_ml = self.ml.predecir(doc, ctx=ctx, tax=tax, econ=econ)
        senales_ml = generar_senales_aprendizaje(pred_ml)

        # Consolidar todas las senales explicables
        senales_todas: list[SenalDetectada] = []
        senales_todas.extend(tax.senales)
        senales_todas.extend(intent.senales)
        senales_todas.extend(econ.senales)
        senales_todas.extend(riesgo.senales)
        senales_todas.extend(senales_ml)

        # --- SCORE COMPUESTO 0..100 ---
        score_intent = self._score_intencion_y_competencia(intent, ctx)
        score_base = (
            tax.score_normalizado_0_100 * perfil.peso_taxonomia
            + econ.score_economico_0_100 * perfil.peso_economia
            + score_intent * perfil.peso_intencion
            + doc.metricas.score_calidad * perfil.peso_calidad
        )

        # Penalizacion proporcional de riesgo + ajuste ML CRM
        penal_riesgo = riesgo.score_riesgo_0_100 * 0.45
        score_compuesto = max(0.0, min(100.0, round(score_base - penal_riesgo + pred_ml.ajuste_score, 1)))
        etiquetas = self._construir_etiquetas(tax, intent, econ, riesgo, pred_ml)

        # --- PUERTAS DE DECISION (ORDEN FORENSE ESTRICTO) ---
        aprobado = False
        decision = DecisionFiltro.RECHAZADO_CALIDAD
        razon = ""

        es_blacklist_user = any(s.codigo == "SEC_BLACKLIST_USUARIO" for s in riesgo.senales)
        tiene_vip = any(sk.startswith("vip:") for sk in tax.skills_encontradas)

        if dedup_res.es_duplicado:
            decision = DecisionFiltro.RECHAZADO_DUPLICADO
            razon = f"Duplicado ({dedup_res.tipo_duplicado} | hamming={dedup_res.distancia_hamming} | sim={dedup_res.similitud_shingle:.2f})"
        elif es_blacklist_user:
            decision = DecisionFiltro.RECHAZADO_BLACKLIST
            razon = riesgo.razones_bloqueo[0] if riesgo.razones_bloqueo else "Coincidencia con blacklist personalizada"
        elif riesgo.bloqueo_duro or riesgo.score_riesgo_0_100 >= perfil.max_riesgo_permitido:
            decision = DecisionFiltro.RECHAZADO_SEGURIDAD
            razon = riesgo.razones_bloqueo[0] if riesgo.razones_bloqueo else f"Riesgo elevado ({riesgo.score_riesgo_0_100:.0f}/100): {', '.join(riesgo.banderas_rojas[:2])}"
        elif (doc.metricas.chars_titulo + doc.metricas.chars_cuerpo) < 12:
            decision = DecisionFiltro.RECHAZADO_CALIDAD
            razon = "Contenido demasiado corto o vacio"
        elif ctx.idiomas_permitidos and doc.idioma.value not in ctx.idiomas_permitidos and doc.confianza_idioma >= 0.72:
            decision = DecisionFiltro.RECHAZADO_IDIOMA
            razon = f"Idioma no permitido ({doc.idioma.value}, conf={doc.confianza_idioma:.0%})"
        elif intent.bloqueo_geografico:
            decision = DecisionFiltro.RECHAZADO_GEOGRAFIA
            razon = intent.motivo_geografico or "Restriccion geografica o trabajo presencial"
        elif not intent.es_comprador_real:
            decision = DecisionFiltro.RECHAZADO_INTENCION
            razon = f"No es comprador real ({intent.intencion.value})"
        elif (not tax.es_tech) and (not tiene_vip):
            decision = DecisionFiltro.RECHAZADO_NO_TECH
            razon = f"Fuera de nicho tecnico (familia={tax.familia_principal}, score_tech={tax.score_normalizado_0_100:.0f})"
        elif perfil.bloquear_lowball and econ.es_lowball:
            decision = DecisionFiltro.RECHAZADO_ECONOMIA
            razon = f"Oferta lowball ({econ.etiqueta_presupuesto} | ~${econ.tarifa_efectiva_usd_hr:.1f}/hr para {econ.horas_estimadas_min:.0f}-{econ.horas_estimadas_max:.0f}h)"
        elif perfil.nombre == "caza_ballenas" and econ.tipo_tarifa == "fijo" and 0 < econ.presupuesto_max_usd < perfil.presupuesto_minimo_usd:
            decision = DecisionFiltro.RECHAZADO_ECONOMIA
            razon = f"Perfil caza_ballenas exige >=${perfil.presupuesto_minimo_usd:.0f} USD (detectado {econ.etiqueta_presupuesto})"
        elif score_compuesto >= perfil.umbral_prioritario:
            aprobado = True
            decision = DecisionFiltro.APROBADO_PRIORITARIO
            razon = f"Prioritario ({score_compuesto:.1f}/100 | {tax.familia_principal} | {econ.etiqueta_presupuesto})"
        elif score_compuesto >= perfil.umbral_aprobacion:
            aprobado = True
            decision = DecisionFiltro.APROBADO
            razon = f"Aprobado ({score_compuesto:.1f}/100 | {tax.familia_principal} | {econ.etiqueta_presupuesto})"
        elif score_compuesto >= (perfil.umbral_aprobacion - 5.0) and (econ.es_high_ticket or intent.es_urgente or tiene_vip):
            aprobado = True
            decision = DecisionFiltro.REVISION_LIMITE
            razon = f"Rescatado por prioridad ({score_compuesto:.1f}/100 | {', '.join(etiquetas[:2])})"
        else:
            decision = DecisionFiltro.RECHAZADO_CALIDAD
            razon = f"Score compuesto ({score_compuesto:.1f}) por debajo del umbral ({perfil.umbral_aprobacion:.0f}) del perfil {perfil.nombre}"

        # Registrar en Dedup solo si se solicito explicitamente (en dry-run suele ser False)
        if registrar_dedup and not dedup_res.es_duplicado and not simular_sin_dedup:
            self.dedup.registrar(pid, doc, ctx=ctx)

        # Prioridad de cola (0..1000) para ordenar que sube primero a Gemini
        prioridad_cola = int(round(score_compuesto * 8.0))
        if decision == DecisionFiltro.APROBADO_PRIORITARIO:
            prioridad_cola += 120
        if econ.es_high_ticket:
            prioridad_cola += 65
        if intent.es_urgente:
            prioridad_cola += 40
        if intent.intencion in (TipoIntencion.CONTRATANDO_FREELANCE, TipoIntencion.BOUNTY_PAGO):
            prioridad_cola += 45

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        veredicto = VeredictoFiltro(
            aprobado=aprobado,
            decision=decision,
            score_compuesto_0_100=score_compuesto,
            prioridad_cola=max(0, min(1200, prioridad_cola)),
            razon_principal=razon,
            etiquetas=etiquetas,
            documento=doc,
            taxonomia=tax,
            intencion=intent,
            economia=econ,
            riesgo=riesgo,
            dedup=dedup_res,
            aprendizaje=pred_ml,
            senales_todas=senales_todas,
            tiempo_ms=round(elapsed_ms, 3),
        )

        if clave_vc:
            self.verdict_cache.guardar(clave_vc, veredicto)

        if registrar_auditoria and self.auditoria is not None:
            self.auditoria.encolar(pid, ctx, doc.titulo_limpio, veredicto)

        from titan_core.filtro_perfil_gemini import aplicar_perfil_a_veredicto
        return aplicar_perfil_a_veredicto(veredicto, titulo=titulo, cuerpo=cuerpo, plataforma="", ctx=ctx)

    def evaluar_lote_ofertas(
        self,
        ofertas: list[dict[str, Any]],
        cfg: dict[str, Any],
        registrar_dedup_rechazadas: bool = False,
        registrar_auditoria: bool = False,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """
        Pasa un lote completo de ofertas de las 12+ plataformas por las 7 capas de AEGIS-X.
        Enriquece cada oferta aprobada con metadatos forenses y devuelve el desglose de rechazos.
        """
        aprobadas: list[dict[str, Any]] = []
        conteo_decisiones: Counter[str] = Counter()
        t0 = time.perf_counter()

        for item in ofertas:
            ctx = construir_contexto_desde_oferta(item, cfg)
            v = self.evaluar(
                titulo=str(item.get("titulo") or ""),
                cuerpo=str(item.get("texto") or ""),
                tags=str(item.get("tags") or ""),
                flair=str(item.get("flair") or ""),
                post_id=str(item.get("id") or item.get("link") or ""),
                ctx=ctx,
                registrar_dedup=False,
                simular_sin_dedup=False,
                registrar_auditoria=registrar_auditoria,
            )
            conteo_decisiones[v.decision.value] += 1

            if v.aprobado:
                enriquecida = dict(item)
                enriquecida["es_tech"] = True
                enriquecida["aegis_score"] = v.score_compuesto_0_100
                enriquecida["aegis_prioridad"] = v.prioridad_cola
                enriquecida["aegis_decision"] = v.decision.value
                enriquecida["aegis_razon"] = v.razon_principal
                enriquecida["aegis_etiquetas"] = list(v.etiquetas)
                enriquecida["aegis_familia"] = v.taxonomia.familia_principal if v.taxonomia else "general"
                enriquecida["aegis_riesgo"] = v.riesgo.score_riesgo_0_100 if v.riesgo else 0.0
                enriquecida["aegis_banderas"] = list(v.riesgo.banderas_rojas) if v.riesgo else []
                enriquecida["aegis_horas"] = (
                    f"{v.economia.horas_estimadas_min:.0f}-{v.economia.horas_estimadas_max:.0f}h"
                    if v.economia else ""
                )
                enriquecida["aegis_tarifa_eff"] = v.economia.tarifa_efectiva_usd_hr if v.economia else 0.0
                enriquecida["aegis_ml_prob"] = v.aprendizaje.probabilidad_ganar if (v.aprendizaje and v.aprendizaje.habilitado) else None
                enriquecida["aegis_simhash"] = v.dedup.simhash_64 if v.dedup else 0

                if v.economia and v.economia.presupuesto_medio_usd > 0:
                    enriquecida["dinero_local"] = v.economia.presupuesto_medio_usd
                    if not enriquecida.get("presupuesto_txt") or enriquecida.get("presupuesto_txt") in ("Por definir", "Remoto", "Remoto / RSS"):
                        enriquecida["presupuesto_txt"] = v.economia.etiqueta_presupuesto

                if v.etiquetas:
                    enriquecida["prioridad_tag"] = " · ".join(v.etiquetas[:3])

                if v.intencion:
                    if v.intencion.intencion == TipoIntencion.BOUNTY_PAGO:
                        enriquecida["tipo_trabajo"] = "bounty"
                    elif v.intencion.intencion == TipoIntencion.EMPLEO_FULLTIME:
                        enriquecida["tipo_trabajo"] = "remoto"
                    elif v.intencion.intencion in (TipoIntencion.CONTRATANDO_FREELANCE, TipoIntencion.CONTRATO_REMOTO):
                        enriquecida["tipo_trabajo"] = "freelance"

                aprobadas.append(enriquecida)
            else:
                if registrar_dedup_rechazadas and v.decision != DecisionFiltro.RECHAZADO_DUPLICADO:
                    self.dedup.registrar(
                        str(item.get("id") or item.get("link") or ""),
                        v.documento,
                        ctx=ctx,
                    )

        aprobadas.sort(
            key=lambda x: (x.get("aegis_prioridad", 0), x.get("aegis_score", 0), x.get("dinero_local", 0)),
            reverse=True,
        )

        if registrar_dedup_rechazadas:
            self.dedup.flush_db()
        if registrar_auditoria and self.auditoria is not None:
            self.auditoria.flush()

        dur_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        resumen = {
            "evaluadas": len(ofertas),
            "aprobadas": len(aprobadas),
            "rechazadas": len(ofertas) - len(aprobadas),
            "desglose": dict(conteo_decisiones),
            "tiempo_ms": dur_ms,
            "perfil": str(cfg.get("aegis_perfil") or "equilibrado"),
        }
        return aprobadas, resumen

    def registrar_vista_aprobada(self, item: dict[str, Any], cfg: dict[str, Any]) -> None:
        ctx = construir_contexto_desde_oferta(item, cfg)
        doc = self.normalizador.normalizar(
            titulo=str(item.get("titulo") or ""),
            cuerpo=str(item.get("texto") or ""),
            tags=str(item.get("tags") or ""),
        )
        self.dedup.registrar(str(item.get("id") or item.get("link") or ""), doc, ctx=ctx)

    def flush_todo(self) -> None:
        self.dedup.flush_db()
        if self.auditoria is not None:
            self.auditoria.flush()

    def radiografia_dict(self, veredicto: VeredictoFiltro) -> dict[str, Any]:
        base = veredicto.to_dict()
        base["intencion"] = {
            "tipo": veredicto.intencion.intencion.value,
            "modalidad": veredicto.intencion.modalidad.value,
            "confianza": round(veredicto.intencion.confianza, 3),
            "es_comprador_real": veredicto.intencion.es_comprador_real,
            "urgente": veredicto.intencion.es_urgente,
            "recurrente": veredicto.intencion.es_recurrente,
            "bloqueo_geo": veredicto.intencion.bloqueo_geografico,
            "motivo_geo": veredicto.intencion.motivo_geografico,
        } if veredicto.intencion else None
        base["economia"] = {
            "etiqueta": veredicto.economia.etiqueta_presupuesto,
            "moneda": veredicto.economia.moneda_detectada,
            "tipo_tarifa": veredicto.economia.tipo_tarifa,
            "medio_usd": veredicto.economia.presupuesto_medio_usd,
            "horas_min": veredicto.economia.horas_estimadas_min,
            "horas_max": veredicto.economia.horas_estimadas_max,
            "tarifa_eff_usd_hr": veredicto.economia.tarifa_efectiva_usd_hr,
            "high_ticket": veredicto.economia.es_high_ticket,
            "lowball": veredicto.economia.es_lowball,
            "score_0_100": veredicto.economia.score_economico_0_100,
        } if veredicto.economia else None
        base["seguridad"] = {
            "nivel": veredicto.riesgo.nivel.value,
            "riesgo_0_100": veredicto.riesgo.score_riesgo_0_100,
            "bloqueo_duro": veredicto.riesgo.bloqueo_duro,
            "razones": veredicto.riesgo.razones_bloqueo,
            "banderas_rojas": veredicto.riesgo.banderas_rojas,
        } if veredicto.riesgo else None
        base["dedup"] = {
            "duplicado": veredicto.dedup.es_duplicado,
            "tipo": veredicto.dedup.tipo_duplicado,
            "simhash_hex": f"{veredicto.dedup.simhash_64:016x}",
            "hamming": veredicto.dedup.distancia_hamming,
            "shingle": veredicto.dedup.similitud_shingle,
        } if veredicto.dedup else None
        base["ml_crm"] = {
            "habilitado": veredicto.aprendizaje.habilitado,
            "prob_ganar_pct": round(veredicto.aprendizaje.probabilidad_ganar * 100.0, 1),
            "ajuste_score": veredicto.aprendizaje.ajuste_score,
            "muestras": veredicto.aprendizaje.muestras_entrenamiento,
            "impulsoras": veredicto.aprendizaje.palabras_impulsoras,
        } if veredicto.aprendizaje else None
        perf_rad = self.resolver_perfil_efectivo("equilibrado")
        base["contribuciones_capas"] = calcular_contribuciones_capas(
            veredicto,
            peso_tax=perf_rad.peso_taxonomia,
            peso_econ=perf_rad.peso_economia,
            peso_int=perf_rad.peso_intencion,
            peso_cal=perf_rad.peso_calidad,
        )
        base["contrafactuales"] = generar_contrafactuales(
            veredicto,
            umbral_aprobacion=perf_rad.umbral_aprobacion,
            umbral_prioritario=perf_rad.umbral_prioritario,
            max_riesgo=perf_rad.max_riesgo_permitido,
            presupuesto_minimo=perf_rad.presupuesto_minimo_usd,
            tarifa_minima_hr=perf_rad.tarifa_minima_usd_hr,
        )
        return base


def formatear_radiografia_texto(v: VeredictoFiltro) -> str:
    estado = "APROBADO" if v.aprobado else "RECHAZADO"
    lineas = [
        f"=== RADIOGRAFIA AEGIS-X v15.0 [{estado} | {v.decision.value}] ===",
        f"Score Compuesto : {v.score_compuesto_0_100:.1f}/100 | Prioridad Cola: {v.prioridad_cola} | Tiempo: {v.tiempo_ms:.2f} ms",
        f"Razon Principal : {v.razon_principal}",
        f"Etiquetas       : {', '.join(v.etiquetas) or 'Ninguna'}",
    ]
    if v.taxonomia:
        lineas.append(f"Taxonomia Tech  : {v.taxonomia.score_normalizado_0_100:.1f}/100 | Familia: {v.taxonomia.familia_principal} | Skills: {', '.join(v.taxonomia.skills_encontradas[:8])}")
        if v.taxonomia.combos_activados:
            lineas.append(f"Combos de Oro   : {', '.join(v.taxonomia.combos_activados)}")
    if v.intencion:
        lineas.append(f"Intencion       : {v.intencion.intencion.value} ({v.intencion.modalidad.value}) | Comprador={v.intencion.es_comprador_real} | GeoBloq={v.intencion.bloqueo_geografico}")
    if v.economia:
        lineas.append(f"Economia        : {v.economia.etiqueta_presupuesto} | Est: {v.economia.horas_estimadas_min:.0f}-{v.economia.horas_estimadas_max:.0f}h | Eff: ${v.economia.tarifa_efectiva_usd_hr:.1f}/hr | Score={v.economia.score_economico_0_100:.1f}")
    if v.riesgo:
        lineas.append(f"Seguridad       : {v.riesgo.nivel.value.upper()} ({v.riesgo.score_riesgo_0_100:.0f}/100) | Banderas: {', '.join(v.riesgo.banderas_rojas) or 'Limpio'}")
    if v.aprendizaje and v.aprendizaje.habilitado:
        lineas.append(f"ML CRM          : {v.aprendizaje.probabilidad_ganar*100:.1f}% cierre ({v.aprendizaje.ajuste_score:+.1f} pts) | {', '.join(v.aprendizaje.palabras_impulsoras[:4])}")
    return "\n".join(lineas)


_PIPELINE_LOCK = threading.Lock()
_PIPELINE_SINGLETON: PipelineAEGIS | None = None


def obtener_pipeline_aegis() -> PipelineAEGIS:
    global _PIPELINE_SINGLETON
    with _PIPELINE_LOCK:
        if _PIPELINE_SINGLETON is None:
            _PIPELINE_SINGLETON = PipelineAEGIS(usar_sqlite=True, guardar_auditoria=True)
        return _PIPELINE_SINGLETON