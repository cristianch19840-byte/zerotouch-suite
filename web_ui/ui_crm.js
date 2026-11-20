// ==================== ZERO-TOUCH UI v14.0 — CRM, KANBAN & DRAWER ====================
let CRM_VIEW = localStorage.getItem('zt_crm_view') || 'table';
let FILTRO_TIPO = '';
const DIRTY_LEADS = new Set();

const KANBAN_COLS = [
  { key: 'nuevo',      label: 'Por Atacar',  color: 'var(--accent)' },
  { key: 'contactado', label: 'Contactado',  color: 'var(--purple)' },
  { key: 'negociando', label: 'Negociando',  color: 'var(--amber)' },
  { key: 'ganado',     label: 'Ganado ($)',  color: 'var(--green)' },
  { key: 'descartado', label: 'Descartado',  color: 'var(--text-3)' },
];

function setFiltroTipo(tipo, btn) {
  FILTRO_TIPO = tipo || '';
  document.querySelectorAll('#tipoChips .chip').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  renderCrmActual();
}

function setCrmView(modo) {
  CRM_VIEW = modo === 'kanban' ? 'kanban' : 'table';
  localStorage.setItem('zt_crm_view', CRM_VIEW);
  const bTab = document.getElementById('btnViewTable');
  const bKan = document.getElementById('btnViewKanban');
  const wTab = document.getElementById('crmTableWrap');
  const wKan = document.getElementById('crmKanbanWrap');
  if (bTab) bTab.classList.toggle('active', CRM_VIEW === 'table');
  if (bKan) bKan.classList.toggle('active', CRM_VIEW === 'kanban');
  if (wTab) wTab.style.display = CRM_VIEW === 'table' ? 'block' : 'none';
  if (wKan) wKan.style.display = CRM_VIEW === 'kanban' ? 'grid' : 'none';
  renderCrmActual();
}

function marcarDirty(id) {
  DIRTY_LEADS.add(id);
  const row = document.getElementById('row_' + id);
  if (row) row.classList.add('dirty');
  actualizarBannerCrm();
}

function actualizarBannerCrm() {
  const el = document.getElementById('crmStatusBanner');
  if (!el) return;
  if (DATA.scan && DATA.scan.running) {
    el.innerHTML = '<span class="c-cyan">Escaneando 12+ plataformas en paralelo...</span>';
  } else if (DIRTY_LEADS.size > 0) {
    el.innerHTML = `<span class="c-amber">Tienes ${DIRTY_LEADS.size} fila(s) con cambios sin guardar (auto-refresco pausado en la tabla).</span>`;
  } else if (DATA.scan && DATA.scan.last_result) {
    const lr = DATA.scan.last_result;
    const fTxt = lr.fuentes_total ? `Fuentes ${lr.fuentes_ok}/${lr.fuentes_total} • ` : '';
    el.textContent = `Ultimo barrido: ${fTxt}${lr.alertas} alertas nuevas • ${lr.descartados} filtrados 0-tokens (${lr.segundos}s)`;
  } else {
    el.textContent = '';
  }
}

function renderKpis() {
  const k = DATA.kpis || {};
  const usd = Number(k.usd || 0);
  const pipe = Number(k.pipeline_usd || 0);
  const ganados = Number(k.ganados || 0);
  const trm = Number((window.CFG_ACTUAL && window.CFG_ACTUAL.trm_cop) || 4200);
  const ticket = ganados > 0 ? Math.round(usd / ganados) : 0;
  const us = Number(k.tok_usados || 0);
  const ah = Number(k.tok_ahorrados || 0);
  const pctTok = (us + ah) > 0 ? Math.round((ah / (us + ah)) * 100) : 0;

  const setT = (id, val) => { const e = document.getElementById(id); if (e) e.textContent = val; };
  setT('kUsd', '$' + usd.toFixed(2));
  setT('kUsdCop', '~$' + Math.round(usd * trm).toLocaleString('es-CO') + ' COP');
  setT('kPipe', '$' + Math.round(pipe).toLocaleString('en-US'));
  setT('kLeads', `${k.leads_total || 0} / ${ganados}`);
  setT('kTicket', `Ticket prom: $${ticket} USD`);
  setT('kCierre', (k.tasa_cierre || 0) + '%');
  setT('kFuentes', `${k.fuentes_ok || 0} / ${k.fuentes_total || 0}`);
  setT('kTok', ah.toLocaleString());
  setT('kTokPct', `${pctTok}% filtrado 0-tokens`);

  const nuevosN = (DATA.leads || []).filter(l => l.estado === 'nuevo').length;
  setT('badgeLeadsNuevos', nuevosN);
  setT('badgeFuentesOk', `${k.fuentes_ok || 0}/${k.fuentes_total || 12}`);
}

function poblarFiltroPlataformas() {
  const sel = document.getElementById('qPlat');
  if (!sel) return;
  const actual = sel.value;
  const unicas = Array.from(new Set((DATA.leads || []).map(l => l.plataforma || l.fuente).filter(Boolean))).sort();
  sel.innerHTML = '<option value="">Todas las plataformas</option>' +
    unicas.map(p => `<option value="${esc(p)}" ${p === actual ? 'selected' : ''}>${esc(p)}</option>`).join('');
}

function obtenerLeadsFiltrados() {
  const q = (document.getElementById('qSearch')?.value || '').trim().toLowerCase();
  const est = document.getElementById('qEstado')?.value || '';
  const plat = document.getElementById('qPlat')?.value || '';
  const minS = parseInt(document.getElementById('qMinScore')?.value || '0', 10);
  const sortBy = document.getElementById('qSort')?.value || 'reciente';

  let lista = (DATA.leads || []).filter(l => {
    const lPlat = l.plataforma || l.fuente || '';
    const lTipo = l.tipo_trabajo || 'freelance';
    const matchQ = !q || (`#${l.id} ${l.titulo} ${l.fuente} ${lPlat} ${l.categoria} ${l.notas || ''}`).toLowerCase().includes(q);
    return l.score >= minS
      && (!est || l.estado === est)
      && (!FILTRO_TIPO || lTipo === FILTRO_TIPO)
      && (!plat || lPlat === plat)
      && matchQ;
  });

  if (sortBy === 'score') {
    lista.sort((a, b) => b.score - a.score || (b.presupuesto_num || 0) - (a.presupuesto_num || 0) || b.id - a.id);
  } else if (sortBy === 'dinero') {
    lista.sort((a, b) => (b.presupuesto_num || 0) - (a.presupuesto_num || 0) || b.score - a.score);
  }
  return lista;
}

function renderCrmActual() {
  actualizarBannerCrm();
  if (CRM_VIEW === 'kanban') renderKanbanCrm();
  else renderTablaCrm();
}

function renderTablaCrm() {
  const tb = document.getElementById('tbodyLeads');
  if (!tb) return;
  const filtrados = obtenerLeadsFiltrados();
  if (!filtrados.length) {
    tb.innerHTML = `<tr><td colspan="9"><div class="empty-state"><b>Sin oportunidades para este filtro</b>Pulsa "Escanear" arriba o limpia los filtros para ver tus leads.</div></td></tr>`;
    return;
  }

  tb.innerHTML = filtrados.map(l => {
    const t = l.tipo_trabajo || 'freelance';
    const scCls = l.score >= 8 ? 'score-hi' : (l.score >= 6 ? 'score-mid' : 'score-low');
    const esHigh = (l.presupuesto_num || 0) >= 150;
    return `
      <tr id="row_${l.id}" class="${DIRTY_LEADS.has(l.id) ? 'dirty' : ''}">
        <td><span style="font-family:var(--font-mono);color:var(--text-2);font-weight:700;">#${l.id}</span></td>
        <td><span class="score-pill ${scCls}">${l.score}/10</span></td>
        <td>
          <div style="font-weight:700;color:var(--text-0);">${esc(l.fuente)}</div>
          <div class="lead-meta"><span class="badge b-${esc(t)}">${esc(t)}</span><span>${esc(l.categoria)}</span></div>
        </td>
        <td>
          <a class="lead-title" href="${esc(l.link)}" target="_blank" rel="noopener">${esc(l.titulo)}</a>
          ${l.prioridad_tag ? `<span class="badge b-hot" style="margin-left:6px;">${esc(l.prioridad_tag)}</span>` : ''}
          <div class="lead-meta">
            <span>${esc(l.competencia || '')}</span>
            ${l.confianza ? `<span>• ${esc(l.confianza)}</span>` : ''}
          </div>
        </td>
        <td style="white-space:nowrap;font-family:var(--font-mono);font-weight:700;${esHigh ? 'color:var(--green);' : 'color:var(--text-1);'}">${esc(l.presupuesto || 'Por definir')}</td>
        <td>
          <select id="est_${l.id}" onchange="marcarDirty(${l.id})" style="padding:5px 8px;font-size:12px;">
            ${['nuevo', 'contactado', 'negociando', 'ganado', 'descartado'].map(o => `<option value="${o}" ${l.estado === o ? 'selected' : ''}>${o}</option>`).join('')}
          </select>
        </td>
        <td><input class="usd-input" type="number" step="1" id="usd_${l.id}" value="${l.ganancia_usd || 0}" oninput="marcarDirty(${l.id})"></td>
        <td><input class="note-input" type="text" id="not_${l.id}" value="${esc(l.notas || '')}" placeholder="Seguimiento..." oninput="marcarDirty(${l.id})"></td>
        <td>
          <div class="row-actions">
            <button class="btn btn-success btn-xs" onclick="guardarLead(${l.id})" title="Guardar cambios">Guardar</button>
            <button class="btn btn-purple btn-xs" onclick="abrirCopilotoLead(${l.id})" title="Abrir Copiloto IA">IA</button>
            ${l.dm_url ? `<a class="btn btn-ghost btn-xs" href="${esc(l.dm_url)}" target="_blank" rel="noopener" title="DM directo Reddit">DM</a>` : ''}
            <button class="btn btn-ghost btn-xs" onclick="pasarAFactura(${l.id})" title="Facturar este lead">PDF</button>
            <button class="btn btn-danger btn-xs" onclick="borrarLead(${l.id})" title="Eliminar">&times;</button>
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

function renderKanbanCrm() {
  const wrap = document.getElementById('crmKanbanWrap');
  if (!wrap) return;
  const filtrados = obtenerLeadsFiltrados();

  wrap.innerHTML = KANBAN_COLS.map(col => {
    const items = filtrados.filter(l => (l.estado || 'nuevo') === col.key);
    const sumaUsd = col.key === 'ganado'
      ? items.reduce((a, b) => a + Number(b.ganancia_usd || 0), 0)
      : items.reduce((a, b) => a + Number(b.presupuesto_num || 0), 0);
    const subMonto = sumaUsd > 0 ? `<span style="font-family:var(--font-mono);font-size:11px;color:${col.color};">$${Math.round(sumaUsd)}</span>` : '';

    const cardsHtml = items.length ? items.slice(0, 35).map(l => {
      const t = l.tipo_trabajo || 'freelance';
      const scCls = l.score >= 8 ? 'score-hi' : (l.score >= 6 ? 'score-mid' : 'score-low');
      return `
        <div class="k-card">
          <div class="k-card-top">
            <div><span class="score-pill ${scCls}" style="min-width:36px;padding:2px 6px;">${l.score}</span> <span class="badge b-${esc(t)}">${esc(l.fuente)}</span></div>
            <span style="font-family:var(--font-mono);font-size:11.5px;font-weight:700;color:var(--green);">${esc(col.key === 'ganado' && l.ganancia_usd > 0 ? '$' + l.ganancia_usd : (l.presupuesto || '$?'))}</span>
          </div>
          <a class="k-card-title" href="${esc(l.link)}" target="_blank" rel="noopener">${esc(l.titulo.slice(0, 92))}</a>
          <div class="muted" style="font-size:11px;">${esc(l.competencia || '')}</div>
          ${l.notas ? `<div class="muted" style="font-size:11px;color:var(--amber);">Nota: ${esc(l.notas.slice(0, 60))}</div>` : ''}
          <div class="k-card-foot">
            <select onchange="moverEstadoKanban(${l.id}, this.value)">
              ${KANBAN_COLS.map(c => `<option value="${c.key}" ${l.estado === c.key ? 'selected' : ''}>${c.label}</option>`).join('')}
            </select>
            <div style="display:flex;gap:4px;">
              <button class="btn btn-purple btn-xs" onclick="abrirCopilotoLead(${l.id})">IA</button>
              <button class="btn btn-ghost btn-xs" onclick="pasarAFactura(${l.id})">PDF</button>
            </div>
          </div>
        </div>
      `;
    }).join('') : `<div class="muted" style="text-align:center;padding:24px 8px;font-size:11.5px;">Sin leads aqui</div>`;

    return `
      <div class="kanban-col">
        <div class="kanban-head" style="color:${col.color};">
          <span>${col.label}</span>
          <div style="display:flex;align-items:center;gap:6px;">${subMonto}<span class="kanban-count">${items.length}</span></div>
        </div>
        ${cardsHtml}
      </div>
    `;
  }).join('');
}

async function moverEstadoKanban(id, nuevoEstado) {
  const lead = (DATA.leads || []).find(x => x.id === id);
  if (!lead) return;
  let usd = Number(lead.ganancia_usd || 0);
  if (nuevoEstado === 'ganado' && usd <= 0) {
    const sugerido = lead.presupuesto_num > 0 ? String(Math.round(lead.presupuesto_num)) : '100';
    const resp = prompt(`Coronaste Lead #${id}! Cuantos USD cobraste?`, sugerido);
    if (resp === null) { renderKanbanCrm(); return; }
    usd = parseFloat(resp.replace(/[^0-9.]/g, '')) || 0;
  }
  const d = await apiJson('/api/update', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id, estado: nuevoEstado, usd, notas: lead.notas || '' }),
  });
  if (d.error) return toast(d.error, 'err');
  toast(`Lead #${id} movido a ${nuevoEstado.toUpperCase()}`, 'ok');
  await cargarDatos(true);
}

async function guardarLead(id) {
  const estado = document.getElementById('est_' + id).value;
  const rawUsd = document.getElementById('usd_' + id).value;
  const usd = rawUsd === '' ? 0 : (parseFloat(rawUsd) || 0);
  const notas = document.getElementById('not_' + id).value || '';
  const d = await apiJson('/api/update', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id, estado, usd, notas }),
  });
  if (d.error) return toast(d.error, 'err');
  DIRTY_LEADS.delete(id);
  const row = document.getElementById('row_' + id);
  if (row) row.classList.remove('dirty');
  toast(`Lead #${id} actualizado`, 'ok');
  await cargarDatos(DIRTY_LEADS.size === 0);
}

async function borrarLead(id) {
  if (!confirm(`Eliminar el lead #${id} de tu CRM?`)) return;
  const d = await apiJson('/api/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }),
  });
  if (d.error) return toast(d.error, 'err');
  DIRTY_LEADS.delete(id);
  toast(`Lead #${id} eliminado`, 'ok');
  await cargarDatos(true);
}

function pasarAFactura(id) {
  const l = (DATA.leads || []).find(x => x.id === id);
  if (!l) return;
  const cli = document.getElementById('invCli');
  const proj = document.getElementById('invProj');
  const usd = document.getElementById('invUsd');
  if (cli) cli.value = l.autor ? l.autor : 'Client';
  if (proj) proj.value = (l.titulo || '').replace(/^\[[^\]]+\]\s*/, '').slice(0, 95);
  if (usd) usd.value = l.ganancia_usd > 0 ? l.ganancia_usd : (l.presupuesto_num > 0 ? Math.round(l.presupuesto_num) : 100);
  verTab('t_whop', 'Calculadora, Facturas & Whop', document.getElementById('nav_whop'));
  toast(`Lead #${id} pre-cargado en Factura PDF`, 'ok');
}

// ==================== SLIDE-OVER DRAWER & COPILOTO CON PESTANAS ====================
let COP_UID = 0;

function cambiarSubtabCop(uid, idx, btn) {
  const root = document.getElementById('cop_' + uid);
  if (!root) return;
  root.querySelectorAll('.subtab').forEach(b => b.classList.remove('active'));
  root.querySelectorAll('.cop-pane').forEach(p => p.style.display = 'none');
  if (btn) btn.classList.add('active');
  const pane = root.querySelector(`.cop-pane[data-idx="${idx}"]`);
  if (pane) pane.style.display = 'block';
}

function renderBloqueCopiloto(res) {
  if (!res || res.error) {
    return `<div class="prebox" style="border-color:var(--red);color:var(--red);">Error: ${esc(res ? res.error : 'Sin respuesta de Gemini')}</div>`;
  }
  const uid = ++COP_UID;
  const idA = regClip(res.pitch_a);
  const idB = regClip(res.pitch_b);
  const idP = regClip(res.preguntas);
  const idF = regClip(res.followup);
  const idCob = regClip(res.cobro);
  const idCon = regClip(res.micro_contrato);
  const idCod = regClip(res.codigo);

  const codeHtml = (typeof resaltarPythonHtml === 'function' && res.codigo)
    ? resaltarPythonHtml(res.codigo)
    : `<div class="prebox" style="max-height:360px;">${esc(res.codigo || '')}</div>`;

  return `
    <div id="cop_${uid}">
      <div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-bottom:12px;">
        <span class="badge b-freelance">${esc(res.plataforma || 'Auto')}</span>
        <span class="muted">${esc(res.confianza || '')}</span>
        ${res.dm_url ? `<a class="btn btn-primary btn-xs" style="margin-left:auto;" href="${esc(res.dm_url)}" target="_blank" rel="noopener">Abrir DM Reddit</a>` : ''}
      </div>

      ${res.estrategia ? `<div style="background:var(--accent-soft);border:1px solid rgba(56,189,248,0.28);border-radius:10px;padding:10px 12px;margin-bottom:10px;font-size:12.5px;"><b class="c-cyan">Estrategia ${esc(res.plataforma || '')}:</b> ${esc(res.estrategia)}</div>` : ''}
      ${res.red_flags ? `<div style="background:var(--amber-soft);border:1px solid rgba(251,191,36,0.28);border-radius:10px;padding:9px 12px;margin-bottom:12px;font-size:12px;"><b class="c-amber">Red Flags:</b> ${esc(res.red_flags)}</div>` : ''}

      <div class="subtabs">
        <button class="subtab active" onclick="cambiarSubtabCop(${uid}, 0, this)">Pitches A/B</button>
        <button class="subtab" onclick="cambiarSubtabCop(${uid}, 1, this)">Precios &amp; Diagnostico</button>
        <button class="subtab" onclick="cambiarSubtabCop(${uid}, 2, this)">Cierre &amp; Contrato</button>
        <button class="subtab" onclick="cambiarSubtabCop(${uid}, 3, this)">Codigo Python</button>
      </div>

      <div class="cop-pane" data-idx="0">
        <div class="field">
          <label><span>Pitch A — Adaptado a ${esc(res.plataforma || 'plataforma')}</span><button class="btn btn-primary btn-xs" onclick="copyId('${idA}')">Copiar Pitch A</button></label>
          <div class="prebox">${esc(res.pitch_a)}</div>
        </div>
        <div class="field">
          <label><span>Pitch B — Enfoque consultivo</span><button class="btn btn-ghost btn-xs" onclick="copyId('${idB}')">Copiar Pitch B</button></label>
          <div class="prebox">${esc(res.pitch_b)}</div>
        </div>
      </div>

      <div class="cop-pane" data-idx="1" style="display:none;">
        <div class="field"><label>Diagnostico tecnico</label><div class="prebox">${esc(res.diagnostico)}</div></div>
        <div class="field"><label>Escalera de precios sugerida (USD)</label><div class="prebox" style="color:var(--green);">${esc(res.precios)}</div></div>
      </div>

      <div class="cop-pane" data-idx="2" style="display:none;">
        ${res.preguntas ? `<div class="field"><label><span>Preguntas de cierre</span><button class="btn btn-ghost btn-xs" onclick="copyId('${idP}')">Copiar</button></label><div class="prebox">${esc(res.preguntas)}</div></div>` : ''}
        <div class="field"><label><span>Micro-Contrato anti-cambios gratis</span><button class="btn btn-ghost btn-xs" onclick="copyId('${idCon}')">Copiar</button></label><div class="prebox">${esc(res.micro_contrato)}</div></div>
        ${res.followup ? `<div class="field"><label><span>Follow-Up 24h</span><button class="btn btn-ghost btn-xs" onclick="copyId('${idF}')">Copiar</button></label><div class="prebox">${esc(res.followup)}</div></div>` : ''}
        ${res.cobro ? `<div class="field"><label><span>Mensaje para pedir pago con muestra</span><button class="btn btn-success btn-xs" onclick="copyId('${idCob}')">Copiar Cobro</button></label><div class="prebox">${esc(res.cobro)}</div></div>` : ''}
      </div>

      <div class="cop-pane" data-idx="3" style="display:none;">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap;">
          <span class="badge ${res.ast_valido ? 'b-remoto' : 'b-custom'}">${res.ast_valido ? 'AST VALIDO' : 'REVISAR SINTAXIS'}</span>
          <div style="display:flex;gap:6px;">
            <button class="btn btn-ghost btn-xs" onclick="copyId('${idCod}')">Copiar Codigo</button>
            <button class="btn btn-primary btn-xs" onclick="irARefinadorDesdeDrawer()">Abrir en Refinador IDE</button>
          </div>
        </div>
        <div class="ide-shell"><div class="ide-body" style="max-height:360px;">${codeHtml}</div></div>
        <div class="muted" style="margin-top:8px;">Guardado en modulo_b_ejecutor/borrador_cliente.py</div>
      </div>
    </div>
  `;
}

function irARefinadorDesdeDrawer() {
  cerrarDrawer();
  verTab('t_code', 'Refinador de Codigo IDE', document.getElementById('nav_code'));
}

function abrirDrawer(titulo, subtitulo, bodyHtml) {
  document.getElementById('drawerTitle').textContent = titulo;
  document.getElementById('drawerSub').textContent = subtitulo || '';
  document.getElementById('drawerBody').innerHTML = bodyHtml;
  document.getElementById('drawerBg').classList.add('open');
}

function cerrarDrawer() {
  document.getElementById('drawerBg').classList.remove('open');
}

async function abrirCopilotoLead(id) {
  const lead = (DATA.leads || []).find(x => x.id === id);
  const sub = lead ? `${lead.fuente} • ${lead.presupuesto || 'Por definir'} • Score ${lead.score}/10` : `Lead #${id}`;
  abrirDrawer(
    `Copiloto Universal — Lead #${id}`,
    sub,
    '<div class="empty-state"><b>Extrayendo oferta y aplicando playbook...</b>Generando Pitch A/B, Red Flags, escalera de precios y script Python validado.</div>'
  );
  const d = await apiJson('/api/copiloto', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ entrada: '#' + id }),
  });
  document.getElementById('drawerBody').innerHTML = renderBloqueCopiloto(d);
}