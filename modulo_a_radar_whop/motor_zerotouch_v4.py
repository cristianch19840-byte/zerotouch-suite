import os
import re
import sys
import html
import time
from collections import defaultdict
from datetime import datetime
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core_ia import (
    C,
    SESSION,
    safe_int,
    safe_bool,
    extraer_score,
    extraer_presupuesto_usd,
    log_evento,
    cargar_config,
    preparar_db,
    registrar_metricas,
    registrar_salud_fuentes,
    obtener_salud_fuentes,
    similitud_jaccard,
    verificar_confianza_reddit,
    generar_json_ia,
    generar_json_lote_ia,
    alerta_sonora,
)
from modulo_a_radar_whop.conectores.reddit import (
    escanear_reddit,
    diagnosticar_reddit_real,
    obtener_headers_reddit_oauth,
    consultar_pullpush,
)
from modulo_a_radar_whop.conectores.freelancer import escanear_freelancer
from modulo_a_radar_whop.conectores.github_bounties import escanear_github_bounties
from modulo_a_radar_whop.conectores.hackernews import escanear_hackernews
from modulo_a_radar_whop.conectores.bolsas_remotas import escanear_bolsas_remotas
from modulo_a_radar_whop.conectores.rss_universal import escanear_weworkremotely, escanear_rss_custom
from modulo_a_radar_whop.conectores.base import crear_meta_fuente
from modulo_a_radar_whop.motor_filtrado.pipeline import obtener_pipeline_aegis
from modulo_a_radar_whop.conectores.freelance_feeds import recolectar_conectores_pro

TG_TOKEN = os.getenv("TELEGRAM_TOKEN")
TG_CHANNEL_ID = os.getenv("TELEGRAM_CHAT_ID")

ORDEN_PRIORIDAD_PLATAFORMAS = [
    "Reddit",
    "Freelancer",
    "GitHub",
    "HackerNews",
    "RSS",
    "WWR",
    "RemoteOK",
    "Remotive",
    "Himalayas",
    "Jobicy",
    "WorkingNomads",
    "Arbeitnow",
]

def construir_dm_reddit(autor: str, titulo: str, pitch: str) -> str | None:
    if not autor or autor.lower() in ("[deleted]", "automoderator", "none", "github", "hackernews", "freelancer_client"):
        return None
    asunto = quote(f"Re: {titulo[:65]}")
    cuerpo = quote(pitch[:380])
    return f"https://www.reddit.com/message/compose/?to={quote(autor)}&subject={asunto}&message={cuerpo}"

def publicar_telegram(mensaje_html: str, fallback_texto: str, botones: list | None = None, chat_id: str | None = None) -> bool:
    destino = chat_id or TG_CHANNEL_ID
    if not TG_TOKEN or not destino:
        log_evento("[!] Faltan credenciales de Telegram")
        print(f"    {C.RED}[!] Faltan credenciales de Telegram.{C.RESET}", flush=True)
        return False
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {
        "chat_id": destino,
        "text": mensaje_html[:4050],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if botones:
        payload["reply_markup"] = {"inline_keyboard": botones}
    try:
        r = SESSION.post(url, json=payload, timeout=15)
        if r.status_code == 200:
            print(f"    {C.GREEN}[TG] Alerta OMNI enviada!{C.RESET}", flush=True)
            return True
        payload.pop("reply_markup", None)
        r2 = SESSION.post(url, json=payload, timeout=15)
        if r2.status_code == 200:
            return True
        plano_limpio = re.sub(r"<[^>]+>", "", fallback_texto)[:4000]
        r3 = SESSION.post(url, json={"chat_id": destino, "text": plano_limpio, "disable_web_page_preview": True}, timeout=15)
        return r3.status_code == 200
    except Exception as e:
        log_evento(f"[TG] Excepcion: {e}")
        print(f"    {C.RED}[TG] Excepcion: {e}{C.RESET}", flush=True)
    return False

def recolectar_todo(cfg: dict) -> tuple[list[dict], dict]:
    activas = cfg.get("fuentes_activas") or {}
    ofertas_raw: list[dict] = []
    detalle_fuentes: list[dict] = []

    tareas = []
    if activas.get("reddit", True):
        tareas.append(("Reddit", lambda: escanear_reddit(cfg), True))
    if activas.get("freelancer", True):
        tareas.append(("Freelancer.com", lambda: escanear_freelancer(cfg), False))
    if activas.get("github_bounties", True):
        tareas.append(("GitHub Bounties", lambda: escanear_github_bounties(cfg), False))
    if activas.get("hackernews", True):
        tareas.append(("HackerNews", lambda: escanear_hackernews(cfg), False))
    if activas.get("weworkremotely", True):
        tareas.append(("WeWorkRemotely", lambda: escanear_weworkremotely(cfg), False))
    if activas.get("rss_custom", True) and (cfg.get("feeds_rss_custom") or []):
        tareas.append(("RSS-Custom", lambda: escanear_rss_custom(cfg), True))

    hay_bolsas = any(activas.get(k, True) for k in ("remoteok", "remotive", "jobicy", "himalayas", "workingnomads", "arbeitnow"))
    if hay_bolsas:
        tareas.append(("Bolsas-Remotas", lambda: escanear_bolsas_remotas(cfg), True))

    with ThreadPoolExecutor(max_workers=6) as pool:
        futuros = {pool.submit(fn): (nom, multi_meta) for nom, fn, multi_meta in tareas}
        for fut in as_completed(futuros):
            nom, multi_meta = futuros[fut]
            try:
                its, meta = fut.result()
                ofertas_raw.extend(its)
                if multi_meta and isinstance(meta, list):
                    detalle_fuentes.extend(meta)
                elif isinstance(meta, dict):
                    detalle_fuentes.append(meta)
            except Exception as e:
                log_evento(f"[!] Error conector {nom}: {e}")
                detalle_fuentes.append(crear_meta_fuente(nom, nom.lower(), False, "ERR", error=str(e)[:100]))

    # Filtro opcional: solo proyectos freelance cortos y bounties (ignorar bolsas full-time)
    if cfg.get("solo_freelance_corto"):
        ofertas_raw = [x for x in ofertas_raw if x.get("tipo_trabajo") in ("freelance", "bounty")]

    # Orden inicial por calidad/frescura antes de deduplicar en memoria
    ofertas_raw.sort(
        key=lambda x: (
            1 if x.get("tipo_trabajo") in ("freelance", "bounty") else 0,
            x.get("comp_bonus", 0),
            x.get("dinero_local", 0) > 0,
            x.get("tech_score", 0),
            -(x.get("edad_min") if x.get("edad_min") is not None else 999),
        ),
        reverse=True,
    )

    unicas: list[dict] = []
    vistos_ids: set[str] = set()
    vistos_tit: set[str] = set()
    vistos_links: set[str] = set()
    dup_memoria = 0

    for it in ofertas_raw:
        pid = it.get("id") or ""
        tn = it.get("titulo_norm") or ""
        lk = it.get("link") or ""
        if (pid and pid in vistos_ids) or (tn and tn in vistos_tit) or (lk and lk in vistos_links):
            dup_memoria += 1
            continue
        if pid:
            vistos_ids.add(pid)
        if tn:
            vistos_tit.add(tn)
        if lk:
            vistos_links.add(lk)
        unicas.append(it)

    descartes_totales: dict[str, int] = {}
    for m in detalle_fuentes:
        for k, v in (m.get("descartes") or {}).items():
            descartes_totales[k] = descartes_totales.get(k, 0) + v

    telemetria = {
        "fuentes_ok": sum(1 for m in detalle_fuentes if m.get("ok")),
        "fuentes_total": len(detalle_fuentes),
        "bruto": sum(m.get("bruto", 0) for m in detalle_fuentes),
        "dup_memoria": dup_memoria,
        "descartes_pre": descartes_totales,
        "detalle_fuentes": sorted(detalle_fuentes, key=lambda x: x["fuente"]),
    }
    return unicas, telemetria

def mezclar_equitativamente(candidatas: list[dict], limite: int) -> list[dict]:
    """Intercala candidatas por plataforma (round-robin) para que una sola fuente no acapare la cuota de IA."""
    if len(candidatas) <= limite:
        return candidatas
    grupos: dict[str, list[dict]] = defaultdict(list)
    for it in candidatas:
        grupos[it.get("plataforma") or it.get("fuente") or "Otras"].append(it)

    orden_claves = [p for p in ORDEN_PRIORIDAD_PLATAFORMAS if p in grupos]
    for k in sorted(grupos.keys()):
        if k not in orden_claves:
            orden_claves.append(k)

    resultado: list[dict] = []
    while len(resultado) < limite:
        agregado = False
        for k in orden_claves:
            if grupos[k]:
                resultado.append(grupos[k].pop(0))
                agregado = True
                if len(resultado) >= limite:
                    break
        if not agregado:
            break
    return resultado

def contexto_aprendizaje_crm(conn) -> str:
    if conn is None:
        return ""
    try:
        gan = [r[0][:50] for r in conn.execute("SELECT titulo FROM leads WHERE estado = 'ganado' ORDER BY id DESC LIMIT 4").fetchall()]
        desc = [r[0][:50] for r in conn.execute("SELECT titulo FROM leads WHERE estado = 'descartado' ORDER BY id DESC LIMIT 4").fetchall()]
        partes = []
        if gan:
            partes.append(f"Proyectos similares a los que el dev YA GANO (subir score): {gan}")
        if desc:
            partes.append(f"Proyectos que el dev DESCARTO (bajar score): {desc}")
        return "\n".join(partes)
    except Exception:
        return ""

def revisar_recordatorios_followup(conn, cfg: dict) -> int:
    horas = max(1, safe_int(cfg.get("recordatorio_followup_horas", 20), 20))
    pendientes = conn.execute(
        f"""
        SELECT id, autor, titulo, link FROM leads
        WHERE estado = 'contactado'
          AND followup_enviado = 0
          AND COALESCE(contactado_ts, fecha) <= datetime('now', '-{horas} hours')
        LIMIT 3
        """
    ).fetchall()
    enviados = 0
    for lid, autor, titulo, link in pendientes:
        followup = f"Hey! Just following up on your post about {titulo[:50]} — I still have availability to build and deliver a clean working prototype today if you haven't picked someone yet."
        msg = (
            f"<b>⏰ RECORDATORIO FOLLOW-UP (Lead #{lid})</b>\n"
            f"Hace mas de {horas}h contactaste a <b>{html.escape(autor or 'cliente')}</b>:\n"
            f"📌 {html.escape(titulo[:140])}\n\n"
            f"📋 <b>SEGUIMIENTO LISTO (toca para copiar):</b>\n"
            f"<code>{html.escape(followup[:600])}</code>"
        )
        botones = [[{"text": "🚀 Abrir Oferta", "url": link}]] if link and link.startswith("http") else None
        if publicar_telegram(msg, msg, botones=botones):
            conn.execute("UPDATE leads SET followup_enviado = 1 WHERE id = ?", (lid,))
            conn.commit()
            enviados += 1
    return enviados

def _enviar_y_guardar_oferta(item: dict, datos: dict, cfg: dict, conn=None, modo_sonido: bool = False) -> bool:
    score_min = safe_int(cfg.get("score_minimo", 6), 6)
    es_relevante = safe_bool(datos.get("relevante"))
    score = extraer_score(datos.get("score", 0))
    fuente = item["fuente"]
    plataforma = item.get("plataforma") or fuente
    tipo_trabajo = item.get("tipo_trabajo") or "freelance"
    titulo = item["titulo"]
    link = item["link"]
    autor = item.get("autor", "")
    comp_txt = item.get("comp_txt", "🔎 En radar")
    prio_tag = item.get("prioridad_tag", "")

    print(f"    [=] {fuente:<15} | Rel: {es_relevante} | Score: {score}/10 | {titulo[:46]}", flush=True)
    if not (es_relevante and score >= score_min):
        return False

    categoria = str(datos.get("categoria") or "Tech")[:40]
    presupuesto = str(datos.get("presupuesto") or item.get("presupuesto_txt") or "Por definir")[:60]
    pres_num = extraer_presupuesto_usd(presupuesto) or float(item.get("dinero_local") or 0)
    resumen = str(datos.get("resumen_es") or "")[:480]
    pitch = str(datos.get("pitch_en") or "")[:1150]
    origen = (item.get("origen") or plataforma).lower()

    if origen == "reddit":
        confianza = verificar_confianza_reddit(autor)
    elif origen == "freelancer":
        confianza = "💼 Proyecto verificado en Freelancer.com"
    elif origen == "github":
        confianza = "💎 Issue oficial en GitHub"
    else:
        confianza = f"🌐 {plataforma}" + (f" ({autor})" if autor and autor.lower() != plataforma.lower() else "")

    badge_tipo = {"bounty": "💎 BOUNTY", "remoto": "🌍 REMOTO"}.get(tipo_trabajo, "💼 FREELANCE")
    etiqueta = "🔥🔥 TOP" if score >= 8 else "⚡ LEAD"
    linea_prio = f"🏷 <b>Alerta:</b> {html.escape(prio_tag)}\n" if prio_tag else ""

    if origen == "github":
        accion = "Entra al Issue y comenta reclamando el bounty antes de abrir PR"
        texto_btn = "💎 Abrir Bounty"
    elif origen == "freelancer":
        accion = "Puja rapido con el pitch de abajo y ofrece avance en 24h"
        texto_btn = "💼 Pujar en Freelancer"
    elif origen == "hn":
        accion = "Abre el hilo de HackerNews y escribe al correo/contacto del comentario"
        texto_btn = "🔥 Abrir HackerNews"
    elif origen == "reddit":
        if fuente.lower() in ("r/slavelabour", "r/donedirtcheap"):
            accion = "Comenta $bid en el post ANTES de tocar 'DM Pre-llenado'"
        else:
            accion = "Toca 'DM Pre-llenado' abajo y envia directo al cliente"
        texto_btn = "🚀 Abrir Post Reddit"
    else:
        accion = f"Aplica en {plataforma} usando el pitch adaptado de abajo"
        texto_btn = f"🌐 Aplicar en {plataforma[:14]}"

    msg_html = (
        f"<b>{etiqueta} | {badge_tipo} | [{html.escape(categoria)}] {score}/10</b>\n"
        f"{linea_prio}"
        f"💰 <b>Presupuesto:</b> {html.escape(presupuesto)}  |  📍 <b>{html.escape(fuente)}</b>\n"
        f"⏱ <b>Competencia:</b> {html.escape(comp_txt)}\n"
        f"👤 <b>Cliente:</b> {html.escape(confianza)}\n\n"
        f"📌 <b>{html.escape(titulo[:180])}</b>\n"
        f"📝 {html.escape(resumen)}\n"
        f"⚠️ <i>{html.escape(accion)}</i>\n\n"
        f"📋 <b>PITCH (toca para copiar):</b>\n"
        f"<code>{html.escape(pitch)}</code>"
    )
    msg_plano = (
        f"{etiqueta} {badge_tipo} [{categoria}] {score}/10 {prio_tag}\n"
        f"Presupuesto: {presupuesto} | {fuente} | {comp_txt} | {confianza}\n\n"
        f"{titulo}\n{resumen}\nProtocolo: {accion}\nLink: {link}\n\nPITCH:\n{pitch}"
    )

    botones = []
    fila = []
    if link.startswith("http"):
        fila.append({"text": texto_btn, "url": link})
    if origen == "reddit":
        dm_url = construir_dm_reddit(autor, titulo, pitch)
        if dm_url and len(dm_url) < 1800:
            fila.append({"text": "⚡ DM Pre-llenado", "url": dm_url})
    if fila:
        botones.append(fila)

    _juez_res = None
    try:
        from titan_core.filtro_perfil_gemini import cargar_perfil_config as _cargar_p_cfg
        if _cargar_p_cfg().get('activo', True):
            from titan_core.juez_gemini_38 import evaluar_y_traducir_oferta as _juez_eval
            _juez_res = _juez_eval(titulo=str(titulo or ''), cuerpo=str(resumen or ''), plataforma=str(plataforma or fuente or ''), presupuesto=str(presupuesto or ''), usar_ia=True)
            if not _juez_res.get('suficiente_gemini_38_high', False):
                log_evento(f"[Juez Gemini 3.8] Rechazada: {str(titulo)[:42]} | {_juez_res.get('motivo_es', '')[:65]}")
                return False
            if _juez_res.get('resumen_es'):
                msg_html = f"{msg_html}\n\n<b>Que pide (ES):</b> {_juez_res['resumen_es']}\n<b>Gemini 3.8 High:</b> APTA ({_juez_res.get('nivel_dificultad', 'media')}) - {_juez_res.get('motivo_es', '')}"
                msg_plano = f"{msg_plano}\n\n[ES] {_juez_res['resumen_es']}\n[Gemini 3.8 High] APTA: {_juez_res.get('motivo_es', '')}"
    except Exception as _ej:
        log_evento(f'[Juez Gemini 3.8] Aviso: {_ej}')
    enviado = publicar_telegram(msg_html, msg_plano, botones=botones)
    log_evento(f"Lead {score}/10 ({fuente} | ${pres_num:.0f}): {titulo[:52]}")
    if modo_sonido and score >= 7:
        alerta_sonora("ballena" if "HIGH-TICKET" in prio_tag else ("alta" if score >= 8 else "media"))

    if conn is not None:
        ya_existe = link and conn.execute("SELECT 1 FROM leads WHERE link = ?", (link,)).fetchone()
        if not ya_existe:
            conn.execute(
                """
                INSERT INTO leads
                (fuente, plataforma, tipo_trabajo, autor, titulo, categoria, presupuesto, presupuesto_num, score, competencia, confianza, prioridad_tag, link)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (fuente, plataforma, tipo_trabajo, autor, titulo, categoria, presupuesto, pres_num, score, comp_txt, confianza, prio_tag, link),
            )
            if _juez_res and _juez_res.get('hash_oferta'):
                try:
                    _lid = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
                    if _lid:
                        conn.execute('UPDATE juez_ia_leads SET lead_id = ? WHERE hash_oferta = ?', (int(_lid), _juez_res['hash_oferta']))
                except Exception:
                    pass
            conn.commit()
    return enviado

def evaluar_y_enviar(item: dict, cfg: dict, conn=None, modo_sonido: bool = False, aprendizaje: str = "") -> tuple[bool, bool, int]:
    """Evalua una sola oferta (usado en --test, /api/test_tg y fallback de lote)."""
    fuente = item["fuente"]
    titulo = item["titulo"]
    texto_limpio = item["texto"]
    tipo = item.get("tipo_trabajo", "freelance")
    print(f"  {C.CYAN}[>] IA Individual ({fuente}):{C.RESET} {titulo[:60]}...", flush=True)

    regla = (
        "En r/forhire NO ofrezcas trabajo gratis; demuestra diagnostico tecnico inmediato."
        if "forhire" in fuente.lower()
        else "Adapta el pitch en ingles (40-65 palabras) a la plataforma, directo al grano y sin sonar a IA."
    )
    prompt = (
        f"Evalua esta oportunidad ({tipo}) de {fuente} y responde UNICAMENTE con JSON valido.\n"
        f"Titulo: {titulo}\nPresupuesto detectado: {item.get('presupuesto_txt', '')}\nContenido: {texto_limpio[:1200]}\n"
        f"Especialidad del dev: {cfg.get('especialidad')}\nContexto: {regla}\n{aprendizaje}\n"
        "REGLAS: relevante=true si encaja con Python, scraping, bots Telegram/Discord, automatizacion, APIs, backend/web o bounties pagos (freelance, contrato o remoto dev de buen nivel). "
        "Rechaza [For Hire], trabajo presencial obligatorio, sin pago, estafas, ventas/marketing no tech o tareas escolares.\n"
        'Formato exacto: {"relevante": true, "score": 8, "categoria": "Python", "presupuesto": "$150 USD", "resumen_es": "...", "pitch_en": "..."}'
    )
    datos = generar_json_ia(prompt, temperatura=0.2, timeout=18)
    tok_est = (len(prompt) + 320) // 4
    if not datos:
        return False, False, tok_est

    enviado = _enviar_y_guardar_oferta(item, datos, cfg, conn=conn, modo_sonido=modo_sonido)
    return True, enviado, tok_est

def evaluar_lote_y_enviar(lote: list[dict], cfg: dict, conn=None, modo_sonido: bool = False, aprendizaje: str = "") -> tuple[list[dict], int, int]:
    """Evalua hasta 5 ofertas en 1 sola llamada a Gemini (-60% tokens). Devuelve (items_ok, alertas_enviadas, tok_est)."""
    if len(lote) == 1:
        ok, env, tok = evaluar_y_enviar(lote[0], cfg, conn=conn, modo_sonido=modo_sonido, aprendizaje=aprendizaje)
        return ([lote[0]] if ok else []), (1 if env else 0), tok

    bloques = []
    for idx, it in enumerate(lote):
        bloques.append(
            f"[{idx}] Fuente: {it['fuente']} ({it.get('tipo_trabajo', 'freelance')}) | Presupuesto: {it.get('presupuesto_txt') or 'N/A'}\n"
            f"Titulo: {it['titulo'][:160]}\n"
            f"Detalle: {it['texto'][:700]}"
        )

    prompt = (
        "Eres un evaluador experto de oportunidades freelance, bounties y contratos remotos de programacion.\n"
        f"Especialidad del dev: {cfg.get('especialidad')}\n"
        f"{aprendizaje}\n"
        "REGLAS:\n"
        "- relevante=true SOLO si es una oportunidad real para programar/automatizar (Python, scraping, bots Telegram/Discord, APIs, backend/fullstack, n8n/Zapier, datos o bounty pago).\n"
        "- Si solo_freelance_corto=true, rechaza puestos corporativos full-time fijos; si es false, acepta tambien buenos contratos/remotos dev con score alto.\n"
        f"- solo_freelance_corto={str(bool(cfg.get('solo_freelance_corto'))).lower()}\n"
        "- Rechaza [For Hire], trabajo presencial, sin pago, estafas, diseño/video/redaccion o tareas escolares.\n"
        "- Si relevante=false, deja resumen_es y pitch_en vacios (\"\") para ahorrar tokens.\n"
        "- Si relevante=true, escribe resumen_es (1-2 frases en espanol) y pitch_en (40-60 palabras en ingles natural, sin sonar a IA, adaptado a la plataforma).\n"
        'Responde UNICAMENTE con JSON valido en este formato exacto: {"resultados": [{"idx": 0, "relevante": true, "score": 8, "categoria": "Python", "presupuesto": "$150 USD", "resumen_es": "...", "pitch_en": "..."}]}\n\n'
        "OFERTAS A EVALUAR:\n" + "\n---\n".join(bloques)
    )

    print(f"  {C.CYAN}[>] IA LOTE ({len(lote)} ofertas en 1 llamada):{C.RESET} {', '.join(x['fuente'] for x in lote)}", flush=True)
    resp = generar_json_lote_ia(prompt, temperatura=0.2, timeout=28)
    tok_est = (len(prompt) + len(lote) * 140) // 4

    lista_res = None
    if isinstance(resp, list):
        lista_res = resp
    elif isinstance(resp, dict):
        if isinstance(resp.get("resultados"), list):
            lista_res = resp["resultados"]
        elif isinstance(resp.get("items"), list):
            lista_res = resp["items"]

    if not lista_res:
        print(f"    {C.YELLOW}[~] Lote sin JSON valido, intentando individual para las 2 primeras...{C.RESET}", flush=True)
        items_ok: list[dict] = []
        alertas = 0
        for it in lote[:2]:
            ok, env, t2 = evaluar_y_enviar(it, cfg, conn=conn, modo_sonido=modo_sonido, aprendizaje=aprendizaje)
            tok_est += t2
            if ok:
                items_ok.append(it)
            if env:
                alertas += 1
        return items_ok, alertas, tok_est

    mapa_res: dict[int, dict] = {}
    for entry in lista_res:
        if isinstance(entry, dict) and "idx" in entry:
            mapa_res[safe_int(entry["idx"], -1)] = entry

    items_ok = []
    alertas = 0
    for idx, it in enumerate(lote):
        datos = mapa_res.get(idx)
        if not datos:
            continue
        items_ok.append(it)
        if _enviar_y_guardar_oferta(it, datos, cfg, conn=conn, modo_sonido=modo_sonido):
            alertas += 1
    return items_ok, alertas, tok_est

def enviar_resumen_telegram(chat_id: str | None = None) -> str:
    conn = preparar_db()
    try:
        hoy = datetime.now().strftime("%Y-%m-%d")
        row = conn.execute(
            "SELECT descartados_local, evaluados_ia, alertas_enviadas, tokens_est_usados, tokens_est_ahorrados FROM stats_diarias WHERE fecha = ?",
            (hoy,),
        ).fetchone()
        desc, ev, al, t_us, t_ah = row if row else (0, 0, 0, 0, 0)
        total_usd = conn.execute("SELECT COALESCE(SUM(ganancia_usd), 0) FROM leads WHERE estado = 'ganado'").fetchone()[0]
        pipeline_usd = conn.execute("SELECT COALESCE(SUM(presupuesto_num), 0) FROM leads WHERE estado IN ('contactado', 'negociando')").fetchone()[0]
        total_leads = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        ganados = conn.execute("SELECT COUNT(*) FROM leads WHERE estado = 'ganado'").fetchone()[0]
        pendientes = conn.execute("SELECT COUNT(*) FROM leads WHERE estado IN ('nuevo', 'contactado', 'negociando')").fetchone()[0]
        salud = obtener_salud_fuentes(conn)
        f_ok = sum(1 for s in salud if s["ok"])

        msg = (
            f"<b>📊 RESUMEN ZEROTOUCH OMNI-GRID v13.0 ({hoy})</b>\n\n"
            f"🌐 <b>Fuentes activas saludables:</b> {f_ok}/{len(salud)}\n"
            f"🛡️ <b>Basura bloqueada sin IA:</b> {desc} (~{t_ah:,} tokens ahorrados)\n"
            f"🤖 <b>Ofertas analizadas hoy:</b> {ev} (~{t_us:,} tokens usados)\n"
            f"⚡ <b>Alertas enviadas hoy:</b> {al}\n"
            f"📂 <b>Leads activos en CRM:</b> {pendientes} (Total: {total_leads})\n"
            f"💼 <b>Pipeline en negociacion:</b> ~${pipeline_usd:.0f} USD\n"
            f"🏆 <b>Clientes ganados:</b> {ganados}\n"
            f"💵 <b>Total facturado:</b> ${total_usd:.2f} USD"
        )
        publicar_telegram(msg, msg, chat_id=chat_id)
        return msg
    finally:
        conn.close()

def ejecutar_ciclo(modo_sonido: bool = False, dry_run: bool = False) -> dict:
    cfg = cargar_config()
    max_ia = max(1, safe_int(cfg.get("max_ia_por_ciclo", 20), 20))
    tam_lote = max(1, min(8, safe_int(cfg.get("batch_ia_tamano", 5), 5)))
    t0 = time.time()
    hora = datetime.now().strftime("%H:%M:%S")
    etiqueta_modo = "DRY-RUN 0-TOKENS" if dry_run else "OMNI-GRID v13.0"
    log_evento(f"Iniciando escaneo {etiqueta_modo}")
    print(f"\n{C.BOLD}{C.CYAN}[{hora}] Iniciando Radar {etiqueta_modo} (12+ Plataformas en paralelo + Batch IA x{tam_lote})...{C.RESET}", flush=True)

    conn = preparar_db()
    descartados_no_tech = 0
    duplicados_sem = 0
    ya_vistos_n = 0
    evaluadas_ia = 0
    alertas_enviadas = 0
    tok_usados = 0
    tok_ahorrados = 0
    fallos_lote_seguidos = 0
    candidatas_nuevas: list[dict] = []

    try:
        filas_v = conn.execute("SELECT post_id, titulo_norm, titulo_palabras FROM vistos ORDER BY ts DESC LIMIT 3500").fetchall()
        vistos_ids = {r[0] for r in filas_v if r[0]}
        vistos_norms = {r[1] for r in filas_v if r[1]}
        recientes = [r[2] for r in filas_v[:300] if r[2]]

        ofertas, telemetria = recolectar_todo(cfg)
        registrar_salud_fuentes(conn, telemetria["detalle_fuentes"])

        try:
            ofertas_pro, metas_pro = recolectar_conectores_pro(cfg, persistir_salud=True)
            if ofertas_pro:
                ofertas.extend(ofertas_pro)
            if metas_pro:
                if "detalle_fuentes" in locals() and isinstance(locals()["detalle_fuentes"], list):
                    locals()["detalle_fuentes"].extend(metas_pro)
                elif "metas_fuentes" in locals() and isinstance(locals()["metas_fuentes"], list):
                    locals()["metas_fuentes"].extend(metas_pro)
        except Exception as _e_pro:
            log_evento(f"Aviso conectores Pro: {_e_pro}")

        pendientes_aegis = []
        for item in ofertas:
            pid = item["id"]
            tn = item["titulo_norm"]
            if pid in vistos_ids or (tn and tn in vistos_norms):
                ya_vistos_n += 1
                continue
            palabras = item.get("titulo_palabras", "")
            if palabras and any(similitud_jaccard(palabras, prev) >= 0.78 for prev in recientes):
                if not dry_run:
                    conn.execute("INSERT OR IGNORE INTO vistos (post_id, titulo_norm, titulo_palabras) VALUES (?, ?, ?)", (pid, tn, palabras))
                    conn.commit()
                vistos_ids.add(pid)
                if tn:
                    vistos_norms.add(tn)
                duplicados_sem += 1
                tok_ahorrados += 420
                continue
            pendientes_aegis.append(item)

        aegis = obtener_pipeline_aegis()
        candidatas_nuevas, resumen_aegis = aegis.evaluar_lote_ofertas(
            pendientes_aegis,
            cfg,
            registrar_dedup_rechazadas=(not dry_run),
            registrar_auditoria=(not dry_run),
        )
        descartados_no_tech += resumen_aegis["rechazadas"]
        tok_ahorrados += resumen_aegis["rechazadas"] * 420
        telemetria["aegis_resumen"] = resumen_aegis

        # Reparto equitativo entre plataformas antes de mandar a Gemini
        seleccionadas = mezclar_equitativamente(candidatas_nuevas, max_ia)
        candidatas_preview = [
            {
                "fuente": it["fuente"],
                "plataforma": it.get("plataforma", it["fuente"]),
                "tipo": it.get("tipo_trabajo", "freelance"),
                "titulo": it["titulo"][:90],
                "tech_score": it.get("tech_score", 0),
                "dinero": it.get("dinero_local", 0),
                "presupuesto": it.get("presupuesto_txt", ""),
                "comp": it.get("comp_txt", ""),
                "aegis_score": it.get("aegis_score", 0),
                "aegis_horas": it.get("aegis_horas", ""),
                "aegis_tarifa_eff": it.get("aegis_tarifa_eff", 0),
            }
            for it in seleccionadas
        ]

        if not dry_run and seleccionadas:
            aprendizaje = contexto_aprendizaje_crm(conn)
            for i in range(0, len(seleccionadas), tam_lote):
                lote = seleccionadas[i:i + tam_lote]
                items_ok, al_n, t_est = evaluar_lote_y_enviar(lote, cfg, conn=conn, modo_sonido=modo_sonido, aprendizaje=aprendizaje)
                tok_usados += t_est
                if items_ok:
                    fallos_lote_seguidos = 0
                    for it in items_ok:
                        conn.execute(
                            "INSERT OR IGNORE INTO vistos (post_id, titulo_norm, titulo_palabras) VALUES (?, ?, ?)",
                            (it["id"], it["titulo_norm"], it.get("titulo_palabras", "")),
                        )
                        aegis.registrar_vista_aprobada(it, cfg)
                        vistos_ids.add(it["id"])
                        if it["titulo_norm"]:
                            vistos_norms.add(it["titulo_norm"])
                        if it.get("titulo_palabras"):
                            recientes.append(it["titulo_palabras"])
                    conn.commit()
                    evaluadas_ia += len(items_ok)
                    alertas_enviadas += al_n
                else:
                    fallos_lote_seguidos += 1
                    if fallos_lote_seguidos >= 3:
                        log_evento("[!] Circuit Breaker IA activado (3 lotes fallidos)")
                        print(f"{C.RED}[!] Circuit Breaker IA: 3 lotes fallidos. Pausando resto del ciclo.{C.RESET}", flush=True)
                        break
                time.sleep(0.5)

        followups = 0 if dry_run else revisar_recordatorios_followup(conn, cfg)
        pre_desc = sum((telemetria.get("descartes_pre") or {}).values())
        total_desc = descartados_no_tech + duplicados_sem + telemetria.get("dup_memoria", 0) + pre_desc
        if not dry_run:
            registrar_metricas(
                conn,
                descartados=total_desc,
                ia=evaluadas_ia,
                alertas=alertas_enviadas,
                tok_usados=tok_usados,
                tok_ahorrados=tok_ahorrados + (pre_desc * 420),
            )

        dur = round(time.time() - t0, 1)
        f_ok = telemetria["fuentes_ok"]
        f_tot = telemetria["fuentes_total"]
        if dry_run:
            resumen_txt = f"DRY-RUN OMNI en {dur}s | Fuentes: {f_ok}/{f_tot} | Bruto: {telemetria['bruto']} | Nuevas tech: {len(candidatas_nuevas)} (Top {len(seleccionadas)}) | Bloqueados: {total_desc}"
        else:
            resumen_txt = f"Ciclo OMNI v13.0 en {dur}s | Fuentes: {f_ok}/{f_tot} | Filtrados: {total_desc} | IA: {evaluadas_ia} | Alertas: {alertas_enviadas}"
        log_evento(resumen_txt)
        print(f"{C.GREEN}{resumen_txt}{C.RESET}", flush=True)

        if dry_run:
            ag = telemetria.get("aegis_resumen") or {}
            if ag:
                desg = ", ".join(f"{k}:{v}" for k, v in sorted((ag.get("desglose") or {}).items()))
                print(f"{C.MAGENTA}[AEGIS-X | perfil={ag.get('perfil')}] {ag.get('evaluadas',0)} eval en {ag.get('tiempo_ms',0)}ms -> {ag.get('aprobadas',0)} aprobadas | {ag.get('rechazadas',0)} bloqueadas ({desg}){C.RESET}")
        if not dry_run:
            aegis.flush_todo()
        if dry_run and candidatas_preview:
            print(f"\n{C.BOLD}Top candidatas certificadas por AEGIS-X para Gemini:{C.RESET}")
            for c in candidatas_preview[:10]:
                print(f"  - [AEGIS {c.get('aegis_score',0):4.1f} | {c['plataforma']:<12} | {c['presupuesto'] or '$?'} | {c.get('aegis_horas','')}] {c['titulo']}")
            print()

        return {
            "dry_run": dry_run,
            "fuentes_ok": f_ok,
            "fuentes_total": f_tot,
            "bruto": telemetria["bruto"],
            "ya_vistos": ya_vistos_n,
            "descartados": total_desc,
            "descartes_pre": telemetria["descartes_pre"],
            "ia": evaluadas_ia,
            "alertas": alertas_enviadas,
            "followups": followups,
            "segundos": dur,
            "detalle_fuentes": telemetria["detalle_fuentes"],
            "candidatas_preview": candidatas_preview[:15],
            "aegis_resumen": telemetria.get("aegis_resumen") or {},
        }
    finally:
        conn.close()

def modo_sniper() -> None:
    cfg = cargar_config()
    intervalo = max(45, safe_int(cfg.get("intervalo_sniper_seg", 75), 75))
    print(f"\n{C.BOLD}{C.MAGENTA}=== MODO FRANCOTIRADOR OMNI-GRID v13.0 (Cada {intervalo}s + 12 Plataformas + Batch IA) ==={C.RESET}")
    print(f"{C.DIM}Minimiza esta ventana mientras usas tu PC. Presiona Ctrl+C para salir.{C.RESET}")
    ciclo_n = 0
    try:
        while True:
            ciclo_n += 1
            print(f"\n{C.DIM}--- Barrido OMNI #{ciclo_n} ---{C.RESET}")
            ejecutar_ciclo(modo_sonido=True)
            print(f"{C.DIM}Esperando {intervalo}s para el proximo barrido...{C.RESET}", flush=True)
            time.sleep(intervalo)
    except KeyboardInterrupt:
        print(f"\n{C.YELLOW}[*] Modo Francotirador detenido.{C.RESET}\n")

def imprimir_fuentes() -> None:
    conn = preparar_db()
    try:
        salud = obtener_salud_fuentes(conn)
        print(f"\n{C.BOLD}=== ESTADO DE PLATAFORMAS OMNI-GRID v13.0 ==={C.RESET}")
        if not salud:
            print("Aun no hay registros. Corre --dry-run primero.")
            return
        for s in salud:
            ic = f"{C.GREEN}OK {C.RESET}" if s["ok"] else f"{C.RED}ERR{C.RESET}"
            print(f"  [{ic}] {s['fuente']:<18} | {s['modo']:<16} | raw: {s['bruto']:3d} | tech: {s['tech']:2d} | {s['actualizado_ts']}")
        print()
    finally:
        conn.close()

if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        ejecutar_ciclo(modo_sonido=False, dry_run=True)
    elif "--fuentes" in sys.argv:
        imprimir_fuentes()
    elif "--test" in sys.argv:
        cfg_t = cargar_config()
        prueba = {
            "id": "test_omni_v13",
            "fuente": "Reddit",
            "plataforma": "Reddit",
            "tipo_trabajo": "freelance",
            "autor": "test_client",
            "titulo": "Simple Python script to merge CSV files into Excel ($300 USD)",
            "texto": "Looking for a clean Python script to extract product titles, variants, and prices from 5 Shopify stores into CSV.",
            "link": "https://www.freelancer.com/",
            "comp_txt": "🎯 SANGRE FRESCA (3m | 2 bids)",
            "prioridad_tag": "🐋 HIGH-TICKET · 🚨 TEST",
            "dinero_local": 300.0,
            "presupuesto_txt": "$300 USD",
            "origen": "freelancer",
        }
        evaluar_y_enviar(prueba, cfg_t, modo_sonido=True)
    elif "--sniper" in sys.argv:
        modo_sniper()
    elif "--resumen" in sys.argv:
        enviar_resumen_telegram()
    else:
        ejecutar_ciclo(modo_sonido=False)