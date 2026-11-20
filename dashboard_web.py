import os
import io
import csv
import sys
import json
import threading
import webbrowser
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core_ia import C, cargar_config, guardar_config, preparar_db
from modulo_a_radar_whop.motor_zerotouch_v4 import ejecutar_ciclo
from modulo_b_ejecutor.copiloto import descargar_post_reddit, cargar_desde_crm, analizar_oferta_completo
from modulo_c_whop.empaquetador import crear_factura_html
from modulo_d_marketing.iman_clientes import responder_objecion_ia

SCAN_LOCK = threading.Lock()
SCAN_STATE = {"running": False, "last_result": None}

HTML_DASHBOARD = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ZeroTouch PRIME v10.0 — Command Center</title>
<style>
  :root { --bg:#070b14; --card:#0f172a; --card2:#162033; --border:#1e293b; --text:#f1f5f9; --muted:#94a3b8; --accent:#38bdf8; --green:#4ade80; --amber:#fbbf24; --red:#f87171; --purple:#c084fc; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:'Segoe UI',system-ui,sans-serif; background:var(--bg); color:var(--text); }
  .shell { max-width:1380px; margin:0 auto; padding:22px; }
  header { display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:14px; margin-bottom:18px; }
  h1 { margin:0; font-size:22px; }
  h1 span { color:var(--accent); }
  .tabs { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:20px; border-bottom:1px solid var(--border); padding-bottom:12px; }
  .tab { background:transparent; color:var(--muted); border:1px solid var(--border); padding:9px 16px; border-radius:9px; cursor:pointer; font-size:13px; font-weight:600; transition:.15s; }
  .tab:hover { color:var(--text); border-color:var(--accent); }
  .tab.active { background:linear-gradient(135deg,#0284c7,#2563eb); color:#fff; border-color:transparent; }
  .view { display:none; }
  .view.active { display:block; }
  .actions { display:flex; gap:9px; flex-wrap:wrap; }
  button, a.btn { background:#1e293b; color:var(--text); border:1px solid #334155; padding:8px 14px; border-radius:8px; cursor:pointer; font-size:13px; font-weight:600; text-decoration:none; transition:.15s; }
  button:hover, a.btn:hover { background:#334155; border-color:var(--accent); }
  button.primary { background:linear-gradient(135deg,#0284c7,#2563eb); border:none; color:#fff; }
  button.success { background:#065f46; border-color:#10b981; color:#ecfdf5; }
  button.purple { background:#581c87; border-color:#a855f7; color:#faf5ff; }
  .kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:13px; margin-bottom:18px; }
  .kpi { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:16px 18px; }
  .kpi .lbl { font-size:11px; text-transform:uppercase; color:var(--muted); letter-spacing:.06em; }
  .kpi .num { font-size:26px; font-weight:800; margin-top:6px; }
  .green { color:var(--green); } .cyan { color:var(--accent); } .amber { color:var(--amber); } .purple { color:var(--purple); }
  .toolbar { display:flex; gap:10px; flex-wrap:wrap; margin-bottom:14px; align-items:center; }
  input, select, textarea { background:#090f1d; color:var(--text); border:1px solid #334155; padding:9px 11px; border-radius:8px; font-size:13px; font-family:inherit; }
  textarea { width:100%; min-height:95px; resize:vertical; }
  .table-box { background:var(--card); border:1px solid var(--border); border-radius:12px; overflow:auto; }
  table { width:100%; border-collapse:collapse; min-width:1040px; }
  th, td { padding:11px 13px; border-bottom:1px solid var(--border); text-align:left; font-size:13px; vertical-align:middle; }
  th { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.06em; background:#0b1220; }
  tr:hover { background:#131d31; }
  .score { display:inline-block; padding:3px 8px; border-radius:6px; font-weight:700; font-size:12px; }
  .s-hi { background:#14532d; color:#86efac; } .s-mid { background:#1e3a8a; color:#93c5fd; }
  .pill { display:inline-block; font-size:11px; padding:2px 7px; border-radius:999px; background:#3b0764; color:#e9d5ff; margin-left:6px; font-weight:700; }
  a.title-link { color:#e2e8f0; text-decoration:none; font-weight:600; }
  a.title-link:hover { color:var(--accent); text-decoration:underline; }
  .meta { font-size:11px; color:var(--muted); margin-top:3px; }
  .usd-in { width:76px; }
  .grid-2 { display:grid; grid-template-columns:repeat(auto-fit,minmax(420px,1fr)); gap:16px; }
  .panel-card { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px; }
  .panel-card h3 { margin:0 0 12px 0; font-size:15px; color:var(--accent); }
  .bar-row { margin-bottom:10px; }
  .bar-lbl { display:flex; justify-content:space-between; font-size:12px; margin-bottom:4px; }
  .bar-track { height:9px; background:#1e293b; border-radius:999px; overflow:hidden; }
  .bar-fill { height:100%; background:linear-gradient(90deg,#0284c7,#38bdf8); border-radius:999px; }
  .bar-fill.g { background:linear-gradient(90deg,#16a34a,#4ade80); }
  .prebox { background:#070b14; border:1px solid #334155; border-radius:8px; padding:12px; white-space:pre-wrap; font-size:12.5px; line-height:1.5; max-height:260px; overflow:auto; }
  .field { margin-bottom:12px; }
  .field label { display:block; font-size:12px; color:var(--muted); margin-bottom:5px; }
  .field input, .field select { width:100%; }
  .modal-bg { position:fixed; inset:0; background:rgba(0,0,0,.72); display:none; align-items:center; justify-content:center; padding:20px; z-index:99; }
  .modal-bg.open { display:flex; }
  .modal { background:var(--card); border:1px solid #334155; border-radius:14px; max-width:820px; width:100%; max-height:88vh; overflow:auto; padding:24px; }
  .status-bar { font-size:12px; color:var(--amber); margin-left:auto; }
</style>
</head>
<body>
<div class="shell">
  <header>
    <div>
      <h1>⚡ ZeroTouch <span>PRIME v10.0</span> — Freelance OS</h1>
      <div class="meta">Radar 16 Fuentes • CRM + Analytics • Laboratorio IA • Facturas PDF • Config</div>
    </div>
    <div class="actions">
      <button class="primary" onclick="lanzarEscaneo()">🚀 Escanear 16 Fuentes</button>
      <button onclick="cargarDatos()">🔄 Refrescar</button>
      <a class="btn" href="/api/export">📥 Excel (.CSV)</a>
    </div>
  </header>

  <div class="tabs">
    <button class="tab active" onclick="verTab('t_crm', this)">📡 Radar & CRM</button>
    <button class="tab" onclick="verTab('t_stats', this)">📊 Analytics</button>
    <button class="tab" onclick="verTab('t_ai', this)">🧠 Laboratorio IA</button>
    <button class="tab" onclick="verTab('t_inv', this)">📄 Facturas + Contrato</button>
    <button class="tab" onclick="verTab('t_cfg', this)">⚙️ Configuracion</button>
  </div>

  <!-- TAB 1: CRM -->
  <section id="t_crm" class="view active">
    <div class="kpis">
      <div class="kpi"><div class="lbl">Facturado Total</div><div class="num green" id="kUsd">$0.00</div></div>
      <div class="kpi"><div class="lbl">Leads Capturados</div><div class="num cyan" id="kLeads">0</div></div>
      <div class="kpi"><div class="lbl">Clientes Ganados</div><div class="num green" id="kGanados">0</div></div>
      <div class="kpi"><div class="lbl">Basura 0-Tokens</div><div class="num amber" id="kAhorro">0</div></div>
      <div class="kpi"><div class="lbl">Tokens Ahorrados</div><div class="num purple" id="kTok">0</div></div>
    </div>

    <div class="toolbar">
      <input type="text" id="qSearch" placeholder="Buscar titulo, subreddit o categoria..." oninput="renderTabla()" style="min-width:250px;">
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
          <tr><th>ID</th><th>Score</th><th>Fuente</th><th>Proyecto, Competencia & Cliente</th><th>Presupuesto</th><th>Estado</th><th>USD</th><th>Acciones</th></tr>
        </thead>
        <tbody id="tbodyLeads"></tbody>
      </table>
    </div>
  </section>

  <!-- TAB 2: ANALYTICS -->
  <section id="t_stats" class="view">
    <div class="grid-2">
      <div class="panel-card"><h3>📍 Top Fuentes (Leads Detectados)</h3><div id="chFuentes"></div></div>
      <div class="panel-card"><h3>🎯 Embudo de Conversion CRM</h3><div id="chEmbudo"></div></div>
      <div class="panel-card"><h3>💵 Ingresos por Categoria (USD)</h3><div id="chCat"></div></div>
      <div class="panel-card"><h3>⚡ Eficiencia de Tokens IA</h3><div id="chTokens"></div></div>
    </div>
  </section>

  <!-- TAB 3: LABORATORIO IA -->
  <section id="t_ai" class="view">
    <div class="grid-2">
      <div class="panel-card">
        <h3>🤖 Copiloto Express (Link Reddit, #ID o Texto)</h3>
        <div class="field"><textarea id="aiOferta" placeholder="Pega aqui un link de Reddit, escribe #4, o pega la descripcion del cliente..."></textarea></div>
        <button class="primary" onclick="correrCopilotoWeb()">Generar Pitch A/B + Precios + Codigo</button>
        <div id="aiResCopiloto" style="margin-top:14px;"></div>
      </div>
      <div class="panel-card">
        <h3>⚔️ Negociador Mata-Objeciones</h3>
        <div class="field"><label>Contexto y precio pedido</label><input id="negCtx" placeholder="Ej. Scraper Shopify, pedi $120 USD"></div>
        <div class="field"><label>Que te respondio el cliente?</label><textarea id="negMsg" placeholder="Ej. Can you do it for $40 or build a free sample first?"></textarea></div>
        <button class="purple" onclick="correrNegociadorWeb()">Generar Contraofertas</button>
        <div id="aiResNeg" style="margin-top:14px;"></div>
      </div>
    </div>
  </section>

  <!-- TAB 4: FACTURAS -->
  <section id="t_inv" class="view">
    <div class="panel-card" style="max-width:640px;">
      <h3>📄 Generador Instantaneo de Factura + Micro-Contrato PDF</h3>
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
    </div>
  </section>

  <!-- TAB 5: CONFIG -->
  <section id="t_cfg" class="view">
    <div class="panel-card" style="max-width:700px;">
      <h3>⚙️ Configuracion Global (config.json)</h3>
      <div class="field"><label>Marca / Nombre Freelance</label><input id="cMarca"></div>
      <div class="field"><label>Especialidad Tecnica</label><input id="cEsp"></div>
      <div class="field"><label>Metodos de Pago (Pitches)</label><input id="cPagos"></div>
      <div class="field"><label>Detalle de Pago (Facturas)</label><input id="cPagosFac"></div>
      <div class="field"><label>GitHub URL</label><input id="cGh"></div>
      <div class="field"><label>Whop URL</label><input id="cWhop"></div>
      <div class="grid-2" style="grid-template-columns:1fr 1fr 1fr;">
        <div class="field"><label>Tarifa/Hora USD</label><input id="cTarifa" type="number"></div>
        <div class="field"><label>Score Minimo</label><input id="cScore" type="number"></div>
        <div class="field"><label>Sniper (seg)</label><input id="cSniper" type="number"></div>
      </div>
      <div class="field"><label>Telegram Admin ID (para control remoto DM)</label><input id="cAdmin" placeholder="Opcional: tu ID numerico personal de Telegram"></div>
      <button class="primary" onclick="guardarConfigWeb()">💾 Guardar Configuracion</button>
      <span id="cfgMsg" style="margin-left:12px;font-size:13px;color:var(--green);"></span>
    </div>
  </section>
</div>

<!-- MODAL COPILOTO -->
<div class="modal-bg" id="modalBg" onclick="if(event.target===this)cerrarModal()">
  <div class="modal">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
      <h3 style="margin:0;color:var(--accent);" id="modalTitle">🤖 Copiloto PRIME</h3>
      <button onclick="cerrarModal()">Cerrar</button>
    </div>
    <div id="modalBody">Cargando...</div>
  </div>
</div>

<script>
let DATA = { leads:[], kpis:{}, analytics:{}, scan:{} };
function esc(s){ return String(s||'').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }
function verTab(id, btn){
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
  if(id === 't_cfg') cargarConfigWeb();
}
function copiarTxt(txt, btn){
  navigator.clipboard.writeText(txt);
  const old = btn.textContent; btn.textContent = '✅ Copiado!';
  setTimeout(()=> btn.textContent = old, 1400);
}
function cerrarModal(){ document.getElementById('modalBg').classList.remove('open'); }

async function cargarDatos(){
  const r = await fetch('/api/data');
  DATA = await r.json();
  document.getElementById('kUsd').textContent = '$' + Number(DATA.kpis.usd || 0).toFixed(2);
  document.getElementById('kLeads').textContent = DATA.kpis.leads;
  document.getElementById('kGanados').textContent = DATA.kpis.ganados;
  document.getElementById('kAhorro').textContent = DATA.kpis.descartados;
  document.getElementById('kTok').textContent = Number(DATA.kpis.tok_ahorrados || 0).toLocaleString();
  const st = document.getElementById('scanStatus');
  if(DATA.scan.running){ st.textContent = '⏳ Escaneando 16 fuentes en segundo plano...'; }
  else if(DATA.scan.last_result){ const lr = DATA.scan.last_result; st.textContent = `✅ Ultimo barrido: ${lr.alertas} alertas | ${lr.descartados} filtrados 0-tokens (${lr.segundos}s)`; }
  renderTabla();
  renderAnalytics();
}

function renderTabla(){
  const q = document.getElementById('qSearch').value.toLowerCase();
  const est = document.getElementById('qEstado').value;
  const minS = parseInt(document.getElementById('qMinScore').value || '0', 10);
  const filtrados = (DATA.leads || []).filter(l => l.score >= minS && (!est || l.estado === est) && (!q || (l.titulo+' '+l.fuente+' '+l.categoria).toLowerCase().includes(q)));
  const tb = document.getElementById('tbodyLeads');
  if(!filtrados.length){ tb.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#94a3b8;padding:28px;">Sin leads para este filtro. Haz clic en "Escanear 16 Fuentes".</td></tr>'; return; }
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
      <td style="white-space:nowrap;">
        <button class="success" onclick="guardarLead(${l.id})">Guardar</button>
        <button class="purple" onclick="abrirCopilotoLead(${l.id})">🤖 IA</button>
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
  const us = DATA.kpis.tok_usados || 0;
  const ah = DATA.kpis.tok_ahorrados || 0;
  const pct = (us + ah) > 0 ? Math.round((ah / (us + ah)) * 100) : 0;
  document.getElementById('chTokens').innerHTML = `
    <div class="bar-row"><div class="bar-lbl"><span>Tokens Ahorrados (Pre-filtro + Jaccard)</span><b>${ah.toLocaleString()} (${pct}%)</b></div>
    <div class="bar-track"><div class="bar-fill g" style="width:${pct}%"></div></div></div>
    <div class="bar-row"><div class="bar-lbl"><span>Tokens Usados en Analisis IA</span><b>${us.toLocaleString()}</b></div>
    <div class="bar-track"><div class="bar-fill" style="width:${100-pct}%"></div></div></div>
  `;
}

async function guardarLead(id){
  const estado = document.getElementById('est_'+id).value;
  const usd = parseFloat(document.getElementById('usd_'+id).value || 0);
  await fetch('/api/update', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id, estado, usd}) });
  await cargarDatos();
}

async function lanzarEscaneo(){
  document.getElementById('scanStatus').textContent = '⏳ Iniciando escaneo PRIME...';
  await fetch('/api/scan', { method:'POST' });
  setTimeout(cargarDatos, 2000);
}

function renderBloqueCopiloto(res){
  if(!res || res.error) return `<div style="color:var(--red);">Error: ${esc(res ? res.error : 'Sin respuesta')}</div>`;
  const pa = JSON.stringify(res.pitch_a || '');
  const pb = JSON.stringify(res.pitch_b || '');
  const mc = JSON.stringify(res.micro_contrato || '');
  return `
    ${res.confianza ? `<div class="meta" style="margin-bottom:8px;color:var(--purple);font-weight:700;">${esc(res.confianza)}</div>` : ''}
    <div class="field"><label>Diagnostico</label><div class="prebox">${esc(res.diagnostico)}</div></div>
    <div class="field"><label>Precios Sugeridos</label><div class="prebox">${esc(res.precios)}</div></div>
    <div class="field"><label>Pitch A (Tecnico) <button style="padding:3px 8px;font-size:11px;margin-left:6px;" onclick='copiarTxt(${pa}, this)'>Copiar</button> ${res.dm_url ? `<a class="btn" style="padding:3px 8px;font-size:11px;margin-left:4px;" href="${esc(res.dm_url)}" target="_blank">⚡ DM Reddit</a>` : ''}</label><div class="prebox">${esc(res.pitch_a)}</div></div>
    <div class="field"><label>Pitch B (Consultivo) <button style="padding:3px 8px;font-size:11px;margin-left:6px;" onclick='copiarTxt(${pb}, this)'>Copiar</button></label><div class="prebox">${esc(res.pitch_b)}</div></div>
    <div class="field"><label>Micro-Contrato <button style="padding:3px 8px;font-size:11px;margin-left:6px;" onclick='copiarTxt(${mc}, this)'>Copiar</button></label><div class="prebox">${esc(res.micro_contrato)}</div></div>
    <div class="meta">✅ Script base guardado y verificado con AST en modulo_b_ejecutor/borrador_cliente.py</div>
  `;
}

async function abrirCopilotoLead(id){
  document.getElementById('modalTitle').textContent = '🤖 Copiloto PRIME — Lead #' + id;
  document.getElementById('modalBody').innerHTML = '⏳ Analizando post y generando Pitch A/B + Codigo Python...';
  document.getElementById('modalBg').classList.add('open');
  const r = await fetch('/api/copiloto', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({entrada: '#' + id}) });
  document.getElementById('modalBody').innerHTML = renderBloqueCopiloto(await r.json());
}

async function correrCopilotoWeb(){
  const entrada = document.getElementById('aiOferta').value.trim();
  if(!entrada) return;
  document.getElementById('aiResCopiloto').innerHTML = '⏳ Generando estrategia, pitches y script...';
  const r = await fetch('/api/copiloto', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({entrada}) });
  document.getElementById('aiResCopiloto').innerHTML = renderBloqueCopiloto(await r.json());
}

async function correrNegociadorWeb(){
  const ctx = document.getElementById('negCtx').value.trim();
  const msg = document.getElementById('negMsg').value.trim();
  if(!msg) return;
  document.getElementById('aiResNeg').innerHTML = '⏳ Calculando contraofertas...';
  const r = await fetch('/api/negociar', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ctx, msg}) });
  const d = await r.json();
  if(d.error){ document.getElementById('aiResNeg').innerHTML = esc(d.error); return; }
  const f = JSON.stringify(d.firme || '');
  const fl = JSON.stringify(d.flexible || '');
  document.getElementById('aiResNeg').innerHTML = `
    <div class="field"><label>Lectura Tactica</label><div class="prebox">${esc(d.consejo)}</div></div>
    <div class="field"><label>Respuesta Firme <button style="padding:3px 8px;font-size:11px;margin-left:6px;" onclick='copiarTxt(${f}, this)'>Copiar</button></label><div class="prebox">${esc(d.firme)}</div></div>
    <div class="field"><label>Respuesta Flexible <button style="padding:3px 8px;font-size:11px;margin-left:6px;" onclick='copiarTxt(${fl}, this)'>Copiar</button></label><div class="prebox">${esc(d.flexible)}</div></div>
  `;
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
  document.getElementById('cfgMsg').textContent = '✅ Guardado!';
  setTimeout(()=> document.getElementById('cfgMsg').textContent = '', 2000);
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
        elif self.path == "/api/data":
            conn = preparar_db()
            try:
                rows = conn.execute(
                    "SELECT id, fecha, fuente, autor, titulo, categoria, presupuesto, score, competencia, confianza, prioridad_tag, link, estado, ganancia_usd FROM leads ORDER BY id DESC LIMIT 150"
                ).fetchall()
                leads = [
                    {
                        "id": r[0], "fecha": r[1], "fuente": r[2], "autor": r[3], "titulo": r[4],
                        "categoria": r[5], "presupuesto": r[6], "score": r[7], "competencia": r[8],
                        "confianza": r[9], "prioridad_tag": r[10], "link": r[11], "estado": r[12], "ganancia_usd": r[13],
                    }
                    for r in rows
                ]
                usd = conn.execute("SELECT COALESCE(SUM(ganancia_usd), 0) FROM leads WHERE estado = 'ganado'").fetchone()[0]
                ganados = conn.execute("SELECT COUNT(*) FROM leads WHERE estado = 'ganado'").fetchone()[0]
                st_row = conn.execute("SELECT COALESCE(SUM(descartados_local), 0), COALESCE(SUM(tokens_est_usados), 0), COALESCE(SUM(tokens_est_ahorrados), 0) FROM stats_diarias").fetchone()
                por_fuente = conn.execute("SELECT fuente, COUNT(*) FROM leads GROUP BY fuente ORDER BY COUNT(*) DESC LIMIT 7").fetchall()
                embudo = conn.execute("SELECT estado, COUNT(*) FROM leads GROUP BY estado ORDER BY COUNT(*) DESC").fetchall()
                usd_cat = conn.execute("SELECT categoria, ROUND(SUM(ganancia_usd), 2) FROM leads WHERE estado = 'ganado' GROUP BY categoria ORDER BY SUM(ganancia_usd) DESC LIMIT 6").fetchall()
                payload = {
                    "leads": leads,
                    "kpis": {"usd": usd, "leads": len(leads), "ganados": ganados, "descartados": st_row[0], "tok_usados": st_row[1], "tok_ahorrados": st_row[2]},
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
                    "SELECT id, fecha, fuente, autor, titulo, categoria, presupuesto, score, competencia, confianza, prioridad_tag, estado, ganancia_usd, link FROM leads ORDER BY id DESC"
                ).fetchall()
                buf = io.StringIO()
                w = csv.writer(buf)
                w.writerow(["ID", "Fecha", "Fuente", "Autor", "Titulo", "Categoria", "Presupuesto", "Score", "Competencia", "Confianza", "Tag", "Estado", "Ganancia_USD", "Link"])
                w.writerows(rows)
                data = ("\ufeff" + buf.getvalue()).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="crm_prime_{datetime.now().strftime("%Y%m%d")}.csv"')
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
                    "UPDATE leads SET estado = ?, ganancia_usd = ? WHERE id = ?",
                    (str(data.get("estado", "nuevo")), float(data.get("usd", 0)), int(data.get("id"))),
                )
                conn.commit()
            finally:
                conn.close()
            self._send(200, "application/json", b'{"ok": true}')
        elif self.path == "/api/scan":
            threading.Thread(target=correr_scan_bg, daemon=True).start()
            self._send(200, "application/json", b'{"started": true}')
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

def main() -> None:
    puerto = 8765
    server = ThreadingHTTPServer(("127.0.0.1", puerto), Handler)
    url = f"http://127.0.0.1:{puerto}"
    print(f"\n{C.BOLD}{C.GREEN}=== ZEROTOUCH PRIME v10.0 WEB OS: {url} ==={C.RESET}")
    print(f"{C.DIM}Presiona Ctrl+C aqui cuando quieras cerrar el servidor.{C.RESET}\n")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\n{C.YELLOW}[*] Servidor web cerrado.{C.RESET}\n")
    finally:
        server.server_close()

if __name__ == "__main__":
    main()