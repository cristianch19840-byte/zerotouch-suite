from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from titan_core.http_shield import TitanHTTPShield, obtener_http_shield


# ==================== UTILIDADES DE LIMPIEZA Y PARSEO JSON ROBUSTO ====================
REGEX_THINK_BLOCK = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
REGEX_THINK_UNCLOSED = re.compile(r"<think>[\s\S]*$", re.IGNORECASE)
REGEX_FENCE_JSON = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)
REGEX_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def limpiar_razonamiento_llm(texto: str) -> str:
    """Elimina bloques <think>...</think> generados por modelos razonadores (ej. qwen3:8b, deepseek-r1)."""
    if not texto:
        return ""
    s = REGEX_THINK_BLOCK.sub("", texto)
    if "<think>" in s.lower():
        s = REGEX_THINK_UNCLOSED.sub("", s)
    return s.strip()


def estimar_tokens(texto: str) -> int:
    if not texto:
        return 0
    return max(1, len(texto) // 4)


def parsear_json_robusto(texto: str) -> Any:
    """Extractor JSON tolerante a fences markdown, bloques <think>, texto alrededor y comas finales."""
    if not texto:
        return None
    limpio = limpiar_razonamiento_llm(texto)
    candidatos: list[str] = [limpio]

    for m in REGEX_FENCE_JSON.finditer(limpio):
        blk = m.group(1).strip()
        if blk:
            candidatos.append(blk)

    # Extraer sub-objeto {...} o sub-arreglo [...] mas externo
    for apertura, cierre in (("{", "}"), ("[", "]")):
        i0 = limpio.find(apertura)
        i1 = limpio.rfind(cierre)
        if i0 != -1 and i1 > i0:
            candidatos.append(limpio[i0:i1 + 1])

    vistos: set[str] = set()
    for cand in candidatos:
        if not cand or cand in vistos:
            continue
        vistos.add(cand)
        for variante in (cand, REGEX_TRAILING_COMMA.sub(r"\1", cand)):
            try:
                return json.loads(variante)
            except Exception:
                pass
    return None


# ==================== CONTRATOS UNIFICADOS ====================
@dataclass(slots=True)
class SolicitudIA:
    prompt: str
    system_prompt: str = ""
    temperatura: float = 0.2
    json_mode: bool = False
    max_tokens: int = 2048
    timeout_seg: float = 28.0
    tarea: str = "general"  # rapida | batch_eval | copiloto | codigo | general
    cache_ttl_seg: float = 21600.0
    usar_cache: bool = True
    permitir_cache_semantica: bool = False
    forzar_proveedor: str = ""  # "" | gemini | ollama | openai_compat


@dataclass(slots=True)
class RespuestaIA:
    ok: bool
    texto: str = ""
    json_data: Any = None
    proveedor: str = ""
    modelo: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    latencia_ms: float = 0.0
    desde_cache: bool = False
    cache_semantica: bool = False
    fallbacks_usados: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "proveedor": self.proveedor,
            "modelo": self.modelo,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "latencia_ms": round(self.latencia_ms, 2),
            "desde_cache": self.desde_cache,
            "fallbacks": self.fallbacks_usados,
            "error": self.error,
        }


# ==================== PROVEEDOR 1: GEMINI CLOUD (MULTI-KEY + CASCADA MODELOS) ====================
class ProveedorGemini:
    nombre = "gemini"

    MODELOS_DEFECTO: tuple[str, ...] = (
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-2.5-flash-lite",
    )

    def __init__(
        self,
        api_keys: list[str] | None = None,
        modelos: tuple[str, ...] | list[str] | None = None,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        shield: TitanHTTPShield | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.shield = shield or obtener_http_shield()
        self._lock = threading.Lock()
        self._cooldowns: dict[str, float] = {}  # "key_idx:modelo" -> epoch
        self._modelos_override = tuple(modelos) if modelos else None
        self._keys_override = [k.strip() for k in (api_keys or []) if k and k.strip()]

    def _obtener_keys(self) -> list[str]:
        if self._keys_override:
            return list(self._keys_override)
        bruto = ",".join(
            v for v in (
                os.getenv("GEMINI_API_KEYS", ""),
                os.getenv("GEMINI_API_KEY_FREE", ""),
                os.getenv("GEMINI_API_KEY", ""),
            ) if v
        )
        vistos: list[str] = []
        for k in bruto.split(","):
            kc = k.strip()
            if kc and kc not in vistos:
                vistos.append(kc)
        return vistos

    def _obtener_modelos(self, tarea: str) -> tuple[str, ...]:
        if self._modelos_override:
            return self._modelos_override
        env_m = (os.getenv("GEMINI_MODELS") or "").strip()
        if env_m:
            return tuple(m.strip() for m in env_m.split(",") if m.strip())
        if tarea in ("rapida", "batch_eval"):
            return ("gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.0-flash-lite", "gemini-2.0-flash")
        return self.MODELOS_DEFECTO

    def esta_configurado(self) -> bool:
        return bool(self._obtener_keys())

    def _en_cooldown(self, slot: str) -> bool:
        with self._lock:
            return self._cooldowns.get(slot, 0.0) > time.time()

    def _marcar_cooldown(self, slot: str, segs: float) -> None:
        with self._lock:
            self._cooldowns[slot] = max(self._cooldowns.get(slot, 0.0), time.time() + segs)

    def generar(self, req: SolicitudIA) -> RespuestaIA:
        keys = self._obtener_keys()
        if not keys:
            return RespuestaIA(ok=False, proveedor=self.nombre, error="Sin GEMINI_API_KEY configurada")

        modelos = self._obtener_modelos(req.tarea)
        errores: list[str] = []
        t_global = time.perf_counter()

        gen_cfg: dict[str, Any] = {
            "temperature": max(0.0, min(1.5, float(req.temperatura))),
            "maxOutputTokens": max(128, int(req.max_tokens)),
        }
        if req.json_mode:
            gen_cfg["responseMimeType"] = "application/json"

        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": req.prompt}]}],
            "generationConfig": gen_cfg,
        }
        if req.system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": req.system_prompt}]}

        for k_idx, api_key in enumerate(keys):
            for modelo in modelos:
                slot = f"k{k_idx}:{modelo}"
                if self._en_cooldown(slot):
                    continue

                url = f"{self.base_url}/models/{modelo}:generateContent"
                t0 = time.perf_counter()
                data, resp = self.shield.post_json(
                    url,
                    payload,
                    params={"key": api_key},
                    timeout=req.timeout_seg,
                    reintentos=0,
                    perfil_headers="api",
                    usar_etag=False,
                    cache_ttl_seg=0.0,
                )
                lat_ms = (time.perf_counter() - t0) * 1000.0

                if resp.ok and isinstance(data, dict):
                    cands = data.get("candidates") or []
                    partes = ((cands[0].get("content") or {}).get("parts") or []) if cands else []
                    txt = "".join(str(p.get("text") or "") for p in partes).strip()
                    if txt:
                        usage = data.get("usageMetadata") or {}
                        t_in = int(usage.get("promptTokenCount") or estimar_tokens(req.prompt))
                        t_out = int(usage.get("candidatesTokenCount") or estimar_tokens(txt))
                        return RespuestaIA(
                            ok=True,
                            texto=limpiar_razonamiento_llm(txt),
                            proveedor=self.nombre,
                            modelo=modelo,
                            tokens_in=t_in,
                            tokens_out=t_out,
                            latencia_ms=round(lat_ms, 2),
                        )
                    errores.append(f"{modelo}: respuesta vacia")
                    continue

                code = resp.status_code
                if code == 429:
                    self._marcar_cooldown(slot, 65.0)
                    errores.append(f"{slot} HTTP 429 (cooldown 65s)")
                elif code == 404:
                    self._marcar_cooldown(slot, 3600.0)
                    errores.append(f"{slot} HTTP 404 (modelo no disp.)")
                elif code in (401, 403):
                    # Llave invalida -> cooldown largo a todos los modelos de esa llave
                    for m_all in modelos:
                        self._marcar_cooldown(f"k{k_idx}:{m_all}", 1800.0)
                    errores.append(f"k{k_idx} HTTP {code} (key rechazada)")
                    break
                else:
                    self._marcar_cooldown(slot, 15.0)
                    errores.append(f"{slot} {resp.error or f'HTTP {code}'}")

        return RespuestaIA(
            ok=False,
            proveedor=self.nombre,
            latencia_ms=round((time.perf_counter() - t_global) * 1000.0, 2),
            error=" | ".join(errores[:4]) or "Todos los modelos Gemini en cooldown",
        )

    def estado(self) -> dict[str, Any]:
        ahora = time.time()
        with self._lock:
            activos_cd = {k: round(v - ahora, 1) for k, v in self._cooldowns.items() if v > ahora}
        return {
            "proveedor": self.nombre,
            "configurado": self.esta_configurado(),
            "keys_count": len(self._obtener_keys()),
            "cooldowns": activos_cd,
        }


# ==================== PROVEEDOR 2: OLLAMA LOCAL (QWEN3:8B / LLAMA / MISTRAL — 0 COSTO) ====================
class ProveedorOllama:
    nombre = "ollama"

    def __init__(
        self,
        base_url: str | None = None,
        modelo: str | None = None,
        shield: TitanHTTPShield | None = None,
    ) -> None:
        self._url_override = base_url.rstrip("/") if base_url else None
        self._modelo_override = modelo
        self.shield = shield or obtener_http_shield()
        self._lock = threading.Lock()
        self._salud_cache: tuple[bool, list[str], float] = (False, [], 0.0)

    def _base_url(self) -> str:
        return (self._url_override or os.getenv("OLLAMA_URL") or "http://127.0.0.1:11434").rstrip("/")

    def _modelo_deseado(self) -> str:
        return (self._modelo_override or os.getenv("OLLAMA_MODEL") or "qwen3:8b").strip()

    def verificar_disponibilidad(self, forzar: bool = False) -> tuple[bool, list[str]]:
        ahora = time.time()
        with self._lock:
            ok_c, mods_c, ts_c = self._salud_cache
            if not forzar and (ahora - ts_c) < 45.0:
                return ok_c, list(mods_c)

        url = f"{self._base_url()}/api/tags"
        data, resp = self.shield.get_json(
            url,
            timeout=2.2,
            reintentos=0,
            perfil_headers="api",
            usar_etag=False,
            cache_ttl_seg=0.0,
            usar_rate_limit=False,
            usar_circuit_breaker=False,
        )
        ok = bool(resp.ok and isinstance(data, dict))
        modelos = [str(m.get("name") or "") for m in (data.get("models") or [])] if ok else []
        with self._lock:
            self._salud_cache = (ok, modelos, time.time())
        return ok, modelos

    def _resolver_modelo(self, instalados: list[str]) -> str:
        deseado = self._modelo_deseado()
        if not instalados:
            return deseado
        if deseado in instalados:
            return deseado
        pref = deseado.split(":")[0].lower()
        for m in instalados:
            if m.lower().startswith(pref):
                return m
        return instalados[0]

    def generar(self, req: SolicitudIA) -> RespuestaIA:
        disponible, instalados = self.verificar_disponibilidad()
        if not disponible:
            return RespuestaIA(ok=False, proveedor=self.nombre, error="Ollama local no responde en " + self._base_url())

        modelo = self._resolver_modelo(instalados)
        mensajes: list[dict[str, str]] = []
        if req.system_prompt:
            mensajes.append({"role": "system", "content": req.system_prompt})
        mensajes.append({"role": "user", "content": req.prompt})

        payload: dict[str, Any] = {
            "model": modelo,
            "messages": mensajes,
            "stream": False,
            "keep_alive": "10m",
            "options": {
                "temperature": max(0.0, min(1.5, float(req.temperatura))),
                "num_predict": max(128, int(req.max_tokens)),
            },
        }
        if req.json_mode:
            payload["format"] = "json"
            # Evita gasto excesivo de tokens internos de pensamiento en qwen3 cuando pedimos JSON estructurado
            if "qwen3" in modelo.lower():
                payload["think"] = False

        url = f"{self._base_url()}/api/chat"
        t0 = time.perf_counter()
        data, resp = self.shield.post_json(
            url,
            payload,
            timeout=max(25.0, float(req.timeout_seg) * 1.8),
            reintentos=0,
            perfil_headers="api",
            usar_etag=False,
            cache_ttl_seg=0.0,
            usar_rate_limit=False,
        )
        lat_ms = (time.perf_counter() - t0) * 1000.0

        if resp.ok and isinstance(data, dict):
            msg = data.get("message") or {}
            bruto = str(msg.get("content") or data.get("response") or "")
            txt = limpiar_razonamiento_llm(bruto)
            if txt:
                t_in = int(data.get("prompt_eval_count") or estimar_tokens(req.prompt))
                t_out = int(data.get("eval_count") or estimar_tokens(txt))
                return RespuestaIA(
                    ok=True,
                    texto=txt,
                    proveedor=self.nombre,
                    modelo=modelo,
                    tokens_in=t_in,
                    tokens_out=t_out,
                    latencia_ms=round(lat_ms, 2),
                )
            return RespuestaIA(ok=False, proveedor=self.nombre, modelo=modelo, latencia_ms=round(lat_ms, 2), error="Ollama devolvio texto vacio")

        return RespuestaIA(
            ok=False,
            proveedor=self.nombre,
            modelo=modelo,
            latencia_ms=round(lat_ms, 2),
            error=resp.error or f"Ollama HTTP {resp.status_code}",
        )

    def estado(self) -> dict[str, Any]:
        ok, mods = self.verificar_disponibilidad()
        return {
            "proveedor": self.nombre,
            "url": self._base_url(),
            "disponible": ok,
            "modelo_default": self._modelo_deseado(),
            "modelos_instalados": mods[:12],
        }


# ==================== PROVEEDOR 3: OPENAI-COMPATIBLE (GROQ / OPENROUTER / DEEPSEEK) ====================
class ProveedorOpenAICompat:
    nombre = "openai_compat"

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        modelo: str | None = None,
        shield: TitanHTTPShield | None = None,
    ) -> None:
        self._url_override = base_url.rstrip("/") if base_url else None
        self._key_override = api_key
        self._mod_override = modelo
        self.shield = shield or obtener_http_shield()

    def _cfg(self) -> tuple[str, str, str]:
        url = (self._url_override or os.getenv("OPENAI_COMPAT_URL") or "").strip().rstrip("/")
        key = (self._key_override or os.getenv("OPENAI_COMPAT_KEY") or "").strip()
        mod = (self._mod_override or os.getenv("OPENAI_COMPAT_MODEL") or "llama-3.3-70b-versatile").strip()
        return url, key, mod

    def esta_configurado(self) -> bool:
        url, key, _ = self._cfg()
        return bool(url and key)

    def generar(self, req: SolicitudIA) -> RespuestaIA:
        url, key, modelo = self._cfg()
        if not url or not key:
            return RespuestaIA(ok=False, proveedor=self.nombre, error="OPENAI_COMPAT_URL/KEY no configurados")

        mensajes: list[dict[str, str]] = []
        if req.system_prompt:
            mensajes.append({"role": "system", "content": req.system_prompt})
        mensajes.append({"role": "user", "content": req.prompt})

        payload: dict[str, Any] = {
            "model": modelo,
            "messages": mensajes,
            "temperature": max(0.0, min(1.5, float(req.temperatura))),
            "max_tokens": max(128, int(req.max_tokens)),
        }
        if req.json_mode:
            payload["response_format"] = {"type": "json_object"}

        endpoint = url if url.endswith("/chat/completions") else f"{url}/chat/completions"
        t0 = time.perf_counter()
        data, resp = self.shield.post_json(
            endpoint,
            payload,
            headers={"Authorization": f"Bearer {key}"},
            timeout=req.timeout_seg,
            reintentos=0,
            perfil_headers="api",
            usar_etag=False,
            cache_ttl_seg=0.0,
        )
        lat_ms = (time.perf_counter() - t0) * 1000.0

        if resp.ok and isinstance(data, dict):
            choices = data.get("choices") or []
            bruto = str(((choices[0].get("message") or {}).get("content") or "")) if choices else ""
            txt = limpiar_razonamiento_llm(bruto)
            if txt:
                usage = data.get("usage") or {}
                return RespuestaIA(
                    ok=True,
                    texto=txt,
                    proveedor=self.nombre,
                    modelo=modelo,
                    tokens_in=int(usage.get("prompt_tokens") or estimar_tokens(req.prompt)),
                    tokens_out=int(usage.get("completion_tokens") or estimar_tokens(txt)),
                    latencia_ms=round(lat_ms, 2),
                )
        return RespuestaIA(
            ok=False,
            proveedor=self.nombre,
            modelo=modelo,
            latencia_ms=round(lat_ms, 2),
            error=resp.error or f"HTTP {resp.status_code}",
        )

    def estado(self) -> dict[str, Any]:
        url, _, mod = self._cfg()
        return {
            "proveedor": self.nombre,
            "configurado": self.esta_configurado(),
            "url": url,
            "modelo": mod,
        }