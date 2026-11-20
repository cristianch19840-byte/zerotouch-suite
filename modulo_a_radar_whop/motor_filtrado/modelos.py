from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class DecisionFiltro(str, Enum):
    APROBADO_PRIORITARIO = "aprobado_prioritario"
    APROBADO = "aprobado"
    REVISION_LIMITE = "revision_limite"
    RECHAZADO_NO_TECH = "rechazado_no_tech"
    RECHAZADO_INTENCION = "rechazado_intencion"
    RECHAZADO_ECONOMIA = "rechazado_economia"
    RECHAZADO_SEGURIDAD = "rechazado_seguridad"
    RECHAZADO_DUPLICADO = "rechazado_duplicado"
    RECHAZADO_GEOGRAFIA = "rechazado_geografia"
    RECHAZADO_IDIOMA = "rechazado_idioma"
    RECHAZADO_BLACKLIST = "rechazado_blacklist"
    RECHAZADO_CALIDAD = "rechazado_calidad"


class NivelRiesgo(str, Enum):
    SEGURO = "seguro"
    BAJO = "bajo"
    PRECAUCION = "precaucion"
    ALTO = "alto"
    BLOQUEO_DURO = "bloqueo_duro"


class TipoIntencion(str, Enum):
    CONTRATANDO_FREELANCE = "contratando_freelance"
    BOUNTY_PAGO = "bounty_pago"
    CONTRATO_REMOTO = "contrato_remoto"
    EMPLEO_FULLTIME = "empleo_fulltime"
    OFRECIENDO_SERVICIOS = "ofreciendo_servicios"
    SOPORTE_O_DUDA = "soporte_o_duda"
    SPAM_O_PROMO = "spam_o_promo"
    INDETERMINADO = "indeterminado"


class ModalidadTrabajo(str, Enum):
    PROYECTO_PUNTUAL = "proyecto_puntual"
    POR_HORA = "por_hora"
    RETAINER_MENSUAL = "retainer_mensual"
    BOUNTY = "bounty"
    FULL_TIME_REMOTO = "full_time_remoto"
    PRESENCIAL_HIBRIDO = "presencial_hibrido"
    DESCONOCIDA = "desconocida"


class IdiomaDetectado(str, Enum):
    EN = "en"
    ES = "es"
    PT = "pt"
    FR = "fr"
    DE = "de"
    MIXTO = "mixto"
    OTRO = "otro"


class CategoriaSenal(str, Enum):
    TAXONOMIA_TECH = "taxonomia_tech"
    TAXONOMIA_NO_TECH = "taxonomia_no_tech"
    SINERGIA_COMBO = "sinergia_combo"
    INTENCION = "intencion"
    ECONOMIA = "economia"
    SEGURIDAD = "seguridad"
    CALIDAD_TEXTO = "calidad_texto"
    DEDUP = "dedup"
    APRENDIZAJE_CRM = "aprendizaje_crm"
    GEOGRAFIA = "geografia"


@dataclass(slots=True)
class SenalDetectada:
    codigo: str
    categoria: CategoriaSenal
    descripcion: str
    peso: float
    evidencia: str = ""
    zona: str = "cuerpo"  # titulo | cuerpo | tags | metadata
    bloqueante: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "codigo": self.codigo,
            "categoria": self.categoria.value,
            "descripcion": self.descripcion,
            "peso": round(self.peso, 2),
            "evidencia": self.evidencia[:140],
            "zona": self.zona,
            "bloqueante": self.bloqueante,
        }


@dataclass(slots=True)
class EntidadesExtraidas:
    urls: list[str] = field(default_factory=list)
    dominios: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    handles_sociales: list[str] = field(default_factory=list)
    repos_github: list[str] = field(default_factory=list)
    canales_contacto_externo: list[str] = field(default_factory=list)
    acortadores_detectados: list[str] = field(default_factory=list)
    plataformas_mencionadas: list[str] = field(default_factory=list)

    def tiene_contacto_fuera_plataforma(self) -> bool:
        return bool(self.canales_contacto_externo or self.emails)


@dataclass(slots=True)
class MetricasTexto:
    chars_titulo: int = 0
    chars_cuerpo: int = 0
    palabras_totales: int = 0
    palabras_unicas: int = 0
    ratio_mayusculas: float = 0.0
    ratio_digitos: float = 0.0
    ratio_puntuacion: float = 0.0
    entropia_shannon: float = 0.0
    diversidad_lexica: float = 0.0
    cantidad_lineas: int = 0
    tiene_vinetas: bool = False
    tiene_bloque_codigo: bool = False
    homoglifos_reemplazados: int = 0
    chars_invisibles_eliminados: int = 0
    evasion_espaciada_detectada: bool = False
    score_calidad: float = 50.0


@dataclass(slots=True)
class DocumentoNormalizado:
    titulo_original: str
    cuerpo_original: str
    tags_original: str
    flair_original: str
    titulo_limpio: str
    cuerpo_limpio: str
    tags_limpio: str
    flair_limpio: str
    texto_unificado: str
    texto_busqueda: str
    texto_sin_acentos: str
    tokens_titulo: list[str] = field(default_factory=list)
    tokens_cuerpo: list[str] = field(default_factory=list)
    tokens_significativos: list[str] = field(default_factory=list)
    idioma: IdiomaDetectado = IdiomaDetectado.EN
    confianza_idioma: float = 0.0
    entidades: EntidadesExtraidas = field(default_factory=EntidadesExtraidas)
    metricas: MetricasTexto = field(default_factory=MetricasTexto)

    def resumen_compacto(self) -> dict[str, Any]:
        return {
            "idioma": self.idioma.value,
            "confianza_idioma": round(self.confianza_idioma, 2),
            "palabras": self.metricas.palabras_totales,
            "entropia": round(self.metricas.entropia_shannon, 2),
            "calidad": round(self.metricas.score_calidad, 1),
            "homoglifos": self.metricas.homoglifos_reemplazados,
            "invisibles": self.metricas.chars_invisibles_eliminados,
            "dominios": self.entidades.dominios[:5],
            "contacto_externo": self.entidades.canales_contacto_externo[:4],
        }


@dataclass(slots=True)
class MatchTaxonomia:
    clave: str
    familia: str
    es_tech: bool
    peso_base: float
    peso_efectivo: float
    zona: str
    fragmento: str
    negado: bool = False


@dataclass(slots=True)
class ResultadoTaxonomia:
    es_tech: bool = False
    score_tech_bruto: float = 0.0
    score_penalidad_bruto: float = 0.0
    score_sinergias: float = 0.0
    score_neto: float = 0.0
    score_normalizado_0_100: float = 0.0
    familia_principal: str = "general"
    familias_detectadas: dict[str, float] = field(default_factory=dict)
    familias_no_tech: dict[str, float] = field(default_factory=dict)
    combos_activados: list[str] = field(default_factory=list)
    skills_encontradas: list[str] = field(default_factory=list)
    no_tech_encontradas: list[str] = field(default_factory=list)
    matches_negados: list[str] = field(default_factory=list)
    matches_detalle: list[MatchTaxonomia] = field(default_factory=list)
    senales: list[SenalDetectada] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "es_tech": self.es_tech,
            "score_neto": round(self.score_neto, 2),
            "score_0_100": round(self.score_normalizado_0_100, 1),
            "familia_principal": self.familia_principal,
            "combos": self.combos_activados,
            "skills": self.skills_encontradas[:15],
            "no_tech": self.no_tech_encontradas[:10],
            "negados": self.matches_negados[:8],
            "familias_tech": {k: round(v, 2) for k, v in self.familias_detectadas.items()},
        }


@dataclass(slots=True)
class AnalisisIntencion:
    intencion: TipoIntencion = TipoIntencion.INDETERMINADO
    modalidad: ModalidadTrabajo = ModalidadTrabajo.DESCONOCIDA
    confianza: float = 0.0
    es_comprador_real: bool = False
    es_urgente: bool = False
    es_recurrente: bool = False
    bloqueo_geografico: bool = False
    motivo_geografico: str = ""
    senales: list[SenalDetectada] = field(default_factory=list)


@dataclass(slots=True)
class PerfilEconomico:
    presupuesto_min_usd: float = 0.0
    presupuesto_max_usd: float = 0.0
    presupuesto_medio_usd: float = 0.0
    moneda_detectada: str = "USD"
    tipo_tarifa: str = "desconocido"  # fijo | hora | mensual | anual | desconocido
    horas_estimadas_min: float = 0.0
    horas_estimadas_max: float = 0.0
    tarifa_efectiva_usd_hr: float = 0.0
    es_high_ticket: bool = False
    es_lowball: bool = False
    score_economico_0_100: float = 50.0
    etiqueta_presupuesto: str = "Por definir"
    senales: list[SenalDetectada] = field(default_factory=list)


@dataclass(slots=True)
class AnalisisRiesgo:
    nivel: NivelRiesgo = NivelRiesgo.SEGURO
    score_riesgo_0_100: float = 0.0
    bloqueo_duro: bool = False
    razones_bloqueo: list[str] = field(default_factory=list)
    banderas_rojas: list[str] = field(default_factory=list)
    senales: list[SenalDetectada] = field(default_factory=list)


@dataclass(slots=True)
class ResultadoDedup:
    es_duplicado: bool = False
    tipo_duplicado: str = ""  # exacto_id | exacto_link | simhash | shingle | cross_author
    simhash_64: int = 0
    distancia_hamming: int = 64
    similitud_shingle: float = 0.0
    match_previo_id: str = ""


@dataclass(slots=True)
class PrediccionAprendizaje:
    habilitado: bool = False
    probabilidad_ganar: float = 0.5
    ajuste_score: float = 0.0
    muestras_entrenamiento: int = 0
    palabras_impulsoras: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ContextoFiltro:
    fuente: str = ""
    plataforma: str = ""
    sub_o_categoria: str = ""
    autor: str = ""
    link: str = ""
    edad_min: int | None = None
    comentarios: int | None = None
    monto_api_usd: float = 0.0
    es_busqueda_global: bool = False
    perfil_nombre: str = "equilibrado"
    tarifa_minima_usd_hr: float = 15.0
    presupuesto_minimo_usd: float = 20.0
    solo_freelance_corto: bool = False
    idiomas_permitidos: tuple[str, ...] = ("en", "es", "mixto")
    palabras_blacklist_usuario: list[str] = field(default_factory=list)
    palabras_whitelist_usuario: list[str] = field(default_factory=list)


@dataclass(slots=True)
class VeredictoFiltro:
    aprobado: bool
    decision: DecisionFiltro
    score_compuesto_0_100: float
    prioridad_cola: int
    razon_principal: str
    etiquetas: list[str] = field(default_factory=list)
    documento: DocumentoNormalizado | None = None
    taxonomia: ResultadoTaxonomia | None = None
    intencion: AnalisisIntencion | None = None
    economia: PerfilEconomico | None = None
    riesgo: AnalisisRiesgo | None = None
    dedup: ResultadoDedup | None = None
    aprendizaje: PrediccionAprendizaje | None = None
    senales_todas: list[SenalDetectada] = field(default_factory=list)
    tiempo_ms: float = 0.0
    timestamp_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "aprobado": self.aprobado,
            "decision": self.decision.value,
            "score_0_100": round(self.score_compuesto_0_100, 1),
            "prioridad_cola": self.prioridad_cola,
            "razon_principal": self.razon_principal,
            "etiquetas": self.etiquetas,
            "tiempo_ms": round(self.tiempo_ms, 2),
            "documento": self.documento.resumen_compacto() if self.documento else None,
            "taxonomia": self.taxonomia.to_dict() if self.taxonomia else None,
            "senales_top": [s.to_dict() for s in sorted(self.senales_todas, key=lambda x: abs(x.peso), reverse=True)[:12]],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)