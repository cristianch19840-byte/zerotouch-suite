from __future__ import annotations

import html
import math
import re
import unicodedata
from collections import Counter
from urllib.parse import urlparse
from bs4 import BeautifulSoup

from modulo_a_radar_whop.motor_filtrado.modelos import (
    DocumentoNormalizado,
    EntidadesExtraidas,
    IdiomaDetectado,
    MetricasTexto,
)

# Mapa forense de homoglifos (cirilico, griego, tipografia matematica y simbolos usados por spammers)
MAPA_HOMOGLIFOS: dict[str, str] = {
    # Cirilico minusculas y mayusculas
    "\u0430": "a", "\u0410": "A",
    "\u0435": "e", "\u0415": "E",
    "\u043e": "o", "\u041e": "O",
    "\u0440": "p", "\u0420": "P",
    "\u0441": "c", "\u0421": "C",
    "\u0443": "y", "\u0423": "Y",
    "\u0445": "x", "\u0425": "X",
    "\u0456": "i", "\u0406": "I",
    "\u0458": "j", "\u0408": "J",
    "\u0455": "s", "\u0405": "S",
    "\u0412": "B", "\u041d": "H",
    "\u041a": "K", "\u041c": "M",
    "\u0422": "T",
    # Griego comun
    "\u03b1": "a", "\u0391": "A",
    "\u03b5": "e", "\u0395": "E",
    "\u03bf": "o", "\u039f": "O",
    "\u03c1": "p", "\u03a1": "P",
    "\u03b9": "i", "\u0399": "I",
    "\u03ba": "k", "\u039a": "K",
    "\u03bd": "v", "\u03c4": "t",
    # Comillas, guiones y espacios raros
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-", "\u2212": "-",
    "\u00a0": " ", "\u2000": " ", "\u2001": " ", "\u2002": " ",
    "\u2003": " ", "\u2009": " ", "\u202f": " ", "\u3000": " ",
}

REGEX_INVISIBLES = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff\u00ad]")
REGEX_URL = re.compile(r"https?://[^\s<>\"'\)\]]+|www\.[a-zA-Z0-9\-]+\.[a-zA-Z]{2,}[^\s<>\"'\)\]]*", re.IGNORECASE)
REGEX_EMAIL = re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b")
REGEX_GITHUB_REPO = re.compile(r"github\.com/([a-zA-Z0-9_.\-]+/[a-zA-Z0-9_.\-]+)", re.IGNORECASE)
REGEX_HANDLE = re.compile(r"(?:^|[\s(])(@[a-zA-Z0-9_]{3,30}|u/[a-zA-Z0-9_\-]{3,25})\b")
REGEX_CONTACTO_EXT = re.compile(
    r"(t\.me/[a-zA-Z0-9_]+|wa\.me/\d+|whatsapp\.com/[^\s]+|discord\.gg/[a-zA-Z0-9]+|"
    r"telegram\s*[:@]\s*@?[a-zA-Z0-9_]{4,}|whatsapp\s*[:+]\s*\+?\d[\d\s\-]{7,}|"
    r"dm\s+(?:me\s+)?on\s+(?:telegram|whatsapp|instagram|snapchat))",
    re.IGNORECASE,
)
REGEX_VINETAS = re.compile(r"(?m)^\s*(?:[-*•▪▸]|\d+[.)])\s+")
REGEX_BLOQUE_CODIGO = re.compile(r"```|def\s+\w+\(|import\s+\w+|SELECT\s+\*|\{\s*\"[a-zA-Z0-9_]+\"\s*:")

# Detecta ofuscacion deliberada estilo "w.h.a.t.s.a.p.p" o "k y c" o "c-r-y-p-t-o"
REGEX_PALABRA_OFUSCADA = re.compile(r"\b(?:[a-zA-Z][.\-_*]){3,}[a-zA-Z]\b")
REGEX_ESPACIADO_SOSPECHOSO = re.compile(r"\b(?:[a-zA-Z]\s){4,}[a-zA-Z]\b")

ACORTADORES_URL = {
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "buff.ly",
    "rb.gy", "cutt.ly", "shorturl.at", "tiny.cc", "rebrand.ly", "clk.sh",
}

PLATAFORMAS_CONOCIDAS = {
    "shopify", "wordpress", "woocommerce", "stripe", "paypal", "binance",
    "telegram", "discord", "slack", "notion", "airtable", "hubspot",
    "salesforce", "zapier", "make.com", "n8n", "upwork", "fiverr",
    "amazon", "ebay", "etsy", "tiktok", "instagram", "youtube", "twitter",
    "linkedin", "google sheets", "google drive", "aws", "gcp", "azure",
    "vercel", "supabase", "firebase", "github", "gitlab",
}

STOPWORDS_COMUNES = {
    "the", "and", "for", "with", "that", "this", "from", "have", "will", "are",
    "you", "your", "our", "can", "all", "not", "but", "what", "when", "who",
    "how", "out", "about", "into", "more", "some", "any", "been", "was", "were",
    "they", "their", "them", "just", "also", "need", "want", "looking", "help",
    "para", "con", "que", "los", "las", "una", "uno", "por", "como", "pero",
    "mas", "del", "este", "esta", "eso", "aqui", "muy", "sin", "sobre", "entre",
}

MARCADORES_IDIOMA: dict[IdiomaDetectado, set[str]] = {
    IdiomaDetectado.EN: {
        "the", "and", "looking", "need", "with", "from", "that", "this", "will",
        "would", "should", "have", "budget", "project", "developer", "script",
        "website", "please", "thanks", "using", "build", "create", "fixed",
    },
    IdiomaDetectado.ES: {
        "para", "busco", "necesito", "proyecto", "desarrollador", "presupuesto",
        "pago", "hacer", "crear", "pagina", "datos", "gracias", "hola", "con",
        "que", "una", "este", "esta", "trabajo", "urgente", "automatizar",
    },
    IdiomaDetectado.PT: {
        "preciso", "procuro", "projeto", "desenvolvedor", "orcamento", "pagamento",
        "fazer", "criar", "dados", "obrigado", "ola", "voce", "nao", "para", "com",
    },
    IdiomaDetectado.FR: {
        "bonjour", "cherche", "besoin", "projet", "developpeur", "avec", "pour",
        "dans", "nous", "vous", "merci", "faire", "donnees", "travail",
    },
    IdiomaDetectado.DE: {
        "suche", "brauche", "projekt", "entwickler", "fuer", "mit", "und", "der",
        "die", "das", "nicht", "bitte", "danke", "arbeit", "daten",
    },
}

MAPA_LEET_CONTEXTUAL = str.maketrans({"@": "a", "0": "o", "1": "i", "3": "e", "5": "s", "7": "t"})


def _quitar_acentos(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def _desofuscar_unicode(texto: str) -> tuple[str, int, int]:
    if not texto:
        return "", 0, 0
    invisibles = len(REGEX_INVISIBLES.findall(texto))
    limpio = REGEX_INVISIBLES.sub("", texto)
    # NFKC convierte letras fullwidth (ＡＢＣ) y tipografia matematica bold/italic a ASCII
    limpio = unicodedata.normalize("NFKC", limpio)

    homoglifos = 0
    chars_out: list[str] = []
    for ch in limpio:
        rep = MAPA_HOMOGLIFOS.get(ch)
        if rep is not None:
            chars_out.append(rep)
            if rep != " ":
                homoglifos += 1
        else:
            chars_out.append(ch)
    return "".join(chars_out), homoglifos, invisibles


def _desofuscar_evasiones(texto: str) -> tuple[str, bool]:
    detectado = False

    def _reemplazar_punteado(m: re.Match[str]) -> str:
        nonlocal detectado
        bruto = m.group(0)
        # No tocar dominios cortos validos ni extensiones como a.b.c si tienen sentido tecnico
        colapsado = re.sub(r"[.\-_*]", "", bruto)
        if len(colapsado) >= 4:
            detectado = True
            return colapsado
        return bruto

    def _reemplazar_espaciado(m: re.Match[str]) -> str:
        nonlocal detectado
        detectado = True
        return m.group(0).replace(" ", "")

    res = REGEX_PALABRA_OFUSCADA.sub(_reemplazar_punteado, texto)
    res = REGEX_ESPACIADO_SOSPECHOSO.sub(_reemplazar_espaciado, res)
    return res, detectado


def limpiar_html_estructurado(raw_html: str, max_len: int = 3500) -> str:
    if not raw_html:
        return ""
    desescapado = html.unescape(str(raw_html))
    if "<" in desescapado and ">" in desescapado:
        soup = BeautifulSoup(desescapado, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()
        for br in soup.find_all(["br", "p", "li", "div", "h1", "h2", "h3", "tr"]):
            br.insert_before("\n")
        texto = soup.get_text(separator=" ")
    else:
        texto = desescapado

    lineas = [re.sub(r"[ \t]+", " ", ln).strip() for ln in texto.splitlines()]
    lineas = [ln for ln in lineas if ln]
    compacto = "\n".join(lineas)
    return compacto[:max_len]


def calcular_entropia_shannon(texto: str) -> float:
    if not texto:
        return 0.0
    muestra = texto[:1200]
    n = len(muestra)
    conteo = Counter(muestra)
    entropia = 0.0
    for c in conteo.values():
        p = c / n
        entropia -= p * math.log2(p)
    return entropia


def detectar_idioma(tokens: list[str], texto_raw: str) -> tuple[IdiomaDetectado, float]:
    if not tokens:
        return IdiomaDetectado.EN, 0.2

    conteos: dict[IdiomaDetectado, int] = {}
    for idi, vocab in MARCADORES_IDIOMA.items():
        conteos[idi] = sum(1 for t in tokens if t in vocab)

    # Bonus por caracteres propios de espanol / portugues / aleman
    low = texto_raw.lower()
    if any(ch in low for ch in ("¿", "¡", "ñ")):
        conteos[IdiomaDetectado.ES] += 4
    if any(ch in low for ch in ("ã", "õ", "ç")):
        conteos[IdiomaDetectado.PT] += 3
    if any(ch in low for ch in ("ß", "ü", "ö", "ä")):
        conteos[IdiomaDetectado.DE] += 3

    ordenados = sorted(conteos.items(), key=lambda x: x[1], reverse=True)
    top_idi, top_val = ordenados[0]
    seg_idi, seg_val = ordenados[1]

    if top_val == 0:
        # Si es texto ASCII tecnico puro (ej. "Python Playwright Shopify CSV"), asumimos EN
        ascii_ratio = sum(1 for ch in texto_raw if ord(ch) < 128) / max(1, len(texto_raw))
        return (IdiomaDetectado.EN, 0.55) if ascii_ratio > 0.85 else (IdiomaDetectado.OTRO, 0.4)

    # Deteccion de texto bilingue EN+ES comun en freelance LATAM/Global
    if {top_idi, seg_idi} == {IdiomaDetectado.EN, IdiomaDetectado.ES} and seg_val >= 3 and (seg_val / max(1, top_val)) >= 0.45:
        return IdiomaDetectado.MIXTO, 0.82

    total_hits = sum(conteos.values())
    confianza = min(0.99, (top_val / max(1, total_hits)) * (0.65 + min(0.35, top_val / 10.0)))
    return top_idi, confianza


def extraer_entidades(texto: str) -> EntidadesExtraidas:
    ent = EntidadesExtraidas()
    if not texto:
        return ent

    urls_raw = REGEX_URL.findall(texto)
    dominios_set: set[str] = set()
    acort_set: set[str] = set()
    for u in urls_raw[:20]:
        u_clean = u.rstrip(".,;:!?")
        if u_clean not in ent.urls:
            ent.urls.append(u_clean)
        u_parse = u_clean if u_clean.lower().startswith("http") else f"https://{u_clean}"
        try:
            dom = urlparse(u_parse).netloc.lower().replace("www.", "")
            if dom:
                dominios_set.add(dom)
                if dom in ACORTADORES_URL:
                    acort_set.add(dom)
        except Exception:
            pass

    ent.dominios = sorted(dominios_set)
    ent.acortadores_detectados = sorted(acort_set)
    ent.emails = sorted({m.lower() for m in REGEX_EMAIL.findall(texto)})[:10]
    ent.repos_github = sorted({m for m in REGEX_GITHUB_REPO.findall(texto)})[:8]
    ent.handles_sociales = sorted({m.strip() for m in REGEX_HANDLE.findall(texto)})[:10]
    ent.canales_contacto_externo = sorted({m.strip() for m in REGEX_CONTACTO_EXT.findall(texto)})[:8]

    low = texto.lower()
    ent.plataformas_mencionadas = sorted(p for p in PLATAFORMAS_CONOCIDAS if p in low)
    return ent


def tokenizar_limpio(texto: str) -> list[str]:
    if not texto:
        return []
    # Preserva terminos tecnicos con +, # o . interno (c++, c#, node.js, next.js)
    return [t.lower() for t in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9+#.\-_]{1,32}", texto)]


class NormalizadorForense:
    """
    Capa 1 de AEGIS-X: limpia HTML, neutraliza homoglifos y caracteres invisibles,
    des-ofusca evasiones, extrae entidades y calcula metricas de calidad y entropia.
    """

    def normalizar(
        self,
        titulo: str,
        cuerpo: str = "",
        tags: str = "",
        flair: str = "",
    ) -> DocumentoNormalizado:
        t_html = limpiar_html_estructurado(titulo, max_len=360)
        c_html = limpiar_html_estructurado(cuerpo, max_len=3200)
        g_html = limpiar_html_estructurado(tags, max_len=400)
        f_html = limpiar_html_estructurado(flair, max_len=120)

        t_uni, h1, inv1 = _desofuscar_unicode(t_html)
        c_uni, h2, inv2 = _desofuscar_unicode(c_html)
        g_uni, h3, inv3 = _desofuscar_unicode(g_html)
        f_uni, h4, inv4 = _desofuscar_unicode(f_html)

        t_limpio, ev1 = _desofuscar_evasiones(t_uni)
        c_limpio, ev2 = _desofuscar_evasiones(c_uni)

        unificado = "\n".join(p for p in (f_uni, t_limpio, c_limpio, g_uni) if p).strip()
        sin_acentos = _quitar_acentos(unificado)
        busqueda = re.sub(r"\s+", " ", sin_acentos.lower()).strip()

        toks_t = tokenizar_limpio(_quitar_acentos(t_limpio))
        toks_c = tokenizar_limpio(_quitar_acentos(c_limpio))
        toks_todos = toks_t + toks_c + tokenizar_limpio(_quitar_acentos(g_uni))
        toks_sig = [t for t in toks_todos if len(t) >= 3 and t not in STOPWORDS_COMUNES]

        entidades = extraer_entidades(unificado)
        idioma, conf_idi = detectar_idioma(toks_todos, unificado)

        # Metricas forenses de calidad del texto
        letras = [ch for ch in unificado if ch.isalpha()]
        mayus = sum(1 for ch in letras if ch.isupper())
        digitos = sum(1 for ch in unificado if ch.isdigit())
        puntuacion = sum(1 for ch in unificado if ch in "!?$%*#@")
        total_chars = max(1, len(unificado))

        palabras_tot = len(toks_todos)
        palabras_uni = len(set(toks_todos))
        diversidad = palabras_uni / max(1, palabras_tot)
        entropia = calcular_entropia_shannon(unificado)

        ratio_mayus = mayus / max(1, len(letras))
        ratio_dig = digitos / total_chars
        ratio_punt = puntuacion / total_chars
        n_lineas = len([ln for ln in c_limpio.splitlines() if ln.strip()])
        tiene_vinetas = bool(REGEX_VINETAS.search(c_limpio))
        tiene_codigo = bool(REGEX_BLOQUE_CODIGO.search(c_limpio))

        # Score de calidad estructural (0..100)
        calidad = 55.0
        if len(t_limpio) >= 18:
            calidad += 8.0
        if palabras_tot >= 25:
            calidad += 12.0
        elif palabras_tot < 8:
            calidad -= 22.0
        if tiene_vinetas:
            calidad += 8.0
        if tiene_codigo or entidades.repos_github:
            calidad += 10.0
        if diversidad >= 0.45 and palabras_tot >= 15:
            calidad += 6.0
        elif diversidad < 0.25 and palabras_tot >= 20:
            calidad -= 18.0  # Repeticion tipo spam
        if ratio_mayus > 0.65 and len(letras) >= 20:
            calidad -= 18.0  # TODO EN MAYUSCULAS GRITANDO
        if entropia < 2.6 and total_chars > 30:
            calidad -= 20.0  # Texto basura repetitivo
        if (h1 + h2 + h3 + h4) >= 3 or (inv1 + inv2 + inv3 + inv4) >= 3:
            calidad -= 25.0  # Ofuscacion deliberada
        if ev1 or ev2:
            calidad -= 15.0

        calidad = max(0.0, min(100.0, calidad))

        metricas = MetricasTexto(
            chars_titulo=len(t_limpio),
            chars_cuerpo=len(c_limpio),
            palabras_totales=palabras_tot,
            palabras_unicas=palabras_uni,
            ratio_mayusculas=round(ratio_mayus, 3),
            ratio_digitos=round(ratio_dig, 3),
            ratio_puntuacion=round(ratio_punt, 3),
            entropia_shannon=round(entropia, 3),
            diversidad_lexica=round(diversidad, 3),
            cantidad_lineas=n_lineas,
            tiene_vinetas=tiene_vinetas,
            tiene_bloque_codigo=tiene_codigo,
            homoglifos_reemplazados=h1 + h2 + h3 + h4,
            chars_invisibles_eliminados=inv1 + inv2 + inv3 + inv4,
            evasion_espaciada_detectada=(ev1 or ev2),
            score_calidad=round(calidad, 1),
        )

        return DocumentoNormalizado(
            titulo_original=titulo or "",
            cuerpo_original=cuerpo or "",
            tags_original=tags or "",
            flair_original=flair or "",
            titulo_limpio=t_limpio,
            cuerpo_limpio=c_limpio,
            tags_limpio=g_uni,
            flair_limpio=f_uni,
            texto_unificado=unificado,
            texto_busqueda=busqueda,
            texto_sin_acentos=sin_acentos,
            tokens_titulo=toks_t,
            tokens_cuerpo=toks_c,
            tokens_significativos=toks_sig,
            idioma=idioma,
            confianza_idioma=round(conf_idi, 3),
            entidades=entidades,
            metricas=metricas,
        )


_NORMALIZADOR_SINGLETON = NormalizadorForense()


def normalizar_oferta(titulo: str, cuerpo: str = "", tags: str = "", flair: str = "") -> DocumentoNormalizado:
    return _NORMALIZADOR_SINGLETON.normalizar(titulo=titulo, cuerpo=cuerpo, tags=tags, flair=flair)