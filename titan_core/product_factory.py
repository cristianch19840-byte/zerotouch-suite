from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from titan_core.ai_providers import SolicitudIA
from titan_core.ai_router import TitanAIRouter, obtener_ai_router
from titan_core.code_sanitizer import CodeSanitizer, ReporteSanitizacion
from titan_core.db_engine import ROOT_DIR, TitanDBEngine, obtener_db_engine
from titan_core.event_bus import TitanEventBus, obtener_event_bus
from titan_core.license_engine import TitanLicenseEngine, obtener_license_engine
from titan_core.sandbox_runner import auditar_codigo_ast


DEFAULT_PRODUCTS_DIR = os.path.join(ROOT_DIR, "productos_whop")


def slugify_producto(nombre: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (nombre or "tool").strip().lower()).strip("-")
    return s[:48] or "zerotouch-tool"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_archivo(ruta: str) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _cargar_marca_factory() -> dict[str, str]:
    info = {
        "marca": "ZeroTouch Automation Studio",
        "github": "https://github.com",
        "whop": "https://whop.com",
    }
    try:
        from core_ia import cargar_config
        cfg = cargar_config()
        info["marca"] = str(cfg.get("nombre_marca") or info["marca"])
        info["github"] = str(cfg.get("github_url") or info["github"])
        info["whop"] = str(cfg.get("whop_url") or info["whop"])
    except Exception:
        pass
    return info


@dataclass(slots=True)
class EspecificacionProducto:
    nombre: str
    version: str = "1.0.0"
    descripcion_corta: str = "Automated Python workflow tool ready for production."
    precio_starter_usd: float = 29.0
    precio_pro_usd: float = 79.0
    precio_agency_usd: float = 199.0
    licencia_tipo: str = "Commercial-Single"  # Commercial-Single | Commercial-Agency | MIT
    incluir_license_guard: bool = True
    generar_marketing_ia: bool = True
    autor: str = ""
    url_soporte: str = ""
    slug: str = ""

    def __post_init__(self) -> None:
        if not self.slug:
            self.slug = slugify_producto(self.nombre)


@dataclass(slots=True)
class ResultadoFactory:
    ok: bool
    producto_id: int | None
    slug: str
    nombre: str
    version: str
    carpeta_salida: str = ""
    ruta_zip: str = ""
    sha256_zip: str = ""
    tamano_zip_bytes: int = 0
    archivos_empaquetados: list[str] = field(default_factory=list)
    sanitizacion: ReporteSanitizacion | None = None
    marketing_kit: dict[str, Any] = field(default_factory=dict)
    ruta_marketing_md: str = ""
    licencia_demo: dict[str, Any] | None = None
    advertencias_ast: list[str] = field(default_factory=list)
    duracion_ms: float = 0.0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "producto_id": self.producto_id,
            "slug": self.slug,
            "nombre": self.nombre,
            "version": self.version,
            "carpeta_salida": self.carpeta_salida,
            "ruta_zip": self.ruta_zip,
            "sha256_zip": self.sha256_zip,
            "tamano_zip_kb": round(self.tamano_zip_bytes / 1024.0, 2),
            "archivos_empaquetados": self.archivos_empaquetados,
            "sanitizacion": self.sanitizacion.to_dict() if self.sanitizacion else None,
            "marketing_kit": self.marketing_kit,
            "ruta_marketing_md": self.ruta_marketing_md,
            "licencia_demo": self.licencia_demo,
            "advertencias_ast": self.advertencias_ast,
            "duracion_ms": round(self.duracion_ms, 2),
            "error": self.error,
        }


# ==================== GENERADORES DE ARTEFACTOS COMERCIALES ====================
def _generar_bat_windows(nombre: str, tiene_reqs: bool) -> str:
    paso_pip = 'echo [2/3] Installing dependencies...\n".venv\\Scripts\\python.exe" -m pip install -q --upgrade pip\n".venv\\Scripts\\python.exe" -m pip install -q -r requirements.txt\n' if tiene_reqs else 'echo [2/3] Zero external dependencies needed.\n'
    return (
        "@echo off\r\n"
        f"title {nombre}\r\n"
        "setlocal\r\n"
        "cd /d \"%~dp0\"\r\n"
        "echo ======================================================\r\n"
        f"echo   {nombre} - Commercial Launcher\r\n"
        "echo ======================================================\r\n"
        "if not exist \".venv\\Scripts\\python.exe\" (\r\n"
        "    echo [1/3] Creating isolated Python virtual environment...\r\n"
        "    python -m venv .venv || (echo [ERROR] Install Python 3.10+ from python.org & pause & exit /b 1)\r\n"
        ")\r\n"
        + paso_pip.replace("\n", "\r\n")
        + "if not exist \"config.json\" if exist \"config.example.json\" (\r\n"
        "    copy /Y \"config.example.json\" \"config.json\" >nul\r\n"
        "    echo [INFO] Created config.json from template. Edit it with your keys if needed.\r\n"
        ")\r\n"
        "echo [3/3] Starting application...\r\n"
        "\".venv\\Scripts\\python.exe\" main.py %*\r\n"
        "echo.\r\n"
        "pause\r\n"
    )


def _generar_sh_unix(nombre: str, tiene_reqs: bool) -> str:
    paso_pip = 'echo "[2/3] Installing dependencies..."\n.venv/bin/python -m pip install -q -r requirements.txt\n' if tiene_reqs else 'echo "[2/3] Zero external dependencies needed."\n'
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "cd \"$(dirname \"$0\")\"\n"
        f"echo '=== {nombre} ==='\n"
        "if [ ! -x .venv/bin/python ]; then\n"
        "  echo '[1/3] Creating virtual environment...'\n"
        "  python3 -m venv .venv\n"
        "fi\n"
        + paso_pip
        + "if [ ! -f config.json ] && [ -f config.example.json ]; then\n"
        "  cp config.example.json config.json\n"
        "  echo '[INFO] Created config.json from config.example.json'\n"
        "fi\n"
        "echo '[3/3] Launching...'\n"
        ".venv/bin/python main.py \"$@\"\n"
    )


def _generar_license_txt(spec: EspecificacionProducto, marca: str) -> str:
    anio = datetime.now(timezone.utc).year
    if spec.licencia_tipo == "MIT":
        return (
            f"MIT License\n\nCopyright (c) {anio} {marca}\n\n"
            "Permission is hereby granted, free of charge, to any person obtaining a copy "
            "of this software and associated documentation files, to deal in the Software without restriction.\n"
        )
    alcance = (
        "up to 10 client projects / team seats under one agency entity"
        if spec.licencia_tipo == "Commercial-Agency"
        else "1 individual operator / 1 workstation"
    )
    return (
        f"COMMERCIAL SOFTWARE LICENSE — {spec.nombre} v{spec.version}\n"
        f"Copyright (c) {anio} {marca}. All rights reserved.\n\n"
        f"1. GRANT: Upon valid purchase, you receive a non-exclusive, non-transferable license for {alcance}.\n"
        "2. RESTRICTIONS: Redistribution, resale, public upload, or sharing of license keys is strictly prohibited.\n"
        "3. WARRANTY: Provided 'AS IS'. Support is provided via the official store channel.\n"
    )


def _generar_readme_md(
    spec: EspecificacionProducto,
    san: ReporteSanitizacion,
    marca: str,
) -> str:
    reqs_md = "\n".join(f"- `{r}`" for r in san.requisitos_pip) if san.requisitos_pip else "- Pure Python 3.10+ Standard Library (no external packages)"
    cfg_rows = "\n".join(f"| `{k}` | `{v}` |" for k, v in san.variables_config.items()) if san.variables_config else "| `output_dir` | `./output` |"
    lic_sec = (
        "\n## License Activation (Offline)\n"
        "Paste your `ZT1....` license key in `config.json` under `\"license_key\"`, inside a `license.key` file, "
        "or export `PRODUCT_LICENSE_KEY`.\n"
        if spec.incluir_license_guard else ""
    )
    return (
        f"# {spec.nombre} (v{spec.version})\n\n"
        f"> {spec.descripcion_corta}\n\n"
        f"Built by **{marca}**.\n\n"
        "## Quick Start (1-Click)\n"
        "- **Windows:** Double-click `RUN_WINDOWS.bat`\n"
        "- **macOS / Linux:** Run `chmod +x run_unix.sh && ./run_unix.sh`\n\n"
        "## Requirements\n"
        f"- Python 3.10+\n{reqs_md}\n\n"
        "## Configuration (`config.json`)\n"
        "Copy `config.example.json` to `config.json` and fill in your settings:\n\n"
        "| Key | Example |\n|---|---|\n"
        f"{cfg_rows}\n"
        f"{lic_sec}\n"
        "## Integrity Verification\n"
        "Every file in this release is indexed with SHA-256 checksums in `MANIFEST_SHA256.json`.\n"
    )


def _generar_changelog_md(spec: EspecificacionProducto, san: ReporteSanitizacion) -> str:
    fecha = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return (
        f"# Changelog — {spec.nombre}\n\n"
        f"## [v{spec.version}] - {fecha}\n"
        "- Initial commercial release packaged with ZeroTouch TITAN Factory v16.0.\n"
        f"- Automated dependency manifest ({len(san.requisitos_pip)} third-party package(s)).\n"
        f"- Security scrub applied ({len(san.hallazgos)} hardcoded credential/path item(s) externalized to config.json).\n"
        + ("- Embedded offline HMAC-SHA256 license verifier (`license_guard.py`).\n" if spec.incluir_license_guard else "")
    )


def _inyectar_guard_en_codigo(codigo: str) -> str:
    hook = (
        "# --- ZeroTouch Offline License Enforcement ---\n"
        "from license_guard import require_valid_license as _zt_require_license\n"
        "_ZT_LICENSE_INFO = _zt_require_license()\n"
        "# ---------------------------------------------\n"
    )
    return CodeSanitizer._inyectar_bloque_tras_future(codigo, hook)


def _marketing_fallback(spec: EspecificacionProducto, san: ReporteSanitizacion) -> dict[str, Any]:
    reqs = ", ".join(san.requisitos_pip[:5]) or "Pure Python 3.12"
    return {
        "titulo_whop": f"{spec.nombre} — Automated Python Tool (1-Click Setup)",
        "subtitulo": spec.descripcion_corta,
        "tagline_producthunt": f"Save hours every week with {spec.nombre} ({reqs}).",
        "beneficios": [
            "1-click isolated virtual environment launcher for Windows, macOS & Linux",
            "Zero hardcoded secrets — clean config.json setup in under 60 seconds",
            "SHA-256 verified release manifest & production-ready Python source code",
            f"Powered by {reqs} with clean error handling",
        ],
        "planes_precio": [
            {"plan": "Starter", "precio_usd": spec.precio_starter_usd, "incluye": "Single workstation license + full script + launchers"},
            {"plan": "Pro", "precio_usd": spec.precio_pro_usd, "incluye": "Lifetime updates + priority setup guide + commercial use"},
            {"plan": "Agency", "precio_usd": spec.precio_agency_usd, "incluye": "Up to 10 team/client seats + white-label customization"},
        ],
        "faq": [
            {"q": "Do I need coding experience?", "a": "No. Double-click RUN_WINDOWS.bat (or run_unix.sh) and edit config.json."},
            {"q": "Does it run locally on my PC?", "a": "Yes, 100% locally with zero monthly cloud lock-in."},
            {"q": "How do license keys work?", "a": "Offline HMAC-SHA256 key verification — works without sending your private data anywhere."},
        ],
        "guion_short_30s": (
            f"[0-4s HOOK] Still doing this manually? Watch {spec.nombre} finish it in seconds.\n"
            "[4-14s DEMO] Drop your settings in config.json, double-click RUN_WINDOWS.bat, and let Python handle the heavy lifting.\n"
            "[14-24s PRUEBA] Clean export, zero monthly SaaS tax, runs 100% on your own machine.\n"
            f"[24-30s CTA] Grab {spec.nombre} on Whop (link in bio) starting at ${int(spec.precio_starter_usd)}."
        ),
        "origen": "fallback_determinista",
    }


def _render_marketing_md(spec: EspecificacionProducto, mkt: dict[str, Any]) -> str:
    bens = "\n".join(f"- {b}" for b in (mkt.get("beneficios") or []))
    planes = "\n".join(
        f"| {p.get('plan','')} | ${p.get('precio_usd',0)} USD | {p.get('incluye','')} |"
        for p in (mkt.get("planes_precio") or [])
    )
    faqs = "\n".join(f"**Q: {f.get('q','')}**\nA: {f.get('a','')}\n" for f in (mkt.get("faq") or []))
    return (
        f"# Marketing Kit — {spec.nombre} v{spec.version}\n\n"
        f"## Whop / Gumroad Headline\n**{mkt.get('titulo_whop', spec.nombre)}**\n\n"
        f"{mkt.get('subtitulo', spec.descripcion_corta)}\n\n"
        f"**ProductHunt Tagline:** {mkt.get('tagline_producthunt', '')}\n\n"
        f"## Key Benefits\n{bens}\n\n"
        f"## Pricing Tiers\n| Tier | Price | Includes |\n|---|---|---|\n{planes}\n\n"
        f"## FAQ\n{faqs}\n"
        f"## 30s TikTok / Reels / Shorts Script\n```\n{mkt.get('guion_short_30s', '')}\n```\n"
    )


# ==================== ORQUESTADOR PRINCIPAL: WHOP / SAAS FACTORY v16 ====================
class TitanProductFactory:
    """
    Fabrica de Productos Digitales Comerciales (Whop / Gumroad / LemonSqueezy):
    - Sanitizacion AST forense anti-fuga de credenciales y rutas privadas
    - Generacion automatica de requirements.txt, config.example.json, launchers .bat/.sh, README, LICENSE, CHANGELOG
    - Inyeccion opcional de verificador de licencias offline HMAC-SHA256 (license_guard.py)
    - Empaquetado .ZIP determinista con MANIFEST_SHA256.json y verificador de integridad
    - Generacion de Marketing Kit via TitanAIRouter (con fallback determinista 0-tokens)
    - Persistencia completa en SQLite ('productos_factory') + EventBus
    """

    SYSTEM_MARKETING = (
        "Eres un copywriter SaaS experto en productos digitales de automatizacion para Whop y Gumroad. "
        "Devuelve UNICAMENTE JSON valido con claves exactas: titulo_whop, subtitulo, tagline_producthunt, "
        "beneficios (lista de 4 strings), planes_precio (lista de 3 dicts con plan/precio_usd/incluye), "
        "faq (lista de 3 dicts con q/a), guion_short_30s (string con timestamps 0-30s)."
    )

    def __init__(
        self,
        db: TitanDBEngine | None = None,
        bus: TitanEventBus | None = None,
        ai_router: TitanAIRouter | None = None,
        license_engine: TitanLicenseEngine | None = None,
        sanitizer: CodeSanitizer | None = None,
        carpeta_salida: str | None = None,
        usar_sqlite: bool = True,
    ) -> None:
        self._lock = threading.RLock()
        self.usar_sqlite = usar_sqlite
        self.db = db if db is not None else (obtener_db_engine() if usar_sqlite else None)
        self.bus = bus if bus is not None else obtener_event_bus()
        self.ai_router = ai_router or obtener_ai_router()
        self.license_engine = license_engine or TitanLicenseEngine(db=self.db, bus=self.bus, usar_sqlite=usar_sqlite)
        self.sanitizer = sanitizer or CodeSanitizer()
        self.carpeta_salida = os.path.abspath(carpeta_salida or DEFAULT_PRODUCTS_DIR)
        self._esquema_ok = False
        if self.usar_sqlite and self.db is not None:
            self._asegurar_esquema()

    def _asegurar_esquema(self) -> None:
        if self._esquema_ok or self.db is None:
            return
        with self.db.transaccion() as tx:
            tx.execute(
                """
                CREATE TABLE IF NOT EXISTS productos_factory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slug TEXT NOT NULL,
                    nombre TEXT NOT NULL,
                    version TEXT NOT NULL,
                    precio_usd REAL DEFAULT 29.0,
                    licencia_tipo TEXT DEFAULT 'Commercial-Single',
                    tiene_license_guard INTEGER DEFAULT 1,
                    ruta_zip TEXT NOT NULL,
                    sha256_zip TEXT NOT NULL,
                    tamano_bytes INTEGER DEFAULT 0,
                    requisitos_json TEXT DEFAULT '[]',
                    marketing_json TEXT DEFAULT '{}',
                    sanitizacion_json TEXT DEFAULT '{}',
                    creado_ts DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            tx.execute("CREATE INDEX IF NOT EXISTS idx_prod_slug ON productos_factory(slug, version)")
        self._esquema_ok = True

    def _generar_marketing_kit(self, spec: EspecificacionProducto, san: ReporteSanitizacion) -> dict[str, Any]:
        if not spec.generar_marketing_ia:
            return _marketing_fallback(spec, san)

        prompt = (
            f"PRODUCTO: {spec.nombre} v{spec.version}\n"
            f"DESCRIPCION: {spec.descripcion_corta}\n"
            f"PRECIOS SUGERIDOS: Starter=${spec.precio_starter_usd}, Pro=${spec.precio_pro_usd}, Agency=${spec.precio_agency_usd}\n"
            f"DEPENDENCIAS: {', '.join(san.requisitos_pip) or 'Python Stdlib'}\n"
            f"CONFIG KEYS: {', '.join(san.variables_config.keys()) or 'output_dir'}\n"
            f"PREVIEW CODIGO:\n{san.codigo_limpio[:1400]}\n"
        )
        resp = self.ai_router.ejecutar(
            SolicitudIA(
                prompt=prompt,
                system_prompt=self.SYSTEM_MARKETING,
                temperatura=0.4,
                json_mode=True,
                max_tokens=1500,
                timeout_seg=25.0,
                tarea="copiloto",
                usar_cache=True,
                cache_ttl_seg=21600.0,
            )
        )
        if resp.ok and isinstance(resp.json_data, dict) and resp.json_data.get("titulo_whop"):
            mkt = dict(resp.json_data)
            mkt["origen"] = f"{resp.proveedor}/{resp.modelo}"
            return mkt
        return _marketing_fallback(spec, san)

    def construir_producto(
        self,
        spec: EspecificacionProducto,
        *,
        codigo_fuente: str = "",
        ruta_script: str = "",
        emitir_licencia_demo: bool = True,
    ) -> ResultadoFactory:
        t0 = time.perf_counter()
        raw_code = codigo_fuente
        if not raw_code and ruta_script:
            ruta_abs = os.path.abspath(ruta_script if os.path.isabs(ruta_script) else os.path.join(ROOT_DIR, ruta_script))
            if not os.path.isfile(ruta_abs):
                return ResultadoFactory(False, None, spec.slug, spec.nombre, spec.version, error=f"Script no encontrado: {ruta_script}")
            with open(ruta_abs, "r", encoding="utf-8", errors="replace") as f:
                raw_code = f.read()

        if not raw_code or not raw_code.strip():
            return ResultadoFactory(False, None, spec.slug, spec.nombre, spec.version, error="Codigo fuente vacio")

        # 1. Sanitizacion Forense AST (elimina secretos/rutas personales y detecta requirements)
        san = self.sanitizer.sanitizar(raw_code)
        if not san.ast_valido:
            return ResultadoFactory(
                False, None, spec.slug, spec.nombre, spec.version,
                sanitizacion=san, error=san.error_sintaxis or "Codigo fuente con sintaxis invalida",
            )

        # 2. Auditoria AST informativa (advertencias de seguridad)
        aud = auditar_codigo_ast(san.codigo_limpio)
        advertencias = [f"L{h.linea}: {h.descripcion}" for h in aud.hallazgos]

        # 3. Preparar codigo final + license_guard opcional
        codigo_main = _inyectar_guard_en_codigo(san.codigo_limpio) if spec.incluir_license_guard else san.codigo_limpio
        marca_info = _cargar_marca_factory()
        marca = spec.autor or marca_info["marca"]

        # 4. Armar diccionario de archivos del paquete
        cfg_example: dict[str, Any] = {}
        if spec.incluir_license_guard:
            cfg_example["license_key"] = "PASTE_YOUR_ZT1_LICENSE_KEY_HERE"
        for k, v in san.variables_config.items():
            cfg_example[k] = v
        cfg_example.setdefault("output_dir", "./output")

        reqs_txt = "\n".join(san.requisitos_pip) + ("\n" if san.requisitos_pip else "")
        archivos: dict[str, bytes] = {
            "main.py": codigo_main.encode("utf-8"),
            "config.example.json": (json.dumps(cfg_example, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
            "requirements.txt": reqs_txt.encode("utf-8"),
            "RUN_WINDOWS.bat": _generar_bat_windows(spec.nombre, bool(san.requisitos_pip)).encode("utf-8"),
            "run_unix.sh": _generar_sh_unix(spec.nombre, bool(san.requisitos_pip)).encode("utf-8"),
            "README.md": _generar_readme_md(spec, san, marca).encode("utf-8"),
            "LICENSE.txt": _generar_license_txt(spec, marca).encode("utf-8"),
            "CHANGELOG.md": _generar_changelog_md(spec, san).encode("utf-8"),
        }
        if spec.incluir_license_guard:
            guard_src = self.license_engine.generar_modulo_license_guard(spec.slug, spec.nombre)
            archivos["license_guard.py"] = guard_src.encode("utf-8")

        # 5. Manifest SHA-256 de todos los archivos del release
        manifest = {
            "product": spec.nombre,
            "slug": spec.slug,
            "version": spec.version,
            "built_utc": datetime.now(timezone.utc).isoformat(),
            "files": {
                fname: {"sha256": _sha256_bytes(content), "bytes": len(content)}
                for fname, content in sorted(archivos.items())
            },
        }
        archivos["MANIFEST_SHA256.json"] = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

        # 6. Escribir carpeta release + .ZIP determinista
        ver_clean = re.sub(r"[^0-9A-Za-z._\-]", "", spec.version) or "1.0.0"
        carpeta_rel = os.path.join(self.carpeta_salida, f"{spec.slug}_v{ver_clean}")
        os.makedirs(carpeta_rel, exist_ok=True)
        ruta_zip = os.path.join(carpeta_rel, f"{spec.slug}_v{ver_clean}.zip")

        with zipfile.ZipFile(ruta_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for fname in sorted(archivos.keys()):
                zi = zipfile.ZipInfo(fname, date_time=(2026, 1, 1, 0, 0, 0))
                zi.compress_type = zipfile.ZIP_DEFLATED
                if fname.endswith(".sh"):
                    zi.external_attr = 0o755 << 16
                zf.writestr(zi, archivos[fname])

        sha_zip = _sha256_archivo(ruta_zip)
        tam_zip = os.path.getsize(ruta_zip)

        # 7. Marketing Kit (se guarda FUERA del ZIP del cliente para uso del vendedor en Whop/Gumroad)
        mkt = self._generar_marketing_kit(spec, san)
        ruta_mkt = os.path.join(carpeta_rel, "MARKETING_KIT.md")
        with open(ruta_mkt, "w", encoding="utf-8", newline="\n") as f:
            f.write(_render_marketing_md(spec, mkt))

        # 8. Licencia demo opcional lista para pruebas
        lic_demo = None
        if spec.incluir_license_guard and emitir_licencia_demo:
            lic_demo = self.license_engine.emitir_licencia(
                spec.slug, "owner_demo", tier="pro", dias_validez=30, notas="Licencia demo auto-generada",
            )

        # 9. Persistencia SQLite + EventBus
        prod_id: int | None = None
        if self.usar_sqlite and self.db is not None:
            self._asegurar_esquema()
            prod_id = self.db.ejecutar(
                """
                INSERT INTO productos_factory (
                    slug, nombre, version, precio_usd, licencia_tipo, tiene_license_guard,
                    ruta_zip, sha256_zip, tamano_bytes, requisitos_json, marketing_json, sanitizacion_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    spec.slug, spec.nombre[:120], ver_clean[:30], float(spec.precio_starter_usd),
                    spec.licencia_tipo[:40], 1 if spec.incluir_license_guard else 0,
                    ruta_zip, sha_zip, tam_zip,
                    json.dumps(san.requisitos_pip, ensure_ascii=False),
                    json.dumps(mkt, ensure_ascii=False),
                    json.dumps(san.to_dict(), ensure_ascii=False),
                ),
            )

        dur_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        if self.bus is not None:
            self.bus.publicar(
                "factory.producto.creado",
                {
                    "producto_id": prod_id,
                    "slug": spec.slug,
                    "version": ver_clean,
                    "ruta_zip": ruta_zip,
                    "secretos_removidos": len(san.hallazgos),
                    "requisitos": len(san.requisitos_pip),
                },
                origen="product_factory",
                nivel="ok",
            )

        return ResultadoFactory(
            ok=True,
            producto_id=prod_id,
            slug=spec.slug,
            nombre=spec.nombre,
            version=ver_clean,
            carpeta_salida=carpeta_rel,
            ruta_zip=ruta_zip,
            sha256_zip=sha_zip,
            tamano_zip_bytes=tam_zip,
            archivos_empaquetados=sorted(archivos.keys()),
            sanitizacion=san,
            marketing_kit=mkt,
            ruta_marketing_md=ruta_mkt,
            licencia_demo=lic_demo,
            advertencias_ast=advertencias,
            duracion_ms=dur_ms,
        )

    @staticmethod
    def verificar_paquete_zip(ruta_zip: str) -> dict[str, Any]:
        """Valida criptograficamente cada archivo dentro del .ZIP contra MANIFEST_SHA256.json."""
        if not os.path.isfile(ruta_zip):
            return {"ok": False, "error": f"ZIP no encontrado: {ruta_zip}"}
        try:
            with zipfile.ZipFile(ruta_zip, "r") as zf:
                if "MANIFEST_SHA256.json" not in zf.namelist():
                    return {"ok": False, "error": "Falta MANIFEST_SHA256.json dentro del ZIP"}
                manifest = json.loads(zf.read("MANIFEST_SHA256.json").decode("utf-8"))
                esperados = manifest.get("files") or {}
                errores: list[str] = []
                verificados = 0
                for fname, meta in esperados.items():
                    if fname not in zf.namelist():
                        errores.append(f"Archivo faltante: {fname}")
                        continue
                    data = zf.read(fname)
                    sha_real = _sha256_bytes(data)
                    if sha_real != meta.get("sha256"):
                        errores.append(f"Hash corrupto en {fname}")
                    else:
                        verificados += 1
                return {
                    "ok": len(errores) == 0,
                    "slug": manifest.get("slug", ""),
                    "version": manifest.get("version", ""),
                    "verificados": verificados,
                    "errores": errores,
                    "sha256_zip": _sha256_archivo(ruta_zip),
                }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def listar_productos(self, limite: int = 50) -> list[dict[str, Any]]:
        if not self.usar_sqlite or self.db is None:
            return []
        self._asegurar_esquema()
        rows = self.db.consultar_todos(
            "SELECT * FROM productos_factory ORDER BY id DESC LIMIT ?",
            (max(1, min(200, int(limite))),),
        )
        out = []
        for r in rows:
            item = dict(r)
            for k in ("requisitos_json", "marketing_json", "sanitizacion_json"):
                try:
                    item[k.replace("_json", "")] = json.loads(item.pop(k) or "{}")
                except Exception:
                    item[k.replace("_json", "")] = {}
            out.append(item)
        return out

    def eliminar_producto(self, producto_id: int, borrar_archivos: bool = False) -> bool:
        if not self.usar_sqlite or self.db is None:
            return False
        self._asegurar_esquema()
        row = self.db.consultar_uno("SELECT ruta_zip FROM productos_factory WHERE id = ?", (int(producto_id),))
        n = self.db.ejecutar("DELETE FROM productos_factory WHERE id = ?", (int(producto_id),))
        if borrar_archivos and row and row.get("ruta_zip"):
            carp = os.path.dirname(str(row["ruta_zip"]))
            if carp.startswith(self.carpeta_salida) and os.path.isdir(carp):
                shutil.rmtree(carp, ignore_errors=True)
        return n > 0


_FAC_LOCK = threading.Lock()
_FAC_SINGLETON: TitanProductFactory | None = None


def obtener_product_factory() -> TitanProductFactory:
    global _FAC_SINGLETON
    with _FAC_LOCK:
        if _FAC_SINGLETON is None:
            _FAC_SINGLETON = TitanProductFactory()
        return _FAC_SINGLETON