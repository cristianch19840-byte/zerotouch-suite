from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, field
from typing import Any


def _rx(expr: str) -> re.Pattern[str]:
    return re.compile(expr, re.IGNORECASE | re.MULTILINE)


# ==================== LIMITES OPTIMOS DE LONGITUD POR PLATAFORMA ====================
LIMITES_PLATAFORMA: dict[str, tuple[int, int, int]] = {
    # plataforma: (min_palabras, max_optimo, max_duro)
    "reddit":      (35, 130, 190),
    "freelancer":  (30, 105, 155),
    "github":      (45, 175, 260),
    "hackernews":  (28, 95, 145),
    "devto":       (40, 140, 200),
    "remoto":      (65, 210, 300),
    "email":       (45, 150, 220),
    "general":     (35, 140, 210),
}


@dataclass(frozen=True, slots=True)
class ReglaCliche:
    codigo: str
    penalidad: float
    etiqueta: str
    patron: re.Pattern[str]


# ==================== DETECTOR ANTI-CLICHES & AI-SLOP (24 REGLAS) ====================
REGLAS_CLICHES: tuple[ReglaCliche, ...] = (
    ReglaCliche("CLICHE_DEAR_SIR", 14.0, "Saludo robotico 'Dear Sir/Madam'",
                _rx(r"\b(?:dear\s+(?:sir|madam|hiring\s+manager|client|team)|to\s+whom\s+it\s+may\s+concern|estimado\s+(?:senor|cliente))\b")),
    ReglaCliche("CLICHE_HOPE_WELL", 12.0, "Apertura de relleno 'I hope this finds you well'",
                _rx(r"\b(?:i\s+hope\s+(?:this|you)\s+(?:message|email|are\s+doing)\s+(?:finds\s+you\s+well|well)|espero\s+que\s+este\s+mensaje\s+te\s+encuentre\s+bien)\b")),
    ReglaCliche("CLICHE_VERY_INTERESTED", 11.0, "Frase generica 'I am very interested / came across your post'",
                _rx(r"\b(?:i\s+(?:am|'m)\s+(?:very\s+|extremely\s+|deeply\s+)?interested\s+in\s+(?:this|your)\s+(?:job|project|role|post|opportunity)|"
                    r"i\s+(?:just\s+)?came\s+across\s+your\s+post|estoy\s+muy\s+interesado\s+en\s+tu\s+proyecto)\b")),
    ReglaCliche("CLICHE_READ_CAREFULLY", 10.0, "Relleno 'I have read your job description carefully'",
                _rx(r"\b(?:i\s+(?:have\s+)?(?:carefully\s+)?read\s+your\s+(?:job\s+)?(?:description|requirements|post)\s*(?:carefully)?|"
                    r"he\s+leido\s+atentamente\s+tu\s+(?:oferta|descripcion))\b")),
    ReglaCliche("CLICHE_PASSIONATE", 9.0, "Auto-elogio vacio 'passionate / rockstar / guru / ninja'",
                _rx(r"\b(?:passionate\s+(?:developer|programmer|engineer)|coding\s+(?:ninja|guru|rockstar)|"
                    r"hard[\s-]*working\s+and\s+dedicated|desarrollador\s+apasionado)\b")),
    ReglaCliche("CLICHE_YEARS_EXP_GENERIC", 8.0, "Apertura centrada en ego 'I have X years of experience'",
                _rx(r"^\s*(?:hi|hello|hey)[^\n]{0,30}\b(?:my\s+name\s+is|i\s+(?:am|'m)\s+a\s+(?:senior\s+)?(?:python\s+)?dev\w*\s+with\s+\d+\+?\s+years?)")),
    ReglaCliche("CLICHE_KINDLY", 7.0, "Muletilla formal 'kindly / do the needful / revert back'",
                _rx(r"\b(?:kindly\s+(?:check|review|let\s+me\s+know|consider|reply)|do\s+the\s+needful|revert\s+back\s+to\s+me)\b")),
    ReglaCliche("CLICHE_BEGGING", 15.0, "Tono necesitado 'please give me a chance / I really need this'",
                _rx(r"\b(?:please\s+give\s+me\s+a\s+chance|i\s+really\s+need\s+this\s+(?:job|money|project)|"
                    r"i\s+will\s+do\s+it\s+for\s+any\s+price|por\s+favor\s+dame\s+una\s+oportunidad)\b")),
    ReglaCliche("CLICHE_AI_SLOP_VERBS", 11.0, "Vocabulario delator de ChatGPT ('delve / tapestry / realm / seamless / leverage')",
                _rx(r"\b(?:delve\s+into|tapestry\s+of|in\s+the\s+realm\s+of|unlock\s+the\s+full\s+potential|"
                    r"thrilled\s+to\s+submit|delighted\s+to\s+assist|elevate\s+your\s+vision|bespoke\s+synergy|"
                    r"cutting[\s-]*edge\s+robust\s+scalable\s+solution)\b")),
    ReglaCliche("CLICHE_100_SATISFACTION", 8.0, "Promesa vacia '100% satisfaction guaranteed / unlimited revisions'",
                _rx(r"\b(?:100%\s+(?:satisfaction|quality)\s+guaranteed|unlimited\s+revisions|best\s+quality\s+at\s+lowest\s+price)\b")),
    ReglaCliche("CLICHE_LOOKING_FORWARD_GENERIC", 5.0, "Cierre pasivo 'Looking forward to hearing from you soon'",
                _rx(r"\b(?:looking\s+forward\s+to\s+hearing\s+from\s+you\s*(?:soon)?|awaiting\s+your\s+(?:positive\s+)?response|"
                    r"quedo\s+atento\s+a\s+tu\s+(?:pronta\s+)?respuesta)\b")),
    ReglaCliche("CLICHE_PLACEHOLDER_OLVIDADO", 25.0, "Placeholder sin rellenar ({{...}} o [INSERT ...])",
                _rx(r"(?:\{\{[^}]+\}\}|\[\s*(?:insert|your\s+name|client\s+name|link|price|nombre|precio)[^\]]*\])")),
)


# ==================== SENALES POSITIVAS DE ALTA CONVERSION ====================
REGEX_TECH_ESPECIFICO = _rx(
    r"\b(?:python|playwright|selenium|scrapy|beautifulsoup|bs4|requests|httpx|aiohttp|asyncio|"
    r"fastapi|flask|django|sqlite|postgres\w*|mongodb|redis|pandas|polars|csv|json|parquet|"
    r"telegram|aiogram|telethon|discord\.py|webhook|rest\s+api|oauth2?|graphql|shopify|woocommerce|"
    r"stripe|n8n|zapier|make\.com|docker|vps|cron|github|pr|pull\s+request|pytest|regex|ocr|llm|gemini|openai|rag|proxy|proxies|headless|pagination|retry|retries|rate[\s-]*limit)\b"
)

REGEX_CTA_FUERTE = _rx(
    r"(?:\?\s*$|"
    r"\b(?:want\s+me\s+to|would\s+you\s+like\s+me\s+to|shall\s+i|can\s+you\s+share|"
    r"send\s+(?:over\s+)?(?:the\s+)?(?:url|sample|site|repo|details)|"
    r"reply\s+with|drop\s+the\s+url|quick\s+\d+[\s-]*min|happy\s+to\s+(?:show|send|build)\s+a\s+(?:quick\s+)?(?:sample|demo|preview|proof)|"
    r"quieres\s+que|me\s+pasas\s+(?:el\s+)?(?:link|url|ejemplo)|te\s+envio\s+una\s+muestra)\b)"
)

REGEX_RISK_REVERSAL = _rx(
    r"\b(?:milestone|50%\s*(?:upfront|deposit|\/50)|pay\s+(?:only\s+)?(?:once|after)\s+you\s+(?:see|verify)\s+(?:the\s+)?(?:demo|sample|output|video)|"
    r"working\s+(?:demo|sample|preview)|clean\s+(?:code|repo|readme)|source\s+code\s+included|"
    r"free\s+(?:5[\s-]*row|mini|small)\s+sample|github\.com/|escrow|pr\s+with\s+tests|sin\s+riesgo|muestra\s+de\s+datos)\b"
)

REGEX_ETA_CONCRETO = _rx(
    r"\b(?:today|tonight|within\s+\d+\s*(?:hours?|hrs?|days?|h\b)|in\s+\d+(?:-\d+)?\s*(?:hours?|hrs?|days?)|"
    r"by\s+tomorrow|24\s*h(?:ours?)?|48\s*h(?:ours?)?|start\s+(?:right\s+now|immediately|today)|"
    r"hoy\s+mismo|en\s+\d+\s*(?:horas?|dias?))\b"
)

REGEX_PRECIO_ANCLADO = _rx(r"(?:\$\s*\d{2,5}(?:\s*-\s*\$?\d{2,5})?|\b\d{2,5}\s*(?:usd|usdt|eur)\b|\bfixed[\s-]*price\b|\bpor\s+\$\d+)")

REGEX_PRONOMBRES_CLIENTE = _rx(r"\b(?:you|your|yours|you're|you'll|tu|tus|te|su|sus)\b")
REGEX_PRONOMBRES_YO = _rx(r"\b(?:i|i'm|i've|i'll|my|me|mine|yo|mi|mis)\b")

STOPWORDS_OVERLAP = {
    "the", "and", "for", "with", "that", "this", "from", "have", "will", "are",
    "you", "your", "our", "can", "all", "not", "but", "what", "when", "who",
    "how", "out", "about", "into", "more", "some", "any", "need", "want",
    "looking", "help", "hiring", "task", "paid", "job", "work", "project",
    "budget", "fixed", "price", "developer", "freelancer", "please", "thanks",
    "para", "con", "que", "los", "las", "una", "uno", "por", "como", "pero",
    "busco", "necesito", "proyecto", "trabajo", "hola", "gracias",
}


@dataclass(slots=True)
class ReportePitchScore:
    score_0_100: float
    grado: str
    plataforma: str
    subscores: dict[str, float] = field(default_factory=dict)
    cliches_detectados: list[str] = field(default_factory=list)
    fortalezas: list[str] = field(default_factory=list)
    mejoras_accionables: list[str] = field(default_factory=list)
    metricas: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score_0_100": round(self.score_0_100, 1),
            "grado": self.grado,
            "plataforma": self.plataforma,
            "subscores": {k: round(v, 1) for k, v in self.subscores.items()},
            "cliches_detectados": self.cliches_detectados,
            "fortalezas": self.fortalezas,
            "mejoras_accionables": self.mejoras_accionables,
            "metricas": self.metricas,
        }


def _normalizar_plat_scorer(plataforma: str) -> str:
    low = (plataforma or "general").strip().lower()
    if "reddit" in low or low.startswith("r/"):
        return "reddit"
    if "freelancer" in low:
        return "freelancer"
    if "github" in low or "bounty" in low:
        return "github"
    if "hackernews" in low or low == "hn":
        return "hackernews"
    if "dev" in low:
        return "devto"
    if any(k in low for k in ("remote", "wwr", "jobicy", "himalayas", "arbeitnow", "python.org", "lobsters")):
        return "remoto"
    if "mail" in low:
        return "email"
    return "general"


def _extraer_keywords_significativos(texto: str) -> set[str]:
    toks = re.findall(r"[a-zA-Z0-9][a-zA-Z0-9+#.\-]{2,26}", (texto or "").lower())
    return {t for t in toks if t not in STOPWORDS_OVERLAP and not t.isdigit()}


def auditar_pitch(
    texto_pitch: str,
    *,
    plataforma: str = "general",
    oferta_texto: str = "",
) -> ReportePitchScore:
    """
    Auditor forense de propuestas en 0-tokens (<1ms):
    Evalua 7 dimensiones de conversion (gancho, personalizacion, especificidad tecnica,
    CTA de cierre, legibilidad por plataforma, enfoque en el cliente y penalidad anti-cliche).
    """
    plat = _normalizar_plat_scorer(plataforma)
    raw = (texto_pitch or "").strip()
    if not raw:
        return ReportePitchScore(
            score_0_100=0.0, grado="F", plataforma=plat,
            mejoras_accionables=["El pitch esta vacio."],
            metricas={"palabras": 0},
        )

    palabras = re.findall(r"\S+", raw)
    n_pal = len(palabras)
    lineas = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    n_lineas = len(lineas)
    oraciones = [s.strip() for s in re.split(r"[.!?]+", raw) if s.strip()]
    min_w, opt_w, max_w = LIMITES_PLATAFORMA.get(plat, LIMITES_PLATAFORMA["general"])

    cliches: list[str] = []
    pen_cliche = 0.0
    for regla in REGLAS_CLICHES:
        if regla.patron.search(raw):
            cliches.append(regla.etiqueta)
            pen_cliche += regla.penalidad

    fortalezas: list[str] = []
    mejoras: list[str] = []

    # 1. Gancho de apertura (primeras 2 lineas / 160 chars)
    apertura = " ".join(lineas[:2])[:170]
    sc_gancho = 62.0
    if REGEX_TECH_ESPECIFICO.search(apertura):
        sc_gancho += 20.0
        fortalezas.append("Gancho tecnico directo en las primeras 2 lineas")
    else:
        mejoras.append("Menciona la tecnologia o entregable exacto en la primera frase (gancho de 2 segundos).")
    if REGEX_ETA_CONCRETO.search(apertura) or REGEX_PRECIO_ANCLADO.search(apertura):
        sc_gancho += 12.0
    if re.match(r"^\s*(?:dear\s+|to\s+whom|i\s+hope\s+this|my\s+name\s+is)", apertura, re.IGNORECASE):
        sc_gancho -= 32.0
    sc_gancho = max(0.0, min(100.0, sc_gancho))

    # 2. Especificidad tecnica + prueba/riesgo cero + ETA
    tech_hits = sorted({m.group(0).lower() for m in REGEX_TECH_ESPECIFICO.finditer(raw)})
    sc_tech = min(100.0, 28.0 + len(tech_hits) * 14.0)
    tiene_risk_rev = bool(REGEX_RISK_REVERSAL.search(raw))
    tiene_eta = bool(REGEX_ETA_CONCRETO.search(raw))
    tiene_precio = bool(REGEX_PRECIO_ANCLADO.search(raw))
    if tiene_risk_rev:
        sc_tech = min(100.0, sc_tech + 14.0)
        fortalezas.append("Incluye reductor de riesgo / demo / milestone")
    else:
        mejoras.append("Agrega un reductor de riesgo (ej. muestra de 5 filas, milestone 50% o demo funcionando).")
    if tiene_eta:
        sc_tech = min(100.0, sc_tech + 10.0)
        fortalezas.append("Define tiempo estimado de entrega concreto")
    else:
        mejoras.append("Indica un tiempo estimado concreto de entrega (ej. 'hoy' o 'en 24-48h').")

    # 3. Personalizacion frente a la oferta real (keyword overlap)
    overlap_pct = 0.0
    if oferta_texto.strip():
        kw_of = _extraer_keywords_significativos(oferta_texto)
        kw_pi = _extraer_keywords_significativos(raw)
        if kw_of:
            inter = kw_of & kw_pi
            # Con 6+ coincidencias o >=28% de las keywords clave de la oferta ya se siente 100% a medida
            overlap_pct = (len(inter) / max(1, min(len(kw_of), 16))) * 100.0
            sc_pers = min(100.0, 25.0 + overlap_pct * 1.15)
            if len(inter) >= 4:
                fortalezas.append(f"Alta personalizacion ({len(inter)} terminos exactos de la oferta)")
            else:
                mejoras.append("Referencia mas detalles especificos del post del cliente para demostrar que lo leiste.")
        else:
            sc_pers = 70.0
    else:
        sc_pers = 70.0

    # 4. CTA de cierre (pregunta o siguiente paso sin friccion)
    cola = "\n".join(lineas[-2:]) if lineas else raw
    tiene_cta = bool(REGEX_CTA_FUERTE.search(cola) or "?" in cola)
    sc_cta = 92.0 if tiene_cta else 32.0
    if tiene_cta:
        fortalezas.append("Cierre con pregunta/CTA de baja friccion")
    else:
        mejoras.append("Termina con una pregunta directa y facil de responder (ej. 'Can you share the target URL?').")

    # 5. Legibilidad y calibracion de longitud por plataforma
    sc_leg = 85.0
    if n_pal < min_w:
        sc_leg -= min(45.0, (min_w - n_pal) * 1.5)
        mejoras.append(f"Demasiado corto ({n_pal} palabras); ideal para {plat}: {min_w}-{opt_w} palabras.")
    elif n_pal > max_w:
        sc_leg -= min(45.0, (n_pal - max_w) * 0.45)
        mejoras.append(f"Demasiado largo para {plat} ({n_pal} palabras); recorta a menos de {opt_w}.")
    elif n_pal > opt_w:
        sc_leg -= 10.0

    # Detectar muro de texto (parrafos de >75 palabras sin saltos)
    max_bloque = max((len(p.split()) for p in raw.split("\n") if p.strip()), default=0)
    if max_bloque > 75:
        sc_leg -= 22.0
        mejoras.append("Divide el muro de texto en parrafos cortos de 1-2 lineas o vinetas escaneables.")
    elif n_lineas >= 3 and max_bloque <= 55:
        sc_leg = min(100.0, sc_leg + 12.0)
        fortalezas.append("Estructura limpia y facil de escanear en movil")
    sc_leg = max(0.0, min(100.0, sc_leg))

    # 6. Enfoque en el cliente (ratio You/I)
    n_tu = len(REGEX_PRONOMBRES_CLIENTE.findall(raw))
    n_yo = len(REGEX_PRONOMBRES_YO.findall(raw))
    ratio_tu_yo = round(n_tu / max(1, n_yo), 2)
    if n_yo >= 6 and ratio_tu_yo < 0.45:
        sc_enfoque = 42.0
        mejoras.append(f"Demasiado centrado en 'I/my' ({n_yo} veces vs {n_tu} 'you/your'); enfocalo en el problema del cliente.")
    elif ratio_tu_yo >= 0.85:
        sc_enfoque = 92.0
        fortalezas.append("Tono orientado al cliente (buen balance you/I)")
    else:
        sc_enfoque = 72.0

    # 7. Anti-cliche
    sc_anti_cliche = max(0.0, 100.0 - pen_cliche * 2.2)
    if cliches:
        mejoras.insert(0, f"Elimina cliches detectados: {', '.join(cliches[:3])}.")

    # Score compuesto ponderado
    comp = (
        sc_gancho * 0.22
        + sc_tech * 0.20
        + sc_pers * 0.18
        + sc_cta * 0.16
        + sc_leg * 0.12
        + sc_enfoque * 0.12
    ) - (pen_cliche * 0.85)
    comp = round(max(0.0, min(100.0, comp)), 1)

    if comp >= 88.0:
        grado = "S"
    elif comp >= 78.0:
        grado = "A"
    elif comp >= 66.0:
        grado = "B"
    elif comp >= 52.0:
        grado = "C"
    elif comp >= 38.0:
        grado = "D"
    else:
        grado = "F"

    return ReportePitchScore(
        score_0_100=comp,
        grado=grado,
        plataforma=plat,
        subscores={
            "gancho": sc_gancho,
            "especificidad_tech": sc_tech,
            "personalizacion": sc_pers,
            "cta_cierre": sc_cta,
            "legibilidad": sc_leg,
            "enfoque_cliente": sc_enfoque,
            "anti_cliche": sc_anti_cliche,
        },
        cliches_detectados=cliches,
        fortalezas=fortalezas[:5],
        mejoras_accionables=mejoras[:5],
        metricas={
            "palabras": n_pal,
            "lineas": n_lineas,
            "oraciones": len(oraciones),
            "tech_terms": tech_hits[:10],
            "overlap_pct": round(min(100.0, overlap_pct), 1),
            "ratio_tu_yo": ratio_tu_yo,
            "tiene_precio": tiene_precio,
            "tiene_eta": tiene_eta,
            "tiene_risk_reversal": tiene_risk_rev,
        },
    )


# ==================== OPTIMIZADOR MULTI-ARMED BANDIT (THOMPSON SAMPLING + UCB1 + WILSON) ====================
def wilson_lower_bound(exitos: float, ensayos: float, z: float = 1.645) -> float:
    """Cota inferior de Wilson (90% confianza) para rankear templates con distintos volumenes de uso."""
    n = float(ensayos)
    if n <= 0.0:
        return 0.0
    p = max(0.0, min(1.0, float(exitos) / n))
    z2 = z * z
    denom = 1.0 + z2 / n
    centro = p + z2 / (2.0 * n)
    margen = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n)
    return round(max(0.0, (centro - margen) / denom), 4)


@dataclass(slots=True)
class BrazoTemplate:
    id: int
    nombre: str
    plataforma: str
    categoria: str
    usos: int
    respuestas: int
    ganados: int
    score_ucb1: float = 0.0
    score_thompson: float = 0.0
    wilson: float = 0.0
    tasa_exito_ponderada: float = 0.0


class BanditOptimizer:
    """
    Selector inteligente de templates A/B con equilibrio Exploracion vs Explotacion:
    - Recompensa ponderada: cada respuesta suma +0.55 y cada proyecto ganado suma +0.45 adicional (1.0 total).
    - Soporta UCB1 (determinista, ideal para ranking UI) y Thompson Sampling Beta-Bernoulli (estocastico).
    - Garantiza exploracion justa a templates nuevos con 0 usos (cold-start).
    """

    def __init__(self, c_exploracion: float = 0.65, seed: int | None = None) -> None:
        self.c_exploracion = max(0.05, float(c_exploracion))
        self._rng = random.Random(seed)

    def evaluar_brazos(self, templates: list[dict[str, Any]]) -> list[BrazoTemplate]:
        total_usos = sum(max(0, int(t.get("usos") or 0)) for t in templates)
        log_n = math.log(max(2, total_usos + 1))

        brazos: list[BrazoTemplate] = []
        for t in templates:
            u = max(0, int(t.get("usos") or 0))
            r = max(0, min(u, int(t.get("respuestas") or 0))) if u > 0 else 0
            g = max(0, min(u, int(t.get("ganados") or 0))) if u > 0 else 0

            # Recompensa continua en [0, u]: ganar pesa casi el doble que solo obtener respuesta
            recompensa = min(float(u), 0.55 * r + 0.45 * g) if u > 0 else 0.0
            media = (recompensa / u) if u > 0 else 0.50

            # UCB1: templates sin usar reciben bonus alto para ser probados pronto
            bonus_ucb = self.c_exploracion * math.sqrt(log_n / max(1, u)) if u > 0 else (0.50 + self.c_exploracion)
            ucb1 = round(media + bonus_ucb, 4)

            # Thompson Sampling con prior debil Beta(1.5, 1.5)
            alpha = max(0.5, 1.5 + recompensa)
            beta = max(0.5, 1.5 + max(0.0, float(u) - recompensa))
            ts_sample = round(self._rng.betavariate(alpha, beta), 4)

            brazos.append(BrazoTemplate(
                id=int(t.get("id") or 0),
                nombre=str(t.get("nombre") or ""),
                plataforma=str(t.get("plataforma") or "general"),
                categoria=str(t.get("categoria") or "Python"),
                usos=u,
                respuestas=r,
                ganados=g,
                score_ucb1=ucb1,
                score_thompson=ts_sample,
                wilson=wilson_lower_bound(recompensa, u),
                tasa_exito_ponderada=round(media * 100.0, 1) if u > 0 else 0.0,
            ))

        brazos.sort(key=lambda b: (b.score_ucb1, b.wilson, b.ganados), reverse=True)
        return brazos

    def seleccionar(self, templates: list[dict[str, Any]], modo: str = "ucb1") -> BrazoTemplate | None:
        if not templates:
            return None
        brazos = self.evaluar_brazos(templates)
        if modo.strip().lower() == "thompson":
            return max(brazos, key=lambda b: b.score_thompson)
        return brazos[0]