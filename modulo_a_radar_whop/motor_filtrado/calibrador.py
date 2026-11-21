from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from modulo_a_radar_whop.motor_filtrado.modelos import (
    DecisionFiltro,
    NivelRiesgo,
    TipoIntencion,
    VeredictoFiltro,
)
from titan_core.db_engine import TitanDBEngine, obtener_db_engine
from titan_core.event_bus import TitanEventBus, obtener_event_bus


# ==================== MODELOS DE CALIBRACION, EXPLICABILIDAD Y DRIFT ====================
@dataclass(slots=True)
class AjustePerfilDinamico:
    perfil: str
    umbral_aprobacion: float
    umbral_prioritario: float
    max_riesgo_permitido: float
    peso_taxonomia: float
    peso_economia: float
    peso_intencion: float
    peso_calidad: float
    f_beta_score: float = 0.0
    precision_est: float = 0.0
    recall_est: float = 0.0
    muestras_usadas: int = 0
    actualizado_ts: float = field(default_factory=time.time)
    activo: bool = True

    def firma(self) -> str:
        raw = (
            f"{self.perfil}:{self.umbral_aprobacion:.2f}:{self.umbral_prioritario:.2f}:"
            f"{self.max_riesgo_permitido:.1f}:{self.peso_taxonomia:.3f}:{self.peso_economia:.3f}:"
            f"{self.peso_intencion:.3f}:{self.peso_calidad:.3f}:{int(self.activo)}"
        )
        return hashlib.blake2b(raw.encode("utf-8"), digest_size=6).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "perfil": self.perfil,
            "umbral_aprobacion": round(self.umbral_aprobacion, 2),
            "umbral_prioritario": round(self.umbral_prioritario, 2),
            "max_riesgo_permitido": round(self.max_riesgo_permitido, 1),
            "pesos": {
                "taxonomia": round(self.peso_taxonomia, 3),
                "economia": round(self.peso_economia, 3),
                "intencion": round(self.peso_intencion, 3),
                "calidad": round(self.peso_calidad, 3),
            },
            "f_beta_score": round(self.f_beta_score, 4),
            "precision_est": round(self.precision_est, 4),
            "recall_est": round(self.recall_est, 4),
            "muestras_usadas": self.muestras_usadas,
            "actualizado_ts": round(self.actualizado_ts, 2),
            "activo": self.activo,
            "firma": self.firma(),
        }


@dataclass(slots=True)
class Contrafactual:
    capa: str
    accion: str
    delta_estimado: str
    factibilidad: str  # alta | media | baja | bloqueante
    impacto_pts: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "capa": self.capa,
            "accion": self.accion,
            "delta_estimado": self.delta_estimado,
            "factibilidad": self.factibilidad,
            "impacto_pts": round(self.impacto_pts, 1),
        }


@dataclass(slots=True)
class ReporteDrift:
    psi: float
    nivel_alerta: str  # normal | moderado | critico
    tasa_aprob_base_pct: float
    tasa_aprob_reciente_pct: float
    delta_tasa_pct: float
    media_score_base: float
    media_score_reciente: float
    n_base: int
    n_reciente: int
    plataformas_anomalas: list[dict[str, Any]] = field(default_factory=list)
    recomendacion: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "psi": round(self.psi, 4),
            "nivel_alerta": self.nivel_alerta,
            "tasa_aprob_base_pct": round(self.tasa_aprob_base_pct, 1),
            "tasa_aprob_reciente_pct": round(self.tasa_aprob_reciente_pct, 1),
            "delta_tasa_pct": round(self.delta_tasa_pct, 1),
            "media_score_base": round(self.media_score_base, 1),
            "media_score_reciente": round(self.media_score_reciente, 1),
            "n_base": self.n_base,
            "n_reciente": self.n_reciente,
            "plataformas_anomalas": self.plataformas_anomalas,
            "recomendacion": self.recomendacion,
        }


# ==================== EXPLICABILIDAD DETERMINISTICA (SHAP-LIKE) + CONTRAFACTUALES ====================
def calcular_contribuciones_capas(
    veredicto: VeredictoFiltro,
    *,
    peso_tax: float = 0.36,
    peso_econ: float = 0.26,
    peso_int: float = 0.22,
    peso_cal: float = 0.16,
    score_intencion_bruto: float | None = None,
) -> dict[str, Any]:
    """
    Descompone exactamente cuantos puntos aporto o resto cada una de las 7 capas
    al score compuesto final (explicabilidad aditiva tipo SHAP).
    """
    sc_tax = veredicto.taxonomia.score_normalizado_0_100 if veredicto.taxonomia else 0.0
    sc_econ = veredicto.economia.score_economico_0_100 if veredicto.economia else 50.0
    sc_cal = veredicto.documento.metricas.score_calidad if veredicto.documento else 50.0
    sc_riesgo = veredicto.riesgo.score_riesgo_0_100 if veredicto.riesgo else 0.0
    aj_ml = veredicto.aprendizaje.ajuste_score if (veredicto.aprendizaje and veredicto.aprendizaje.habilitado) else 0.0

    if score_intencion_bruto is None:
        if veredicto.intencion:
            base_i = {
                TipoIntencion.BOUNTY_PAGO: 86.0,
                TipoIntencion.CONTRATANDO_FREELANCE: 80.0,
                TipoIntencion.CONTRATO_REMOTO: 74.0,
                TipoIntencion.EMPLEO_FULLTIME: 58.0,
            }.get(veredicto.intencion.intencion, 20.0)
            sc_int = min(100.0, base_i * (0.72 + 0.28 * veredicto.intencion.confianza))
        else:
            sc_int = 50.0
    else:
        sc_int = float(score_intencion_bruto)

    ap_tax = round(sc_tax * peso_tax, 2)
    ap_econ = round(sc_econ * peso_econ, 2)
    ap_int = round(sc_int * peso_int, 2)
    ap_cal = round(sc_cal * peso_cal, 2)
    pen_seg = round(-sc_riesgo * 0.45, 2)
    ap_ml = round(aj_ml, 2)

    capas = [
        {"capa": "taxonomia", "score_bruto": round(sc_tax, 1), "peso": round(peso_tax, 3), "aporte_pts": ap_tax},
        {"capa": "economia", "score_bruto": round(sc_econ, 1), "peso": round(peso_econ, 3), "aporte_pts": ap_econ},
        {"capa": "intencion", "score_bruto": round(sc_int, 1), "peso": round(peso_int, 3), "aporte_pts": ap_int},
        {"capa": "calidad", "score_bruto": round(sc_cal, 1), "peso": round(peso_cal, 3), "aporte_pts": ap_cal},
        {"capa": "seguridad", "score_bruto": round(sc_riesgo, 1), "peso": -0.45, "aporte_pts": pen_seg},
        {"capa": "ml_crm", "score_bruto": round(aj_ml, 2), "peso": 1.0, "aporte_pts": ap_ml},
    ]
    capas_ord = sorted(capas, key=lambda x: abs(x["aporte_pts"]), reverse=True)
    return {
        "score_compuesto": round(veredicto.score_compuesto_0_100, 1),
        "suma_aditiva_sin_clamp": round(ap_tax + ap_econ + ap_int + ap_cal + pen_seg + ap_ml, 2),
        "factor_dominante": capas_ord[0]["capa"] if capas_ord else "taxonomia",
        "capas": capas,
    }


def generar_contrafactuales(
    veredicto: VeredictoFiltro,
    *,
    umbral_aprobacion: float = 46.0,
    umbral_prioritario: float = 74.0,
    max_riesgo: float = 64.0,
    presupuesto_minimo: float = 20.0,
    tarifa_minima_hr: float = 15.0,
) -> list[dict[str, Any]]:
    """
    Explicacion contrafactual accionable:
    - Si RECHAZADO: explica el cambio minimo para que la oferta apruebe.
    - Si APROBADO (no prioritario): explica que le falto para subir a APROBADO_PRIORITARIO.
    - Si PRIORITARIO: indica el margen de seguridad antes de caer bajo el umbral.
    """
    cfs: list[Contrafactual] = []
    dec = veredicto.decision
    sc = veredicto.score_compuesto_0_100

    if dec == DecisionFiltro.RECHAZADO_DUPLICADO:
        d = veredicto.dedup
        cfs.append(Contrafactual(
            "dedup",
            f"Oferta ya vista previamente ({d.tipo_duplicado if d else 'exacto'}). Solo pasaria si el cliente publica un alcance nuevo.",
            f"hamming={d.distancia_hamming if d else 0} -> >3",
            "bloqueante",
            0.0,
        ))
        return [c.to_dict() for c in cfs]

    if dec == DecisionFiltro.RECHAZADO_BLACKLIST:
        cfs.append(Contrafactual(
            "blacklist",
            "Coincide con tu lista negra personalizada. Quita el termino de palabras_extra_blacklist si fue un falso positivo.",
            "Remover regla blacklist",
            "alta",
            90.0,
        ))
        return [c.to_dict() for c in cfs]

    if dec == DecisionFiltro.RECHAZADO_SEGURIDAD and veredicto.riesgo:
        r = veredicto.riesgo
        if r.bloqueo_duro:
            cfs.append(Contrafactual(
                "seguridad",
                f"Bloqueo duro anti-estafa/malware ({', '.join(r.banderas_rojas[:2]) or 'regla critica'}). No es recuperable.",
                f"riesgo={r.score_riesgo_0_100:.0f} (duro)",
                "bloqueante",
                -r.score_riesgo_0_100,
            ))
        else:
            exceso = max(1.0, r.score_riesgo_0_100 - max_riesgo + 1.0)
            cfs.append(Contrafactual(
                "seguridad",
                f"Reducir senales de riesgo ({', '.join(r.banderas_rojas[:2])}) en al menos {exceso:.0f} pts para bajar de {max_riesgo:.0f}.",
                f"-{exceso:.0f} riesgo",
                "baja",
                round(exceso * 0.45, 1),
            ))
        return [c.to_dict() for c in cfs]

    if dec == DecisionFiltro.RECHAZADO_GEOGRAFIA and veredicto.intencion:
        cfs.append(Contrafactual(
            "geografia",
            f"Bloqueo geografico/presencial ({veredicto.intencion.motivo_geografico}). Solo seria viable si el cliente acepta remoto Worldwide/LATAM.",
            "Cambiar a remoto global",
            "bloqueante",
            0.0,
        ))
        return [c.to_dict() for c in cfs]

    if dec == DecisionFiltro.RECHAZADO_INTENCION and veredicto.intencion:
        it = veredicto.intencion
        if it.intencion == TipoIntencion.EMPLEO_FULLTIME:
            cfs.append(Contrafactual(
                "intencion",
                "Rechazada por modo 'solo_freelance_corto'. Cambia al perfil 'remoto_pro' o 'equilibrado' para habilitar empleos remotos.",
                "Perfil -> remoto_pro",
                "alta",
                25.0,
            ))
        else:
            cfs.append(Contrafactual(
                "intencion",
                f"Clasificada como '{it.intencion.value}' (no comprador). Requiere senal explicita de contratacion/presupuesto pago.",
                "Anadir intencion [Hiring]/budget",
                "baja",
                20.0,
            ))
        return [c.to_dict() for c in cfs]

    if dec == DecisionFiltro.RECHAZADO_NO_TECH and veredicto.taxonomia:
        tx = veredicto.taxonomia
        falta_neto = max(0.5, 3.0 - tx.score_neto)
        cfs.append(Contrafactual(
            "taxonomia",
            f"Fuera de nicho tecnico (neto={tx.score_neto:.1f}, min=3.0). Necesita skills Python/Scraping/Bots o agregar palabra clave a Whitelist VIP.",
            f"+{falta_neto:.1f} pts taxonomia",
            "baja",
            round(falta_neto * 4.0, 1),
        ))
        return [c.to_dict() for c in cfs]

    if dec == DecisionFiltro.RECHAZADO_ECONOMIA and veredicto.economia:
        ec = veredicto.economia
        h_med = max(1.0, (ec.horas_estimadas_min + ec.horas_estimadas_max) / 2.0)
        obj_usd = max(presupuesto_minimo, round(h_med * tarifa_minima_hr * 0.55, 0))
        falta_usd = max(5.0, obj_usd - ec.presupuesto_max_usd)
        cfs.append(Contrafactual(
            "economia",
            f"Presupuesto insuficiente ({ec.etiqueta_presupuesto} para {ec.horas_estimadas_min:.0f}-{ec.horas_estimadas_max:.0f}h). Subir presupuesto a ~${obj_usd:.0f}+ USD o reducir alcance.",
            f"+${falta_usd:.0f} USD",
            "media",
            22.0,
        ))
        if presupuesto_minimo >= 100.0:
            cfs.append(Contrafactual(
                "perfil",
                "Cambiar de perfil 'caza_ballenas' a 'equilibrado' bajaria el piso de presupuesto minimo.",
                "Perfil -> equilibrado",
                "alta",
                18.0,
            ))
        return [c.to_dict() for c in cfs]

    if not veredicto.aprobado:
        deficit = max(0.5, round(umbral_aprobacion - sc, 1))
        cfs.append(Contrafactual(
            "score_compuesto",
            f"Faltaron {deficit:.1f} puntos para superar el umbral ({umbral_aprobacion:.1f}).",
            f"+{deficit:.1f} pts",
            "media",
            deficit,
        ))
        if veredicto.economia and veredicto.economia.presupuesto_medio_usd <= 0:
            cfs.append(Contrafactual(
                "economia",
                "Publicar un presupuesto claro >=$150 USD sumaria entre +8 y +14 pts al score compuesto.",
                "+$150 USD explicito",
                "alta",
                10.0,
            ))
        if veredicto.taxonomia and not veredicto.taxonomia.combos_activados:
            cfs.append(Contrafactual(
                "taxonomia",
                "Combinar dos stacks complementarios (ej. Python + Playwright o Bot + API) activa Combo de Oro (+10 pts).",
                "Activar combo sinergia",
                "media",
                10.0,
            ))
        if veredicto.riesgo and veredicto.riesgo.score_riesgo_0_100 >= 15.0:
            rec = round(veredicto.riesgo.score_riesgo_0_100 * 0.45, 1)
            cfs.append(Contrafactual(
                "seguridad",
                f"Eliminar banderas de precaucion ({', '.join(veredicto.riesgo.banderas_rojas[:2])}) recuperaria +{rec:.1f} pts.",
                f"+{rec:.1f} pts",
                "media",
                rec,
            ))
        return [c.to_dict() for c in cfs]

    # Ya APROBADO: mostrar que falta para PRIORITARIO o cual es el colchon de seguridad
    if dec != DecisionFiltro.APROBADO_PRIORITARIO:
        falta_prio = max(0.5, round(umbral_prioritario - sc, 1))
        cfs.append(Contrafactual(
            "prioridad",
            f"Aprobado. A solo {falta_prio:.1f} pts de subir a APROBADO_PRIORITARIO ({umbral_prioritario:.1f}).",
            f"+{falta_prio:.1f} pts",
            "alta",
            falta_prio,
        ))
    else:
        margen = round(sc - umbral_aprobacion, 1)
        cfs.append(Contrafactual(
            "margen",
            f"Aprobado Prioritario con colchon solido de +{margen:.1f} pts sobre el umbral de corte.",
            f"margen +{margen:.1f} pts",
            "alta",
            margen,
        ))
    return [c.to_dict() for c in cfs]


# ==================== MOTOR DE CALIBRACION DINAMICA & DRIFT MONITOR ====================
class CalibradorDinamicoAEGIS:
    """
    Subsistema v16.0 de auto-calibracion de AEGIS-X:
    - Persiste ajustes dinamicos de umbrales y pesos por perfil en SQLite ('aegis_calibracion')
    - Optimiza umbrales maximizando F-beta sobre historial etiquetado (leads ganados/negociando vs descartados)
    - Simula impacto retrospectivo What-If sobre 'aegis_auditoria' antes de aplicar un umbral
    - Monitorea Drift de distribucion de scores usando PSI (Population Stability Index)
    """

    BETA_POR_PERFIL: dict[str, float] = {
        "equilibrado": 1.0,
        "francotirador": 0.72,
        "caza_ballenas": 0.60,
        "remoto_pro": 1.15,
    }

    def __init__(
        self,
        db: TitanDBEngine | None = None,
        bus: TitanEventBus | None = None,
        usar_sqlite: bool = True,
    ) -> None:
        self._lock = threading.RLock()
        self.usar_sqlite = usar_sqlite
        self.db = db if db is not None else (obtener_db_engine() if usar_sqlite else None)
        self.bus = bus if bus is not None else obtener_event_bus()
        self._ajustes: dict[str, AjustePerfilDinamico] = {}
        self._esquema_ok = False

        if self.usar_sqlite and self.db is not None:
            self._asegurar_esquema()
            self._cargar_desde_db()

    def _asegurar_esquema(self) -> None:
        if self._esquema_ok or self.db is None:
            return
        with self.db.transaccion() as tx:
            tx.execute(
                """
                CREATE TABLE IF NOT EXISTS aegis_calibracion (
                    perfil TEXT PRIMARY KEY,
                    umbral_aprobacion REAL NOT NULL,
                    umbral_prioritario REAL NOT NULL,
                    max_riesgo_permitido REAL NOT NULL,
                    peso_taxonomia REAL NOT NULL,
                    peso_economia REAL NOT NULL,
                    peso_intencion REAL NOT NULL,
                    peso_calidad REAL NOT NULL,
                    f_beta_score REAL DEFAULT 0,
                    precision_est REAL DEFAULT 0,
                    recall_est REAL DEFAULT 0,
                    muestras_usadas INTEGER DEFAULT 0,
                    activo INTEGER DEFAULT 1,
                    actualizado_ts REAL NOT NULL
                )
                """
            )
            tx.execute(
                """
                CREATE TABLE IF NOT EXISTS aegis_calibracion_historial (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    perfil TEXT NOT NULL,
                    umbral_anterior REAL NOT NULL,
                    umbral_nuevo REAL NOT NULL,
                    f_beta_score REAL DEFAULT 0,
                    muestras INTEGER DEFAULT 0,
                    motivo TEXT DEFAULT '',
                    ts_epoch REAL NOT NULL
                )
                """
            )
        self._esquema_ok = True

    def _cargar_desde_db(self) -> None:
        if self.db is None:
            return
        try:
            rows = self.db.consultar_todos("SELECT * FROM aegis_calibracion")
            with self._lock:
                for r in rows:
                    aj = AjustePerfilDinamico(
                        perfil=str(r["perfil"]),
                        umbral_aprobacion=float(r["umbral_aprobacion"]),
                        umbral_prioritario=float(r["umbral_prioritario"]),
                        max_riesgo_permitido=float(r["max_riesgo_permitido"]),
                        peso_taxonomia=float(r["peso_taxonomia"]),
                        peso_economia=float(r["peso_economia"]),
                        peso_intencion=float(r["peso_intencion"]),
                        peso_calidad=float(r["peso_calidad"]),
                        f_beta_score=float(r.get("f_beta_score") or 0.0),
                        precision_est=float(r.get("precision_est") or 0.0),
                        recall_est=float(r.get("recall_est") or 0.0),
                        muestras_usadas=int(r.get("muestras_usadas") or 0),
                        actualizado_ts=float(r.get("actualizado_ts") or time.time()),
                        activo=bool(r.get("activo", 1)),
                    )
                    self._ajustes[aj.perfil] = aj
        except Exception:
            pass

    def _guardar_ajuste(self, aj: AjustePerfilDinamico, umbral_anterior: float, motivo: str = "") -> None:
        with self._lock:
            self._ajustes[aj.perfil] = aj
        if not self.usar_sqlite or self.db is None:
            return
        self._asegurar_esquema()
        with self.db.transaccion() as tx:
            tx.execute(
                """
                INSERT INTO aegis_calibracion (
                    perfil, umbral_aprobacion, umbral_prioritario, max_riesgo_permitido,
                    peso_taxonomia, peso_economia, peso_intencion, peso_calidad,
                    f_beta_score, precision_est, recall_est, muestras_usadas, activo, actualizado_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(perfil) DO UPDATE SET
                    umbral_aprobacion = excluded.umbral_aprobacion,
                    umbral_prioritario = excluded.umbral_prioritario,
                    max_riesgo_permitido = excluded.max_riesgo_permitido,
                    peso_taxonomia = excluded.peso_taxonomia,
                    peso_economia = excluded.peso_economia,
                    peso_intencion = excluded.peso_intencion,
                    peso_calidad = excluded.peso_calidad,
                    f_beta_score = excluded.f_beta_score,
                    precision_est = excluded.precision_est,
                    recall_est = excluded.recall_est,
                    muestras_usadas = excluded.muestras_usadas,
                    activo = excluded.activo,
                    actualizado_ts = excluded.actualizado_ts
                """,
                (
                    aj.perfil, aj.umbral_aprobacion, aj.umbral_prioritario, aj.max_riesgo_permitido,
                    aj.peso_taxonomia, aj.peso_economia, aj.peso_intencion, aj.peso_calidad,
                    aj.f_beta_score, aj.precision_est, aj.recall_est, aj.muestras_usadas,
                    1 if aj.activo else 0, aj.actualizado_ts,
                ),
            )
            tx.execute(
                """
                INSERT INTO aegis_calibracion_historial (
                    perfil, umbral_anterior, umbral_nuevo, f_beta_score, muestras, motivo, ts_epoch
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (aj.perfil, umbral_anterior, aj.umbral_aprobacion, aj.f_beta_score, aj.muestras_usadas, motivo[:200], aj.actualizado_ts),
            )

    def obtener_ajuste(self, perfil_nombre: str) -> AjustePerfilDinamico | None:
        clave = (perfil_nombre or "equilibrado").strip().lower()
        with self._lock:
            aj = self._ajustes.get(clave)
            return aj if (aj and aj.activo) else None

    def firma_perfil(self, perfil_nombre: str) -> str:
        aj = self.obtener_ajuste(perfil_nombre)
        return aj.firma() if aj else f"static:{(perfil_nombre or 'equilibrado').lower()}"

    def resetear_perfil(self, perfil_nombre: str) -> bool:
        clave = (perfil_nombre or "equilibrado").strip().lower()
        with self._lock:
            ex = self._ajustes.pop(clave, None)
        if self.usar_sqlite and self.db is not None:
            self._asegurar_esquema()
            n = self.db.ejecutar("DELETE FROM aegis_calibracion WHERE perfil = ?", (clave,))
            return n > 0 or (ex is not None)
        return ex is not None

    def guardar_ajuste_manual(
        self,
        perfil_nombre: str,
        *,
        umbral_aprobacion: float,
        umbral_prioritario: float | None = None,
        max_riesgo_permitido: float = 64.0,
        peso_taxonomia: float = 0.36,
        peso_economia: float = 0.26,
        peso_intencion: float = 0.22,
        peso_calidad: float = 0.16,
    ) -> AjustePerfilDinamico:
        clave = (perfil_nombre or "equilibrado").strip().lower()
        u_apr = max(25.0, min(85.0, float(umbral_aprobacion)))
        u_pri = max(u_apr + 10.0, min(95.0, float(umbral_prioritario if umbral_prioritario is not None else u_apr + 24.0)))
        suma_w = max(0.01, float(peso_taxonomia) + float(peso_economia) + float(peso_intencion) + float(peso_calidad))
        prev = self.obtener_ajuste(clave)
        u_prev = prev.umbral_aprobacion if prev else u_apr

        aj = AjustePerfilDinamico(
            perfil=clave,
            umbral_aprobacion=round(u_apr, 2),
            umbral_prioritario=round(u_pri, 2),
            max_riesgo_permitido=round(max(20.0, min(90.0, float(max_riesgo_permitido))), 1),
            peso_taxonomia=round(float(peso_taxonomia) / suma_w, 4),
            peso_economia=round(float(peso_economia) / suma_w, 4),
            peso_intencion=round(float(peso_intencion) / suma_w, 4),
            peso_calidad=round(float(peso_calidad) / suma_w, 4),
            actualizado_ts=time.time(),
            activo=True,
        )
        self._guardar_ajuste(aj, u_prev, motivo="ajuste_manual")
        return aj

    def _leer_muestras_etiquetadas(self) -> list[tuple[float, int, float, float]]:
        """
        Devuelve lista de (score_0_100, etiqueta_0_1, peso_muestra, presupuesto_num)
        combinando leads etiquetados en CRM (ganado/negociando vs descartado).
        """
        if self.db is None:
            return []
        rows = self.db.consultar_todos(
            """
            SELECT estado, score, COALESCE(aegis_score, 0) AS aegis_score,
                   COALESCE(ganancia_usd, 0) AS ganancia_usd,
                   COALESCE(presupuesto_num, 0) AS presupuesto_num
            FROM leads
            WHERE estado IN ('ganado', 'negociando', 'descartado')
            ORDER BY id DESC
            LIMIT 800
            """
        )
        muestras: list[tuple[float, int, float, float]] = []
        for r in rows:
            est = str(r.get("estado") or "")
            sc_aegis = float(r.get("aegis_score") or 0.0)
            sc_llm = float(r.get("score") or 0.0) * 10.0
            sc = sc_aegis if sc_aegis > 0.0 else sc_llm
            if sc <= 0.0:
                continue
            pnum = float(r.get("presupuesto_num") or 0.0)
            if est == "ganado":
                w = 1.8 + 0.4 * math.log1p(max(0.0, float(r.get("ganancia_usd") or 50.0)) / 50.0)
                muestras.append((sc, 1, w, pnum))
            elif est == "negociando":
                muestras.append((sc, 1, 1.15, pnum))
            else:
                muestras.append((sc, 0, 1.25, pnum))
        return muestras

    def calibrar_perfil(
        self,
        perfil_base: Any,
        *,
        muestras_override: list[tuple[float, int, float, float]] | None = None,
        min_muestras: int = 8,
        aplicar: bool = True,
    ) -> dict[str, Any]:
        """
        Busca el umbral de aprobacion optimo maximizando F-beta ponderado,
        con amortiguamiento de seguridad (nunca se mueve mas de +-14 pts respecto al base).
        """
        muestras = muestras_override if muestras_override is not None else self._leer_muestras_etiquetadas()
        n_pos = sum(1 for _, y, _, _ in muestras if y == 1)
        n_neg = sum(1 for _, y, _, _ in muestras if y == 0)

        if len(muestras) < min_muestras or n_pos < 3 or n_neg < 3:
            return {
                "calibrado": False,
                "perfil": perfil_base.nombre,
                "motivo": f"Muestras insuficientes (total={len(muestras)}, pos={n_pos}, neg={n_neg}; minimo {min_muestras} y 3 por clase)",
                "umbral_actual": perfil_base.umbral_aprobacion,
            }

        beta = self.BETA_POR_PERFIL.get(perfil_base.nombre, 1.0)
        beta2 = beta * beta
        lo = max(30.0, perfil_base.umbral_aprobacion - 14.0)
        hi = min(82.0, perfil_base.umbral_aprobacion + 14.0)

        mejor_u = perfil_base.umbral_aprobacion
        mejor_fb = -1.0
        mejor_prec = 0.0
        mejor_rec = 0.0

        # Grid search de alta resolucion (paso 1.0 pt)
        u = lo
        while u <= hi + 0.001:
            tp = fp = fn = 0.0
            for sc, y, w, _ in muestras:
                pred = 1 if sc >= u else 0
                if pred == 1 and y == 1:
                    tp += w
                elif pred == 1 and y == 0:
                    fp += w
                elif pred == 0 and y == 1:
                    fn += w
            prec = tp / max(1e-9, tp + fp)
            rec = tp / max(1e-9, tp + fn)
            fb = ((1.0 + beta2) * prec * rec / max(1e-9, beta2 * prec + rec)) if (prec + rec) > 0 else 0.0
            # Tie-breaker suave hacia el umbral base para estabilidad
            pen_dist = abs(u - perfil_base.umbral_aprobacion) * 0.0005
            if (fb - pen_dist) > mejor_fb:
                mejor_fb = fb - pen_dist
                mejor_u = u
                mejor_prec = prec
                mejor_rec = rec
            u += 1.0

        # Suavizado bayesiano (shrinkage hacia el perfil base cuando hay pocas muestras)
        confianza = min(1.0, len(muestras) / 30.0)
        u_suavizado = round(perfil_base.umbral_aprobacion * (1.0 - confianza) + mejor_u * confianza, 1)

        # Ajuste suave de pesos: si los positivos tienen presupuestos altos fuertes, potenciar ligeramente economia
        pos_pres = [p for _, y, _, p in muestras if y == 1 and p > 0]
        neg_pres = [p for _, y, _, p in muestras if y == 0 and p > 0]
        w_tax = perfil_base.peso_taxonomia
        w_econ = perfil_base.peso_economia
        w_int = perfil_base.peso_intencion
        w_cal = perfil_base.peso_calidad
        if len(pos_pres) >= 3 and len(neg_pres) >= 3:
            prom_p = sum(pos_pres) / len(pos_pres)
            prom_n = sum(neg_pres) / len(neg_pres)
            if prom_p > prom_n * 1.6:
                w_econ = min(0.44, w_econ + 0.04)
                w_cal = max(0.08, w_cal - 0.04)
        s_w = w_tax + w_econ + w_int + w_cal
        w_tax, w_econ, w_int, w_cal = w_tax / s_w, w_econ / s_w, w_int / s_w, w_cal / s_w

        # Umbral prioritario: percentil 75 de los positivos, acotado
        scores_pos = sorted(sc for sc, y, _, _ in muestras if y == 1)
        p75_pos = scores_pos[min(len(scores_pos) - 1, int(len(scores_pos) * 0.72))]
        u_prio = round(max(u_suavizado + 14.0, min(90.0, 0.55 * perfil_base.umbral_prioritario + 0.45 * p75_pos)), 1)

        prev = self.obtener_ajuste(perfil_base.nombre)
        u_anterior = prev.umbral_aprobacion if prev else perfil_base.umbral_aprobacion

        aj = AjustePerfilDinamico(
            perfil=perfil_base.nombre,
            umbral_aprobacion=u_suavizado,
            umbral_prioritario=u_prio,
            max_riesgo_permitido=perfil_base.max_riesgo_permitido,
            peso_taxonomia=round(w_tax, 4),
            peso_economia=round(w_econ, 4),
            peso_intencion=round(w_int, 4),
            peso_calidad=round(w_cal, 4),
            f_beta_score=round(max(0.0, mejor_fb), 4),
            precision_est=round(mejor_prec, 4),
            recall_est=round(mejor_rec, 4),
            muestras_usadas=len(muestras),
            actualizado_ts=time.time(),
            activo=True,
        )

        if aplicar:
            self._guardar_ajuste(aj, u_anterior, motivo=f"auto_fbeta_{beta:.2f}")
            if self.bus is not None:
                self.bus.publicar(
                    "aegis.calibracion.aplicada",
                    {
                        "perfil": aj.perfil,
                        "umbral_anterior": u_anterior,
                        "umbral_nuevo": aj.umbral_aprobacion,
                        "f_beta": aj.f_beta_score,
                        "muestras": aj.muestras_usadas,
                    },
                    origen="aegis_calibrador",
                    nivel="ok",
                )

        return {
            "calibrado": True,
            "aplicado": aplicar,
            "umbral_anterior": u_anterior,
            "ajuste": aj.to_dict(),
        }

    def simular_impacto_umbral(self, nuevo_umbral: float, ventana_ultimas: int = 300) -> dict[str, Any]:
        """Simulador What-If sobre aegis_auditoria: estima cambio en aprobaciones y tokens Gemini."""
        if self.db is None:
            return {"disponible": False, "motivo": "SQLite deshabilitado"}
        try:
            rows = self.db.consultar_todos(
                """
                SELECT aprobado, decision, score_0_100
                FROM aegis_auditoria
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(10, int(ventana_ultimas)),),
            )
        except Exception:
            return {"disponible": False, "motivo": "Tabla aegis_auditoria aun sin crear"}

        if not rows:
            return {"disponible": False, "motivo": "Sin registros de auditoria aun"}

        u = float(nuevo_umbral)
        aprob_actual = sum(1 for r in rows if int(r["aprobado"]) == 1)
        # Decisiones bloqueadas por puertas duras (scam, dedup, geo, no_tech, intencion) no cambian solo por umbral
        puertas_duras = {
            DecisionFiltro.RECHAZADO_DUPLICADO.value,
            DecisionFiltro.RECHAZADO_SEGURIDAD.value,
            DecisionFiltro.RECHAZADO_BLACKLIST.value,
            DecisionFiltro.RECHAZADO_GEOGRAFIA.value,
            DecisionFiltro.RECHAZADO_INTENCION.value,
            DecisionFiltro.RECHAZADO_NO_TECH.value,
            DecisionFiltro.RECHAZADO_IDIOMA.value,
            DecisionFiltro.RECHAZADO_ECONOMIA.value,
        }
        aprob_nuevo = 0
        for r in rows:
            dec = str(r["decision"])
            if dec in puertas_duras:
                continue
            if float(r["score_0_100"] or 0.0) >= u:
                aprob_nuevo += 1

        delta = aprob_nuevo - aprob_actual
        # Cada oferta aprobada consume ~420 tokens estimados en Batch IA
        tokens_delta = delta * 420
        return {
            "disponible": True,
            "muestra": len(rows),
            "nuevo_umbral": round(u, 1),
            "aprobadas_actual": aprob_actual,
            "aprobadas_proyectadas": aprob_nuevo,
            "delta_ofertas": delta,
            "tasa_actual_pct": round((aprob_actual / len(rows)) * 100.0, 1),
            "tasa_proyectada_pct": round((aprob_nuevo / len(rows)) * 100.0, 1),
            "delta_tokens_ia_est": tokens_delta,
        }

    def analizar_drift(self, ventana_reciente: int = 80, ventana_base: int = 240) -> ReporteDrift:
        """
        Monitor de Drift Poblacional (PSI — Population Stability Index) sobre los scores de aegis_auditoria.
        PSI < 0.10: estable | 0.10..0.25: drift moderado | >= 0.25: drift critico (cambio brusco de mercado/spam).
        """
        if self.db is None:
            return ReporteDrift(0.0, "normal", 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0, [], "Sin SQLite activo")

        try:
            rows = self.db.consultar_todos(
                """
                SELECT plataforma, aprobado, decision, score_0_100
                FROM aegis_auditoria
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(20, int(ventana_reciente + ventana_base)),),
            )
        except Exception:
            return ReporteDrift(0.0, "normal", 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0, [], "Sin datos de auditoria aun")

        if len(rows) < 20:
            return ReporteDrift(0.0, "normal", 0.0, 0.0, 0.0, 0.0, 0.0, 0, len(rows), [], "Acumulando historial minimo (20+ ofertas)")

        corte = min(len(rows) // 2, int(ventana_reciente))
        rec = rows[:corte]
        base = rows[corte:]

        # 5 cubetas de score: [0-20), [20-40), [40-60), [60-80), [80-100]
        def _hist5(lista: list[dict[str, Any]]) -> list[float]:
            bins = [0, 0, 0, 0, 0]
            for r in lista:
                sc = max(0.0, min(99.99, float(r.get("score_0_100") or 0.0)))
                bins[int(sc // 20.0)] += 1
            n = max(1, len(lista))
            return [max(0.0001, c / n) for c in bins]

        p_base = _hist5(base)
        p_rec = _hist5(rec)
        psi = sum((pr - pb) * math.log(pr / pb) for pb, pr in zip(p_base, p_rec))

        tasa_base = (sum(1 for r in base if int(r["aprobado"]) == 1) / max(1, len(base))) * 100.0
        tasa_rec = (sum(1 for r in rec if int(r["aprobado"]) == 1) / max(1, len(rec))) * 100.0
        delta_tasa = tasa_rec - tasa_base

        m_base = sum(float(r.get("score_0_100") or 0.0) for r in base) / max(1, len(base))
        m_rec = sum(float(r.get("score_0_100") or 0.0) for r in rec) / max(1, len(rec))

        # Detectar plataformas recientes con tasa de rechazo por seguridad/spam > 45%
        por_plat: dict[str, Counter[str]] = {}
        for r in rec:
            pl = str(r.get("plataforma") or "N/A")
            c = por_plat.setdefault(pl, Counter())
            c["tot"] += 1
            if str(r.get("decision")) == DecisionFiltro.RECHAZADO_SEGURIDAD.value:
                c["sec"] += 1
            if int(r["aprobado"]) == 1:
                c["ok"] += 1

        anomalas: list[dict[str, Any]] = []
        for pl, c in por_plat.items():
            if c["tot"] >= 5 and (c["sec"] / c["tot"]) >= 0.40:
                anomalas.append({
                    "plataforma": pl,
                    "muestras": c["tot"],
                    "scam_pct": round((c["sec"] / c["tot"]) * 100.0, 1),
                    "aprob_pct": round((c["ok"] / c["tot"]) * 100.0, 1),
                })

        if psi >= 0.25 or abs(delta_tasa) >= 22.0 or anomalas:
            nivel = "critico"
            reco = "Distribucion de ofertas cambio bruscamente. Ejecuta recalibracion o revisa las plataformas con alto spam."
        elif psi >= 0.10 or abs(delta_tasa) >= 12.0:
            nivel = "moderado"
            reco = "Variacion moderada en calidad de leads recientes. Sugerido revisar simulador What-If."
        else:
            nivel = "normal"
            reco = "Flujo estable: los umbrales actuales estan bien calibrados."

        rep = ReporteDrift(
            psi=psi,
            nivel_alerta=nivel,
            tasa_aprob_base_pct=tasa_base,
            tasa_aprob_reciente_pct=tasa_rec,
            delta_tasa_pct=delta_tasa,
            media_score_base=m_base,
            media_score_reciente=m_rec,
            n_base=len(base),
            n_reciente=len(rec),
            plataformas_anomalas=anomalas,
            recomendacion=reco,
        )

        if nivel == "critico" and self.bus is not None:
            self.bus.publicar(
                "aegis.drift.detectado",
                {"psi": round(psi, 4), "delta_tasa_pct": round(delta_tasa, 1), "anomalas": len(anomalas)},
                origen="aegis_calibrador",
                nivel="warn",
            )
        return rep

    def resumen_estado(self) -> dict[str, Any]:
        with self._lock:
            activos = {k: v.to_dict() for k, v in self._ajustes.items()}
        hist: list[dict[str, Any]] = []
        if self.usar_sqlite and self.db is not None:
            self._asegurar_esquema()
            hist = self.db.consultar_todos(
                "SELECT perfil, umbral_anterior, umbral_nuevo, f_beta_score, muestras, motivo, ts_epoch FROM aegis_calibracion_historial ORDER BY id DESC LIMIT 15"
            )
        return {
            "ajustes_activos": activos,
            "historial": hist,
            "drift": self.analizar_drift().to_dict(),
        }