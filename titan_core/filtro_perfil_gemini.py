from __future__ import annotations
import json, os, re
from typing import Any

DEFAULT_PERFIL_CONFIG: dict[str, Any] = {
    "activo": True,
    "nombre": "gemini_38_flash_high_menor",
    "modelo_ia": "gemini-3.8-flash-high",
    "bloquear_kyc_y_edad": True,
    "bloquear_entrevistas_en_vivo": True,
    "bloquear_plataformas_kyc": True,
    "plataformas_kyc": ["freelancer.com", "freelancer", "upwork", "toptal", "fiverr"],
    "presupuesto_max_usd": 600,
    "max_bids_permitidos": 30,
    "min_score_aprobado": 6,
}

RX_KYC_EDAD = re.compile(
    r"\b(18\+|21\+|must be 18|over 18|legal age|kyc|id verification|verify identity|"
    r"w-?2|w-?9|ssn|tax id|ein required|llc required|corporate entity|us citizen|"
    r"eu citizen|uk citizen|work authorization|authorized to work|background check|"
    r"drug test|sign nda|legal contract|employment contract|full[- ]?time|part[- ]?time|"
    r"on[- ]?site|onsite|hybrid role|w2 only|long[- ]?term retainer|salary|per year|annual salary)\b",
    re.IGNORECASE,
)
RX_ENTREVISTAS = re.compile(
    r"\b(live coding|technical interview|coding interview|video interview|phone interview|"
    r"zoom interview|daily standup|scrum meetings|pair programming|camera on|screen share interview)\b",
    re.IGNORECASE,
)
RX_COMPLEJIDAD_EXTREMA = re.compile(
    r"\b(senior|sr\.?\s+(?:dev|eng|python|ml|ai|back|front|full)|lead engineer|staff engineer|"
    r"principal engineer|tech lead|architect|cto|devops|sre|mlops|kubernetes|k8s|terraform|"
    r"ansible|helm|openshift|aws migration|gcp migration|azure migration|production cluster|"
    r"0\.5[- ]?ulp|ulp|fma|ieee[- ]?754|packet frame|frame boundary|zero[- ]?copy|kernel|"
    r"firmware|embedded|fpga|verilog|vhdl|assembly|x86|arm64|compiler|llvm|bytecode|wasm runtime|"
    r"decompile|reverse engineer|c\+\+|rust\b|golang|zig\b|haskell|erlang|elixir|scala|cobol|"
    r"dynamicAnchor|subschema|json stream chunk|ast engine|lock[- ]?free|race condition|"
    r"smart contract audit|solidity audit|penetration test|pentest|exploit|cloudflare bypass|"
    r"akamai|datadome|perimeterx|captcha bypass|anti[- ]?bot|anti[- ]?cheat|visa portal|bls visa|"
    r"vfs global|government portal|bank login|ios app store|swiftui|kotlin native|"
    r"react native production|flutter production|sap\b|salesforce|workday|netsuite|dynamics 365|"
    r"erp migration|saas from scratch|uber clone|airbnb clone|marketplace from scratch|"
    r"train(?:ing)? (?:a )?(?:llm|model)|fine[- ]?tun|pytorch distributed|cuda kernel|"
    r"[3-9]\+?\s*years? (?:of )?experience|5\+?\s*years)\b",
    re.IGNORECASE,
)
RX_GEMINI_FIT = re.compile(
    r"\b(google sheets?|apps? script|excel|vba|macro|csv|json|xml|yaml|pdf to excel|merge pdf|"
    r"extract pdf|rename files|data clean(?:ing|up)?|airtable|notion|zapier|make\.com|n8n|"
    r"landing page|static site|html|css|tailwind|single[- ]?page|portfolio|calculator|widget|"
    r"form|chrome extension|userscript|tampermonkey|telegram bot|discord bot|webhook|rss|"
    r"simple script|python script|small script|quick script|automation script|csv export|"
    r"scraper|markdown|documentation|readme|quick fix|small task|one[- ]?time|simple tool)\b",
    re.IGNORECASE,
)
RX_BIDS = re.compile(r"\b(\d{1,4})\s*(?:bids?|proposals?|ofertas?)\b", re.IGNORECASE)
RX_MONEY = re.compile(r"(?:\$|usd\s*)(\d{2,6}(?:,\d{3})?)(?:\s*(?:-|to)\s*(?:\$|usd\s*)?(\d{2,6}(?:,\d{3})?))?", re.IGNORECASE)
_CFG_CACHE: tuple[float, dict[str, Any]] = (0.0, dict(DEFAULT_PERFIL_CONFIG))

def _ruta_config() -> str:
    try:
        from titan_core.db_engine import ROOT_DIR
        return os.path.join(ROOT_DIR, "config.json")
    except Exception:
        return os.path.abspath("config.json")

def cargar_perfil_config() -> dict[str, Any]:
    global _CFG_CACHE
    path = _ruta_config()
    try: mtime = os.path.getmtime(path)
    except OSError: return dict(DEFAULT_PERFIL_CONFIG)
    if mtime == _CFG_CACHE[0]: return _CFG_CACHE[1]
    cfg = dict(DEFAULT_PERFIL_CONFIG)
    try:
        with open(path, "r", encoding="utf-8") as f: raw = json.load(f)
        if isinstance(raw, dict) and isinstance(raw.get("perfil_ia_usuario"), dict): cfg.update(raw["perfil_ia_usuario"])
    except Exception: pass
    _CFG_CACHE = (mtime, cfg)
    return cfg

def guardar_perfil_config(cambios: dict[str, Any]) -> dict[str, Any]:
    global _CFG_CACHE
    path = _ruta_config()
    raw: dict[str, Any] = {}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f: data = json.load(f)
            if isinstance(data, dict): raw = data
        except Exception: raw = {}
    actual = dict(DEFAULT_PERFIL_CONFIG)
    if isinstance(raw.get("perfil_ia_usuario"), dict): actual.update(raw["perfil_ia_usuario"])
    for k, v in cambios.items():
        if k in DEFAULT_PERFIL_CONFIG:
            actual[k] = max(0, int(v)) if isinstance(DEFAULT_PERFIL_CONFIG[k], int) and not isinstance(DEFAULT_PERFIL_CONFIG[k], bool) and str(v).isdigit() else (bool(v) if isinstance(DEFAULT_PERFIL_CONFIG[k], bool) else v)
    raw["perfil_ia_usuario"] = actual
    with open(path, "w", encoding="utf-8", newline="\n") as f: json.dump(raw, f, indent=2, ensure_ascii=False)
    _CFG_CACHE = (0.0, actual)
    return actual

def evaluar_aptitud_gemini_menor(titulo: str = "", cuerpo: str = "", plataforma: str = "", ctx: Any = None, config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config if isinstance(config, dict) else cargar_perfil_config()
    if not cfg.get("activo", True):
        return {"bloqueado": False, "motivo": "", "motivos": [], "delta_score": 0, "etiquetas": [], "hits_fit": []}
    plat = str(plataforma or "").strip()
    if not plat and ctx is not None:
        plat = str(getattr(ctx, "plataforma", "") or (ctx.get("plataforma", "") if isinstance(ctx, dict) else ""))
    plat_low, texto, motivos = plat.lower(), f"{titulo or ''}\n{cuerpo or ''}", []
    if cfg.get("bloquear_plataformas_kyc", True) and plat_low:
        if any(pb and pb in plat_low for pb in [str(p).lower() for p in cfg.get("plataformas_kyc", [])]):
            motivos.append(f"Plataforma con KYC 18+ estricto ({plat})")
    if cfg.get("bloquear_kyc_y_edad", True):
        m = RX_KYC_EDAD.search(texto)
        if m: motivos.append(f"Requiere 18+/KYC/contrato ({m.group(0)})")
    if cfg.get("bloquear_entrevistas_en_vivo", True):
        m = RX_ENTREVISTAS.search(texto)
        if m: motivos.append(f"Exige entrevista en vivo ({m.group(0)})")
    m_c = RX_COMPLEJIDAD_EXTREMA.search(texto)
    if m_c: motivos.append(f"Complejidad alta no apta IA-solo ({m_c.group(0)})")
    max_bids = int(cfg.get("max_bids_permitidos", 30) or 0)
    if max_bids > 0:
        m_b = RX_BIDS.search(texto)
        if m_b and int(m_b.group(1)) > max_bids: motivos.append(f"Competencia saturada ({m_b.group(1)} bids)")
    max_usd = int(cfg.get("presupuesto_max_usd", 600) or 0)
    if max_usd > 0:
        montos = [int(g.replace(",", "")) for m in RX_MONEY.finditer(texto) for g in (m.group(1), m.group(2)) if g]
        if montos and min(montos) > max_usd: motivos.append(f"Presupuesto complejo (${min(montos)} > ${max_usd})")
    if motivos:
        return {"bloqueado": True, "motivo": " | ".join(motivos[:2]), "motivos": motivos, "delta_score": -6, "etiquetas": ["BLOQUEADO-PERFIL-IA"], "hits_fit": []}
    hits = sorted({m.group(0).lower() for m in RX_GEMINI_FIT.finditer(texto)})
    delta = 2 if len(hits) >= 2 else (1 if len(hits) == 1 else 0)
    etiquetas = ["GEMINI-3.8-IDEAL"] if delta == 2 else (["GEMINI-3.8-APTO"] if delta == 1 else [])
    return {"bloqueado": False, "motivo": "", "motivos": [], "delta_score": delta, "etiquetas": etiquetas, "hits_fit": hits[:6]}

def _set_s(obj: Any, k: str, v: Any) -> None:
    if isinstance(obj, dict): obj[k] = v; return
    try: setattr(obj, k, v)
    except Exception:
        try: object.__setattr__(obj, k, v)
        except Exception: pass

def _get_s(obj: Any, k: str, d: Any = None) -> Any:
    return obj.get(k, d) if isinstance(obj, dict) else getattr(obj, k, d)

def aplicar_perfil_a_veredicto(veredicto: Any, *, titulo: str = "", cuerpo: str = "", plataforma: str = "", ctx: Any = None) -> Any:
    if veredicto is None or not bool(_get_s(veredicto, "aprobado", False)): return veredicto
    res = evaluar_aptitud_gemini_menor(titulo=titulo, cuerpo=cuerpo, plataforma=plataforma, ctx=ctx)
    for ft in ("etiquetas", "tags", "senales", "badges"):
        cur = _get_s(veredicto, ft, None)
        if isinstance(cur, list):
            for et in res["etiquetas"]:
                if et not in cur: cur.append(et)
            break
    if res["bloqueado"]:
        _set_s(veredicto, "aprobado", False)
        for fs in ("score", "score_final"):
            sc = _get_s(veredicto, fs, None)
            if isinstance(sc, (int, float)): _set_s(veredicto, fs, max(1, min(int(sc), 3)))
        mot = f"[Perfil Gemini 3.8 + Menor] {res['motivo']}"
        for fr in ("motivo_rechazo", "razon", "motivo", "decision_detalle"):
            if (isinstance(veredicto, dict) and fr in veredicto) or hasattr(veredicto, fr): _set_s(veredicto, fr, mot)
        for fl in ("motivos", "razones", "banderas_rojas"):
            cur = _get_s(veredicto, fl, None)
            if isinstance(cur, list): cur.append(mot); break
        return veredicto
    if res["delta_score"] > 0:
        for fs in ("score", "score_final"):
            sc = _get_s(veredicto, fs, None)
            if isinstance(sc, (int, float)): _set_s(veredicto, fs, min(10, int(round(sc)) + int(res["delta_score"])))
    return veredicto


def registrar_rutas_perfil_ia(router: Any, svc: Any = None) -> None:
    from titan_core.radar_cleaner import _leer_json_req, _montar_ruta

    def _get_cfg(req: Any) -> dict[str, Any]:
        return {"ok": True, "perfil": cargar_perfil_config()}

    def _set_cfg(req: Any) -> dict[str, Any]:
        body = _leer_json_req(req)
        nuevo = guardar_perfil_config(body)
        if svc is not None and getattr(svc, "aegis", None) is not None:
            vc = getattr(svc.aegis, "verdict_cache", None)
            if vc is not None and hasattr(vc, "limpiar"):
                try: vc.limpiar()
                except Exception: pass
        return {"ok": True, "perfil": nuevo}

    def _probar(req: Any) -> dict[str, Any]:
        body = _leer_json_req(req)
        res = evaluar_aptitud_gemini_menor(
            titulo=str(body.get("titulo") or ""),
            cuerpo=str(body.get("cuerpo") or ""),
            plataforma=str(body.get("plataforma") or ""),
        )
        return {"ok": True, "resultado": res, "perfil": cargar_perfil_config()}

    _montar_ruta(router, "GET", "/api/v2/perfil-ia", _get_cfg, "perfil_ia_v2_get")
    _montar_ruta(router, "POST", "/api/v2/perfil-ia", _set_cfg, "perfil_ia_v2_set")
    _montar_ruta(router, "POST", "/api/v2/perfil-ia/probar", _probar, "perfil_ia_v2_probar")
