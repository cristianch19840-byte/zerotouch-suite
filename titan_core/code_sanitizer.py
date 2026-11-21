from __future__ import annotations

import ast
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from titan_core.sandbox_runner import MAPA_MODULO_A_PIP, STDLIB_MODULOS

MODULOS_INTERNOS_PROYECTO = {
    "titan_core", "core_ia", "modulo_a_radar_whop", "modulo_b_ejecutor",
    "modulo_c_whop", "modulo_d_marketing", "license_guard",
}

# Patrones de secretos de alta precision
PATRONES_SECRETO: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("GEMINI_API_KEY", "API Key de Google/Gemini", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,45}\b")),
    ("OPENAI_API_KEY", "API Key de OpenAI", re.compile(r"\bsk-(?:proj-)?[0-9A-Za-z_\-]{24,}\b")),
    ("ANTHROPIC_API_KEY", "API Key de Anthropic", re.compile(r"\bsk-ant-[0-9A-Za-z_\-]{24,}\b")),
    ("GITHUB_TOKEN", "Token personal de GitHub", re.compile(r"\b(?:ghp_[0-9A-Za-z]{30,}|github_pat_[0-9A-Za-z_]{30,})\b")),
    ("TELEGRAM_TOKEN", "Token de Bot de Telegram", re.compile(r"\b\d{8,11}:[A-Za-z0-9_\-]{30,45}\b")),
    ("STRIPE_SECRET_KEY", "Clave secreta de Stripe", re.compile(r"\b(?:sk|rk)_(?:live|test)_[0-9A-Za-z]{20,}\b")),
    ("AWS_ACCESS_KEY", "Clave de acceso AWS", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("SLACK_TOKEN", "Token de Slack", re.compile(r"\bxox[baprs]-[0-9A-Za-z\-]{18,}\b")),
    ("DISCORD_WEBHOOK_URL", "Webhook privado de Discord", re.compile(r"https?://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_\-]+", re.IGNORECASE)),
)

REGEX_RUTA_PERSONAL = re.compile(r"^(?:[A-Za-z]:[\\/](?:Users|Usuarios)[\\/][^\\/]+|/(?:Users|home)/[^/]+)", re.IGNORECASE)
REGEX_EMAIL_PRIVADO = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
REGEX_VAR_SENSIBLE = re.compile(
    r"(?:API_?KEY|TOKEN|SECRET|PASS(?:WORD)?|WEBHOOK|CHAT_?ID|CLIENT_?ID|CLIENT_?SECRET|AUTH|PROXY_?URL|COOKIE)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class HallazgoSanitizacion:
    tipo: str
    variable_config: str
    linea: int
    descripcion: str
    muestra_ofuscada: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "tipo": self.tipo,
            "variable_config": self.variable_config,
            "linea": self.linea,
            "descripcion": self.descripcion,
            "muestra_ofuscada": self.muestra_ofuscada,
        }


@dataclass(slots=True)
class ReporteSanitizacion:
    ast_valido: bool
    codigo_limpio: str
    hallazgos: list[HallazgoSanitizacion] = field(default_factory=list)
    variables_config: dict[str, str] = field(default_factory=dict)
    requisitos_pip: list[str] = field(default_factory=list)
    imports_stdlib: list[str] = field(default_factory=list)
    error_sintaxis: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ast_valido": self.ast_valido,
            "total_secretos_removidos": len(self.hallazgos),
            "hallazgos": [h.to_dict() for h in self.hallazgos],
            "variables_config": self.variables_config,
            "requisitos_pip": self.requisitos_pip,
            "imports_stdlib": self.imports_stdlib[:20],
            "error_sintaxis": self.error_sintaxis,
        }


def _entropia(s: str) -> float:
    if not s:
        return 0.0
    n = len(s)
    c = Counter(s)
    return -sum((cnt / n) * math.log2(cnt / n) for cnt in c.values())


def _ofuscar_muestra(s: str) -> str:
    if len(s) <= 8:
        return "***"
    return f"{s[:4]}...{s[-3:]}"


def _construir_mapa_offsets_linea(codigo: str) -> tuple[list[int], list[bytes]]:
    lineas_txt = codigo.splitlines(keepends=True)
    offsets: list[int] = []
    lineas_bytes: list[bytes] = []
    pos = 0
    for ln in lineas_txt:
        offsets.append(pos)
        lineas_bytes.append(ln.encode("utf-8"))
        pos += len(ln)
    return offsets, lineas_bytes


def _pos_ast_a_char_idx(lineno: int, col_byte: int, offsets: list[int], lineas_bytes: list[bytes]) -> int:
    idx_ln = lineno - 1
    if idx_ln < 0 or idx_ln >= len(offsets):
        return 0
    pref_chars = len(lineas_bytes[idx_ln][:col_byte].decode("utf-8", errors="ignore"))
    return offsets[idx_ln] + pref_chars


def _nombre_var_desde_objetivo(target: ast.AST) -> str:
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return ""


def _normalizar_clave_cfg(nombre: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (nombre or "setting").strip()).strip("_").lower()
    return s[:48] or "setting"


class CodeSanitizer:
    """
    Sanitizador Forense AST para comercializacion de scripts Python:
    - Detecta y neutraliza secretos (API keys, tokens, webhooks, rutas C:\\Users\\..., emails privados)
    - Reemplaza literales sensibles por lookups seguros _zt_cfg('clave', 'ENV_VAR', default)
    - Respeta UTF-8 exacto en offsets AST (inmune a acentos/emojis en comentarios)
    - Extrae automaticamente requisitos PIP terceros para requirements.txt
    - Valida AST final tras la reescritura
    """

    HELPER_CONFIG = '''# --- ZeroTouch Commercial Runtime Config Loader ---
import json as _zt_json
import os as _zt_os

def _zt_load_cfg() -> dict:
    p = _zt_os.path.join(_zt_os.path.dirname(_zt_os.path.abspath(__file__)), "config.json")
    if _zt_os.path.isfile(p):
        try:
            with open(p, "r", encoding="utf-8") as _f:
                data = _zt_json.load(_f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}

_ZT_CFG = _zt_load_cfg()

def _zt_cfg(key: str, env_name: str, default: str = "") -> str:
    return str(_zt_os.getenv(env_name) or _ZT_CFG.get(key) or default)
# --------------------------------------------------
'''

    def sanitizar(self, codigo: str) -> ReporteSanitizacion:
        raw = str(codigo or "")
        try:
            tree = ast.parse(raw)
        except SyntaxError as e:
            return ReporteSanitizacion(
                ast_valido=False,
                codigo_limpio=raw,
                error_sintaxis=f"SyntaxError linea {e.lineno}: {e.msg}",
            )

        # 1. Extraer imports -> separar stdlib vs paquetes PIP de terceros
        mods_terceros: set[str] = set()
        mods_stdlib: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for al in node.names:
                    raiz = al.name.split(".", 1)[0]
                    if raiz in STDLIB_MODULOS:
                        mods_stdlib.add(raiz)
                    elif raiz not in MODULOS_INTERNOS_PROYECTO:
                        mods_terceros.add(MAPA_MODULO_A_PIP.get(raiz, raiz))
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    raiz = node.module.split(".", 1)[0]
                    if raiz in STDLIB_MODULOS:
                        mods_stdlib.add(raiz)
                    elif raiz not in MODULOS_INTERNOS_PROYECTO:
                        mods_terceros.add(MAPA_MODULO_A_PIP.get(raiz, raiz))

        # 2. Construir mapa de padres para ignorar docstrings y sub-nodos de JoinedStr (f-strings)
        parent_map: dict[int, ast.AST] = {}
        docstrings_ids: set[int] = set()
        for parent in ast.walk(tree):
            if isinstance(parent, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if parent.body and isinstance(parent.body[0], ast.Expr) and isinstance(parent.body[0].value, ast.Constant):
                    docstrings_ids.add(id(parent.body[0].value))
            for child in ast.iter_child_nodes(parent):
                parent_map[id(child)] = parent

        def _en_fstring(n: ast.AST) -> bool:
            cur: ast.AST | None = n
            while cur is not None:
                if isinstance(cur, ast.JoinedStr):
                    return True
                cur = parent_map.get(id(cur))
            return False

        def _contexto_variable(n: ast.AST) -> str:
            p = parent_map.get(id(n))
            if isinstance(p, ast.Assign) and p.targets:
                return _nombre_var_desde_objetivo(p.targets[0])
            if isinstance(p, ast.AnnAssign):
                return _nombre_var_desde_objetivo(p.target)
            if isinstance(p, ast.keyword) and p.arg:
                return p.arg
            if isinstance(p, ast.Dict):
                for k, v in zip(p.keys, p.values):
                    if v is n and isinstance(k, ast.Constant) and isinstance(k.value, str):
                        return k.value
            return ""

        offsets, lineas_bytes = _construir_mapa_offsets_linea(raw)
        reemplazos: list[tuple[int, int, str]] = []
        hallazgos: list[HallazgoSanitizacion] = []
        vars_cfg: dict[str, str] = {}

        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if id(node) in docstrings_ids or _en_fstring(node):
                continue
            if node.lineno is None or node.end_lineno is None or node.col_offset is None or node.end_col_offset is None:
                continue

            val = node.value.strip()
            if len(val) < 5 or val.startswith("PASTE_") or val.startswith("YOUR_"):
                continue

            var_ctx = _contexto_variable(node)
            tipo_hallado = ""
            desc_hallada = ""
            clave_cfg = ""
            default_val = ""

            # A) Patrones de secretos conocidos (alta precision)
            for env_def, desc, rx in PATRONES_SECRETO:
                if rx.search(val):
                    tipo_hallado = env_def
                    desc_hallada = desc
                    clave_cfg = _normalizar_clave_cfg(var_ctx or env_def)
                    default_val = f"PASTE_{env_def}_HERE"
                    break

            # B) Ruta local personal hardcodeada (C:\Users\... o /home/...)
            if not tipo_hallado and REGEX_RUTA_PERSONAL.search(val):
                tipo_hallado = "LOCAL_PATH"
                desc_hallada = "Ruta personal absoluta del host"
                clave_cfg = _normalizar_clave_cfg(var_ctx or "data_path")
                default_val = "./output"

            # C) Email personal hardcodeado (excluyendo example.com / placeholder)
            if not tipo_hallado and REGEX_EMAIL_PRIVADO.match(val) and not val.lower().endswith(("@example.com", "@yourdomain.com", "@test.com")):
                tipo_hallado = "PRIVATE_EMAIL"
                desc_hallada = "Correo electronico hardcodeado"
                clave_cfg = _normalizar_clave_cfg(var_ctx or "contact_email")
                default_val = "you@example.com"

            # D) Variable con nombre sensible (API_KEY, TOKEN, SECRET, PASSWORD) y valor no trivial
            if not tipo_hallado and var_ctx and REGEX_VAR_SENSIBLE.search(var_ctx):
                if len(val) >= 8 and (" " not in val or _entropia(val) >= 3.2):
                    tipo_hallado = "SENSITIVE_CREDENTIAL"
                    desc_hallada = f"Credencial hardcodeada en variable '{var_ctx}'"
                    clave_cfg = _normalizar_clave_cfg(var_ctx)
                    default_val = f"PASTE_{clave_cfg.upper()}_HERE"

            if not tipo_hallado:
                continue

            s_idx = _pos_ast_a_char_idx(node.lineno, node.col_offset, offsets, lineas_bytes)
            e_idx = _pos_ast_a_char_idx(node.end_lineno, node.end_col_offset, offsets, lineas_bytes)
            if e_idx <= s_idx:
                continue

            env_name = clave_cfg.upper()
            expr_rep = f'_zt_cfg("{clave_cfg}", "{env_name}", "{default_val}")'
            reemplazos.append((s_idx, e_idx, expr_rep))
            vars_cfg[clave_cfg] = default_val
            hallazgos.append(HallazgoSanitizacion(
                tipo=tipo_hallado,
                variable_config=clave_cfg,
                linea=int(node.lineno),
                descripcion=desc_hallada,
                muestra_ofuscada=_ofuscar_muestra(val),
            ))

        # 3. Aplicar reemplazos en orden inverso de offset (cero desplazamiento)
        limpio = raw
        if reemplazos:
            reemplazos.sort(key=lambda x: x[0], reverse=True)
            ultimo_inicio = len(limpio) + 1
            for s_idx, e_idx, expr in reemplazos:
                if e_idx <= ultimo_inicio:
                    limpio = limpio[:s_idx] + expr + limpio[e_idx:]
                    ultimo_inicio = s_idx

            # Inyectar HELPER_CONFIG respetando shebang, encoding y 'from __future__ import ...'
            limpio = self._inyectar_bloque_tras_future(limpio, self.HELPER_CONFIG)

        # 4. Validacion AST final garantizada
        try:
            ast.parse(limpio)
            ast_ok = True
            err_syn = ""
        except SyntaxError as e:
            ast_ok = False
            err_syn = f"SyntaxError post-sanitizacion linea {e.lineno}: {e.msg}"

        return ReporteSanitizacion(
            ast_valido=ast_ok,
            codigo_limpio=limpio,
            hallazgos=hallazgos,
            variables_config=vars_cfg,
            requisitos_pip=sorted(mods_terceros),
            imports_stdlib=sorted(mods_stdlib),
            error_sintaxis=err_syn,
        )

    @staticmethod
    def _inyectar_bloque_tras_future(codigo: str, bloque: str) -> str:
        lineas = codigo.splitlines(keepends=True)
        idx_ins = 0
        # Saltar shebang y comentario encoding
        while idx_ins < len(lineas) and (
            lineas[idx_ins].startswith("#!") or "coding" in lineas[idx_ins]
        ):
            idx_ins += 1
        # Respetar docstring de modulo y imports from __future__
        try:
            t = ast.parse(codigo)
            for stmt in t.body:
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str) and stmt.lineno <= idx_ins + 3:
                    idx_ins = max(idx_ins, int(stmt.end_lineno or stmt.lineno))
                elif isinstance(stmt, ast.ImportFrom) and stmt.module == "__future__":
                    idx_ins = max(idx_ins, int(stmt.end_lineno or stmt.lineno))
                else:
                    break
        except SyntaxError:
            pass

        pref = "".join(lineas[:idx_ins])
        suf = "".join(lineas[idx_ins:])
        sep = "\n" if pref and not pref.endswith("\n") else ""
        return f"{pref}{sep}{bloque}\n{suf}"