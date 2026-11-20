from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass

from modulo_a_radar_whop.motor_filtrado.modelos import (
    AnalisisIntencion,
    CategoriaSenal,
    ContextoFiltro,
    DocumentoNormalizado,
    ModalidadTrabajo,
    SenalDetectada,
    TipoIntencion,
)


@dataclass(frozen=True, slots=True)
class ReglaPatron:
    codigo: str
    eje: str
    peso: float
    descripcion: str
    patron: re.Pattern[str]
    zonas: tuple[str, ...] = ("flair", "titulo", "cuerpo", "tags")
    bloqueante: bool = False


def _sin_acentos(texto: str) -> str:
    if not texto:
        return ""
    return "".join(ch for ch in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(ch))


def _rx(expr: str) -> re.Pattern[str]:
    return re.compile(expr, re.IGNORECASE | re.MULTILINE)


# ==================== 1. REGLAS DE COMPRA FREELANCE REAL (EN + ES) ====================
REGLAS_COMPRA_FREELANCE: tuple[ReglaPatron, ...] = (
    ReglaPatron(
        "TAG_HIRING_EXPLICITO", "compra_freelance", 7.5,
        "Etiqueta explicita de contratacion ([Hiring]/[Task]/[Paid]/[Request])",
        _rx(r"(?:[\[\(]\s*(?:hiring|task|paid|request|gig|job|bounty|se\s+busca|busco)\s*[\]\)]|^\s*(?:hiring|\[h\]|task)\s*[:\-]?)"),
        zonas=("flair", "titulo"),
    ),
    ReglaPatron(
        "INTENCION_COMPRADOR_EN_FUERTE", "compra_freelance", 5.5,
        "Frase directa de contratacion freelance en ingles",
        _rx(r"\b(?:looking\s+to\s+hire|seeking\s+(?:a\s+)?(?:freelance\w*|dev\w*|python|coder|engineer|contractor|expert|specialist)|"
            r"want\s+to\s+hire|need\s+to\s+hire|hiring\s+(?:a\s+)?(?:freelance\w*|dev\w*|python|programmer|scraper|bot)|"
            r"hire\s+someone\s+to|paying\s+(?:someone\s+)?to|will\s+pay\s+(?:\$?\d+|for|someone)|willing\s+to\s+pay)\b"),
    ),
    ReglaPatron(
        "INTENCION_COMPRADOR_DELIVERABLE", "compra_freelance", 4.2,
        "Solicitud directa de entregable tecnico pago",
        _rx(r"\b(?:need\s+(?:someone|a\s+dev\w*|a\s+programmer|a\s+coder|a\s+freelancer)\s+to\s+(?:build|create|write|make|code|fix|scrape|automate|develop|deploy)|"
            r"looking\s+for\s+(?:someone|a\s+dev\w*|a\s+programmer|an?\s+expert)\s+to\s+(?:build|create|write|scrape|automate|code|fix|develop)|"
            r"need\s+(?:a\s+)?(?:custom\s+)?(?:python\s+script|scraper|telegram\s+bot|discord\s+bot|automation|webhook)\s+(?:built|made|created|developed))\b"),
    ),
    ReglaPatron(
        "PRESUPUESTO_DECLARADO_COMPRADOR", "compra_freelance", 3.8,
        "Cliente declara presupuesto, pago o escrow",
        _rx(r"\b(?:my\s+budget\s*(?:is|around|:)?|budget\s*(?:is|of|:)\s*\$?\d+|fixed[\s-]*price|milestone\s+payment|"
            r"can\s+pay\s+(?:via|with|in)?\s*(?:paypal|usdt|crypto|wise|stripe|binance|upwork)|"
            r"paid\s+(?:task|gig|project|work|job)|compensation\s*(?:is|:)\s*\$?\d+)\b"),
    ),
    ReglaPatron(
        "INTENCION_COMPRADOR_ES", "compra_freelance", 5.5,
        "Frase directa de contratacion freelance en espanol",
        _rx(r"\b(?:busco\s+(?:programador|desarrollador|freelancer|dev|experto|alguien\s+que)|"
            r"necesito\s+(?:contratar|programador|desarrollador|alguien\s+que\s+(?:me\s+)?(?:haga|cree|programe|desarrolle|automatice))|"
            r"pago\s+(?:por|bien|\$?\d+)|presupuesto\s*(?:de|:)?\s*\$?\d+|trabajo\s+remunerado|proyecto\s+pago)\b"),
    ),
    ReglaPatron(
        "CTA_PROPUESTA_COMPRADOR", "compra_freelance", 3.0,
        "Cliente solicita propuestas, cotizaciones o portafolio",
        _rx(r"\b(?:send\s+(?:me\s+)?(?:your\s+)?(?:portfolio|quote|estimate|rate|proposal|github|examples)|"
            r"dm\s+(?:me\s+)?(?:with\s+)?(?:your\s+)?(?:rate|quote|price|portfolio|experience)|"
            r"comment\s+\$bid|bid\s+below|drop\s+your\s+(?:portfolio|rates?)|envia\s+(?:tu\s+)?(?:cotizacion|portafolio|tarifa))\b"),
    ),
)

# ==================== 2. REGLAS DE BOUNTIES PAGOS ====================
REGLAS_BOUNTY: tuple[ReglaPatron, ...] = (
    ReglaPatron(
        "BOUNTY_PLATAFORMA_OFICIAL", "bounty", 8.0,
        "Bounty oficial de plataforma (Algora, Opire, Polar, Gitcoin)",
        _rx(r"\b(?:algora\.io|algora\s+bounty|opire|polar\.sh|gitcoin|bountysource|issuehunt|console\.algora|\/bounty\s+\$?\d+|\/attempt)\b"),
    ),
    ReglaPatron(
        "BOUNTY_ETIQUETA_O_RECOMPENSA", "bounty", 6.5,
        "Issue o tarea con recompensa monetaria por PR/solucion",
        _rx(r"(?:[\[\(]\s*bounty[^\]]*[\]\)]|\bbounty\s*(?:of|:|-)?\s*\$?\d+|\$\d+\s*bounty\b|"
            r"\breward\s*(?:of|:)\s*\$\d+|\bpaid\s+issue\b|\bpr\s+merged\b.*\b(?:reward|payout|bounty)\b)"),
    ),
)

# ==================== 3. REGLAS DE CONTRATO REMOTO (PART-TIME / B2B / C2C) ====================
REGLAS_CONTRATO_REMOTO: tuple[ReglaPatron, ...] = (
    ReglaPatron(
        "CONTRATO_EXTERNO_B2B", "contrato_remoto", 5.2,
        "Rol por contrato freelance, B2B, 1099 o part-time",
        _rx(r"\b(?:freelance\s+(?:role|position|engineer|developer|contract)|independent\s+contractor|"
            r"contract\s+(?:role|position|opportunity|work|to\s+hire|basis)|b2b\s+contract|1099\s+contractor|"
            r"part[\s-]*time\s+(?:remote|developer|engineer|python|contract)|fractional\s+(?:engineer|developer)|"
            r"project[\s-]*based\s+(?:contract|role)|short[\s-]*term\s+contract|hourly\s+contract|consulting\s+engagement)\b"),
    ),
    ReglaPatron(
        "CONTRATO_DURACION_ACOTADA", "contrato_remoto", 3.5,
        "Contrato con duracion definida en semanas o meses",
        _rx(r"\b(?:\d+\s*(?:-|to)\s*\d+\s*(?:weeks?|months?)\s+(?:contract|engagement|project)|"
            r"(?:1|2|3|6)\s*month\s+contract|\b(?:10|15|20|25)\s*(?:-|to)?\s*(?:20|30)?\s*(?:hrs?|hours?)\s*(?:\/|\s*per\s*)\s*week)\b"),
    ),
)

# ==================== 4. REGLAS DE EMPLEO CORPORATIVO FULL-TIME ====================
REGLAS_FULLTIME_CORP: tuple[ReglaPatron, ...] = (
    ReglaPatron(
        "CORP_BENEFICIOS_HR", "empleo_fulltime", 5.0,
        "Paquete de beneficios corporativos tipicos de empleo fijo",
        _rx(r"\b(?:401\s*\(?k\)?|health,?\s*dental,?\s*(?:and\s*)?vision|medical\s+insurance|paid\s+time\s+off|"
            r"unlimited\s+pto|parental\s+leave|stock\s+options|equity\s+package|annual\s+bonus|"
            r"equal\s+opportunity\s+employer|eeo\s+statement|background\s+check\s+required)\b"),
    ),
    ReglaPatron(
        "CORP_SENIORITY_ESTRUCTURA", "empleo_fulltime", 4.2,
        "Estructura corporativa full-time (salaried, grados, anos experiencia)",
        _rx(r"\b(?:full[\s-]*time\s+(?:salaried|permanent|employee|role|position)|permanent\s+position|"
            r"(?:5|6|7|8|10)\+\s*years?\s+of\s+(?:professional|industry|commercial)\s+experience|"
            r"bachelor'?s\s+degree\s+in\s+computer\s+science|reports?\s+(?:directly\s+)?to\s+the\s+(?:vp|cto|director|head\s+of)|"
            r"cross[\s-]*functional\s+teams|join\s+our\s+growing\s+engineering\s+team|series\s+[a-d]\s+startup)\b"),
    ),
    ReglaPatron(
        "CORP_SALARIO_ANUAL", "empleo_fulltime", 3.4,
        "Compensacion expresada como salario anual corporativo",
        _rx(r"(?:\$\d{2,3},000\s*(?:-|to)\s*\$\d{2,3},000|\b\d{2,3}k\s*(?:-|to)\s*\d{2,3}k\s*(?:usd|eur|gbp)?\s*(?:\/yr|per\s+year|annually|base\s+salary)|\bannual\s+salary\b)"),
    ),
)

# ==================== 5. DETECTOR PROFUNDO DE [FOR HIRE] / VENDEDOR CAMUFLADO ====================
REGLAS_OFRECIENDO_SERVICIOS: tuple[ReglaPatron, ...] = (
    ReglaPatron(
        "TAG_FOR_HIRE_EXPLICITO", "ofreciendo_servicios", 12.0,
        "Etiqueta explicita ofreciendo servicios ([For Hire]/[Offer]/[Selling])",
        _rx(r"(?:[\[\(]\s*(?:for\s*hire|forhire|offer|offering|selling|available|hire\s*me)\s*[\]\)]|^\s*(?:for\s*hire|offer|hire\s*me)\b)"),
        zonas=("flair", "titulo"),
        bloqueante=True,
    ),
    ReglaPatron(
        "HN_SEEKING_WORK", "ofreciendo_servicios", 12.0,
        "Formato 'SEEKING WORK' de desarrollador buscando trabajo",
        _rx(r"\b(?:seeking\s+work|available\s+for\s+hire|open\s+for\s+work|looking\s+for\s+(?:work|clients|freelance\s+gigs|projects\s+to\s+work\s+on))\b"),
        bloqueante=True,
    ),
    ReglaPatron(
        "VENDEDOR_CAMUFLADO_PRIMERA_PERSONA", "ofreciendo_servicios", 7.2,
        "Autopromocion de desarrollador o agencia ofreciendo servicios",
        _rx(r"\b(?:i\s*(?:am|'m)\s+a\s+(?:senior\s+|experienced\s+|freelance\s+)?(?:python\s+|web\s+|full[\s-]*stack\s+|software\s+|automation\s+)?(?:dev\w*|programmer|engineer|freelancer|scraper)\s+(?:with|offering|available|looking\s+for\s+(?:work|clients))|"
            r"i\s+(?:will\s+)?(?:build|create|develop|code)\s+(?:custom\s+)?(?:python\s+scripts?|scrapers?|bots?|websites?|automations?)\s+for\s+you|"
            r"my\s+(?:rates?|prices?|pricing)\s+start\s+at|starting\s+at\s+\$\d+\s*(?:\/hr|per\s+hour)?|"
            r"open\s+for\s+(?:commissions|new\s+clients|freelance\s+work)|hire\s+me\s+(?:to|for)|"
            r"check\s+out\s+my\s+portfolio|here\s+is\s+my\s+portfolio|dm\s+me\s+if\s+you\s+need\s+(?:a\s+)?(?:bot|scraper|script|dev\w*|website))\b"),
    ),
    ReglaPatron(
        "VENDEDOR_CAMUFLADO_ES", "ofreciendo_servicios", 7.5,
        "Autopromocion en espanol ofreciendo servicios freelance",
        _rx(r"\b(?:ofrezco\s+mis\s+servicios|soy\s+(?:desarrollador|programador|freelancer)\s+(?:python|web|disponible)|"
            r"disponible\s+para\s+(?:proyectos|trabajos|clientes)|te\s+(?:creo|hago|programo|desarrollo)\s+tu\s+(?:bot|scraper|web|script)|"
            r"escribeme\s+si\s+necesitas\s+un\s+(?:bot|scraper|programador))\b"),
    ),
    ReglaPatron(
        "AGENCIA_OFRECIENDO", "ofreciendo_servicios", 6.0,
        "Agencia o equipo vendiendo servicios de desarrollo",
        _rx(r"\b(?:we\s+are\s+a\s+(?:dev\w*|software|automation|ai)\s+agency|our\s+agency\s+(?:builds|offers|helps)|"
            r"we\s+offer\s+(?:custom\s+)?(?:scraping|automation|development)\s+services|book\s+a\s+(?:free\s+)?(?:discovery|strategy)\s+call\s+with\s+(?:me|us))\b"),
    ),
)

# ==================== 6. DETECTOR DE POSTS DE SOPORTE TECNICO / DUDAS GRATIS ====================
REGLAS_SOPORTE_DUDA: tuple[ReglaPatron, ...] = (
    ReglaPatron(
        "SOPORTE_ERROR_TRACEBACK", "soporte_o_duda", 5.5,
        "Pregunta de depuracion o error tecnico pidiendo ayuda gratis",
        _rx(r"\b(?:how\s+do\s+i\s+(?:fix|scrape|solve|bypass|handle|run|deploy)|"
            r"why\s+(?:is|does)\s+my\s+(?:code|script|scraper|bot|workflow)\s+(?:not\s+work\w*|fail\w*|return\w*|throw\w*)|"
            r"can\s+anyone\s+(?:help\s+me\s+(?:fix|understand|debug)|explain\s+why)|"
            r"getting\s+(?:an?\s+)?(?:403|404|500|attributeerror|typeerror|keyerror|modulenotfounderror|traceback)|"
            r"traceback\s*\(most\s+recent\s+call\s+last\)|any\s+(?:good\s+)?(?:tutorial|guide|course|resources?)\s+(?:for|on|to\s+learn))\b"),
    ),
    ReglaPatron(
        "SOPORTE_DUDA_ES", "soporte_o_duda", 5.0,
        "Pregunta de soporte o aprendizaje en espanol sin pago",
        _rx(r"\b(?:como\s+puedo\s+(?:arreglar|solucionar|hacer\s+que\s+funcione)|alguien\s+sabe\s+por\s+que\s+me\s+da\s+error|"
            r"ayuda\s+con\s+mi\s+codigo|algun\s+tutorial\s+para|soy\s+principiante\s+y\s+no\s+me\s+funciona)\b"),
    ),
    ReglaPatron(
        "SOPORTE_SIN_PAGO_EXPLICITO", "soporte_o_duda", 8.0,
        "Post declara explicitamente que es sin pago o voluntario",
        _rx(r"\b(?:unpaid\s+(?:project|internship|work|role|gig)|no\s+budget|zero\s+budget|\$0\s+budget|"
            r"for\s+exposure|for\s+experience\s+only|revenue\s+share\s+only|equity\s+only\s*\(no\s+pay\)|"
            r"volunteer\s+developer|cannot\s+pay|can'?t\s+pay\s+right\s+now|sin\s+presupuesto|no\s+hay\s+pago)\b"),
        bloqueante=True,
    ),
)

# ==================== 7. DETECTOR DE SPAM / AUTO-PROMO DE PRODUCTOS ====================
REGLAS_SPAM_PROMO: tuple[ReglaPatron, ...] = (
    ReglaPatron(
        "PROMO_SHOWCASE_SAAS", "spam_o_promo", 6.5,
        "Showcase o promocion de herramienta propia (no es cliente)",
        _rx(r"\b(?:i\s+built\s+(?:a|an|this)\s+(?:free|open[\s-]*source|new)\s+(?:tool|app|saas|scraper|bot|extension)|"
            r"just\s+launched\s+my\s+(?:saas|app|tool|startup)|check\s+out\s+my\s+(?:new\s+)?(?:tool|app|project|github\s+repo|youtube\s+channel)|"
            r"show\s+hn:|feedback\s+on\s+my\s+(?:mvp|saas|startup)|join\s+my\s+(?:newsletter|discord\s+community|waitlist)|"
            r"use\s+my\s+(?:promo|coupon|referral)\s+code|giveaway)\b"),
    ),
)

# ==================== 8. DETECTOR DE POST CERRADO / YA CONTRATADO ====================
REGLAS_CERRADO: tuple[ReglaPatron, ...] = (
    ReglaPatron(
        "POST_CERRADO_CABECERA", "cerrado", 15.0,
        "Flair o titulo marcado como cerrado/llenado",
        _rx(r"(?:[\[\(]\s*(?:closed|filled|completed|expired|found|hired|taken|solved|cerrado)\s*[\]\)]|^\s*(?:closed|filled|completed)\b)"),
        zonas=("flair", "titulo"),
        bloqueante=True,
    ),
    ReglaPatron(
        "POST_CERRADO_EDIT_CUERPO", "cerrado", 14.0,
        "Cliente edito el cuerpo indicando que ya contrato a alguien",
        _rx(r"(?:(?:edit|update|actualizacion)\s*[:\-]?\s*[^\n]{0,40}\b(?:found\s+(?:someone|a\s+dev\w*)|hired\s+someone|position\s+(?:is\s+)?filled|closed|no\s+longer\s+(?:needed|looking)|ya\s+encontre)\b|"
            r"\b(?:position\s+has\s+been\s+filled|no\s+longer\s+accepting\s+applications|this\s+task\s+is\s+closed|thanks\s+everyone,?\s+i\s+found\s+someone)\b)"),
        zonas=("cuerpo",),
        bloqueante=True,
    ),
)

# ==================== 9. URGENCIA Y RECURRENCIA ====================
REGEX_URGENCIA = _rx(
    r"\b(?:urgent\w*|asap|right\s+now|today|tonight|immediately|within\s+(?:a\s+few\s+)?(?:\d+\s+)?hours?|"
    r"within\s+24\s*h|by\s+tomorrow|tight\s+deadline|quick\s+turnaround|rush\s+job|para\s+hoy|lo\s+antes\s+posible)\b"
)
REGEX_RECURRENCIA = _rx(
    r"\b(?:ongoing|long[\s-]*term|retainer|monthly\s+(?:maintenance|retainer|support|work)|"
    r"recurring|repeat\s+work|more\s+projects\s+in\s+the\s+future|phase\s+2|continuous\s+work|"
    r"mantenimiento\s+mensual|trabajo\s+continuo|largo\s+plazo)\b"
)

# ==================== 10. GATEKEEPER GEOGRAFICO Y LEGAL (CALIBRADO PARA COLOMBIA / LATAM) ====================
REGLAS_GEO_BLOQUEO: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("GEO_US_ONLY", "Solo residentes o ciudadanos de EE.UU. (US-Only / W2)",
     _rx(r"\b(?:us\s+only|u\.s\.\s+only|usa\s+only|united\s+states\s+only|us[\s-]*based\s+only|"
         r"must\s+(?:be\s+)?(?:located|based|reside)\s+in\s+(?:the\s+)?(?:us|u\.s\.|usa|united\s+states)|"
         r"us\s+citizens?\s+only|u\.s\.\s+citizens?\s+only|us\s+work\s+authorization\s+required|"
         r"authorized\s+to\s+work\s+in\s+the\s+(?:us|united\s+states)|w[\s-]?2\s+only|no\s+c2c|"
         r"must\s+have\s+us\s+citizenship|green\s+card\s+or\s+us\s+citizen)\b")),
    ("GEO_CLEARANCE", "Requiere Security Clearance gubernamental",
     _rx(r"\b(?:active\s+(?:secret|top\s+secret)|ts\/sci|security\s+clearance\s+required|dod\s+clearance|itar\s+compliant)\b")),
    ("GEO_OTRO_PAIS_ESTRICTO", "Restringido a pais/region fuera de LATAM (UK/EU/CA/AU/IN)",
     _rx(r"\b(?:uk\s+only|united\s+kingdom\s+only|must\s+(?:be\s+)?(?:based|located|reside)\s+in\s+(?:the\s+)?(?:uk|canada|australia|germany|eu|europe|india|france|spain)|"
         r"eu\s+(?:residents?|citizens?)\s+only|canada\s+only|canadian\s+residents?\s+only|"
         r"australia\s+only|aus\s+residents?\s+only|eea\s+only|schengen\s+only|right\s+to\s+work\s+in\s+the\s+(?:uk|eu|australia|canada))\b")),
    ("GEO_PRESENCIAL_HIBRIDO", "Trabajo presencial o hibrido en oficina fisica",
     _rx(r"\b(?:on[\s-]*site\s+(?:only|required|position|role|in\s+[a-z]+)|in[\s-]*office\s+(?:only|required|\d+\s+days?)|"
         r"hybrid\s*(?:\(|:|-)?\s*(?:\d+\s+days?\s*(?:\/|\s*per\s*)?\s*week|in[\s-]*office|on[\s-]*site)|"
         r"local\s+candidates\s+only|relocation\s+(?:required|mandatory)|must\s+commute\s+to|"
         r"presencial\s+en|trabajo\s+presencial\s+obligatorio)\b")),
)

# Excepciones positivas para Colombia (UTC-5 / EST-CDT / LATAM / Worldwide)
REGEX_GEO_AMIGABLE_LATAM = _rx(
    r"\b(?:worldwide|work\s+from\s+anywhere|remote\s+anywhere|global\s+remote|international\s+contractors?|"
    r"latam|latin\s+america|south\s+america|colombia|americas\s+timezone|"
    r"(?:us|est|cst|eastern)\s+time\s*zone\s+overlap|overlap\s+with\s+(?:us|est|pst)\s+hours?)\b"
)

# ==================== 11. MODALIDAD DE TRABAJO ====================
REGEX_MOD_HORA = _rx(r"(?:\$\d+(?:\.\d+)?\s*(?:\/|\s*per\s*)\s*(?:hr|hour)|\bhourly\s+(?:rate|pay|basis|contract)\b|\bpor\s+hora\b)")
REGEX_MOD_RETAINER = _rx(r"(?:\$\d+(?:,\d{3})*\s*(?:\/|\s*per\s*)\s*(?:mo|month)|\bmonthly\s+retainer\b|\bretainer\b|\bmensualidad\b)")
REGEX_MOD_PUNTUAL = _rx(r"\b(?:fixed[\s-]*price|one[\s-]*off|one[\s-]*time\s+(?:project|task|script|job)|quick\s+(?:task|script|job|gig)|small\s+project|single\s+script|proyecto\s+puntual)\b")

# Priors por plataforma (conocimiento previo de la fuente)
PRIORS_PLATAFORMA: dict[str, dict[str, float]] = {
    "freelancer":     {"compra_freelance": 6.0},
    "github":         {"bounty": 7.0},
    "github bounty":  {"bounty": 7.0},
    "remoteok":       {"empleo_fulltime": 2.8},
    "wwr":            {"empleo_fulltime": 2.8},
    "weworkremotely": {"empleo_fulltime": 2.8},
    "remotive":       {"empleo_fulltime": 2.5},
    "jobicy":         {"empleo_fulltime": 2.5},
    "himalayas":      {"empleo_fulltime": 2.5},
    "workingnomads":  {"empleo_fulltime": 2.2},
    "arbeitnow":      {"empleo_fulltime": 2.8},
    "hackernews":     {"compra_freelance": 1.2},
    "reddit":         {},
    "rss":            {"compra_freelance": 1.0},
}

SUBS_EXIGEN_COMPRA_CLARA = {"webscraping", "discord_bots", "n8n", "automate", "pythonjobs"}


class ClasificadorIntencion:
    """
    Capa 3 de AEGIS-X: Clasifica si el autor es un comprador real o un vendedor camuflado,
    determina la modalidad contractual, detecta urgencia/retainers y aplica el gatekeeper
    geografico calibrado para freelancers trabajando remotamente desde LATAM/Colombia.
    """

    def __init__(self) -> None:
        self._reglas_todas: tuple[ReglaPatron, ...] = (
            REGLAS_CERRADO
            + REGLAS_OFRECIENDO_SERVICIOS
            + REGLAS_SOPORTE_DUDA
            + REGLAS_SPAM_PROMO
            + REGLAS_BOUNTY
            + REGLAS_COMPRA_FREELANCE
            + REGLAS_CONTRATO_REMOTO
            + REGLAS_FULLTIME_CORP
        )

    def clasificar(self, doc: DocumentoNormalizado, ctx: ContextoFiltro | None = None) -> AnalisisIntencion:
        ctx = ctx or ContextoFiltro()
        res = AnalisisIntencion()

        zonas = {
            "flair": _sin_acentos(doc.flair_limpio),
            "titulo": _sin_acentos(doc.titulo_limpio),
            "cuerpo": _sin_acentos(doc.cuerpo_limpio),
            "tags": _sin_acentos(doc.tags_limpio),
        }
        texto_full = _sin_acentos(doc.texto_unificado)

        ejes: dict[str, float] = {
            "compra_freelance": 0.0,
            "bounty": 0.0,
            "contrato_remoto": 0.0,
            "empleo_fulltime": 0.0,
            "ofreciendo_servicios": 0.0,
            "soporte_o_duda": 0.0,
            "spam_o_promo": 0.0,
            "cerrado": 0.0,
        }

        # 1. Aplicar priors de plataforma
        plat_key = (ctx.plataforma or ctx.fuente or "").lower().strip()
        for pk, bonus_map in PRIORS_PLATAFORMA.items():
            if pk in plat_key:
                for eje_k, val in bonus_map.items():
                    ejes[eje_k] += val
                break

        # Bonus por monto numerico proveniente de API (ej. Freelancer.com)
        if ctx.monto_api_usd > 0 and "freelancer" in plat_key:
            ejes["compra_freelance"] += 2.0

        # 2. Evaluar todas las reglas de intencion por zona
        bloqueo_duro_eje: str | None = None
        mult_zona = {"flair": 1.35, "titulo": 1.30, "tags": 1.05, "cuerpo": 1.00}

        for regla in self._reglas_todas:
            for z_nom in regla.zonas:
                txt_z = zonas.get(z_nom, "")
                if not txt_z:
                    continue
                m = regla.patron.search(txt_z)
                if m:
                    peso_eff = regla.peso * mult_zona[z_nom]
                    ejes[regla.eje] += peso_eff
                    es_neg = regla.eje in ("ofreciendo_servicios", "soporte_o_duda", "spam_o_promo", "cerrado")
                    res.senales.append(SenalDetectada(
                        codigo=regla.codigo,
                        categoria=CategoriaSenal.INTENCION,
                        descripcion=regla.descripcion,
                        peso=(-peso_eff if es_neg else peso_eff),
                        evidencia=m.group(0),
                        zona=z_nom,
                        bloqueante=regla.bloqueante,
                    ))
                    if regla.bloqueante and bloqueo_duro_eje is None:
                        bloqueo_duro_eje = regla.eje
                    break  # Una activacion por regla es suficiente

        # 3. Deteccion de urgencia y recurrencia
        m_urg = REGEX_URGENCIA.search(texto_full)
        if m_urg:
            res.es_urgente = True
            res.senales.append(SenalDetectada(
                codigo="INTENCION_URGENTE",
                categoria=CategoriaSenal.INTENCION,
                descripcion="El cliente expresa urgencia de entrega",
                peso=2.5,
                evidencia=m_urg.group(0),
                zona="combinado",
            ))

        m_rec = REGEX_RECURRENCIA.search(texto_full)
        if m_rec:
            res.es_recurrente = True
            res.senales.append(SenalDetectada(
                codigo="INTENCION_RECURRENTE",
                categoria=CategoriaSenal.INTENCION,
                descripcion="Potencial trabajo recurrente / retainer mensual",
                peso=3.0,
                evidencia=m_rec.group(0),
                zona="combinado",
            ))

        # 4. Gatekeeper geografico y legal (calibrado para LATAM/Colombia)
        es_latam_friendly = bool(REGEX_GEO_AMIGABLE_LATAM.search(texto_full))
        for cod_g, desc_g, rx_g in REGLAS_GEO_BLOQUEO:
            mg = rx_g.search(texto_full)
            if not mg:
                continue
            # Si solo menciona US timezone overlap o worldwide junto a una palabra suelta, no bloquear salvo que sea presencial/clearance/citizenship
            if es_latam_friendly and cod_g == "GEO_OTRO_PAIS_ESTRICTO":
                continue
            res.bloqueo_geografico = True
            res.motivo_geografico = f"{desc_g} ({mg.group(0)})"
            res.senales.append(SenalDetectada(
                codigo=cod_g,
                categoria=CategoriaSenal.GEOGRAFIA,
                descripcion=desc_g,
                peso=-12.0,
                evidencia=mg.group(0),
                zona="cuerpo",
                bloqueante=True,
            ))
            break

        if es_latam_friendly and not res.bloqueo_geografico:
            res.senales.append(SenalDetectada(
                codigo="GEO_AMIGABLE_LATAM",
                categoria=CategoriaSenal.GEOGRAFIA,
                descripcion="Oferta abierta a Worldwide / LATAM / zona horaria Americas",
                peso=2.2,
                evidencia="worldwide/latam/est-overlap",
                zona="cuerpo",
            ))

        # 5. Resolucion de intencion ganadora (con jerarquia de seguridad)
        sub_clean = (ctx.sub_o_categoria or ctx.fuente or "").lower().replace("r/", "").strip()

        if bloqueo_duro_eje == "cerrado" or ejes["cerrado"] >= 10.0:
            res.intencion = TipoIntencion.INDETERMINADO
            res.es_comprador_real = False
            res.confianza = 0.98
        elif bloqueo_duro_eje == "ofreciendo_servicios" or (
            ejes["ofreciendo_servicios"] >= 6.0 and ejes["ofreciendo_servicios"] > ejes["compra_freelance"]
        ):
            res.intencion = TipoIntencion.OFRECIENDO_SERVICIOS
            res.es_comprador_real = False
            res.confianza = min(0.99, 0.72 + ejes["ofreciendo_servicios"] / 25.0)
        elif bloqueo_duro_eje == "soporte_o_duda":
            res.intencion = TipoIntencion.SOPORTE_O_DUDA
            res.es_comprador_real = False
            res.confianza = 0.95
        elif ejes["spam_o_promo"] >= 6.0 and ejes["compra_freelance"] < 5.0:
            res.intencion = TipoIntencion.SPAM_O_PROMO
            res.es_comprador_real = False
            res.confianza = 0.90
        elif ejes["soporte_o_duda"] >= 5.0 and ejes["compra_freelance"] < 4.5 and ejes["bounty"] < 5.0:
            res.intencion = TipoIntencion.SOPORTE_O_DUDA
            res.es_comprador_real = False
            res.confianza = min(0.94, 0.65 + ejes["soporte_o_duda"] / 18.0)
        else:
            # Competencia entre ejes positivos de compra/trabajo
            positivos = {
                TipoIntencion.BOUNTY_PAGO: ejes["bounty"],
                TipoIntencion.CONTRATANDO_FREELANCE: ejes["compra_freelance"],
                TipoIntencion.CONTRATO_REMOTO: ejes["contrato_remoto"],
                TipoIntencion.EMPLEO_FULLTIME: ejes["empleo_fulltime"],
            }
            # Si un empleo remoto trae fuertes senales de contrato/freelance, asciende a CONTRATO_REMOTO
            if ejes["contrato_remoto"] >= 4.5 and ejes["empleo_fulltime"] > 0:
                positivos[TipoIntencion.CONTRATO_REMOTO] += 3.0

            ganador, puntaje_top = max(positivos.items(), key=lambda kv: kv[1])
            suma_pos = sum(positivos.values())

            # En subreddits nicho o busqueda global exigimos senal clara de compra (evita discusiones random)
            umbral_min = 3.5 if (ctx.es_busqueda_global or sub_clean in SUBS_EXIGEN_COMPRA_CLARA) else 2.2

            if puntaje_top < umbral_min:
                res.intencion = TipoIntencion.INDETERMINADO
                res.es_comprador_real = False
                res.confianza = 0.35
            else:
                res.intencion = ganador
                res.confianza = round(min(0.98, 0.52 + 0.46 * (1.0 - math.exp(-puntaje_top / 6.5)) * (puntaje_top / max(1.0, suma_pos))), 3)

                if ganador in (TipoIntencion.CONTRATANDO_FREELANCE, TipoIntencion.BOUNTY_PAGO, TipoIntencion.CONTRATO_REMOTO):
                    res.es_comprador_real = not res.bloqueo_geografico
                elif ganador == TipoIntencion.EMPLEO_FULLTIME:
                    # Un full-time remoto solo pasa si el usuario NO activo solo_freelance_corto y no hay bloqueo geo
                    res.es_comprador_real = (not ctx.solo_freelance_corto) and (not res.bloqueo_geografico)

        # 6. Clasificacion exacta de modalidad contractual
        if res.bloqueo_geografico and any(s.codigo == "GEO_PRESENCIAL_HIBRIDO" for s in res.senales):
            res.modalidad = ModalidadTrabajo.PRESENCIAL_HIBRIDO
        elif res.intencion == TipoIntencion.BOUNTY_PAGO:
            res.modalidad = ModalidadTrabajo.BOUNTY
        elif REGEX_MOD_RETAINER.search(texto_full) or (res.es_recurrente and res.intencion == TipoIntencion.CONTRATANDO_FREELANCE):
            res.modalidad = ModalidadTrabajo.RETAINER_MENSUAL
        elif REGEX_MOD_HORA.search(texto_full):
            res.modalidad = ModalidadTrabajo.POR_HORA
        elif res.intencion == TipoIntencion.EMPLEO_FULLTIME:
            res.modalidad = ModalidadTrabajo.FULL_TIME_REMOTO
        elif res.intencion in (TipoIntencion.CONTRATANDO_FREELANCE, TipoIntencion.CONTRATO_REMOTO) or REGEX_MOD_PUNTUAL.search(texto_full):
            res.modalidad = ModalidadTrabajo.PROYECTO_PUNTUAL
        else:
            res.modalidad = ModalidadTrabajo.DESCONOCIDA

        return res


_INTENCION_SINGLETON = ClasificadorIntencion()


def analizar_intencion(doc: DocumentoNormalizado, ctx: ContextoFiltro | None = None) -> AnalisisIntencion:
    return _INTENCION_SINGLETON.clasificar(doc, ctx=ctx)