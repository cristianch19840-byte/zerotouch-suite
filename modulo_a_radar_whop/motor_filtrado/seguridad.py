from __future__ import annotations

import re
from dataclasses import dataclass

from modulo_a_radar_whop.motor_filtrado.modelos import (
    AnalisisIntencion,
    AnalisisRiesgo,
    CategoriaSenal,
    ContextoFiltro,
    DocumentoNormalizado,
    NivelRiesgo,
    PerfilEconomico,
    SenalDetectada,
)


def _rx(expr: str) -> re.Pattern[str]:
    return re.compile(expr, re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True, slots=True)
class ReglaSeguridad:
    codigo: str
    grupo: str
    severidad: float  # puntos de riesgo 0..100
    bloqueo_duro: bool
    bandera_corta: str
    descripcion: str
    patron: re.Pattern[str]
    zonas: tuple[str, ...] = ("titulo", "cuerpo", "tags")


# ==================== BLOQUE A: IDENTIDAD, KYC Y ALQUILER DE CUENTAS (BLOQUEO DURO) ====================
REGLAS_IDENTIDAD_KYC: tuple[ReglaSeguridad, ...] = (
    ReglaSeguridad(
        "SEC_ALQUILER_CUENTA_UPWORK", "identidad_kyc", 95.0, True,
        "Alquiler ilegal de cuenta Upwork/Fiverr/LinkedIn",
        "Intento de alquilar o compartir cuenta de freelance o acceso remoto a PC",
        _rx(r"\b(?:rent\s+(?:your\s+|an?\s+)?(?:upwork|fiverr|freelancer|linkedin|toptal)\s+account|"
            r"(?:upwork|fiverr|freelancer)\s+account\s+(?:for\s+rent|rental|partner\w*|lease|share|sharing)|"
            r"share\s+your\s+(?:upwork|fiverr|laptop|pc|computer)\s+(?:with\s+me|for\s+\d+%)|"
            r"need\s+(?:a\s+)?(?:us|eu|uk|latam|colombian?)\s+(?:upwork|linkedin)\s+account|"
            r"(?:anydesk|teamviewer|rustdesk)\s+access\s+(?:to\s+your\s+pc|24\/7)|"
            r"alquilo\s+cuenta\s+(?:de\s+)?(?:upwork|fiverr|linkedin))\b"),
    ),
    ReglaSeguridad(
        "SEC_KYC_VERIFICACION", "identidad_kyc", 95.0, True,
        "Estafa KYC / Verificacion de identidad",
        "Solicitud de verificacion KYC, documentos de identidad o cuentas bancarias/cripto",
        _rx(r"\b(?:kyc\s+(?:verification|needed|task|job|account|partner)|pass\s+kyc|complete\s+kyc|"
            r"verify\s+(?:my|an?|this)\s+(?:binance|coinbase|bybit|okx|kraken|wise|revolut|stripe|paypal|mercury|paxful|bet365|outlier|remotasks)\s+account|"
            r"sell\s+(?:your\s+)?(?:verified\s+)?(?:binance|stripe|wise|paypal|upwork|aws|google\s+cloud)\s+account|"
            r"buy\s+verified\s+(?:accounts?|stripe|wise|paypal|binance)|"
            r"use\s+your\s+(?:id|passport|ssn|driver'?s\s+license)\s+to\s+(?:verify|register|open)|"
            r"verificar\s+cuenta\s+(?:con\s+cedula|con\s+pasaporte|de\s+binance))\b"),
    ),
    ReglaSeguridad(
        "SEC_MULA_FINANCIERA", "identidad_kyc", 98.0, True,
        "Riesgo de lavado / mula financiera",
        "Pide recibir dinero en cuenta personal y reenviarlo por cripto/transferencia",
        _rx(r"\b(?:receive\s+(?:money|funds|payments?|wires?)\s+(?:in|to|into)\s+your\s+(?:bank\s+)?account\s+and\s+(?:send|forward|convert|transfer)|"
            r"payment\s+processor\s+agent\s+from\s+home|keep\s+\d+%\s+(?:and\s+)?(?:send|forward)\s+the\s+rest|"
            r"recibir\s+transferencias\s+y\s+reenviar\s+(?:en\s+)?usdt)\b"),
    ),
    ReglaSeguridad(
        "SEC_GRANJA_REVIEWS_CUENTAS", "identidad_kyc", 85.0, True,
        "Granja de resenas falsas o compra de votos",
        "Solicitud de resenas falsas, votos pagados o creacion masiva de cuentas fraudulentas",
        _rx(r"\b(?:fake\s+(?:google|trustpilot|amazon|yelp|app\s+store)\s+reviews?|"
            r"leave\s+(?:a\s+)?5[\s-]*star\s+review\s+for\s+\$?\d+|"
            r"buy\s+(?:google|trustpilot|amazon)\s+reviews?|paid\s+(?:upvotes?|reviews?)|"
            r"mass\s+create\s+(?:gmail|outlook|instagram|tiktok|facebook|reddit)\s+accounts?|"
            r"phone\s+verified\s+accounts?\s*\(?pva\)?|resenas?\s+falsas?)\b"),
    ),
)

# ==================== BLOQUE B: MALWARE, DRAINERS, HACKING ILEGAL Y TRAMPAS A DEVS ====================
REGLAS_MALWARE_ILEGAL: tuple[ReglaSeguridad, ...] = (
    ReglaSeguridad(
        "SEC_WALLET_DRAINER", "malware_ilegal", 100.0, True,
        "Crypto wallet drainer / robo de seed phrases",
        "Solicitud de software malicioso orientado al robo de wallets o claves privadas",
        _rx(r"\b(?:wallet\s+drainer|crypto\s+drainer|solana\s+drainer|eth\s+drainer|drainer\s+script|"
            r"seed\s+phrase\s+(?:stealer|grabber|finder|cracker|brute)|private\s+key\s+(?:stealer|cracker|brute)|"
            r"crypto\s+clipper|clipboard\s+hijacker|metamask\s+stealer|phantom\s+drainer|"
            r"honeypot\s+token\s+contract|rug\s*pull\s+(?:contract|script))\b"),
    ),
    ReglaSeguridad(
        "SEC_MALWARE_RAT_STEALER", "malware_ilegal", 100.0, True,
        "Malware / RAT / Keylogger / Info-stealer",
        "Solicitud de creacion o distribucion de malware, troyanos o spyware",
        _rx(r"\b(?:keylogger|info[\s-]*stealer|token\s+grabber|discord\s+token\s+grabber|"
            r"cookie\s+stealer|browser\s+password\s+stealer|remote\s+access\s+trojan|\brat\s+builder\b|"
            r"fud\s+crypter|bypass\s+windows\s+defender\s+(?:payload|exe)|ransomware|botnet|ddos\s+(?:tool|script|booter)|"
            r"spyware\s+(?:for|on)\s+(?:my\s+)?(?:wife|husband|partner|gf|bf|phone))\b"),
    ),
    ReglaSeguridad(
        "SEC_PHISHING_CARDING_CRACK", "malware_ilegal", 100.0, True,
        "Phishing / Carding / Robo de credenciales",
        "Actividad ilegal de phishing, clonacion de paginas bancarias o cracking de cuentas",
        _rx(r"\b(?:phishing\s+(?:page|kit|site|template|link)|fake\s+(?:login|bank|paypal|binance|icloud)\s+page|"
            r"credential\s+stuffing|account\s+cracker|combo\s+list|openbullet\s+config|silverbullet\s+config|"
            r"carding|cc\s+checker|cvv\s+checker|fullz|bank\s+logs|hack\s+(?:into\s+)?(?:an?\s+)?(?:instagram|facebook|whatsapp|gmail|snapchat|tiktok)\s+account|"
            r"hackear\s+(?:cuenta|whatsapp|instagram|facebook))\b"),
    ),
    ReglaSeguridad(
        "SEC_TRAMPA_MALWARE_DEV", "malware_ilegal", 62.0, False,
        "Posible trampa de malware dirigida al dev (ejecutar repo/binario)",
        "Patron tipo 'Contagious Interview': pide descargar y ejecutar zip/exe/repo antes de contratar",
        _rx(r"\b(?:download\s+and\s+run\s+(?:this|my|the)\s+(?:zip|exe|msi|bat|file|project)\s+(?:first|before|to\s+see)|"
            r"run\s+(?:this\s+)?(?:exe|installer|script)\s+on\s+your\s+(?:pc|machine)\s+(?:before|for)\s+(?:the\s+)?interview|"
            r"disable\s+(?:your\s+)?antivirus\s+(?:to\s+run|before\s+running)|"
            r"clone\s+(?:my|this)\s+(?:bitbucket|github)\s+repo\s+and\s+run\s+(?:npm\s+start|python)\s+(?:immediately|now)\s+for\s+(?:the\s+)?(?:test|interview))\b"),
    ),
)

# ==================== BLOQUE C: ESTAFAS FINANCIERAS Y DE PAGO AL FREELANCER ====================
REGLAS_ESTAFAS_PAGO: tuple[ReglaSeguridad, ...] = (
    ReglaSeguridad(
        "SEC_PAGO_ADELANTADO_DEV", "estafa_pago", 95.0, True,
        "Estafa de cobro al freelancer (advance-fee / task scam)",
        "Exige que el desarrollador pague deposito, tarifa de registro o recarga USDT",
        _rx(r"\b(?:pay\s+(?:a\s+)?(?:small\s+)?(?:registration|security|verification|onboarding|membership)\s+fee|"
            r"refundable\s+(?:security\s+)?deposit\s+(?:from\s+you|required\s+to\s+start)|"
            r"recharge\s+(?:your\s+)?(?:usdt|account)\s+to\s+(?:unlock|withdraw)|"
            r"deposit\s+\$?\d+\s+(?:in\s+usdt\s+)?to\s+(?:start|activate|withdraw)|"
            r"buy\s+(?:equipment|laptop|software)\s+from\s+our\s+(?:approved\s+)?vendor|"
            r"paga\s+(?:una\s+)?(?:cuota|inscripcion|deposito)\s+para\s+empezar)\b"),
    ),
    ReglaSeguridad(
        "SEC_CHEQUE_FALSO", "estafa_pago", 95.0, True,
        "Estafa de cheque falso / sobrepago",
        "Patron clasico de pago con cheque movil y devolucion de excedente",
        _rx(r"\b(?:mobile\s+check\s+deposit|e[\s-]*check\s+for\s+equipment|cashier'?s\s+check\s+(?:to\s+buy|and\s+send)|"
            r"overpay\s+you\s+and\s+(?:you\s+)?send\s+back|send\s+back\s+the\s+(?:difference|extra|remaining))\b"),
    ),
    ReglaSeguridad(
        "SEC_DINERO_FACIL_MLM", "estafa_pago", 80.0, True,
        "Esquema de dinero facil / MLM / apuestas",
        "Promesa fraudulenta de ganancias garantizadas, senales forex o esquemas piramidales",
        _rx(r"\b(?:make\s+\$\d{3,4}\s+(?:a\s+day|daily)\s+(?:from\s+home|easily|guaranteed)|"
            r"guaranteed\s+(?:daily\s+)?(?:profit|returns?|roi\s+of\s+\d+%)|"
            r"pump\s+and\s+dump\s+group|binary\s+options\s+signals|forex\s+account\s+flipping|"
            r"gana\s+\$\d{3,}\s+diarios\s+sin\s+experiencia)\b"),
    ),
)

# ==================== BLOQUE D: EXPLOTACION, SPEC WORK GRATIS Y RIESGO DE IMPAGO ====================
REGLAS_EXPLOTACION: tuple[ReglaSeguridad, ...] = (
    ReglaSeguridad(
        "SEC_SPEC_WORK_GRATIS", "explotacion", 48.0, False,
        "Exige trabajo/prototipo gratis antes de contratar",
        "Cliente pide construir el entregable o prueba completa sin pago para 'evaluar'",
        _rx(r"\b(?:build\s+(?:a\s+)?(?:free\s+)?(?:working\s+)?(?:prototype|mvp|demo|sample|scraper|bot)\s+(?:for\s+free|first\s+before\s+(?:i\s+)?(?:hire|pay))|"
            r"unpaid\s+(?:test\s+(?:project|task|assignment)|trial\s+(?:week|period|project))|"
            r"send\s+(?:me\s+)?(?:the\s+)?(?:full\s+)?working\s+(?:code|script)\s+first\s+so\s+i\s+can\s+test|"
            r"do\s+(?:the\s+)?first\s+(?:task|script|milestone)\s+for\s+free\s+to\s+prove|"
            r"hazme\s+(?:una\s+)?prueba\s+gratis\s+primero)\b"),
    ),
    ReglaSeguridad(
        "SEC_PAGO_CONDICIONADO", "explotacion", 52.0, False,
        "Pago condicionado a ventas/viralidad o solo comision",
        "El cliente traslada su riesgo comercial al dev (paga solo si el negocio despega)",
        _rx(r"\b(?:pay\s+(?:you\s+)?(?:only\s+)?(?:if|once|when)\s+(?:it\s+)?(?:makes\s+money|gets\s+users|gets\s+funded|goes\s+viral|sells)|"
            r"profit\s+share\s+only|rev(?:enue)?\s*share\s+only|commission[\s-]*only\s+(?:developer|coding|role)|"
            r"future\s+equity\s+instead\s+of\s+(?:cash|pay)|te\s+pago\s+cuando\s+(?:venda|genere\s+ingresos))\b"),
    ),
    ReglaSeguridad(
        "SEC_ANTI_ESCROW_SIN_ADELANTO", "explotacion", 30.0, False,
        "Se niega a deposito inicial o escrow",
        "Riesgo de impago tras entregar el codigo fuente",
        _rx(r"\b(?:no\s+(?:upfront|deposit|advance|milestone)\s+(?:payment|at\s+all)|"
            r"will\s+not\s+pay\s+(?:anything\s+)?upfront|100%\s+(?:payment\s+)?only\s+after\s+(?:full\s+)?(?:completion|delivery|source\s+code)|"
            r"no\s+escrow|sin\s+adelanto\s+pago\s+al\s+final)\b"),
    ),
)

# ==================== BLOQUE E: DESVIO OFF-PLATFORM, LINKS ACORTADOS Y BINARIOS ====================
REGLAS_CONTACTO_LINKS: tuple[ReglaSeguridad, ...] = (
    ReglaSeguridad(
        "SEC_DESVIO_OFF_PLATFORM", "contacto_riesgo", 32.0, False,
        "Desvio sospechoso a WhatsApp/Telegram fuera de plataforma",
        "Pide salir inmediatamente de la plataforma hacia WhatsApp/Telegram personal",
        _rx(r"\b(?:contact\s+me\s+(?:only\s+)?on\s+(?:whatsapp|telegram|snapchat|signal)|"
            r"(?:dm|message|text|ping|add)\s+me\s+on\s+(?:whatsapp|telegram|wa\.me|t\.me)\s*[:@]?\s*(?:\+?\d|@?[a-z0-9_])|"
            r"don'?t\s+(?:bid|reply)\s+here,?\s+(?:message|contact|text)\s+me\s+on\s+(?:telegram|whatsapp)|"
            r"escribeme\s+(?:solo\s+)?al\s+whatsapp\s*\+?\d)\b"),
    ),
    ReglaSeguridad(
        "SEC_DESCARGA_EJECUTABLE", "contacto_riesgo", 55.0, False,
        "Link a ejecutable o archivo comprimido sospechoso",
        "Enlaza ejecutables o servicios de descarga directa pidiendo ejecutar archivos",
        _rx(r"(?:https?:\/\/[^\s]+\.(?:exe|msi|scr|bat|cmd|ps1|vbs|dmg)(?:\?|\b)|"
            r"(?:mega\.nz|mediafire\.com|anonfiles\.|gofile\.io|transfer\.sh)\/[^\s]+)"),
    ),
)

# ==================== BLOQUE F: CLIENTES TOXICOS Y SCOPE CREEP ====================
REGLAS_CLIENTE_TOXICO: tuple[ReglaSeguridad, ...] = (
    ReglaSeguridad(
        "SEC_MINIMIZA_ESFUERZO", "cliente_toxico", 18.0, False,
        "Minimiza el esfuerzo ('5 minute easy job')",
        "Suele anticipar regateo agresivo o desconocimiento del trabajo real",
        _rx(r"\b(?:should\s+(?:only\s+)?take\s+(?:you\s+)?(?:5|10|15|20|30)\s*min(?:ute)?s?\s*(?:for\s+an?\s+expert)?|"
            r"super\s+easy\s+(?:5|10)\s*min(?:ute)?\s+job|very\s+simple\s+for\s+someone\s+who\s+knows|"
            r"es\s+super\s+facil\s+en\s+(?:5|10)\s+minutos)\b"),
    ),
    ReglaSeguridad(
        "SEC_REVISIONES_ILIMITADAS", "cliente_toxico", 22.0, False,
        "Exige revisiones ilimitadas o soporte gratis eterno",
        "Alto riesgo de scope creep infinito sin pago adicional",
        _rx(r"\b(?:unlimited\s+revisions?|free\s+(?:lifetime|ongoing)\s+(?:support|updates|maintenance)|"
            r"until\s+i\s+am\s+1000%\s+satisfied|cambios\s+ilimitados\s+sin\s+costo)\b"),
    ),
    ReglaSeguridad(
        "SEC_HISTORIAL_CONFLICTIVO", "cliente_toxico", 20.0, False,
        "Se queja de multiples devs previos ('todos me estafaron')",
        "Indicador frecuente de requisitos mal definidos o cliente conflictivo",
        _rx(r"\b(?:my\s+last\s+(?:2|3|4|5|two|three|several)\s+(?:devs?|developers?|freelancers?)\s+(?:were\s+(?:useless|terrible|scammers)|failed|disappeared)|"
            r"tired\s+of\s+useless\s+freelancers|don'?t\s+waste\s+my\s+time\s+if\s+you\s+aren'?t\s+a\s+rockstar)\b"),
    ),
    ReglaSeguridad(
        "SEC_URGENCIA_EXTREMA_SOSPECHOSA", "cliente_toxico", 16.0, False,
        "Presion de cierre inmediato en minutos",
        "Presion artificial para decidir sin revisar alcance ni condiciones",
        _rx(r"\b(?:need\s+this\s+in\s+(?:30\s+minutes|1\s+hour)\s+or\s+don'?t\s+apply|reply\s+in\s+5\s+minutes\s+only|urgent\s+instant\s+start\s+no\s+questions)\b"),
    ),
)

# Dominios con TLD estadisticamente saturados de phishing/spam
TLDS_SOSPECHOSOS = (".xyz", ".top", ".click", ".gq", ".tk", ".ml", ".cf", ".work", ".zip", ".mov", ".ru")
DOMINIOS_WHITELIST_DEV = {
    "github.com", "gitlab.com", "bitbucket.org", "stackoverflow.com", "pypi.org",
    "docs.python.org", "npmjs.com", "vercel.app", "netlify.app", "railway.app",
    "render.com", "algora.io", "polar.sh", "reddit.com", "freelancer.com",
    "news.ycombinator.com", "remoteok.com", "weworkremotely.com", "remotive.com",
    "jobicy.com", "himalayas.app", "workingnomads.com", "arbeitnow.com",
    "notion.so", "airtable.com", "figma.com", "loom.com", "youtube.com", "youtu.be",
    "docs.google.com", "sheets.google.com", "drive.google.com", "shopify.com",
}


class EscudoSeguridad:
    """
    Capa 5 de AEGIS-X: Evalua 40+ heuristicas anti-estafa, anti-malware,
    anti-explotacion, anomalias forenses Unicode y matriz de correlacion de amenazas.
    """

    def __init__(self) -> None:
        self._reglas: tuple[ReglaSeguridad, ...] = (
            REGLAS_IDENTIDAD_KYC
            + REGLAS_MALWARE_ILEGAL
            + REGLAS_ESTAFAS_PAGO
            + REGLAS_EXPLOTACION
            + REGLAS_CONTACTO_LINKS
            + REGLAS_CLIENTE_TOXICO
        )

    def analizar(
        self,
        doc: DocumentoNormalizado,
        ctx: ContextoFiltro | None = None,
        econ: PerfilEconomico | None = None,
        intent: AnalisisIntencion | None = None,
    ) -> AnalisisRiesgo:
        ctx = ctx or ContextoFiltro()
        res = AnalisisRiesgo()

        zonas = {
            "titulo": doc.titulo_limpio,
            "cuerpo": doc.cuerpo_limpio,
            "tags": doc.tags_limpio,
        }
        codigos_activos: set[str] = set()
        riesgo_acum = 0.0

        def _registrar(
            codigo: str,
            sev: float,
            desc: str,
            bandera: str,
            evidencia: str = "",
            zona: str = "cuerpo",
            bloqueante: bool = False,
            cat: CategoriaSenal = CategoriaSenal.SEGURIDAD,
        ) -> None:
            nonlocal riesgo_acum
            if codigo in codigos_activos:
                return
            codigos_activos.add(codigo)
            riesgo_acum += sev
            if bandera and bandera not in res.banderas_rojas:
                res.banderas_rojas.append(bandera)
            if bloqueante:
                res.bloqueo_duro = True
                if desc not in res.razones_bloqueo:
                    res.razones_bloqueo.append(desc)
            res.senales.append(SenalDetectada(
                codigo=codigo,
                categoria=cat,
                descripcion=desc,
                peso=-round(sev / 10.0, 2),
                evidencia=evidencia[:120],
                zona=zona,
                bloqueante=bloqueante,
            ))

        # 1. Evaluar las reglas forenses por bloques A..F
        for regla in self._reglas:
            for z in regla.zonas:
                txt = zonas.get(z, "")
                if not txt:
                    continue
                m = regla.patron.search(txt)
                if m:
                    _registrar(
                        codigo=regla.codigo,
                        sev=regla.severidad,
                        desc=regla.descripcion,
                        bandera=regla.bandera_corta,
                        evidencia=m.group(0),
                        zona=z,
                        bloqueante=regla.bloqueo_duro,
                    )
                    break

        # 2. Auditoria de entidades extraidas (acortadores, TLDs riesgosos, contacto externo)
        ent = doc.entidades
        plat_low = (ctx.plataforma or ctx.fuente or "").lower()

        if ent.acortadores_detectados:
            _registrar(
                "SEC_ACORTADOR_URL", 28.0,
                "Enlace oculto con acortador de URL (bit.ly / tinyurl / similar)",
                "Link acortado (oculta destino real)",
                evidencia=", ".join(ent.acortadores_detectados[:3]),
                zona="cuerpo",
            )

        tlds_malos = [
            dom for dom in ent.dominios
            if dom not in DOMINIOS_WHITELIST_DEV and any(dom.endswith(tld) for tld in TLDS_SOSPECHOSOS)
        ]
        if tlds_malos:
            _registrar(
                "SEC_DOMINIO_TLD_RIESGO", 24.0,
                "Dominio externo con TLD de alta incidencia de spam/phishing",
                f"Dominio riesgoso ({tlds_malos[0]})",
                evidencia=", ".join(tlds_malos[:3]),
                zona="cuerpo",
            )

        # Contacto off-platform dentro de Freelancer.com es violacion directa de escrow y patron #1 de scam
        if ent.canales_contacto_externo and "freelancer" in plat_low:
            _registrar(
                "SEC_FREELANCER_OFF_PLATFORM", 58.0,
                "Intento de sacar al freelancer de Freelancer.com hacia chat externo (evasion de escrow)",
                "Intenta sacarte de Freelancer.com (sin escrow)",
                evidencia=", ".join(ent.canales_contacto_externo[:2]),
                zona="cuerpo",
            )
        elif ent.canales_contacto_externo and "SEC_DESVIO_OFF_PLATFORM" not in codigos_activos:
            # En Reddit/HN un t.me o wa.me suelto es senal leve-media de precaucion, no bloqueo automatico
            _registrar(
                "SEC_CONTACTO_EXTERNO_LEVE", 16.0,
                "Incluye enlace directo de mensajeria externa (verifica antes de enviar codigo)",
                "Pide contacto externo (pide 50% adelanto)",
                evidencia=", ".join(ent.canales_contacto_externo[:2]),
                zona="cuerpo",
            )

        # 3. Anomalias forenses del Normalizador (evasion deliberada de filtros)
        met = doc.metricas
        if met.homoglifos_reemplazados >= 2:
            _registrar(
                "SEC_EVASION_HOMOGLIFOS", 42.0,
                f"Uso deliberado de {met.homoglifos_reemplazados} homoglifos cirilicos/griegos para burlar filtros",
                "Texto ofuscado con homoglifos Unicode",
                evidencia=f"{met.homoglifos_reemplazados} homoglifos",
                zona="titulo",
                cat=CategoriaSenal.CALIDAD_TEXTO,
            )

        if met.chars_invisibles_eliminados >= 2:
            _registrar(
                "SEC_EVASION_INVISIBLES", 34.0,
                f"Inyeccion de {met.chars_invisibles_eliminados} caracteres Unicode invisibles",
                "Caracteres invisibles anti-filtro",
                evidencia=f"{met.chars_invisibles_eliminados} invisibles",
                zona="titulo",
                cat=CategoriaSenal.CALIDAD_TEXTO,
            )

        if met.evasion_espaciada_detectada:
            _registrar(
                "SEC_EVASION_ESPACIADA", 35.0,
                "Palabra ofuscada con puntos o espacios (ej. w.h.a.t.s.a.p.p / k y c)",
                "Ofuscacion deliberada de palabras",
                evidencia="punteado/espaciado",
                zona="cuerpo",
                cat=CategoriaSenal.CALIDAD_TEXTO,
            )

        if met.ratio_mayusculas > 0.72 and met.palabras_totales >= 12:
            _registrar(
                "SEC_GRITO_MAYUSCULAS", 15.0,
                "Texto escrito casi totalmente en mayusculas (patron de spam/urgencia falsa)",
                "Todo en mayusculas",
                evidencia=f"{int(met.ratio_mayusculas * 100)}% CAPS",
                zona="titulo",
                cat=CategoriaSenal.CALIDAD_TEXTO,
            )

        if met.entropia_shannon < 2.5 and (met.chars_titulo + met.chars_cuerpo) >= 35:
            _registrar(
                "SEC_BAJA_ENTROPIA", 30.0,
                "Entropia de Shannon anomala (texto repetitivo o basura generada)",
                "Texto repetitivo de baja entropia",
                evidencia=f"H={met.entropia_shannon:.2f}",
                zona="cuerpo",
                cat=CategoriaSenal.CALIDAD_TEXTO,
            )

        # 4. Blacklist personalizada del usuario (config.json -> palabras_extra_blacklist)
        if ctx.palabras_blacklist_usuario:
            low_busq = doc.texto_busqueda
            for palabra in ctx.palabras_blacklist_usuario:
                p = str(palabra).strip().lower()
                if p and p in low_busq:
                    _registrar(
                        "SEC_BLACKLIST_USUARIO", 90.0,
                        f"Coincidencia con palabra bloqueada por el usuario: '{p}'",
                        f"Blacklist usuario ({p})",
                        evidencia=p,
                        zona="combinado",
                        bloqueante=True,
                    )
                    break

        # 5. MATRIZ DE CORRELACION DE AMENAZAS (senales compuestas que delatan estafas sofisticadas)
        # Combo 1: Ofuscacion (homoglifos/invisibles/espaciado) + Contacto externo o acortador -> BLOQUEO DURO
        tiene_ofuscacion = bool(codigos_activos & {"SEC_EVASION_HOMOGLIFOS", "SEC_EVASION_INVISIBLES", "SEC_EVASION_ESPACIADA"})
        tiene_canal_riesgo = bool(codigos_activos & {"SEC_ACORTADOR_URL", "SEC_DESVIO_OFF_PLATFORM", "SEC_CONTACTO_EXTERNO_LEVE", "SEC_FREELANCER_OFF_PLATFORM"})
        if tiene_ofuscacion and tiene_canal_riesgo:
            _registrar(
                "SEC_COMBO_EVASION_SCAM", 85.0,
                "Correlacion critica: ofuscacion anti-filtro combinada con desvio externo o link acortado",
                "Scam ofuscado con link/chat externo",
                evidencia="ofuscacion + canal_externo",
                zona="combinado",
                bloqueante=True,
            )

        # Combo 2: Trampa de malware/entrevista + descarga ejecutable o acortador -> BLOQUEO DURO
        if "SEC_TRAMPA_MALWARE_DEV" in codigos_activos and bool(codigos_activos & {"SEC_DESCARGA_EJECUTABLE", "SEC_ACORTADOR_URL"}):
            _registrar(
                "SEC_COMBO_MALWARE_INTERVIEW", 95.0,
                "Correlacion critica: ataque de malware dirigido a desarrolladores via archivo/link",
                "ATAQUE MALWARE A DEV — NO EJECUTAR",
                evidencia="interview_trap + ejecutable",
                zona="combinado",
                bloqueante=True,
            )

        # Combo 3: Spec work gratis + se niega a adelanto/escrow -> BLOQUEO DURO
        if "SEC_SPEC_WORK_GRATIS" in codigos_activos and "SEC_ANTI_ESCROW_SIN_ADELANTO" in codigos_activos:
            _registrar(
                "SEC_COMBO_ROBO_CODIGO", 80.0,
                "Correlacion alta: exige prototipo gratis y rechaza escrow/adelanto (robo de trabajo)",
                "Alto riesgo de robo de codigo sin pago",
                evidencia="spec_work + no_upfront",
                zona="combinado",
                bloqueante=True,
            )

        # Combo 4: Presupuesto lowball + cliente toxico (minimiza esfuerzo o revisiones ilimitadas)
        if econ and econ.es_lowball and bool(codigos_activos & {"SEC_MINIMIZA_ESFUERZO", "SEC_REVISIONES_ILIMITADAS", "SEC_HISTORIAL_CONFLICTIVO"}):
            _registrar(
                "SEC_COMBO_LOWBALL_TOXICO", 28.0,
                "Cliente lowballer con senales toxicas (mal negocio garantizado)",
                "Combo Lowball + Cliente toxico",
                evidencia="lowball + toxicidad",
                zona="combinado",
            )

        # Combo 5: Urgencia artificial + desvío a WhatsApp/Telegram en Freelancer
        if intent and intent.es_urgente and "SEC_FREELANCER_OFF_PLATFORM" in codigos_activos:
            _registrar(
                "SEC_COMBO_URGENCIA_OFFPLATFORM", 30.0,
                "Urgencia artificial para sacarte rapido del escrow de Freelancer.com",
                "Urgencia para evadir escrow",
                evidencia="urgente + off_platform",
                zona="combinado",
                bloqueante=True,
            )

        # 6. Normalizacion final del score de riesgo y clasificacion de NivelRiesgo
        score_final = min(100.0, round(riesgo_acum, 1))
        if score_final >= 85.0 and not res.bloqueo_duro:
            res.bloqueo_duro = True
            res.razones_bloqueo.append(f"Acumulacion critica de senales de riesgo ({score_final:.0f}/100)")

        res.score_riesgo_0_100 = score_final
        if res.bloqueo_duro:
            res.nivel = NivelRiesgo.BLOQUEO_DURO
        elif score_final >= 55.0:
            res.nivel = NivelRiesgo.ALTO
        elif score_final >= 25.0:
            res.nivel = NivelRiesgo.PRECAUCION
        elif score_final > 0.0:
            res.nivel = NivelRiesgo.BAJO
        else:
            res.nivel = NivelRiesgo.SEGURO

        return res


_ESCUDO_SINGLETON = EscudoSeguridad()


def analizar_seguridad(
    doc: DocumentoNormalizado,
    ctx: ContextoFiltro | None = None,
    econ: PerfilEconomico | None = None,
    intent: AnalisisIntencion | None = None,
) -> AnalisisRiesgo:
    return _ESCUDO_SINGLETON.analizar(doc, ctx=ctx, econ=econ, intent=intent)