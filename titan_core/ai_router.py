from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any

from titan_core.ai_cache import TitanAICache, construir_clave_cache
from titan_core.ai_providers import (
    ProveedorGemini,
    ProveedorOllama,
    ProveedorOpenAICompat,
    RespuestaIA,
    SolicitudIA,
    parsear_json_robusto,
)
from titan_core.db_engine import TitanDBEngine, obtener_db_engine
from titan_core.event_bus import TitanEventBus, obtener_event_bus
from titan_core.telemetry import TitanTelemetry, obtener_telemetry


ESTRATEGIAS_ROUTING: dict[str, tuple[str, ...]] = {
    "cloud_first": ("gemini", "openai_compat", "ollama"),
    "local_first": ("ollama", "gemini", "openai_compat"),
    "economy": ("ollama", "gemini", "openai_compat"),
    "cloud_only": ("gemini", "openai_compat"),
    "local_only": ("ollama",),
}


class TitanAIRouter:
    """
    Orquestador IA Multi-Modelo para TITAN-OS v16.0:
    - Enrutamiento dinamico Gemini Cloud + OpenAI-Compat + Ollama Local (qwen3:8b)
    - Cache hibrida L1 RAM + L2 SQLite ('ai_cache') con soporte semantico opcional
    - Budget Guard diario sobre tokens/llamadas cloud (si se agota cuota cloud, cae automaticamente a Ollama local)
    - Persistencia de telemetria real en 'ai_uso_diario' y eventos Pub/Sub en EventBus
    """

    def __init__(
        self,
        db: TitanDBEngine | None = None,
        bus: TitanEventBus | None = None,
        telemetry: TitanTelemetry | None = None,
        cache: TitanAICache | None = None,
        gemini: ProveedorGemini | None = None,
        ollama: ProveedorOllama | None = None,
        openai_compat: ProveedorOpenAICompat | None = None,
        estrategia_default: str = "cloud_first",
        budget_tokens_cloud_dia: int = 800_000,
        usar_sqlite: bool = True,
    ) -> None:
        self._lock = threading.RLock()
        self.usar_sqlite = usar_sqlite
        self.db = db if db is not None else (obtener_db_engine() if usar_sqlite else None)
        self.bus = bus if bus is not None else obtener_event_bus()
        self.telemetry = telemetry if telemetry is not None else obtener_telemetry()
        self.cache = cache if cache is not None else TitanAICache(db=self.db, usar_sqlite=usar_sqlite)

        self.estrategia_default = estrategia_default if estrategia_default in ESTRATEGIAS_ROUTING else "cloud_first"
        self.budget_tokens_cloud_dia = max(10_000, int(budget_tokens_cloud_dia))

        self.proveedores: dict[str, Any] = {
            "gemini": gemini or ProveedorGemini(),
            "ollama": ollama or ProveedorOllama(),
            "openai_compat": openai_compat or ProveedorOpenAICompat(),
        }

    def configurar(
        self,
        estrategia: str | None = None,
        budget_tokens_cloud_dia: int | None = None,
    ) -> None:
        with self._lock:
            if estrategia and estrategia in ESTRATEGIAS_ROUTING:
                self.estrategia_default = estrategia
            if budget_tokens_cloud_dia is not None:
                self.budget_tokens_cloud_dia = max(10_000, int(budget_tokens_cloud_dia))

    @staticmethod
    def _hoy() -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def tokens_cloud_usados_hoy(self) -> int:
        if not self.usar_sqlite or self.db is None:
            return 0
        val = self.db.escalar(
            """
            SELECT COALESCE(SUM(tokens_in + tokens_out), 0)
            FROM ai_uso_diario
            WHERE fecha = ? AND proveedor != 'ollama'
            """,
            (self._hoy(),),
            default=0,
        )
        return int(val or 0)

    def _registrar_uso_diario(
        self,
        proveedor: str,
        modelo: str,
        *,
        llamadas: int = 0,
        cache_hits: int = 0,
        errores: int = 0,
        tokens_in: int = 0,
        tokens_out: int = 0,
        latencia_ms: float = 0.0,
    ) -> None:
        if not self.usar_sqlite or self.db is None:
            return
        try:
            self.db.ejecutar(
                """
                INSERT INTO ai_uso_diario (
                    fecha, proveedor, modelo, llamadas, cache_hits, errores,
                    tokens_in, tokens_out, latencia_total_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fecha, proveedor, modelo) DO UPDATE SET
                    llamadas = llamadas + excluded.llamadas,
                    cache_hits = cache_hits + excluded.cache_hits,
                    errores = errores + excluded.errores,
                    tokens_in = tokens_in + excluded.tokens_in,
                    tokens_out = tokens_out + excluded.tokens_out,
                    latencia_total_ms = latencia_total_ms + excluded.latencia_total_ms
                """,
                (
                    self._hoy(),
                    (proveedor or "desconocido")[:40],
                    (modelo or "default")[:80],
                    int(llamadas),
                    int(cache_hits),
                    int(errores),
                    int(tokens_in),
                    int(tokens_out),
                    round(float(latencia_ms), 2),
                ),
            )
        except Exception:
            pass

    def _orden_proveedores(self, req: SolicitudIA) -> list[str]:
        if req.forzar_proveedor and req.forzar_proveedor in self.proveedores:
            return [req.forzar_proveedor]
        estr = self.estrategia_default
        # En estrategia 'economy', las tareas de volumen (batch_eval/rapida) intentan Ollama primero,
        # mientras copiloto/codigo mantienen calidad cloud primero.
        if estr == "economy" and req.tarea in ("copiloto", "codigo"):
            return ["gemini", "openai_compat", "ollama"]
        return list(ESTRATEGIAS_ROUTING.get(estr, ESTRATEGIAS_ROUTING["cloud_first"]))

    def ejecutar(self, req: SolicitudIA) -> RespuestaIA:
        clave = construir_clave_cache(
            prompt=req.prompt,
            system_prompt=req.system_prompt,
            json_mode=req.json_mode,
            tarea=req.tarea,
            temperatura=req.temperatura,
        )

        # 1. Consultar cache L1/L2 (0 tokens, <1ms)
        if req.usar_cache and not req.forzar_proveedor:
            hit = self.cache.obtener(
                clave,
                prompt_para_semantica=req.prompt,
                tarea=req.tarea,
                json_mode=req.json_mode,
                permitir_semantica=req.permitir_cache_semantica,
            )
            if hit is not None:
                jdata = parsear_json_robusto(hit.respuesta) if req.json_mode else None
                if (not req.json_mode) or (jdata is not None):
                    self._registrar_uso_diario(hit.proveedor, hit.modelo, cache_hits=1)
                    self.telemetry.inc("ai.cache.hit")
                    if self.bus is not None:
                        self.bus.publicar(
                            "ai.cache.hit",
                            {"tarea": req.tarea, "modelo": hit.modelo, "semantica": hit.desde_semantica},
                            origen="ai_router",
                            nivel="info",
                        )
                    return RespuestaIA(
                        ok=True,
                        texto=hit.respuesta,
                        json_data=jdata,
                        proveedor=hit.proveedor,
                        modelo=hit.modelo,
                        tokens_in=hit.tokens_in,
                        tokens_out=hit.tokens_out,
                        latencia_ms=0.2,
                        desde_cache=True,
                        cache_semantica=hit.desde_semantica,
                    )

        # 2. Determinar cadena de proveedores + verificar Budget Guard cloud
        orden = self._orden_proveedores(req)
        usados_cloud = self.tokens_cloud_usados_hoy()
        cloud_agotado = usados_cloud >= self.budget_tokens_cloud_dia
        if cloud_agotado and self.bus is not None:
            self.bus.publicar(
                "ai.budget.exceeded",
                {"usados_hoy": usados_cloud, "limite": self.budget_tokens_cloud_dia},
                origen="ai_router",
                nivel="warn",
            )

        fallbacks: list[str] = []
        errores: list[str] = []

        for prov_nom in orden:
            if cloud_agotado and prov_nom != "ollama" and not req.forzar_proveedor:
                fallbacks.append(f"{prov_nom}:budget_limit")
                continue

            prov = self.proveedores.get(prov_nom)
            if prov is None:
                continue
            if hasattr(prov, "esta_configurado") and not prov.esta_configurado():
                continue

            resp = prov.generar(req)
            if resp.ok:
                if req.json_mode:
                    jdata = parsear_json_robusto(resp.texto)
                    if jdata is None:
                        # El modelo devolvio texto invalido en modo JSON -> intentar siguiente proveedor
                        self._registrar_uso_diario(prov_nom, resp.modelo, llamadas=1, errores=1, latencia_ms=resp.latencia_ms)
                        fallbacks.append(f"{prov_nom}:json_invalido")
                        errores.append(f"{prov_nom}({resp.modelo}): JSON invalido")
                        continue
                    resp.json_data = jdata

                resp.fallbacks_usados = list(fallbacks)
                if req.usar_cache and req.cache_ttl_seg > 0:
                    self.cache.guardar(
                        clave_hash=clave,
                        proveedor=resp.proveedor,
                        modelo=resp.modelo,
                        prompt=req.prompt,
                        respuesta=resp.texto,
                        tokens_in=resp.tokens_in,
                        tokens_out=resp.tokens_out,
                        ttl_seg=req.cache_ttl_seg,
                        tarea=req.tarea,
                        json_mode=req.json_mode,
                    )

                self._registrar_uso_diario(
                    resp.proveedor,
                    resp.modelo,
                    llamadas=1,
                    tokens_in=resp.tokens_in,
                    tokens_out=resp.tokens_out,
                    latencia_ms=resp.latencia_ms,
                )
                self.telemetry.registrar_latencia("ai", f"{resp.proveedor}.{resp.modelo}", resp.latencia_ms, exito=True)
                if self.bus is not None:
                    self.bus.publicar(
                        "ai.request.ok",
                        {
                            "proveedor": resp.proveedor,
                            "modelo": resp.modelo,
                            "tarea": req.tarea,
                            "tokens": resp.tokens_in + resp.tokens_out,
                            "latencia_ms": resp.latencia_ms,
                            "fallbacks": fallbacks,
                        },
                        origen="ai_router",
                        nivel="ok",
                    )
                return resp

            # Fallo del proveedor -> log y continuar cadena de fallback
            self._registrar_uso_diario(prov_nom, resp.modelo or "default", llamadas=1, errores=1, latencia_ms=resp.latencia_ms)
            self.telemetry.registrar_latencia("ai", prov_nom, resp.latencia_ms, exito=False)
            fallbacks.append(f"{prov_nom}:error")
            errores.append(f"{prov_nom}: {resp.error}")
            if self.bus is not None:
                self.bus.publicar(
                    "ai.fallback",
                    {"proveedor": prov_nom, "tarea": req.tarea, "error": resp.error[:140]},
                    origen="ai_router",
                    nivel="warn",
                )

        err_final = " | ".join(errores) or "Ningun proveedor IA disponible"
        if self.bus is not None:
            self.bus.publicar("ai.error", {"tarea": req.tarea, "error": err_final[:200]}, origen="ai_router", nivel="error")
        return RespuestaIA(ok=False, fallbacks_usados=fallbacks, error=err_final)

    # ==================== ATAJOS ERGONOMICOS ====================
    def generar_texto(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        temperatura: float = 0.25,
        json_mode: bool = False,
        timeout: float = 28.0,
        tarea: str = "general",
        usar_cache: bool = True,
        cache_ttl_seg: float = 21600.0,
    ) -> str | None:
        resp = self.ejecutar(
            SolicitudIA(
                prompt=prompt,
                system_prompt=system_prompt,
                temperatura=temperatura,
                json_mode=json_mode,
                timeout_seg=timeout,
                tarea=tarea,
                usar_cache=usar_cache,
                cache_ttl_seg=cache_ttl_seg,
            )
        )
        return resp.texto if resp.ok else None

    def generar_json(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        temperatura: float = 0.2,
        timeout: float = 24.0,
        tarea: str = "rapida",
        usar_cache: bool = True,
    ) -> dict[str, Any] | None:
        resp = self.ejecutar(
            SolicitudIA(
                prompt=prompt,
                system_prompt=system_prompt,
                temperatura=temperatura,
                json_mode=True,
                timeout_seg=timeout,
                tarea=tarea,
                usar_cache=usar_cache,
                cache_ttl_seg=14400.0,
            )
        )
        return resp.json_data if (resp.ok and isinstance(resp.json_data, dict)) else None

    def generar_json_lote(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        temperatura: float = 0.2,
        timeout: float = 34.0,
        usar_cache: bool = True,
    ) -> Any:
        resp = self.ejecutar(
            SolicitudIA(
                prompt=prompt,
                system_prompt=system_prompt,
                temperatura=temperatura,
                json_mode=True,
                max_tokens=3072,
                timeout_seg=timeout,
                tarea="batch_eval",
                usar_cache=usar_cache,
                cache_ttl_seg=10800.0,
            )
        )
        return resp.json_data if resp.ok else None

    def resumen_uso_diario(self, dias: int = 7) -> list[dict[str, Any]]:
        if not self.usar_sqlite or self.db is None:
            return []
        return self.db.consultar_todos(
            """
            SELECT fecha, proveedor, modelo, llamadas, cache_hits, errores,
                   tokens_in, tokens_out,
                   ROUND(latencia_total_ms / CASE WHEN llamadas > 0 THEN llamadas ELSE 1 END, 1) AS latencia_avg_ms
            FROM ai_uso_diario
            ORDER BY fecha DESC, (tokens_in + tokens_out) DESC
            LIMIT ?
            """,
            (max(1, int(dias)) * 10,),
        )

    def estado_salud(self) -> dict[str, Any]:
        usados = self.tokens_cloud_usados_hoy()
        return {
            "estrategia": self.estrategia_default,
            "budget_cloud_hoy": {
                "usados": usados,
                "limite": self.budget_tokens_cloud_dia,
                "pct": round((usados / max(1, self.budget_tokens_cloud_dia)) * 100.0, 1),
            },
            "proveedores": {k: p.estado() for k, p in self.proveedores.items()},
            "cache": self.cache.estadisticas(),
            "uso_reciente": self.resumen_uso_diario(5),
        }


_ROUTER_LOCK = threading.RLock()
_ROUTER_SINGLETON: TitanAIRouter | None = None


def obtener_ai_router() -> TitanAIRouter:
    global _ROUTER_SINGLETON
    with _ROUTER_LOCK:
        if _ROUTER_SINGLETON is None:
            estr = "cloud_first"
            budget = 800_000
            try:
                from core_ia import cargar_config, safe_int
                cfg = cargar_config()
                estr = str(cfg.get("ai_estrategia") or "cloud_first")
                budget = safe_int(cfg.get("ai_budget_tokens_dia", 800_000), 800_000)
            except Exception:
                pass
            _ROUTER_SINGLETON = TitanAIRouter(estrategia_default=estr, budget_tokens_cloud_dia=budget)
        return _ROUTER_SINGLETON