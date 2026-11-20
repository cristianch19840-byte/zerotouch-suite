// ==================== ZERO-TOUCH UI v14.0 — STUDIO IA, MINI-IDE, CALC & LOGS ====================
let CODIGO_ACTUAL = '';

const PY_TOKEN_RE = /(#.*$)|("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(@[A-Za-z_]\w*)|\b(def|class|import|from|as|return|yield|if|elif|else|for|while|try|except|finally|with|raise|pass|break|continue|and|or|not|in|is|lambda|async|await|True|False|None)\b|\b(\d+(?:\.\d+)?)\b/g;

function resaltarLineaPython(linea) {
  let out = '';
  let last = 0;
  PY_TOKEN_RE.lastIndex = 0;
  let m;
  while ((m = PY_TOKEN_RE.exec(linea)) !== null) {
    if (m.index > last) out += esc(linea.slice(last, m.index));
    const tok = m[0];
    let cls = '';
    if (m[1]) cls = 'tok-com';
    else if (m[2]) cls = 'tok-str';
    else if (m[3]) cls = 'tok-dec';
    else if (m[4]) cls = 'tok-kw';
    else if (m[5]) cls = 'tok-num';
    out += cls ? `<span class="${cls}">${esc(tok)}</span>` : esc(tok);
    last = m.index + tok.length;
  }
  if (last < linea.length) out += esc(linea.slice(last));
  return out || ' ';
}

function resaltarPythonHtml(codigo) {
  const lineas = String(codigo || '').replace(/\r\n/g, '\n').split('\n');
  return lineas.map((ln, idx) =>
    `<div class="code-line"><span class="line-num">${idx + 1}</span><span class="line-txt">${resaltarLineaPython(ln)}</span></div>`
  ).join('');
}

// ==================== COPILOTO & NEGOCIADOR ====================
async function correrCopilotoWeb(btn) {
  const entrada = (document.getElementById('aiOferta')?.value || '').trim();
  if (!entrada) return toast('Pega un link, #ID o texto de oferta primero', 'err');
  btn.disabled = true;
  document.getElementById('aiResCopiloto').innerHTML =
    '<div class="empty-state"><b>Analizando oportunidad...</b>Detectando plataforma, Red Flags, escalera de precios, Pitch A/B y script Python.</div>';
  const d = await apiJson('/api/copiloto', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ entrada }),
  });
  document.getElementById('aiResCopiloto').innerHTML = renderBloqueCopiloto(d);
  btn.disabled = false;
  if (!d.error) toast('Kit de cierre y script base listos', 'ok');
}

function setObjecion(txt) {
  const el = document.getElementById('negMsg');
  if (el) { el.value = txt; el.focus(); }
}

async function correrNegociadorWeb(btn) {
  const ctx = (document.getElementById('negCtx')?.value || '').trim();
  const msg = (document.getElementById('negMsg')?.value || '').trim();
  if (!msg) return toast('Escribe o elige la objecion del cliente', 'err');
  btn.disabled = true;
  document.getElementById('aiResNeg').innerHTML = '<div class="muted">Calculando contraofertas...</div>';
  const d = await apiJson('/api/negociar', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ctx, msg }),
  });
  btn.disabled = false;
  if (d.error) {
    document.getElementById('aiResNeg').innerHTML = `<div class="prebox c-red">${esc(d.error)}</div>`;
    return;
  }
  const idF = regClip(d.firme);
  const idFl = regClip(d.flexible);
  document.getElementById('aiResNeg').innerHTML = `
    ${d.red_flag ? `<div style="background:var(--amber-soft);border:1px solid rgba(251,191,36,0.3);border-radius:9px;padding:9px 12px;margin-bottom:10px;font-size:12px;"><b class="c-amber">Riesgo:</b> ${esc(d.red_flag)}</div>` : ''}
    <div class="field"><label>Lectura tactica</label><div class="prebox">${esc(d.consejo)}</div></div>
    <div class="field"><label><span>Respuesta Firme (defiende tu precio)</span><button class="btn btn-primary btn-xs" onclick="copyId('${idF}')">Copiar Firme</button></label><div class="prebox">${esc(d.firme)}</div></div>
    <div class="field"><label><span>Respuesta Flexible (ajusta alcance sin regalarte)</span><button class="btn btn-ghost btn-xs" onclick="copyId('${idFl}')">Copiar Flexible</button></label><div class="prebox">${esc(d.flexible)}</div></div>
  `;
}

// ==================== REFINADOR MINI-IDE ====================
function setInstruccionCode(txt) {
  const el = document.getElementById('codeInstr');
  if (el) { el.value = txt; el.focus(); }
}

async function cargarScriptsLista() {
  const d = await apiJson('/api/scripts');
  if (d.error) return;
  const scripts = d.scripts || [];
  const opts = scripts.length
    ? scripts.map(s => `<option value="${esc(s.ruta)}">${esc(s.label)}</option>`).join('')
    : '<option value="modulo_b_ejecutor/borrador_cliente.py">borrador_cliente.py (sin crear aun)</option>';
  const selCode = document.getElementById('codeSel');
  const selWhop = document.getElementById('whopSel');
  if (selCode) selCode.innerHTML = opts;
  if (selWhop) selWhop.innerHTML = opts;
  cargarCodigoScript();
}

async function cargarCodigoScript() {
  const sel = document.getElementById('codeSel');
  if (!sel) return;
  const ruta = sel.value;
  const d = await apiJson('/api/script_leer?ruta=' + encodeURIComponent(ruta));
  const view = document.getElementById('codeView');
  const meta = document.getElementById('codeMeta');
  const fname = document.getElementById('ideFilename');
  const badge = document.getElementById('ideBadge');

  if (d.error) {
    CODIGO_ACTUAL = '';
    if (fname) fname.textContent = ruta.split('/').pop() || 'script.py';
    if (badge) badge.innerHTML = '<span class="badge b-custom">Sin archivo</span>';
    if (view) view.innerHTML = `<div class="empty-state"><b>${esc(d.error)}</b>Genera primero un proyecto en el Copiloto IA.</div>`;
    if (meta) meta.textContent = '';
    return;
  }

  CODIGO_ACTUAL = d.codigo || '';
  if (fname) fname.textContent = d.ruta || ruta;
  if (badge) badge.innerHTML = d.ast_valido ? '<span class="badge b-remoto">AST VALIDO</span>' : '<span class="badge b-hot">ERROR SINTAXIS</span>';
  if (view) view.innerHTML = resaltarPythonHtml(CODIGO_ACTUAL);
  const falt = (d.faltantes_pip || []).length
    ? ` • Faltan pip: <b class="c-amber">${esc(d.faltantes_pip.join(', '))}</b>`
    : ' • <span class="c-green">Dependencias instaladas</span>';
  if (meta) meta.innerHTML = `<b>${d.lineas}</b> lineas${falt}`;
}

function copiarCodigoActual() {
  if (!CODIGO_ACTUAL) return toast('No hay codigo cargado', 'err');
  navigator.clipboard.writeText(CODIGO_ACTUAL);
  toast('Codigo Python copiado al portapapeles', 'ok');
}

async function refinarCodigoWeb(btn) {
  const ruta = document.getElementById('codeSel')?.value || '';
  const instruccion = (document.getElementById('codeInstr')?.value || '').trim();
  if (!instruccion) return toast('Escribe o elige una instruccion de mejora', 'err');
  btn.disabled = true;
  document.getElementById('codeMeta').innerHTML = '<span class="c-cyan">Refinando script y validando sintaxis AST...</span>';
  const d = await apiJson('/api/refinar', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ruta, instruccion }),
  });
  btn.disabled = false;
  if (d.error) return toast(d.error, 'err');
  CODIGO_ACTUAL = d.codigo || '';
  document.getElementById('codeView').innerHTML = resaltarPythonHtml(CODIGO_ACTUAL);
  document.getElementById('ideBadge').innerHTML = d.ast_valido ? '<span class="badge b-remoto">AST VALIDO</span>' : '<span class="badge b-hot">REVISAR</span>';
  document.getElementById('codeMeta').innerHTML = `<span class="c-green">${esc(d.resumen)}</span> (${d.lineas} lineas)`;
  toast('Codigo actualizado y guardado', 'ok');
}

// ==================== MARKETING & CIERRE ====================
async function generarPostWeb(btn) {
  const sub = document.getElementById('mktSub').value;
  const enfoque = (document.getElementById('mktEnf')?.value || '').trim();
  btn.disabled = true;
  document.getElementById('resMktPost').innerHTML = '<div class="muted">Redactando post magnetico...</div>';
  const d = await apiJson('/api/mkt_post', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sub, enfoque }),
  });
  btn.disabled = false;
  if (d.error) { document.getElementById('resMktPost').innerHTML = `<div class="prebox c-red">${esc(d.error)}</div>`; return; }
  const idT = regClip(d.titulo), idC = regClip(d.cuerpo);
  document.getElementById('resMktPost').innerHTML = `
    <div class="field"><label><span>Titulo</span><button class="btn btn-primary btn-xs" onclick="copyId('${idT}')">Copiar Titulo</button></label><div class="prebox">${esc(d.titulo)}</div></div>
    <div class="field"><label><span>Cuerpo Markdown</span><button class="btn btn-ghost btn-xs" onclick="copyId('${idC}')">Copiar Cuerpo</button></label><div class="prebox">${esc(d.cuerpo)}</div></div>
  `;
}

async function generarFollowupWeb(btn) {
  const ctx = (document.getElementById('seqCtx')?.value || '').trim();
  btn.disabled = true;
  document.getElementById('resSeq').innerHTML = '<div class="muted">Generando secuencia de 3 dias...</div>';
  const d = await apiJson('/api/mkt_followup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ctx }),
  });
  btn.disabled = false;
  if (d.error) { document.getElementById('resSeq').innerHTML = `<div class="prebox c-red">${esc(d.error)}</div>`; return; }
  const i1 = regClip(d.dia_1), i3 = regClip(d.dia_3), ic = regClip(d.cierre);
  document.getElementById('resSeq').innerHTML = `
    <div class="field"><label><span>Dia 1 (24h)</span><button class="btn btn-ghost btn-xs" onclick="copyId('${i1}')">Copiar</button></label><div class="prebox">${esc(d.dia_1)}</div></div>
    <div class="field"><label><span>Dia 3 (Valor)</span><button class="btn btn-ghost btn-xs" onclick="copyId('${i3}')">Copiar</button></label><div class="prebox">${esc(d.dia_3)}</div></div>
    <div class="field"><label><span>Cierre Suave</span><button class="btn btn-ghost btn-xs" onclick="copyId('${ic}')">Copiar</button></label><div class="prebox">${esc(d.cierre)}</div></div>
  `;
}

async function generarDeliveryWeb(btn) {
  const ctx = (document.getElementById('seqCtx')?.value || '').trim();
  btn.disabled = true;
  document.getElementById('resSeq').innerHTML = '<div class="muted">Generando kit de entrega, review y upsell...</div>';
  const d = await apiJson('/api/mkt_delivery', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ctx }),
  });
  btn.disabled = false;
  if (d.error) { document.getElementById('resSeq').innerHTML = `<div class="prebox c-red">${esc(d.error)}</div>`; return; }
  const ie = regClip(d.entrega), ir = regClip(d.review), iu = regClip(d.upsell);
  document.getElementById('resSeq').innerHTML = `
    <div class="field"><label><span>Entrega Final</span><button class="btn btn-success btn-xs" onclick="copyId('${ie}')">Copiar</button></label><div class="prebox">${esc(d.entrega)}</div></div>
    <div class="field"><label><span>Pedir Review / Testimonio</span><button class="btn btn-ghost btn-xs" onclick="copyId('${ir}')">Copiar</button></label><div class="prebox">${esc(d.review)}</div></div>
    <div class="field"><label><span>Upsell / Retainer Mensual</span><button class="btn btn-purple btn-xs" onclick="copyId('${iu}')">Copiar</button></label><div class="prebox">${esc(d.upsell)}</div></div>
  `;
}

async function generarBiosWeb(btn) {
  btn.disabled = true;
  document.getElementById('resMktBios').innerHTML = '<div class="muted">Generando 3 bios...</div>';
  const d = await apiJson('/api/mkt_bios', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
  btn.disabled = false;
  if (d.error) { document.getElementById('resMktBios').innerHTML = `<div class="prebox c-red">${esc(d.error)}</div>`; return; }
  const idR = regClip(d.reddit), idG = regClip(d.github), idW = regClip(d.whop);
  document.getElementById('resMktBios').innerHTML = `
    <div class="field"><label><span>Reddit Bio</span><button class="btn btn-ghost btn-xs" onclick="copyId('${idR}')">Copiar</button></label><div class="prebox">${esc(d.reddit)}</div></div>
    <div class="field"><label><span>GitHub Bio</span><button class="btn btn-ghost btn-xs" onclick="copyId('${idG}')">Copiar</button></label><div class="prebox">${esc(d.github)}</div></div>
    <div class="field"><label><span>Whop Bio</span><button class="btn btn-ghost btn-xs" onclick="copyId('${idW}')">Copiar</button></label><div class="prebox">${esc(d.whop)}</div></div>
  `;
}

async function generarPortafolioWeb(btn) {
  btn.disabled = true;
  document.getElementById('resMktBios').innerHTML = '<div class="muted">Construyendo PORTAFOLIO.md profesional...</div>';
  const d = await apiJson('/api/mkt_portfolio', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
  btn.disabled = false;
  if (d.error) { document.getElementById('resMktBios').innerHTML = `<div class="prebox c-red">${esc(d.error)}</div>`; return; }
  const idP = regClip(d.markdown);
  document.getElementById('resMktBios').innerHTML = `
    <div class="c-green" style="font-size:12px;margin-bottom:8px;">Guardado en PORTAFOLIO.md</div>
    <div class="field"><label><span>PORTAFOLIO.md</span><button class="btn btn-success btn-xs" onclick="copyId('${idP}')">Copiar Markdown</button></label><div class="prebox">${esc(d.markdown)}</div></div>
  `;
  toast('PORTAFOLIO.md creado', 'ok');
}

// ==================== CALCULADORA COMPARATIVA, FACTURAS & WHOP ====================
function usarMontoEnFactura(monto) {
  const el = document.getElementById('invUsd');
  if (el) {
    el.value = Math.ceil(monto);
    el.focus();
    toast(`$${Math.ceil(monto)} USD cargado en Factura`, 'ok');
  }
}

function calcularPrecio() {
  const hrs = parseFloat(document.getElementById('calcHrs')?.value || '4');
  const rate = parseFloat(document.getElementById('calcRate')?.value || '25');
  const mult = parseFloat(document.getElementById('calcMult')?.value || '1');
  const trm = parseFloat(document.getElementById('calcTrm')?.value || '4200');
  const bruto = hrs * rate * mult;

  const lblH = document.getElementById('lblHrs');
  const lblB = document.getElementById('cBruto');
  if (lblH) lblH.textContent = hrs + 'h';
  if (lblB) lblB.textContent = '$' + bruto.toFixed(2) + ' USD';

  const pasarelas = [
    { nom: 'Binance USDT', tag: '0% FEE', best: true, fee: 0, gross: bruto },
    { nom: 'Airtm', tag: '~2%', best: false, fee: bruto * 0.02, gross: bruto > 0 ? bruto / 0.98 : 0 },
    { nom: 'PayPal', tag: '5.4%+0.3', best: false, fee: bruto > 0 ? bruto * 0.054 + 0.30 : 0, gross: bruto > 0 ? (bruto + 0.30) / 0.946 : 0 },
  ];

  const grid = document.getElementById('calcCompareGrid');
  if (!grid) return;
  grid.innerHTML = pasarelas.map(g => {
    const neto = Math.max(0, bruto - g.fee);
    const cop = Math.round(neto * trm);
    return `
      <div class="gw-card ${g.best ? 'best' : ''}">
        <div class="gw-name"><span>${g.nom}</span><span class="badge ${g.best ? 'b-remoto' : 'b-custom'}">${g.tag}</span></div>
        <div class="gw-net">$${neto.toFixed(2)}</div>
        <div class="gw-cop">$${cop.toLocaleString('es-CO')} COP</div>
        <div class="gw-sub">Comision: -$${g.fee.toFixed(2)}</div>
        <div class="gw-sub">Gross-Up: <b style="color:var(--amber);">$${g.gross.toFixed(2)}</b></div>
        <button class="btn btn-ghost btn-xs" style="margin-top:4px;" onclick="usarMontoEnFactura(${g.gross.toFixed(2)})">Usar en Factura</button>
      </div>
    `;
  }).join('');
}

async function generarFacturaWeb() {
  const payload = {
    cliente: document.getElementById('invCli')?.value || 'Client',
    proyecto: document.getElementById('invProj')?.value || 'Custom Python Automation',
    monto: document.getElementById('invUsd')?.value || '100',
    tipo: document.getElementById('invTipo')?.value || 'Final Payment (Full Delivery)',
    nota: document.getElementById('invNota')?.value || '',
  };
  const r = await fetch('/api/factura', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const htmlTxt = await r.text();
  const w = window.open('', '_blank');
  if (w) { w.document.open(); w.document.write(htmlTxt); w.document.close(); }
  toast('Factura PDF abierta y archivada en entregas_clientes/', 'ok');
}

async function empaquetarWhopWeb(btn) {
  const nombre = (document.getElementById('whopNom')?.value || '').trim() || 'ZeroTouch Automation Tool';
  const ruta = document.getElementById('whopSel')?.value || '';
  btn.disabled = true;
  document.getElementById('resWhop').innerHTML = '<div class="muted">Refactorizando codigo y armando .ZIP comercial...</div>';
  const d = await apiJson('/api/whop_pack', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ nombre, ruta }),
  });
  btn.disabled = false;
  if (d.error) { document.getElementById('resWhop').innerHTML = `<div class="prebox c-red">${esc(d.error)}</div>`; return; }
  const idW = regClip(d.whop_copy);
  const idG = regClip(d.guion || '');
  document.getElementById('resWhop').innerHTML = `
    <div class="c-green" style="font-size:12px;margin-bottom:8px;">ZIP listo: ${esc(d.zip_path)}</div>
    <div class="field"><label><span>Copy de Ventas Whop</span><button class="btn btn-primary btn-xs" onclick="copyId('${idW}')">Copiar Copy</button></label><div class="prebox">${esc(d.whop_copy)}</div></div>
    ${d.guion ? `<div class="field"><label><span>Guion TikTok / Short 30s</span><button class="btn btn-purple btn-xs" onclick="copyId('${idG}')">Copiar Guion</button></label><div class="prebox">${esc(d.guion)}</div></div>` : ''}
  `;
  toast('Paquete comercial Whop generado', 'ok');
}

// ==================== TERMINAL COLOREADA & DIAGNOSTICO ====================
function renderLiveLogs(logs) {
  const el = document.getElementById('liveLogs');
  if (!el || !logs || !logs.length) return;
  el.innerHTML = logs.map(line => {
    let cls = '';
    if (line.includes('Lead ')) cls = 'log-lead';
    else if (line.includes('[!]') || line.includes('Error')) cls = 'log-err';
    else if (line.includes('Aviso') || line.includes('cooldown')) cls = 'log-warn';
    else if (line.includes('terminado') || line.includes('iniciado') || line.includes('Backup') || line.includes('OK')) cls = 'log-ok';
    return `<div class="term-line ${cls}">${esc(line)}</div>`;
  }).join('');
  el.scrollTop = el.scrollHeight;
}

async function correrDryRunWeb(btn, outId = 'resDiag') {
  btn.disabled = true;
  const el = document.getElementById(outId);
  if (el) {
    el.style.display = 'block';
    el.textContent = 'Probando todas las plataformas activas en paralelo (0 tokens IA)...';
  }
  const d = await apiJson('/api/scan_dry', { method: 'POST' });
  btn.disabled = false;
  if (d.error) { if (el) el.textContent = 'Error: ' + d.error; return; }
  const fLines = (d.detalle_fuentes || []).map(f => `  ${f.ok ? '[OK ]' : '[ERR]'} ${f.fuente.padEnd(18)} [${f.modo}] -> ${f.bruto} raw | ${f.tech} tech`).join('\n');
  const cLines = (d.candidatas_preview || []).slice(0, 10).map(c => `  - [${c.plataforma} | ${c.tipo} | ${c.presupuesto || '$?'}] ${c.titulo}`).join('\n') || '  (Todas las ofertas vigentes ya estan en tu cache de vistos)';
  if (el) {
    el.textContent = `=== DRY-RUN OMNI-GRID (${d.segundos}s | 0 Tokens) ===\nFuentes OK: ${d.fuentes_ok}/${d.fuentes_total} | Bruto: ${d.bruto} | Bloqueados: ${d.descartados} | Ya vistos: ${d.ya_vistos}\n\nPLATAFORMAS:\n${fLines}\n\nTOP CANDIDATAS NUEVAS (${(d.candidatas_preview || []).length}):\n${cLines}`;
  }
  toast('Dry-Run completado (0 tokens)', 'ok');
  await cargarDatos(false);
}

async function correrDiagWeb(btn) {
  btn.disabled = true;
  document.getElementById('resDiag').textContent = 'Probando Reddit, Telegram y Gemini...';
  const d = await apiJson('/api/diagnostico');
  document.getElementById('resDiag').textContent = d.reporte || d.error;
  btn.disabled = false;
}

async function probarTelegramWeb(btn) {
  btn.disabled = true;
  const d = await apiJson('/api/test_tg', { method: 'POST' });
  btn.disabled = false;
  toast(d.ok ? 'Alerta de prueba enviada a Telegram' : 'Fallo envio a Telegram', d.ok ? 'ok' : 'err');
  cargarDatos(false);
}

async function hacerBackupWeb() {
  const d = await apiJson('/api/backup', { method: 'POST' });
  toast(d.path ? 'Backup SQLite creado en backups/' : 'No hay DB todavia', d.path ? 'ok' : 'err');
}