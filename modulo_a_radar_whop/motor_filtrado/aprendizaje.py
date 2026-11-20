from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from core_ia import DB_PATH, safe_float
from modulo_a_radar_whop.motor_filtrado.modelos import (
    CategoriaSenal,
    ContextoFiltro,
    DocumentoNormalizado,
    PerfilEconomico,
    PrediccionAprendizaje,
    ResultadoTaxonomia,
    SenalDetectada,
)

# ==================== STOPWORDS & CONSTANTES ML ====================
STOPWORDS_ML = {
    "the", "and", "for", "with", "that", "this", "from", "have", "will", "are",
    "you", "your", "our", "can", "all", "not", "but", "what", "when", "who",
    "how", "out", "about", "into", "more", "some", "any", "been", "was", "were",
    "they", "their", "them", "just", "also", "need", "want", "looking", "help",
    "please", "thanks", "hello", "hey", "hi", "there", "would", "could", "should",
    "project", "work", "job", "task", "hiring", "paid", "someone", "developer",
    "para", "con", "que", "los", "las", "una", "uno", "por", "como", "pero",
    "mas", "del", "este", "esta", "eso", "aqui", "muy", "sin", "sobre", "entre",
    "busco", "necesito", "hola", "gracias", "proyecto", "trabajo",
}

REGEX_TOKEN_ML = re.compile(r"[a-z0-9][a-z0-9+#.\-]{1,28}")


@dataclass(slots=True)
class MuestraCRM:
    muestra_id: str
    etiqueta: int  # 1 = positivo (ganado/negociando), 0 = negativo (descartado)
    peso: float
    features: dict[str, float]
    plataforma: str = ""
    categoria: str = ""
    ganancia_usd: float = 0.0
    estado_origen: str = ""
    edad_dias: float = 0.0


@dataclass(slots=True)
class MetricasValidacionCV:
    folds: int = 0
    muestras_totales: int = 0
    muestras_pos: int = 0
    muestras_neg: int = 0
    accuracy: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1_score: float = 0.0
    brier_score: float = 0.25
    confiable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "folds": self.folds,
            "muestras_totales": self.muestras_totales,
            "muestras_pos": self.muestras_pos,
            "muestras_neg": self.muestras_neg,
            "accuracy": round(self.accuracy, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1_score": round(self.f1_score, 4),
            "brier_score": round(self.brier_score, 4),
            "confiable": self.confiable,
        }


@dataclass(slots=True)
class EstadoModeloNB:
    habilitado: bool = False
    version: str = "aegis_nb_v15"
    firma_datos: str = ""
    entrenado_ts: float = 0.0
    muestras_pos: int = 0
    muestras_neg: int = 0
    peso_total_pos: float = 0.0
    peso_total_neg: float = 0.0
    prior_log_pos: float = -0.6931
    prior_log_neg: float = -0.6931
    alpha: float = 1.0
    temperatura: float = 1.65
    idf: dict[str, float] = field(default_factory=dict)
    log_prob_pos: dict[str, float] = field(default_factory=dict)
    log_prob_neg: dict[str, float] = field(default_factory=dict)
    default_log_pos: float = -8.0
    default_log_neg: float = -8.0
    vocab_size: int = 0
    cv_f1: float = 0.0

    @property
    def muestras_totales(self) -> int:
        return self.muestras_pos + self.muestras_neg

    def to_dict(self) -> dict[str, Any]:
        return {
            "habilitado": self.habilitado,
            "version": self.version,
            "firma_datos": self.firma_datos,
            "entrenado_ts": self.entrenado_ts,
            "muestras_pos": self.muestras_pos,
            "muestras_neg": self.muestras_neg,
            "peso_total_pos": round(self.peso_total_pos, 4),
            "peso_total_neg": round(self.peso_total_neg, 4),
            "prior_log_pos": round(self.prior_log_pos, 6),
            "prior_log_neg": round(self.prior_log_neg, 6),
            "alpha": self.alpha,
            "temperatura": self.temperatura,
            "idf": self.idf,
            "log_prob_pos": self.log_prob_pos,
            "log_prob_neg": self.log_prob_neg,
            "default_log_pos": round(self.default_log_pos, 6),
            "default_log_neg": round(self.default_log_neg, 6),
            "vocab_size": self.vocab_size,
            "cv_f1": round(self.cv_f1, 4),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EstadoModeloNB:
        return cls(
            habilitado=bool(d.get("habilitado", False)),
            version=str(d.get("version", "aegis_nb_v15")),
            firma_datos=str(d.get("firma_datos", "")),
            entrenado_ts=float(d.get("entrenado_ts", 0.0)),
            muestras_pos=int(d.get("muestras_pos", 0)),
            muestras_neg=int(d.get("muestras_neg", 0)),
            peso_total_pos=float(d.get("peso_total_pos", 0.0)),
            peso_total_neg=float(d.get("peso_total_neg", 0.0)),
            prior_log_pos=float(d.get("prior_log_pos", -0.6931)),
            prior_log_neg=float(d.get("prior_log_neg", -0.6931)),
            alpha=float(d.get("alpha", 1.0)),
            temperatura=float(d.get("temperatura", 1.65)),
            idf={str(k): float(v) for k, v in (d.get("idf") or {}).items()},
            log_prob_pos={str(k): float(v) for k, v in (d.get("log_prob_pos") or {}).items()},
            log_prob_neg={str(k): float(v) for k, v in (d.get("log_prob_neg") or {}).items()},
            default_log_pos=float(d.get("default_log_pos", -8.0)),
            default_log_neg=float(d.get("default_log_neg", -8.0)),
            vocab_size=int(d.get("vocab_size", 0)),
            cv_f1=float(d.get("cv_f1", 0.0)),
        )


# ==================== EXTRACTOR DE FEATURES ENRIQUECIDAS ====================
def _bucket_presupuesto(monto_usd: float) -> str:
    if monto_usd <= 0:
        return "sin_monto"
    if monto_usd < 45:
        return "micro"
    if monto_usd < 150:
        return "medio"
    if monto_usd < 400:
        return "alto"
    return "ballena"


def _tokenizar_texto_ml(texto: str) -> list[str]:
    if not texto:
        return []
    raw = REGEX_TOKEN_ML.findall(texto.lower())
    return [t for t in raw if len(t) >= 3 and not t.isdigit() and t not in STOPWORDS_ML]


def extraer_features_texto(
    titulo: str,
    cuerpo: str = "",
    plataforma: str = "",
    categoria: str = "",
    tipo_trabajo: str = "",
    presupuesto_usd: float = 0.0,
    familia_tech: str = "",
    combos: list[str] | None = None,
    extras: list[str] | None = None,
) -> dict[str, float]:
    """
    Construye el vector disperso de frecuencias crudas (TF ponderado por zona):
    - Unigramas y bigramas de titulo (peso 1.8x y 1.5x)
    - Unigramas y bigramas de cuerpo (peso 1.0x y 0.85x)
    - Metadatos categoricos discretizados (plataforma, categoria, rango USD, combos)
    """
    conteo: dict[str, float] = defaultdict(float)

    toks_t = _tokenizar_texto_ml(titulo)[:32]
    toks_c = _tokenizar_texto_ml(cuerpo)[:160]

    for t in toks_t:
        conteo[t] += 1.8
    for i in range(len(toks_t) - 1):
        bg = f"{toks_t[i]}_{toks_t[i + 1]}"
        conteo[bg] += 1.5

    for t in toks_c:
        conteo[t] += 1.0
    for i in range(len(toks_c) - 1):
        bg = f"{toks_c[i]}_{toks_c[i + 1]}"
        conteo[bg] += 0.85

    plat_c = re.sub(r"[^a-z0-9_]", "", (plataforma or "").lower().replace("r/", ""))
    if plat_c:
        conteo[f"plat:{plat_c}"] += 1.6

    cat_c = re.sub(r"[^a-z0-9_]", "", (categoria or "").lower())
    if cat_c:
        conteo[f"cat:{cat_c}"] += 1.5

    tipo_c = re.sub(r"[^a-z0-9_]", "", (tipo_trabajo or "").lower())
    if tipo_c:
        conteo[f"tipo:{tipo_c}"] += 1.2

    fam_c = re.sub(r"[^a-z0-9_]", "", (familia_tech or "").lower())
    if fam_c and not fam_c.startswith("no_tech"):
        conteo[f"fam:{fam_c}"] += 1.4

    conteo[f"usd:{_bucket_presupuesto(presupuesto_usd)}"] += 1.2

    for cb in (combos or ())[:6]:
        conteo[f"combo:{cb.lower()}"] += 1.7

    for ex in (extras or ())[:8]:
        conteo[f"meta:{ex.lower()}"] += 1.1

    return dict(conteo)


def extraer_features_desde_doc(
    doc: DocumentoNormalizado,
    ctx: ContextoFiltro | None = None,
    tax: ResultadoTaxonomia | None = None,
    econ: PerfilEconomico | None = None,
) -> dict[str, float]:
    ctx = ctx or ContextoFiltro()
    extras: list[str] = []
    if doc.metricas.tiene_vinetas:
        extras.append("vinetas")
    if doc.entidades.repos_github:
        extras.append("github_repo")
    if econ and econ.es_high_ticket:
        extras.append("high_ticket")
    if econ and econ.es_lowball:
        extras.append("lowball")

    monto = econ.presupuesto_medio_usd if econ else ctx.monto_api_usd
    tipo = "bounty" if "github" in (ctx.plataforma or "").lower() else (
        "remoto" if any(p in (ctx.plataforma or "").lower() for p in ("remoteok", "wwr", "remotive", "jobicy", "himalayas", "workingnomads", "arbeitnow")) else "freelance"
    )
    return extraer_features_texto(
        titulo=doc.titulo_limpio,
        cuerpo=doc.cuerpo_limpio,
        plataforma=ctx.plataforma or ctx.fuente,
        categoria=tax.familia_principal if tax else "",
        tipo_trabajo=tipo,
        presupuesto_usd=monto,
        familia_tech=tax.familia_principal if tax else "",
        combos=tax.combos_activados if tax else [],
        extras=extras,
    )


def _vectorizar_tfidf_l2(features_raw: dict[str, float], idf: dict[str, float], idf_default: float = 1.0) -> dict[str, float]:
    """Sublinear TF scaling (1 + log(tf)) * IDF + normalizacion L2 para invarianza a longitud del texto."""
    if not features_raw:
        return {}
    vec: dict[str, float] = {}
    norm_sq = 0.0
    for tok, tf in features_raw.items():
        if tf <= 0.0:
            continue
        w = (1.0 + math.log(tf)) * idf.get(tok, idf_default)
        vec[tok] = w
        norm_sq += w * w

    if norm_sq <= 0.0:
        return {}
    inv_norm = 1.0 / math.sqrt(norm_sq)
    # Multiplicamos por constante de escala (6.0) para que las cuentas en NB mantengan resolucion clara
    escala = 6.0 * inv_norm
    return {k: v * escala for k, v in vec.items()}


def _dias_desde_fecha(fecha_str: str | None) -> float:
    if not fecha_str:
        return 0.0
    s = str(fecha_str).strip().replace("Z", "+00:00")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s[:19], fmt).replace(tzinfo=timezone.utc)
            return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0)
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0)
    except Exception:
        return 0.0


def _peso_decaimiento_temporal(edad_dias: float, half_life_dias: float = 90.0) -> float:
    return math.exp(-math.log(2.0) * max(0.0, edad_dias) / max(7.0, half_life_dias))


# ==================== NUCLEO MATEMATICO NAIVE BAYES MULTINOMIAL + TF-IDF ====================
def entrenar_nb_en_memoria(
    muestras: list[MuestraCRM],
    alpha: float = 1.0,
    min_df: int = 1,
    max_vocab: int = 2500,
    temperatura: float = 1.65,
    firma_datos: str = "",
) -> EstadoModeloNB:
    pos_list = [m for m in muestras if m.etiqueta == 1]
    neg_list = [m for m in muestras if m.etiqueta == 0]

    estado = EstadoModeloNB(
        habilitado=False,
        firma_datos=firma_datos,
        entrenado_ts=time.time(),
        muestras_pos=len(pos_list),
        muestras_neg=len(neg_list),
        alpha=alpha,
        temperatura=temperatura,
    )

    if len(pos_list) < 2 or len(neg_list) < 2:
        return estado

    n_docs = len(muestras)

    # 1. Calcular Document Frequency (DF) y construir vocabulario filtrado
    df: Counter[str] = Counter()
    for m in muestras:
        for tok in m.features.keys():
            df[tok] += 1

    # Filtrar terminos con df >= min_df (y si sobra vocabulario, conservar los mas informativos por frecuencia moderada)
    vocab_cands = [tok for tok, cnt in df.items() if cnt >= min_df]
    if len(vocab_cands) > max_vocab:
        vocab_cands.sort(key=lambda t: (df[t], len(t)), reverse=True)
        vocab_cands = vocab_cands[:max_vocab]
    vocab = set(vocab_cands)
    if not vocab:
        return estado

    # 2. Calcular IDF suavizado
    idf: dict[str, float] = {
        tok: round(math.log((1.0 + n_docs) / (1.0 + df[tok])) + 1.0, 5)
        for tok in vocab
    }

    # 3. Acumular pesos TF-IDF L2 por clase (ponderados por valor economico y recencia)
    sum_pos: dict[str, float] = defaultdict(float)
    sum_neg: dict[str, float] = defaultdict(float)
    total_feat_pos = 0.0
    total_feat_neg = 0.0
    peso_docs_pos = 0.0
    peso_docs_neg = 0.0

    for m in muestras:
        feats_filtradas = {k: v for k, v in m.features.items() if k in vocab}
        vec = _vectorizar_tfidf_l2(feats_filtradas, idf)
        w_doc = max(0.1, float(m.peso))
        if m.etiqueta == 1:
            peso_docs_pos += w_doc
            for tok, val in vec.items():
                inc = val * w_doc
                sum_pos[tok] += inc
                total_feat_pos += inc
        else:
            peso_docs_neg += w_doc
            for tok, val in vec.items():
                inc = val * w_doc
                sum_neg[tok] += inc
                total_feat_neg += inc

    v_size = len(vocab)
    denom_pos = total_feat_pos + alpha * v_size
    denom_neg = total_feat_neg + alpha * v_size

    log_prob_pos: dict[str, float] = {}
    log_prob_neg: dict[str, float] = {}
    for tok in vocab:
        log_prob_pos[tok] = round(math.log((sum_pos.get(tok, 0.0) + alpha) / denom_pos), 6)
        log_prob_neg[tok] = round(math.log((sum_neg.get(tok, 0.0) + alpha) / denom_neg), 6)

    # Priors suavizados (evitan que una clase con 10x mas muestras aplaste la probabilidad)
    p_pos_raw = (peso_docs_pos + 1.0) / (peso_docs_pos + peso_docs_neg + 2.0)
    # Suavizado moderado hacia 0.5 para mantener balanceado el ranking
    p_pos_bal = 0.70 * p_pos_raw + 0.30 * 0.50
    p_pos_bal = max(0.15, min(0.85, p_pos_bal))

    estado.habilitado = True
    estado.peso_total_pos = peso_docs_pos
    estado.peso_total_neg = peso_docs_neg
    estado.prior_log_pos = math.log(p_pos_bal)
    estado.prior_log_neg = math.log(1.0 - p_pos_bal)
    estado.idf = idf
    estado.log_prob_pos = log_prob_pos
    estado.log_prob_neg = log_prob_neg
    estado.default_log_pos = math.log(alpha / denom_pos)
    estado.default_log_neg = math.log(alpha / denom_neg)
    estado.vocab_size = v_size
    return estado


def inferir_con_estado(
    estado: EstadoModeloNB,
    features_raw: dict[str, float],
    max_ajuste_score: float = 18.0,
) -> PrediccionAprendizaje:
    if not estado.habilitado or not features_raw:
        return PrediccionAprendizaje(
            habilitado=False,
            probabilidad_ganar=0.5,
            ajuste_score=0.0,
            muestras_entrenamiento=estado.muestras_totales,
            palabras_impulsoras=[],
        )

    # Vectorizar solo sobre vocabulario conocido (tokens OOV no aportan ruido)
    feats_conocidas = {k: v for k, v in features_raw.items() if k in estado.idf}
    if not feats_conocidas:
        return PrediccionAprendizaje(
            habilitado=True,
            probabilidad_ganar=0.5,
            ajuste_score=0.0,
            muestras_entrenamiento=estado.muestras_totales,
            palabras_impulsoras=[],
        )

    vec = _vectorizar_tfidf_l2(feats_conocidas, estado.idf)

    log_pos = estado.prior_log_pos
    log_neg = estado.prior_log_neg
    contribuciones: list[tuple[str, float]] = []

    for tok, w in vec.items():
        lp = estado.log_prob_pos.get(tok, estado.default_log_pos)
        ln = estado.log_prob_neg.get(tok, estado.default_log_neg)
        log_pos += w * lp
        log_neg += w * ln
        delta = w * (lp - ln)
        if abs(delta) >= 0.08:
            contribuciones.append((tok, delta))

    # Logit escalado por temperatura para evitar probabilidades extremas 0.0001 / 0.9999
    logit = (log_pos - log_neg) / max(0.5, estado.temperatura)
    logit = max(-14.0, min(14.0, logit))
    prob_raw = 1.0 / (1.0 + math.exp(-logit))

    # Factor de madurez bayesiano: con pocas muestras (ej. 4..10) encogemos suavemente hacia 0.5
    n_min_clase = min(estado.muestras_pos, estado.muestras_neg)
    madurez = min(1.0, n_min_clase / 8.0) * min(1.0, estado.muestras_totales / 16.0)
    madurez = max(0.30, madurez)

    prob_calibrada = 0.5 + (prob_raw - 0.5) * madurez
    ajuste = round((prob_calibrada - 0.5) * 2.0 * max_ajuste_score, 2)

    contribuciones.sort(key=lambda kv: abs(kv[1]), reverse=True)
    impulsoras = [f"{'+' if d > 0 else '-'}{tok}" for tok, d in contribuciones[:6]]

    return PrediccionAprendizaje(
        habilitado=True,
        probabilidad_ganar=round(prob_calibrada, 4),
        ajuste_score=ajuste,
        muestras_entrenamiento=estado.muestras_totales,
        palabras_impulsoras=impulsoras,
    )


def evaluar_validacion_cruzada(muestras: list[MuestraCRM], k_folds: int = 5) -> MetricasValidacionCV:
    """Validacion cruzada estratificada K-Fold en Python puro (mide F1, Precision, Recall y Brier)."""
    pos = [m for m in muestras if m.etiqueta == 1]
    neg = [m for m in muestras if m.etiqueta == 0]
    n_tot = len(muestras)

    if len(pos) < 3 or len(neg) < 3:
        return MetricasValidacionCV(
            folds=0, muestras_totales=n_tot, muestras_pos=len(pos), muestras_neg=len(neg), confiable=False
        )

    folds = max(2, min(k_folds, len(pos), len(neg)))
    # Distribucion estratificada determinista por indice modulo folds
    buckets: list[list[MuestraCRM]] = [[] for _ in range(folds)]
    for i, m in enumerate(pos):
        buckets[i % folds].append(m)
    for i, m in enumerate(neg):
        buckets[i % folds].append(m)

    tp = fp = tn = fn = 0
    brier_sum = 0.0

    for f_idx in range(folds):
        test_set = buckets[f_idx]
        train_set = [m for j, b in enumerate(buckets) if j != f_idx for m in b]
        mod_fold = entrenar_nb_en_memoria(train_set)
        for m in test_set:
            pred = inferir_con_estado(mod_fold, m.features)
            p = pred.probabilidad_ganar
            brier_sum += (p - float(m.etiqueta)) ** 2
            y_hat = 1 if p >= 0.5 else 0
            if y_hat == 1 and m.etiqueta == 1:
                tp += 1
            elif y_hat == 1 and m.etiqueta == 0:
                fp += 1
            elif y_hat == 0 and m.etiqueta == 0:
                tn += 1
            else:
                fn += 1

    acc = (tp + tn) / max(1, n_tot)
    prec = tp / max(1, tp + fp)
    rec = tp / max(1, tp + fn)
    f1 = (2.0 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0
    brier = brier_sum / max(1, n_tot)

    return MetricasValidacionCV(
        folds=folds,
        muestras_totales=n_tot,
        muestras_pos=len(pos),
        muestras_neg=len(neg),
        accuracy=acc,
        precision=prec,
        recall=rec,
        f1_score=f1,
        brier_score=brier,
        confiable=(n_tot >= 10 and f1 >= 0.60 and brier <= 0.24),
    )


# ==================== ALMACEN SQLITE + MOTOR DE APRENDIZAJE ADAPTATIVO ====================
class MotorAprendizajeCRM:
    """
    Capa 7 de AEGIS-X: Se entrena automaticamente con el historial real del CRM (leads + feedback manual),
    persiste el modelo calibrado en SQLite, detecta cambios por firma SHA-256 y genera insights
    de rentabilidad (que skills y plataformas dejan mas dolares reales).
    """

    def __init__(self, db_path: str | None = None, usar_sqlite: bool = True, max_ajuste_score: float = 18.0) -> None:
        self._lock = threading.RLock()
        self.db_path = db_path or DB_PATH
        self.usar_sqlite = usar_sqlite
        self.max_ajuste_score = max_ajuste_score
        self._estado = EstadoModeloNB()
        self._esquema_ok = False
        self._ultimo_check_ts = 0.0

        if self.usar_sqlite:
            self.asegurar_esquema()
            self._cargar_modelo_cacheado()

    def _conectar(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def asegurar_esquema(self) -> None:
        if not self.usar_sqlite or self._esquema_ok:
            return
        conn = self._conectar()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS aegis_ml_modelo (
                    clave TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    actualizado_ts REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS aegis_ml_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    titulo TEXT NOT NULL,
                    cuerpo TEXT DEFAULT '',
                    plataforma TEXT DEFAULT '',
                    categoria TEXT DEFAULT '',
                    etiqueta INTEGER NOT NULL,
                    ganancia_usd REAL DEFAULT 0,
                    ts_epoch REAL NOT NULL
                )
                """
            )
            conn.commit()
            self._esquema_ok = True
        finally:
            conn.close()

    def _cargar_modelo_cacheado(self) -> bool:
        if not self.usar_sqlite:
            return False
        self.asegurar_esquema()
        conn = self._conectar()
        try:
            row = conn.execute("SELECT payload_json FROM aegis_ml_modelo WHERE clave = 'nb_principal'").fetchone()
            if row and row[0]:
                self._estado = EstadoModeloNB.from_dict(json.loads(row[0]))
                return True
        except Exception:
            pass
        finally:
            conn.close()
        return False

    def _guardar_modelo_cacheado(self, estado: EstadoModeloNB) -> None:
        if not self.usar_sqlite:
            return
        self.asegurar_esquema()
        conn = self._conectar()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO aegis_ml_modelo (clave, payload_json, actualizado_ts) VALUES ('nb_principal', ?, ?)",
                (json.dumps(estado.to_dict(), ensure_ascii=False), time.time()),
            )
            conn.commit()
        finally:
            conn.close()

    def registrar_feedback(
        self,
        titulo: str,
        etiqueta: int,
        cuerpo: str = "",
        plataforma: str = "",
        categoria: str = "",
        ganancia_usd: float = 0.0,
        reentrenar: bool = True,
    ) -> EstadoModeloNB:
        """Permite ensenarle manualmente al motor ('me interesa'=1, 'basura'=0) desde Web OS o Telegram."""
        if not self.usar_sqlite:
            return self._estado
        self.asegurar_esquema()
        conn = self._conectar()
        try:
            conn.execute(
                """
                INSERT INTO aegis_ml_feedback (titulo, cuerpo, plataforma, categoria, etiqueta, ganancia_usd, ts_epoch)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (titulo[:260], cuerpo[:1600], plataforma[:60], categoria[:60], 1 if etiqueta else 0, float(ganancia_usd or 0.0), time.time()),
            )
            conn.commit()
        finally:
            conn.close()
        if reentrenar:
            return self.entrenar_desde_db(forzar=True)
        return self._estado

    def _leer_muestras_db(self) -> tuple[list[MuestraCRM], str]:
        self.asegurar_esquema()
        muestras: list[MuestraCRM] = []
        hasher = hashlib.sha256()
        conn = self._conectar()
        try:
            # 1. Leer tabla leads si existe
            tablas = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            if "leads" in tablas:
                cols = {r[1] for r in conn.execute("PRAGMA table_info(leads)").fetchall()}
                tiene_plat = "plataforma" in cols
                tiene_tipo = "tipo_trabajo" in cols
                tiene_notas = "notas" in cols
                tiene_pnum = "presupuesto_num" in cols

                sel_plat = "COALESCE(NULLIF(plataforma,''), fuente)" if tiene_plat else "fuente"
                sel_tipo = "COALESCE(tipo_trabajo, 'freelance')" if tiene_tipo else "'freelance'"
                sel_notas = "COALESCE(notas, '')" if tiene_notas else "''"
                sel_pnum = "COALESCE(presupuesto_num, 0)" if tiene_pnum else "0"

                rows = conn.execute(
                    f"""
                    SELECT id, fecha, {sel_plat}, {sel_tipo}, titulo, categoria, {sel_pnum}, estado, ganancia_usd, {sel_notas}
                    FROM leads
                    WHERE estado IN ('ganado', 'negociando', 'contactado', 'descartado')
                    ORDER BY id DESC
                    LIMIT 1200
                    """
                ).fetchall()

                # Contar positivos fuertes para decidir si incluir 'contactado' como senal suave
                pos_fuertes = sum(1 for r in rows if r[7] in ("ganado", "negociando"))

                for lid, fecha, plat, tipo, titulo, cat, pnum, est, gan_usd, notas in rows:
                    hasher.update(f"L:{lid}:{est}:{gan_usd}:{titulo[:40]}|".encode("utf-8", errors="ignore"))
                    edad_d = _dias_desde_fecha(fecha)
                    decay = _peso_decaimiento_temporal(edad_d)
                    usd_eff = safe_float(gan_usd, 0.0) or safe_float(pnum, 0.0)

                    if est == "ganado":
                        etiqueta = 1
                        peso = (2.0 + 0.65 * math.log1p(max(0.0, safe_float(gan_usd, 50.0)) / 50.0)) * decay
                    elif est == "negociando":
                        etiqueta = 1
                        peso = 1.20 * decay
                    elif est == "contactado":
                        if pos_fuertes >= 8:
                            continue  # Ya tenemos suficientes cierres/negociaciones reales
                        etiqueta = 1
                        peso = 0.55 * decay
                    else:  # descartado
                        etiqueta = 0
                        peso = 1.35 * decay

                    feats = extraer_features_texto(
                        titulo=titulo or "",
                        cuerpo=notas or "",
                        plataforma=plat or "",
                        categoria=cat or "",
                        tipo_trabajo=tipo or "freelance",
                        presupuesto_usd=usd_eff,
                    )
                    muestras.append(MuestraCRM(
                        muestra_id=f"lead_{lid}",
                        etiqueta=etiqueta,
                        peso=peso,
                        features=feats,
                        plataforma=plat or "",
                        categoria=cat or "",
                        ganancia_usd=safe_float(gan_usd, 0.0),
                        estado_origen=est,
                        edad_dias=edad_d,
                    ))

            # 2. Leer feedback explicito adicional
            if "aegis_ml_feedback" in tablas:
                frows = conn.execute(
                    "SELECT id, titulo, cuerpo, plataforma, categoria, etiqueta, ganancia_usd, ts_epoch FROM aegis_ml_feedback ORDER BY id DESC LIMIT 600"
                ).fetchall()
                ahora = time.time()
                for fid, tit, cue, plat, cat, et, gan, ts_ep in frows:
                    hasher.update(f"F:{fid}:{et}:{gan}:{tit[:40]}|".encode("utf-8", errors="ignore"))
                    edad_d = max(0.0, (ahora - float(ts_ep or ahora)) / 86400.0)
                    decay = _peso_decaimiento_temporal(edad_d)
                    peso = (1.8 if et == 1 else 1.5) * decay
                    feats = extraer_features_texto(
                        titulo=tit or "",
                        cuerpo=cue or "",
                        plataforma=plat or "",
                        categoria=cat or "",
                        presupuesto_usd=safe_float(gan, 0.0),
                    )
                    muestras.append(MuestraCRM(
                        muestra_id=f"fb_{fid}",
                        etiqueta=1 if et else 0,
                        peso=peso,
                        features=feats,
                        plataforma=plat or "",
                        categoria=cat or "",
                        ganancia_usd=safe_float(gan, 0.0),
                        estado_origen="feedback_pos" if et else "feedback_neg",
                        edad_dias=edad_d,
                    ))
        finally:
            conn.close()

        return muestras, hasher.hexdigest()[:24]

    def entrenar_desde_db(self, forzar: bool = False) -> EstadoModeloNB:
        if not self.usar_sqlite:
            return self._estado
        with self._lock:
            muestras, firma = self._leer_muestras_db()
            self._ultimo_check_ts = time.time()
            if (not forzar) and self._estado.firma_datos == firma and firma:
                return self._estado

            nuevo = entrenar_nb_en_memoria(muestras, firma_datos=firma)
            if nuevo.habilitado and len(muestras) >= 6:
                cv = evaluar_validacion_cruzada(muestras, k_folds=5)
                nuevo.cv_f1 = cv.f1_score
            self._estado = nuevo
            self._guardar_modelo_cacheado(nuevo)
            return nuevo

    def entrenar_con_muestras(self, muestras: list[MuestraCRM]) -> EstadoModeloNB:
        with self._lock:
            nuevo = entrenar_nb_en_memoria(muestras, firma_datos="memoria")
            if nuevo.habilitado and len(muestras) >= 6:
                nuevo.cv_f1 = evaluar_validacion_cruzada(muestras, k_folds=5).f1_score
            self._estado = nuevo
            return nuevo

    def predecir(
        self,
        doc: DocumentoNormalizado,
        ctx: ContextoFiltro | None = None,
        tax: ResultadoTaxonomia | None = None,
        econ: PerfilEconomico | None = None,
        auto_refrescar_seg: int = 300,
    ) -> PrediccionAprendizaje:
        with self._lock:
            if self.usar_sqlite and (time.time() - self._ultimo_check_ts) >= auto_refrescar_seg:
                self.entrenar_desde_db(forzar=False)
            feats = extraer_features_desde_doc(doc, ctx=ctx, tax=tax, econ=econ)
            return inferir_con_estado(self._estado, feats, max_ajuste_score=self.max_ajuste_score)

    def top_tokens_aprendidos(self, limite: int = 10) -> dict[str, list[tuple[str, float]]]:
        """Devuelve las palabras que mas suben y mas bajan la probabilidad de cierre segun tu CRM."""
        with self._lock:
            if not self._estado.habilitado:
                return {"positivos": [], "negativos": []}
            llrs = [
                (tok, round(self._estado.log_prob_pos[tok] - self._estado.log_prob_neg[tok], 3))
                for tok in self._estado.idf.keys()
            ]
            positivos = sorted([x for x in llrs if x[1] > 0], key=lambda kv: kv[1], reverse=True)[:limite]
            negativos = sorted([x for x in llrs if x[1] < 0], key=lambda kv: kv[1])[:limite]
            return {"positivos": positivos, "negativos": negativos}

    def generar_insights_rentabilidad(self) -> dict[str, Any]:
        """Analiza tu historial de leads para mostrar donde esta el dinero real (para AEGIS Lab)."""
        with self._lock:
            muestras, _ = self._leer_muestras_db() if self.usar_sqlite else ([], "")
            por_plat: dict[str, dict[str, float]] = defaultdict(lambda: {"pos": 0, "neg": 0, "usd": 0.0})
            por_cat: dict[str, dict[str, float]] = defaultdict(lambda: {"pos": 0, "neg": 0, "usd": 0.0})

            for m in muestras:
                p_key = m.plataforma or "Desconocida"
                c_key = m.categoria or "General"
                if m.etiqueta == 1:
                    por_plat[p_key]["pos"] += 1
                    por_plat[p_key]["usd"] += m.ganancia_usd
                    por_cat[c_key]["pos"] += 1
                    por_cat[c_key]["usd"] += m.ganancia_usd
                else:
                    por_plat[p_key]["neg"] += 1
                    por_cat[c_key]["neg"] += 1

            def _resumir(mapa: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
                res = []
                for nom, d in mapa.items():
                    tot = d["pos"] + d["neg"]
                    res.append({
                        "nombre": nom,
                        "positivos": int(d["pos"]),
                        "descartados": int(d["neg"]),
                        "tasa_exito_pct": round((d["pos"] / max(1, tot)) * 100.0, 1),
                        "usd_ganados": round(d["usd"], 2),
                    })
                res.sort(key=lambda x: (x["usd_ganados"], x["tasa_exito_pct"], x["positivos"]), reverse=True)
                return res[:8]

            return {
                "modelo_habilitado": self._estado.habilitado,
                "muestras_pos": self._estado.muestras_pos,
                "muestras_neg": self._estado.muestras_neg,
                "vocab_size": self._estado.vocab_size,
                "cv_f1": round(self._estado.cv_f1, 4),
                "top_tokens": self.top_tokens_aprendidos(8),
                "rentabilidad_plataformas": _resumir(por_plat),
                "rentabilidad_categorias": _resumir(por_cat),
            }

    def estado_actual(self) -> EstadoModeloNB:
        with self._lock:
            return self._estado


def generar_senales_aprendizaje(pred: PrediccionAprendizaje) -> list[SenalDetectada]:
    if not pred.habilitado or abs(pred.ajuste_score) < 1.0:
        return []
    signo = "favorable" if pred.ajuste_score > 0 else "desfavorable"
    return [
        SenalDetectada(
            codigo="ML_CRM_NAIVE_BAYES",
            categoria=CategoriaSenal.APRENDIZAJE_CRM,
            descripcion=f"Historial CRM ({pred.muestras_entrenamiento} leads): patron {signo} ({int(pred.probabilidad_ganar * 100)}% prob. cierre)",
            peso=round(pred.ajuste_score / 3.0, 2),
            evidencia=", ".join(pred.palabras_impulsoras[:4]),
            zona="modelo_crm",
        )
    ]