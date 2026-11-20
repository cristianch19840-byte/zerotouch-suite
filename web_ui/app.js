// ==================== ZERO-TOUCH UI v14.0 — APP CORE, CTRL+K & POLLING ====================
let DATA = {
  leads: [], kpis: {}, analytics: {}, scan: {}, logs: [],
  salud: [], catalogo: [], fuentes_activas: {}, feeds_rss_custom: [], solo_freelance_corto: false,
};
window.CFG_ACTUAL = { tarifa_hora_usd: 25, trm_cop: 4200 };

const CLIP_STORE = {};
let CLIP_SEQ = 0;
let CMD_INDEX = 0;
let CMD_ITEMS = [];

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, m => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[m]));
}

function toast(msg, tipo = '') {
  const stack = document.getElementById('toastStack');
  if (!stack) return;
  const item = document.createElement('div');
  item.className = 'toast-item ' + (tipo || '');
  item.textContent = msg;
  stack.appendChild(item);
  setTimeout(() => {
    item.style.opacity = '0';
    item.style.transform = 'translateY(8px)';
    item.style.transition = '0.18s ease';
    setTimeout(() => item.remove(), 200);
  }, 2700);
}

function regClip(txt) {
  const id = 'c' + (++CLIP_SEQ);
  CLIP_STORE[id] = String(txt || '');
  return id;
}

function copyId(id) {
  const val = CLIP_STORE[id] || '';
  if (!val) return toast('Nada para copiar', 'err');
  navigator.clipboard.writeText(val);
  toast('Copiado al portapapeles', 'ok');
}

async function apiJson(url, opts = {}) {
  try {
    const r = await fetch(url, opts);
    const txt = await r.text();
    try { return JSON.parse(txt); }
    catch { return { error: `Respuesta invalida del servidor (HTTP ${r.status})` }; }
  } catch (e) {
    return { error: 'Error de red: ' + e.message };
  }
}

// ==================== LAYOUT, TEMAS & NAVEGACION ====================
function setTheme(theme) {
  const valido = ['cyan', 'violet', 'emerald', 'amber'].includes(theme) ? theme : 'cyan';
  document.documentElement.setAttribute('data-theme', valido);
  localStorage.setItem('zt_theme', valido);
  document.querySelectorAll('.theme-dot').forEach(b => b.classList.toggle('active', b.dataset.t === valido));
}

function toggleSidebar() {
  const sh = document.getElementById('appShell');
  if (!sh) return;
  const col = sh.classList.toggle('collapsed');
  localStorage.setItem('zt_side_collapsed', col ? '1' : '0');
  const btn = document.getElementById('btnCollapse');
  if (btn) btn.style.transform = col ? 'rotate(180deg)' : '';
}

function verTab(id, title, btn) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
  const target = document.getElementById(id);
  if (target) target.classList.add('active');
  const titleEl = document.getElementById('pageTitle');
  if (titleEl) titleEl.textContent = title;
  if (btn) btn.classList.add('active');

  if (id === 't_cfg') cargarConfigWeb();
  if (id === 't_plat') renderPlataformas();
  if (id === 't_stats') renderAnalytics();
  if (id === 't_aegis' && typeof cargarAegisLab === 'function') cargarAegisLab();
  if (id === 't_whop') { calcularPrecio(); cargarScriptsLista(); }
  if (id === 't_code') cargarScriptsLista();
}

// ==================== CARGA DE DATOS, SCAN & SNIPER ====================
function actualizarEstadoVivo() {
  const pill = document.getElementById('livePill');
  const pillTxt = document.getElementById('livePillText');
  const btnSnip = document.getElementById('btnSniper');
  const txtSnip = document.getElementById('sniperTxt');

  const scan = DATA.scan || {};
  if (btnSnip && txtSnip) {
    if (scan.sniper_on) {
      btnSnip.className = 'btn btn-sniper-on';
      txtSnip.textContent = `Sniper: ON (#${scan.sniper_ciclos || 0})`;
    } else {
      btnSnip.className = 'btn';
      txtSnip.textContent = 'Sniper: OFF';
    }
  }

  if (pill && pillTxt) {
    if (scan.running) {
      pill.classList.add('scanning');
      pillTxt.textContent = 'Escaneando 12+ fuentes...';
    } else if (scan.sniper_on) {
      pill.classList.remove('scanning');
      pillTxt.textContent = 'Sniper activo';
    } else {
      pill.classList.remove('scanning');
      pillTxt.textContent = 'En linea';
    }
  }
}

async function cargarDatos(forzarTabla = false) {
  const d = await apiJson('/api/data');
  if (d.error) return;
  DATA = d;

  renderKpis();
  actualizarEstadoVivo();
  poblarFiltroPlataformas();
  renderPlataformas();
  renderAnalytics();
  renderLiveLogs(DATA.logs || []);

  const editandoTabla = document.activeElement && document.activeElement.closest('#tbodyLeads');
  if (forzarTabla) DIRTY_LEADS.clear();
  if (forzarTabla || CRM_VIEW === 'kanban' || (!editandoTabla && DIRTY_LEADS.size === 0)) {
    renderCrmActual();
  } else {
    actualizarBannerCrm();
  }
}

async function lanzarEscaneo() {
  if (!DATA.scan) DATA.scan = {};
  DATA.scan.running = true;
  actualizarEstadoVivo();
  actualizarBannerCrm();
  toast('Escaneo OMNI-GRID iniciado en segundo plano', 'ok');
  await apiJson('/api/scan', { method: 'POST' });
  setTimeout(() => cargarDatos(false), 1800);
}

async function toggleSniper() {
  const d = await apiJson('/api/sniper_toggle', { method: 'POST' });
  if (d.error) return toast(d.error, 'err');
  toast(d.sniper_on ? 'Auto-Sniper ACTIVADO en segundo plano' : 'Auto-Sniper detenido', d.sniper_on ? 'ok' : '');
  await cargarDatos(false);
}

// ==================== CONFIGURACION ====================
async function cargarConfigWeb() {
  const c = await apiJson('/api/config');
  if (c.error) return;
  window.CFG_ACTUAL = c;

  const setV = (id, v) => { const e = document.getElementById(id); if (e) e.value = v; };
  setV('cMarca', c.nombre_marca || '');
  setV('cEsp', c.especialidad || '');
  setV('cPagos', c.metodos_pago || '');
  setV('cPagosFac', c.detalle_pago_factura || '');
  setV('cGh', c.github_url || '');
  setV('cWhop', c.whop_url || '');
  setV('cTarifa', c.tarifa_hora_usd || 25);
  setV('cTrm', c.trm_cop || 4200);
  setV('cScore', c.score_minimo || 6);
  setV('cSniper', c.intervalo_sniper_seg || 75);
  setV('cMaxHrs', c.max_horas_post || 18);
  setV('cBatch', c.batch_ia_tamano || 5);
  setV('cMaxIa', c.max_ia_por_ciclo || 20);
  const bl = Array.isArray(c.palabras_extra_blacklist) ? c.palabras_extra_blacklist.join(', ') : (c.palabras_extra_blacklist || '');
  setV('cBlack', bl);
  setV('cAdmin', c.telegram_admin_id || '');

  setV('calcRate', c.tarifa_hora_usd || 25);
  setV('calcTrm', c.trm_cop || 4200);
  calcularPrecio();
  renderKpis();
}

async function guardarConfigWeb() {
  const getV = id => (document.getElementById(id)?.value || '');
  const listaBl = getV('cBlack').split(',').map(s => s.trim()).filter(Boolean);
  const payload = {
    nombre_marca: getV('cMarca'),
    especialidad: getV('cEsp'),
    metodos_pago: getV('cPagos'),
    detalle_pago_factura: getV('cPagosFac'),
    github_url: getV('cGh'),
    whop_url: getV('cWhop'),
    tarifa_hora_usd: parseInt(getV('cTarifa') || '25', 10),
    trm_cop: parseInt(getV('cTrm') || '4200', 10),
    score_minimo: Math.max(1, Math.min(10, parseInt(getV('cScore') || '6', 10))),
    intervalo_sniper_seg: Math.max(45, parseInt(getV('cSniper') || '75', 10)),
    max_horas_post: Math.max(1, parseInt(getV('cMaxHrs') || '18', 10)),
    batch_ia_tamano: Math.max(1, Math.min(8, parseInt(getV('cBatch') || '5', 10))),
    max_ia_por_ciclo: Math.max(1, Math.min(50, parseInt(getV('cMaxIa') || '20', 10))),
    palabras_extra_blacklist: listaBl,
    telegram_admin_id: getV('cAdmin').trim(),
  };
  const d = await apiJson('/api/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (d.error) return toast(d.error, 'err');
  window.CFG_ACTUAL = Object.assign({}, window.CFG_ACTUAL, payload);
  document.getElementById('calcRate').value = payload.tarifa_hora_usd;
  document.getElementById('calcTrm').value = payload.trm_cop;
  calcularPrecio();
  renderKpis();
  toast('Configuracion guardada en config.json', 'ok');
}

// ==================== COMMAND PALETTE (CTRL+K) ====================
function obtenerAccionesCmd() {
  const base = [
    { label: 'Escanear 12+ plataformas ahora', hint: 'Accion', run: () => lanzarEscaneo() },
    { label: 'Activar / Detener Auto-Sniper', hint: 'Accion', run: () => toggleSniper() },
    { label: 'Cambiar CRM a Tablero Kanban', hint: 'Vista', run: () => { verTab('t_crm', 'Radar & CRM', document.getElementById('nav_crm')); setCrmView('kanban'); } },
    { label: 'Cambiar CRM a Tabla Compacta', hint: 'Vista', run: () => { verTab('t_crm', 'Radar & CRM', document.getElementById('nav_crm')); setCrmView('table'); } },
    { label: 'Abrir AEGIS-X Lab (Simulador Forense & ML)', hint: 'AEGIS-X', run: () => verTab('t_aegis', 'AEGIS-X Lab ? Motor Forense', document.getElementById('nav_aegis')) },
    { label: 'Ir a Plataformas & RSS', hint: 'Navegacion', run: () => verTab('t_plat', 'Plataformas & RSS', document.getElementById('nav_plat')) },
    { label: 'Ir a Analytics & Graficos SVG', hint: 'Navegacion', run: () => verTab('t_stats', 'Analytics & Pipeline', document.getElementById('nav_stats')) },
    { label: 'Ir a Copiloto Universal & Negociador', hint: 'Estudio IA', run: () => verTab('t_ai', 'Copiloto & Negociador', document.getElementById('nav_ai')) },
    { label: 'Ir a Refinador de Codigo IDE', hint: 'Estudio IA', run: () => verTab('t_code', 'Refinador de Codigo IDE', document.getElementById('nav_code')) },
    { label: 'Ir a Marketing & Follow-Up', hint: 'Facturacion', run: () => verTab('t_mkt', 'Marketing & Follow-Up', document.getElementById('nav_mkt')) },
    { label: 'Ir a Calculadora USD->COP, Facturas & Whop', hint: 'Facturacion', run: () => verTab('t_whop', 'Calculadora, Facturas & Whop', document.getElementById('nav_whop')) },
    { label: 'Ir a Ajustes, Salud & Terminal', hint: 'Sistema', run: () => verTab('t_cfg', 'Ajustes & Terminal', document.getElementById('nav_cfg')) },
    { label: 'Crear Backup de Base de Datos SQLite', hint: 'Sistema', run: () => hacerBackupWeb() },
  ];

  const leadsCmd = (DATA.leads || []).slice(0, 25).map(l => ({
    label: `#${l.id} [${l.fuente}] ${l.titulo.slice(0, 62)}`,
    hint: `IA • ${l.score}/10`,
    run: () => abrirCopilotoLead(l.id),
  }));
  return base.concat(leadsCmd);
}

function abrirCmdPalette() {
  const bg = document.getElementById('cmdBg');
  const inp = document.getElementById('cmdInput');
  if (!bg || !inp) return;
  bg.classList.add('open');
  inp.value = '';
  CMD_INDEX = 0;
  renderCmdList();
  setTimeout(() => inp.focus(), 20);
}

function cerrarCmdPalette() {
  const bg = document.getElementById('cmdBg');
  if (bg) bg.classList.remove('open');
}

function renderCmdList() {
  const q = (document.getElementById('cmdInput')?.value || '').trim().toLowerCase();
  const list = document.getElementById('cmdList');
  if (!list) return;
  CMD_ITEMS = obtenerAccionesCmd().filter(it => !q || (it.label + ' ' + it.hint).toLowerCase().includes(q)).slice(0, 12);
  if (CMD_INDEX >= CMD_ITEMS.length) CMD_INDEX = 0;

  if (!CMD_ITEMS.length) {
    list.innerHTML = '<div class="muted" style="padding:18px;text-align:center;">Sin coincidencias</div>';
    return;
  }
  list.innerHTML = CMD_ITEMS.map((it, i) => `
    <button class="cmd-item ${i === CMD_INDEX ? 'selected' : ''}" onclick="ejecutarCmd(${i})">
      <span>${esc(it.label)}</span>
      <span class="kbd">${esc(it.hint)}</span>
    </button>
  `).join('');
}

function ejecutarCmd(idx) {
  const item = CMD_ITEMS[idx];
  cerrarCmdPalette();
  if (item && typeof item.run === 'function') item.run();
}

// ==================== ATAJOS DE TECLADO ====================
document.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault();
    const bg = document.getElementById('cmdBg');
    if (bg && bg.classList.contains('open')) cerrarCmdPalette();
    else abrirCmdPalette();
    return;
  }

  const cmdOpen = document.getElementById('cmdBg')?.classList.contains('open');
  if (cmdOpen) {
    if (e.key === 'Escape') { cerrarCmdPalette(); return; }
    if (e.key === 'ArrowDown') { e.preventDefault(); CMD_INDEX = (CMD_INDEX + 1) % Math.max(1, CMD_ITEMS.length); renderCmdList(); return; }
    if (e.key === 'ArrowUp') { e.preventDefault(); CMD_INDEX = (CMD_INDEX - 1 + Math.max(1, CMD_ITEMS.length)) % Math.max(1, CMD_ITEMS.length); renderCmdList(); return; }
    if (e.key === 'Enter') { e.preventDefault(); ejecutarCmd(CMD_INDEX); return; }
  }

  if (e.key === 'Escape') {
    cerrarDrawer();
    return;
  }

  const tag = (document.activeElement?.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
  if (e.key.toLowerCase() === 'r' && !e.ctrlKey && !e.metaKey) {
    cargarDatos(true);
    toast('Datos actualizados', 'ok');
  }
});

// ==================== ARRANQUE ====================
(function initApp() {
  setTheme(localStorage.getItem('zt_theme') || 'cyan');
  if (localStorage.getItem('zt_side_collapsed') === '1') {
    document.getElementById('appShell')?.classList.add('collapsed');
    const btn = document.getElementById('btnCollapse');
    if (btn) btn.style.transform = 'rotate(180deg)';
  }
  setCrmView(CRM_VIEW);
  cargarConfigWeb();
  cargarDatos(true);

  setInterval(() => cargarDatos(false), 15000);
  setInterval(() => { if (DATA.scan && DATA.scan.running) cargarDatos(false); }, 3500);
})();