from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from typing import Any

import requests

from titan_core.filtro_perfil_gemini import cargar_perfil_config, evaluar_aptitud_gemini_menor

SCHEMA_JUEZ_SQL = """
CREATE TABLE IF NOT EXISTS juez_ia_leads (
    hash_oferta TEXT PRIMARY KEY,
    lead_id INTEGER,
    titulo_original TEXT DEFAULT '',
    plataforma TEXT DEFAULT '',
    resumen_es TEXT DEFAULT '',
    suficiente_gemini_38_high INTEGER DEFAULT 0,
    veredicto TEXT DEFAULT 'NO_APTA',
    confianza INTEGER DEFAULT 0,
    nivel_dificultad TEXT DEFAULT 'alta',
    motivo_es TEXT DEFAULT '',
    pasos_sugeridos_es TEXT DEFAULT '',
    modelo_usado TEXT DEFAULT '',
    actualizado_ts DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_juez_ia_lead_id ON juez_ia_leads(lead_id);
"""

PROMPT_JUEZ_TEMPLATE = """Eres un auditor técnico estricto para un estudiante de 17 años SIN experiencia en programación/scripting que SOLO cuenta con Gemini 3.8 Flash en modo (High) para resolver tareas freelance.

Analiza esta oferta y responde ÚNICAMENTE con un objeto JSON válido (sin markdown ni texto extra) con estas claves exactas:
- "resumen_es": Traducción y explicación clara en español (máx 2 frases) de QUÉ necesita exactamente el cliente y qué entregable espera.
- "suficiente_gemini_38_high": true o false. Pon true SOLO si Gemini 3.8 Flash (High) puede producir una entrega funcional casi de un tirón sin experiencia en scripting (ej: script simple Python CSV/Excel/PDF, Google Sheets/Apps Script, landing page estática HTML/CSS/Tailwind, bot básico de Telegram/Discord, extensión simple o arreglo muy acotado). Pon false si requiere arquitectura compleja, repos grandes, DevOps/Cloud/Docker, C++/Rust/bajo nivel, apps móviles nativas, bypass anti-bot/Cloudflare, APIs empresariales complejas, entrevistas técnicas en vivo o requisitos legales/KYC/18+.
- "veredicto": "APTA" si suficiente_gemini_38_high es true, de lo contrario "NO_APTA".
- "nivel_dificultad": "baja", "media", "alta" o "imposible".
- "confianza": entero de 0 a 100.
- "motivo_es": 1 frase directa y honesta en español explicando por qué SÍ o por qué NO basta Gemini 3.8 Flash (High).
- "pasos_sugeridos_es": Si es APTA, 1 frase corta de cómo pedírselo a Gemini 3.8 Flash (High). Si es NO_APTA, deja "".

OFERTA A AUDITAR:
Plataforma: {plataforma}
Presupuesto: {presupuesto}
Título: {titulo}
Descripción: {cuerpo}
"""

def hash_oferta(titulo: str, cuerpo: str = "", plataforma: str = "") -> str:
    base = f"{(plataforma or '').strip().lower()}|{(titulo or '').strip().lower()}|{(cuerpo or '').strip()[:600].lower()}"
    return hashlib.sha256(base.encode("utf-8", errors="ignore")).hexdigest()[:32]

def asegurar_tabla_juez(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_JUEZ_SQL)

def _extraer_json(texto: str) -> dict[str, Any] | None:
    if not texto:
        return None
    s = texto.strip()
    if "```" in s:
        s = re.sub(r"```(?:json)?\s*|```", "", s, flags=re.IGNORECASE).strip()
    try:
        d = json.loads(s)
        if isinstance(d, dict):
            return d
    except Exception:
        pass
    dec = json.JSONDecoder()
    for pos in [m.start() for m in re.finditer(r"\{", s)]:
        try:
            obj, _ = dec.raw_decode(s[pos:])
            if isinstance(obj, dict) and ("resumen_es" in obj or "suficiente_gemini_38_high" in obj or "veredicto" in obj):
                return obj
        except Exception:
            continue
    return None

def _llamar_gemini_json(prompt: str, timeout: int = 30) -> tuple[dict[str, Any] | None, str]:
    try:
        import core_ia
        core_ia.cargar_env()
        modelos = list(getattr(core_ia, "MODELOS_PREFERIDOS", []))
    except Exception:
        modelos = []
    if not modelos:
        modelos = ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-flash-latest"]
    api_key = (os.environ.get("GEMINI_API_KEY_FREE") or os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        return None, ""
    for modelo in modelos:
        url = f"[https://generativelanguage.googleapis.com/v1beta/models/](https://generativelanguage.googleapis.com/v1beta/models/){modelo}:generateContent?key={api_key}"
        for usar_mime in (True, False):
            gen_cfg: dict[str, Any] = {"temperature": 0.15}
            if usar_mime:
                gen_cfg["responseMimeType"] = "application/json"
            payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": gen_cfg}
            try:
                r = requests.post(url, json=payload, timeout=timeout)
                if r.status_code == 400 and usar_mime:
                    continue
                if r.status_code != 200:
                    break
                cands = r.json().get("candidates") or []
                if not cands:
                    break
                parts = ((cands[0].get("content") or {}).get("parts") or [])
                visibles = [str(pt.get("text") or "") for pt in parts if not pt.get("thought") and pt.get("text")]
                for chunk in reversed(visibles):
                    parsed = _extraer_json(chunk)
                    if parsed:
                        return parsed, f"gemini:{modelo}"
                parsed = _extraer_json("\n".join(visibles))
                if parsed:
                    return parsed, f"gemini:{modelo}"
                break
            except Exception:
                break
    return None, ""

def _llamar_ollama_json(prompt: str, timeout: int = 25) -> tuple[dict[str, Any] | None, str]:
    try:
        import core_ia
        cfg = core_ia.cargar_config()
    except Exception:
        cfg = {}
    url = str(cfg.get("ollama_url") or "[http://127.0.0.1:11434](http://127.0.0.1:11434)").rstrip("/")
    modelo = str(cfg.get("ollama_modelo") or "qwen3:8b")
    try:
        r = requests.post(
            f"{url}/api/generate",
            json={"model": modelo, "prompt": prompt, "stream": False, "format": "json", "options": {"temperature": 0.15}},
            timeout=timeout,
        )
        if r.status_code == 200:
            parsed = _extraer_json(str(r.json().get("response") or ""))
            if parsed:
                return parsed, f"ollama:{modelo}"
    except Exception:
        pass
    return None, ""

def _db_path_default() -> str:
    try:
        from titan_core.db_engine import DEFAULT_DB_PATH
        return str(DEFAULT_DB_PATH)
    except Exception:
        return os.path.abspath("estado_radar_v4.db")

def _normalizar_resultado(
    raw: dict[str, Any] | None,
    *,
    titulo: str,
    cuerpo: str,
    plataforma: str,
    modelo_usado: str,
    reglas: dict[str, Any],
) -> dict[str, Any]:
    if raw is None:
        bloqueado = bool(reglas.get("bloqueado"))
        return {
            "resumen_es": f"Oferta en {plataforma or 'web'}: {titulo[:180]} (sin conexión IA para traducir).",
            "suficiente_gemini_38_high": not bloqueado,
            "veredicto": "NO_APTA" if bloqueado else "REVISAR",
            "confianza": 70 if bloqueado else 45,
            "nivel_dificultad": "alta" if bloqueado else "media",
            "motivo_es": reglas.get("motivo") or "Pendiente de evaluación IA (modo offline).",
            "pasos_sugeridos_es": "" if bloqueado else "Usa el botón Verificar IA cuando tengas conexión.",
            "modelo_usado": "heuristica_offline",
        }

    suf = bool(raw.get("suficiente_gemini_38_high", False))
    resumen = str(raw.get("resumen_es") or "").strip() or titulo[:200]
    motivo = str(raw.get("motivo_es") or "").strip()
    pasos = str(raw.get("pasos_sugeridos_es") or "").strip()
    dif = str(raw.get("nivel_dificultad") or ("media" if suf else "alta")).strip().lower()
    if dif not in ("baja", "media", "alta", "imposible"):
        dif = "media" if suf else "alta"
    try:
        conf = max(0, min(100, int(raw.get("confianza", 75))))
    except Exception:
        conf = 75

    # Doble candado de seguridad: si el filtro duro detecto KYC/18+/complejidad extrema, nunca se aprueba
    if reglas.get("bloqueado"):
        suf = False
        dif = "imposible" if dif == "baja" else dif
        mot_regla = str(reglas.get("motivo") or "").strip()
        motivo = f"{mot_regla}. {motivo}".strip(". ") if mot_regla else motivo
        pasos = ""

    return {
        "resumen_es": resumen[:420],
        "suficiente_gemini_38_high": suf,
        "veredicto": "APTA" if suf else "NO_APTA",
        "confianza": conf,
        "nivel_dificultad": dif,
        "motivo_es": (motivo or ("Apta para Gemini 3.8 Flash (High)." if suf else "Excede el alcance seguro de IA-solo."))[:360],
        "pasos_sugeridos_es": (pasos if suf else "")[:260],
        "modelo_usado": modelo_usado or "ia",
    }

def evaluar_y_traducir_oferta(
    titulo: str,
    cuerpo: str = "",
    plataforma: str = "",
    presupuesto: str = "",
    *,
    lead_id: int | None = None,
    db_path: str | None = None,
    usar_ia: bool = True,
    forzar: bool = False,
) -> dict[str, Any]:
    path = db_path or _db_path_default()
    h = hash_oferta(titulo, cuerpo, plataforma)
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        asegurar_tabla_juez(conn)
        if not forzar:
            row = conn.execute("SELECT * FROM juez_ia_leads WHERE hash_oferta = ?", (h,)).fetchone()
            if row is None and lead_id is not None:
                row = conn.execute("SELECT * FROM juez_ia_leads WHERE lead_id = ?", (int(lead_id),)).fetchone()
            if row is not None and (not usar_ia or row["modelo_usado"] != "heuristica_offline"):
                d = dict(row)
                d["suficiente_gemini_38_high"] = bool(d["suficiente_gemini_38_high"])
                d["desde_cache"] = True
                if lead_id is not None and d.get("lead_id") != int(lead_id):
                    with conn:
                        conn.execute("UPDATE juez_ia_leads SET lead_id = ? WHERE hash_oferta = ?", (int(lead_id), d["hash_oferta"]))
                    d["lead_id"] = int(lead_id)
                return d

        reglas = evaluar_aptitud_gemini_menor(titulo=titulo, cuerpo=cuerpo, plataforma=plataforma)
        raw, modelo = None, ""
        offline_env = os.environ.get("TITAN_JUEZ_OFFLINE") == "1"
        if usar_ia and not offline_env:
            prompt = PROMPT_JUEZ_TEMPLATE.format(
                plataforma=plataforma or "No especificada",
                presupuesto=presupuesto or "No especificado",
                titulo=(titulo or "").strip()[:300],
                cuerpo=(cuerpo or "").strip()[:1400] or "(Sin descripción adicional, evalúa por título y contexto)",
            )
            raw, modelo = _llamar_gemini_json(prompt)
            if raw is None:
                raw, modelo = _llamar_ollama_json(prompt)

        res = _normalizar_resultado(raw, titulo=titulo, cuerpo=cuerpo, plataforma=plataforma, modelo_usado=modelo, reglas=reglas)
        res["hash_oferta"] = h
        res["lead_id"] = int(lead_id) if lead_id is not None else None
        res["titulo_original"] = (titulo or "")[:300]
        res["plataforma"] = plataforma or ""
        res["desde_cache"] = False

        with conn:
            conn.execute(
                """
                INSERT INTO juez_ia_leads (
                    hash_oferta, lead_id, titulo_original, plataforma, resumen_es,
                    suficiente_gemini_38_high, veredicto, confianza, nivel_dificultad,
                    motivo_es, pasos_sugeridos_es, modelo_usado, actualizado_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(hash_oferta) DO UPDATE SET
                    lead_id = COALESCE(excluded.lead_id, juez_ia_leads.lead_id),
                    resumen_es = excluded.resumen_es,
                    suficiente_gemini_38_high = excluded.suficiente_gemini_38_high,
                    veredicto = excluded.veredicto,
                    confianza = excluded.confianza,
                    nivel_dificultad = excluded.nivel_dificultad,
                    motivo_es = excluded.motivo_es,
                    pasos_sugeridos_es = excluded.pasos_sugeridos_es,
                    modelo_usado = excluded.modelo_usado,
                    actualizado_ts = CURRENT_TIMESTAMP
                """,
                (
                    h, res["lead_id"], res["titulo_original"], res["plataforma"], res["resumen_es"],
                    1 if res["suficiente_gemini_38_high"] else 0, res["veredicto"], res["confianza"],
                    res["nivel_dificultad"], res["motivo_es"], res["pasos_sugeridos_es"], res["modelo_usado"],
                ),
            )
        return res
    finally:
        conn.close()

def obtener_mapa_juez(db_path: str | None = None) -> dict[int, dict[str, Any]]:
    path = db_path or _db_path_default()
    if not os.path.isfile(path):
        return {}
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        asegurar_tabla_juez(conn)
        rows = conn.execute("SELECT * FROM juez_ia_leads WHERE lead_id IS NOT NULL").fetchall()
        out: dict[int, dict[str, Any]] = {}
        for r in rows:
            d = dict(r)
            d["suficiente_gemini_38_high"] = bool(d["suficiente_gemini_38_high"])
            out[int(d["lead_id"])] = d
        return out
    finally:
        conn.close()

def verificar_todas_en_db(
    db_path: str | None = None,
    *,
    forzar: bool = False,
    usar_ia: bool = True,
    marcar_no_aptas: bool = False,
    limite: int = 50,
) -> dict[str, Any]:
    path = db_path or _db_path_default()
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        asegurar_tabla_juez(conn)
        leads = conn.execute(
            "SELECT id, titulo, plataforma, presupuesto, notas, estado FROM leads ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limite), 200)),),
        ).fetchall()
    finally:
        conn.close()

    resultados = []
    aptas, no_aptas, cacheadas = 0, 0, 0
    for row in leads:
        r = evaluar_y_traducir_oferta(
            titulo=str(row["titulo"] or ""),
            cuerpo=str(row["notas"] or ""),
            plataforma=str(row["plataforma"] or ""),
            presupuesto=str(row["presupuesto"] or ""),
            lead_id=int(row["id"]),
            db_path=path,
            usar_ia=usar_ia,
            forzar=forzar,
        )
        if r.get("desde_cache"):
            cacheadas += 1
        if r.get("suficiente_gemini_38_high"):
            aptas += 1
        else:
            no_aptas += 1
            if marcar_no_aptas and str(row["estado"] or "").lower() in ("", "nuevo"):
                c2 = sqlite3.connect(path, timeout=10)
                with c2:
                    c2.execute("UPDATE leads SET estado = 'descartado' WHERE id = ?", (int(row["id"]),))
                c2.close()
        resultados.append(r)

    return {
        "ok": True,
        "total_verificadas": len(resultados),
        "aptas": aptas,
        "no_aptas": no_aptas,
        "desde_cache": cacheadas,
        "resultados": resultados,
    }


def registrar_rutas_juez_ia(router: Any, svc: Any = None) -> None:
    from titan_core.radar_cleaner import _leer_json_req, _montar_ruta

    def _dbp() -> str | None:
        return getattr(getattr(svc, "db", None), "db_path", None) if svc is not None else None

    def _mapa(req: Any) -> dict[str, Any]:
        mp = obtener_mapa_juez(db_path=_dbp())
        return {"ok": True, "total": len(mp), "mapa": {str(k): v for k, v in mp.items()}}

    def _verificar_todas(req: Any) -> dict[str, Any]:
        body = _leer_json_req(req)
        lim = int(body.get("limite") or 50) if str(body.get("limite", 50)).isdigit() else 50
        return verificar_todas_en_db(
            db_path=_dbp(),
            forzar=bool(body.get("forzar", False)),
            usar_ia=bool(body.get("usar_ia", True)),
            marcar_no_aptas=bool(body.get("marcar_no_aptas", False)),
            limite=lim,
        )

    def _verificar_una(req: Any) -> dict[str, Any]:
        body = _leer_json_req(req)
        lid = body.get("lead_id")
        titulo = str(body.get("titulo") or "")
        cuerpo = str(body.get("cuerpo") or "")
        plataforma = str(body.get("plataforma") or "")
        presupuesto = str(body.get("presupuesto") or "")
        dbp = _dbp()
        if lid is not None and not titulo:
            conn = sqlite3.connect(dbp or _db_path_default(), timeout=10)
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute("SELECT titulo, notas, plataforma, presupuesto FROM leads WHERE id = ?", (int(lid),)).fetchone()
                if not row:
                    return {"ok": False, "error": f"Lead {lid} no encontrado"}
                titulo, cuerpo, plataforma, presupuesto = str(row["titulo"] or ""), str(row["notas"] or ""), str(row["plataforma"] or ""), str(row["presupuesto"] or "")
            finally:
                conn.close()
        res = evaluar_y_traducir_oferta(
            titulo=titulo, cuerpo=cuerpo, plataforma=plataforma, presupuesto=presupuesto,
            lead_id=int(lid) if lid is not None else None, db_path=dbp,
            usar_ia=bool(body.get("usar_ia", True)), forzar=bool(body.get("forzar", False)),
        )
        return {"ok": True, "resultado": res}

    _montar_ruta(router, "GET", "/api/v2/juez-ia/mapa", _mapa, "juez_ia_v2_mapa")
    _montar_ruta(router, "POST", "/api/v2/juez-ia/verificar-todas", _verificar_todas, "juez_ia_v2_todas")
    _montar_ruta(router, "POST", "/api/v2/juez-ia/verificar-una", _verificar_una, "juez_ia_v2_una")

