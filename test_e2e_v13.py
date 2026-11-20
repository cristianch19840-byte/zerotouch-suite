import os
import sys
import json
import py_compile
import threading
import requests
from http.server import ThreadingHTTPServer

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

ARCHIVOS_SUITE = [
    "core_ia.py",
    "panel.py",
    "dashboard_web.py",
    "telegram_bot_control.py",
    "modulo_a_radar_whop/__init__.py",
    "modulo_a_radar_whop/motor_zerotouch_v4.py",
    "modulo_a_radar_whop/conectores/__init__.py",
    "modulo_a_radar_whop/conectores/base.py",
    "modulo_a_radar_whop/conectores/filtros.py",
    "modulo_a_radar_whop/conectores/reddit.py",
    "modulo_a_radar_whop/conectores/freelancer.py",
    "modulo_a_radar_whop/conectores/github_bounties.py",
    "modulo_a_radar_whop/conectores/hackernews.py",
    "modulo_a_radar_whop/conectores/bolsas_remotas.py",
    "modulo_a_radar_whop/conectores/rss_universal.py",
    "modulo_b_ejecutor/copiloto.py",
    "modulo_c_whop/empaquetador.py",
    "modulo_d_marketing/iman_clientes.py",
]

def run_e2e() -> None:
    print("\n=== AUDITORIA & AUTO-TEST E2E — ZEROTOUCH OMNI-GRID v13.0 ===\n")

    # 1. Compilacion de los 18 archivos del proyecto
    for rel in ARCHIVOS_SUITE:
        ruta = os.path.join(ROOT_DIR, rel)
        assert os.path.isfile(ruta), f"Falta archivo: {rel}"
        py_compile.compile(ruta, doraise=True)
    print(f"[PASS 1/6] Compilacion limpia de {len(ARCHIVOS_SUITE)} archivos Python.")

    # 2. Importacion cruzada y utilidades core
    import core_ia
    from modulo_a_radar_whop.conectores import base, filtros, reddit, freelancer, github_bounties, hackernews, bolsas_remotas, rss_universal
    from modulo_a_radar_whop import motor_zerotouch_v4 as motor
    from modulo_b_ejecutor import copiloto
    from modulo_c_whop import empaquetador
    from modulo_d_marketing import iman_clientes
    import dashboard_web as dw
    import telegram_bot_control as tb

    assert core_ia.extraer_presupuesto_usd("Budget $1.5k-$2.5k") == 2000.0
    assert core_ia.extraer_presupuesto_usd("Paying 80-120 USD") == 100.0
    assert core_ia.parsear_json_cualquiera('```json\n{"resultados":[{"idx":0}]}\n```')["resultados"][0]["idx"] == 0
    assert core_ia.similitud_jaccard("hiring python shopify scraper", "hiring python discord moderation bot") < 0.25
    assert filtros.puntuar_relevancia_local("Python Playwright scraper CSV", "extract shopify products")[1] is True
    assert filtros.puntuar_relevancia_local("YouTube video editor CapCut", "thumbnails photoshop")[1] is False
    print("[PASS 2/6] Core IA, parsers JSON/USD, Jaccard y motor de filtros OK.")

    # 3. Esquema SQLite completo (sin alterar datos reales)
    conn = core_ia.preparar_db()
    try:
        cols_l = {r[1] for r in conn.execute("PRAGMA table_info(leads)").fetchall()}
        for col in ("plataforma", "tipo_trabajo", "presupuesto_num", "contactado_ts", "notas"):
            assert col in cols_l, f"Falta columna {col} en leads"
        tablas = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        for t in ("vistos", "leads", "stats_diarias", "salud_fuentes"):
            assert t in tablas, f"Falta tabla {t}"
    finally:
        conn.close()
    print("[PASS 3/6] Esquema SQLite WAL (vistos, leads, stats_diarias, salud_fuentes) OK.")

    # 4. Contratos de Orquestador, Copiloto Universal, Empaquetador y Bot 2-Vias
    mix = motor.mezclar_equitativamente(
        [{"plataforma": "Freelancer", "id": f"f{i}"} for i in range(10)] +
        [{"plataforma": "Reddit", "id": "r1"}, {"plataforma": "GitHub", "id": "g1"}, {"plataforma": "RemoteOK", "id": "k1"}],
        6,
    )
    assert {"Reddit", "Freelancer", "GitHub", "RemoteOK"}.issubset({x["plataforma"] for x in mix})
    assert copiloto.detectar_plataforma_url("https://www.freelancer.com/projects/python/x") == "Freelancer"
    assert copiloto.detectar_plataforma_url("https://github.com/org/repo/issues/1") == "GitHub"
    assert copiloto.detectar_plataforma_url("https://remoteok.com/remote-jobs/1") == "RemoteOK"
    assert tb.resolver_clave_fuente("fl") == "freelancer"
    assert tb.resolver_clave_fuente("corto") == "solo_freelance_corto"
    num, html_inv = empaquetador.crear_factura_html("u/test", "Python Bot", "150")
    assert num.startswith("ZT-") and "INVOICE" in html_inv and "Micro-Contract" in html_inv
    print("[PASS 4/6] Contratos Orquestador, Copiloto Universal, Facturas y Bot 2-Vias OK.")

    # 5. Smoke Test HTTP real del Dashboard Web OS en puerto efimero (cero conflicto con 8765)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), dw.Handler)
    puerto = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        base_url = f"http://127.0.0.1:{puerto}"
        r_home = requests.get(f"{base_url}/", timeout=5)
        assert r_home.status_code == 200 and "ZeroTouch" in r_home.text and "t_plat" in r_home.text

        r_data = requests.get(f"{base_url}/api/data", timeout=5)
        assert r_data.status_code == 200
        d = r_data.json()
        for k in ("leads", "kpis", "analytics", "salud", "catalogo", "fuentes_activas", "scan"):
            assert k in d, f"Falta clave {k} en /api/data"
        assert len(d["catalogo"]) == 12

        r_cfg = requests.get(f"{base_url}/api/config", timeout=5)
        assert r_cfg.status_code == 200 and "fuentes_activas" in r_cfg.json()

        r_scr = requests.get(f"{base_url}/api/scripts", timeout=5)
        assert r_scr.status_code == 200 and "scripts" in r_scr.json()
    finally:
        srv.shutdown()
        srv.server_close()
    print(f"[PASS 5/6] Servidor Web OS v13 probado en vivo (HTTP 200 en /, /api/data, /api/config, /api/scripts).")

    # 6. Verificacion de Workflow GitHub Actions y .gitignore
    wf_path = os.path.join(ROOT_DIR, ".github", "workflows", "radar_autonomo.yml")
    with open(wf_path, encoding="utf-8") as f:
        wf = f.read()
    assert "radar-db-v13-" in wf and "dry_run" in wf and "REDDIT_CLIENT_ID" in wf
    print("[PASS 6/6] GitHub Actions v13.0 y configuracion de despliegue verificados.")

    print("\n==============================================================")
    print("  [100% PASS] ZEROTOUCH SUITE v13.0 OMNI-GRID CERTIFICADA!")
    print("==============================================================\n")

if __name__ == "__main__":
    run_e2e()