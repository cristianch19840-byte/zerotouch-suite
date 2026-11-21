from __future__ import annotations

import difflib
import hashlib
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from titan_core.ai_providers import SolicitudIA, limpiar_razonamiento_llm
from titan_core.ai_router import TitanAIRouter, obtener_ai_router
from titan_core.db_engine import ROOT_DIR
from titan_core.event_bus import TitanEventBus, obtener_event_bus
from titan_core.sandbox_runner import (
    ResultadoSandbox,
    TitanSandboxRunner,
    auditar_codigo_ast,
    obtener_sandbox_runner,
)

REGEX_PY_FENCE = re.compile(r"```(?:python|py)?\s*\n([\s\S]*?)```", re.IGNORECASE)


def extraer_codigo_python_llm(respuesta_raw: str) -> str:
    """Extrae codigo Python limpio desde la respuesta de un LLM eliminando <think> y fences markdown."""
    limpio = limpiar_razonamiento_llm(respuesta_raw or "").strip()
    if not limpio:
        return ""
    bloques = REGEX_PY_FENCE.findall(limpio)
    if bloques:
        # Elegimos el bloque mas extenso (suele ser el script completo reparado)
        mejor = max(bloques, key=len).strip()
        return mejor
    return limpio


def numerar_codigo(codigo: str, max_lineas: int = 350) -> str:
    lineas = (codigo or "").splitlines()[:max_lineas]
    return "\n".join(f"{i + 1:03d} | {ln}" for i, ln in enumerate(lineas))


def generar_diff_unificado(codigo_antes: str, codigo_despues: str, nombre: str = "script.py") -> str:
    a = (codigo_antes or "").splitlines(keepends=True)
    b = (codigo_despues or "").splitlines(keepends=True)
    diff = difflib.unified_diff(a, b, fromfile=f"a/{nombre}", tofile=f"b/{nombre}", n=3)
    return "".join(diff)


@dataclass(slots=True)
class IntentoAutoFix:
    iteracion: int
    proveedor_ia: str
    modelo_ia: str
    ast_valido: bool
    sandbox_ok: bool
    exit_code: int
    error_resumen: str = ""
    duracion_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteracion": self.iteracion,
            "proveedor_ia": self.proveedor_ia,
            "modelo_ia": self.modelo_ia,
            "ast_valido": self.ast_valido,
            "sandbox_ok": self.sandbox_ok,
            "exit_code": self.exit_code,
            "error_resumen": self.error_resumen[:200],
            "duracion_ms": round(self.duracion_ms, 2),
        }


@dataclass(slots=True)
class ResultadoAutoFix:
    exito: bool
    reparado: bool
    codigo_original: str
    codigo_final: str
    diff_unificado: str = ""
    iteraciones_usadas: int = 0
    snapshot_ruta: str = ""
    resultado_inicial: ResultadoSandbox | None = None
    resultado_final: ResultadoSandbox | None = None
    intentos: list[IntentoAutoFix] = field(default_factory=list)
    mensaje: str = ""
    duracion_total_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "exito": self.exito,
            "reparado": self.reparado,
            "iteraciones_usadas": self.iteraciones_usadas,
            "snapshot_ruta": self.snapshot_ruta,
            "diff_unificado": self.diff_unificado,
            "mensaje": self.mensaje,
            "duracion_total_ms": round(self.duracion_total_ms, 2),
            "resultado_inicial": self.resultado_inicial.to_dict() if self.resultado_inicial else None,
            "resultado_final": self.resultado_final.to_dict() if self.resultado_final else None,
            "intentos": [i.to_dict() for i in self.intentos],
        }


class SnapshotManager:
    """Respaldos locales ligeros antes de sobrescribir un script reparado/refinado (permite rollback 1-clic)."""

    def __init__(self, carpeta: str | None = None, max_por_archivo: int = 12) -> None:
        self.carpeta = os.path.abspath(carpeta or os.path.join(ROOT_DIR, ".titan_snapshots"))
        self.max_por_archivo = max(2, int(max_por_archivo))

    def guardar_snapshot(self, ruta_origen: str, contenido: str) -> str:
        os.makedirs(self.carpeta, exist_ok=True)
        base = re.sub(r"[^a-zA-Z0-9_.\-]", "_", os.path.basename(ruta_origen) or "script.py")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        h = hashlib.blake2b(contenido.encode("utf-8", errors="ignore"), digest_size=4).hexdigest()
        destino = os.path.join(self.carpeta, f"{base}.{stamp}.{h}.bak.py")
        with open(destino, "w", encoding="utf-8", newline="\n") as f:
            f.write(contenido)

        # Rotar snapshots antiguos del mismo archivo
        pref = f"{base}."
        existentes = sorted(
            [os.path.join(self.carpeta, fn) for fn in os.listdir(self.carpeta) if fn.startswith(pref)],
            key=os.path.getmtime,
        )
        while len(existentes) > self.max_por_archivo:
            viejo = existentes.pop(0)
            try:
                os.remove(viejo)
            except OSError:
                pass
        return destino

    def restaurar_snapshot(self, snapshot_ruta: str, destino_ruta: str) -> bool:
        snap_abs = os.path.abspath(snapshot_ruta)
        if not snap_abs.startswith(self.carpeta) or not os.path.isfile(snap_abs):
            return False
        with open(snap_abs, "r", encoding="utf-8") as f:
            raw = f.read()
        dest_abs = os.path.abspath(destino_ruta if os.path.isabs(destino_ruta) else os.path.join(ROOT_DIR, destino_ruta))
        with open(dest_abs, "w", encoding="utf-8", newline="\n") as f:
            f.write(raw)
        return True

    def listar_snapshots(self, nombre_archivo: str = "") -> list[dict[str, Any]]:
        if not os.path.isdir(self.carpeta):
            return []
        pref = re.sub(r"[^a-zA-Z0-9_.\-]", "_", os.path.basename(nombre_archivo)) if nombre_archivo else ""
        out: list[dict[str, Any]] = []
        for fn in sorted(os.listdir(self.carpeta), reverse=True):
            if not fn.endswith(".bak.py"):
                continue
            if pref and not fn.startswith(pref):
                continue
            full = os.path.join(self.carpeta, fn)
            out.append({
                "archivo": fn,
                "ruta": full,
                "bytes": os.path.getsize(full),
                "mtime": round(os.path.getmtime(full), 2),
            })
        return out[:40]


class TitanCodeAutoFixer:
    """
    Motor de Auto-Reparacion y Refinamiento Verificado para TITAN-OS v16.0:
    1. Ejecuta el script en TitanSandboxRunner (aislado y sin fuga de secretos)
    2. Si falla por SyntaxError o excepcion en runtime, captura traceback + linea exacta
    3. Invoca TitanAIRouter (Gemini/Ollama) en bucle iterativo (1..max_iter) con memoria de intentos fallidos
    4. Valida AST + Auditoria Seguridad + Re-ejecucion en Sandbox hasta lograr exit_code == 0
    5. Genera Diff Unificado, guarda Snapshot de rollback y persiste telemetria en SQLite + EventBus
    """

    SYSTEM_AUTOFIX = (
        "Eres un ingeniero senior de Python 3.12 especializado en depuracion quirurgica. "
        "Recibiras un script Python con un fallo real y su traceback exacto. "
        "Devuelve UNICAMENTE el script Python completo corregido dentro de un bloque ```python ... ```. "
        "Reglas estrictas: no uses eval/exec/os.system/shutil.rmtree, no leas archivos .env, "
        "mantiene la logica e intencion original del script y asegura que ejecute limpiamente con exit code 0."
    )

    SYSTEM_REFINAR = (
        "Eres un arquitecto senior de Python 3.12. Refina el script aplicando exactamente la instruccion solicitada. "
        "Devuelve UNICAMENTE el codigo Python completo actualizado dentro de ```python ... ```. "
        "Asegura sintaxis 100% valida, manejo limpio de excepciones y cero comandos peligrosos del SO."
    )

    def __init__(
        self,
        sandbox: TitanSandboxRunner | None = None,
        ai_router: TitanAIRouter | None = None,
        bus: TitanEventBus | None = None,
        snapshots: SnapshotManager | None = None,
    ) -> None:
        self.sandbox = sandbox or obtener_sandbox_runner()
        self.ai_router = ai_router or obtener_ai_router()
        self.bus = bus or obtener_event_bus()
        self.snapshots = snapshots or SnapshotManager()

    def _construir_prompt_fix(
        self,
        codigo_actual: str,
        res_fallo: ResultadoSandbox,
        instruccion_extra: str,
        historial_errores: list[str],
    ) -> str:
        diag = res_fallo.diagnostico
        partes = [
            f"=== DIAGNOSTICO DEL FALLO ===",
            f"Exit code: {res_fallo.exit_code} | Tipo: {diag.tipo_error if diag else 'Error'} | Linea: {diag.linea if diag else 0}",
            f"Mensaje: {diag.mensaje if diag else res_fallo.stderr[:240]}",
        ]
        if diag and diag.paquete_pip_sugerido:
            partes.append(f"NOTA: Falta paquete '{diag.paquete_pip_sugerido}'. Si puedes resolverlo con stdlib de Python 3.12 hazlo.")
        if res_fallo.stderr:
            partes.append(f"\n=== STDERR ===\n{res_fallo.stderr[:1800]}")
        if res_fallo.stdout:
            partes.append(f"\n=== STDOUT PARCIAL ===\n{res_fallo.stdout[:600]}")
        if instruccion_extra:
            partes.append(f"\n=== OBJETIVO ADICIONAL ===\n{instruccion_extra}")
        if historial_errores:
            partes.append("\n=== INTENTOS PREVIOS QUE FALLARON (NO REPETIR) ===")
            for idx, he in enumerate(historial_errores[-3:], 1):
                partes.append(f"- Intento {idx}: {he}")
        partes.append(f"\n=== CODIGO ACTUAL (CON NUMEROS DE LINEA) ===\n{numerar_codigo(codigo_actual)}")
        partes.append("\nDevuelve el script completo corregido en ```python ... ```:")
        return "\n".join(partes)

    def reparar_codigo(
        self,
        codigo: str,
        *,
        nombre_ref: str = "script.py",
        instruccion_extra: str = "",
        max_iteraciones: int = 3,
        timeout_seg: float = 10.0,
        args: list[str] | None = None,
        stdin_texto: str = "",
    ) -> ResultadoAutoFix:
        t0 = time.perf_counter()
        max_it = max(1, min(6, int(max_iteraciones)))

        # Paso 1: Evaluacion inicial en Sandbox
        res_ini = self.sandbox.ejecutar_codigo(
            codigo,
            nombre_ref=nombre_ref,
            args=args,
            stdin_texto=stdin_texto,
            timeout_seg=timeout_seg,
            persistir=True,
            auto_reparado=False,
        )

        if res_ini.ok:
            return ResultadoAutoFix(
                exito=True,
                reparado=False,
                codigo_original=codigo,
                codigo_final=codigo,
                diff_unificado="",
                iteraciones_usadas=0,
                resultado_inicial=res_ini,
                resultado_final=res_ini,
                mensaje="El script ya paso todas las pruebas sin errores.",
                duracion_total_ms=round((time.perf_counter() - t0) * 1000.0, 2),
            )

        if res_ini.bloqueado_seguridad:
            return ResultadoAutoFix(
                exito=False,
                reparado=False,
                codigo_original=codigo,
                codigo_final=codigo,
                resultado_inicial=res_ini,
                resultado_final=res_ini,
                mensaje=f"Abortado por seguridad AST: {res_ini.stderr}",
                duracion_total_ms=round((time.perf_counter() - t0) * 1000.0, 2),
            )

        # Paso 2: Bucle iterativo de Auto-Fix con TitanAIRouter + Re-verificacion Sandbox
        codigo_actual = codigo
        ultimo_res = res_ini
        intentos: list[IntentoAutoFix] = []
        historial_err: list[str] = []

        for it in range(1, max_it + 1):
            t_it = time.perf_counter()
            prompt = self._construir_prompt_fix(codigo_actual, ultimo_res, instruccion_extra, historial_err)

            resp_ia = self.ai_router.ejecutar(
                SolicitudIA(
                    prompt=prompt,
                    system_prompt=self.SYSTEM_AUTOFIX,
                    temperatura=0.15,
                    json_mode=False,
                    max_tokens=3072,
                    timeout_seg=32.0,
                    tarea="codigo",
                    usar_cache=False,
                )
            )
            if not resp_ia.ok or not resp_ia.texto:
                err_ia = resp_ia.error or "IA no devolvio codigo"
                historial_err.append(f"Fallo IA: {err_ia}")
                intentos.append(IntentoAutoFix(
                    iteracion=it, proveedor_ia=resp_ia.proveedor, modelo_ia=resp_ia.modelo,
                    ast_valido=False, sandbox_ok=False, exit_code=-1,
                    error_resumen=err_ia, duracion_ms=round((time.perf_counter() - t_it) * 1000.0, 2),
                ))
                continue

            candidato = extraer_codigo_python_llm(resp_ia.texto)
            if not candidato or len(candidato) < 8:
                historial_err.append("Respuesta vacia tras extraer bloque python")
                intentos.append(IntentoAutoFix(
                    iteracion=it, proveedor_ia=resp_ia.proveedor, modelo_ia=resp_ia.modelo,
                    ast_valido=False, sandbox_ok=False, exit_code=-1,
                    error_resumen="Bloque de codigo vacio", duracion_ms=round((time.perf_counter() - t_it) * 1000.0, 2),
                ))
                continue

            aud_cand = auditar_codigo_ast(candidato)
            if aud_cand.bloqueado:
                razon_seg = "; ".join(h.descripcion for h in aud_cand.hallazgos if h.bloqueante) or "Bloqueo AST"
                historial_err.append(f"Parche rechazado por seguridad AST: {razon_seg}")
                intentos.append(IntentoAutoFix(
                    iteracion=it, proveedor_ia=resp_ia.proveedor, modelo_ia=resp_ia.modelo,
                    ast_valido=aud_cand.ast_valido, sandbox_ok=False, exit_code=126,
                    error_resumen=razon_seg, duracion_ms=round((time.perf_counter() - t_it) * 1000.0, 2),
                ))
                continue

            # Ejecutar candidato en el Sandbox
            res_cand = self.sandbox.ejecutar_codigo(
                candidato,
                nombre_ref=nombre_ref,
                args=args,
                stdin_texto=stdin_texto,
                timeout_seg=timeout_seg,
                persistir=True,
                auto_reparado=True,
            )
            dur_it = round((time.perf_counter() - t_it) * 1000.0, 2)
            err_sum = "" if res_cand.ok else (res_cand.diagnostico.mensaje if res_cand.diagnostico else res_cand.stderr[:160])

            intentos.append(IntentoAutoFix(
                iteracion=it,
                proveedor_ia=resp_ia.proveedor,
                modelo_ia=resp_ia.modelo,
                ast_valido=aud_cand.ast_valido,
                sandbox_ok=res_cand.ok,
                exit_code=res_cand.exit_code,
                error_resumen=err_sum,
                duracion_ms=dur_it,
            ))

            codigo_actual = candidato
            ultimo_res = res_cand

            if res_cand.ok:
                diff = generar_diff_unificado(codigo, candidato, nombre=os.path.basename(nombre_ref))
                if self.bus is not None:
                    self.bus.publicar(
                        "sandbox.autofix.ok",
                        {
                            "ruta_script": nombre_ref,
                            "iteraciones": it,
                            "proveedor": resp_ia.proveedor,
                            "modelo": resp_ia.modelo,
                        },
                        origen="autofix",
                        nivel="ok",
                    )
                return ResultadoAutoFix(
                    exito=True,
                    reparado=True,
                    codigo_original=codigo,
                    codigo_final=candidato,
                    diff_unificado=diff,
                    iteraciones_usadas=it,
                    resultado_inicial=res_ini,
                    resultado_final=res_cand,
                    intentos=intentos,
                    mensaje=f"Script auto-reparado con exito en {it} iteracion(es) via {resp_ia.proveedor}/{resp_ia.modelo}.",
                    duracion_total_ms=round((time.perf_counter() - t0) * 1000.0, 2),
                )

            historial_err.append(f"{res_cand.diagnostico.tipo_error if res_cand.diagnostico else 'Error'}: {err_sum}")

        # Agotadas todas las iteraciones sin lograr exit_code == 0
        if self.bus is not None:
            self.bus.publicar(
                "sandbox.autofix.fail",
                {"ruta_script": nombre_ref, "iteraciones": len(intentos)},
                origen="autofix",
                nivel="error",
            )
        return ResultadoAutoFix(
            exito=False,
            reparado=False,
            codigo_original=codigo,
            codigo_final=codigo_actual,
            diff_unificado=generar_diff_unificado(codigo, codigo_actual, nombre=os.path.basename(nombre_ref)),
            iteraciones_usadas=len(intentos),
            resultado_inicial=res_ini,
            resultado_final=ultimo_res,
            intentos=intentos,
            mensaje=f"No se logro reparar tras {len(intentos)} intento(s): {ultimo_res.stderr[:180]}",
            duracion_total_ms=round((time.perf_counter() - t0) * 1000.0, 2),
        )

    def reparar_archivo(
        self,
        ruta_archivo: str,
        *,
        guardar_si_ok: bool = True,
        **kwargs: Any,
    ) -> ResultadoAutoFix:
        ruta_abs = os.path.abspath(ruta_archivo if os.path.isabs(ruta_archivo) else os.path.join(ROOT_DIR, ruta_archivo))
        if not os.path.isfile(ruta_abs):
            return ResultadoAutoFix(
                exito=False, reparado=False, codigo_original="", codigo_final="",
                mensaje=f"Archivo no encontrado: {ruta_archivo}",
            )
        with open(ruta_abs, "r", encoding="utf-8", errors="replace") as f:
            original = f.read()

        kwargs.setdefault("nombre_ref", ruta_archivo)
        res = self.reparar_codigo(original, **kwargs)

        if res.exito and res.reparado and guardar_si_ok:
            snap = self.snapshots.guardar_snapshot(ruta_abs, original)
            res.snapshot_ruta = snap
            with open(ruta_abs, "w", encoding="utf-8", newline="\n") as f:
                f.write(res.codigo_final)
        return res

    def refinar_y_verificar(
        self,
        codigo: str,
        instruccion: str,
        *,
        nombre_ref: str = "script.py",
        ejecutar_sandbox: bool = True,
        auto_fix_si_falla: bool = True,
        timeout_seg: float = 10.0,
    ) -> ResultadoAutoFix:
        """
        Refina un script segun una instruccion del usuario y garantiza que compile y ejecute limpio.
        """
        t0 = time.perf_counter()
        prompt = (
            f"=== INSTRUCCION DE MEJORA ===\n{instruccion.strip()}\n\n"
            f"=== CODIGO ACTUAL ===\n{numerar_codigo(codigo)}\n\n"
            "Devuelve el script completo mejorado dentro de ```python ... ```:"
        )
        resp_ia = self.ai_router.ejecutar(
            SolicitudIA(
                prompt=prompt,
                system_prompt=self.SYSTEM_REFINAR,
                temperatura=0.2,
                max_tokens=3200,
                timeout_seg=35.0,
                tarea="codigo",
                usar_cache=False,
            )
        )
        if not resp_ia.ok or not resp_ia.texto:
            return ResultadoAutoFix(
                exito=False, reparado=False, codigo_original=codigo, codigo_final=codigo,
                mensaje=f"Error IA al refinar: {resp_ia.error}",
                duracion_total_ms=round((time.perf_counter() - t0) * 1000.0, 2),
            )

        nuevo = extraer_codigo_python_llm(resp_ia.texto)
        if not nuevo:
            return ResultadoAutoFix(
                exito=False, reparado=False, codigo_original=codigo, codigo_final=codigo,
                mensaje="La IA devolvio un bloque vacio",
                duracion_total_ms=round((time.perf_counter() - t0) * 1000.0, 2),
            )

        if not ejecutar_sandbox:
            aud = auditar_codigo_ast(nuevo)
            return ResultadoAutoFix(
                exito=aud.ast_valido and not aud.bloqueado,
                reparado=aud.ast_valido,
                codigo_original=codigo,
                codigo_final=nuevo,
                diff_unificado=generar_diff_unificado(codigo, nuevo, nombre=os.path.basename(nombre_ref)),
                iteraciones_usadas=1,
                mensaje="Refinado (validacion AST)" if aud.ast_valido else aud.error_sintaxis,
                duracion_total_ms=round((time.perf_counter() - t0) * 1000.0, 2),
            )

        if auto_fix_si_falla:
            res_fix = self.reparar_codigo(
                nuevo,
                nombre_ref=nombre_ref,
                instruccion_extra=instruccion,
                max_iteraciones=2,
                timeout_seg=timeout_seg,
            )
            res_fix.codigo_original = codigo
            res_fix.diff_unificado = generar_diff_unificado(codigo, res_fix.codigo_final, nombre=os.path.basename(nombre_ref))
            res_fix.reparado = res_fix.exito
            res_fix.duracion_total_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            return res_fix

        res_sbx = self.sandbox.ejecutar_codigo(nuevo, nombre_ref=nombre_ref, timeout_seg=timeout_seg, persistir=True)
        return ResultadoAutoFix(
            exito=res_sbx.ok,
            reparado=res_sbx.ok,
            codigo_original=codigo,
            codigo_final=nuevo,
            diff_unificado=generar_diff_unificado(codigo, nuevo, nombre=os.path.basename(nombre_ref)),
            iteraciones_usadas=1,
            resultado_final=res_sbx,
            mensaje="Refinado y verificado en Sandbox OK" if res_sbx.ok else res_sbx.stderr[:200],
            duracion_total_ms=round((time.perf_counter() - t0) * 1000.0, 2),
        )


_FIX_LOCK = threading.Lock()
_FIX_SINGLETON: TitanCodeAutoFixer | None = None


def obtener_code_autofixer() -> TitanCodeAutoFixer:
    global _FIX_SINGLETON
    with _FIX_LOCK:
        if _FIX_SINGLETON is None:
            _FIX_SINGLETON = TitanCodeAutoFixer()
        return _FIX_SINGLETON