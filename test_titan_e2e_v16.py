#!/usr/bin/env python3
"""
ZeroTouch TITAN-OS v16.0 — Suite de Verificacion End-to-End Global (Fases 1..20).
Valida integracion real entre todos los subsistemas en entorno 100% aislado (tmp_dir)
sin tocar la base de datos de produccion ni requerir internet.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import requests

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from modulo_a_radar_whop.conectores.shield_adapter import parsear_feed_xml_pro
from titan_core.ai_cache import TitanAICache
from titan_core.ai_providers import ProveedorGemini, ProveedorOllama, ProveedorOpenAICompat
from titan_core.ai_router import TitanAIRouter
from titan_core.api_v2_app import crear_app_titan_v16
from titan_core.code_sanitizer import CodeSanitizer
from titan_core.license_engine import obtener_hwid_local
from titan_core.security_hardening import EncryptedBackupVault, SecurityAuditor
from titan_core.telegram_bot_v16 import TitanTelegramBotV16
from titan_core.telegram_callbacks import encode_cb


# ==================== MOCK UNIFICADO (OLLAMA + TELEGRAM API) ====================
MOCK_STATE: dict[str, Any] = {"ai_calls": 0, "tg_calls": []}


class _UnifiedMockHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        pass

    def _json(self, code: int, obj: Any) -> None:
        raw = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        if self.path == "/api/tags":
            self._json(200, {"models": [{"name": "qwen3:8b"}]})
        else:
            self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        ln = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(ln).decode("utf-8")) if ln else {}

        if self.path == "/api/chat":
            MOCK_STATE["ai_calls"] += 1
            msgs = body.get("messages") or []
            prompt = str(msgs[-1].get("content", "")) if msgs else ""
            if "DIAGNOSTICO DEL FALLO" in prompt:
                content = '```python\ndef safe_div(a, b):\n    return a / b if b else 0\nprint("E2E_FIXED", safe_div(10, 0))\n```'
            else:
                content = json.dumps({
                    "variante_a": {
                        "enfoque": "Directo Sniper",
                        "precio_usd": 350,
                        "texto": (
                            "Hey — I can build your Python + Playwright Shopify scraper with clean CSV export and retry logic.\n\n"
                            "Delivery within 24 hours for $350 fixed (50% milestone or working 5-row sample first).\n\n"
                            "Can you share the first store URL so I can send your sample today?"
                        ),
                    },
                    "variante_b": {
                        "enfoque": "Consultivo",
                        "precio_usd": 380,
                        "texto": (
                            "Hi — I build production Python Playwright pipelines with rate-limit handling and clean JSON/CSV output.\n\n"
                            "Happy to ship a working preview within 24-48h before final payment.\n\n"
                            "Which product fields are highest priority for v1?"
                        ),
                    },
                })
            self._json(200, {
                "model": "qwen3:8b",
                "message": {"role": "assistant", "content": content},
                "prompt_eval_count": 120,
                "eval_count": 70,
            })
            return

        if "/bot" in self.path:
            metodo = self.path.rsplit("/", 1)[-1]
            MOCK_STATE["tg_calls"].append({"metodo": metodo, "body": body})
            res: Any = True
            if metodo in ("sendMessage", "editMessageText"):
                res = {"message_id": 900 + len(MOCK_STATE["tg_calls"]), "chat": {"id": body.get("chat_id")}}
            elif metodo == "getUpdates":
                res = []
            self._json(200, {"ok": True, "result": res})
            return

        self._json(404, {"error": "unknown"})


class _HTMLUniqueIDValidator(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.dups: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for k, v in attrs:
            if k == "id" and v:
                if v in self.ids:
                    self.dups.append(v)
                self.ids.add(v)


def ejecutar_suite_e2e() -> dict[str, Any]:
    t_global = time.perf_counter()
    tmp_dir = tempfile.mkdtemp(prefix="titan_e2e_v16_")
    mock_srv = ThreadingHTTPServer(("127.0.0.1", 0), _UnifiedMockHandler)
    mock_port = mock_srv.server_address[1]
    threading.Thread(target=mock_srv.serve_forever, daemon=True).start()
    mock_base = f"http://127.0.0.1:{mock_port}"

    srv = None
    svc = None
    resultados: list[tuple[str, float]] = []

    def _paso(nombre: str, fn: Any) -> Any:
        t0 = time.perf_counter()
        out = fn()
        resultados.append((nombre, round((time.perf_counter() - t0) * 1000.0, 1)))
        return out

    try:
        # 1. Levantar aplicacion completa TITAN-OS v16 con API REST v2 + SSE + Workflows + Mock Ollama
        db_path = os.path.join(tmp_dir, "titan_e2e.db")
        srv, svc = crear_app_titan_v16(
            host="127.0.0.1",
            port=0,
            db_path=db_path,
            log_path=os.path.join(tmp_dir, "titan_e2e.jsonl"),
            carpeta_facturas=os.path.join(tmp_dir, "facturas"),
            carpeta_productos=os.path.join(tmp_dir, "productos"),
            carpeta_snapshots=os.path.join(tmp_dir, "snapshots"),
            secret_file=os.path.join(tmp_dir, ".lic_secret"),
            ui_dir=os.path.join(ROOT_DIR, "web_ui"),
            iniciar_workflows=True,
        )
        # Inyectar AI Router apuntando al mock local de Ollama para pruebas deterministas 0-cost
        svc.ai_router = TitanAIRouter(
            db=svc.db, bus=svc.bus, telemetry=svc.telemetry,
            cache=TitanAICache(db=svc.db, usar_sqlite=True),
            gemini=ProveedorGemini(api_keys=[]),
            ollama=ProveedorOllama(base_url=mock_base, modelo="qwen3:8b", shield=svc.http_shield),
            openai_compat=ProveedorOpenAICompat(base_url="", api_key=""),
            estrategia_default="local_only",
            usar_sqlite=True,
        )
        svc.autofixer.ai_router = svc.ai_router
        svc.pitch_engine.ai_router = svc.ai_router
        svc.factory.ai_router = svc.ai_router

        host, port = srv.iniciar_en_hilo()
        base = f"http://{host}:{port}"
        api = f"{base}/api/v2"

        # PASO 1: Salud, Rutas, OpenAPI 3.0 y Web UI v16 (HTML/CSS/JS + Gzip + ETag 304)
        def _p1() -> None:
            r_h = requests.get(f"{api}/health?full=true", timeout=5)
            assert r_h.status_code == 200 and r_h.json()["ok"] is True and r_h.json()["db"]["version_esquema"] == 6
            r_rt = requests.get(f"{api}/routes", timeout=5).json()
            assert r_rt["total"] >= 70
            r_oa = requests.get(f"{api}/openapi.json", timeout=5).json()
            assert r_oa["openapi"] == "3.0.3"

            raw_html = open(os.path.join(ROOT_DIR, "web_ui", "index.html"), encoding="utf-8").read()
            val = _HTMLUniqueIDValidator()
            val.feed(raw_html)
            assert not val.dups, f"IDs duplicados: {val.dups}"

            for asset in (
                "/ui/titan_v16.css", "/ui/titan_store.js", "/ui/titan_components.js",
                "/ui/ui_crm_v16.js", "/ui/ui_pitch_v16.js", "/ui/ui_finanzas_v16.js",
                "/ui/ui_timer_v16.js", "/ui/ui_sandbox_v16.js", "/ui/ui_studio_ops_v16.js",
            ):
                r1 = requests.get(f"{base}{asset}", headers={"Accept-Encoding": "gzip"}, timeout=5)
                assert r1.status_code == 200 and r1.headers.get("Content-Encoding") == "gzip", asset
                r304 = requests.get(f"{base}{asset}", headers={"If-None-Match": r1.headers["ETag"]}, timeout=5)
                assert r304.status_code == 304, asset

        _paso("F1/12/13/15-18 Web Server + API v2 + UI Assets Gzip/ETag", _p1)

        # PASO 2: Flujo completo CRM + Workflows IFTTT + SSE Live + Telegram Proactivo
        ctx_ids: dict[str, Any] = {}

        def _p2() -> None:
            bot = TitanTelegramBotV16(
                svc, token="123456:E2E_TOKEN", chat_id_autorizado="777000",
                api_base_url=mock_base, score_min_alerta_proactiva=8,
            )
            bot.activar_alertas_event_bus()

            sse_lines: list[str] = []
            def _read_sse() -> None:
                with requests.get(f"{api}/events/stream?topics=crm.*,finanzas.*&max_events=2", stream=True, timeout=6) as rs:
                    for ln in rs.iter_lines(chunk_size=1, decode_unicode=True):
                        if ln:
                            sse_lines.append(ln)

            t_sse = threading.Thread(target=_read_sse, daemon=True)
            t_sse.start()
            time.sleep(0.2)

            # Crear Lead Ballena -> dispara Workflow Ballena (crea tarea critica) + SSE + Alerta Telegram!
            r_l = requests.post(f"{api}/leads", json={
                "fuente": "r/forhire", "plataforma": "Reddit", "autor": "u/whale_e2e",
                "titulo": "[Hiring] Python Playwright Shopify Scraper ($380 USD)",
                "presupuesto": "$380 USD", "presupuesto_num": 380, "score": 9,
                "prioridad_tag": "HIGH-TICKET",
                "link": "https://reddit.com/r/forhire/comments/e2e16/shopify",
            }, timeout=5).json()
            assert r_l["ok"] is True
            lid = r_l["lead"]["id"]
            ctx_ids["lead_id"] = lid
            ctx_ids["cliente_id"] = r_l["lead"]["cliente_id"]

            # Generar Pitch A/B + Enviar al CRM
            r_p = requests.post(f"{api}/pitch/generar", json={"lead_id": lid, "num_variantes": 2}, timeout=8).json()
            assert r_p["ok"] is True and len(r_p["variantes"]) == 2
            mejor_v = r_p["variantes"][0]
            r_env = requests.post(f"{api}/pitch/enviar", json={
                "lead_id": lid, "texto_pitch": mejor_v["texto"], "variante": mejor_v["variante"],
                "precio_cotizado_usd": 380, "template_nombre": mejor_v["template_base"], "plataforma": "Reddit",
            }, timeout=5).json()
            assert r_env["ok"] is True

            t_sse.join(timeout=4.0)
            blob_sse = "\n".join(sse_lines)
            assert "event: crm.lead.nuevo" in blob_sse
            assert any(c["metodo"] == "sendMessage" and f"LEAD #{lid}" in c["body"]["text"] for c in MOCK_STATE["tg_calls"])

            # Callback 1-toque desde Telegram: iniciar/detener timer + emitir factura rapida
            assert bot.procesar_update({"callback_query": {"id": "e1", "data": encode_cb("t_start", lid), "message": {"message_id": 1, "chat": {"id": 777000}}}})
            assert bot.procesar_update({"callback_query": {"id": "e2", "data": encode_cb("t_stop", lid), "message": {"message_id": 1, "chat": {"id": 777000}}}})
            bot.detener()

        _paso("F4/5/10/14 CRM + Workflows IFTTT + Pitch A/B + SSE + Telegram", _p2)

        # PASO 3: Finanzas + Factura HTML + Cobro Idempotente + Time Tracker Rentabilidad
        def _p3() -> None:
            lid = ctx_ids["lead_id"]
            r_tt = requests.post(f"{api}/tiempo/manual", json={
                "proyecto_nombre": "Shopify Scraper E2E", "duracion_minutos": 180,
                "lead_id": lid, "tarifa_hora_usd": 30,
            }, timeout=5).json()
            assert r_tt["ok"] is True

            r_fac = requests.post(f"{api}/facturas", json={
                "cliente_nombre": "u/whale_e2e", "concepto": "Shopify Scraper Python",
                "monto_bruto_usd": 380, "pasarela": "binance", "lead_id": lid,
            }, timeout=5).json()
            fid = r_fac["factura"]["id"]
            assert requests.post(f"{api}/facturas/{fid}/pagar", json={"pasarela": "binance"}, timeout=5).json()["factura"]["estado_pago"] == "pagada"
            assert requests.post(f"{api}/finanzas/movimientos", json={"tipo": "gasto", "categoria": "vps", "descripcion": "VPS", "monto_usd": 30}, timeout=5).json()["ok"]

            res_fin = requests.get(f"{api}/finanzas/resumen?trm_cop=4200", timeout=5).json()["resumen"]
            assert res_fin["balance_caja_usd"] == 350.0
            rent = requests.get(f"{api}/tiempo/rentabilidad/{lid}", timeout=5).json()["rentabilidad"]
            assert rent["tarifa_efectiva_usd_hr"] >= 100.0 and rent["veredicto"] == "excelente"

        _paso("F6 Finanzas Ledger + Facturas + Time Tracker USD/hr", _p3)

        # PASO 4: AEGIS-X v16 (Simular + Contrafactuales + 4 Perfiles + Benchmark 200 ofertas)
        def _p4() -> None:
            r_sim = requests.post(f"{api}/aegis/simular", json={
                "titulo": "[Hiring] Python Playwright Shopify scraper ($380 USD)",
                "cuerpo": "Need CSV export today, 50% milestone via Binance.", "plataforma": "Reddit",
            }, timeout=5).json()
            assert r_sim["radiografia"]["aprobado"] is True and r_sim["radiografia"]["contrafactuales"]
            assert len(requests.post(f"{api}/aegis/comparar-perfiles", json={"titulo": "Quick Python CSV fix ($60)", "cuerpo": "1h script"}, timeout=5).json()["comparativa"]) == 4
            assert len(parsear_feed_xml_pro('<rss><channel><item><title>Python &amp; API</title><link>https://x.io/1</link></item></channel></rss>', "t")) == 1

            # Micro-benchmark velocidad AEGIS-X (200 evaluaciones)
            tb = time.perf_counter()
            for i in range(200):
                svc.aegis.evaluar(f"[Hiring] Python automation script #{i} ($200)", "Playwright CSV export", post_id=f"bm_{i}", simular_sin_dedup=True, registrar_dedup=False, registrar_auditoria=False)
            ms_200 = (time.perf_counter() - tb) * 1000.0
            assert ms_200 < 2500.0, f"AEGIS-X lento: {ms_200:.1f}ms en 200 ofertas"

        _paso("F7/8 Conectores Parser + AEGIS-X v16 + Benchmark 200 ofertas", _p4)

        # PASO 5: Sandbox Python + Bloqueo AST + Auto-Fix IA + Whop Factory + Ejecucion Real Licenciada
        def _p5() -> None:
            assert requests.post(f"{api}/sandbox/ejecutar", json={"codigo": "import os\nos.system('id')"}, timeout=5).json()["resultado"]["bloqueado_seguridad"] is True
            r_fix = requests.post(f"{api}/sandbox/autofix", json={"codigo": "def safe_div(a,b): return a/b\nprint(safe_div(10,0))\n", "max_iteraciones": 2}, timeout=12).json()
            assert r_fix["ok"] is True and "E2E_FIXED 0" in r_fix["autofix"]["resultado_final"]["stdout"]

            r_fac = requests.post(f"{api}/factory/construir", json={
                "nombre": "Titan E2E Product", "version": "1.0.0",
                "codigo_fuente": 'SECRET = "AIzaSyQx9Km7Np2Rt5Vw8Yz3Bc6Df1Gh4Jk0Lm9"\nprint("PROD_OK", _ZT_LICENSE_INFO["tier"])\n',
                "incluir_license_guard": True, "generar_marketing_ia": False,
            }, timeout=10).json()
            assert r_fac["ok"] is True and r_fac["sanitizacion"]["total_secretos_removidos"] == 1
            assert requests.post(f"{api}/factory/verificar-zip", json={"ruta_zip": r_fac["ruta_zip"]}, timeout=5).json()["ok"] is True

            ext_dir = os.path.join(tmp_dir, "prod_ext")
            with zipfile.ZipFile(r_fac["ruta_zip"], "r") as zf:
                zf.extractall(ext_dir)
            env_lic = {k: v for k, v in os.environ.items() if "LICENSE" not in k.upper()}
            env_lic["PRODUCT_LICENSE_KEY"] = r_fac["licencia_demo"]["clave_licencia"]
            cp = subprocess.run([sys.executable, "main.py"], cwd=ext_dir, env=env_lic, capture_output=True, text=True, timeout=10)
            assert cp.returncode == 0 and "PROD_OK pro" in cp.stdout, (cp.returncode, cp.stdout, cp.stderr)

        _paso("F9/11 Sandbox AST + Auto-Fix IA + Whop Factory ZIP + Licencia Real", _p5)

        # PASO 6: Security Hardening + Encrypted Vault Backup/Restore + Overview Maestro
        def _p6() -> None:
            rep_sec = SecurityAuditor(root_dir=ROOT_DIR, db=svc.db).auditar()
            assert rep_sec.criticos == 0 and rep_sec.altos == 0 and rep_sec.score_0_100 >= 95, rep_sec.to_dict()

            vault = EncryptedBackupVault(
                db=svc.db, bus=svc.bus,
                vault_dir=os.path.join(tmp_dir, "vault"),
                key_file=os.path.join(tmp_dir, ".vkey"),
            )
            bkp = vault.crear_backup_cifrado(incluir_config=False, etiqueta="e2e")
            assert bkp["ok"] is True and vault.verificar_backup(bkp["ruta"])["ok"] is True
            rest = vault.restaurar_backup(bkp["ruta"], os.path.join(tmp_dir, "rest"))
            assert rest["ok"] is True and "estado_radar_v4.db" in rest["archivos_restaurados"]

            r_ov = requests.get(f"{api}/overview", timeout=5).json()
            assert r_ov["ok"] is True and r_ov["finanzas"]["balance_caja_usd"] == 350.0 and r_ov["factory"]["productos_total"] == 1

        _paso("F19/20 SecurityAuditor + Encrypted Vault + Overview Maestro", _p6)

        total_ms = round((time.perf_counter() - t_global) * 1000.0, 1)
        return {"ok": True, "total_ms": total_ms, "pasos": resultados}
    finally:
        if srv is not None:
            srv.detener()
        if svc is not None:
            svc.cerrar()
        mock_srv.shutdown()
        mock_srv.server_close()
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    res = ejecutar_suite_e2e()
    print("=" * 72)
    print("  ZEROTOUCH TITAN-OS v16.0 — REPORTE E2E GLOBAL (20 FASES)")
    print("=" * 72)
    for nom, ms in res["pasos"]:
        print(f"  [PASS] {nom:<58} {ms:>7.1f} ms")
    print("-" * 72)
    print(f"  TOTAL E2E GLOBAL: {res['total_ms']:.1f} ms | 100% VERDE!")
    print("=" * 72)