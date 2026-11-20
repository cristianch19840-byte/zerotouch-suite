from __future__ import annotations

import math
import re
from dataclasses import dataclass

from modulo_a_radar_whop.motor_filtrado.modelos import (
    AnalisisIntencion,
    CategoriaSenal,
    ContextoFiltro,
    DocumentoNormalizado,
    ModalidadTrabajo,
    PerfilEconomico,
    ResultadoTaxonomia,
    SenalDetectada,
    TipoIntencion,
)


def _rx(expr: str) -> re.Pattern[str]:
    return re.compile(expr, re.IGNORECASE)


# ==================== 1. TASAS DE CAMBIO REFERENCIALES A USD (14 MONEDAS) ====================
TASAS_A_USD: dict[str, float] = {
    "USD": 1.00,
    "USDT": 1.00,
    "USDC": 1.00,
    "EUR": 1.08,
    "GBP": 1.27,
    "CHF": 1.13,
    "CAD": 0.73,
    "AUD": 0.66,
    "SGD": 0.74,
    "PLN": 0.25,
    "BRL": 0.19,
    "MXN": 0.055,
    "INR": 0.012,
    "JPY": 0.0066,
    "COP": 0.00024,
}

ALIAS_MONEDA: dict[str, str] = {
    "$": "USD",
    "us$": "USD",
    "usd": "USD",
    "usdt": "USDT",
    "usdc": "USDC",
    "bucks": "USD",
    "dollars": "USD",
    "dollar": "USD",
    "dolares": "USD",
    "dolar": "USD",
    "€": "EUR",
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "£": "GBP",
    "gbp": "GBP",
    "pounds": "GBP",
    "chf": "CHF",
    "ca$": "CAD",
    "c$": "CAD",
    "cad": "CAD",
    "a$": "AUD",
    "au$": "AUD",
    "aud": "AUD",
    "s$": "SGD",
    "sgd": "SGD",
    "pln": "PLN",
    "zl": "PLN",
    "r$": "BRL",
    "brl": "BRL",
    "reais": "BRL",
    "mx$": "MXN",
    "mxn": "MXN",
    "₹": "INR",
    "inr": "INR",
    "rs": "INR",
    "¥": "JPY",
    "jpy": "JPY",
    "cop": "COP",
    "pesos colombianos": "COP",
}

# ==================== 2. REGEX DE EXTRACCION MONETARIA MULTI-MONEDA ====================
_NUM = r"(?:\d{1,3}(?:[,\.]\d{3})+|\d+(?:\.\d+)?)"
_SUF_K = r"(?:k)?"
_PREF_MON = r"(?:US\$|CA\$|AU\$|MX\$|A\$|C\$|S\$|R\$|\$|€|£|₹|¥|(?:USDT|USDC|USD|EUR|GBP|CAD|AUD|CHF|MXN|COP|BRL|INR|PLN|JPY|SGD)\s+)"
_SUF_MON = r"(?:USDT|USDC|USD|EUR|GBP|CAD|AUD|CHF|MXN|COP|BRL|INR|PLN|JPY|SGD|bucks|dollars?|dolares?|euros?|€|£|\$)"

REGEX_RANGO_PREFIJO = _rx(
    rf"(?P<mon>{_PREF_MON})\s*(?P<n1>{_NUM})(?P<k1>{_SUF_K})\s*(?:-|–|—|to|a)\s*(?P<mon2>{_PREF_MON})?\s*(?P<n2>{_NUM})(?P<k2>{_SUF_K})(?![A-Za-z0-9])"
)
REGEX_RANGO_SUFIJO = _rx(
    rf"(?<![A-Za-z0-9\$€£₹¥])(?P<n1>{_NUM})(?P<k1>{_SUF_K})\s*(?:-|–|—|to|a)\s*(?P<n2>{_NUM})(?P<k2>{_SUF_K})\s*(?P<mon>{_SUF_MON})(?![A-Za-z0-9])"
)
REGEX_UNICO_PREFIJO = _rx(
    rf"(?P<mon>{_PREF_MON})\s*(?P<n1>{_NUM})(?P<k1>{_SUF_K})(?![A-Za-z0-9])"
)
REGEX_UNICO_SUFIJO = _rx(
    rf"(?<![A-Za-z0-9\$€£₹¥])(?P<n1>{_NUM})(?P<k1>{_SUF_K})\s*(?P<mon>{_SUF_MON})(?![A-Za-z0-9])"
)

# Ventanas contextuales para clasificar unidad temporal
REGEX_PERIODO_HORA = _rx(r"^\s*(?:\/|\s*per\s*|\s*an?\s*|\s*por\s*|\s+)(?:hr|hrs|hour|hours|h|hora|horas)\b|\b(?:hourly\s+rate|per\s+hour|an\s+hour)\b")
REGEX_PERIODO_DIA = _rx(r"^\s*(?:\/|\s*per\s*|\s*a\s*|\s*por\s*)(?:day|days|d|dia|dias)\b|\bdaily\s+rate\b")
REGEX_PERIODO_SEMANA = _rx(r"^\s*(?:\/|\s*per\s*|\s*a\s*|\s*por\s*)(?:wk|week|weeks|semana|semanas)\b|\bweekly\b")
REGEX_PERIODO_MES = _rx(r"^\s*(?:\/|\s*per\s*|\s*a\s*|\s*por\s*)(?:mo|mos|month|months|mes|meses)\b|\b(?:monthly\s+(?:retainer|budget|pay|rate|salary)|per\s+month)\b")
REGEX_PERIODO_ANO = _rx(r"^\s*(?:\/|\s*per\s*|\s*a\s*|\s*por\s*)(?:yr|yrs|year|years|annum|ano|anos)\b|\b(?:annual(?:ly)?|per\s+year|base\s+salary|ote|p\.a\.)\b")

# Palabras que indican que un monto NO es el presupuesto del freelancer (ruido corporativo/metricas)
REGEX_RUIDO_FINANCIERO_POST = _rx(
    r"^\s*(?:million|billion|mn|bn|m\b|b\b)?\s*(?:in\s+)?(?:revenue|arr|mrr|funding|raised|valuation|market\s*cap|"
    r"sales|gmv|aum|series\s+[a-e]|seed\s+round|profit|turnover|worth|ad\s*spend|portfolio\s+value|"
    r"followers|subscribers|users|customers|leads|rows|records|items|products|listings|emails|pages|skus)\b"
)
REGEX_RUIDO_FINANCIERO_PRE = _rx(
    r"\b(?:raised|funding\s+of|valued\s+at|revenue\s+of|generating|doing|making|over|reached|worth|spent)\s*$"
)
REGEX_CONTEXTO_PRESUPUESTO_PRE = _rx(
    r"\b(?:budget|pay|paying|paid|rate|price|pricing|bounty|reward|offer|offering|compensation|salary|fixed|flat|fee|cost|presupuesto|pago|tarifa)\s*(?:is|of|around|up\s+to|starts?\s+at|:|-|de)?\s*$"
)
REGEX_CONTEXTO_PRESUPUESTO_POST = _rx(
    r"^\s*(?:fixed|flat|budget|bounty|reward|total|max|min|negotiable|obo|ono|usd|usdt|per\s+hour|\/hr|\/mo|\/yr|por\s+hora)\b"
)

# Senales cualitativas economicas
REGEX_LOWBALL_TEXTO = _rx(
    r"\b(?:as\s+cheap\s+as\s+possible|cheapest\s+(?:bid|price|offer|dev\w*)\s+wins|lowest\s+(?:bid|price)\s+wins|"
    r"super\s+cheap|very\s+cheap|dirt\s+cheap|tiny\s+budget|very\s+tight\s+budget|limited\s+budget\s+of\s+\$?[1-9]\b|"
    r"only\s+have\s+\$?(?:[1-9]|1[0-4])\b|max\s+\$?(?:[1-9]|1[0-4])\b|lo\s+mas\s+barato\s+posible|muy\s+poco\s+presupuesto)\b"
)
REGEX_FLEXIBLE_GENEROSO = _rx(
    r"\b(?:budget\s+(?:is\s+)?(?:flexible|open|negotiable)|open\s+budget|willing\s+to\s+pay\s+(?:well|fairly|top|generously|good\s+rates?)|"
    r"fair\s+(?:rate|compensation|pay)|competitive\s+(?:rate|pay|compensation)|pay\s+for\s+quality|"
    r"send\s+(?:me\s+)?your\s+(?:rate|quote|estimate)|name\s+your\s+price|funded\s+startup|well[\s-]*funded|"
    r"presupuesto\s+flexible|buen\s+pago)\b"
)


# ==================== 3. ESTIMADOR DETERMINISTICO DE ESFUERZO (HORAS) ====================
# Rango base (min_h, max_h) por familia tecnica principal
HORAS_BASE_FAMILIA: dict[str, tuple[float, float]] = {
    "scraping":         (3.0, 7.0),
    "bots_messaging":   (4.0, 9.0),
    "python_core":      (2.5, 6.0),
    "automation":       (2.5, 6.5),
    "data_etl":         (2.0, 5.5),
    "backend_api":      (6.0, 14.0),
    "databases":        (4.0, 9.0),
    "ai_llm":           (6.0, 15.0),
    "ecommerce":        (5.0, 12.0),
    "browser_ext":      (5.0, 11.0),
    "frontend_web":     (8.0, 18.0),
    "devops":           (3.0, 7.0),
    "engineering_gen":  (4.0, 10.0),
}


@dataclass(frozen=True, slots=True)
class ModificadorEsfuerzo:
    codigo: str
    descripcion: str
    delta_min: float
    delta_max: float
    factor: float
    patron: re.Pattern[str]


MODIFICADORES_ESFUERZO: tuple[ModificadorEsfuerzo, ...] = (
    # Reductores (tareas acotadas y rapidas)
    ModificadorEsfuerzo(
        "SCOPE_MINI_FIX", "Tarea puntual / arreglo rapido", -1.5, -2.5, 0.55,
        _rx(r"\b(?:quick\s+(?:fix|tweak|script|help|task)|small\s+(?:fix|bug|script|tweak|change)|"
            r"minor\s+(?:bug|fix|change)|one\s+simple\s+script|single\s+page|tiny\s+script|bug\s+fix\s+only|arreglo\s+rapido)\b"),
    ),
    # Multiplicadores tecnicos reales
    ModificadorEsfuerzo(
        "SCOPE_ANTIBOT", "Bypass anti-bot / Cloudflare / Captcha / Proxies", 3.0, 6.0, 1.20,
        _rx(r"\b(?:cloudflare|datadome|akamai|perimeterx|recaptcha|hcaptcha|captcha\s+solv\w*|rotating\s+prox\w*|residential\s+prox\w*|anti[\s-]*bot)\b"),
    ),
    ModificadorEsfuerzo(
        "SCOPE_MULTI_SITIO", "Multiples sitios o fuentes simultaneas", 2.5, 6.0, 1.15,
        _rx(r"\b(?:multiple\s+(?:websites|sites|stores|sources|platforms)|(?:\d{2,}|5|6|7|8|9|10)\+?\s*(?:websites|sites|stores|domains|suppliers))\b"),
    ),
    ModificadorEsfuerzo(
        "SCOPE_AUTH_PAGOS", "Autenticacion de usuarios y pasarela de pagos", 4.0, 9.0, 1.18,
        _rx(r"\b(?:user\s+auth\w*|login\s+system|oauth2?|stripe\s+(?:checkout|subscriptions?|billing)|payment\s+gateway|role[\s-]*based\s+access)\b"),
    ),
    ModificadorEsfuerzo(
        "SCOPE_DASHBOARD_ADMIN", "Panel de administracion / Dashboard web completo", 6.0, 14.0, 1.25,
        _rx(r"\b(?:admin\s+panel|admin\s+dashboard|full\s+dashboard|web\s+portal|crm\s+system|analytics\s+dashboard)\b"),
    ),
    ModificadorEsfuerzo(
        "SCOPE_DEPLOY_REALTIME", "Despliegue en servidor / tiempo real / alta concurrencia", 2.0, 5.0, 1.12,
        _rx(r"\b(?:real[\s-]*time|websockets?|24\/7|high\s+concurrency|dockerize|deploy\s+to\s+(?:aws|vps|gcp|azure|cloud)|scale\s+to\s+millions)\b"),
    ),
    ModificadorEsfuerzo(
        "SCOPE_AI_RAG", "Agente IA complejo / RAG / memoria vectorial", 4.0, 10.0, 1.20,
        _rx(r"\b(?:rag\s+pipeline|vector\s+database|multi[\s-]*agent|fine[\s-]*tun\w*|voice\s+ai\s+agent|autonomous\s+agent)\b"),
    ),
    # Multiplicadores MEGALODON (alcance gigante que delata lowballers)
    ModificadorEsfuerzo(
        "SCOPE_CLON_APP", "Clon de plataforma masiva o marketplace completo", 35.0, 80.0, 1.80,
        _rx(r"\b(?:clone\s+of\s+(?:uber|airbnb|amazon|instagram|tiktok|facebook|twitter|spotify|netflix|upwork|fiverr|doordash)|"
            r"(?:uber|airbnb|amazon|instagram|tiktok|upwork)\s+clone|"
            r"full[\s-]*featured\s+(?:marketplace|social\s+network|saas\s+platform|casino\s+platform|erp|crypto\s+exchange)|"
            r"build\s+(?:a\s+)?complete\s+(?:saas|platform|marketplace)\s+from\s+scratch)\b"),
    ),
    ModificadorEsfuerzo(
        "SCOPE_MOBILE_CROSS", "App movil nativa iOS y Android completa", 30.0, 70.0, 1.70,
        _rx(r"\b(?:ios\s+and\s+android\s+app|mobile\s+app\s+for\s+(?:ios|android)|app\s+store\s+and\s+play\s+store|flutter\s+app\s+with\s+backend)\b"),
    ),
)


@dataclass(slots=True)
class MencionMonetaria:
    min_usd: float
    max_usd: float
    moneda: str
    tipo_tarifa: str  # fijo | hora | diario | semanal | mensual | anual
    confianza: float
    evidencia: str
    zona: str


def _normalizar_moneda(token_mon: str) -> str:
    limpio = (token_mon or "").strip().lower()
    if limpio in ALIAS_MONEDA:
        return ALIAS_MONEDA[limpio]
    limpio_sin_esp = limpio.replace(" ", "")
    return ALIAS_MONEDA.get(limpio_sin_esp, "USD")


def _parsear_numero_moneda(num_str: str, suf_k: str, moneda: str) -> float:
    s = (num_str or "").strip()
    if not s:
        return 0.0
    # Maneja separadores de miles estilo 400.000 COP / 1.200 EUR vs decimales 1.5k
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", s) and not suf_k:
        s = s.replace(".", "")
    elif "," in s and "." not in s:
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+", s):
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    else:
        s = s.replace(",", "")

    try:
        val = float(s)
    except ValueError:
        return 0.0

    if suf_k and suf_k.lower() == "k":
        val *= 1000.0
    tasa = TASAS_A_USD.get(moneda, 1.0)
    return round(val * tasa, 2)


def _detectar_tipo_tarifa(pre_ctx: str, post_ctx: str, min_usd: float, max_usd: float, es_bolsa_remota: bool) -> str:
    if REGEX_PERIODO_HORA.search(post_ctx) or REGEX_PERIODO_HORA.search(pre_ctx):
        return "hora"
    if REGEX_PERIODO_DIA.search(post_ctx) or REGEX_PERIODO_DIA.search(pre_ctx):
        return "diario"
    if REGEX_PERIODO_SEMANA.search(post_ctx) or REGEX_PERIODO_SEMANA.search(pre_ctx):
        return "semanal"
    if REGEX_PERIODO_MES.search(post_ctx) or REGEX_PERIODO_MES.search(pre_ctx):
        return "mensual"
    if REGEX_PERIODO_ANO.search(post_ctx) or REGEX_PERIODO_ANO.search(pre_ctx):
        return "anual"

    # Heuristica inteligente por magnitud cuando no hay sufijo explicito
    med = (min_usd + max_usd) / 2.0
    if es_bolsa_remota and med >= 28000:
        return "anual"
    if med >= 50000:
        return "anual"
    return "fijo"


class AnalizadorEconomico:
    """
    Capa 4 de AEGIS-X: Extrae y normaliza presupuestos en 14 monedas a USD,
    filtra ruido financiero corporativo, estima horas reales de desarrollo,
    calcula tarifa efectiva USD/hr, caza lowballers y detecta ballenas.
    """

    @staticmethod
    def _extraer_menciones_zona(texto: str, zona: str, es_bolsa_remota: bool) -> list[MencionMonetaria]:
        if not texto:
            return []
        menciones: list[MencionMonetaria] = []
        spans_usados: list[tuple[int, int]] = []

        def _solapa(a: int, b: int) -> bool:
            return any(not (b <= s0 or a >= s1) for s0, s1 in spans_usados)

        patrones = (
            ("rango_pref", REGEX_RANGO_PREFIJO, True),
            ("rango_suf", REGEX_RANGO_SUFIJO, True),
            ("unico_pref", REGEX_UNICO_PREFIJO, False),
            ("unico_suf", REGEX_UNICO_SUFIJO, False),
        )

        for _, rx, es_rango in patrones:
            for m in rx.finditer(texto):
                s0, s1 = m.start(), m.end()
                if _solapa(s0, s1):
                    continue

                pre = texto[max(0, s0 - 38):s0]
                post = texto[s1:min(len(texto), s1 + 42)]

                # Descarta ruido corporativo/metricas ("$10M revenue", "500 products")
                if REGEX_RUIDO_FINANCIERO_POST.search(post) or REGEX_RUIDO_FINANCIERO_PRE.search(pre):
                    continue

                mon = _normalizar_moneda(m.group("mon"))
                v1 = _parsear_numero_moneda(m.group("n1"), m.group("k1") or "", mon)
                if es_rango:
                    mon2 = _normalizar_moneda(m.group("mon2")) if ("mon2" in m.groupdict() and m.group("mon2")) else mon
                    v2 = _parsear_numero_moneda(m.group("n2"), m.group("k2") or "", mon2)
                    lo, hi = min(v1, v2), max(v1, v2)
                else:
                    lo = hi = v1

                # Filtra valores absurdos o fuera de rango freelance/remoto
                if hi < 3.0 or lo > 450000.0:
                    continue
                # Evitar falsos positivos tipo "$0" o anos sueltos sin contexto fuerte
                if not es_rango and lo in (2023.0, 2024.0, 2025.0, 2026.0, 2027.0) and mon == "USD" and "$" not in m.group(0):
                    continue

                tipo = _detectar_tipo_tarifa(pre, post, lo, hi, es_bolsa_remota)

                # Puntaje de confianza de que esta mencion es EL presupuesto real de la oferta
                conf = 0.55
                if zona == "titulo":
                    conf += 0.25
                if es_rango:
                    conf += 0.10
                if REGEX_CONTEXTO_PRESUPUESTO_PRE.search(pre) or REGEX_CONTEXTO_PRESUPUESTO_POST.search(post):
                    conf += 0.22
                if tipo != "fijo":
                    conf += 0.08
                if "$" in m.group(0) or "€" in m.group(0) or "£" in m.group(0):
                    conf += 0.06

                spans_usados.append((s0, s1))
                menciones.append(MencionMonetaria(
                    min_usd=lo,
                    max_usd=hi,
                    moneda=mon,
                    tipo_tarifa=tipo,
                    confianza=min(1.0, conf),
                    evidencia=m.group(0).strip(),
                    zona=zona,
                ))

        return menciones

    @staticmethod
    def _estimar_horas(
        doc: DocumentoNormalizado,
        tax: ResultadoTaxonomia | None,
        intent: AnalisisIntencion | None,
    ) -> tuple[float, float, list[SenalDetectada]]:
        senales: list[SenalDetectada] = []

        # 1. Base por familia principal + 30% por familias secundarias (integrar multiples stacks cuesta mas)
        if tax and tax.familias_detectadas:
            ordenadas = sorted(tax.familias_detectadas.items(), key=lambda kv: kv[1], reverse=True)
            fam_top = ordenadas[0][0]
            h_min, h_max = HORAS_BASE_FAMILIA.get(fam_top, (4.0, 9.0))
            for fam_sec, _ in ordenadas[1:4]:
                s_min, s_max = HORAS_BASE_FAMILIA.get(fam_sec, (2.0, 4.0))
                h_min += s_min * 0.28
                h_max += s_max * 0.30
        else:
            h_min, h_max = (3.5, 8.0)

        # 2. Aplicar modificadores detectados en el texto
        texto = doc.texto_unificado
        factor_acum = 1.0
        for mod in MODIFICADORES_ESFUERZO:
            m = mod.patron.search(texto)
            if m:
                h_min += mod.delta_min
                h_max += mod.delta_max
                factor_acum *= mod.factor
                senales.append(SenalDetectada(
                    codigo=mod.codigo,
                    categoria=CategoriaSenal.ECONOMIA,
                    descripcion=mod.descripcion,
                    peso=(-1.5 if mod.delta_max >= 30 else 0.5),
                    evidencia=m.group(0),
                    zona="cuerpo",
                ))

        # 3. Ajuste por extension y densidad de requisitos (vinetas)
        if doc.metricas.tiene_vinetas and doc.metricas.cantidad_lineas >= 8:
            h_min += 1.5
            h_max += 3.5
        if doc.metricas.palabras_totales >= 220:
            factor_acum *= 1.15

        # Si es una tarea urgente pequena sin megalodones, acotar techo
        if intent and intent.es_urgente and h_max < 20.0:
            factor_acum *= 0.90

        h_min = max(1.0, round(h_min * factor_acum, 1))
        h_max = max(h_min + 1.0, round(h_max * factor_acum, 1))
        return h_min, h_max, senales

    @staticmethod
    def _formatear_etiqueta(lo: float, hi: float, tipo: str, moneda: str) -> str:
        suf = {
            "hora": "/hr",
            "mensual": "/mo",
            "anual": "/yr",
            "diario": "/day",
            "semanal": "/wk",
        }.get(tipo, "")
        mon_tag = f" ({moneda})" if moneda not in ("USD", "USDT", "USDC") else ""
        if hi <= 0:
            return "Por definir"
        if abs(hi - lo) < 1.0:
            return f"${int(round(hi)):,}{suf} USD{mon_tag}"
        return f"${int(round(lo)):,}-${int(round(hi)):,}{suf} USD{mon_tag}"

    def analizar(
        self,
        doc: DocumentoNormalizado,
        tax: ResultadoTaxonomia | None = None,
        intent: AnalisisIntencion | None = None,
        ctx: ContextoFiltro | None = None,
    ) -> PerfilEconomico:
        ctx = ctx or ContextoFiltro()
        res = PerfilEconomico()

        plat_low = (ctx.plataforma or ctx.fuente or "").lower()
        es_bolsa_remota = any(p in plat_low for p in ("remoteok", "wwr", "weworkremotely", "remotive", "jobicy", "himalayas", "workingnomads", "arbeitnow"))

        # 1. Estimar esfuerzo deterministico en horas
        h_min, h_max, sen_esf = self._estimar_horas(doc, tax, intent)
        res.horas_estimadas_min = h_min
        res.horas_estimadas_max = h_max
        res.senales.extend(sen_esf)
        h_med = (h_min + h_max) / 2.0

        # 2. Extraer menciones monetarias en titulo y cuerpo
        menciones = self._extraer_menciones_zona(doc.titulo_limpio, "titulo", es_bolsa_remota)
        menciones.extend(self._extraer_menciones_zona(doc.cuerpo_limpio, "cuerpo", es_bolsa_remota))

        mejor: MencionMonetaria | None = None
        if menciones:
            # Preferimos mayor confianza; en empate, titulo y mayor claridad
            menciones.sort(key=lambda x: (x.confianza, x.zona == "titulo", x.max_usd > 0), reverse=True)
            mejor = menciones[0]
        elif ctx.monto_api_usd > 0:
            tipo_api = "anual" if (es_bolsa_remota and ctx.monto_api_usd >= 25000) else (
                "hora" if (intent and intent.modalidad == ModalidadTrabajo.POR_HORA and ctx.monto_api_usd <= 250) else "fijo"
            )
            mejor = MencionMonetaria(
                min_usd=ctx.monto_api_usd,
                max_usd=ctx.monto_api_usd,
                moneda="USD",
                tipo_tarifa=tipo_api,
                confianza=0.90,
                evidencia=f"API:${ctx.monto_api_usd:.0f}",
                zona="metadata",
            )

        # 3. Normalizar unidades temporales a PerfilEconomico y calcular tarifa efectiva USD/hr
        tarifa_obj = max(8.0, float(ctx.tarifa_minima_usd_hr or 15.0))
        pres_min_cfg = max(5.0, float(ctx.presupuesto_minimo_usd or 20.0))

        if mejor is not None:
            res.moneda_detectada = mejor.moneda
            lo, hi = mejor.min_usd, mejor.max_usd
            tipo_norm = mejor.tipo_tarifa

            # Normalizar diario/semanal a equivalente entendible sin perder precision
            if tipo_norm == "diario":
                tarifa_eff = ((lo + hi) / 2.0) / 8.0
                tipo_guardado = "fijo"
            elif tipo_norm == "semanal":
                tarifa_eff = ((lo + hi) / 2.0) / 25.0
                tipo_guardado = "mensual"
                lo, hi = round(lo * 4.0, 2), round(hi * 4.0, 2)
            elif tipo_norm == "hora":
                tarifa_eff = (lo + hi) / 2.0
                tipo_guardado = "hora"
            elif tipo_norm == "mensual":
                horas_mes = 160.0 if (intent and intent.intencion == TipoIntencion.EMPLEO_FULLTIME) else 45.0
                tarifa_eff = ((lo + hi) / 2.0) / horas_mes
                tipo_guardado = "mensual"
            elif tipo_norm == "anual":
                tarifa_eff = ((lo + hi) / 2.0) / 2000.0
                tipo_guardado = "anual"
            else:
                tarifa_eff = ((lo + hi) / 2.0) / max(1.0, h_med)
                tipo_guardado = "fijo"

            res.presupuesto_min_usd = round(lo, 2)
            res.presupuesto_max_usd = round(hi, 2)
            res.presupuesto_medio_usd = round((lo + hi) / 2.0, 2)
            res.tipo_tarifa = tipo_guardado
            res.tarifa_efectiva_usd_hr = round(tarifa_eff, 2)
            res.etiqueta_presupuesto = self._formatear_etiqueta(lo, hi, tipo_guardado, mejor.moneda)

            res.senales.append(SenalDetectada(
                codigo=f"ECON_PRESUPUESTO_{tipo_guardado.upper()}",
                categoria=CategoriaSenal.ECONOMIA,
                descripcion=f"Presupuesto detectado: {res.etiqueta_presupuesto} (~${res.tarifa_efectiva_usd_hr:.1f}/hr est.)",
                peso=2.0,
                evidencia=mejor.evidencia,
                zona=mejor.zona,
            ))

        # 4. Deteccion de senales cualitativas (tacaños vs clientes generosos/flexibles)
        texto_full = doc.texto_unificado
        m_low_txt = REGEX_LOWBALL_TEXTO.search(texto_full)
        m_flex_txt = REGEX_FLEXIBLE_GENEROSO.search(texto_full)

        if m_low_txt:
            res.senales.append(SenalDetectada(
                codigo="ECON_SENAL_TACANO",
                categoria=CategoriaSenal.ECONOMIA,
                descripcion="Lenguaje de presupuesto extremadamente bajo o subasta a la baja",
                peso=-5.5,
                evidencia=m_low_txt.group(0),
                zona="cuerpo",
            ))

        if m_flex_txt:
            res.senales.append(SenalDetectada(
                codigo="ECON_PRESUPUESTO_FLEXIBLE",
                categoria=CategoriaSenal.ECONOMIA,
                descripcion="Cliente dispuesto a negociar o pagar tarifa justa por calidad",
                peso=3.0,
                evidencia=m_flex_txt.group(0),
                zona="cuerpo",
            ))

        # 5. Evaluacion de Lowball vs High-Ticket y Score Economico (0..100)
        if mejor is None:
            # Sin monto publicado: neutro-positivo (no penalizar ofertas "send your quote")
            score = 52.0
            if m_flex_txt:
                score += 14.0
            if intent and intent.es_recurrente:
                score += 10.0
            if intent and intent.es_urgente:
                score += 6.0
            if m_low_txt:
                score -= 28.0
                res.es_lowball = True
            res.score_economico_0_100 = round(max(0.0, min(100.0, score)), 1)
            return res

        med = res.presupuesto_medio_usd
        teff = res.tarifa_efectiva_usd_hr
        tipo = res.tipo_tarifa

        # Reglas estrictas de LOWBALL
        motivo_lowball = ""
        if tipo == "fijo":
            if res.presupuesto_max_usd < pres_min_cfg:
                motivo_lowball = f"Presupuesto fijo (${res.presupuesto_max_usd:.0f}) por debajo del minimo (${pres_min_cfg:.0f})"
            elif h_min >= 10.0 and teff < (tarifa_obj * 0.42):
                motivo_lowball = f"Alcance gigante ({h_min:.0f}-{h_max:.0f}h) para solo ${med:.0f} (~${teff:.1f}/hr)"
            elif teff < 5.0 and res.presupuesto_max_usd < 80.0:
                motivo_lowball = f"Tarifa efectiva demasiado baja (~${teff:.1f}/hr)"
        elif tipo == "hora":
            if res.presupuesto_max_usd < max(7.0, tarifa_obj * 0.55):
                motivo_lowball = f"Tarifa horaria (${res.presupuesto_max_usd:.1f}/hr) muy por debajo de tu piso"
        elif tipo == "mensual":
            if res.presupuesto_max_usd < 250.0:
                motivo_lowball = f"Mensualidad demasiado baja (${res.presupuesto_max_usd:.0f}/mo)"
        elif tipo == "anual":
            if res.presupuesto_max_usd < 15000.0:
                motivo_lowball = f"Salario anual demasiado bajo (${res.presupuesto_max_usd:,.0f}/yr)"

        if m_low_txt and (tipo == "fijo" and res.presupuesto_max_usd < 60.0):
            motivo_lowball = motivo_lowball or "Presupuesto bajo + lenguaje de subasta barata"

        if motivo_lowball:
            res.es_lowball = True
            res.senales.append(SenalDetectada(
                codigo="ECON_LOWBALL_DETECTADO",
                categoria=CategoriaSenal.ECONOMIA,
                descripcion=motivo_lowball,
                peso=-8.0,
                evidencia=res.etiqueta_presupuesto,
                zona="combinado",
            ))

        # Reglas de BALLENA / HIGH-TICKET
        if not res.es_lowball:
            if (
                (tipo == "fijo" and res.presupuesto_max_usd >= 250.0 and teff >= tarifa_obj * 0.70)
                or (tipo == "hora" and med >= 35.0)
                or (tipo == "mensual" and med >= 600.0)
                or (tipo == "anual" and med >= 55000.0)
            ):
                res.es_high_ticket = True
                res.senales.append(SenalDetectada(
                    codigo="ECON_HIGH_TICKET_BALLENA",
                    categoria=CategoriaSenal.ECONOMIA,
                    descripcion=f"Oportunidad High-Ticket / Ballena ({res.etiqueta_presupuesto})",
                    peso=6.0,
                    evidencia=res.etiqueta_presupuesto,
                    zona="combinado",
                ))

        # Calculo de Score Economico 0..100
        ratio_tarifa = teff / max(1.0, tarifa_obj)
        # Curva base segun relacion tarifa_efectiva / tarifa_objetivo (1.0x -> ~66 pts, 2.0x -> ~85 pts)
        score_tarifa = 20.0 + 72.0 * (1.0 - math.exp(-0.95 * max(0.0, ratio_tarifa)))

        # Bonus por volumen real de caja (un proyecto de $400 pesa mas que uno de $30 a misma tarifa/hr)
        if tipo == "fijo":
            bonus_caja = min(16.0, max(0.0, math.log10(max(10.0, med)) * 6.5 - 6.0))
        elif tipo == "mensual":
            bonus_caja = min(18.0, max(0.0, math.log10(max(100.0, med)) * 6.0 - 4.0))
        elif tipo == "anual":
            bonus_caja = 12.0 if med >= 50000 else 6.0
        else:
            bonus_caja = min(14.0, max(0.0, (med - 15.0) * 0.35))

        score = score_tarifa + bonus_caja
        if res.es_high_ticket:
            score += 8.0
        if m_flex_txt:
            score += 5.0
        if intent and intent.es_recurrente:
            score += 6.0
        if m_low_txt:
            score -= 18.0
        if res.es_lowball:
            score = min(score - 22.0, 26.0)

        res.score_economico_0_100 = round(max(0.0, min(100.0, score)), 1)
        return res


_ECONOMIA_SINGLETON = AnalizadorEconomico()


def analizar_economia(
    doc: DocumentoNormalizado,
    tax: ResultadoTaxonomia | None = None,
    intent: AnalisisIntencion | None = None,
    ctx: ContextoFiltro | None = None,
) -> PerfilEconomico:
    return _ECONOMIA_SINGLETON.analizar(doc, tax=tax, intent=intent, ctx=ctx)