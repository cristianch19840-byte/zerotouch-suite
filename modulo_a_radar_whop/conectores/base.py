import time
import threading
from modulo_a_radar_whop.conectores.filtros import (
    normalizar_titulo,
    titulo_palabras_limpio,
    puntuar_relevancia_local,
    detectar_prioridad_tag,
    calcular_competencia,
    extraer_dinero_combinado,
)

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json,application/xml,text/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_DOMAIN_LOCK = threading.Lock()
_LAST_HIT: dict[str, float] = {}

def esperar_dominio(dominio: str, min_intervalo: float = 0.25) -> None:
    try:
        from titan_core.rate_limiter import obtener_rate_limiter
        obtener_rate_limiter().adquirir(dominio, pausa_min_override=min_intervalo)
        return
    except Exception:
        pass
    with _DOMAIN_LOCK:
        ahora = time.time()
        ultimo = _LAST_HIT.get(dominio, 0.0)
        espera = min_intervalo - (ahora - ultimo)
        if espera > 0:
            time.sleep(espera)
        _LAST_HIT[dominio] = time.time()

def crear_oferta(
    post_id: str,
    fuente: str,
    plataforma: str,
    tipo_trabajo: str,
    titulo: str,
    texto: str,
    link: str,
    autor: str = "",
    edad_min: int | None = None,
    comentarios: int | None = None,
    monto_directo: float = 0.0,
    presupuesto_txt: str = "",
    tags_extra: str = "",
    comp_txt_override: str | None = None,
    bonus_extra: int = 0,
    origen: str | None = None,
) -> dict:
    titulo_limpio = (titulo or "").strip()
    texto_limpio = (texto or "").strip()[:1600]
    tech_score, es_tech = puntuar_relevancia_local(titulo_limpio, texto_limpio, sub_o_tags=tags_extra)
    dinero_local = extraer_dinero_combinado(titulo_limpio, texto_limpio, monto_directo=monto_directo)
    combinado = f"{titulo_limpio} {texto_limpio} {presupuesto_txt}"
    prio_tag = detectar_prioridad_tag(combinado, dinero_local)

    if comp_txt_override:
        comp_txt, comp_bonus = comp_txt_override, bonus_extra
    else:
        comp_txt, comp_bonus = calcular_competencia(edad_min, comentarios, etiqueta_fallback=f"🌐 {plataforma}")
        comp_bonus += bonus_extra

    total_bonus = comp_bonus + (2 if prio_tag else 0) + (1 if dinero_local >= 100 else 0) + (1 if tech_score >= 6 else 0)

    return {
        "id": str(post_id or link),
        "fuente": fuente,
        "plataforma": plataforma,
        "tipo_trabajo": tipo_trabajo,
        "autor": autor or "",
        "titulo": titulo_limpio,
        "titulo_norm": normalizar_titulo(titulo_limpio),
        "titulo_palabras": titulo_palabras_limpio(titulo_limpio),
        "texto": texto_limpio,
        "link": link or "",
        "es_tech": es_tech,
        "tech_score": tech_score,
        "edad_min": edad_min,
        "comentarios": comentarios,
        "comp_txt": comp_txt,
        "comp_bonus": total_bonus,
        "dinero_local": dinero_local,
        "presupuesto_txt": presupuesto_txt or (f"${int(dinero_local)} USD" if dinero_local > 0 else ""),
        "prioridad_tag": prio_tag,
        "origen": origen or plataforma.lower(),
    }

def crear_meta_fuente(
    fuente: str,
    clave_config: str,
    ok: bool,
    modo: str,
    bruto: int = 0,
    tech: int = 0,
    descartes: dict | None = None,
    error: str = "",
) -> dict:
    return {
        "fuente": fuente,
        "clave_config": clave_config,
        "ok": ok,
        "modo": modo,
        "bruto": bruto,
        "tech": tech,
        "descartes": descartes or {},
        "error": error,
    }

def http_get_blindado(url: str, *, params=None, headers=None, timeout: float = 12.0, cache_ttl_seg: float = 90.0):
    from titan_core.http_shield import obtener_http_shield
    return obtener_http_shield().get(
        url, params=params, headers=headers, timeout=timeout,
        reintentos=1, cache_ttl_seg=cache_ttl_seg, usar_etag=True,
    )

def http_get_json_blindado(url: str, *, params=None, headers=None, timeout: float = 12.0, cache_ttl_seg: float = 90.0):
    from titan_core.http_shield import obtener_http_shield
    return obtener_http_shield().get_json(
        url, params=params, headers=headers, timeout=timeout,
        reintentos=1, cache_ttl_seg=cache_ttl_seg, usar_etag=True,
    )
