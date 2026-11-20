import os
import io
import re
import csv
import sys
import json
import time
import socket
import zipfile
import threading
import webbrowser
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core_ia import (
    C,
    SESSION,
    safe_float,
    safe_int,
    cargar_config,
    guardar_config,
    preparar_db,
    crear_backup_rotativo,
    generar_texto_ia,
    extraer_etiqueta,
    limpiar_bloque_codigo,
    validar_y_reparar_python,
    analizar_dependencias,
)
from modulo_a_radar_whop.motor_zerotouch_v4 import ejecutar_ciclo
from modulo_b_ejecutor.copiloto import descargar_post_reddit, cargar_desde_crm, analizar_oferta_completo
from modulo_c_whop.empaquetador import crear_factura_html
from modulo_d_marketing.iman_clientes import responder_objecion_ia

SCAN_LOCK = threading.Lock()
SCAN_STATE = {"running": False, "last_result": None, "sniper_on": False, "sniper_ciclos": 0}
SNIPER_STOP = threading.Event()

HTML_DASHBOARD = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ZeroTouch TITAN v11.0 — Freelance OS</title>
<style>
  :root {
    --bg:#060911; --sidebar:#0b1120; --card:#0f172a; --card2:#162033;
    --border:#1e293b; --text:#f1f5f9; --muted:#94a3b8;
    --accent:#38bdf8; --green:#4ade80; --amber:#fbbf24; --red:#f87171; --purple:#c084fc;
  }
  * { box-sizing:border-box; }
  body { margin:0; font-family:'Segoe UI',system-ui,sans-serif; background:var(--bg); color:var(--text); display:flex; min-height:100vh; }
  .side { width:245px; background:var(--sidebar); border-right:1px solid var(--border); padding:20px 14px; display:flex; flex-direction:column; position:fixed; inset:0 auto 0 0; overflow-y:auto; }
  .brand { font-size:18px; font-weight:800; padding:4px 10px 16px; border-bottom:1px solid var(--border); margin-bottom:14px; }
  .brand span { color:var(--accent); }
  .brand small { display:block; font-size:11px; color:var(--muted); font-weight:500; margin-top:2px; }
  .nav-grp { font-size:10px; text-transform:uppercase; letter-spacing:.09em; color:#64748b; font-weight:700; padding:12px 10px 6px; }
  .nav-btn { width:100%; text-align:left; background:transparent; color:var(--muted); border:none; padding:10px 12px; border-radius:9px; cursor:pointer; font-size:13px; font-weight:600; display:flex; align-items:center; gap:9px; transition:.15s; margin-bottom:3px; }
  .nav-btn:hover { background:#1e293b88; color:var(--text); }
  .nav-btn.active { background:linear-gradient(135deg,#0284c7,#2563eb); color:#fff; box-shadow:0 4px 14px rgba(37,99,235,.35); }
  .side-foot { margin-top:auto; padding-top:14px; border-top:1px solid var(--border); font-size:11px; color:#64748b; text-align:center; }

  .main { margin-left:245px; flex:1; padding:24px 28px; max-width:calc(100% - 245px); }
  .topbar { display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:12px; margin-bottom:20px; }
  .topbar h2 { margin:0; font-size:20px; }
  .actions { display:flex; gap:8px; flex-wrap:wrap; }
  button, a.btn { background:#1e293b; color:var(--text); border:1px solid #334155; padding:8px 14px; border-radius:8px; cursor:pointer; font-size:13px; font-weight:600; text-decoration:none; transition:.15s; display:inline-flex; align-items:center; gap:6px; }
  button:hover, a.btn:hover { background:#334155; border-color:var(--accent); }
  button.primary { background:linear-gradient(135deg,#0284c7,#2563eb); border:none; color:#fff; }
  button.success { background:#065f46; border-color:#10b981; color:#ecfdf5; }
  button.purple { background:#581c87; border-color:#a855f7; color:#faf5ff; }
  button.danger { background:#7f1d1d; border-color:#ef4444; color:#fef2f2; }
  button.sniper-on { background:#14532d; border-color:#4ade80; color:#86efac; box-shadow:0 0 14px rgba(74,222,128,.25); }
  button.sm { padding:5px 9px; font-size:12px; }

  .view { display:none; animation:fade .18s ease; }
  .view.active { display:block; }
  @keyframes fade { from { opacity:0; transform:translateY(4px); } to { opacity:1; transform:none; } }

  .kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:12px; margin-bottom:18px; }
  .kpi { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:15px 17px; }
  .kpi .lbl { font-size:10.5px; text-transform:uppercase; color:var(--muted); letter-spacing:.06em; }
  .kpi .num { font-size:24px; font-weight:800; margin-top:5px; }
  .green { color:var(--green); } .cyan { color:var(--accent); } .amber { color:var(--amber); } .purple { color:var(--purple); }

  .toolbar { display:flex; gap:10px; flex-wrap:wrap; margin-bottom:14px; align-items:center; }
  input, select, textarea { background:#080d19; color:var(--text); border:1px solid #334155; padding:8px 11px; border-radius:8px; font-size:13px; font-family:inherit; }
  input:focus, select:focus, textarea:focus { outline:none; border-color:var(--accent); }
  textarea { width:100%; min-height:90px; resize:vertical; }

  .table-box { background:var(--card); border:1px solid var(--border); border-radius:12px; overflow:auto; }
  table { width:100%; border-collapse:collapse; min-width:1100px; }
  th, td { padding:10px 12px; border-bottom:1px solid var(--border); text-align:left; font-size:13px; vertical-align:middle; }
  th { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.06em; background:#0b1220; }
  tr:hover { background:#131d31; }
  .score { display:inline-block; padding:3px 8px; border-radius:6px; font-weight:700; font-size:12px; }
  .s-hi { background:#14532d; color:#86efac; } .s-mid { background:#1e3a8a; color:#93c5fd; }
  .pill { display:inline-block; font-size:10.5px; padding:2px 7px; border-radius:999px; background:#3b0764; color:#e9d5ff; margin-left:6px; font-weight:700; }
  a.title-link { color:#e2e8f0; text-decoration:none; font-weight:600; }
  a.title-link:hover { color:var(--accent); text-decoration:underline; }
  .meta { font-size:11.5px; color:var(--muted); margin-top:3px; }
  .usd-in { width:70px; }
  .note-in { width:135px; font-size:12px; padding:6px 8px; }

  .grid-2 { display:grid; grid-template-columns:repeat(auto-fit,minmax(390px,1fr)); gap:16px; }
  .card { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px; }
  .card h3 { margin:0 0 12px 0; font-size:15px; color:var(--accent); }
  .field { margin-bottom:12px; }
  .field label { display:block; font-size:12px; color:var(--muted); margin-bottom:5px; font-weight:600; }
  .field input, .field select { width:100%; }
  .prebox { background:#060911; border:1px solid #334155; border-radius:8px; padding:12px; white-space:pre-wrap; font-size:12.5px; line-height:1.5; max-height:240px; overflow:auto; font-family:Consolas,monospace; }
  .calc-box { background:#060911; border:1px solid #1e293b; border-radius:10px; padding:16px; margin-top:14px; }
  .calc-row { display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid #1e293b; font-size:13px; }
  .calc-row:last-child { border:none; font-size:17px; font-weight:800; color:var(--green); padding-top:10px; }

  .bar-row { margin-bottom:11px; }
  .bar-lbl { display:flex; justify-content:space-between; font-size:12px; margin-bottom:4px; }
  .bar-track { height:9px; background:#1e293b; border-radius:999px; overflow:hidden; }
  .bar-fill { height:100%; background:linear-gradient(90deg,#0284c7,#38bdf8); border-radius:999px; }
  .bar-fill.g { background:linear-gradient(90deg,#16a34a,#4ade80); }

  .modal-bg { position:fixed; inset:0; background:rgba(0,0,0,.75); display:none; align-items:center; justify-content:center; padding:20px; z-index:99; }
  .modal-bg.open { display:flex; }
  .modal { background:var(--card); border:1px solid #334155; border-radius:14px; max-width:860px; width:100%; max-height:88vh; overflow:auto; padding:24px; }

  .toast { position:fixed; bottom:22px; right:22px; background:#0f172a; border:1px solid var(--accent); color:#fff; padding:11px 16px; border-radius:10px; font-size:13px; font-weight:600; box-shadow:0 10px 30px rgba(0,0,0,.5); opacity:0; transform:translateY(12px); pointer-events:none; transition:.2s; z-index:120; }
  .toast.show { opacity:1; transform:none; }
  .status-bar { font-size:12px; color:var(--amber); margin-left:auto; }
  @media (max-width:860px) { .side { position:static; width:100%; height:auto; } body { flex-direction:column; } .main { margin-left:0; max-width:100%; padding:16px; } }
</style>
</head>
<body>
  <aside class="side">
    <div class="brand">⚡ ZeroTouch <span>TITAN</span><small>v11.0 Unified Freelance OS</small></div>
    <div class="nav-grp">Operacion</div>
    <button class="nav-btn active" onclick="verTab('t_crm','📡 Radar & CRM',this)">📡 Radar & CRM</button>
    <button class="nav-btn" onclick="verTab('t_stats','📊 Analytics',this)">📊 Analytics</button>
    <div class="nav-grp">Estudio IA</div>
    <button class="nav-btn" onclick="verTab('t_ai','🧠 Copiloto & Negociador',this)">🧠 Copiloto & Negociador</button>
    <div class="nav-grp">Negocio</div>
    <button class="nav-btn" onclick="verTab('t_mkt','🧲 Marketing & Portafolio',this)">🧲 Marketing & Portafolio</button>
    <button class="nav-btn" onclick="verTab('t_whop','📦 Whop, Facturas & Calc',this)">📦 Whop, Facturas & Calc</button>
    <div class="nav-grp">Sistema</div>
    <button class="nav-btn" onclick="verTab('t_cfg','⚙️ Ajustes & Salud',this)">⚙️ Ajustes & Salud</button>
    <div class="side-foot">SQLite WAL • 16 Fuentes • AST</div>
  </aside>

  <main class="main">
    <div class="topbar">
      <h2 id="pageTitle">📡 Radar & CRM</h2>
      <div class="actions">
        <button id="btnSniper" onclick="toggleSniper()">🎯 Auto-Sniper: OFF</button>
        <button class="primary" onclick="lanzarEscaneo()">🚀 Escanear Ahora</button>
        <button onclick="cargarDatos()">🔄</button>
        <a class="btn" href="/api/export">📥 Excel</a>
      </div>
    </div>

    <!-- 1. RADAR & CRM -->
    <section id="t_crm" class="view active">
      <div class="kpis">
        <div class="kpi"><div class="lbl">Facturado Total</div><div class="num green" id="kUsd">$0.00</div></div>
        <div class="kpi"><div class="lbl">Leads Totales</div><div class="num cyan" id="kLeads">0</div></div>
        <div class="kpi"><div class="lbl">Clientes Ganados</div><div class="num green" id="kGanados">0</div></div>
        <div class="kpi"><div class="lbl">Tasa de Cierre</div><div class="num cyan" id="kCierre">0%</div></div>
        <div class="kpi"><div class="lbl">Tokens Ahorrados</div><div class="num purple" id="kTok">0</div></div>
      </div>

      <div class="toolbar">
        <input type="text" id="qSearch" placeholder="Buscar titulo, subreddit, nota o categoria..." oninput="renderTabla()" style="min-width:260px;">
        <select id="qEstado" onchange="renderTabla()">
          <option value="">Todos los estados</option>
          <option value="nuevo">Nuevo</option>
          <option value="contactado">Contactado</option>
          <option value="negociando">Negociando</option>
          <option value="ganado">Ganado</option>
          <option value="descartado">Descartado</option>
        </select>
        <select id="qMinScore" onchange="renderTabla()">
          <option value="0">Cualquier Score</option>
          <option value="7">Score 7+</option>
          <option value="8">Score 8+ (Top)</option>
        </select>
        <div class="status-bar" id="scanStatus"></div>
      </div>

      <div class="table-box">
        <table>
          <thead>
            <tr><th>ID</th><th>Score</th><th>Fuente</th><th>Proyecto, Competencia & Cliente</th><th>Presupuesto</th><th>Estado</th><th>USD</th><th>Nota rapida</th><th>Acciones</th></tr>
          </thead>
          <tbody id="tbodyLeads"></tbody>
        </table>
      </div>
    </section>

    <!-- 2. ANALYTICS -->
    <section id="t_stats" class="view">
      <div class="grid-2">
        <div class="card"><h3>📍 Top Fuentes (Leads Detectados)</h3><div id="chFuentes"></div></div>
        <div class="card"><h3>🎯 Embudo de Conversion CRM</h3><div id="chEmbudo"></div></div>
        <div class="card"><h3>💵 Ingresos por Categoria (USD)</h3><div id="chCat"></div></div>
        <div class="card"><h3>⚡ Eficiencia de Tokens IA</h3><div id="chTokens"></div></div>
      </div>
    </section>

    <!-- 3. ESTUDIO IA -->
    <section id="t_ai" class="view">
      <div class="grid-2">
        <div class="card">
          <h3>🤖 Copiloto TITAN (Link Reddit, #ID o Texto)</h3>
          <div class="field"><textarea id="aiOferta" placeholder="Pega un link de Reddit, escribe #4, o pega la descripcion del cliente..."></textarea></div>
          <button class="primary" onclick="correrCopilotoWeb()">Generar Pitch A/B + Precios + Codigo</button>
          <div id="aiResCopiloto" style="margin-top:14px;"></div>
        </div>
        <div class="card">
          <h3>⚔️ Negociador Mata-Objeciones</h3>
          <div class="field"><label>Contexto y precio pedido</label><input id="negCtx" placeholder="Ej. Scraper Shopify, pedi $120 USD"></div>
          <div class="field"><label>Que te respondio el cliente?</label><textarea id="negMsg" placeholder="Ej. Can you do it for $40 or build a free sample first?"></textarea></div>
          <button class="purple" onclick="correrNegociadorWeb()">Generar Contraofertas</button>
          <div id="aiResNeg" style="margin-top:14px;"></div>
        </div>
      </div>
    </section>

    <!-- 4. MARKETING & PORTAFOLIO -->
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
          <button class="primary" onclick="generarPostWeb()">Redactar Post Magnetico</button>
          <div id="resMktPost" style="margin-top:14px;"></div>
        </div>
        <div class="card">
          <h3>✨ Bios & Portafolio Profesional</h3>
          <div class="actions" style="margin-bottom:14px;">
            <button class="purple" onclick="generarBiosWeb()">✨ Generar 3 Bios</button>
            <button class="success" onclick="generarPortafolioWeb()">📂 Generar PORTAFOLIO.md</button>
          </div>
          <div id="resMktBios"></div>
        </div>
      </div>
    </section>

    <!-- 5. WHOP, FACTURAS & CALCULADORA -->
    <section id="t_whop" class="view">
      <div class="grid-2">
        <div class="card">
          <h3>🧮 Calculadora Freelance (USD → COP Neto)</h3>
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
            <div class="calc-row"><span>Neto aproximado en Colombia</span><b id="cNetoCop">$420,000 COP</b></div>
          </div>
        </div>

        <div class="card">
          <h3>📄 Factura + Micro-Contrato PDF</h3>
          <div class="field"><label>Cliente / Usuario</label><input id="invCli" placeholder="u/john_founder"></div>
          <div class="field"><label>Concepto del proyecto</label><input id="invProj" placeholder="Custom Python Shopify Scraper & CSV Pipeline"></div>
          <div class="field"><label>Monto (USD)</label><input id="invUsd" type="number" value="120"></div>
          <div class="field"><label>Modalidad</label>
            <select id="invTipo">
              <option value="50% Deposit (Project Start)">50% Adelanto (Inicio)</option>
              <option value="Final Payment (Full Delivery)">100% Pago Final (Entrega)</option>
              <option value="Monthly Retainer / Maintenance">Mensualidad / Mantenimiento</option>
            </select>
          </div>
          <button class="success" onclick="generarFacturaWeb()">Abrir Factura Lista para PDF</button>
          <hr style="border:none;border-top:1px solid var(--border);margin:20px 0;">
          <h3>📦 Fabrica 1-Click para Whop (.ZIP)</h3>
          <div class="field"><label>Nombre comercial</label><input id="whopNom" placeholder="Ej. AutoLead Scraper Pro"></div>
          <div class="field"><label>Ruta script (vacio = borrador_cliente.py)</label><input id="whopRuta" placeholder="modulo_b_ejecutor/borrador_cliente.py"></div>
          <button class="purple" onclick="empaquetarWhopWeb()">Empaquetar .ZIP + Copy + Guion</button>
          <div id="resWhop" style="margin-top:12px;"></div>
        </div>
      </div>
    </section>

    <!-- 6. AJUSTES & SALUD -->
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
            <div class="field"><label>Score Min</label><input id="cScore" type="number"></div>
            <div class="field"><label>Sniper (s)</label><input id="cSniper" type="number"></div>
          </div>
          <div class="field"><label>Telegram Admin ID (control remoto DM)</label><input id="cAdmin" placeholder="Opcional"></div>
          <button class="primary" onclick="guardarConfigWeb()">💾 Guardar Configuracion</button>
        </div>
        <div class="card">
          <h3>🩺 Salud del Sistema & Respaldos</h3>
          <div class="actions" style="margin-bottom:14px;">
            <button class="primary" onclick="correrDiagWeb()">🩺 Probar Conexiones</button>
            <button class="success" onclick="hacerBackupWeb()">💾 Backup DB</button>
          </div>
          <div id="resDiag" class="prebox">Haz clic en "Probar Conexiones" para revisar Reddit, Telegram y Gemini.</div>
        </div>
      </div>
    </section>
  </main>

  <div class="modal-bg" id="modalBg" onclick="if(event.target===this)cerrarModal()">
    <div class="modal">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
        <h3 style="margin:0;color:var(--accent);" id="modalTitle">🤖 Copiloto TITAN</h3>
        <button class="sm" onclick="cerrarModal()">Cerrar</button>
      </div>
      <div id="modalBody">Cargando...</div>
    </div>
  </div>
  <div id="toast" class="toast"></div>

<script>
let DATA = { leads:[], kpis:{}, analytics:{}, scan:{} };
const CLIP_STORE = {};
let CLIP_SEQ = 0;

function esc(s){ return String(s||'').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }
function toast(msg){ const t = document.getElementById('toast'); t.textContent = msg; t.classList.add('show'); setTimeout(()=> t.classList.remove('show'), 2500); }
function regClip(txt){ const id = 'c' + (++CLIP_SEQ); CLIP_STORE[id] = String(txt || ''); return id; }
function copyId(id){ navigator.clipboard.writeText(CLIP_STORE[id] || ''); toast('✅ Copiado al portapapeles'); }
function cerrarModal(){ document.getElementById('modalBg').classList.remove('open'); }

function verTab(id, title, btn){
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  document.getElementById('pageTitle').textContent = title;
  btn.classList.add('active');
  if(id === 't_cfg') cargarConfigWeb();
  if(id === 't_whop') calcularPrecio();
}

function calcularPrecio(){
  const hrs = parseFloat(document.getElementById('calcHrs').value || '0');
  const rate = parseFloat(document.getElementById('calcRate').value || '0');
  const mult = parseFloat(document.getElementById('calcMult').value || '1');
  const feeType = document.getElementById('calcFee').value;
  const trm = parseFloat(document.getElementById('calcTrm').value || '4200');
  const bruto = hrs * rate * mult;
  let com = 0;
  if(feeType === 'paypal' && bruto > 0) com = bruto * 0.054 + 0.30;
  else if(feeType === 'airtm') com = bruto * 0.02;
  const neto = Math.max(0, bruto - com);
  const cop = Math.round(neto * trm);
  document.getElementById('cBruto').textContent = '$' + bruto.toFixed(2) + ' USD';
  document.getElementById('cCom').textContent = '-$' + com.toFixed(2) + ' USD';
  document.getElementById('cNetoUsd').textContent = '$' + neto.toFixed(2) + ' USD';
  document.getElementById('cNetoCop').textContent = '$' + cop.toLocaleString('es-CO') + ' COP';
}

async function toggleSniper(){
  const r = await fetch('/api/sniper_toggle', { method:'POST' });
  const d = await r.json();
  toast(d.sniper_on ? '🎯 Auto-Sniper ACTIVADO en segundo plano' : '⏹️ Auto-Sniper detenido');
  await cargarDatos();
}

async function cargarDatos(){
  const r = await fetch('/api/data');
  DATA = await r.json();
  document.getElementById('kUsd').textContent = '$' + Number(DATA.kpis.usd || 0).toFixed(2);
  document.getElementById('kLeads').textContent = DATA.kpis.leads_total;
  document.getElementById('kGanados').textContent = DATA.kpis.ganados;
  document.getElementById('kCierre').textContent = DATA.kpis.tasa_cierre + '%';
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
  if(DATA.scan.running){ st.textContent = '⏳ Escaneando 16 fuentes en segundo plano...'; }
  else if(DATA.scan.last_result){ const lr = DATA.scan.last_result; st.textContent = `✅ Ultimo barrido: ${lr.alertas} alertas | ${lr.descartados} filtrados (${lr.segundos}s)`; }
  renderTabla();
  renderAnalytics();
}

function renderTabla(){
  const q = document.getElementById('qSearch').value.toLowerCase();
  const est = document.getElementById('qEstado').value;
  const minS = parseInt(document.getElementById('qMinScore').value || '0', 10);
  const filtrados = (DATA.leads || []).filter(l => l.score >= minS && (!est || l.estado === est) && (!q || (l.titulo+' '+l.fuente+' '+l.categoria+' '+(l.notas||'')).toLowerCase().includes(q)));
  const tb = document.getElementById('tbodyLeads');
  if(!filtrados.length){ tb.innerHTML = '<tr><td colspan="9" style="text-align:center;color:#94a3b8;padding:28px;">Sin leads para este filtro. Haz clic en "Escanear Ahora".</td></tr>'; return; }
  tb.innerHTML = filtrados.map(l => `
    <tr>
      <td><b>#${l.id}</b></td>
      <td><span class="score ${l.score>=8?'s-hi':'s-mid'}">${l.score}/10</span></td>
      <td><div>${esc(l.fuente)}</div><div class="meta">${esc(l.categoria)}</div></td>
      <td>
        <a class="title-link" href="${esc(l.link)}" target="_blank">${esc(l.titulo)}</a>
        ${l.prioridad_tag ? `<span class="pill">${esc(l.prioridad_tag)}</span>` : ''}
        <div class="meta">${esc(l.competencia)} ${l.confianza ? ' • ' + esc(l.confianza) : ''}</div>
      </td>
      <td>${esc(l.presupuesto)}</td>
      <td>
        <select id="est_${l.id}">
          ${['nuevo','contactado','negociando','ganado','descartado'].map(o => `<option value="${o}" ${l.estado===o?'selected':''}>${o}</option>`).join('')}
        </select>
      </td>
      <td><input class="usd-in" type="number" step="1" id="usd_${l.id}" value="${l.ganancia_usd || 0}"></td>
      <td><input class="note-in" type="text" id="not_${l.id}" value="${esc(l.notas || '')}" placeholder="Nota..."></td>
      <td style="white-space:nowrap;">
        <button class="success sm" onclick="guardarLead(${l.id})" title="Guardar">💾</button>
        <button class="purple sm" onclick="abrirCopilotoLead(${l.id})" title="Copiloto IA">🤖</button>
        <button class="danger sm" onclick="borrarLead(${l.id})" title="Eliminar">🗑️</button>
      </td>
    </tr>
  `).join('');
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
  await fetch('/api/update', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id, estado, usd, notas}) });
  toast(`✅ Lead #${id} guardado`);
  await cargarDatos();
}

async function borrarLead(id){
  if(!confirm(`Eliminar el lead #${id} de tu CRM?`)) return;
  await fetch('/api/delete', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id}) });
  toast(`🗑️ Lead #${id} eliminado`);
  await cargarDatos();
}

async function lanzarEscaneo(){
  document.getElementById('scanStatus').textContent = '⏳ Iniciando escaneo TITAN...';
  toast('🚀 Escaneo de 16 fuentes iniciado');
  await fetch('/api/scan', { method:'POST' });
  setTimeout(cargarDatos, 2000);
}

function renderBloqueCopiloto(res){
  if(!res || res.error) return `<div style="color:var(--red);">Error: ${esc(res ? res.error : 'Sin respuesta')}</div>`;
  const idA = regClip(res.pitch_a), idB = regClip(res.pitch_b), idC = regClip(res.micro_contrato), idCode = regClip(res.codigo);
  return `
    ${res.confianza ? `<div class="meta" style="margin-bottom:8px;color:var(--purple);font-weight:700;">${esc(res.confianza)}</div>` : ''}
    <div class="field"><label>Diagnostico</label><div class="prebox">${esc(res.diagnostico)}</div></div>
    <div class="field"><label>Precios Sugeridos</label><div class="prebox">${esc(res.precios)}</div></div>
    <div class="field"><label>Pitch A (Tecnico) <button class="sm" onclick="copyId('${idA}')">Copiar</button> ${res.dm_url ? `<a class="btn sm" href="${esc(res.dm_url)}" target="_blank">⚡ DM Reddit</a>` : ''}</label><div class="prebox">${esc(res.pitch_a)}</div></div>
    <div class="field"><label>Pitch B (Consultivo) <button class="sm" onclick="copyId('${idB}')">Copiar</button></label><div class="prebox">${esc(res.pitch_b)}</div></div>
    <div class="field"><label>Micro-Contrato <button class="sm" onclick="copyId('${idC}')">Copiar</button></label><div class="prebox">${esc(res.micro_contrato)}</div></div>
    ${res.codigo ? `<div class="field"><label>Codigo Python (${res.ast_valido ? '✅ AST OK' : '⚠️ Revisar'}) <button class="sm" onclick="copyId('${idCode}')">Copiar Codigo</button></label><div class="prebox">${esc(res.codigo)}</div></div>` : ''}
    <div class="meta">Guardado automaticamente en modulo_b_ejecutor/borrador_cliente.py</div>
  `;
}

async function abrirCopilotoLead(id){
  document.getElementById('modalTitle').textContent = '🤖 Copiloto TITAN — Lead #' + id;
  document.getElementById('modalBody').innerHTML = '⏳ Analizando post y generando Pitch A/B + Codigo Python...';
  document.getElementById('modalBg').classList.add('open');
  const r = await fetch('/api/copiloto', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({entrada: '#' + id}) });
  document.getElementById('modalBody').innerHTML = renderBloqueCopiloto(await r.json());
}

async function correrCopilotoWeb(){
  const entrada = document.getElementById('aiOferta').value.trim();
  if(!entrada) return toast('⚠️ Pega un link, #ID o texto primero');
  document.getElementById('aiResCopiloto').innerHTML = '⏳ Generando estrategia, pitches y codigo...';
  const r = await fetch('/api/copiloto', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({entrada}) });
  document.getElementById('aiResCopiloto').innerHTML = renderBloqueCopiloto(await r.json());
}

async function correrNegociadorWeb(){
  const ctx = document.getElementById('negCtx').value.trim();
  const msg = document.getElementById('negMsg').value.trim();
  if(!msg) return toast('⚠️ Escribe lo que te dijo el cliente');
  document.getElementById('aiResNeg').innerHTML = '⏳ Calculando contraofertas...';
  const r = await fetch('/api/negociar', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ctx, msg}) });
  const d = await r.json();
  if(d.error){ document.getElementById('aiResNeg').innerHTML = esc(d.error); return; }
  const idF = regClip(d.firme), idFl = regClip(d.flexible);
  document.getElementById('aiResNeg').innerHTML = `
    <div class="field"><label>Lectura Tactica</label><div class="prebox">${esc(d.consejo)}</div></div>
    <div class="field"><label>Respuesta Firme <button class="sm" onclick="copyId('${idF}')">Copiar</button></label><div class="prebox">${esc(d.firme)}</div></div>
    <div class="field"><label>Respuesta Flexible <button class="sm" onclick="copyId('${idFl}')">Copiar</button></label><div class="prebox">${esc(d.flexible)}</div></div>
  `;
}

async function generarPostWeb(){
  const sub = document.getElementById('mktSub').value;
  const enfoque = document.getElementById('mktEnf').value.trim();
  document.getElementById('resMktPost').innerHTML = '⏳ Redactando post magnetico...';
  const r = await fetch('/api/mkt_post', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({sub, enfoque}) });
  const d = await r.json();
  if(d.error){ document.getElementById('resMktPost').innerHTML = esc(d.error); return; }
  const idT = regClip(d.titulo), idC = regClip(d.cuerpo);
  document.getElementById('resMktPost').innerHTML = `
    <div class="field"><label>Titulo <button class="sm" onclick="copyId('${idT}')">Copiar</button></label><div class="prebox">${esc(d.titulo)}</div></div>
    <div class="field"><label>Cuerpo Markdown <button class="sm" onclick="copyId('${idC}')">Copiar</button></label><div class="prebox">${esc(d.cuerpo)}</div></div>
  `;
}

async function generarBiosWeb(){
  document.getElementById('resMktBios').innerHTML = '⏳ Generando 3 bios...';
  const r = await fetch('/api/mkt_bios', { method:'POST', headers:{'Content-Type':'application/json'}, body: '{}' });
  const d = await r.json();
  if(d.error){ document.getElementById('resMktBios').innerHTML = esc(d.error); return; }
  const idR = regClip(d.reddit), idG = regClip(d.github), idW = regClip(d.whop);
  document.getElementById('resMktBios').innerHTML = `
    <div class="field"><label>Reddit Bio <button class="sm" onclick="copyId('${idR}')">Copiar</button></label><div class="prebox">${esc(d.reddit)}</div></div>
    <div class="field"><label>GitHub Bio <button class="sm" onclick="copyId('${idG}')">Copiar</button></label><div class="prebox">${esc(d.github)}</div></div>
    <div class="field"><label>Whop Bio <button class="sm" onclick="copyId('${idW}')">Copiar</button></label><div class="prebox">${esc(d.whop)}</div></div>
  `;
}

async function generarPortafolioWeb(){
  document.getElementById('resMktBios').innerHTML = '⏳ Construyendo PORTAFOLIO.md profesional...';
  const r = await fetch('/api/mkt_portfolio', { method:'POST', headers:{'Content-Type':'application/json'}, body: '{}' });
  const d = await r.json();
  if(d.error){ document.getElementById('resMktBios').innerHTML = esc(d.error); return; }
  const idP = regClip(d.markdown);
  document.getElementById('resMktBios').innerHTML = `
    <div class="meta" style="color:var(--green);margin-bottom:8px;">✅ Guardado en PORTAFOLIO.md</div>
    <div class="field"><label>PORTAFOLIO.md <button class="sm" onclick="copyId('${idP}')">Copiar Markdown</button></label><div class="prebox">${esc(d.markdown)}</div></div>
  `;
  toast('📂 PORTAFOLIO.md creado');
}

async function empaquetarWhopWeb(){
  const nombre = document.getElementById('whopNom').value.trim() || 'ZeroTouch Automation Tool';
  const ruta = document.getElementById('whopRuta').value.trim();
  document.getElementById('resWhop').innerHTML = '⏳ Refactorizando codigo y armando .ZIP comercial...';
  const r = await fetch('/api/whop_pack', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({nombre, ruta}) });
  const d = await r.json();
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
    tipo: document.getElementById('invTipo').value
  };
  const r = await fetch('/api/factura', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
  const htmlTxt = await r.text();
  const w = window.open('', '_blank');
  w.document.open(); w.document.write(htmlTxt); w.document.close();
}

async function cargarConfigWeb(){
  const r = await fetch('/api/config');
  const c = await r.json();
  document.getElementById('cMarca').value = c.nombre_marca || '';
  document.getElementById('cEsp').value = c.especialidad || '';
  document.getElementById('cPagos').value = c.metodos_pago || '';
  document.getElementById('cPagosFac').value = c.detalle_pago_factura || '';
  document.getElementById('cGh').value = c.github_url || '';
  document.getElementById('cWhop').value = c.whop_url || '';
  document.getElementById('cTarifa').value = c.tarifa_hora_usd || 25;
  document.getElementById('cScore').value = c.score_minimo || 6;
  document.getElementById('cSniper').value = c.intervalo_sniper_seg || 70;
  document.getElementById('cAdmin').value = c.telegram_admin_id || '';
  document.getElementById('calcRate').value = c.tarifa_hora_usd || 25;
  document.getElementById('calcTrm').value = c.trm_cop || 4200;
}

async function guardarConfigWeb(){
  const payload = {
    nombre_marca: document.getElementById('cMarca').value,
    especialidad: document.getElementById('cEsp').value,
    metodos_pago: document.getElementById('cPagos').value,
    detalle_pago_factura: document.getElementById('cPagosFac').value,
    github_url: document.getElementById('cGh').value,
    whop_url: document.getElementById('cWhop').value,
    tarifa_hora_usd: parseInt(document.getElementById('cTarifa').value || '25', 10),
    score_minimo: parseInt(document.getElementById('cScore').value || '6', 10),
    intervalo_sniper_seg: Math.max(45, parseInt(document.getElementById('cSniper').value || '70', 10)),
    telegram_admin_id: document.getElementById('cAdmin').value.trim()
  };
  await fetch('/api/config', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
  toast('💾 Configuracion guardada');
}

async function correrDiagWeb(){
  document.getElementById('resDiag').textContent = '⏳ Probando Reddit, Telegram y Gemini...';
  const r = await fetch('/api/diagnostico');
  const d = await r.json();
  document.getElementById('resDiag').textContent = d.reporte;
}

async function hacerBackupWeb(){
  const r = await fetch('/api/backup', { method:'POST' });
  const d = await r.json();
  toast(d.path ? '💾 Backup creado en backups/' : '⚠️ No hay DB todavia');
}

cargarDatos();
setInterval(cargarDatos, 15000);
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
    finally:
        SCAN_STATE["running"] = False
        SCAN_LOCK.release()

def loop_sniper_web() -> None:
    while not SNIPER_STOP.is_set():
        SCAN_STATE["sniper_ciclos"] += 1
        correr_scan_bg()
        intervalo = max(45, safe_int(cargar_config().get("intervalo_sniper_seg", 70), 70))
        if SNIPER_STOP.wait(intervalo):
            break
    SCAN_STATE["sniper_on"] = False

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send(self, code: int, content_type: str, data: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self) -> None:
        if self.path == "/":
            self._send(200, "text/html; charset=utf-8", HTML_DASHBOARD.encode("utf-8"))
        elif self.path == "/api/config":
            self._send(200, "application/json; charset=utf-8", json.dumps(cargar_config()).encode("utf-8"))
        elif self.path == "/api/diagnostico":
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
            try:
                rr = SESSION.get("https://www.reddit.com/r/forhire/new.json?limit=1", headers={"User-Agent": "python:zerotouch-diag:v11.0"}, timeout=6)
                lineas.append(f"5. Reddit API        : {'OK (JSON en vivo)' if rr.status_code == 200 else 'Fallback XML Nativo (HTTP ' + str(rr.status_code) + ')'}")
            except Exception as e:
                lineas.append(f"5. Reddit API        : Error ({e})")
            resp = generar_texto_ia("Responde solo OK", temperatura=0.0, timeout=10) if key else None
            lineas.append(f"6. Gemini API        : {'OK' if resp else 'SIN RESPUESTA'}")
            self._send(200, "application/json; charset=utf-8", json.dumps({"reporte": "\n".join(lineas)}).encode("utf-8"))
        elif self.path == "/api/data":
            conn = preparar_db()
            try:
                rows = conn.execute(
                    "SELECT id, fecha, fuente, autor, titulo, categoria, presupuesto, score, competencia, confianza, prioridad_tag, link, estado, ganancia_usd, notas FROM leads ORDER BY id DESC LIMIT 150"
                ).fetchall()
                leads = [
                    {
                        "id": r[0], "fecha": r[1], "fuente": r[2], "autor": r[3], "titulo": r[4],
                        "categoria": r[5], "presupuesto": r[6], "score": r[7], "competencia": r[8],
                        "confianza": r[9], "prioridad_tag": r[10], "link": r[11], "estado": r[12],
                        "ganancia_usd": r[13], "notas": r[14] or "",
                    }
                    for r in rows
                ]
                leads_total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
                usd = conn.execute("SELECT COALESCE(SUM(ganancia_usd), 0) FROM leads WHERE estado = 'ganado'").fetchone()[0]
                ganados = conn.execute("SELECT COUNT(*) FROM leads WHERE estado = 'ganado'").fetchone()[0]
                activos_neg = conn.execute("SELECT COUNT(*) FROM leads WHERE estado IN ('contactado','negociando','ganado')").fetchone()[0]
                tasa = round((ganados / activos_neg) * 100) if activos_neg > 0 else 0
                st_row = conn.execute("SELECT COALESCE(SUM(descartados_local), 0), COALESCE(SUM(tokens_est_usados), 0), COALESCE(SUM(tokens_est_ahorrados), 0) FROM stats_diarias").fetchone()
                por_fuente = conn.execute("SELECT fuente, COUNT(*) FROM leads GROUP BY fuente ORDER BY COUNT(*) DESC LIMIT 7").fetchall()
                embudo = conn.execute("SELECT estado, COUNT(*) FROM leads GROUP BY estado ORDER BY COUNT(*) DESC").fetchall()
                usd_cat = conn.execute("SELECT categoria, ROUND(SUM(ganancia_usd), 2) FROM leads WHERE estado = 'ganado' GROUP BY categoria ORDER BY SUM(ganancia_usd) DESC LIMIT 6").fetchall()
                payload = {
                    "leads": leads,
                    "kpis": {
                        "usd": usd, "leads_total": leads_total, "ganados": ganados, "tasa_cierre": tasa,
                        "descartados": st_row[0], "tok_usados": st_row[1], "tok_ahorrados": st_row[2],
                    },
                    "analytics": {"por_fuente": por_fuente, "embudo": embudo, "usd_categoria": usd_cat},
                    "scan": SCAN_STATE,
                }
                self._send(200, "application/json; charset=utf-8", json.dumps(payload).encode("utf-8"))
            finally:
                conn.close()
        elif self.path == "/api/export":
            conn = preparar_db()
            try:
                rows = conn.execute(
                    "SELECT id, fecha, fuente, autor, titulo, categoria, presupuesto, score, competencia, confianza, prioridad_tag, estado, ganancia_usd, notas, link FROM leads ORDER BY id DESC"
                ).fetchall()
                buf = io.StringIO()
                w = csv.writer(buf)
                w.writerow(["ID", "Fecha", "Fuente", "Autor", "Titulo", "Categoria", "Presupuesto", "Score", "Competencia", "Confianza", "Tag", "Estado", "Ganancia_USD", "Notas", "Link"])
                w.writerows(rows)
                data = ("\ufeff" + buf.getvalue()).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="crm_titan_{datetime.now().strftime("%Y%m%d")}.csv"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            finally:
                conn.close()
        else:
            self._send(404, "text/plain", b"Not Found")

    def do_POST(self) -> None:
        data = self._json_body()
        if self.path == "/api/update":
            conn = preparar_db()
            try:
                conn.execute(
                    "UPDATE leads SET estado = ?, ganancia_usd = ?, notas = ? WHERE id = ?",
                    (
                        str(data.get("estado", "nuevo")),
                        safe_float(data.get("usd", 0), 0.0),
                        str(data.get("notas", ""))[:300],
                        safe_int(data.get("id", 0), 0),
                    ),
                )
                conn.commit()
            finally:
                conn.close()
            self._send(200, "application/json", b'{"ok": true}')
        elif self.path == "/api/delete":
            conn = preparar_db()
            try:
                conn.execute("DELETE FROM leads WHERE id = ?", (safe_int(data.get("id", 0), 0),))
                conn.commit()
            finally:
                conn.close()
            self._send(200, "application/json", b'{"ok": true}')
        elif self.path == "/api/scan":
            threading.Thread(target=correr_scan_bg, daemon=True).start()
            self._send(200, "application/json", b'{"started": true}')
        elif self.path == "/api/sniper_toggle":
            if SCAN_STATE["sniper_on"]:
                SNIPER_STOP.set()
                SCAN_STATE["sniper_on"] = False
            else:
                SNIPER_STOP.clear()
                SCAN_STATE["sniper_on"] = True
                threading.Thread(target=loop_sniper_web, daemon=True).start()
            self._send(200, "application/json", json.dumps({"sniper_on": SCAN_STATE["sniper_on"]}).encode("utf-8"))
        elif self.path == "/api/backup":
            dst = crear_backup_rotativo()
            self._send(200, "application/json", json.dumps({"path": dst}).encode("utf-8"))
        elif self.path == "/api/config":
            cfg = cargar_config()
            cfg.update(data)
            guardar_config(cfg)
            self._send(200, "application/json", b'{"ok": true}')
        elif self.path == "/api/copiloto":
            entrada = str(data.get("entrada", "")).strip()
            autor = titulo = ""
            if entrada.startswith("#") and entrada[1:].isdigit():
                oferta, autor, titulo = cargar_desde_crm(int(entrada[1:]))
            elif entrada.startswith("http") and "reddit.com" in entrada:
                oferta, autor, titulo = descargar_post_reddit(entrada)
            else:
                oferta = entrada
            if not oferta:
                self._send(200, "application/json", json.dumps({"error": "No se pudo leer el post o ID"}).encode("utf-8"))
                return
            res = analizar_oferta_completo(oferta, autor=autor, titulo=titulo, guardar_archivos=True)
            self._send(200, "application/json; charset=utf-8", json.dumps(res or {"error": "IA no respondio"}).encode("utf-8"))
        elif self.path == "/api/negociar":
            res = responder_objecion_ia(str(data.get("ctx", "")), str(data.get("msg", "")))
            self._send(200, "application/json; charset=utf-8", json.dumps(res or {"error": "IA no respondio"}).encode("utf-8"))
        elif self.path == "/api/mkt_post":
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
            self._send(200, "application/json; charset=utf-8", json.dumps(out).encode("utf-8"))
        elif self.path == "/api/mkt_bios":
            cfg = cargar_config()
            prompt = (
                f"Crea 3 bios profesionales en ingles para un dev freelance ({cfg.get('especialidad')}).\n"
                "Responde UNICAMENTE con <REDDIT_BIO>...</REDDIT_BIO>, <GITHUB_BIO>...</GITHUB_BIO> y <WHOP_BIO>...</WHOP_BIO>."
            )
            txt = generar_texto_ia(prompt, temperatura=0.4)
            out = {"reddit": extraer_etiqueta(txt, "REDDIT_BIO"), "github": extraer_etiqueta(txt, "GITHUB_BIO"), "whop": extraer_etiqueta(txt, "WHOP_BIO")} if txt else {"error": "IA no respondio"}
            self._send(200, "application/json; charset=utf-8", json.dumps(out).encode("utf-8"))
        elif self.path == "/api/mkt_portfolio":
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
                "Incluye resumen, stack tecnico, 3 casos de estudio (ZeroTouch 24/7 Lead Radar, Python Scrapers, Telegram Bots) y CTA.\n"
                "Devuelve UNICAMENTE el contenido dentro de <PORTAFOLIO>...</PORTAFOLIO>."
            )
            txt = generar_texto_ia(prompt, temperatura=0.35)
            if not txt:
                self._send(200, "application/json", json.dumps({"error": "IA no respondio"}).encode("utf-8"))
                return
            md = extraer_etiqueta(txt, "PORTAFOLIO") or txt
            with open(os.path.join(ROOT_DIR, "PORTAFOLIO.md"), "w", encoding="utf-8") as f:
                f.write(md)
            self._send(200, "application/json; charset=utf-8", json.dumps({"markdown": md}).encode("utf-8"))
        elif self.path == "/api/whop_pack":
            nombre = str(data.get("nombre", "ZeroTouch Tool")).strip()
            ruta = str(data.get("ruta", "")).strip() or os.path.join(ROOT_DIR, "modulo_b_ejecutor", "borrador_cliente.py")
            if not os.path.exists(ruta):
                self._send(200, "application/json", json.dumps({"error": f"No existe el archivo: {ruta}"}).encode("utf-8"))
                return
            with open(ruta, "r", encoding="utf-8") as f:
                cod_raw = f.read()
            prompt = (
                f"Convierte este script en producto comercial Whop llamado '{nombre}'.\n"
                "Responde UNICAMENTE con <CODIGO_LIMPIO>, <README>, <WHOP_COPY> y <GUION_SHORT>.\n\n"
                f"SCRIPT:\n{cod_raw}"
            )
            txt = generar_texto_ia(prompt, temperatura=0.25, timeout=32)
            if not txt:
                self._send(200, "application/json", json.dumps({"error": "IA no respondio"}).encode("utf-8"))
                return
            cod, _ = validar_y_reparar_python(extraer_etiqueta(txt, "CODIGO_LIMPIO"), descripcion=nombre)
            readme = limpiar_bloque_codigo(extraer_etiqueta(txt, "README"))
            whop = extraer_etiqueta(txt, "WHOP_COPY")
            guion = extraer_etiqueta(txt, "GUION_SHORT")
            todos_pip, _ = analizar_dependencias(cod)
            carp = os.path.join(ROOT_DIR, "modulo_c_whop", "producto_listo")
            os.makedirs(carp, exist_ok=True)
            slug = re.sub(r"[^a-zA-Z0-9]+", "_", nombre.lower()).strip("_") or "producto"
            launcher = "@echo off\r\npython -m pip install -r requirements.txt\r\npython main.py\r\npause\r\n"
            for fn, ct in [("main.py", cod), ("README.md", readme), ("requirements.txt", ("\n".join(todos_pip) or "# stdlib") + "\n"), ("RUN_WINDOWS.bat", launcher), ("WHOP_LISTING.md", whop), ("GUION_SHORT.txt", guion)]:
                with open(os.path.join(carp, fn), "w", encoding="utf-8") as f:
                    f.write(ct)
            zpath = os.path.join(carp, f"{slug}_whop_prime.zip")
            with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
                for fn in ("main.py", "README.md", "requirements.txt", "RUN_WINDOWS.bat"):
                    zf.write(os.path.join(carp, fn), arcname=fn)
            self._send(200, "application/json; charset=utf-8", json.dumps({"zip_path": zpath, "whop_copy": whop}).encode("utf-8"))
        elif self.path == "/api/factura":
            _, html_doc = crear_factura_html(
                str(data.get("cliente", "Client")),
                str(data.get("proyecto", "Custom Python Automation")),
                str(data.get("monto", "100")),
                str(data.get("tipo", "Final Payment")),
                incluir_contrato=True,
            )
            self._send(200, "text/html; charset=utf-8", html_doc.encode("utf-8"))
        else:
            self._send(404, "text/plain", b"Not Found")

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
    print(f"\n{C.BOLD}{C.GREEN}=== ZEROTOUCH TITAN v11.0 WEB OS: {url} ==={C.RESET}")
    print(f"{C.DIM}Presiona Ctrl+C aqui cuando quieras apagar el servidor.{C.RESET}\n")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        SNIPER_STOP.set()
        print(f"\n{C.YELLOW}[*] Servidor web cerrado.{C.RESET}\n")
    finally:
        server.server_close()

if __name__ == "__main__":
    main()