from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from core_ia import DB_PATH
from modulo_a_radar_whop.motor_filtrado.modelos import (
    ContextoFiltro,
    DocumentoNormalizado,
    ResultadoDedup,
)

# ==================== CONSTANTES DE ALGORITMIA (SIMHASH 64 + LSH + MINHASH) ====================
# 6 bandas que cubren exactamente los 64 bits -> por Principio del Palomar garantiza 100% recall con Hamming <= 5
BANDAS_LSH_SPEC: tuple[tuple[int, int], ...] = (
    (0, 0x7FF),   # bits 0..10  (11 bits)
    (11, 0x7FF),  # bits 11..21 (11 bits)
    (22, 0x7FF),  # bits 22..32 (11 bits)
    (33, 0x7FF),  # bits 33..43 (11 bits)
    (44, 0x3FF),  # bits 44..53 (10 bits)
    (54, 0x3FF),  # bits 54..63 (10 bits)
)

# Parametros primos deterministas para MinHash de 32 permutaciones (h_i(x) = (a_i * x + b_i) % P)
_MINHASH_PRIMO = (1 << 61) - 1
_MINHASH_SEEDS: tuple[tuple[int, int], ...] = tuple(
    (
        (2654435761 * (i + 1) + 1013904223) % (_MINHASH_PRIMO - 1) + 1,
        (1664525 * (i + 7) + 374761393) % (_MINHASH_PRIMO - 1),
    )
    for i in range(32)
)

# Autores genericos o bots que NUNCA deben disparar deduplicacion cross-author
AUTORES_GENERICOS = {
    "", "none", "null", "[deleted]", "automoderator", "github", "hackernews",
    "freelancer_client", "remoteok", "wwr", "remotive", "jobicy",
    "himalayas", "workingnomads", "arbeitnow", "rss", "web", "unknown",
}

# Stopwords freelance de ruido (se excluyen de shingles para no falsopositivar 2 proyectos distintos de Python)
STOPWORDS_DEDUP = {
    "hiring", "task", "paid", "request", "need", "looking", "for", "someone",
    "help", "with", "project", "work", "job", "usd", "usdt", "eur", "gbp",
    "budget", "fixed", "price", "quick", "simple", "small", "urgent", "asap",
    "developer", "programmer", "freelancer", "dev", "engineer", "expert",
    "build", "create", "make", "write", "want", "please", "thanks", "hello",
    "busco", "necesito", "proyecto", "presupuesto", "pago", "hola", "gracias",
    "remote", "contract", "full", "time", "part", "the", "and", "that", "this",
    "from", "into", "your", "our", "will", "can", "have", "are", "you",
}

PARAMS_TRACKING = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "ref_src", "fbclid", "gclid", "mc_cid", "mc_eid", "si",
    "share_id", "context", "rdt", "utm_name",
}

REGEX_REDDIT_POST = re.compile(r"/r/([^/]+)/comments/([a-z0-9]+)", re.IGNORECASE)
REGEX_GITHUB_ISSUE = re.compile(r"/([^/]+/[^/]+/issues/\d+)", re.IGNORECASE)
REGEX_FL_PROJECT = re.compile(r"/projects/([^/?#]+(?:/[^/?#]+)?)", re.IGNORECASE)
REGEX_CORCHETES = re.compile(r"\[[^\]]*\]|\([^\)]*\)")


# ==================== UTILIDADES DE HUELLA DIGITAL ====================
def canonicalizar_url(url: str) -> str:
    """Normaliza URLs de Reddit, GitHub, Freelancer, HN y bolsas removiendo ruido de tracking."""
    if not url:
        return ""
    raw = url.strip()
    if not raw.lower().startswith(("http://", "https://")):
        return raw.lower()
    try:
        p = urlparse(raw)
        host = p.netloc.lower().replace("www.", "")
        path = re.sub(r"/+", "/", p.path or "").rstrip("/")

        if host in ("reddit.com", "old.reddit.com", "new.reddit.com", "m.reddit.com", "np.reddit.com"):
            m = REGEX_REDDIT_POST.search(path)
            if m:
                return f"reddit.com/r/{m.group(1).lower()}/comments/{m.group(2).lower()}"
            host = "reddit.com"
        elif host == "github.com":
            m = REGEX_GITHUB_ISSUE.search(path)
            if m:
                return f"github.com/{m.group(1).lower()}"
        elif host == "freelancer.com":
            m = REGEX_FL_PROJECT.search(path)
            if m:
                return f"freelancer.com/projects/{m.group(1).lower().rstrip('/')}"
        elif host == "news.ycombinator.com":
            qs = dict(parse_qsl(p.query))
            if "id" in qs:
                return f"news.ycombinator.com/item?id={qs['id']}"

        # Filtrar parametros de tracking en cualquier otra URL
        qs_limpia = [
            (k.lower(), v)
            for k, v in parse_qsl(p.query, keep_blank_values=False)
            if k.lower() not in PARAMS_TRACKING
        ]
        qs_limpia.sort()
        query_out = urlencode(qs_limpia)
        return urlunparse(("", host, path.lower(), "", query_out, "")).lstrip("/")
    except Exception:
        return raw.lower()


def normalizar_titulo_exacto(titulo: str) -> str:
    limpio = REGEX_CORCHETES.sub(" ", (titulo or "").lower())
    limpio = re.sub(r"\W+", "", limpio)
    return limpio[:96]


def _hash64(texto: str) -> int:
    digest = hashlib.blake2b(texto.encode("utf-8", errors="ignore"), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=False)


def distancia_hamming(h1: int, h2: int) -> int:
    return (int(h1) ^ int(h2)).bit_count()


def extraer_bandas_lsh(simhash_64: int) -> tuple[tuple[int, int], ...]:
    h = int(simhash_64)
    return tuple((idx, (h >> shift) & mask) for idx, (shift, mask) in enumerate(BANDAS_LSH_SPEC))


def _tokens_dedup(texto: str) -> list[str]:
    brutos = re.findall(r"[a-z0-9][a-z0-9+#.\-]{1,28}", (texto or "").lower())
    filtrados = [t for t in brutos if len(t) >= 3 and t not in STOPWORDS_DEDUP]
    return filtrados if len(filtrados) >= 3 else [t for t in brutos if len(t) >= 2]


def extraer_shingles(doc: DocumentoNormalizado) -> set[str]:
    """
    Construye un conjunto hibrido de shingles:
    - Palabras significativas del titulo (con prefijo t:)
    - Bigramas y trigramas de palabras de titulo + cuerpo
    - 4-gramas de caracteres del titulo normalizado (resistente a typos/espacios)
    """
    toks_t = _tokens_dedup(doc.titulo_limpio)[:24]
    toks_c = _tokens_dedup(doc.cuerpo_limpio)[:140]
    toks_all = toks_t + toks_c

    shingles: set[str] = set()
    for t in toks_t:
        shingles.add(f"t:{t}")

    for i in range(len(toks_all) - 1):
        shingles.add(f"2:{toks_all[i]}_{toks_all[i + 1]}")

    for i in range(len(toks_all) - 2):
        shingles.add(f"3:{toks_all[i]}_{toks_all[i + 1]}_{toks_all[i + 2]}")

    # Si el post es muy corto (solo titulo), agregamos unigramas y char 4-grams
    if len(toks_all) < 12:
        for t in toks_all:
            shingles.add(f"1:{t}")
        tn = normalizar_titulo_exacto(doc.titulo_limpio)
        for i in range(max(0, len(tn) - 3)):
            shingles.add(f"c:{tn[i:i + 4]}")

    # Tope de seguridad para textos muy largos (conserva orden determinista)
    if len(shingles) > 260:
        shingles = set(sorted(shingles)[:260])
    return shingles


def calcular_minhash(shingles: set[str]) -> tuple[int, ...]:
    if not shingles:
        return tuple(0 for _ in _MINHASH_SEEDS)
    hashes_base = [_hash64(s) % _MINHASH_PRIMO for s in shingles]
    firma: list[int] = []
    for a, b in _MINHASH_SEEDS:
        min_v = _MINHASH_PRIMO
        for x in hashes_base:
            v = (a * x + b) % _MINHASH_PRIMO
            if v < min_v:
                min_v = v
        firma.append(min_v)
    return tuple(firma)


def similitud_minhash(f1: tuple[int, ...], f2: tuple[int, ...]) -> float:
    if not f1 or not f2 or len(f1) != len(f2):
        return 0.0
    iguales = sum(1 for a, b in zip(f1, f2) if a == b)
    return iguales / len(f1)


def similitud_jaccard_shingles(s1: set[str], s2: set[str]) -> float:
    if not s1 or not s2:
        return 0.0
    inter = len(s1 & s2)
    if inter == 0:
        return 0.0
    union = len(s1 | s2)
    # Coeficiente hibrido: 70% Jaccard + 30% Overlap (captura cuando un repost recorta el cuerpo)
    jacc = inter / union
    overlap = inter / min(len(s1), len(s2))
    return round(0.70 * jacc + 0.30 * overlap, 4)


def calcular_simhash_64(doc: DocumentoNormalizado) -> int:
    """
    Calcula huella SimHash de 64 bits ponderada por zona y n-grama:
    - Titulo unigramas (peso 3.0) y bigramas (peso 3.6)
    - Cuerpo unigramas (peso 1.4), bigramas (peso 2.2) y trigramas (peso 2.8)
    """
    toks_t = _tokens_dedup(doc.titulo_limpio)[:28]
    toks_c = _tokens_dedup(doc.cuerpo_limpio)[:160]

    features: list[tuple[str, float]] = []
    for t in toks_t:
        features.append((f"tu:{t}", 3.0))
    for i in range(len(toks_t) - 1):
        features.append((f"tb:{toks_t[i]}_{toks_t[i + 1]}", 3.6))

    for t in toks_c:
        features.append((f"cu:{t}", 1.4))
    for i in range(len(toks_c) - 1):
        features.append((f"cb:{toks_c[i]}_{toks_c[i + 1]}", 2.2))
    for i in range(len(toks_c) - 2):
        features.append((f"ct:{toks_c[i]}_{toks_c[i + 1]}_{toks_c[i + 2]}", 2.8))

    if not features:
        tn = normalizar_titulo_exacto(doc.titulo_limpio) or doc.texto_busqueda[:80]
        if not tn:
            return 0
        return _hash64(tn)

    acum = [0.0] * 64
    for feat, peso in features:
        h = _hash64(feat)
        for bit in range(64):
            if (h >> bit) & 1:
                acum[bit] += peso
            else:
                acum[bit] -= peso

    resultado = 0
    for bit in range(64):
        if acum[bit] > 0.0:
            resultado |= (1 << bit)
    return resultado


def extraer_artefactos_unicos(doc: DocumentoNormalizado) -> set[str]:
    """Extrae identificadores de alta unicidad (repos GitHub especificos, emails personales)."""
    arts: set[str] = set()
    for repo in doc.entidades.repos_github:
        r_clean = repo.strip().lower().rstrip("/")
        if "/" in r_clean:
            arts.add(f"gh:{r_clean}")
    for mail in doc.entidades.emails:
        m_clean = mail.strip().lower()
        if m_clean and not m_clean.startswith(("noreply@", "no-reply@", "support@", "info@")):
            arts.add(f"mail:{m_clean}")
    return arts


# ==================== REGISTRO EN MEMORIA + INDICE LSH O(1) ====================
@dataclass(slots=True)
class RegistroDedup:
    post_id: str
    link_canon: str
    titulo_norm: str
    autor_norm: str
    plataforma: str
    simhash_64: int
    shingles: set[str] = field(default_factory=set)
    minhash: tuple[int, ...] = field(default_factory=tuple)
    artefactos: set[str] = field(default_factory=set)
    ts_epoch: float = 0.0


class IndiceLSH64:
    """Indice Locality-Sensitive Hashing en RAM con 6 bandas para busqueda O(1) de vecinos SimHash."""

    def __init__(self) -> None:
        self._buckets: list[dict[int, set[str]]] = [defaultdict(set) for _ in BANDAS_LSH_SPEC]

    def agregar(self, post_id: str, simhash_64: int) -> None:
        if simhash_64 == 0:
            return
        for idx, val in extraer_bandas_lsh(simhash_64):
            self._buckets[idx][val].add(post_id)

    def buscar_candidatos(self, simhash_64: int) -> set[str]:
        if simhash_64 == 0:
            return set()
        cands: set[str] = set()
        for idx, val in extraer_bandas_lsh(simhash_64):
            bucket = self._buckets[idx].get(val)
            if bucket:
                cands.update(bucket)
        return cands

    def limpiar(self) -> None:
        for b in self._buckets:
            b.clear()


# ==================== PERSISTENCIA SQLITE DEDICADA (WAL + HEX SAFE) ====================
class AlmacenDedupSQLite:
    def __init__(self, db_path: str | None = None, max_registros: int = 12000, ttl_dias: int = 30) -> None:
        self.db_path = db_path or DB_PATH
        self.max_registros = max(500, int(max_registros))
        self.ttl_dias = max(1, int(ttl_dias))
        self._inicializado = False

    def _conectar(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def asegurar_esquema(self) -> None:
        if self._inicializado:
            return
        conn = self._conectar()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS aegis_dedup_index (
                    post_id TEXT PRIMARY KEY,
                    link_canon TEXT DEFAULT '',
                    titulo_norm TEXT DEFAULT '',
                    autor_norm TEXT DEFAULT '',
                    plataforma TEXT DEFAULT '',
                    simhash_hex TEXT NOT NULL,
                    shingles_json TEXT DEFAULT '[]',
                    artefactos_json TEXT DEFAULT '[]',
                    ts_epoch REAL NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_aegis_dedup_ts ON aegis_dedup_index(ts_epoch DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_aegis_dedup_link ON aegis_dedup_index(link_canon)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_aegis_dedup_autor ON aegis_dedup_index(autor_norm)")
            conn.commit()
            self._inicializado = True
        finally:
            conn.close()

    def cargar_recientes(self, limite: int = 6000) -> list[RegistroDedup]:
        self.asegurar_esquema()
        corte = time.time() - (self.ttl_dias * 86400)
        conn = self._conectar()
        try:
            rows = conn.execute(
                """
                SELECT post_id, link_canon, titulo_norm, autor_norm, plataforma,
                       simhash_hex, shingles_json, artefactos_json, ts_epoch
                FROM aegis_dedup_index
                WHERE ts_epoch >= ?
                ORDER BY ts_epoch DESC
                LIMIT ?
                """,
                (corte, limite),
            ).fetchall()
            salida: list[RegistroDedup] = []
            for r in rows:
                try:
                    sh_64 = int(r[5], 16) if r[5] else 0
                except ValueError:
                    sh_64 = 0
                try:
                    shingles = set(json.loads(r[6] or "[]"))
                except Exception:
                    shingles = set()
                try:
                    artefactos = set(json.loads(r[7] or "[]"))
                except Exception:
                    artefactos = set()
                salida.append(RegistroDedup(
                    post_id=r[0],
                    link_canon=r[1] or "",
                    titulo_norm=r[2] or "",
                    autor_norm=r[3] or "",
                    plataforma=r[4] or "",
                    simhash_64=sh_64,
                    shingles=shingles,
                    minhash=calcular_minhash(shingles) if shingles else (),
                    artefactos=artefactos,
                    ts_epoch=float(r[8] or 0.0),
                ))
            return salida
        finally:
            conn.close()

    def guardar_lote(self, registros: list[RegistroDedup]) -> None:
        if not registros:
            return
        self.asegurar_esquema()
        conn = self._conectar()
        try:
            datos = [
                (
                    reg.post_id,
                    reg.link_canon,
                    reg.titulo_norm,
                    reg.autor_norm,
                    reg.plataforma,
                    f"{int(reg.simhash_64):016x}",
                    json.dumps(sorted(reg.shingles)[:160], ensure_ascii=False),
                    json.dumps(sorted(reg.artefactos)[:12], ensure_ascii=False),
                    float(reg.ts_epoch or time.time()),
                )
                for reg in registros
            ]
            conn.executemany(
                """
                INSERT OR REPLACE INTO aegis_dedup_index
                (post_id, link_canon, titulo_norm, autor_norm, plataforma, simhash_hex, shingles_json, artefactos_json, ts_epoch)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                datos,
            )
            conn.commit()
        finally:
            conn.close()

    def podar(self) -> int:
        self.asegurar_esquema()
        corte = time.time() - (self.ttl_dias * 86400)
        conn = self._conectar()
        try:
            cur1 = conn.execute("DELETE FROM aegis_dedup_index WHERE ts_epoch < ?", (corte,))
            cur2 = conn.execute(
                """
                DELETE FROM aegis_dedup_index
                WHERE post_id NOT IN (
                    SELECT post_id FROM aegis_dedup_index ORDER BY ts_epoch DESC LIMIT ?
                )
                """,
                (self.max_registros,),
            )
            conn.commit()
            return int((cur1.rowcount or 0) + (cur2.rowcount or 0))
        finally:
            conn.close()


# ==================== MOTOR PRINCIPAL DE DEDUPLICACION SEMANTICA (CAPA 6) ====================
class MotorDedup:
    """
    Capa 6 de AEGIS-X: Cascada de deduplicacion en 6 niveles con complejidad O(1) amortizada:
      1. Exacto por post_id
      2. Exacto por URL canonicalizada (cross-domain Reddit/GitHub/Freelancer)
      3. Exacto por titulo normalizado
      4. Artefacto compartido (mismo repo GitHub o email en ventana de 72h)
      5. SimHash 64-bit via LSH 6 bandas + verificacion por Shingles 3-grama / MinHash
      6. Cross-Author repost (mismo usuario spameando varios subreddits con texto parafraseado)
    """

    def __init__(
        self,
        db_path: str | None = None,
        usar_sqlite: bool = True,
        umbral_hamming_directo: int = 3,
        umbral_hamming_lsh: int = 10,
        umbral_shingle: float = 0.62,
        umbral_cross_author_shingle: float = 0.40,
        ventana_autor_horas: int = 72,
    ) -> None:
        self._lock = threading.RLock()
        self.usar_sqlite = usar_sqlite
        self.umbral_hamming_directo = umbral_hamming_directo
        self.umbral_hamming_lsh = umbral_hamming_lsh
        self.umbral_shingle = umbral_shingle
        self.umbral_cross_author_shingle = umbral_cross_author_shingle
        self.ventana_autor_seg = max(3600, int(ventana_autor_horas) * 3600)

        self._almacen = AlmacenDedupSQLite(db_path=db_path) if usar_sqlite else None
        self._registros: dict[str, RegistroDedup] = {}
        self._por_link: dict[str, str] = {}
        self._por_titulo: dict[str, str] = {}
        self._por_autor: dict[str, list[str]] = defaultdict(list)
        self._por_artefacto: dict[str, list[str]] = defaultdict(list)
        self._lsh = IndiceLSH64()
        self._pendientes_db: list[RegistroDedup] = []

        self._stats: dict[str, int] = defaultdict(int)

        if self._almacen is not None:
            self.cargar_desde_db()

    def _indexar_en_ram(self, reg: RegistroDedup) -> None:
        self._registros[reg.post_id] = reg
        if reg.link_canon:
            self._por_link[reg.link_canon] = reg.post_id
        if reg.titulo_norm and len(reg.titulo_norm) >= 14:
            self._por_titulo[reg.titulo_norm] = reg.post_id
        if reg.autor_norm and reg.autor_norm not in AUTORES_GENERICOS:
            lista_a = self._por_autor[reg.autor_norm]
            if reg.post_id not in lista_a:
                lista_a.append(reg.post_id)
                if len(lista_a) > 25:
                    del lista_a[:-25]
        for art in reg.artefactos:
            lista_art = self._por_artefacto[art]
            if reg.post_id not in lista_art:
                lista_art.append(reg.post_id)
                if len(lista_art) > 15:
                    del lista_art[:-15]
        self._lsh.agregar(reg.post_id, reg.simhash_64)

    def cargar_desde_db(self, limite: int = 6000) -> int:
        if self._almacen is None:
            return 0
        with self._lock:
            self._registros.clear()
            self._por_link.clear()
            self._por_titulo.clear()
            self._por_autor.clear()
            self._por_artefacto.clear()
            self._lsh.limpiar()
            regs = self._almacen.cargar_recientes(limite=limite)
            for reg in regs:
                self._indexar_en_ram(reg)
            return len(regs)

    def preparar_registro(
        self,
        post_id: str,
        doc: DocumentoNormalizado,
        ctx: ContextoFiltro | None = None,
    ) -> RegistroDedup:
        ctx = ctx or ContextoFiltro()
        shingles = extraer_shingles(doc)
        return RegistroDedup(
            post_id=str(post_id or ctx.link or normalizar_titulo_exacto(doc.titulo_limpio)),
            link_canon=canonicalizar_url(ctx.link),
            titulo_norm=normalizar_titulo_exacto(doc.titulo_limpio),
            autor_norm=(ctx.autor or "").strip().lower().lstrip("u/"),
            plataforma=(ctx.plataforma or ctx.fuente or "").strip().lower(),
            simhash_64=calcular_simhash_64(doc),
            shingles=shingles,
            minhash=calcular_minhash(shingles),
            artefactos=extraer_artefactos_unicos(doc),
            ts_epoch=time.time(),
        )

    def verificar(
        self,
        post_id: str,
        doc: DocumentoNormalizado,
        ctx: ContextoFiltro | None = None,
        registrar_si_nuevo: bool = False,
        persistir_inmediato: bool = False,
    ) -> ResultadoDedup:
        reg = self.preparar_registro(post_id=post_id, doc=doc, ctx=ctx)
        ahora = reg.ts_epoch

        with self._lock:
            self._stats["consultas"] += 1

            # Nivel 1: Exacto por ID
            if reg.post_id in self._registros:
                self._stats["dup_exacto_id"] += 1
                return ResultadoDedup(
                    es_duplicado=True,
                    tipo_duplicado="exacto_id",
                    simhash_64=reg.simhash_64,
                    distancia_hamming=0,
                    similitud_shingle=1.0,
                    match_previo_id=reg.post_id,
                )

            # Nivel 2: Exacto por URL canonicalizada
            if reg.link_canon and reg.link_canon in self._por_link:
                prev_id = self._por_link[reg.link_canon]
                self._stats["dup_exacto_link"] += 1
                return ResultadoDedup(
                    es_duplicado=True,
                    tipo_duplicado="exacto_link",
                    simhash_64=reg.simhash_64,
                    distancia_hamming=0,
                    similitud_shingle=1.0,
                    match_previo_id=prev_id,
                )

            # Nivel 3: Exacto por titulo normalizado (requiere >= 14 chars para evitar titulos cortos genericos)
            if reg.titulo_norm and len(reg.titulo_norm) >= 14 and reg.titulo_norm in self._por_titulo:
                prev_id = self._por_titulo[reg.titulo_norm]
                self._stats["dup_exacto_titulo"] += 1
                return ResultadoDedup(
                    es_duplicado=True,
                    tipo_duplicado="exacto_titulo",
                    simhash_64=reg.simhash_64,
                    distancia_hamming=0,
                    similitud_shingle=1.0,
                    match_previo_id=prev_id,
                )

            # Nivel 4: Artefacto unico compartido (mismo repo GitHub o email personal en ventana de 72h)
            for art in reg.artefactos:
                for prev_id in self._por_artefacto.get(art, ()):
                    prev_reg = self._registros.get(prev_id)
                    if prev_reg and (ahora - prev_reg.ts_epoch) <= self.ventana_autor_seg:
                        sim_s = similitud_jaccard_shingles(reg.shingles, prev_reg.shingles)
                        if sim_s >= 0.25 or art.startswith("gh:"):
                            self._stats["dup_artefacto"] += 1
                            return ResultadoDedup(
                                es_duplicado=True,
                                tipo_duplicado="artefacto",
                                simhash_64=reg.simhash_64,
                                distancia_hamming=distancia_hamming(reg.simhash_64, prev_reg.simhash_64),
                                similitud_shingle=sim_s,
                                match_previo_id=prev_id,
                            )

            # Nivel 5: Busqueda LSH 6 bandas en O(1) -> SimHash 64-bit + Shingles / MinHash
            mejor_ham = 64
            mejor_sim = 0.0
            mejor_id = ""
            candidatos_lsh = self._lsh.buscar_candidatos(reg.simhash_64)

            for cand_id in candidatos_lsh:
                prev = self._registros.get(cand_id)
                if prev is None:
                    continue
                ham = distancia_hamming(reg.simhash_64, prev.simhash_64)
                if ham < mejor_ham:
                    mejor_ham = ham
                    mejor_id = cand_id

                # Confirmacion directa por SimHash casi identico (Hamming <= 3)
                if ham <= self.umbral_hamming_directo:
                    sim_s = similitud_jaccard_shingles(reg.shingles, prev.shingles)
                    # Guardrail contra textos extremadamente cortos que colisionen accidentalmente
                    if sim_s >= 0.35 or ham <= 1:
                        self._stats["dup_simhash"] += 1
                        return ResultadoDedup(
                            es_duplicado=True,
                            tipo_duplicado="simhash",
                            simhash_64=reg.simhash_64,
                            distancia_hamming=ham,
                            similitud_shingle=sim_s,
                            match_previo_id=cand_id,
                        )

                # Zona gris LSH (Hamming 4..10): verificar con Shingles + MinHash
                if ham <= self.umbral_hamming_lsh:
                    sim_mh = similitud_minhash(reg.minhash, prev.minhash)
                    sim_s = similitud_jaccard_shingles(reg.shingles, prev.shingles)
                    sim_comb = max(sim_s, sim_mh * 0.92)
                    if sim_comb > mejor_sim:
                        mejor_sim = sim_comb
                        mejor_id = cand_id
                    if sim_s >= self.umbral_shingle or (ham <= 6 and sim_comb >= 0.50):
                        self._stats["dup_shingle"] += 1
                        return ResultadoDedup(
                            es_duplicado=True,
                            tipo_duplicado="shingle",
                            simhash_64=reg.simhash_64,
                            distancia_hamming=ham,
                            similitud_shingle=round(sim_comb, 4),
                            match_previo_id=cand_id,
                        )

            # Nivel 6: Cross-Author repost (mismo cliente en distintos subreddits con texto reescrito)
            if reg.autor_norm and reg.autor_norm not in AUTORES_GENERICOS:
                for prev_id in self._por_autor.get(reg.autor_norm, ()):
                    prev = self._registros.get(prev_id)
                    if prev is None or (ahora - prev.ts_epoch) > self.ventana_autor_seg:
                        continue
                    ham = distancia_hamming(reg.simhash_64, prev.simhash_64)
                    sim_s = similitud_jaccard_shingles(reg.shingles, prev.shingles)
                    if ham <= 14 or sim_s >= self.umbral_cross_author_shingle:
                        self._stats["dup_cross_author"] += 1
                        return ResultadoDedup(
                            es_duplicado=True,
                            tipo_duplicado="cross_author",
                            simhash_64=reg.simhash_64,
                            distancia_hamming=ham,
                            similitud_shingle=sim_s,
                            match_previo_id=prev_id,
                        )

            # Es genuinamente NUEVO
            self._stats["unicos"] += 1
            if registrar_si_nuevo:
                self._indexar_en_ram(reg)
                if self._almacen is not None:
                    self._pendientes_db.append(reg)
                    if persistir_inmediato or len(self._pendientes_db) >= 40:
                        self.flush_db()

            return ResultadoDedup(
                es_duplicado=False,
                tipo_duplicado="",
                simhash_64=reg.simhash_64,
                distancia_hamming=mejor_ham,
                similitud_shingle=round(mejor_sim, 4),
                match_previo_id=mejor_id if mejor_ham < 64 else "",
            )

    def registrar(
        self,
        post_id: str,
        doc: DocumentoNormalizado,
        ctx: ContextoFiltro | None = None,
        persistir_inmediato: bool = False,
    ) -> RegistroDedup:
        reg = self.preparar_registro(post_id=post_id, doc=doc, ctx=ctx)
        with self._lock:
            self._indexar_en_ram(reg)
            if self._almacen is not None:
                self._pendientes_db.append(reg)
                if persistir_inmediato or len(self._pendientes_db) >= 40:
                    self.flush_db()
        return reg

    def flush_db(self) -> int:
        if self._almacen is None:
            return 0
        with self._lock:
            if not self._pendientes_db:
                return 0
            lote = list(self._pendientes_db)
            self._pendientes_db.clear()
        self._almacen.guardar_lote(lote)
        return len(lote)

    def podar_db(self) -> int:
        if self._almacen is None:
            return 0
        self.flush_db()
        return self._almacen.podar()

    def estadisticas(self) -> dict[str, int]:
        with self._lock:
            out = dict(self._stats)
            out["en_ram"] = len(self._registros)
            out["pendientes_db"] = len(self._pendientes_db)
            return out