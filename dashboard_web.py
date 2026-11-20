import os
import io
import csv
import sys
import json
import socket
import threading
import webbrowser
from datetime import datetime
from urllib.parse import urlparse, parse_qs, quote
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core_ia import (
    C,
    SESSION,
    DEFAULT_FUENTES_ACTIVAS,
    safe_float,
    safe_int,
    safe_bool,
    log_evento,
    obtener_logs,
    cargar_config,
    guardar_config,
    preparar_db,
    obtener_salud_fuentes,
    crear_backup_rotativo,
    listar_scripts_disponibles,
    generar_texto_ia,
    extraer_etiqueta,
)
from modulo_a_radar_whop.motor_zerotouch_v4 import (
    ejecutar_ciclo,
    evaluar_y_enviar,
    diagnosticar_reddit_real,
)
from modulo_b_ejecutor.copiloto import (
    descargar_oferta_universal,
    cargar_desde_crm_completo,
    analizar_oferta_completo,
    leer_borrador_actual,
    refinar_borrador_ia,
)
from modulo_c_whop.empaquetador import guardar_factura_local, empaquetar_producto_whop
from modulo_d_marketing.iman_clientes import (
    responder_objecion_ia,
    generar_secuencia_followup_ia,
    generar_cierre_y_review_ia,
)

WEB_UI_DIR = os.path.join(ROOT_DIR, "web_ui")
MIME_MAP = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
}

def ui_v14_lista() -> bool:
    return (
        os.path.isfile(os.path.join(WEB_UI_DIR, "index.html"))
        and os.path.isfile(os.path.join(WEB_UI_DIR, "app.js"))
    )

SCAN_LOCK = threading.Lock()
SNIPER_LOCK = threading.Lock()
SCAN_STATE = {"running": False, "last_result": None, "sniper_on": False, "sniper_ciclos": 0}
CURRENT_SNIPER_STOP: threading.Event | None = None

CATALOGO_PLATAFORMAS = [
    {"clave": "reddit", "nombre": "Reddit Omni", "tipo": "freelance", "desc": "16 Subreddits + 2 Busquedas Globales (Anti-403)"},
    {"clave": "freelancer", "nombre": "Freelancer.com", "tipo": "freelance", "desc": "API oficial con presupuestos USD y contador de bids"},
    {"clave": "github_bounties", "nombre": "GitHub Bounties", "tipo": "bounty", "desc": "Issues pagos con label bounty, Algora y Opire"},
    {"clave": "hackernews", "nombre": "HackerNews", "tipo": "freelance", "desc": "Hilos freelance y contratos Python (Algolia API)"},
    {"clave": "remoteok", "nombre": "RemoteOK", "tipo": "remoto", "desc": "Bolsa remota global con salarios y tags dev"},
    {"clave": "weworkremotely", "nombre": "We Work Remotely", "tipo": "remoto", "desc": "Feeds oficiales Programming y Back-End"},
    {"clave": "remotive", "nombre": "Remotive", "tipo": "remoto", "desc": "Vacantes y contratos remotos de software"},
    {"clave": "jobicy", "nombre": "Jobicy", "tipo": "remoto", "desc": "Roles tech remotos con rangos salariales"},
    {"clave": "himalayas", "nombre": "Himalayas", "tipo": "remoto", "desc": "API moderna de empleos y contratos remotos"},
    {"clave": "workingnomads", "nombre": "Working Nomads", "tipo": "remoto", "desc": "Bolsa internacional de contratos y dev remoto"},
    {"clave": "arbeitnow", "nombre": "Arbeitnow", "tipo": "remoto", "desc": "Tech remoto Europa / Global (filtrado remote=True)"},
    {"clave": "rss_custom", "nombre": "Feeds RSS Custom", "tipo": "custom", "desc": "Tus propios links RSS/Atom personalizados"},
]

HTML_DASHBOARD = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ZeroTouch OMNI-GRID v13.0 — Freelance OS</title>
<style>
  :root {
    --bg:#060911; --sidebar:#0b1120; --card:#0f172a; --card2:#162033;
    --border:#1e293b; --text:#f1f5f9; --muted:#94a3b8;
    --accent:#38bdf8; --green:#4ade80; --amber:#fbbf24; --red:#f87171; --purple:#c084fc;
  }
  * { box-sizing:border-box; }
  body { margin:0; font-family:'Segoe UI',system-ui,sans-serif; background:var(--bg); color:var(--text); display:flex; min-height:100vh; }
  .side { width:250px; background:var(--sidebar); border-right:1px solid var(--border); padding:20px 14px; display:flex; flex-direction:column; position:fixed; inset:0 auto 0 0; overflow-y:auto; }
  .brand { font-size:18px; font-weight:800; padding:4px 10px 16px; border-bottom:1px solid var(--border); margin-bottom:14px; }
  .brand span { color:var(--accent); }
  .brand small { display:block; font-size:11px; color:var(--muted); font-weight:500; margin-top:2px; }
  .nav-grp { font-size:10px; text-transform:uppercase; letter-spacing:.09em; color:#64748b; font-weight:700; padding:12px 10px 6px; }
  .nav-btn { width:100%; text-align:left; background:transparent; color:var(--muted); border:none; padding:10px 12px; border-radius:9px; cursor:pointer; font-size:13px; font-weight:600; display:flex; align-items:center; gap:9px; transition:.15s; margin-bottom:3px; }
  .nav-btn:hover { background:#1e293b88; color:var(--text); }
  .nav-btn.active { background:linear-gradient(135deg,#0284c7,#2563eb); color:#fff; box-shadow:0 4px 14px rgba(37,99,235,.35); }
  .side-foot { margin-top:auto; padding-top:14px; border-top:1px solid var(--border); font-size:11px; color:#64748b; text-align:center; }

  .main { margin-left:250px; flex:1; padding:24px 28px; max-width:calc(100% - 250px); }
  .topbar { display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:12px; margin-bottom:20px; }
  .topbar h2 { margin:0; font-size:20px; }
  .actions { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
  button, a.btn { background:#1e293b; color:var(--text); border:1px solid #334155; padding:8px 14px; border-radius:8px; cursor:pointer; font-size:13px; font-weight:600; text-decoration:none; transition:.15s; display:inline-flex; align-items:center; gap:6px; }
  button:hover:not(:disabled), a.btn:hover { background:#334155; border-color:var(--accent); }
  button:disabled { opacity:.55; cursor:not-allowed; }
  button.primary { background:linear-gradient(135deg,#0284c7,#2563eb); border:none; color:#fff; }
  button.success { background:#065f46; border-color:#10b981; color:#ecfdf5; }
  button.purple { background:#581c87; border-color:#a855f7; color:#faf5ff; }
  button.danger { background:#7f1d1d; border-color:#ef4444; color:#fef2f2; }
  button.sniper-on { background:#14532d; border-color:#4ade80; color:#86efac; box-shadow:0 0 14px rgba(74,222,128,.25); }
  button.sm, a.sm { padding:5px 8px; font-size:12px; }

  .view { display:none; animation:fade .18s ease; }
  .view.active { display:block; }
  @keyframes fade { from { opacity:0; transform:translateY(4px); } to { opacity:1; transform:none; } }

  .kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(155px,1fr)); gap:12px; margin-bottom:18px; }
  .kpi { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:14px 16px; }
  .kpi .lbl { font-size:10.5px; text-transform:uppercase; color:var(--muted); letter-spacing:.06em; }
  .kpi .num { font-size:22px; font-weight:800; margin-top:5px; }
  .green { color:var(--green); } .cyan { color:var(--accent); } .amber { color:var(--amber); } .purple { color:var(--purple); } .red { color:var(--red); }

  .toolbar { display:flex; gap:9px; flex-wrap:wrap; margin-bottom:14px; align-items:center; }
  input, select, textarea { background:#080d19; color:var(--text); border:1px solid #334155; padding:8px 11px; border-radius:8px; font-size:13px; font-family:inherit; }
  input:focus, select:focus, textarea:focus { outline:none; border-color:var(--accent); }
  textarea { width:100%; min-height:88px; resize:vertical; }

  .table-box { background:var(--card); border:1px solid var(--border); border-radius:12px; overflow:auto; }
  table { width:100%; border-collapse:collapse; min-width:1180px; }
  th, td { padding:10px 11px; border-bottom:1px solid var(--border); text-align:left; font-size:13px; vertical-align:middle; }
  th { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.06em; background:#0b1220; }
  tr:hover { background:#131d31; }
  tr.dirty { background:#1e293b99; }
  .score { display:inline-block; padding:3px 8px; border-radius:6px; font-weight:700; font-size:12px; }
  .s-hi { background:#14532d; color:#86efac; } .s-mid { background:#1e3a8a; color:#93c5fd; }
  .pill { display:inline-block; font-size:10.5px; padding:2px 7px; border-radius:999px; background:#3b0764; color:#e9d5ff; margin-left:5px; font-weight:700; }
  .badge-tipo { display:inline-block; font-size:10px; padding:2px 6px; border-radius:5px; font-weight:700; text-transform:uppercase; margin-right:4px; }
  .bt-freelance { background:#0c4a6e; color:#7dd3fc; }
  .bt-bounty { background:#4c1d95; color:#ddd6fe; }
  .bt-remoto { background:#064e3b; color:#6ee7b7; }
  .bt-custom { background:#78350f; color:#fde68a; }
  a.title-link { color:#e2e8f0; text-decoration:none; font-weight:600; }
  a.title-link:hover { color:var(--accent); text-decoration:underline; }
  .meta { font-size:11.5px; color:var(--muted); margin-top:3px; }
  .usd-in { width:68px; }
  .note-in { width:120px; font-size:12px; padding:6px 8px; }

  .grid-2 { display:grid; grid-template-columns:repeat(auto-fit,minmax(390px,1fr)); gap:16px; }
  .grid-plat { display:grid; grid-template-columns:repeat(auto-fill,minmax(290px,1fr)); gap:13px; margin-bottom:20px; }
  .card { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px; }
  .card h3 { margin:0 0 12px 0; font-size:15px; color:var(--accent); }
  .plat-card { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:15px; display:flex; flex-direction:column; gap:8px; transition:.15s; }
  .plat-card.off { opacity:.52; }
  .plat-top { display:flex; justify-content:space-between; align-items:flex-start; gap:8px; }
  .plat-name { font-weight:700; font-size:14.5px; }
  .plat-stat { font-size:11.5px; background:#080d19; border:1px solid #1e293b; border-radius:7px; padding:7px 9px; color:#cbd5e1; }
  .dot { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:6px; }
  .dot-ok { background:var(--green); box-shadow:0 0 8px var(--green); }
  .dot-err { background:var(--red); box-shadow:0 0 8px var(--red); }
  .dot-idle { background:#64748b; }

  .switch { position:relative; display:inline-block; width:42px; height:22px; flex-shrink:0; }
  .switch input { opacity:0; width:0; height:0; }
  .slider { position:absolute; cursor:pointer; inset:0; background:#334155; border-radius:999px; transition:.2s; }
  .slider:before { position:absolute; content:""; height:16px; width:16px; left:3px; bottom:3px; background:#fff; border-radius:50%; transition:.2s; }
  .switch input:checked + .slider { background:#10b981; }
  .switch input:checked + .slider:before { transform:translateX(20px); }

  .rss-row { display:flex; justify-content:space-between; align-items:center; gap:10px; background:#080d19; border:1px solid #1e293b; border-radius:8px; padding:9px 12px; margin-bottom:8px; font-size:12.5px; }
  .field { margin-bottom:12px; }
  .field label { display:block; font-size:12px; color:var(--muted); margin-bottom:5px; font-weight:600; }
  .field input, .field select { width:100%; }
  .prebox { background:#060911; border:1px solid #334155; border-radius:8px; padding:12px; white-space:pre-wrap; font-size:12.5px; line-height:1.5; max-height:260px; overflow:auto; font-family:Consolas,monospace; }
  .calc-box { background:#060911; border:1px solid #1e293b; border-radius:10px; padding:15px; margin-top:12px; }
  .calc-row { display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid #1e293b; font-size:13px; }
  .calc-row:last-child { border:none; font-size:16px; font-weight:800; color:var(--green); padding-top:9px; }

  .bar-row { margin-bottom:11px; }
  .bar-lbl { display:flex; justify-content:space-between; font-size:12px; margin-bottom:4px; }
  .bar-track { height:9px; background:#1e293b; border-radius:999px; overflow:hidden; }
  .bar-fill { height:100%; background:linear-gradient(90deg,#0284c7,#38bdf8); border-radius:999px; }
  .bar-fill.g { background:linear-gradient(90deg,#16a34a,#4ade80); }

  .modal-bg { position:fixed; inset:0; background:rgba(0,0,0,.75); display:none; align-items:center; justify-content:center; padding:20px; z-index:99; }
  .modal-bg.open { display:flex; }
  .modal { background:var(--card); border:1px solid #334155; border-radius:14px; max-width:880px; width:100%; max-height:88vh; overflow:auto; padding:24px; }

  .toast { position:fixed; bottom:22px; right:22px; background:#0f172a; border:1px solid var(--accent); color:#fff; padding:11px 16px; border-radius:10px; font-size:13px; font-weight:600; box-shadow:0 10px 30px rgba(0,0,0,.5); opacity:0; transform:translateY(12px); pointer-events:none; transition:.2s; z-index:120; }
  .toast.show { opacity:1; transform:none; }
  .status-bar { font-size:12px; color:var(--amber); margin-left:auto; }
  @media (max-width:860px) { .side { position:static; width:100%; height:auto; } body { flex-direction:column; } .main { margin-left:0; max-width:100%; padding:16px; } }
</style>
</head>
<body>
  <aside class="side">
    <div class="brand">⚡ ZeroTouch <span>OMNI-GRID</span><small>v13.0 • 12+ Plataformas</small></div>
    <div class="nav-grp">Operacion</div>
    <button class="nav-btn active" id="nav_crm" onclick="verTab('t_crm','📡 Radar & CRM',this)">📡 Radar & CRM</button>
    <button class="nav-btn" id="nav_plat" onclick="verTab('t_plat','🌐 Plataformas & RSS',this)">🌐 Plataformas & RSS</button>
    <button class="nav-btn" onclick="verTab('t_stats','📊 Analytics & Pipeline',this)">📊 Analytics & Pipeline</button>
    <div class="nav-grp">Estudio IA</div>
    <button class="nav-btn" onclick="verTab('t_ai','🧠 Copiloto Universal & Negociador',this)">🧠 Copiloto & Negociador</button>
    <button class="nav-btn" onclick="verTab('t_code','💻 Refinador de Codigo IA',this)">💻 Refinador de Codigo IA</button>
    <div class="nav-grp">Negocio</div>
    <button class="nav-btn" onclick="verTab('t_mkt','🧲 Marketing & Cierre',this)">🧲 Marketing & Cierre</button>
    <button class="nav-btn" id="nav_whop" onclick="verTab('t_whop','📦 Whop, Facturas & Calc',this)">📦 Whop, Facturas & Calc</button>
    <div class="nav-grp">Sistema</div>
    <button class="nav-btn" onclick="verTab('t_cfg','⚙️ Ajustes & Salud',this)">⚙️ Ajustes & Salud</button>
    <div class="side-foot">OMNI-GRID v13.0 • Batch IA</div>
  </aside>

  <main class="main">
    <div class="topbar">
      <h2 id="pageTitle">📡 Radar & CRM</h2>
      <div class="actions">
        <button id="btnSniper" onclick="toggleSniper()">🎯 Auto-Sniper: OFF</button>
        <button class="primary" onclick="lanzarEscaneo()">🚀 Escanear Todo</button>
        <button onclick="cargarDatos(true)" title="Forzar recarga">🔄</button>
        <a class="btn" href="/api/export">📥 Excel</a>
      </div>
    </div>

    <!-- 1. RADAR & CRM -->
    <section id="t_crm" class="view active">
      <div class="kpis">
        <div class="kpi"><div class="lbl">Facturado Total</div><div class="num green" id="kUsd">$0.00</div></div>
        <div class="kpi"><div class="lbl">Pipeline Vivo</div><div class="num amber" id="kPipe">$0</div></div>
        <div class="kpi"><div class="lbl">Leads / Ganados</div><div class="num green" id="kLeads">0 / 0</div></div>
        <div class="kpi"><div class="lbl">Tasa de Cierre</div><div class="num cyan" id="kCierre">0%</div></div>
        <div class="kpi"><div class="lbl">Fuentes OK</div><div class="num cyan" id="kFuentes">0 / 0</div></div>
        <div class="kpi"><div class="lbl">Tokens Ahorrados</div><div class="num purple" id="kTok">0</div></div>
      </div>

      <div class="toolbar">
        <input type="text" id="qSearch" placeholder="Buscar titulo, plataforma, nota o categoria..." oninput="renderTabla()" style="min-width:230px;">
        <select id="qTipo" onchange="renderTabla()">
          <option value="">Todos los tipos</option>
          <option value="freelance">💼 Freelance</option>
          <option value="bounty">💎 Bounty</option>
          <option value="remoto">🌍 Remoto</option>
        </select>
        <select id="qPlat" onchange="renderTabla()">
          <option value="">Todas las plataformas</option>
        </select>
        <select id="qEstado" onchange="renderTabla()">
          <option value="">Todos los estados</option>
          <option value="nuevo">Nuevo</option>
          <option value="contactado">Contactado</option>
          <option value="negociando">Negociando</option>
          <option value="ganado">Ganado</option>
          <option value="descartado">Descartado</option>
        </select>
        <select id="qMinScore" onchange="renderTabla()">
          <option value="0">Score: Todos</option>
          <option value="7">Score 7+</option>
          <option value="8">Score 8+ (Top)</option>
        </select>
        <select id="qSort" onchange="renderTabla()">
          <option value="reciente">Orden: Recientes</option>
          <option value="score">Orden: Mayor Score</option>
          <option value="dinero">Orden: Mayor $</option>
        </select>
        <div class="status-bar" id="scanStatus"></div>
      </div>

      <div class="table-box">
        <table>
          <thead>
            <tr><th>ID</th><th>Score</th><th>Plataforma & Tipo</th><th>Proyecto, Competencia & Cliente</th><th>Presupuesto</th><th>Estado</th><th>USD</th><th>Nota</th><th>Acciones</th></tr>
          </thead>
          <tbody id="tbodyLeads"></tbody>
        </table>
      </div>
    </section>

    <!-- 2. PLATAFORMAS & RSS -->
    <section id="t_plat" class="view">
      <div class="card" style="margin-bottom:16px;">
        <div style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:12px;">
          <div>
            <h3 style="margin-bottom:4px;">🌐 Panel de Control Multi-Plataforma (12+ Fuentes)</h3>
            <div class="meta">Prende o apaga cada plataforma al instante. Los cambios se guardan automaticamente en config.json.</div>
          </div>
          <div class="actions">
            <label style="display:inline-flex;align-items:center;gap:8px;font-size:12.5px;background:#080d19;padding:7px 12px;border-radius:8px;border:1px solid #334155;cursor:pointer;">
              <input type="checkbox" id="chkSoloCorto" onchange="toggleSoloCorto(this.checked)">
              <span>Solo Freelance Corto & Bounties</span>
            </label>
            <button class="primary" onclick="correrDryRunWeb(this, 'platDryOut')">🧪 Test Todas las Fuentes (0 Tokens)</button>
          </div>
        </div>
        <div id="platDryOut" class="prebox" style="display:none;margin-top:14px;"></div>
      </div>

      <div id="gridPlataformas" class="grid-plat"></div>

      <div class="grid-2">
        <div class="card">
          <h3>📡 Agregar Feed RSS / Atom Propio</h3>
          <div class="field"><label>Nombre corto del feed</label><input id="rssNom" placeholder="Ej. PythonOrg Jobs / Upwork RSS / IndieHackers"></div>
          <div class="field"><label>URL del feed (.rss / .xml / .atom)</label><input id="rssUrl" placeholder="https://ejemplo.com/jobs.rss"></div>
          <button class="success" onclick="agregarRssWeb()">➕ Agregar Feed al Radar</button>
          <div id="listaRssCustom" style="margin-top:16px;"></div>
        </div>
        <div class="card">
          <h3>🩺 Detalle en Vivo de Conectores (Ultima Corrida)</h3>
          <div id="tablaSaludDetalle" class="prebox" style="max-height:320px;">Corre un escaneo o "Test Todas las Fuentes" para ver el pulso de cada conector.</div>
        </div>
      </div>
    </section>

    <!-- 3. ANALYTICS -->
    <section id="t_stats" class="view">
      <div class="grid-2">
        <div class="card"><h3>📍 Top Fuentes (Leads Detectados)</h3><div id="chFuentes"></div></div>
        <div class="card"><h3>🎯 Embudo de Conversion CRM</h3><div id="chEmbudo"></div></div>
        <div class="card"><h3>💵 Ingresos por Categoria (USD)</h3><div id="chCat"></div></div>
        <div class="card"><h3>⚡ Eficiencia de Tokens IA (Batch + Pre-filtro)</h3><div id="chTokens"></div></div>
      </div>
    </section>

    <!-- 4. ESTUDIO IA -->
    <section id="t_ai" class="view">
      <div class="grid-2">
        <div class="card">
          <h3>🤖 Copiloto Universal (Cualquier Link, #ID o Texto)</h3>
          <div class="field"><textarea id="aiOferta" placeholder="Pega cualquier link (Reddit, Freelancer.com, GitHub Issue, HackerNews, RemoteOK, WWR...), escribe #4 o pega la descripcion..."></textarea></div>
          <button class="primary" onclick="correrCopilotoWeb(this)">Generar Estrategia + Pitch A/B + Codigo</button>
          <div id="aiResCopiloto" style="margin-top:14px;"></div>
        </div>
        <div class="card">
          <h3>⚔️ Negociador Mata-Objeciones + Red Flag</h3>
          <div class="field"><label>Contexto y precio pedido</label><input id="negCtx" placeholder="Ej. Scraper Shopify, pedi $120 USD"></div>
          <div class="field"><label>Que te respondio el cliente?</label><textarea id="negMsg" placeholder="Ej. Can you do it for $40 or build a free sample first?"></textarea></div>
          <button class="purple" onclick="correrNegociadorWeb(this)">Generar Contraofertas</button>
          <div id="aiResNeg" style="margin-top:14px;"></div>
        </div>
      </div>
    </section>

    <!-- 5. REFINADOR DE CODIGO IA -->
    <section id="t_code" class="view">
      <div class="grid-2">
        <div class="card">
          <h3>💻 Seleccionar & Refinar Script con IA (Auto-AST)</h3>
          <div class="field">
            <label>Script guardado en tu PC</label>
            <div style="display:flex;gap:8px;">
              <select id="codeSel" onchange="cargarCodigoScript()" style="flex:1;"></select>
              <button onclick="cargarScriptsLista()">🔄</button>
            </div>
          </div>
          <div class="field"><label>Que cambio o mejora quieres hacerle?</label><textarea id="codeInstr" placeholder="Ej. Cambia requests por playwright headless, guarda tambien imagenes y exporta a CSV..."></textarea></div>
          <div class="actions">
            <button class="primary" onclick="refinarCodigoWeb(this)">✨ Refinar & Validar AST</button>
            <button class="sm" onclick="copiarCodigoActual()">📋 Copiar Codigo</button>
          </div>
          <div id="codeMeta" class="meta" style="margin-top:12px;"></div>
        </div>
        <div class="card">
          <h3>📄 Vista Previa del Codigo Python</h3>
          <div id="codeView" class="prebox" style="max-height:460px;">Genera primero un script en el Copiloto o selecciona uno arriba.</div>
        </div>
      </div>
    </section>

    <!-- 6. MARKETING & CIERRE -->
    <section id="t_mkt" class="view">
      <div class="grid-2">
        <div class="card">
          <h3>🧲 Generador de Posts [For Hire] / [Offer]</h3>
          <div class="field"><label>Subreddit destino</label>
            <select id="mktSub">
              <option value="r/forhire">r/forhire (Tarifas altas $50+)</option>
              <option value="r/slavelabour">r/slavelabour (Rapido $20-$80)</option>
              <option value="r/DoneDirtCheap">r/DoneDirtCheap (Rapido $15-$60)</option>
              <option value="r/Jobs4Bitcoins">r/Jobs4Bitcoins (Pagos USDT/Cripto)</option>
              <option value="r/freelance_forhire">r/freelance_forhire</option>
            </select>
          </div>
          <div class="field"><label>Enfoque (opcional)</label><input id="mktEnf" placeholder="Python Scraping, Bots Telegram/Discord & Automation"></div>
          <button class="primary" onclick="generarPostWeb(this)">Redactar Post Magnetico</button>
          <div id="resMktPost" style="margin-top:14px;"></div>
        </div>

        <div class="card">
          <h3>🔥 Secuencia Follow-Up (3 Dias) & Kit Entrega/Upsell</h3>
          <div class="field"><label>Proyecto / Contexto del cliente</label><input id="seqCtx" placeholder="Ej. Shopify Price Scraper ($120 USD) para u/john"></div>
          <div class="actions" style="margin-bottom:14px;">
            <button class="primary" onclick="generarFollowupWeb(this)">⏰ Secuencia 3 Dias</button>
            <button class="success" onclick="generarDeliveryWeb(this)">🎁 Entrega + Review + Upsell</button>
          </div>
          <div id="resSeq"></div>
          <hr style="border:none;border-top:1px solid var(--border);margin:18px 0;">
          <div class="actions" style="margin-bottom:12px;">
            <button class="purple" onclick="generarBiosWeb(this)">✨ Generar 3 Bios</button>
            <button class="success" onclick="generarPortafolioWeb(this)">📂 Generar PORTAFOLIO.md</button>
          </div>
          <div id="resMktBios"></div>
        </div>
      </div>
    </section>

    <!-- 7. WHOP, FACTURAS & CALCULADORA -->
    <section id="t_whop" class="view">
      <div class="grid-2">
        <div class="card">
          <h3>🧮 Calculadora Freelance (Normal + Inversa Gross-Up)</h3>
          <div class="grid-2" style="grid-template-columns:1fr 1fr;gap:10px;">
            <div class="field"><label>Horas estimadas</label><input id="calcHrs" type="number" value="4" oninput="calcularPrecio()"></div>
            <div class="field"><label>Tarifa/Hora (USD)</label><input id="calcRate" type="number" value="25" oninput="calcularPrecio()"></div>
          </div>
          <div class="grid-2" style="grid-template-columns:1fr 1fr;gap:10px;">
            <div class="field"><label>Complejidad / Urgencia</label>
              <select id="calcMult" onchange="calcularPrecio()">
                <option value="1">Normal (1.0x)</option>
                <option value="1.25">Complejo / API dificil (1.25x)</option>
                <option value="1.5">Urgente hoy mismo (1.5x)</option>
              </select>
            </div>
            <div class="field"><label>Pasarela de Cobro</label>
              <select id="calcFee" onchange="calcularPrecio()">
                <option value="binance">Binance USDT (0%)</option>
                <option value="airtm">Airtm (~2%)</option>
                <option value="paypal">PayPal (5.4% + $0.30)</option>
              </select>
            </div>
          </div>
          <div class="field"><label>TRM Referencia (COP por 1 USD)</label><input id="calcTrm" type="number" value="4200" oninput="calcularPrecio()"></div>
          <div class="calc-box">
            <div class="calc-row"><span>Precio sugerido al cliente</span><b id="cBruto">$100.00 USD</b></div>
            <div class="calc-row"><span>Comision pasarela</span><b id="cCom" style="color:var(--red);">-$0.00 USD</b></div>
            <div class="calc-row"><span>Neto en tu bolsillo (USD)</span><b id="cNetoUsd" style="color:var(--accent);">$100.00 USD</b></div>
            <div class="calc-row"><span>Para recibir ESE monto limpio cobra:</span><b id="cGrossUp" style="color:var(--amber);">$100.00 USD</b></div>
            <div class="calc-row"><span>Neto aproximado en Colombia</span><b id="cNetoCop">$420,000 COP</b></div>
          </div>
        </div>

        <div class="card">
          <h3>📄 Factura + Micro-Contrato PDF (Auto-Archivada)</h3>
          <div class="field"><label>Cliente / Usuario</label><input id="invCli" placeholder="u/john_founder"></div>
          <div class="field"><label>Concepto del proyecto</label><input id="invProj" placeholder="Custom Python Shopify Scraper & CSV Pipeline"></div>
          <div class="grid-2" style="grid-template-columns:1fr 1fr;gap:10px;">
            <div class="field"><label>Monto (USD)</label><input id="invUsd" type="number" value="120"></div>
            <div class="field"><label>Modalidad</label>
              <select id="invTipo">
                <option value="50% Deposit (Project Start)">50% Adelanto</option>
                <option value="Final Payment (Full Delivery)">100% Pago Final</option>
                <option value="Monthly Retainer / Maintenance">Mensualidad</option>
              </select>
            </div>
          </div>
          <div class="field"><label>Notas / Entregables opcionales</label><input id="invNota" placeholder="Ej. Includes main.py, CSV export and 5-day bugfix support"></div>
          <button class="success" onclick="generarFacturaWeb()">Abrir & Archivar Factura PDF</button>

          <hr style="border:none;border-top:1px solid var(--border);margin:18px 0;">
          <h3>📦 Fabrica 1-Click para Whop (.ZIP + Launcher + Licencia)</h3>
          <div class="field"><label>Nombre comercial</label><input id="whopNom" placeholder="Ej. AutoLead Scraper Pro"></div>
          <div class="field"><label>Elige el script a empaquetar</label><select id="whopSel"></select></div>
          <button class="purple" onclick="empaquetarWhopWeb(this)">Empaquetar .ZIP Comercial</button>
          <div id="resWhop" style="margin-top:12px;"></div>
        </div>
      </div>
    </section>

    <!-- 8. AJUSTES & SALUD -->
    <section id="t_cfg" class="view">
      <div class="grid-2">
        <div class="card">
          <h3>⚙️ Configuracion Global (config.json)</h3>
          <div class="field"><label>Marca / Nombre Freelance</label><input id="cMarca"></div>
          <div class="field"><label>Especialidad Tecnica</label><input id="cEsp"></div>
          <div class="field"><label>Metodos de Pago (Pitches)</label><input id="cPagos"></div>
          <div class="field"><label>Detalle de Pago (Facturas)</label><input id="cPagosFac"></div>
          <div class="field"><label>GitHub URL</label><input id="cGh"></div>
          <div class="field"><label>Whop URL</label><input id="cWhop"></div>
          <div class="grid-2" style="grid-template-columns:1fr 1fr 1fr;gap:10px;">
            <div class="field"><label>Tarifa/Hr USD</label><input id="cTarifa" type="number"></div>
            <div class="field"><label>TRM COP</label><input id="cTrm" type="number"></div>
            <div class="field"><label>Score Min</label><input id="cScore" type="number"></div>
          </div>
          <div class="grid-2" style="grid-template-columns:1fr 1fr 1fr;gap:10px;">
            <div class="field"><label>Sniper (seg)</label><input id="cSniper" type="number"></div>
            <div class="field"><label>Max Edad (hrs)</label><input id="cMaxHrs" type="number"></div>
            <div class="field"><label>Lote IA (1-8)</label><input id="cBatch" type="number"></div>
          </div>
          <div class="field"><label>Max Ofertas IA por ciclo</label><input id="cMaxIa" type="number"></div>
          <div class="field"><label>Blacklist Extra (palabras separadas por coma)</label><input id="cBlack" placeholder="ej. unpaid, internship, wordpress"></div>
          <div class="field"><label>Telegram Admin ID (control remoto DM)</label><input id="cAdmin" placeholder="Opcional"></div>
          <button class="primary" onclick="guardarConfigWeb()">💾 Guardar Configuracion</button>
        </div>
        <div class="card">
          <h3>🩺 Salud del Sistema & Logs en Vivo</h3>
          <div class="actions" style="margin-bottom:14px;">
            <button class="primary" onclick="correrDiagWeb(this)">🩺 Probar Conexiones</button>
            <button class="sm" onclick="correrDryRunWeb(this, 'resDiag')">🧪 Test Escaner (0 Tokens)</button>
            <button class="purple" onclick="probarTelegramWeb(this)">📨 Alerta Prueba TG</button>
            <button class="success" onclick="hacerBackupWeb()">💾 Backup DB</button>
          </div>
          <div id="resDiag" class="prebox" style="margin-bottom:16px;">Haz clic en "Probar Conexiones" para revisar Reddit, Telegram y Gemini.</div>
          <h3>📜 Consola de Eventos en Vivo</h3>
          <div id="liveLogs" class="prebox" style="max-height:220px;color:#93c5fd;">Sin eventos recientes todavia.</div>
        </div>
      </div>
    </section>
  </main>

  <div class="modal-bg" id="modalBg" onclick="if(event.target===this)cerrarModal()">
    <div class="modal">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
        <h3 style="margin:0;color:var(--accent);" id="modalTitle">🤖 Copiloto Universal OMNI</h3>
        <button class="sm" onclick="cerrarModal()">Cerrar (Esc)</button>
      </div>
      <div id="modalBody">Cargando...</div>
    </div>
  </div>
  <div id="toast" class="toast"></div>

<script>
let DATA = { leads:[], kpis:{}, analytics:{}, scan:{}, logs:[], salud:[], catalogo:[], fuentes_activas:{}, feeds_rss_custom:[], solo_freelance_corto:false };
const CLIP_STORE = {};
const DIRTY_LEADS = new Set();
let CLIP_SEQ = 0;
let CODIGO_ACTUAL = '';

function esc(s){ return String(s||'').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }
function toast(msg){ const t = document.getElementById('toast'); t.textContent = msg; t.classList.add('show'); setTimeout(()=> t.classList.remove('show'), 2600); }
function regClip(txt){ const id = 'c' + (++CLIP_SEQ); CLIP_STORE[id] = String(txt || ''); return id; }
function copyId(id){ navigator.clipboard.writeText(CLIP_STORE[id] || ''); toast('✅ Copiado al portapapeles'); }
function cerrarModal(){ document.getElementById('modalBg').classList.remove('open'); }
document.addEventListener('keydown', e => { if(e.key === 'Escape') cerrarModal(); });

async function apiJson(url, opts={}){
  try {
    const r = await fetch(url, opts);
    const txt = await r.text();
    try { return JSON.parse(txt); }
    catch { return { error: `Respuesta invalida del servidor (HTTP ${r.status})` }; }
  } catch (e) {
    return { error: 'Error de red: ' + e.message };
  }
}

function verTab(id, title, btn){
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  document.getElementById('pageTitle').textContent = title;
  if(btn) btn.classList.add('active');
  if(id === 't_cfg') cargarConfigWeb();
  if(id === 't_plat') renderPlataformas();
  if(id === 't_whop'){ calcularPrecio(); cargarScriptsLista(); }
  if(id === 't_code'){ cargarScriptsLista(); }
}

function calcularPrecio(){
  const hrs = parseFloat(document.getElementById('calcHrs').value || '0');
  const rate = parseFloat(document.getElementById('calcRate').value || '0');
  const mult = parseFloat(document.getElementById('calcMult').value || '1');
  const feeType = document.getElementById('calcFee').value;
  const trm = parseFloat(document.getElementById('calcTrm').value || '4200');
  const bruto = hrs * rate * mult;
  let com = 0, grossUp = bruto;
  if(feeType === 'paypal' && bruto > 0){
    com = bruto * 0.054 + 0.30;
    grossUp = (bruto + 0.30) / (1 - 0.054);
  } else if(feeType === 'airtm' && bruto > 0){
    com = bruto * 0.02;
    grossUp = bruto / (1 - 0.02);
  }
  const neto = Math.max(0, bruto - com);
  const cop = Math.round(neto * trm);
  document.getElementById('cBruto').textContent = '$' + bruto.toFixed(2) + ' USD';
  document.getElementById('cCom').textContent = '-$' + com.toFixed(2) + ' USD';
  document.getElementById('cNetoUsd').textContent = '$' + neto.toFixed(2) + ' USD';
  document.getElementById('cGrossUp').textContent = '$' + grossUp.toFixed(2) + ' USD';
  document.getElementById('cNetoCop').textContent = '$' + cop.toLocaleString('es-CO') + ' COP';
}

function marcarDirty(id){
  DIRTY_LEADS.add(id);
  const row = document.getElementById('row_' + id);
  if(row) row.classList.add('dirty');
}

function pasarAFactura(id){
  const l = (DATA.leads || []).find(x => x.id === id);
  if(!l) return;
  document.getElementById('invCli').value = l.autor ? l.autor : 'Client';
  document.getElementById('invProj').value = l.titulo.replace(/^\[[^\]]+\]\s*/,'').slice(0, 90);
  document.getElementById('invUsd').value = l.ganancia_usd > 0 ? l.ganancia_usd : (l.presupuesto_num > 0 ? l.presupuesto_num : 100);
  verTab('t_whop', '📦 Whop, Facturas & Calc', document.getElementById('nav_whop'));
  toast(`📄 Lead #${id} cargado en Factura`);
}

async function toggleSniper(){
  const d = await apiJson('/api/sniper_toggle', { method:'POST' });
  if(d.error) return toast('❌ ' + d.error);
  toast(d.sniper_on ? '🎯 Auto-Sniper ACTIVADO en segundo plano' : '⏹️ Auto-Sniper detenido');
  await cargarDatos(false);
}

async function togglePlataforma(clave, activa){
  const d = await apiJson('/api/fuentes_toggle', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({clave, activa}) });
  if(d.error) return toast('❌ ' + d.error);
  DATA.fuentes_activas = d.fuentes_activas || DATA.fuentes_activas;
  renderPlataformas();
  toast(activa ? `✅ ${clave} activada` : `⏸️ ${clave} pausada`);
}

async function toggleSoloCorto(activo){
  const d = await apiJson('/api/fuentes_toggle', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({solo_freelance_corto: activo}) });
  if(d.error) return toast('❌ ' + d.error);
  DATA.solo_freelance_corto = activo;
  toast(activo ? '💼 Filtro activo: solo Freelance corto & Bounties' : '🌍 Modo completo: Freelance + Bounties + Remoto');
}

async function agregarRssWeb(){
  const nombre = document.getElementById('rssNom').value.trim();
  const url = document.getElementById('rssUrl').value.trim();
  if(!url.startsWith('http')) return toast('⚠️ Ingresa una URL valida que empiece por http/https');
  const d = await apiJson('/api/rss_add', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({nombre, url}) });
  if(d.error) return toast('❌ ' + d.error);
  document.getElementById('rssNom').value = '';
  document.getElementById('rssUrl').value = '';
  DATA.feeds_rss_custom = d.feeds || [];
  renderPlataformas();
  toast('📡 Feed RSS agregado al radar');
}

async function eliminarRssWeb(idx){
  const d = await apiJson('/api/rss_del', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({idx}) });
  if(d.error) return toast('❌ ' + d.error);
  DATA.feeds_rss_custom = d.feeds || [];
  renderPlataformas();
  toast('🗑️ Feed RSS eliminado');
}

function renderPlataformas(){
  const cat = DATA.catalogo || [];
  const act = DATA.fuentes_activas || {};
  const salud = DATA.salud || [];
  document.getElementById('chkSoloCorto').checked = !!DATA.solo_freelance_corto;

  const porClave = {};
  salud.forEach(s => {
    const k = s.clave_config || 'otros';
    if(!porClave[k]) porClave[k] = { ok:0, tot:0, bruto:0, tech:0, modos:new Set(), err:'' };
    porClave[k].tot += 1;
    if(s.ok) porClave[k].ok += 1;
    porClave[k].bruto += (s.bruto || 0);
    porClave[k].tech += (s.tech || 0);
    if(s.modo) porClave[k].modos.add(s.modo);
    if(s.ultimo_error) porClave[k].err = s.ultimo_error;
  });

  document.getElementById('gridPlataformas').innerHTML = cat.map(p => {
    const on = act[p.clave] !== false;
    const st = porClave[p.clave];
    let dot = 'dot-idle', statTxt = 'Sin escanear aun en esta sesion';
    if(st){
      dot = st.ok > 0 ? 'dot-ok' : 'dot-err';
      const modosTxt = Array.from(st.modos).slice(0,2).join(', ');
      statTxt = `${st.ok}/${st.tot} OK • ${st.bruto} raw • ${st.tech} tech${modosTxt ? ' • ' + modosTxt : ''}`;
      if(st.ok === 0 && st.err) statTxt += ` (${st.err})`;
    }
    return `
      <div class="plat-card ${on ? '' : 'off'}">
        <div class="plat-top">
          <div>
            <div class="plat-name"><span class="dot ${dot}"></span>${esc(p.nombre)}</div>
            <div class="meta"><span class="badge-tipo bt-${esc(p.tipo)}">${esc(p.tipo)}</span> ${esc(p.desc)}</div>
          </div>
          <label class="switch" title="Activar / Pausar">
            <input type="checkbox" ${on ? 'checked' : ''} onchange="togglePlataforma('${esc(p.clave)}', this.checked)">
            <span class="slider"></span>
          </label>
        </div>
        <div class="plat-stat">${esc(statTxt)}</div>
      </div>
    `;
  }).join('');

  const feeds = DATA.feeds_rss_custom || [];
  const boxRss = document.getElementById('listaRssCustom');
  if(!feeds.length){
    boxRss.innerHTML = '<div class="meta">No tienes feeds RSS propios agregados todavia.</div>';
  } else {
    boxRss.innerHTML = feeds.map((f, idx) => {
      const nom = typeof f === 'string' ? f : (f.nombre || f.url);
      const url = typeof f === 'string' ? f : f.url;
      return `<div class="rss-row"><div><b>${esc(nom)}</b><div class="meta">${esc(url)}</div></div><button class="danger sm" onclick="eliminarRssWeb(${idx})">🗑️</button></div>`;
    }).join('');
  }

  const detEl = document.getElementById('tablaSaludDetalle');
  if(salud.length){
    detEl.textContent = salud.map(s => `${s.ok ? '✅' : '❌'} ${s.fuente.padEnd(18)} | ${(s.modo||'').padEnd(15)} | raw:${String(s.bruto).padStart(3)} | tech:${String(s.tech).padStart(2)}${s.ultimo_error ? ' | ' + s.ultimo_error : ''}`).join('\n');
  }
}

function poblarFiltroPlataformas(){
  const sel = document.getElementById('qPlat');
  const actual = sel.value;
  const unicas = Array.from(new Set((DATA.leads || []).map(l => l.plataforma || l.fuente).filter(Boolean))).sort();
  sel.innerHTML = '<option value="">Todas las plataformas</option>' + unicas.map(p => `<option value="${esc(p)}" ${p===actual?'selected':''}>${esc(p)}</option>`).join('');
}

async function cargarDatos(forzarTabla=false){
  const d = await apiJson('/api/data');
  if(d.error) return;
  DATA = d;
  document.getElementById('kUsd').textContent = '$' + Number(DATA.kpis.usd || 0).toFixed(2);
  document.getElementById('kPipe').textContent = '$' + Math.round(DATA.kpis.pipeline_usd || 0);
  document.getElementById('kLeads').textContent = `${DATA.kpis.leads_total} / ${DATA.kpis.ganados}`;
  document.getElementById('kCierre').textContent = DATA.kpis.tasa_cierre + '%';
  document.getElementById('kFuentes').textContent = `${DATA.kpis.fuentes_ok || 0} / ${DATA.kpis.fuentes_total || 0}`;
  document.getElementById('kTok').textContent = Number(DATA.kpis.tok_ahorrados || 0).toLocaleString();

  const bSnip = document.getElementById('btnSniper');
  if(DATA.scan.sniper_on){
    bSnip.className = 'sniper-on';
    bSnip.textContent = `🎯 Auto-Sniper: ON (#${DATA.scan.sniper_ciclos})`;
  } else {
    bSnip.className = '';
    bSnip.textContent = '🎯 Auto-Sniper: OFF';
  }

  const st = document.getElementById('scanStatus');
  if(DATA.scan.running){ st.textContent = '⏳ Escaneando 12+ plataformas en paralelo...'; }
  else if(DIRTY_LEADS.size > 0){ st.textContent = `✏️ Tienes ${DIRTY_LEADS.size} fila(s) sin guardar`; }
  else if(DATA.scan.last_result){ const lr = DATA.scan.last_result; const fTxt = lr.fuentes_total ? `Fuentes ${lr.fuentes_ok}/${lr.fuentes_total} | ` : ''; st.textContent = `✅ ${fTxt}${lr.alertas} alertas | ${lr.descartados} filtrados (${lr.segundos}s)`; }

  if(DATA.logs && DATA.logs.length){
    document.getElementById('liveLogs').textContent = DATA.logs.join('\n');
  }

  poblarFiltroPlataformas();
  renderPlataformas();

  const editandoTabla = document.activeElement && document.activeElement.closest('#tbodyLeads');
  if(forzarTabla){ DIRTY_LEADS.clear(); }
  if(forzarTabla || (!editandoTabla && DIRTY_LEADS.size === 0)){
    renderTabla();
  }
  renderAnalytics();
}

function renderTabla(){
  const q = document.getElementById('qSearch').value.toLowerCase();
  const est = document.getElementById('qEstado').value;
  const tipo = document.getElementById('qTipo').value;
  const plat = document.getElementById('qPlat').value;
  const minS = parseInt(document.getElementById('qMinScore').value || '0', 10);
  const sortBy = document.getElementById('qSort').value;

  let filtrados = (DATA.leads || []).filter(l => {
    const lPlat = l.plataforma || l.fuente || '';
    const lTipo = l.tipo_trabajo || 'freelance';
    return l.score >= minS
      && (!est || l.estado === est)
      && (!tipo || lTipo === tipo)
      && (!plat || lPlat === plat)
      && (!q || (l.titulo+' '+l.fuente+' '+lPlat+' '+l.categoria+' '+(l.notas||'')).toLowerCase().includes(q));
  });

  if(sortBy === 'score') filtrados.sort((a,b) => b.score - a.score || b.id - a.id);
  else if(sortBy === 'dinero') filtrados.sort((a,b) => (b.presupuesto_num||0) - (a.presupuesto_num||0) || b.score - a.score);

  const tb = document.getElementById('tbodyLeads');
  if(!filtrados.length){ tb.innerHTML = '<tr><td colspan="9" style="text-align:center;color:#94a3b8;padding:28px;">Sin leads para este filtro. Haz clic en "Escanear Todo".</td></tr>'; return; }
  tb.innerHTML = filtrados.map(l => {
    const t = l.tipo_trabajo || 'freelance';
    return `
    <tr id="row_${l.id}">
      <td><b>#${l.id}</b></td>
      <td><span class="score ${l.score>=8?'s-hi':'s-mid'}">${l.score}/10</span></td>
      <td>
        <div><b>${esc(l.fuente)}</b></div>
        <div class="meta"><span class="badge-tipo bt-${esc(t)}">${esc(t)}</span>${esc(l.categoria)}</div>
      </td>
      <td>
        <a class="title-link" href="${esc(l.link)}" target="_blank">${esc(l.titulo)}</a>
        ${l.prioridad_tag ? `<span class="pill">${esc(l.prioridad_tag)}</span>` : ''}
        <div class="meta">${esc(l.competencia)} ${l.confianza ? ' • ' + esc(l.confianza) : ''}</div>
      </td>
      <td>${esc(l.presupuesto)}</td>
      <td>
        <select id="est_${l.id}" onchange="marcarDirty(${l.id})">
          ${['nuevo','contactado','negociando','ganado','descartado'].map(o => `<option value="${o}" ${l.estado===o?'selected':''}>${o}</option>`).join('')}
        </select>
      </td>
      <td><input class="usd-in" type="number" step="1" id="usd_${l.id}" value="${l.ganancia_usd || 0}" oninput="marcarDirty(${l.id})"></td>
      <td><input class="note-in" type="text" id="not_${l.id}" value="${esc(l.notas || '')}" placeholder="Nota..." oninput="marcarDirty(${l.id})"></td>
      <td style="white-space:nowrap;">
        <button class="success sm" onclick="guardarLead(${l.id})" title="Guardar">💾</button>
        <button class="purple sm" onclick="abrirCopilotoLead(${l.id})" title="Copiloto IA">🤖</button>
        ${l.dm_url ? `<a class="btn sm" href="${esc(l.dm_url)}" target="_blank" title="DM Reddit">⚡</a>` : ''}
        <button class="sm" onclick="pasarAFactura(${l.id})" title="Crear Factura">📄</button>
        <button class="danger sm" onclick="borrarLead(${l.id})" title="Eliminar">🗑️</button>
      </td>
    </tr>
  `;
  }).join('');
}

function renderBarras(elId, pares, cls=''){
  const el = document.getElementById(elId);
  if(!pares || !pares.length){ el.innerHTML = '<div class="meta">Sin datos todavia.</div>'; return; }
  const max = Math.max(...pares.map(p => p[1]), 1);
  el.innerHTML = pares.map(([k, v]) => `
    <div class="bar-row">
      <div class="bar-lbl"><span>${esc(k)}</span><b>${v}</b></div>
      <div class="bar-track"><div class="bar-fill ${cls}" style="width:${Math.max(4, Math.round((v/max)*100))}%"></div></div>
    </div>
  `).join('');
}

function renderAnalytics(){
  const a = DATA.analytics || {};
  renderBarras('chFuentes', a.por_fuente || []);
  renderBarras('chEmbudo', a.embudo || [], 'g');
  renderBarras('chCat', a.usd_categoria || [], 'g');
  const us = DATA.kpis.tok_usados || 0, ah = DATA.kpis.tok_ahorrados || 0;
  const pct = (us + ah) > 0 ? Math.round((ah / (us + ah)) * 100) : 0;
  document.getElementById('chTokens').innerHTML = `
    <div class="bar-row"><div class="bar-lbl"><span>Tokens Ahorrados</span><b>${ah.toLocaleString()} (${pct}%)</b></div>
    <div class="bar-track"><div class="bar-fill g" style="width:${pct}%"></div></div></div>
    <div class="bar-row"><div class="bar-lbl"><span>Tokens Usados</span><b>${us.toLocaleString()}</b></div>
    <div class="bar-track"><div class="bar-fill" style="width:${100-pct}%"></div></div></div>
  `;
}

async function guardarLead(id){
  const estado = document.getElementById('est_'+id).value;
  const rawUsd = document.getElementById('usd_'+id).value;
  const usd = rawUsd === '' ? 0 : (parseFloat(rawUsd) || 0);
  const notas = document.getElementById('not_'+id).value || '';
  const d = await apiJson('/api/update', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id, estado, usd, notas}) });
  if(d.error) return toast('❌ ' + d.error);
  DIRTY_LEADS.delete(id);
  const row = document.getElementById('row_' + id);
  if(row) row.classList.remove('dirty');
  toast(`✅ Lead #${id} guardado`);
  await cargarDatos(DIRTY_LEADS.size === 0);
}

async function borrarLead(id){
  if(!confirm(`Eliminar el lead #${id} de tu CRM?`)) return;
  const d = await apiJson('/api/delete', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id}) });
  if(d.error) return toast('❌ ' + d.error);
  DIRTY_LEADS.delete(id);
  toast(`🗑️ Lead #${id} eliminado`);
  await cargarDatos(true);
}

async function lanzarEscaneo(){
  document.getElementById('scanStatus').textContent = '⏳ Iniciando escaneo OMNI-GRID...';
  toast('🚀 Escaneo de 12+ plataformas iniciado');
  await apiJson('/api/scan', { method:'POST' });
  setTimeout(() => cargarDatos(false), 2000);
}

function renderBloqueCopiloto(res){
  if(!res || res.error) return `<div style="color:var(--red);">Error: ${esc(res ? res.error : 'Sin respuesta')}</div>`;
  const idA = regClip(res.pitch_a), idB = regClip(res.pitch_b), idP = regClip(res.preguntas), idC = regClip(res.micro_contrato), idCode = regClip(res.codigo);
  return `
    <div class="meta" style="margin-bottom:4px;color:var(--purple);font-weight:700;">🌐 ${esc(res.plataforma || 'Auto')} • ${esc(res.confianza || '')}</div>
    ${res.estrategia ? `<div class="meta" style="margin-bottom:6px;color:var(--accent);font-weight:600;">🎯 ${esc(res.estrategia)}</div>` : ''}
    ${res.red_flags ? `<div class="meta" style="margin-bottom:10px;color:var(--amber);font-weight:700;">🚩 ${esc(res.red_flags)}</div>` : ''}
    <div class="field"><label>Diagnostico</label><div class="prebox">${esc(res.diagnostico)}</div></div>
    <div class="field"><label>Precios Sugeridos</label><div class="prebox">${esc(res.precios)}</div></div>
    <div class="field"><label>Pitch A (Adaptado a ${esc(res.plataforma || 'Plataforma')}) <button class="sm" onclick="copyId('${idA}')">Copiar</button> ${res.dm_url ? `<a class="btn sm" href="${esc(res.dm_url)}" target="_blank">⚡ DM Reddit</a>` : ''}</label><div class="prebox">${esc(res.pitch_a)}</div></div>
    <div class="field"><label>Pitch B (Consultivo) <button class="sm" onclick="copyId('${idB}')">Copiar</button></label><div class="prebox">${esc(res.pitch_b)}</div></div>
    ${res.preguntas ? `<div class="field"><label>Preguntas de Cierre <button class="sm" onclick="copyId('${idP}')">Copiar</button></label><div class="prebox">${esc(res.preguntas)}</div></div>` : ''}
    <div class="field"><label>Micro-Contrato <button class="sm" onclick="copyId('${idC}')">Copiar</button></label><div class="prebox">${esc(res.micro_contrato)}</div></div>
    ${res.codigo ? `<div class="field"><label>Codigo Python (${res.ast_valido ? '✅ AST OK' : '⚠️ Revisar'}) <button class="sm" onclick="copyId('${idCode}')">Copiar Codigo</button></label><div class="prebox">${esc(res.codigo)}</div></div>` : ''}
    <div class="meta">Guardado en borrador_cliente.py — puedes mejorarlo en "💻 Refinador de Codigo IA".</div>
  `;
}

async function abrirCopilotoLead(id){
  document.getElementById('modalTitle').textContent = '🤖 Copiloto Universal — Lead #' + id;
  document.getElementById('modalBody').innerHTML = '⏳ Descargando oferta y aplicando playbook de la plataforma...';
  document.getElementById('modalBg').classList.add('open');
  const d = await apiJson('/api/copiloto', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({entrada: '#' + id}) });
  document.getElementById('modalBody').innerHTML = renderBloqueCopiloto(d);
}

async function correrCopilotoWeb(btn){
  const entrada = document.getElementById('aiOferta').value.trim();
  if(!entrada) return toast('⚠️ Pega un link, #ID o texto primero');
  btn.disabled = true;
  document.getElementById('aiResCopiloto').innerHTML = '⏳ Extrayendo oferta y generando Estrategia + Pitch A/B + Codigo...';
  const d = await apiJson('/api/copiloto', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({entrada}) });
  document.getElementById('aiResCopiloto').innerHTML = renderBloqueCopiloto(d);
  btn.disabled = false;
}

async function correrNegociadorWeb(btn){
  const ctx = document.getElementById('negCtx').value.trim();
  const msg = document.getElementById('negMsg').value.trim();
  if(!msg) return toast('⚠️ Escribe lo que te dijo el cliente');
  btn.disabled = true;
  document.getElementById('aiResNeg').innerHTML = '⏳ Calculando contraofertas...';
  const d = await apiJson('/api/negociar', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ctx, msg}) });
  btn.disabled = false;
  if(d.error){ document.getElementById('aiResNeg').innerHTML = `<div style="color:var(--red);">${esc(d.error)}</div>`; return; }
  const idF = regClip(d.firme), idFl = regClip(d.flexible);
  document.getElementById('aiResNeg').innerHTML = `
    ${d.red_flag ? `<div class="meta" style="color:var(--amber);font-weight:700;margin-bottom:8px;">🚩 ${esc(d.red_flag)}</div>` : ''}
    <div class="field"><label>Lectura Tactica</label><div class="prebox">${esc(d.consejo)}</div></div>
    <div class="field"><label>Respuesta Firme <button class="sm" onclick="copyId('${idF}')">Copiar</button></label><div class="prebox">${esc(d.firme)}</div></div>
    <div class="field"><label>Respuesta Flexible <button class="sm" onclick="copyId('${idFl}')">Copiar</button></label><div class="prebox">${esc(d.flexible)}</div></div>
  `;
}

async function cargarScriptsLista(){
  const d = await apiJson('/api/scripts');
  if(d.error) return;
  const opts = (d.scripts || []).length
    ? d.scripts.map(s => `<option value="${esc(s.ruta)}">${esc(s.label)}</option>`).join('')
    : '<option value="modulo_b_ejecutor/borrador_cliente.py">borrador_cliente.py (sin crear aun)</option>';
  document.getElementById('codeSel').innerHTML = opts;
  document.getElementById('whopSel').innerHTML = opts;
  cargarCodigoScript();
}

async function cargarCodigoScript(){
  const ruta = document.getElementById('codeSel').value;
  const d = await apiJson('/api/script_leer?ruta=' + encodeURIComponent(ruta));
  if(d.error){
    CODIGO_ACTUAL = '';
    document.getElementById('codeView').textContent = d.error;
    document.getElementById('codeMeta').textContent = '';
    return;
  }
  CODIGO_ACTUAL = d.codigo || '';
  document.getElementById('codeView').textContent = CODIGO_ACTUAL;
  const falt = (d.faltantes_pip || []).length ? ` | ⚠️ Faltan pip: ${d.faltantes_pip.join(', ')}` : ' | ✅ Dependencias listas';
  document.getElementById('codeMeta').textContent = `${d.lineas} lineas • ${d.ast_valido ? '✅ AST Valido' : '❌ Error sintaxis'}${falt}`;
}

function copiarCodigoActual(){
  if(!CODIGO_ACTUAL) return toast('⚠️ No hay codigo cargado');
  navigator.clipboard.writeText(CODIGO_ACTUAL);
  toast('📋 Codigo Python copiado');
}

async function refinarCodigoWeb(btn){
  const ruta = document.getElementById('codeSel').value;
  const instruccion = document.getElementById('codeInstr').value.trim();
  if(!instruccion) return toast('⚠️ Escribe que mejora quieres hacerle');
  btn.disabled = true;
  document.getElementById('codeMeta').textContent = '⏳ Refinando codigo y validando sintaxis AST...';
  const d = await apiJson('/api/refinar', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ruta, instruccion}) });
  btn.disabled = false;
  if(d.error) return toast('❌ ' + d.error);
  CODIGO_ACTUAL = d.codigo || '';
  document.getElementById('codeView').textContent = CODIGO_ACTUAL;
  document.getElementById('codeMeta').textContent = `✅ ${d.resumen} (${d.lineas} lineas | ${d.ast_valido ? 'AST OK' : 'Revisar'})`;
  toast('✨ Codigo actualizado y guardado');
}

async function generarPostWeb(btn){
  const sub = document.getElementById('mktSub').value;
  const enfoque = document.getElementById('mktEnf').value.trim();
  btn.disabled = true;
  document.getElementById('resMktPost').innerHTML = '⏳ Redactando post magnetico...';
  const d = await apiJson('/api/mkt_post', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({sub, enfoque}) });
  btn.disabled = false;
  if(d.error){ document.getElementById('resMktPost').innerHTML = `<div style="color:var(--red);">${esc(d.error)}</div>`; return; }
  const idT = regClip(d.titulo), idC = regClip(d.cuerpo);
  document.getElementById('resMktPost').innerHTML = `
    <div class="field"><label>Titulo <button class="sm" onclick="copyId('${idT}')">Copiar</button></label><div class="prebox">${esc(d.titulo)}</div></div>
    <div class="field"><label>Cuerpo Markdown <button class="sm" onclick="copyId('${idC}')">Copiar</button></label><div class="prebox">${esc(d.cuerpo)}</div></div>
  `;
}

async function generarFollowupWeb(btn){
  const ctx = document.getElementById('seqCtx').value.trim();
  btn.disabled = true;
  document.getElementById('resSeq').innerHTML = '⏳ Generando secuencia de 3 dias...';
  const d = await apiJson('/api/mkt_followup', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ctx}) });
  btn.disabled = false;
  if(d.error){ document.getElementById('resSeq').innerHTML = `<div style="color:var(--red);">${esc(d.error)}</div>`; return; }
  const i1 = regClip(d.dia_1), i3 = regClip(d.dia_3), ic = regClip(d.cierre);
  document.getElementById('resSeq').innerHTML = `
    <div class="field"><label>Dia 1 <button class="sm" onclick="copyId('${i1}')">Copiar</button></label><div class="prebox">${esc(d.dia_1)}</div></div>
    <div class="field"><label>Dia 3 <button class="sm" onclick="copyId('${i3}')">Copiar</button></label><div class="prebox">${esc(d.dia_3)}</div></div>
    <div class="field"><label>Cierre Suave <button class="sm" onclick="copyId('${ic}')">Copiar</button></label><div class="prebox">${esc(d.cierre)}</div></div>
  `;
}

async function generarDeliveryWeb(btn){
  const ctx = document.getElementById('seqCtx').value.trim();
  btn.disabled = true;
  document.getElementById('resSeq').innerHTML = '⏳ Generando kit de entrega, review y upsell...';
  const d = await apiJson('/api/mkt_delivery', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ctx}) });
  btn.disabled = false;
  if(d.error){ document.getElementById('resSeq').innerHTML = `<div style="color:var(--red);">${esc(d.error)}</div>`; return; }
  const ie = regClip(d.entrega), ir = regClip(d.review), iu = regClip(d.upsell);
  document.getElementById('resSeq').innerHTML = `
    <div class="field"><label>Entrega Final <button class="sm" onclick="copyId('${ie}')">Copiar</button></label><div class="prebox">${esc(d.entrega)}</div></div>
    <div class="field"><label>Pedir Review <button class="sm" onclick="copyId('${ir}')">Copiar</button></label><div class="prebox">${esc(d.review)}</div></div>
    <div class="field"><label>Upsell / Retainer Mensual <button class="sm" onclick="copyId('${iu}')">Copiar</button></label><div class="prebox">${esc(d.upsell)}</div></div>
  `;
}

async function generarBiosWeb(btn){
  btn.disabled = true;
  document.getElementById('resMktBios').innerHTML = '⏳ Generando 3 bios...';
  const d = await apiJson('/api/mkt_bios', { method:'POST', headers:{'Content-Type':'application/json'}, body: '{}' });
  btn.disabled = false;
  if(d.error){ document.getElementById('resMktBios').innerHTML = `<div style="color:var(--red);">${esc(d.error)}</div>`; return; }
  const idR = regClip(d.reddit), idG = regClip(d.github), idW = regClip(d.whop);
  document.getElementById('resMktBios').innerHTML = `
    <div class="field"><label>Reddit Bio <button class="sm" onclick="copyId('${idR}')">Copiar</button></label><div class="prebox">${esc(d.reddit)}</div></div>
    <div class="field"><label>GitHub Bio <button class="sm" onclick="copyId('${idG}')">Copiar</button></label><div class="prebox">${esc(d.github)}</div></div>
    <div class="field"><label>Whop Bio <button class="sm" onclick="copyId('${idW}')">Copiar</button></label><div class="prebox">${esc(d.whop)}</div></div>
  `;
}

async function generarPortafolioWeb(btn){
  btn.disabled = true;
  document.getElementById('resMktBios').innerHTML = '⏳ Construyendo PORTAFOLIO.md profesional...';
  const d = await apiJson('/api/mkt_portfolio', { method:'POST', headers:{'Content-Type':'application/json'}, body: '{}' });
  btn.disabled = false;
  if(d.error){ document.getElementById('resMktBios').innerHTML = `<div style="color:var(--red);">${esc(d.error)}</div>`; return; }
  const idP = regClip(d.markdown);
  document.getElementById('resMktBios').innerHTML = `
    <div class="meta" style="color:var(--green);margin-bottom:8px;">✅ Guardado en PORTAFOLIO.md</div>
    <div class="field"><label>PORTAFOLIO.md <button class="sm" onclick="copyId('${idP}')">Copiar Markdown</button></label><div class="prebox">${esc(d.markdown)}</div></div>
  `;
  toast('📂 PORTAFOLIO.md creado');
}

async function empaquetarWhopWeb(btn){
  const nombre = document.getElementById('whopNom').value.trim() || 'ZeroTouch Automation Tool';
  const ruta = document.getElementById('whopSel').value;
  btn.disabled = true;
  document.getElementById('resWhop').innerHTML = '⏳ Refactorizando codigo y armando .ZIP comercial...';
  const d = await apiJson('/api/whop_pack', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({nombre, ruta}) });
  btn.disabled = false;
  if(d.error){ document.getElementById('resWhop').innerHTML = `<div style="color:var(--red);">${esc(d.error)}</div>`; return; }
  const idW = regClip(d.whop_copy);
  document.getElementById('resWhop').innerHTML = `
    <div class="meta" style="color:var(--green);margin-bottom:8px;">✅ ZIP listo: ${esc(d.zip_path)}</div>
    <div class="field"><label>Copy de Ventas Whop <button class="sm" onclick="copyId('${idW}')">Copiar</button></label><div class="prebox">${esc(d.whop_copy)}</div></div>
  `;
  toast('📦 Paquete Whop generado');
}

async function generarFacturaWeb(){
  const payload = {
    cliente: document.getElementById('invCli').value || 'Client',
    proyecto: document.getElementById('invProj').value || 'Custom Python Automation',
    monto: document.getElementById('invUsd').value || '100',
    tipo: document.getElementById('invTipo').value,
    nota: document.getElementById('invNota').value || ''
  };
  const r = await fetch('/api/factura', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
  const htmlTxt = await r.text();
  const w = window.open('', '_blank');
  w.document.open(); w.document.write(htmlTxt); w.document.close();
  toast('📄 Factura abierta y archivada en entregas_clientes/');
}

async function cargarConfigWeb(){
  const c = await apiJson('/api/config');
  if(c.error) return;
  document.getElementById('cMarca').value = c.nombre_marca || '';
  document.getElementById('cEsp').value = c.especialidad || '';
  document.getElementById('cPagos').value = c.metodos_pago || '';
  document.getElementById('cPagosFac').value = c.detalle_pago_factura || '';
  document.getElementById('cGh').value = c.github_url || '';
  document.getElementById('cWhop').value = c.whop_url || '';
  document.getElementById('cTarifa').value = c.tarifa_hora_usd || 25;
  document.getElementById('cTrm').value = c.trm_cop || 4200;
  document.getElementById('cScore').value = c.score_minimo || 6;
  document.getElementById('cSniper').value = c.intervalo_sniper_seg || 75;
  document.getElementById('cMaxHrs').value = c.max_horas_post || 18;
  document.getElementById('cBatch').value = c.batch_ia_tamano || 5;
  document.getElementById('cMaxIa').value = c.max_ia_por_ciclo || 20;
  const bl = Array.isArray(c.palabras_extra_blacklist) ? c.palabras_extra_blacklist.join(', ') : (c.palabras_extra_blacklist || '');
  document.getElementById('cBlack').value = bl;
  document.getElementById('cAdmin').value = c.telegram_admin_id || '';
  document.getElementById('calcRate').value = c.tarifa_hora_usd || 25;
  document.getElementById('calcTrm').value = c.trm_cop || 4200;
  calcularPrecio();
}

async function guardarConfigWeb(){
  const rawBl = document.getElementById('cBlack').value || '';
  const listaBl = rawBl.split(',').map(s => s.trim()).filter(Boolean);
  const payload = {
    nombre_marca: document.getElementById('cMarca').value,
    especialidad: document.getElementById('cEsp').value,
    metodos_pago: document.getElementById('cPagos').value,
    detalle_pago_factura: document.getElementById('cPagosFac').value,
    github_url: document.getElementById('cGh').value,
    whop_url: document.getElementById('cWhop').value,
    tarifa_hora_usd: parseInt(document.getElementById('cTarifa').value || '25', 10),
    trm_cop: parseInt(document.getElementById('cTrm').value || '4200', 10),
    score_minimo: Math.max(1, Math.min(10, parseInt(document.getElementById('cScore').value || '6', 10))),
    intervalo_sniper_seg: Math.max(45, parseInt(document.getElementById('cSniper').value || '75', 10)),
    max_horas_post: Math.max(1, parseInt(document.getElementById('cMaxHrs').value || '18', 10)),
    batch_ia_tamano: Math.max(1, Math.min(8, parseInt(document.getElementById('cBatch').value || '5', 10))),
    max_ia_por_ciclo: Math.max(1, Math.min(50, parseInt(document.getElementById('cMaxIa').value || '20', 10))),
    palabras_extra_blacklist: listaBl,
    telegram_admin_id: document.getElementById('cAdmin').value.trim()
  };
  const d = await apiJson('/api/config', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
  if(d.error) return toast('❌ ' + d.error);
  document.getElementById('calcRate').value = payload.tarifa_hora_usd;
  document.getElementById('calcTrm').value = payload.trm_cop;
  calcularPrecio();
  toast('💾 Configuracion guardada');
}

async function correrDryRunWeb(btn, outId='resDiag'){
  btn.disabled = true;
  const el = document.getElementById(outId);
  el.style.display = 'block';
  el.textContent = '⏳ Probando todas las plataformas activas en paralelo (0 tokens IA)...';
  const d = await apiJson('/api/scan_dry', { method:'POST' });
  btn.disabled = false;
  if(d.error){ el.textContent = 'Error: ' + d.error; return; }
  const fLines = (d.detalle_fuentes || []).map(f => `  ${f.ok ? '✅' : '❌'} ${f.fuente.padEnd(18)} [${f.modo}] -> ${f.bruto} raw | ${f.tech} tech`).join('\n');
  const cLines = (d.candidatas_preview || []).slice(0, 10).map(c => `  • [${c.plataforma} | ${c.tipo} | ${c.presupuesto || '$?'}] ${c.titulo}`).join('\n') || '  (Todas las ofertas tech vigentes ya estan en tu cache de vistos)';
  el.textContent = `=== DRY-RUN OMNI-GRID (${d.segundos}s | 0 Tokens) ===\nFuentes OK: ${d.fuentes_ok}/${d.fuentes_total} | Bruto: ${d.bruto} | Bloqueados: ${d.descartados} | Ya vistos: ${d.ya_vistos}\n\nPLATAFORMAS:\n${fLines}\n\nTOP CANDIDATAS NUEVAS REPARTIDAS PARA GEMINI (${(d.candidatas_preview||[]).length}):\n${cLines}`;
  toast('🧪 Dry-Run terminado (0 tokens)');
  await cargarDatos(false);
}

async function correrDiagWeb(btn){
  btn.disabled = true;
  document.getElementById('resDiag').textContent = '⏳ Probando Reddit, Telegram y Gemini...';
  const d = await apiJson('/api/diagnostico');
  document.getElementById('resDiag').textContent = d.reporte || d.error;
  btn.disabled = false;
}

async function probarTelegramWeb(btn){
  btn.disabled = true;
  const d = await apiJson('/api/test_tg', { method:'POST' });
  btn.disabled = false;
  toast(d.ok ? '📨 Alerta de prueba enviada a Telegram' : '❌ Fallo envio a Telegram');
  cargarDatos(false);
}

async function hacerBackupWeb(){
  const d = await apiJson('/api/backup', { method:'POST' });
  toast(d.path ? '💾 Backup creado en backups/' : '⚠️ No hay DB todavia');
}

cargarConfigWeb();
cargarDatos(true);
setInterval(() => cargarDatos(false), 15000);
setInterval(() => { if(DATA.scan && DATA.scan.running) cargarDatos(false); }, 3500);
</script>
</body>
</html>
"""

def correr_scan_bg() -> None:
    if not SCAN_LOCK.acquire(blocking=False):
        return
    SCAN_STATE["running"] = True
    try:
        SCAN_STATE["last_result"] = ejecutar_ciclo(modo_sonido=True)
    except Exception as e:
        log_evento(f"Error en escaneo: {e}")
    finally:
        SCAN_STATE["running"] = False
        SCAN_LOCK.release()

def loop_sniper_web(stop_evt: threading.Event) -> None:
    while not stop_evt.is_set():
        SCAN_STATE["sniper_ciclos"] += 1
        correr_scan_bg()
        intervalo = max(45, safe_int(cargar_config().get("intervalo_sniper_seg", 75), 75))
        if stop_evt.wait(intervalo):
            break

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send(self, code: int, content_type: str, data: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, obj: dict, code: int = 200) -> None:
        self._send(code, "application/json; charset=utf-8", json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        ruta = parsed.path
        qs = parse_qs(parsed.query)
        try:
            if ruta == "/":
                if ui_v14_lista():
                    with open(os.path.join(WEB_UI_DIR, "index.html"), "rb") as f_idx:
                        self.send_response(200)
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.send_header("Cache-Control", "no-store")
                        data_idx = f_idx.read()
                        self.send_header("Content-Length", str(len(data_idx)))
                        self.end_headers()
                        self.wfile.write(data_idx)
                else:
                    self._send(200, "text/html; charset=utf-8", HTML_DASHBOARD.encode("utf-8"))
            elif ruta.startswith("/ui/"):
                rel_name = os.path.basename(ruta[4:])
                full_p = os.path.abspath(os.path.join(WEB_UI_DIR, rel_name))
                if full_p.startswith(os.path.abspath(WEB_UI_DIR)) and os.path.isfile(full_p):
                    ext = os.path.splitext(rel_name)[1].lower()
                    ctype = MIME_MAP.get(ext, "application/octet-stream")
                    with open(full_p, "rb") as f_st:
                        raw_st = f_st.read()
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(raw_st)))
                    self.end_headers()
                    self.wfile.write(raw_st)
                else:
                    self._send(404, "text/plain", b"Asset Not Found")
            elif ruta == "/api/config":
                self._send_json(cargar_config())
            elif ruta == "/api/scripts":
                self._send_json({"scripts": listar_scripts_disponibles()})
            elif ruta == "/api/script_leer":
                sel = (qs.get("ruta") or [""])[0]
                self._send_json(leer_borrador_actual(sel))
            elif ruta == "/api/diagnostico":
                key = os.getenv("GEMINI_API_KEY_FREE")
                tg_tok = os.getenv("TELEGRAM_TOKEN")
                tg_id = os.getenv("TELEGRAM_CHAT_ID")
                lineas = [
                    f"1. Archivo .env      : {'OK' if os.path.exists(os.path.join(ROOT_DIR, '.env')) else 'FALTA'}",
                    f"2. config.json       : {'OK' if os.path.exists(os.path.join(ROOT_DIR, 'config.json')) else 'Default'}",
                    f"3. TELEGRAM_CHAT_ID  : {tg_id or 'FALTA'}",
                ]
                if tg_tok:
                    try:
                        rt = SESSION.get(f"https://api.telegram.org/bot{tg_tok}/getMe", timeout=6)
                        lineas.append(f"4. Telegram API      : {'OK (@' + rt.json()['result']['username'] + ')' if rt.status_code == 200 else 'Error ' + str(rt.status_code)}")
                    except Exception as e:
                        lineas.append(f"4. Telegram API      : Error ({e})")
                else:
                    lineas.append("4. Telegram API      : FALTA TELEGRAM_TOKEN")
                lineas.append(f"5. Reddit API        : {diagnosticar_reddit_real()}")
                resp = generar_texto_ia("Responde solo OK", temperatura=0.0, timeout=10) if key else None
                lineas.append(f"6. Gemini API        : {'OK' if resp else 'SIN RESPUESTA'}")
                self._send_json({"reporte": "\n".join(lineas)})
            elif ruta == "/api/data":
                cfg = cargar_config()
                conn = preparar_db()
                try:
                    rows = conn.execute(
                        "SELECT id, fecha, fuente, plataforma, tipo_trabajo, autor, titulo, categoria, presupuesto, presupuesto_num, score, competencia, confianza, prioridad_tag, link, estado, ganancia_usd, notas FROM leads ORDER BY id DESC LIMIT 180"
                    ).fetchall()
                    leads = []
                    for r in rows:
                        autor = r[5] or ""
                        plat = r[3] or r[2] or ""
                        dm_url = ""
                        if plat.lower() == "reddit" and autor and autor.lower() not in ("[deleted]", "automoderator", "none", "github", "hackernews", "freelancer_client"):
                            dm_url = f"https://www.reddit.com/message/compose/?to={quote(autor)}&subject={quote('Re: ' + (r[6] or '')[:60])}"
                        leads.append({
                            "id": r[0], "fecha": r[1], "fuente": r[2], "plataforma": plat,
                            "tipo_trabajo": r[4] or "freelance", "autor": autor, "titulo": r[6],
                            "categoria": r[7], "presupuesto": r[8], "presupuesto_num": r[9] or 0, "score": r[10],
                            "competencia": r[11], "confianza": r[12], "prioridad_tag": r[13], "link": r[14],
                            "estado": r[15], "ganancia_usd": r[16], "notas": r[17] or "", "dm_url": dm_url,
                        })
                    leads_total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
                    usd = conn.execute("SELECT COALESCE(SUM(ganancia_usd), 0) FROM leads WHERE estado = 'ganado'").fetchone()[0]
                    ganados = conn.execute("SELECT COUNT(*) FROM leads WHERE estado = 'ganado'").fetchone()[0]
                    pipeline_usd = conn.execute("SELECT COALESCE(SUM(presupuesto_num), 0) FROM leads WHERE estado IN ('contactado','negociando')").fetchone()[0]
                    activos_neg = conn.execute("SELECT COUNT(*) FROM leads WHERE estado IN ('contactado','negociando','ganado')").fetchone()[0]
                    tasa = round((ganados / activos_neg) * 100) if activos_neg > 0 else 0
                    st_row = conn.execute("SELECT COALESCE(SUM(descartados_local), 0), COALESCE(SUM(tokens_est_usados), 0), COALESCE(SUM(tokens_est_ahorrados), 0) FROM stats_diarias").fetchone()
                    por_fuente = conn.execute("SELECT COALESCE(NULLIF(plataforma, ''), fuente), COUNT(*) FROM leads GROUP BY COALESCE(NULLIF(plataforma, ''), fuente) ORDER BY COUNT(*) DESC LIMIT 8").fetchall()
                    embudo = conn.execute("SELECT estado, COUNT(*) FROM leads GROUP BY estado ORDER BY COUNT(*) DESC").fetchall()
                    usd_cat = conn.execute("SELECT categoria, ROUND(SUM(ganancia_usd), 2) FROM leads WHERE estado = 'ganado' GROUP BY categoria ORDER BY SUM(ganancia_usd) DESC LIMIT 6").fetchall()
                    salud = obtener_salud_fuentes(conn)
                    f_ok = sum(1 for s in salud if s["ok"])

                    self._send_json({
                        "leads": leads,
                        "kpis": {
                            "usd": usd, "pipeline_usd": pipeline_usd,
                            "leads_total": leads_total, "ganados": ganados, "tasa_cierre": tasa,
                            "descartados": st_row[0], "tok_usados": st_row[1], "tok_ahorrados": st_row[2],
                            "fuentes_ok": f_ok, "fuentes_total": len(salud),
                        },
                        "analytics": {"por_fuente": por_fuente, "embudo": embudo, "usd_categoria": usd_cat},
                        "salud": salud,
                        "catalogo": CATALOGO_PLATAFORMAS,
                        "fuentes_activas": cfg.get("fuentes_activas") or dict(DEFAULT_FUENTES_ACTIVAS),
                        "feeds_rss_custom": cfg.get("feeds_rss_custom") or [],
                        "solo_freelance_corto": bool(cfg.get("solo_freelance_corto", False)),
                        "scan": SCAN_STATE,
                        "logs": obtener_logs(50),
                    })
                finally:
                    conn.close()
            elif ruta == "/api/export":
                conn = preparar_db()
                try:
                    rows = conn.execute(
                        "SELECT id, fecha, fuente, plataforma, tipo_trabajo, autor, titulo, categoria, presupuesto, presupuesto_num, score, competencia, confianza, prioridad_tag, estado, ganancia_usd, notas, link FROM leads ORDER BY id DESC"
                    ).fetchall()
                    buf = io.StringIO()
                    w = csv.writer(buf)
                    w.writerow(["ID", "Fecha", "Fuente", "Plataforma", "Tipo_Trabajo", "Autor", "Titulo", "Categoria", "Presupuesto", "Presupuesto_USD", "Score", "Competencia", "Confianza", "Tag", "Estado", "Ganancia_USD", "Notas", "Link"])
                    w.writerows(rows)
                    data = ("\ufeff" + buf.getvalue()).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/csv; charset=utf-8")
                    self.send_header("Content-Disposition", f'attachment; filename="crm_omni_{datetime.now().strftime("%Y%m%d")}.csv"')
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                finally:
                    conn.close()
            else:
                self._send(404, "text/plain", b"Not Found")
        except Exception as e:
            log_evento(f"Error GET {ruta}: {e}")
            self._send_json({"error": str(e)}, code=500)

    def do_POST(self) -> None:
        global CURRENT_SNIPER_STOP
        ruta = urlparse(self.path).path
        try:
            data = self._json_body()
            if ruta == "/api/update":
                est = str(data.get("estado", "nuevo")).strip().lower()
                conn = preparar_db()
                try:
                    conn.execute(
                        """
                        UPDATE leads
                        SET estado = ?,
                            ganancia_usd = ?,
                            notas = ?,
                            contactado_ts = CASE WHEN ? = 'contactado' AND estado != 'contactado' THEN CURRENT_TIMESTAMP ELSE contactado_ts END,
                            followup_enviado = CASE WHEN ? = 'contactado' AND estado != 'contactado' THEN 0 ELSE followup_enviado END
                        WHERE id = ?
                        """,
                        (
                            est,
                            safe_float(data.get("usd", 0), 0.0),
                            str(data.get("notas", ""))[:300],
                            est,
                            est,
                            safe_int(data.get("id", 0), 0),
                        ),
                    )
                    conn.commit()
                finally:
                    conn.close()
                self._send_json({"ok": True})
            elif ruta == "/api/delete":
                conn = preparar_db()
                try:
                    conn.execute("DELETE FROM leads WHERE id = ?", (safe_int(data.get("id", 0), 0),))
                    conn.commit()
                finally:
                    conn.close()
                self._send_json({"ok": True})
            elif ruta == "/api/fuentes_toggle":
                cfg = cargar_config()
                if "solo_freelance_corto" in data:
                    cfg["solo_freelance_corto"] = safe_bool(data.get("solo_freelance_corto"))
                if "clave" in data:
                    clave = str(data.get("clave", "")).strip()
                    if clave in DEFAULT_FUENTES_ACTIVAS:
                        fa = dict(cfg.get("fuentes_activas") or DEFAULT_FUENTES_ACTIVAS)
                        fa[clave] = safe_bool(data.get("activa"))
                        cfg["fuentes_activas"] = fa
                        log_evento(f"Plataforma '{clave}' -> {'ON' if fa[clave] else 'OFF'}")
                guardar_config(cfg)
                self._send_json({"ok": True, "fuentes_activas": cfg["fuentes_activas"], "solo_freelance_corto": cfg["solo_freelance_corto"]})
            elif ruta == "/api/rss_add":
                url = str(data.get("url", "")).strip()
                if not (url.startswith("http://") or url.startswith("https://")):
                    self._send_json({"error": "La URL debe empezar con http:// o https://"})
                    return
                nom = str(data.get("nombre", "")).strip() or urlparse(url).netloc.replace("www.", "") or "RSS-Custom"
                cfg = cargar_config()
                feeds = list(cfg.get("feeds_rss_custom") or [])
                existentes = {f if isinstance(f, str) else f.get("url") for f in feeds}
                if url not in existentes:
                    feeds.append({"nombre": nom[:40], "url": url})
                    cfg["feeds_rss_custom"] = feeds
                    guardar_config(cfg)
                    log_evento(f"RSS custom agregado: {nom}")
                self._send_json({"ok": True, "feeds": feeds})
            elif ruta == "/api/rss_del":
                idx = safe_int(data.get("idx", -1), -1)
                cfg = cargar_config()
                feeds = list(cfg.get("feeds_rss_custom") or [])
                if 0 <= idx < len(feeds):
                    eliminado = feeds.pop(idx)
                    cfg["feeds_rss_custom"] = feeds
                    guardar_config(cfg)
                    log_evento(f"RSS custom eliminado: {eliminado}")
                self._send_json({"ok": True, "feeds": feeds})
            elif ruta == "/api/scan_dry":
                res = ejecutar_ciclo(modo_sonido=False, dry_run=True)
                self._send_json(res)
            elif ruta == "/api/scan":
                threading.Thread(target=correr_scan_bg, daemon=True).start()
                self._send_json({"started": True})
            elif ruta == "/api/sniper_toggle":
                with SNIPER_LOCK:
                    if SCAN_STATE["sniper_on"]:
                        if CURRENT_SNIPER_STOP is not None:
                            CURRENT_SNIPER_STOP.set()
                        CURRENT_SNIPER_STOP = None
                        SCAN_STATE["sniper_on"] = False
                        log_evento("Auto-Sniper Web detenido")
                    else:
                        evt = threading.Event()
                        CURRENT_SNIPER_STOP = evt
                        SCAN_STATE["sniper_on"] = True
                        log_evento("Auto-Sniper Web activado")
                        threading.Thread(target=loop_sniper_web, args=(evt,), daemon=True).start()
                self._send_json({"sniper_on": SCAN_STATE["sniper_on"]})
            elif ruta == "/api/test_tg":
                cfg_t = cargar_config()
                prueba = {
                    "id": "test_web_v13",
                    "fuente": "Freelancer.com",
                    "plataforma": "Freelancer",
                    "tipo_trabajo": "freelance",
                    "autor": "test_client",
                    "titulo": "Build Python Playwright scraper for Shopify stores ($250 USD)",
                    "texto": "Need a Python script to scrape product prices into CSV.",
                    "link": "https://www.freelancer.com/",
                    "comp_txt": "🎯 SANGRE FRESCA (1m | 1 bid)",
                    "prioridad_tag": "🐋 TEST v13",
                    "dinero_local": 250.0,
                    "presupuesto_txt": "$250 USD",
                    "origen": "freelancer",
                }
                _, env, _ = evaluar_y_enviar(prueba, cfg_t, modo_sonido=True)
                self._send_json({"ok": env})
            elif ruta == "/api/backup":
                dst = crear_backup_rotativo()
                self._send_json({"path": dst})
            elif ruta == "/api/config":
                cfg = cargar_config()
                cfg.update(data)
                guardar_config(cfg)
                log_evento("Configuracion actualizada desde Web OS")
                self._send_json({"ok": True})
            elif ruta == "/api/copiloto":
                entrada = str(data.get("entrada", "")).strip()
                autor = titulo = plat = tipo = ""
                if entrada.startswith("#") and entrada[1:].isdigit():
                    oferta, autor, titulo, plat, tipo = cargar_desde_crm_completo(int(entrada[1:]))
                elif entrada.startswith("http"):
                    oferta, autor, titulo, plat = descargar_oferta_universal(entrada)
                else:
                    oferta = entrada
                if not oferta:
                    self._send_json({"error": "No se pudo leer el enlace o ID"})
                    return
                res = analizar_oferta_completo(oferta, autor=autor, titulo=titulo, guardar_archivos=True, plataforma=plat, tipo_trabajo=tipo)
                self._send_json(res or {"error": "IA no respondio en este intento"})
            elif ruta == "/api/refinar":
                res = refinar_borrador_ia(str(data.get("instruccion", "")), str(data.get("ruta", "")))
                self._send_json(res)
            elif ruta == "/api/negociar":
                res = responder_objecion_ia(str(data.get("ctx", "")), str(data.get("msg", "")))
                self._send_json(res or {"error": "IA no respondio"})
            elif ruta == "/api/mkt_followup":
                res = generar_secuencia_followup_ia(str(data.get("ctx", "")))
                self._send_json(res or {"error": "IA no respondio"})
            elif ruta == "/api/mkt_delivery":
                res = generar_cierre_y_review_ia(str(data.get("ctx", "")))
                self._send_json(res or {"error": "IA no respondio"})
            elif ruta == "/api/mkt_post":
                cfg = cargar_config()
                sub = str(data.get("sub", "r/forhire"))
                enf = str(data.get("enfoque", "")).strip() or cfg.get("especialidad")
                prompt = (
                    f"Crea una publicacion persuasiva en ingles para {sub} que atraiga clientes freelance.\n"
                    f"Especialidad: {enf}\nPagos: {cfg.get('metodos_pago')}\nGitHub: {cfg.get('github_url')}\n"
                    "Responde UNICAMENTE con <TITULO>...</TITULO> y <CUERPO>...</CUERPO>."
                )
                txt = generar_texto_ia(prompt, temperatura=0.4)
                out = {"titulo": extraer_etiqueta(txt, "TITULO"), "cuerpo": extraer_etiqueta(txt, "CUERPO")} if txt else {"error": "IA no respondio"}
                self._send_json(out)
            elif ruta == "/api/mkt_bios":
                cfg = cargar_config()
                prompt = (
                    f"Crea 3 bios profesionales en ingles para un dev freelance ({cfg.get('especialidad')}).\n"
                    "Responde UNICAMENTE con <REDDIT_BIO>...</REDDIT_BIO>, <GITHUB_BIO>...</GITHUB_BIO> y <WHOP_BIO>...</WHOP_BIO>."
                )
                txt = generar_texto_ia(prompt, temperatura=0.4)
                out = {"reddit": extraer_etiqueta(txt, "REDDIT_BIO"), "github": extraer_etiqueta(txt, "GITHUB_BIO"), "whop": extraer_etiqueta(txt, "WHOP_BIO")} if txt else {"error": "IA no respondio"}
                self._send_json(out)
            elif ruta == "/api/mkt_portfolio":
                cfg = cargar_config()
                conn = preparar_db()
                try:
                    ganados = conn.execute("SELECT titulo, categoria FROM leads WHERE estado = 'ganado' ORDER BY id DESC LIMIT 6").fetchall()
                finally:
                    conn.close()
                prompt = (
                    "Crea un archivo PORTAFOLIO.md profesional y directo en ingles para GitHub y clientes freelance.\n"
                    f"Marca: {cfg.get('nombre_marca')}\nEspecialidad: {cfg.get('especialidad')}\n"
                    f"Proyectos ganados: {ganados}\nPagos: {cfg.get('metodos_pago')}\n"
                    "Incluye resumen, stack tecnico, 3 casos de estudio (ZeroTouch OMNI-GRID Lead Radar, Python Scrapers, Telegram Bots) y CTA.\n"
                    "Devuelve UNICAMENTE el contenido dentro de <PORTAFOLIO>...</PORTAFOLIO>."
                )
                txt = generar_texto_ia(prompt, temperatura=0.35)
                if not txt:
                    self._send_json({"error": "IA no respondio"})
                    return
                md = extraer_etiqueta(txt, "PORTAFOLIO") or txt
                with open(os.path.join(ROOT_DIR, "PORTAFOLIO.md"), "w", encoding="utf-8") as f:
                    f.write(md)
                self._send_json({"markdown": md})
            elif ruta == "/api/whop_pack":
                res = empaquetar_producto_whop(str(data.get("ruta", "")), str(data.get("nombre", "")))
                self._send_json(res)
            elif ruta == "/api/factura":
                _, _, html_doc = guardar_factura_local(
                    str(data.get("cliente", "Client")),
                    str(data.get("proyecto", "Custom Python Automation")),
                    str(data.get("monto", "100")),
                    str(data.get("tipo", "Final Payment")),
                    notas_extra=str(data.get("nota", "")),
                )
                self._send(200, "text/html; charset=utf-8", html_doc.encode("utf-8"))
            else:
                self._send(404, "text/plain", b"Not Found")
        except Exception as e:
            log_evento(f"Error POST {ruta}: {e}")
            self._send_json({"error": str(e)}, code=500)

def puerto_en_uso(puerto: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", puerto)) == 0

def main() -> None:
    puerto = 8765
    url = f"http://127.0.0.1:{puerto}"
    if puerto_en_uso(puerto):
        print(f"{C.GREEN}[+] El Dashboard Web ya estaba corriendo. Abriendo {url}...{C.RESET}")
        webbrowser.open(url)
        return
    server = ThreadingHTTPServer(("127.0.0.1", puerto), Handler)
    log_evento("Servidor Web OMNI-GRID v13.0 iniciado en " + url)
    print(f"\n{C.BOLD}{C.GREEN}=== ZEROTOUCH OMNI-GRID v13.0 WEB OS: {url} ==={C.RESET}")
    print(f"{C.DIM}Presiona Ctrl+C aqui cuando quieras apagar el servidor.{C.RESET}\n")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        if CURRENT_SNIPER_STOP is not None:
            CURRENT_SNIPER_STOP.set()
        print(f"\n{C.YELLOW}[*] Servidor web cerrado.{C.RESET}\n")
    finally:
        server.server_close()

if __name__ == "__main__":
    main()