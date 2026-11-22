from __future__ import annotations

import ast
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from titan_core.db_engine import ROOT_DIR, TitanDBEngine, obtener_db_engine
from titan_core.event_bus import TitanEventBus, obtener_event_bus
from titan_core.telemetry import TitanTelemetry, obtener_telemetry


# ==================== MAPEO DE MODULOS PYTHON -> PAQUETES PIP ====================
MAPA_MODULO_A_PIP: dict[str, str] = {
    "bs4": "beautifulsoup4",
    "PIL": "Pillow",
    "cv2": "opencv-python",
    "yaml": "PyYAML",
    "dotenv": "python-dotenv",
    "sklearn": "scikit-learn",
    "telegram": "python-telegram-bot",
    "discord": "discord.py",
    "fitz": "PyMuPDF",
    "docx": "python-docx",
    "dateutil": "python-dateutil",
    "jwt": "PyJWT",
    "Crypto": "pycryptodome",
    "OpenSSL": "pyOpenSSL",
    "magic": "python-magic",
    "serial": "pyserial",
    "win32api": "pywin32",
    "win32com": "pywin32",
    "playwright": "playwright",
    "selenium": "selenium",
    "scrapy": "scrapy",
    "httpx": "httpx",
    "aiohttp": "aiohttp",
    "requests": "requests",
    "pandas": "pandas",
    "numpy": "numpy",
    "openpyxl": "openpyxl",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "pydantic": "pydantic",
    "telethon": "Telethon",
    "pyrogram": "Pyrogram",
    "aiogram": "aiogram",
    "curl_cffi": "curl_cffi",
    "cloudscraper": "cloudscraper",
    "stripe": "stripe",
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "google-genai",
    "lxml": "lxml",
    "rich": "rich",
    "typer": "typer",
    "click": "click",
    "schedule": "schedule",
    "apscheduler": "APScheduler",
}

STDLIB_MODULOS: frozenset[str] = frozenset(getattr(sys, "stdlib_module_names", set())) | {
    "__future__", "builtins", "typing_extensions",
}

# Variables de entorno sensibles que JAMAS deben filtrarse al subproceso sandbox
PATRONES_ENV_SENSIBLES = re.compile(
    r"(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|AUTH|COOKIE|CREDENTIAL|PRIVATE|"
    r"GEMINI|TELEGRAM|OPENAI|ANTHROPIC|GITHUB|REDDIT|STRIPE|BINANCE|AWS_|GCP_|AZURE_)",
    re.IGNORECASE,
)

# Rutas criticas protegidas contra lectura/escritura accidental desde scripts de prueba
PATRONES_RUTAS_PROTEGIDAS = re.compile(
    r"(?:\.env\b|estado_radar_v4\.db|config\.json|id_rsa|system32|c:\\windows|/etc/passwd|/etc/shadow)",
    re.IGNORECASE,
)

# Llamadas peligrosas por modulo.funcion -> (severidad, bloqueante, descripcion)
LLAMADAS_PELIGROSAS: dict[str, tuple[float, bool, str]] = {
    "os.system": (95.0, True, "Ejecucion directa de shell via os.system"),
    "os.popen": (90.0, True, "Ejecucion de shell via os.popen"),
    "os.execv": (95.0, True, "Reemplazo de proceso via os.execv"),
    "os.execve": (95.0, True, "Reemplazo de proceso via os.execve"),
    "os.spawnv": (90.0, True, "Creacion de proceso externo via os.spawnv"),
    "os.kill": (70.0, True, "Terminacion de procesos del sistema via os.kill"),
    "shutil.rmtree": (85.0, True, "Borrado recursivo de directorios via shutil.rmtree"),
    "os.remove": (45.0, False, "Eliminacion de archivos via os.remove"),
    "os.unlink": (45.0, False, "Eliminacion de archivos via os.unlink"),
    "os.rmdir": (40.0, False, "Eliminacion de carpetas via os.rmdir"),
    "subprocess.Popen": (65.0, False, "Subproceso externo via subprocess.Popen"),
    "subprocess.run": (55.0, False, "Subproceso externo via subprocess.run"),
    "subprocess.call": (60.0, False, "Subproceso externo via subprocess.call"),
    "subprocess.check_output": (60.0, False, "Subproceso externo via subprocess.check_output"),
    "subprocess.check_call": (60.0, False, "Subproceso externo via subprocess.check_call"),
    "webbrowser.open": (25.0, False, "Apertura de navegador externo"),
    "ctypes.windll": (95.0, True, "Acceso directo a DLLs de Windows via ctypes"),
    "ctypes.CDLL": (90.0, True, "Carga de librerias nativas C via ctypes"),
}

BUILTINS_PELIGROSOS: dict[str, tuple[float, bool, str]] = {
    "eval": (80.0, True, "Evaluacion dinamica arbitraria eval()"),
    "exec": (85.0, True, "Ejecucion dinamica arbitraria exec()"),
    "compile": (45.0, False, "Compilacion dinamica de codigo compile()"),
    "__import__": (75.0, True, "Importacion dinamica ofuscada __import__()"),
}

MODULOS_RESTRINGIDOS: dict[str, tuple[float, bool, str]] = {
    "ctypes": (85.0, True, "Modulo ctypes permite acceso a memoria/APIs del SO"),
    "winreg": (95.0, True, "Acceso al Registro de Windows"),
    "pty": (80.0, True, "Pseudo-terminal del sistema"),
    "msvcrt": (50.0, False, "Acceso bajo nivel consola Windows"),
    "pickle": (25.0, False, "Deserializacion pickle potencialmente insegura"),
}

REGEX_TRACEBACK_ERR = re.compile(r"^([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Exit|Interrupt|Warning)):\s*(.*)$")
REGEX_TRACEBACK_FILE = re.compile(r'File "([^"]+)", line (\d+)(?:, in (.+))?')
REGEX_MOD_NOT_FOUND = re.compile(r"No module named ['\"]([^'\"]+)['\"]", re.IGNORECASE)


# ==================== MODELOS DE AUDITORIA Y EJECUCION ====================
@dataclass(slots=True)
class HallazgoAST:
    codigo: str
    severidad: float
    bloqueante: bool
    linea: int
    descripcion: str
    evidencia: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "codigo": self.codigo,
            "severidad": round(self.severidad, 1),
            "bloqueante": self.bloqueante,
            "linea": self.linea,
            "descripcion": self.descripcion,
            "evidencia": self.evidencia[:120],
        }


@dataclass(slots=True)
class ReporteAuditoriaAST:
    ast_valido: bool
    error_sintaxis: str = ""
    linea_sintaxis: int = 0
    columna_sintaxis: int = 0
    riesgo_score: float = 0.0
    bloqueado: bool = False
    hallazgos: list[HallazgoAST] = field(default_factory=list)
    imports_detectados: list[str] = field(default_factory=list)
    paquetes_pip_faltantes: list[str] = field(default_factory=list)
    funciones_definidas: list[str] = field(default_factory=list)
    clases_definidas: list[str] = field(default_factory=list)
    lineas_codigo: int = 0
    complejidad_ciclomatica: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "ast_valido": self.ast_valido,
            "error_sintaxis": self.error_sintaxis,
            "linea_sintaxis": self.linea_sintaxis,
            "columna_sintaxis": self.columna_sintaxis,
            "riesgo_score": round(self.riesgo_score, 1),
            "bloqueado": self.bloqueado,
            "hallazgos": [h.to_dict() for h in self.hallazgos],
            "imports_detectados": self.imports_detectados,
            "paquetes_pip_faltantes": self.paquetes_pip_faltantes,
            "funciones": self.funciones_definidas[:25],
            "clases": self.clases_definidas[:15],
            "lineas_codigo": self.lineas_codigo,
            "complejidad_ciclomatica": self.complejidad_ciclomatica,
        }


@dataclass(slots=True)
class DiagnosticoTraceback:
    tipo_error: str = ""
    mensaje: str = ""
    archivo: str = ""
    linea: int = 0
    funcion: str = ""
    modulo_faltante: str = ""
    paquete_pip_sugerido: str = ""
    es_sintaxis: bool = False
    es_timeout: bool = False
    es_seguridad: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "tipo_error": self.tipo_error,
            "mensaje": self.mensaje[:240],
            "archivo": self.archivo,
            "linea": self.linea,
            "funcion": self.funcion,
            "modulo_faltante": self.modulo_faltante,
            "paquete_pip_sugerido": self.paquete_pip_sugerido,
            "es_sintaxis": self.es_sintaxis,
            "es_timeout": self.es_timeout,
            "es_seguridad": self.es_seguridad,
        }


@dataclass(slots=True)
class ResultadoSandbox:
    ok: bool
    exit_code: int
    ruta_script: str
    duracion_ms: float
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    truncado: bool = False
    bloqueado_seguridad: bool = False
    auditoria: ReporteAuditoriaAST | None = None
    diagnostico: DiagnosticoTraceback | None = None
    archivos_creados: list[str] = field(default_factory=list)
    ejecucion_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "exit_code": self.exit_code,
            "ruta_script": self.ruta_script,
            "duracion_ms": round(self.duracion_ms, 2),
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
            "truncado": self.truncado,
            "bloqueado_seguridad": self.bloqueado_seguridad,
            "auditoria": self.auditoria.to_dict() if self.auditoria else None,
            "diagnostico": self.diagnostico.to_dict() if self.diagnostico else None,
            "archivos_creados": self.archivos_creados,
            "ejecucion_id": self.ejecucion_id,
        }


# ==================== AUDITOR AST ANTI-COMANDOS PELIGROSOS ====================
def _resolver_nombre_llamada(node: ast.AST, alias_map: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return alias_map.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        base = _resolver_nombre_llamada(node.value, alias_map)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _es_modulo_instalado(mod_raiz: str) -> bool:
    if not mod_raiz or mod_raiz in STDLIB_MODULOS:
        return True
    try:
        return importlib.util.find_spec(mod_raiz) is not None
    except Exception:
        return False


def auditar_codigo_ast(codigo: str, permitir_subprocesos_seguros: bool = False) -> ReporteAuditoriaAST:
    """
    Auditoria estatica completa via AST de Python 3.12:
    - Valida sintaxis exacta (linea/columna)
    - Detecta llamadas peligrosas, shell=True, eval/exec, rutas protegidas (.env/DB/config)
    - Calcula complejidad ciclomatica y detecta paquetes pip faltantes
    """
    lineas = len(str(codigo or "").splitlines())
    rep = ReporteAuditoriaAST(ast_valido=False, lineas_codigo=lineas)

    try:
        tree = ast.parse(codigo or "")
    except SyntaxError as e:
        rep.ast_valido = False
        rep.error_sintaxis = f"{type(e).__name__}: {e.msg}"
        rep.linea_sintaxis = int(e.lineno or 0)
        rep.columna_sintaxis = int(e.offset or 0)
        return rep

    rep.ast_valido = True
    alias_map: dict[str, str] = {}
    imports_set: set[str] = set()
    complejidad = 1

    # 1. Primera pasada: recopilar imports y alias (ej. import subprocess as sp -> sp -> subprocess)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for al in node.names:
                raiz = al.name.split(".", 1)[0]
                imports_set.add(raiz)
                alias_map[al.asname or raiz] = al.name
                if raiz in MODULOS_RESTRINGIDOS:
                    sev, bloq, desc = MODULOS_RESTRINGIDOS[raiz]
                    rep.hallazgos.append(HallazgoAST(f"AST_MOD_{raiz.upper()}", sev, bloq, getattr(node, "lineno", 0), desc, f"import {al.name}"))
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                raiz = node.module.split(".", 1)[0]
                imports_set.add(raiz)
                if raiz in MODULOS_RESTRINGIDOS:
                    sev, bloq, desc = MODULOS_RESTRINGIDOS[raiz]
                    rep.hallazgos.append(HallazgoAST(f"AST_MOD_{raiz.upper()}", sev, bloq, getattr(node, "lineno", 0), desc, f"from {node.module} import ..."))
                for al in node.names:
                    alias_map[al.asname or al.name] = f"{node.module}.{al.name}"

    # 2. Segunda pasada: llamadas, complejidad, funciones, clases, rutas protegidas y bucles sin salida
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            rep.funciones_definidas.append(node.name)
        elif isinstance(node, ast.ClassDef):
            rep.clases_definidas.append(node.name)
        elif isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.With, ast.AsyncWith, ast.IfExp)):
            complejidad += 1
        elif isinstance(node, ast.BoolOp):
            complejidad += max(1, len(node.values) - 1)

        # Detectar bucle infinito obvio (while True sin break/return/raise)
        if isinstance(node, ast.While) and isinstance(node.test, ast.Constant) and node.test.value is True:
            tiene_salida = any(isinstance(sub, (ast.Break, ast.Return, ast.Raise)) for sub in ast.walk(node))
            if not tiene_salida:
                rep.hallazgos.append(HallazgoAST(
                    "AST_WHILE_INFINITO", 35.0, False, getattr(node, "lineno", 0),
                    "Bucle 'while True' sin break/return/raise explicito (riesgo de timeout)",
                    "while True:",
                ))

        # Inspeccionar llamadas
        if isinstance(node, ast.Call):
            nombre_call = _resolver_nombre_llamada(node.func, alias_map)
            ln = getattr(node, "lineno", 0)

            if nombre_call in BUILTINS_PELIGROSOS:
                sev, bloq, desc = BUILTINS_PELIGROSOS[nombre_call]
                rep.hallazgos.append(HallazgoAST(f"AST_BUILTIN_{nombre_call.upper()}", sev, bloq, ln, desc, f"{nombre_call}(...)"))

            if nombre_call in LLAMADAS_PELIGROSAS:
                sev, bloq, desc = LLAMADAS_PELIGROSAS[nombre_call]
                # Verificar shell=True en subprocess.*
                if nombre_call.startswith("subprocess."):
                    shell_true = any(
                        kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True
                        for kw in node.keywords
                    )
                    if shell_true:
                        sev = 95.0
                        bloq = True
                        desc = f"{desc} con shell=True (inyeccion de comandos)"
                    elif not permitir_subprocesos_seguros:
                        bloq = True
                rep.hallazgos.append(HallazgoAST("AST_CALL_PELIGROSA", sev, bloq, ln, desc, nombre_call))

            # Verificar acceso directo a archivos sensibles (.env, DB principal, config.json)
            if nombre_call in ("open", "io.open", "pathlib.Path", "Path") or nombre_call.endswith(".read_text") or nombre_call.endswith(".write_text"):
                for arg in node.args[:2]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        if PATRONES_RUTAS_PROTEGIDAS.search(arg.value):
                            rep.hallazgos.append(HallazgoAST(
                                "AST_RUTA_PROTEGIDA", 90.0, True, ln,
                                f"Intento de acceso a archivo sensible protegido: {arg.value}",
                                arg.value,
                            ))

        # Detectar literales sospechosos tipo lectura directa de .env o DB
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) <= 140:
            if ".env" == node.value.strip().lower() or "estado_radar_v4.db" in node.value.lower():
                ln = getattr(node, "lineno", 0)
                if not any(h.codigo == "AST_RUTA_PROTEGIDA" and h.linea == ln for h in rep.hallazgos):
                    rep.hallazgos.append(HallazgoAST(
                        "AST_RUTA_PROTEGIDA", 80.0, True, ln,
                        f"Referencia a archivo critico del sistema: {node.value}",
                        node.value,
                    ))

    # 3. Detectar dependencias pip faltantes (excluyendo modulos locales del proyecto)
    imports_ordenados = sorted(imports_set)
    faltantes: list[str] = []
    modulos_locales = {"titan_core", "core_ia", "modulo_a_radar_whop", "modulo_b_ejecutor", "modulo_c_whop", "modulo_d_marketing"}
    for mod in imports_ordenados:
        if mod in modulos_locales or mod in STDLIB_MODULOS:
            continue
        if not _es_modulo_instalado(mod):
            pip_nom = MAPA_MODULO_A_PIP.get(mod, mod)
            if pip_nom not in faltantes:
                faltantes.append(pip_nom)

    riesgo = min(100.0, sum(h.severidad for h in rep.hallazgos))
    bloqueado = any(h.bloqueante for h in rep.hallazgos) or riesgo >= 85.0

    rep.imports_detectados = imports_ordenados
    rep.paquetes_pip_faltantes = faltantes
    rep.complejidad_ciclomatica = complejidad
    rep.riesgo_score = round(riesgo, 1)
    rep.bloqueado = bloqueado
    return rep


# ==================== PARSER DE TRACEBACKS Y ENTORNO SANITIZADO ====================
def diagnosticar_traceback(stderr: str, timed_out: bool = False, aud: ReporteAuditoriaAST | None = None) -> DiagnosticoTraceback:
    diag = DiagnosticoTraceback()
    if aud is not None and not aud.ast_valido:
        diag.tipo_error = "SyntaxError"
        diag.mensaje = aud.error_sintaxis
        diag.linea = aud.linea_sintaxis
        diag.es_sintaxis = True
        return diag
    if aud is not None and aud.bloqueado:
        diag.tipo_error = "SandboxSecurityError"
        diag.mensaje = "; ".join(h.descripcion for h in aud.hallazgos if h.bloqueante)[:220] or "Bloqueado por politica AST"
        diag.es_seguridad = True
        return diag
    if timed_out:
        diag.tipo_error = "TimeoutExpired"
        diag.mensaje = "El script excedio el tiempo limite de ejecucion en el sandbox"
        diag.es_timeout = True
        return diag

    lineas = [ln.rstrip() for ln in (stderr or "").splitlines() if ln.strip()]
    if not lineas:
        return diag

    # Buscar ultima linea de excepcion real
    for ln in reversed(lineas):
        m = REGEX_TRACEBACK_ERR.match(ln.strip())
        if m:
            diag.tipo_error = m.group(1)
            diag.mensaje = m.group(2).strip()
            break
    if not diag.tipo_error:
        diag.tipo_error = "RuntimeError"
        diag.mensaje = lineas[-1][:220]

    # Buscar ultima referencia de archivo/linea del script del usuario
    for ln in reversed(lineas):
        mf = REGEX_TRACEBACK_FILE.search(ln)
        if mf:
            diag.archivo = os.path.basename(mf.group(1))
            diag.linea = int(mf.group(2))
            diag.funcion = (mf.group(3) or "").strip()
            break

    if diag.tipo_error in ("SyntaxError", "IndentationError", "TabError"):
        diag.es_sintaxis = True

    if diag.tipo_error in ("ModuleNotFoundError", "ImportError"):
        mm = REGEX_MOD_NOT_FOUND.search(diag.mensaje or stderr)
        if mm:
            mod = mm.group(1).split(".", 1)[0]
            diag.modulo_faltante = mod
            diag.paquete_pip_sugerido = MAPA_MODULO_A_PIP.get(mod, mod)

    return diag


def construir_entorno_sandbox(vars_extra: dict[str, str] | None = None) -> dict[str, str]:
    """Construye un entorno sanitizado sin ninguna API key, token ni secreto del host."""
    env_limpio: dict[str, str] = {}
    for k, v in os.environ.items():
        if PATRONES_ENV_SENSIBLES.search(k):
            continue
        env_limpio[k] = v
    env_limpio["PYTHONIOENCODING"] = "utf-8"
    env_limpio["PYTHONUTF8"] = "1"
    env_limpio["PYTHONDONTWRITEBYTECODE"] = "1"
    env_limpio["TITAN_SANDBOX"] = "1"
    if vars_extra:
        for k, v in vars_extra.items():
            if not PATRONES_ENV_SENSIBLES.search(k):
                env_limpio[str(k)] = str(v)
    return env_limpio


def _terminar_arbol_proceso(proc: subprocess.Popen[bytes]) -> None:
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass


# ==================== MOTOR PRINCIPAL SANDBOX RUNNER ====================
class TitanSandboxRunner:
    """
    Ejecutor Python aislado para TITAN-OS v16.0:
    - Auditoria AST previa anti-comandos destructivos y deteccion de pip faltantes
    - Entorno limpio (cero fuga de secretos .env)
    - Directorio de trabajo temporal desechable + timeout estricto con kill de arbol
    - Truncado seguro de salida stdout/stderr
    - Registro persistente en SQLite ('sandbox_ejecuciones') + EventBus + Telemetria
    """

    def __init__(
        self,
        db: TitanDBEngine | None = None,
        bus: TitanEventBus | None = None,
        telemetry: TitanTelemetry | None = None,
        python_exe: str | None = None,
        timeout_default_seg: float = 12.0,
        max_output_bytes: int = 32_768,
        usar_sqlite: bool = True,
    ) -> None:
        self.usar_sqlite = usar_sqlite
        self.db = db if db is not None else (obtener_db_engine() if usar_sqlite else None)
        self.bus = bus if bus is not None else obtener_event_bus()
        self.telemetry = telemetry if telemetry is not None else obtener_telemetry()
        self.python_exe = python_exe or sys.executable
        self.timeout_default_seg = max(0.2, float(timeout_default_seg))
        self.max_output_bytes = max(1024, int(max_output_bytes))
        self._lock = threading.Lock()

    def _persistir_ejecucion(self, res: ResultadoSandbox, auto_reparado: bool = False) -> int | None:
        if not self.usar_sqlite or self.db is None:
            return None
        try:
            eid = self.db.ejecutar(
                """
                INSERT INTO sandbox_ejecuciones (
                    ruta_script, exit_code, duracion_ms, stdout_txt, stderr_txt, auto_reparado, ts_epoch
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(res.ruta_script)[:260],
                    int(res.exit_code),
                    round(float(res.duracion_ms), 2),
                    str(res.stdout)[:8000],
                    str(res.stderr)[:8000],
                    1 if auto_reparado else 0,
                    time.time(),
                ),
            )
            res.ejecucion_id = eid
            return eid
        except Exception:
            return None

    def _emitir_evento(self, res: ResultadoSandbox) -> None:
        if self.bus is None:
            return
        topico = "sandbox.exec.blocked" if res.bloqueado_seguridad else ("sandbox.exec.ok" if res.ok else "sandbox.exec.error")
        nivel = "warn" if res.bloqueado_seguridad else ("ok" if res.ok else "error")
        self.bus.publicar(
            topico,
            {
                "ejecucion_id": res.ejecucion_id,
                "ruta_script": res.ruta_script,
                "exit_code": res.exit_code,
                "duracion_ms": res.duracion_ms,
                "timed_out": res.timed_out,
                "error_tipo": res.diagnostico.tipo_error if res.diagnostico else "",
            },
            origen="sandbox",
            nivel=nivel,
        )

    def auditar_codigo(self, codigo: str, permitir_subprocesos_seguros: bool = False) -> ReporteAuditoriaAST:
        return auditar_codigo_ast(codigo, permitir_subprocesos_seguros=permitir_subprocesos_seguros)

    def ejecutar_codigo(
        self,
        codigo: str,
        *,
        nombre_ref: str = "<inline_script.py>",
        args: list[str] | None = None,
        stdin_texto: str = "",
        timeout_seg: float | None = None,
        forzar_sin_auditoria: bool = False,
        permitir_subprocesos_seguros: bool = False,
        persistir: bool = True,
        auto_reparado: bool = False,
        env_extra: dict[str, str] | None = None,
    ) -> ResultadoSandbox:
        t0 = time.perf_counter()
        timeout_eff = self.timeout_default_seg if timeout_seg is None else max(0.15, min(120.0, float(timeout_seg)))

        # 1. Auditoria AST previa (0ms, evita lanzar procesos con sintaxis rota o comandos peligrosos)
        aud = self.auditar_codigo(codigo, permitir_subprocesos_seguros=permitir_subprocesos_seguros)
        if not aud.ast_valido:
            dur = (time.perf_counter() - t0) * 1000.0
            err_msg = f"SyntaxError en linea {aud.linea_sintaxis}: {aud.error_sintaxis}"
            res = ResultadoSandbox(
                ok=False,
                exit_code=2,
                ruta_script=nombre_ref,
                duracion_ms=round(dur, 2),
                stderr=err_msg,
                auditoria=aud,
                diagnostico=diagnosticar_traceback(err_msg, aud=aud),
            )
            if persistir:
                self._persistir_ejecucion(res, auto_reparado=auto_reparado)
            self._emitir_evento(res)
            return res

        if aud.bloqueado and not forzar_sin_auditoria:
            dur = (time.perf_counter() - t0) * 1000.0
            razones = "; ".join(h.descripcion for h in aud.hallazgos if h.bloqueante) or "Riesgo AST excedido"
            err_msg = f"SandboxSecurityError: {razones}"
            res = ResultadoSandbox(
                ok=False,
                exit_code=126,
                ruta_script=nombre_ref,
                duracion_ms=round(dur, 2),
                stderr=err_msg,
                bloqueado_seguridad=True,
                auditoria=aud,
                diagnostico=diagnosticar_traceback(err_msg, aud=aud),
            )
            if persistir:
                self._persistir_ejecucion(res, auto_reparado=auto_reparado)
            self._emitir_evento(res)
            return res

        # 2. Ejecucion aislada en carpeta temporal desechable con entorno limpio
        workdir = tempfile.mkdtemp(prefix="titan_sbx_")
        script_path = os.path.join(workdir, "sandbox_target.py")
        try:
            with open(script_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(codigo)

            cmd = [self.python_exe, "-I", "-u", script_path] + [str(a) for a in (args or [])]
            env_sbx = construir_entorno_sandbox(env_extra)
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

            proc = subprocess.Popen(
                cmd,
                cwd=workdir,
                env=env_sbx,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=flags,
            )

            timed_out = False
            try:
                raw_out, raw_err = proc.communicate(
                    input=(stdin_texto.encode("utf-8") if stdin_texto else b""),
                    timeout=timeout_eff,
                )
            except subprocess.TimeoutExpired:
                timed_out = True
                _terminar_arbol_proceso(proc)
                try:
                    raw_out, raw_err = proc.communicate(timeout=2.0)
                except Exception:
                    raw_out, raw_err = b"", b""

            dur = (time.perf_counter() - t0) * 1000.0
            truncado = False
            if len(raw_out) > self.max_output_bytes:
                raw_out = raw_out[:self.max_output_bytes] + b"\n...[STDOUT TRUNCADO]..."
                truncado = True
            if len(raw_err) > self.max_output_bytes:
                raw_err = raw_err[:self.max_output_bytes] + b"\n...[STDERR TRUNCADO]..."
                truncado = True

            stdout_txt = raw_out.decode("utf-8", errors="replace")
            stderr_txt = raw_err.decode("utf-8", errors="replace")
            if timed_out:
                stderr_txt = (stderr_txt + f"\nTimeoutExpired: supero {timeout_eff:.1f}s").strip()

            exit_code = 124 if timed_out else int(proc.returncode if proc.returncode is not None else 1)
            ok = (exit_code == 0) and (not timed_out)

            creados = sorted(
                fn for fn in os.listdir(workdir)
                if fn != "sandbox_target.py" and not fn.startswith("__pycache__")
            )[:25]

            diag = None if ok else diagnosticar_traceback(stderr_txt, timed_out=timed_out, aud=aud)
            res = ResultadoSandbox(
                ok=ok,
                exit_code=exit_code,
                ruta_script=nombre_ref,
                duracion_ms=round(dur, 2),
                stdout=stdout_txt,
                stderr=stderr_txt,
                timed_out=timed_out,
                truncado=truncado,
                bloqueado_seguridad=False,
                auditoria=aud,
                diagnostico=diag,
                archivos_creados=creados,
            )
            if persistir:
                self._persistir_ejecucion(res, auto_reparado=auto_reparado)
            self.telemetry.registrar_latencia("sandbox", "exec", dur, exito=ok)
            self._emitir_evento(res)
            return res
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def ejecutar_archivo(self, ruta_archivo: str, **kwargs: Any) -> ResultadoSandbox:
        ruta_abs = os.path.abspath(ruta_archivo if os.path.isabs(ruta_archivo) else os.path.join(ROOT_DIR, ruta_archivo))
        if not os.path.isfile(ruta_abs):
            return ResultadoSandbox(
                ok=False, exit_code=1, ruta_script=ruta_archivo, duracion_ms=0.0,
                stderr=f"FileNotFoundError: No existe el archivo '{ruta_archivo}'",
                diagnostico=DiagnosticoTraceback(tipo_error="FileNotFoundError", mensaje=f"No existe {ruta_archivo}"),
            )
        with open(ruta_abs, "r", encoding="utf-8", errors="replace") as f:
            codigo = f.read()
        kwargs.setdefault("nombre_ref", ruta_archivo)
        return self.ejecutar_codigo(codigo, **kwargs)

    def historial_ejecuciones(self, ruta_script: str = "", limite: int = 30) -> list[dict[str, Any]]:
        if not self.usar_sqlite or self.db is None:
            return []
        lim = max(1, min(200, int(limite)))
        if ruta_script.strip():
            return self.db.consultar_todos(
                "SELECT * FROM sandbox_ejecuciones WHERE ruta_script = ? ORDER BY id DESC LIMIT ?",
                (ruta_script.strip(), lim),
            )
        return self.db.consultar_todos(
            "SELECT * FROM sandbox_ejecuciones ORDER BY id DESC LIMIT ?",
            (lim,),
        )

    def estadisticas(self) -> dict[str, Any]:
        if not self.usar_sqlite or self.db is None:
            return {"total": 0, "exitosas": 0, "fallidas": 0, "auto_reparadas": 0, "latencia_avg_ms": 0.0}
        row = self.db.consultar_uno(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN exit_code = 0 THEN 1 ELSE 0 END) AS exitosas,
                SUM(CASE WHEN exit_code != 0 THEN 1 ELSE 0 END) AS fallidas,
                SUM(CASE WHEN auto_reparado = 1 THEN 1 ELSE 0 END) AS auto_reparadas,
                ROUND(COALESCE(AVG(duracion_ms), 0), 1) AS latencia_avg_ms
            FROM sandbox_ejecuciones
            """
        ) or {}
        tot = int(row.get("total") or 0)
        ex = int(row.get("exitosas") or 0)
        return {
            "total": tot,
            "exitosas": ex,
            "fallidas": int(row.get("fallidas") or 0),
            "auto_reparadas": int(row.get("auto_reparadas") or 0),
            "tasa_exito_pct": round((ex / max(1, tot)) * 100.0, 1) if tot else 0.0,
            "latencia_avg_ms": float(row.get("latencia_avg_ms") or 0.0),
        }


_SBX_LOCK = threading.RLock()
_SBX_SINGLETON: TitanSandboxRunner | None = None


def obtener_sandbox_runner() -> TitanSandboxRunner:
    global _SBX_SINGLETON
    with _SBX_LOCK:
        if _SBX_SINGLETON is None:
            _SBX_SINGLETON = TitanSandboxRunner()
        return _SBX_SINGLETON