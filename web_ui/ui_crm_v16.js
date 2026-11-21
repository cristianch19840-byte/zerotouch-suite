// ==================== ZERO-TOUCH TITAN-OS v16.0 — CRM ENTERPRISE UI (KANBAN D&D, 360, CLIENTES, AGENDA) ====================
(function (global) {
  'use strict';

  const ESTADOS_KANBAN = [
    { key: 'nuevo', label: '🆕 Por Atacar', tono: 'cyan' },
    { key: 'contactado', label: '📨 Contactado', tono: 'purple' },
    { key: 'negociando', label: '🤝 Negociando', tono: 'warn' },
    { key: 'ganado', label: '🏆 Ganado', tono: 'ok' },
    { key: 'descartado', label: '🗑️ Descartado', tono: 'muted' },
  ];

  const STATE = {
    subtab: 'kanban', // kanban | clientes | agenda | pitch
    leads: [],
    pipeline: null,
    estancados: [],
    clientes: [],
    tareas: [],
    agendaResumen: null,
    selectedIds: new Set(),
    dragLeadId: null,
    filtros: { q: '', plataforma: '', tipo_trabajo: '', score_min: 0, sort: 'score' },
    cliFiltros: { q: '', solo_recurrentes: false, sort: 'ltv' },
    tareaFiltros: { solo_pendientes: true, solo_vencidas: false, prioridad: '' },
    sseWired: false,
    debounceTimer: null,
  };

  const U = () => global.TitanUI;
  const API = () => global.TitanAPI;

  function wireSSEOnce() {
    if (STATE.sseWired || !global.TitanSSE) return;
    STATE.sseWired = true;
    global.TitanSSE.on('crm.*', () => {
      const sec = document.getElementById('t_crm_v16');
      if (!sec || !sec.classList.contains('active')) return;
      if (STATE.debounceTimer) clearTimeout(STATE.debounceTimer);
      STATE.debounceTimer = setTimeout(() => refreshCurrentSubtab(true), 450);
    });
  }

  async function init() {
    wireSSEOnce();
    renderShellTabs();
    await refreshCurrentSubtab(false);
  }

  function renderShellTabs() {
    const bar = document.getElementById('t16CrmSubtabs');
    if (!bar) return;
    const tabs = [
      { id: 'kanban', label: '🗂️ Kanban Drag & Drop' },
      { id: 'clientes', label: '👥 Cartera Clientes (LTV)' },
      { id: 'agenda', label: '📋 Agenda & Tareas' },
      { id: 'pitch', label: '✍️ Pitch Studio A/B' },
    ];
    bar.innerHTML = tabs.map((t) =>
      `<button class="t16-subtab ${STATE.subtab === t.id ? 'active' : ''}" onclick="TitanCRMUI.switchSubtab('${t.id}')">${t.label}</button>`
    ).join('');
  }

  async function switchSubtab(id) {
    STATE.subtab = id;
    renderShellTabs();
    await refreshCurrentSubtab(false);
  }

  async function refreshCurrentSubtab(silent = false) {
    if (STATE.subtab === 'kanban') await loadKanban(silent);
    else if (STATE.subtab === 'clientes') await loadClientes(silent);
    else if (STATE.subtab === 'agenda') await loadAgenda(silent);
    else if (STATE.subtab === 'pitch' && global.TitanPitchUI) await global.TitanPitchUI.render('t16CrmBody');
  }

  // ==================== 1. KANBAN DRAG & DROP + FORECAST + BULK ====================
  async function loadKanban(silent = false) {
    const host = document.getElementById('t16CrmBody');
    if (!host) return;
    if (!silent && !STATE.leads.length) host.innerHTML = '<div class="t16-skeleton" style="height:260px;"></div>';

    const f = STATE.filtros;
    const qs = new URLSearchParams({ limit: '250', sort: f.sort || 'score' });
    if (f.q) qs.set('q', f.q);
    if (f.plataforma) qs.set('plataforma', f.plataforma);
    if (f.tipo_trabajo) qs.set('tipo_trabajo', f.tipo_trabajo);
    if (Number(f.score_min) > 0) qs.set('score_min', String(f.score_min));

    const trm = Number(global.TitanStore?.get('prefs.trm_cop') || 4200);
    const [rLeads, rPipe, rEst] = await Promise.all([
      API().get(`/api/v2/leads?${qs.toString()}`, { silent }),
      API().get(`/api/v2/pipeline?trm_cop=${trm}`, { silent }),
      API().get('/api/v2/leads/estancados?limit=15', { silent }),
    ]);

    if (rLeads?.ok) STATE.leads = rLeads.items || [];
    if (rPipe?.ok) STATE.pipeline = rPipe.pipeline || null;
    if (rEst?.ok) STATE.estancados = rEst.items || [];

    renderKanbanView();
  }

  function renderKanbanView() {
    const host = document.getElementById('t16CrmBody');
    if (!host) return;
    const p = STATE.pipeline || {};
    const f = STATE.filtros;

    const kpisHtml = `
      <div class="t16-kpi-grid">
        <div class="t16-kpi">
          <span class="t16-kpi-lbl">Facturado Ganado</span>
          <span class="t16-kpi-val" style="color:var(--t16-green);">${U().fmtUSD(p.facturado_usd || 0, 0)}</span>
          <span class="t16-kpi-sub">${U().fmtCOP(p.facturado_cop || 0)} &bull; ${p.ganados || 0} ganados (${p.tasa_cierre_pct || 0}%)</span>
        </div>
        <div class="t16-kpi">
          <span class="t16-kpi-lbl">Forecast Ponderado</span>
          <span class="t16-kpi-val" style="color:var(--t16-cyan);">${U().fmtUSD(p.pipeline_ponderado_usd || 0, 0)}</span>
          <span class="t16-kpi-sub">Bruto en juego: ${U().fmtUSD(p.pipeline_bruto_usd || 0, 0)}</span>
        </div>
        <div class="t16-kpi">
          <span class="t16-kpi-lbl">Ticket Promedio</span>
          <span class="t16-kpi-val">${U().fmtUSD(p.ticket_promedio_usd || 0, 0)}</span>
          <span class="t16-kpi-sub">Clientes: ${p.clientes_totales || 0} (${p.clientes_recurrentes || 0} VIP/Rec)</span>
        </div>
        <div class="t16-kpi">
          <span class="t16-kpi-lbl">Leads Estancados</span>
          <span class="t16-kpi-val" style="color:${STATE.estancados.length ? 'var(--t16-amber)' : 'var(--t16-green)'};">${STATE.estancados.length}</span>
          <span class="t16-kpi-sub">${STATE.estancados.length ? '<a href="#" style="color:var(--t16-amber);" onclick="TitanCRMUI.openEstancadosDrawer();return false;">Ver acciones sugeridas &rarr;</a>' : 'Seguimiento al día'}</span>
        </div>
      </div>
    `;

    const toolbarHtml = `
      <div class="t16-toolbar">
        <input class="t16-input" id="t16CrmSearch" placeholder="🔍 Buscar título, autor, stack..." value="${U().escHtml(f.q)}" style="flex:1;min-width:180px;" onkeydown="if(event.key==='Enter')TitanCRMUI.applyLeadFilters()">
        <select class="t16-select" id="t16CrmPlat" onchange="TitanCRMUI.applyLeadFilters()">
          <option value="">Todas plataformas</option>
          ${['Reddit', 'Freelancer', 'GitHub', 'HackerNews', 'Dev.to', 'RemoteOK', 'WWR', 'Python.org', 'Lobsters'].map((pl) =>
            `<option value="${pl}" ${f.plataforma === pl ? 'selected' : ''}>${pl}</option>`
          ).join('')}
        </select>
        <select class="t16-select" id="t16CrmTipo" onchange="TitanCRMUI.applyLeadFilters()">
          <option value="">Todos tipos</option>
          <option value="freelance" ${f.tipo_trabajo === 'freelance' ? 'selected' : ''}>Freelance</option>
          <option value="bounty" ${f.tipo_trabajo === 'bounty' ? 'selected' : ''}>Bounty</option>
          <option value="remoto" ${f.tipo_trabajo === 'remoto' ? 'selected' : ''}>Remoto</option>
        </select>
        <select class="t16-select" id="t16CrmScore" onchange="TitanCRMUI.applyLeadFilters()">
          <option value="0" ${Number(f.score_min) === 0 ? 'selected' : ''}>Score: Todos</option>
          <option value="7" ${Number(f.score_min) === 7 ? 'selected' : ''}>Score &ge; 7</option>
          <option value="8" ${Number(f.score_min) === 8 ? 'selected' : ''}>Score &ge; 8 (Oro)</option>
          <option value="9" ${Number(f.score_min) === 9 ? 'selected' : ''}>Score &ge; 9</option>
        </select>
        <button class="t16-pill" onclick="TitanCRMUI.applyLeadFilters()">Filtrar</button>
        <button class="t16-pill t16-pill-live" onclick="TitanCRMUI.openNewLeadModal()">+ Nuevo Lead</button>
      </div>
    `;

    const selCount = STATE.selectedIds.size;
    const bulkHtml = selCount > 0 ? `
      <div class="t16-bulk-bar">
        <span><b>${selCount}</b> lead(s) seleccionados</span>
        <div style="display:flex;gap:6px;flex-wrap:wrap;">
          ${ESTADOS_KANBAN.map((e) => `<button class="t16-pill" onclick="TitanCRMUI.bulkMove('${e.key}')">&rarr; ${e.label}</button>`).join('')}
          <button class="t16-pill" onclick="TitanCRMUI.clearSelection()">✕ Limpiar</button>
        </div>
      </div>
    ` : '';

    const byEstado = { nuevo: [], contactado: [], negociando: [], ganado: [], descartado: [] };
    for (const l of STATE.leads) {
      const k = byEstado[l.estado] ? l.estado : 'nuevo';
      byEstado[k].push(l);
    }

    const colsHtml = ESTADOS_KANBAN.map((col) => {
      const items = byEstado[col.key] || [];
      const sumaUsd = items.reduce((acc, it) => acc + Number(col.key === 'ganado' ? (it.ganancia_usd || it.presupuesto_num || 0) : (it.presupuesto_num || 0)), 0);
      const cardsHtml = items.map((l) => renderLeadCard(l)).join('') || U().renderEmptyState('Sin leads', 'Arrastra una tarjeta aquí');
      return `
        <div class="t16-kanban-col t16-drop-col" data-estado="${col.key}"
             ondragover="TitanCRMUI.onDragOver(event)"
             ondragleave="TitanCRMUI.onDragLeave(event)"
             ondrop="TitanCRMUI.onDrop(event, '${col.key}')">
          <div class="t16-kanban-col-head">
            <span style="font-size:12.5px;font-weight:800;">${col.label}</span>
            <div style="display:flex;gap:5px;align-items:center;">
              ${U().badge(String(items.length), col.tono)}
              ${sumaUsd > 0 ? `<span style="font-family:var(--t16-mono);font-size:11px;color:var(--t16-green);">${U().fmtUSD(sumaUsd, 0)}</span>` : ''}
            </div>
          </div>
          <div class="t16-kanban-col-body">${cardsHtml}</div>
        </div>
      `;
    }).join('');

    host.innerHTML = `${kpisHtml}${toolbarHtml}${bulkHtml}<div class="t16-kanban-board">${colsHtml}</div>`;
  }

  function renderLeadCard(l) {
    const id = Number(l.id);
    const sel = STATE.selectedIds.has(id);
    const scoreTono = Number(l.score) >= 8 ? 'ok' : (Number(l.score) >= 6 ? 'cyan' : 'muted');
    const usdVal = l.estado === 'ganado' && Number(l.ganancia_usd) > 0
      ? `🏆 ${U().fmtUSD(l.ganancia_usd, 0)}`
      : (l.presupuesto || (Number(l.presupuesto_num) > 0 ? U().fmtUSD(l.presupuesto_num, 0) : '$?'));
    const aegisB = Number(l.aegis_score) > 0 ? U().badge(`A:${Math.round(l.aegis_score)}`, 'purple') : '';
    const tareasB = Number(l.num_tareas_pend) > 0 ? U().badge(`📋${l.num_tareas_pend}`, 'warn') : '';

    return `
      <div class="t16-lead-card t16-draggable ${sel ? 'selected' : ''}" draggable="true" data-lead-id="${id}"
           ondragstart="TitanCRMUI.onDragStart(event, ${id})" ondragend="TitanCRMUI.onDragEnd(event)">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:6px;">
          <label style="display:inline-flex;align-items:center;gap:5px;font-size:11px;color:var(--t16-muted);cursor:pointer;">
            <input type="checkbox" ${sel ? 'checked' : ''} onchange="TitanCRMUI.toggleSelect(${id}, this.checked)">
            <span>#${id} &bull; ${U().escHtml(l.plataforma || l.fuente)}</span>
          </label>
          <div style="display:flex;gap:4px;">${U().badge(l.score + '/10', scoreTono)}${aegisB}${tareasB}</div>
        </div>
        <div class="t16-lead-title" onclick="TitanCRMUI.openLead360(${id})">${U().escHtml(String(l.titulo || '').slice(0, 96))}</div>
        <div style="display:flex;justify-content:space-between;align-items:center;font-size:11.5px;">
          <span style="font-family:var(--t16-mono);font-weight:700;color:var(--t16-green);">${U().escHtml(usdVal)}</span>
          <span style="color:var(--t16-muted);">${U().escHtml(l.cliente_nombre || l.autor || '')}</span>
        </div>
        ${l.prioridad_tag ? `<div style="font-size:10.5px;color:var(--t16-amber);font-weight:700;">${U().escHtml(l.prioridad_tag)}</div>` : ''}
        <div class="t16-card-actions">
          <button class="t16-btn-xs" onclick="TitanCRMUI.openLead360(${id})">🔍 360</button>
          <button class="t16-btn-xs" onclick="TitanCRMUI.openPitchForLead(${id})">✍️ Pitch</button>
          <button class="t16-btn-xs" onclick="TitanCRMUI.startTimerForLead(${id})">⏱️</button>
          ${l.link ? `<a class="t16-btn-xs" href="${U().escHtml(l.link)}" target="_blank" rel="noopener" style="text-decoration:none;">🔗</a>` : ''}
          ${l.dm_url ? `<a class="t16-btn-xs" href="${U().escHtml(l.dm_url)}" target="_blank" rel="noopener" style="text-decoration:none;">💬</a>` : ''}
        </div>
      </div>
    `;
  }

  // --- Drag & Drop Handlers ---
  function onDragStart(ev, leadId) {
    STATE.dragLeadId = Number(leadId);
    ev.dataTransfer.effectAllowed = 'move';
    ev.dataTransfer.setData('text/plain', String(leadId));
    if (ev.currentTarget) ev.currentTarget.classList.add('t16-dragging');
  }

  function onDragEnd(ev) {
    if (ev.currentTarget) ev.currentTarget.classList.remove('t16-dragging');
    document.querySelectorAll('.t16-drag-over').forEach((el) => el.classList.remove('t16-drag-over'));
  }

  function onDragOver(ev) {
    ev.preventDefault();
    ev.dataTransfer.dropEffect = 'move';
    if (ev.currentTarget) ev.currentTarget.classList.add('t16-drag-over');
  }

  function onDragLeave(ev) {
    if (ev.currentTarget && !ev.currentTarget.contains(ev.relatedTarget)) {
      ev.currentTarget.classList.remove('t16-drag-over');
    }
  }

  async function onDrop(ev, nuevoEstado) {
    ev.preventDefault();
    if (ev.currentTarget) ev.currentTarget.classList.remove('t16-drag-over');
    const lid = Number(ev.dataTransfer.getData('text/plain') || STATE.dragLeadId || 0);
    STATE.dragLeadId = null;
    if (!lid) return;

    const lead = STATE.leads.find((x) => Number(x.id) === lid);
    if (!lead || lead.estado === nuevoEstado) return;

    // Optimistic update para sensacion instantanea
    const prevEstado = lead.estado;
    lead.estado = nuevoEstado;
    renderKanbanView();

    const payload = { estado: nuevoEstado };
    if (nuevoEstado === 'ganado' && Number(lead.ganancia_usd || 0) <= 0 && Number(lead.presupuesto_num || 0) > 0) {
      payload.ganancia_usd = Number(lead.presupuesto_num);
      lead.ganancia_usd = payload.ganancia_usd;
    }

    const res = await API().patch(`/api/v2/leads/${lid}`, payload);
    if (!res?.ok) {
      lead.estado = prevEstado;
      renderKanbanView();
      return;
    }
    U().toast(`Lead #${lid} movido a ${nuevoEstado.toUpperCase()}`, 'ok');
    loadKanban(true);
  }

  function applyLeadFilters() {
    STATE.filtros.q = (document.getElementById('t16CrmSearch')?.value || '').trim();
    STATE.filtros.plataforma = document.getElementById('t16CrmPlat')?.value || '';
    STATE.filtros.tipo_trabajo = document.getElementById('t16CrmTipo')?.value || '';
    STATE.filtros.score_min = Number(document.getElementById('t16CrmScore')?.value || 0);
    loadKanban(false);
  }

  function toggleSelect(id, checked) {
    if (checked) STATE.selectedIds.add(Number(id));
    else STATE.selectedIds.delete(Number(id));
    renderKanbanView();
  }

  function clearSelection() {
    STATE.selectedIds.clear();
    renderKanbanView();
  }

  async function bulkMove(nuevoEstado) {
    const ids = Array.from(STATE.selectedIds);
    if (!ids.length) return;
    const res = await API().post('/api/v2/leads/batch-estado', { lead_ids: ids, estado: nuevoEstado });
    if (res?.ok) {
      STATE.selectedIds.clear();
      U().toast(`${res.actualizados} lead(s) movidos a ${nuevoEstado.toUpperCase()}`, 'ok');
      loadKanban(true);
    }
  }

  function openNewLeadModal() {
    U().openModal({
      title: '➕ Crear Nuevo Lead en CRM',
      html: `
        <div style="display:flex;flex-direction:column;gap:10px;">
          <input id="t16NlTit" class="t16-input" placeholder="Título del proyecto (obligatorio)">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            <select id="t16NlPlat" class="t16-select">
              <option value="Reddit">Reddit</option><option value="Freelancer">Freelancer</option>
              <option value="GitHub">GitHub</option><option value="HackerNews">HackerNews</option>
              <option value="Dev.to">Dev.to</option><option value="Manual">Manual / Directo</option>
            </select>
            <select id="t16NlTipo" class="t16-select">
              <option value="freelance">Freelance</option><option value="bounty">Bounty</option><option value="remoto">Remoto</option>
            </select>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;">
            <input id="t16NlAutor" class="t16-input" placeholder="Autor / handle">
            <input id="t16NlUsd" class="t16-input" type="number" placeholder="Presupuesto USD" value="200">
            <input id="t16NlScore" class="t16-input" type="number" min="1" max="10" value="8" placeholder="Score 1-10">
          </div>
          <input id="t16NlLink" class="t16-input" placeholder="URL de la oferta (opcional)">
          <textarea id="t16NlNotas" class="t16-textarea" placeholder="Notas o detalles clave..."></textarea>
        </div>
      `,
      footerHtml: `
        <button class="t16-pill" onclick="TitanUI.closeModal()">Cancelar</button>
        <button class="t16-pill t16-pill-live" id="t16NlSaveBtn">Crear Lead</button>
      `,
      onOpen: () => {
        document.getElementById('t16NlSaveBtn')?.addEventListener('click', async () => {
          const titulo = (document.getElementById('t16NlTit')?.value || '').trim();
          if (!titulo) return U().toast('El título es obligatorio', 'err');
          const usd = Number(document.getElementById('t16NlUsd')?.value || 0);
          const res = await API().post('/api/v2/leads', {
            titulo,
            plataforma: document.getElementById('t16NlPlat')?.value || 'Manual',
            fuente: document.getElementById('t16NlPlat')?.value || 'Manual',
            tipo_trabajo: document.getElementById('t16NlTipo')?.value || 'freelance',
            autor: (document.getElementById('t16NlAutor')?.value || '').trim(),
            presupuesto_num: usd,
            presupuesto: usd > 0 ? `$${usd} USD` : 'Por definir',
            score: Number(document.getElementById('t16NlScore')?.value || 8),
            link: (document.getElementById('t16NlLink')?.value || '').trim(),
            notas: (document.getElementById('t16NlNotas')?.value || '').trim(),
          });
          if (res?.ok) {
            U().toast(`Lead #${res.lead.id} creado en CRM`, 'ok');
            U().closeModal(true);
            loadKanban(true);
          }
        });
      },
    });
  }

  function openEstancadosDrawer() {
    const html = STATE.estancados.length
      ? STATE.estancados.map((e) => `
          <div class="t16-event-item lvl-warn">
            <div class="t16-event-head">
              <span class="t16-event-topic">#${e.id} [${U().escHtml(e.estado.toUpperCase())}]</span>
              <span class="t16-event-time">${U().fmtUSD(e.presupuesto_num || 0, 0)} &bull; ${e.score}/10</span>
            </div>
            <div style="font-weight:700;font-size:12.5px;">${U().escHtml(e.titulo)}</div>
            <div class="t16-event-body">💡 ${U().escHtml(e.accion_sugerida)}</div>
            <div style="margin-top:6px;display:flex;gap:6px;">
              <button class="t16-btn-xs" onclick="TitanCRMUI.openLead360(${e.id})">🔍 Abrir 360</button>
              <button class="t16-btn-xs" onclick="TitanCRMUI.openPitchForLead(${e.id})">✍️ Pitch A/B</button>
            </div>
          </div>
        `).join('')
      : U().renderEmptyState('Sin leads estancados');
    U().openDrawer({ title: `⏰ Leads Estancados (${STATE.estancados.length})`, html });
  }

  // ==================== 2. VISTA 360 SLIDE-OVER DRAWER ====================
  async function openLead360(leadId) {
    U().openDrawer({ title: `🔍 Lead #${leadId} — Vista 360`, html: '<div class="t16-skeleton" style="height:180px;"></div>', width: 'min(640px, 96vw)' });
    const [r360, rRent] = await Promise.all([
      API().get(`/api/v2/leads/${leadId}/360`),
      API().get(`/api/v2/tiempo/rentabilidad/${leadId}`, { silent: true }),
    ]);
    if (!r360?.ok) return;

    const l = r360.lead;
    const cli = r360.cliente;
    const props = r360.propuestas || [];
    const tareas = r360.tareas || [];
    const facs = r360.facturas || [];
    const rent = rRent?.rentabilidad || null;

    const propsHtml = props.length
      ? props.map((p) => `
          <div class="t16-event-item lvl-${p.estado_respuesta === 'ganada' ? 'ok' : 'info'}">
            <div class="t16-event-head">
              <span class="t16-event-topic">Prop #${p.id} [Var ${U().escHtml(p.variante)}] &bull; ${U().fmtUSD(p.precio_cotizado_usd, 0)}</span>
              ${U().badge(p.estado_respuesta, p.estado_respuesta === 'ganada' ? 'ok' : (p.estado_respuesta === 'rechazada' ? 'err' : 'cyan'))}
            </div>
            <div class="t16-event-body">${U().escHtml(String(p.texto_pitch || '').slice(0, 150))}...</div>
            <div style="display:flex;gap:5px;flex-wrap:wrap;margin-top:6px;">
              ${['respondida', 'entrevista', 'ganada', 'rechazada'].map((st) =>
                `<button class="t16-btn-xs" onclick="TitanCRMUI.markProposalResult(${p.id}, '${st}', ${l.id})">${st}</button>`
              ).join('')}
            </div>
          </div>
        `).join('')
      : '<div style="font-size:12px;color:var(--t16-muted);">Sin propuestas registradas aún.</div>';

    const tareasHtml = tareas.length
      ? tareas.map((t) => `
          <div class="t16-agenda-row ${t.vencida ? 'vencida' : ''}" style="margin-bottom:6px;padding:7px 10px;">
            <span style="font-size:12px;">${t.estado === 'completada' ? '✅' : '⏳'} <b>${U().escHtml(t.titulo)}</b> ${U().badge(t.prioridad, t.prioridad === 'critica' ? 'err' : 'muted')}</span>
            ${t.estado !== 'completada' ? `<button class="t16-btn-xs" onclick="TitanCRMUI.completeTask(${t.id}, ${l.id})">✓ Hecha</button>` : ''}
          </div>
        `).join('')
      : '<div style="font-size:12px;color:var(--t16-muted);">Sin tareas vinculadas.</div>';

    const bodyHtml = `
      <div class="t16-card-box" style="margin-bottom:12px;">
        <div style="display:flex;justify-content:space-between;gap:8px;align-items:flex-start;">
          <div>
            <div style="font-size:14px;font-weight:800;color:var(--t16-text-0);">${U().escHtml(l.titulo)}</div>
            <div style="font-size:12px;color:var(--t16-muted);margin-top:4px;">${U().escHtml(l.plataforma)} &bull; ${U().escHtml(l.tipo_trabajo)} &bull; ${U().escHtml(l.presupuesto)} &bull; Score ${l.score}/10</div>
          </div>
          ${U().badge(l.estado.toUpperCase(), l.estado === 'ganado' ? 'ok' : 'cyan')}
        </div>
        ${cli ? `<div style="margin-top:10px;padding:8px 10px;border-radius:8px;background:rgba(34,211,238,0.08);border:1px solid rgba(34,211,238,0.25);display:flex;justify-content:space-between;align-items:center;font-size:12px;">
          <span>👤 <b>${U().escHtml(cli.nombre)}</b> (${U().escHtml(cli.tier)} &bull; Rep ${cli.reputacion_score} &bull; LTV ${U().fmtUSD(cli.total_facturado_usd, 0)})</span>
          <button class="t16-btn-xs" onclick="TitanCRMUI.openClientTimeline(${cli.id})">Timeline &rarr;</button>
        </div>` : ''}
        ${rent && rent.horas_totales > 0 ? `<div style="margin-top:8px;font-size:12px;color:var(--t16-text-1);">
          ⏱️ Invertido: <b>${rent.horas_totales}h</b> (${rent.formato_hms}) &bull; Tarifa efectiva: <b style="color:var(--t16-green);">${U().fmtUSD(rent.tarifa_efectiva_usd_hr)}/hr</b> (${U().escHtml(rent.veredicto)})
        </div>` : ''}
      </div>

      <div class="t16-card-box" style="margin-bottom:12px;">
        <div style="font-size:12px;font-weight:800;margin-bottom:8px;">Actualizar Estado, Ganancia &amp; Notas</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px;">
          <select id="t16L360Est" class="t16-select">
            ${ESTADOS_KANBAN.map((e) => `<option value="${e.key}" ${l.estado === e.key ? 'selected' : ''}>${e.label}</option>`).join('')}
          </select>
          <input id="t16L360Gan" class="t16-input" type="number" step="1" value="${Number(l.ganancia_usd || 0)}" placeholder="Ganancia USD">
        </div>
        <textarea id="t16L360Notas" class="t16-textarea" style="min-height:68px;" placeholder="Notas internas del cliente...">${U().escHtml(l.notas || '')}</textarea>
        <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap;">
          <button class="t16-pill t16-pill-live" onclick="TitanCRMUI.saveLead360(${l.id})">💾 Guardar</button>
          <button class="t16-pill" onclick="TitanCRMUI.openPitchForLead(${l.id})">✍️ Pitch A/B</button>
          <button class="t16-pill" onclick="TitanCRMUI.startTimerForLead(${l.id})">⏱️ Iniciar Timer</button>
          <button class="t16-pill" onclick="TitanCRMUI.quickInvoiceLead(${l.id})">🧾 Emitir Factura</button>
        </div>
      </div>

      <div class="t16-card-box" style="margin-bottom:12px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
          <span style="font-size:12.5px;font-weight:800;">📨 Propuestas A/B (${props.length})</span>
        </div>
        ${propsHtml}
      </div>

      <div class="t16-card-box" style="margin-bottom:12px;">
        <div style="font-size:12.5px;font-weight:800;margin-bottom:8px;">📋 Tareas (${tareas.length})</div>
        ${tareasHtml}
        <div style="display:flex;gap:6px;margin-top:8px;">
          <input id="t16L360NewTask" class="t16-input" style="flex:1;" placeholder="Nueva tarea para este lead...">
          <button class="t16-pill" onclick="TitanCRMUI.quickTaskForLead(${l.id})">+ Crear</button>
        </div>
      </div>

      ${facs.length ? `<div class="t16-card-box"><div style="font-size:12.5px;font-weight:800;margin-bottom:6px;">🧾 Facturas (${facs.length})</div>
        ${facs.map((f) => `<div style="font-size:12px;margin-bottom:4px;"><b>${U().escHtml(f.numero)}</b> &bull; ${U().fmtUSD(f.monto_neto_usd)} &bull; ${U().badge(f.estado_pago, f.estado_pago === 'pagada' ? 'ok' : 'warn')}</div>`).join('')}
      </div>` : ''}
    `;

    U().openDrawer({
      title: `🔍 Lead #${l.id} — Vista 360`,
      html: bodyHtml,
      width: 'min(640px, 96vw)',
      footerHtml: `<button class="t16-pill t16-pill-err" onclick="TitanCRMUI.deleteLead(${l.id})">🗑️ Eliminar</button><button class="t16-pill" onclick="TitanUI.closeDrawer()">Cerrar</button>`,
    });
  }

  async function saveLead360(leadId) {
    const res = await API().patch(`/api/v2/leads/${leadId}`, {
      estado: document.getElementById('t16L360Est')?.value,
      ganancia_usd: Number(document.getElementById('t16L360Gan')?.value || 0),
      notas: document.getElementById('t16L360Notas')?.value || '',
    });
    if (res?.ok) {
      U().toast(`Lead #${leadId} actualizado`, 'ok');
      openLead360(leadId);
      loadKanban(true);
    }
  }

  async function deleteLead(leadId) {
    const ok = await U().confirmDialog('Eliminar Lead', `¿Eliminar permanentemente el Lead #${leadId}?`, 'Eliminar');
    if (!ok) return;
    const res = await API().del(`/api/v2/leads/${leadId}`);
    if (res?.ok) {
      U().closeDrawer();
      U().toast(`Lead #${leadId} eliminado`, 'ok');
      loadKanban(true);
    }
  }

  async function markProposalResult(propId, estado, leadId) {
    const res = await API().patch(`/api/v2/propuestas/${propId}/respuesta`, { estado_respuesta: estado });
    if (res?.ok) {
      U().toast(`Propuesta #${propId} -> ${estado.toUpperCase()}`, 'ok');
      if (leadId) openLead360(leadId);
      loadKanban(true);
    }
  }

  async function quickTaskForLead(leadId) {
    const inp = document.getElementById('t16L360NewTask');
    const tit = (inp?.value || '').trim();
    if (!tit) return;
    const res = await API().post('/api/v2/tareas', { titulo: tit, lead_id: leadId, prioridad: 'alta', vence_en_horas: 24 });
    if (res?.ok) {
      U().toast('Tarea creada (+24h)', 'ok');
      openLead360(leadId);
    }
  }

  async function startTimerForLead(leadId) {
    const res = await API().post('/api/v2/tiempo/iniciar', { lead_id: leadId });
    if (res?.ok) {
      U().toast(`⏱️ Cronómetro iniciado en Lead #${leadId}`, 'ok');
      API().refreshOverview();
    }
  }

  async function quickInvoiceLead(leadId) {
    const r = await API().get(`/api/v2/leads/${leadId}`);
    if (!r?.ok) return;
    const l = r.lead;
    const monto = Number(l.ganancia_usd || l.presupuesto_num || 150);
    const res = await API().post('/api/v2/facturas', {
      cliente_nombre: l.cliente_nombre || l.autor || 'Client',
      concepto: String(l.titulo || `Project #${leadId}`).slice(0, 140),
      monto_bruto_usd: monto > 0 ? monto : 150,
      pasarela: 'binance',
      lead_id: leadId,
    });
    if (res?.ok) {
      U().toast(`🧾 Factura ${res.factura.numero} emitida (${U().fmtUSD(res.factura.monto_bruto_usd)})`, 'ok');
      openLead360(leadId);
    }
  }

  function openPitchForLead(leadId) {
    U().closeDrawer();
    STATE.subtab = 'pitch';
    renderShellTabs();
    if (global.TitanPitchUI) global.TitanPitchUI.render('t16CrmBody', leadId);
  }

  // ==================== 3. CARTERA DE CLIENTES (LTV, REPUTACION, MERGE, TIMELINE) ====================
  async function loadClientes(silent = false) {
    const host = document.getElementById('t16CrmBody');
    if (!host) return;
    const f = STATE.cliFiltros;
    const qs = new URLSearchParams({ sort: f.sort || 'ltv', limit: '100' });
    if (f.q) qs.set('q', f.q);
    if (f.solo_recurrentes) qs.set('solo_recurrentes', 'true');
    const r = await API().get(`/api/v2/clientes?${qs.toString()}`, { silent });
    if (r?.ok) STATE.clientes = r.items || [];
    renderClientesView();
  }

  function renderClientesView() {
    const host = document.getElementById('t16CrmBody');
    if (!host) return;
    const f = STATE.cliFiltros;
    const totLtv = STATE.clientes.reduce((a, c) => a + Number(c.total_facturado_usd || 0), 0);
    const vips = STATE.clientes.filter((c) => c.tier === 'VIP' || c.es_recurrente).length;

    const cards = STATE.clientes.length
      ? STATE.clientes.map((c) => `
          <div class="t16-card-box">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
              <div>
                <div style="font-weight:800;font-size:14px;color:var(--t16-text-0);">${U().escHtml(c.nombre)}</div>
                <div style="font-size:11.5px;color:var(--t16-muted);">${U().escHtml(c.plataforma_origen)} ${c.handle ? '&bull; @' + U().escHtml(c.handle) : ''} ${c.email ? '&bull; ' + U().escHtml(c.email) : ''}</div>
              </div>
              ${U().badge(c.tier, c.tier === 'VIP' ? 'ok' : (c.tier === 'Activo' ? 'cyan' : 'muted'))}
            </div>
            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:12px 0;text-align:center;">
              <div style="background:rgba(5,8,17,0.6);padding:7px;border-radius:8px;"><div style="font-size:10px;color:var(--t16-muted);">LTV</div><b style="font-family:var(--t16-mono);color:var(--t16-green);">${U().fmtUSD(c.total_facturado_usd, 0)}</b></div>
              <div style="background:rgba(5,8,17,0.6);padding:7px;border-radius:8px;"><div style="font-size:10px;color:var(--t16-muted);">REPUTACIÓN</div><b style="font-family:var(--t16-mono);color:var(--t16-cyan);">${c.reputacion_score}/100</b></div>
              <div style="background:rgba(5,8,17,0.6);padding:7px;border-radius:8px;"><div style="font-size:10px;color:var(--t16-muted);">GANADOS</div><b style="font-family:var(--t16-mono);">${c.proyectos_ganados}/${c.leads_totales}</b></div>
            </div>
            <div style="display:flex;gap:6px;flex-wrap:wrap;">
              <button class="t16-btn-xs" onclick="TitanCRMUI.openClientTimeline(${c.id})">📜 Timeline</button>
              <button class="t16-btn-xs" onclick="TitanCRMUI.recalcClient(${c.id})">🔄 Recalcular</button>
              <button class="t16-btn-xs" onclick="TitanCRMUI.openMergeModal(${c.id})">🔀 Fusionar</button>
            </div>
          </div>
        `).join('')
      : U().renderEmptyState('Sin clientes registrados', 'Usa "Vincular Huérfanos" para importar clientes desde tus leads existentes.');

    host.innerHTML = `
      <div class="t16-kpi-grid">
        <div class="t16-kpi"><span class="t16-kpi-lbl">Clientes en Cartera</span><span class="t16-kpi-val">${STATE.clientes.length}</span><span class="t16-kpi-sub">VIP / Recurrentes: ${vips}</span></div>
        <div class="t16-kpi"><span class="t16-kpi-lbl">LTV Acumulado</span><span class="t16-kpi-val" style="color:var(--t16-green);">${U().fmtUSD(totLtv, 0)}</span><span class="t16-kpi-sub">Valor histórico facturado</span></div>
      </div>
      <div class="t16-toolbar">
        <input id="t16CliQ" class="t16-input" placeholder="🔍 Buscar cliente, handle o email..." value="${U().escHtml(f.q)}" style="flex:1;min-width:180px;" onkeydown="if(event.key==='Enter')TitanCRMUI.applyCliFilters()">
        <select id="t16CliSort" class="t16-select" onchange="TitanCRMUI.applyCliFilters()">
          <option value="ltv" ${f.sort === 'ltv' ? 'selected' : ''}>Orden: Mayor LTV</option>
          <option value="reputacion" ${f.sort === 'reputacion' ? 'selected' : ''}>Orden: Reputación</option>
          <option value="proyectos" ${f.sort === 'proyectos' ? 'selected' : ''}>Orden: Proyectos</option>
          <option value="reciente" ${f.sort === 'reciente' ? 'selected' : ''}>Orden: Reciente</option>
        </select>
        <label style="font-size:12px;display:inline-flex;align-items:center;gap:5px;"><input id="t16CliRec" type="checkbox" ${f.solo_recurrentes ? 'checked' : ''} onchange="TitanCRMUI.applyCliFilters()"> Solo VIP/Rec</label>
        <button class="t16-pill" onclick="TitanCRMUI.applyCliFilters()">Filtrar</button>
        <button class="t16-pill" onclick="TitanCRMUI.linkOrphanLeads()">🔗 Vincular Huérfanos</button>
        <button class="t16-pill t16-pill-live" onclick="TitanCRMUI.openNewClientModal()">+ Cliente</button>
      </div>
      <div class="t16-grid-cards">${cards}</div>
    `;
  }

  function applyCliFilters() {
    STATE.cliFiltros.q = (document.getElementById('t16CliQ')?.value || '').trim();
    STATE.cliFiltros.sort = document.getElementById('t16CliSort')?.value || 'ltv';
    STATE.cliFiltros.solo_recurrentes = !!document.getElementById('t16CliRec')?.checked;
    loadClientes(false);
  }

  async function linkOrphanLeads() {
    const r = await API().post('/api/v2/clientes/vincular-huerfanos', { limite: 500 });
    if (r?.ok) {
      U().toast(`Vinculados ${r.leads_vinculados} leads en ${r.clientes_actualizados} clientes`, 'ok');
      loadClientes(true);
    }
  }

  async function recalcClient(cid) {
    const r = await API().post(`/api/v2/clientes/${cid}/recalcular`, {});
    if (r?.ok) {
      U().toast(`LTV recalculado: ${U().fmtUSD(r.cliente.total_facturado_usd)} (Rep ${r.cliente.reputacion_score})`, 'ok');
      loadClientes(true);
    }
  }

  async function openClientTimeline(cid) {
    U().openDrawer({ title: `📜 Cliente #${cid} — Timeline`, html: '<div class="t16-skeleton" style="height:140px;"></div>' });
    const [rCli, rTl] = await Promise.all([
      API().get(`/api/v2/clientes/${cid}`),
      API().get(`/api/v2/clientes/${cid}/timeline?limit=40`),
    ]);
    if (!rCli?.ok) return;
    const c = rCli.cliente;
    const evs = rTl?.timeline || [];
    const html = `
      <div class="t16-card-box" style="margin-bottom:12px;">
        <div style="font-size:15px;font-weight:800;">${U().escHtml(c.nombre)} ${U().badge(c.tier, c.tier === 'VIP' ? 'ok' : 'cyan')}</div>
        <div style="font-size:12px;color:var(--t16-muted);margin-top:4px;">LTV: <b style="color:var(--t16-green);">${U().fmtUSD(c.total_facturado_usd)}</b> &bull; Rep: <b>${c.reputacion_score}/100</b> &bull; Ganados: <b>${c.proyectos_ganados}</b></div>
      </div>
      ${evs.length ? evs.map((e) => `
        <div class="t16-event-item lvl-${e.tipo === 'factura' ? 'ok' : 'info'}">
          <div class="t16-event-head">
            <span class="t16-event-topic">${U().escHtml(e.tipo.toUpperCase())}</span>
            <span class="t16-event-time">${U().escHtml(String(e.ts || '').slice(0, 16))}</span>
          </div>
          <div class="t16-event-body">${U().escHtml(e.titulo)}</div>
        </div>
      `).join('') : U().renderEmptyState('Sin actividad registrada aún')}
    `;
    U().openDrawer({ title: `📜 Timeline — ${c.nombre}`, html });
  }

  function openNewClientModal() {
    U().openModal({
      title: '👤 Nuevo Cliente en Cartera',
      html: `
        <div style="display:flex;flex-direction:column;gap:9px;">
          <input id="t16NcNom" class="t16-input" placeholder="Nombre o empresa (obligatorio)">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            <input id="t16NcHandle" class="t16-input" placeholder="Handle (ej. u/alex)">
            <input id="t16NcPlat" class="t16-input" placeholder="Plataforma (Reddit, Freelancer...)" value="Reddit">
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            <input id="t16NcEmail" class="t16-input" placeholder="Email de contacto">
            <input id="t16NcPais" class="t16-input" placeholder="País (ej. USA, UK, CO)">
          </div>
          <textarea id="t16NcNotas" class="t16-textarea" placeholder="Notas, preferencias de pago..."></textarea>
        </div>
      `,
      footerHtml: `<button class="t16-pill" onclick="TitanUI.closeModal()">Cancelar</button><button class="t16-pill t16-pill-live" id="t16NcSave">Crear Cliente</button>`,
      onOpen: () => {
        document.getElementById('t16NcSave')?.addEventListener('click', async () => {
          const nombre = (document.getElementById('t16NcNom')?.value || '').trim();
          if (!nombre) return U().toast('El nombre es obligatorio', 'err');
          const r = await API().post('/api/v2/clientes', {
            nombre,
            handle: document.getElementById('t16NcHandle')?.value || '',
            plataforma_origen: document.getElementById('t16NcPlat')?.value || 'General',
            email: document.getElementById('t16NcEmail')?.value || '',
            pais: document.getElementById('t16NcPais')?.value || '',
            notas: document.getElementById('t16NcNotas')?.value || '',
          });
          if (r?.ok) {
            U().toast(`Cliente '${nombre}' creado`, 'ok');
            U().closeModal(true);
            loadClientes(true);
          }
        });
      },
    });
  }

  function openMergeModal(origenId) {
    const otros = STATE.clientes.filter((c) => Number(c.id) !== Number(origenId));
    if (!otros.length) return U().toast('Necesitas al menos 2 clientes para fusionar', 'warn');
    const orig = STATE.clientes.find((c) => Number(c.id) === Number(origenId));
    U().openModal({
      title: `🔀 Fusionar Cliente #${origenId}`,
      html: `
        <p style="font-size:12.5px;color:var(--t16-text-1);margin:0 0 10px 0;">
          Todos los leads, propuestas, tareas y facturas de <b>${U().escHtml(orig?.nombre || '')}</b> se moverán al cliente destino elegido:
        </p>
        <select id="t16MergeDest" class="t16-select" style="width:100%;">
          ${otros.map((c) => `<option value="${c.id}">#${c.id} — ${U().escHtml(c.nombre)} (${U().fmtUSD(c.total_facturado_usd, 0)})</option>`).join('')}
        </select>
      `,
      footerHtml: `<button class="t16-pill" onclick="TitanUI.closeModal()">Cancelar</button><button class="t16-pill t16-pill-warn" id="t16MergeGo">Confirmar Fusión</button>`,
      onOpen: () => {
        document.getElementById('t16MergeGo')?.addEventListener('click', async () => {
          const destId = Number(document.getElementById('t16MergeDest')?.value || 0);
          const r = await API().post('/api/v2/clientes/fusionar', { origen_id: origenId, destino_id: destId });
          if (r?.ok) {
            U().toast(`Clientes fusionados en #${destId} (LTV ${U().fmtUSD(r.cliente.total_facturado_usd)})`, 'ok');
            U().closeModal(true);
            loadClientes(true);
          }
        });
      },
    });
  }

  // ==================== 4. AGENDA & TAREAS CRM ====================
  async function loadAgenda(silent = false) {
    const host = document.getElementById('t16CrmBody');
    if (!host) return;
    const tf = STATE.tareaFiltros;
    const qs = new URLSearchParams({ limit: '100' });
    if (tf.solo_pendientes) qs.set('solo_pendientes', 'true');
    if (tf.solo_vencidas) qs.set('solo_vencidas', 'true');
    if (tf.prioridad) qs.set('prioridad', tf.prioridad);

    const [rAg, rTa] = await Promise.all([
      API().get('/api/v2/agenda', { silent }),
      API().get(`/api/v2/tareas?${qs.toString()}`, { silent }),
    ]);
    if (rAg?.ok) STATE.agendaResumen = rAg.agenda;
    if (rTa?.ok) STATE.tareas = rTa.items || [];
    renderAgendaView();
  }

  function renderAgendaView() {
    const host = document.getElementById('t16CrmBody');
    if (!host) return;
    const ag = STATE.agendaResumen || {};
    const tf = STATE.tareaFiltros;

    const rows = STATE.tareas.length
      ? STATE.tareas.map((t) => `
          <div class="t16-agenda-row ${t.vencida ? 'vencida' : ''}">
            <div style="min-width:0;flex:1;">
              <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
                ${U().badge(t.prioridad.toUpperCase(), t.prioridad === 'critica' ? 'err' : (t.prioridad === 'alta' ? 'warn' : 'cyan'))}
                <b style="font-size:13px;color:var(--t16-text-0);">${U().escHtml(t.titulo)}</b>
                ${t.vencida ? U().badge('VENCIDA', 'err') : ''}
              </div>
              <div style="font-size:11.5px;color:var(--t16-muted);margin-top:4px;">
                ${t.lead_titulo ? `Lead: ${U().escHtml(t.lead_titulo.slice(0, 56))} &bull; ` : ''}
                ${t.vence_ts ? `Vence: ${U().escHtml(String(t.vence_ts).slice(0, 16))}` : 'Sin vencimiento'}
                ${t.descripcion ? ` &bull; ${U().escHtml(t.descripcion.slice(0, 80))}` : ''}
              </div>
            </div>
            <div style="display:flex;gap:6px;flex-wrap:wrap;">
              ${t.lead_id ? `<button class="t16-btn-xs" onclick="TitanCRMUI.openLead360(${t.lead_id})">🔍 Lead</button>` : ''}
              ${t.estado !== 'completada' ? `<button class="t16-btn-xs" style="border-color:var(--t16-green);color:#4ade80;" onclick="TitanCRMUI.completeTask(${t.id})">✅ Hecha</button>` : ''}
              ${t.estado !== 'completada' ? `<button class="t16-btn-xs" onclick="TitanCRMUI.snoozeTask(${t.id}, 24)">⏰ +24h</button>` : ''}
              <button class="t16-btn-xs" onclick="TitanCRMUI.deleteTask(${t.id})">🗑️</button>
            </div>
          </div>
        `).join('')
      : U().renderEmptyState('🎉 Agenda despejada', 'Crea una tarea rápida arriba para mantener seguimiento.');

    host.innerHTML = `
      <div class="t16-kpi-grid">
        <div class="t16-kpi"><span class="t16-kpi-lbl">Vencidas</span><span class="t16-kpi-val" style="color:${ag.vencidas ? 'var(--t16-red)' : 'var(--t16-green)'};">${ag.vencidas || 0}</span></div>
        <div class="t16-kpi"><span class="t16-kpi-lbl">Próximas 24h</span><span class="t16-kpi-val" style="color:var(--t16-amber);">${ag.proximas_24h || 0}</span></div>
        <div class="t16-kpi"><span class="t16-kpi-lbl">Pendientes Totales</span><span class="t16-kpi-val">${ag.pendientes_totales || 0}</span></div>
        <div class="t16-kpi"><span class="t16-kpi-lbl">Completadas (7d)</span><span class="t16-kpi-val" style="color:var(--t16-green);">${ag.completadas_7d || 0}</span></div>
      </div>
      <div class="t16-toolbar">
        <input id="t16TaNewTit" class="t16-input" placeholder="+ Nueva tarea rápida (Enter)..." style="flex:1;min-width:200px;" onkeydown="if(event.key==='Enter')TitanCRMUI.createQuickTask()">
        <select id="t16TaNewPrio" class="t16-select">
          <option value="critica">🔴 Crítica</option><option value="alta" selected>🟠 Alta</option>
          <option value="media">🔵 Media</option><option value="baja">⚪ Baja</option>
        </select>
        <input id="t16TaNewHrs" class="t16-input" type="number" value="24" min="1" style="width:76px;" title="Horas hasta vencimiento">
        <button class="t16-pill t16-pill-live" onclick="TitanCRMUI.createQuickTask()">+ Agregar</button>
        <label style="font-size:12px;display:inline-flex;align-items:center;gap:4px;margin-left:auto;">
          <input type="checkbox" ${tf.solo_pendientes ? 'checked' : ''} onchange="TitanCRMUI.toggleTaskFilter('solo_pendientes', this.checked)"> Solo pendientes
        </label>
        <label style="font-size:12px;display:inline-flex;align-items:center;gap:4px;">
          <input type="checkbox" ${tf.solo_vencidas ? 'checked' : ''} onchange="TitanCRMUI.toggleTaskFilter('solo_vencidas', this.checked)"> Solo vencidas
        </label>
      </div>
      <div>${rows}</div>
    `;
  }

  function toggleTaskFilter(key, val) {
    STATE.tareaFiltros[key] = !!val;
    loadAgenda(false);
  }

  async function createQuickTask() {
    const tit = (document.getElementById('t16TaNewTit')?.value || '').trim();
    if (!tit) return U().toast('Escribe un título para la tarea', 'err');
    const r = await API().post('/api/v2/tareas', {
      titulo: tit,
      prioridad: document.getElementById('t16TaNewPrio')?.value || 'alta',
      vence_en_horas: Number(document.getElementById('t16TaNewHrs')?.value || 24),
    });
    if (r?.ok) {
      U().toast(`Tarea #${r.tarea.id} creada`, 'ok');
      loadAgenda(true);
    }
  }

  async function completeTask(tid, refreshLeadId = null) {
    const r = await API().post(`/api/v2/tareas/${tid}/completar`, {});
    if (r?.ok) {
      U().toast(`✅ Tarea #${tid} completada`, 'ok');
      if (refreshLeadId) openLead360(refreshLeadId);
      if (STATE.subtab === 'agenda') loadAgenda(true);
    }
  }

  async function snoozeTask(tid, horas = 24) {
    const r = await API().post(`/api/v2/tareas/${tid}/posponer`, { horas });
    if (r?.ok) {
      U().toast(`⏰ Tarea #${tid} pospuesta +${horas}h`, 'ok');
      loadAgenda(true);
    }
  }

  async function deleteTask(tid) {
    const r = await API().del(`/api/v2/tareas/${tid}`);
    if (r?.ok) {
      U().toast(`Tarea #${tid} eliminada`, 'ok');
      loadAgenda(true);
    }
  }

  global.TitanCRMUI = {
    init,
    switchSubtab,
    refreshCurrentSubtab,
    applyLeadFilters,
    onDragStart,
    onDragEnd,
    onDragOver,
    onDragLeave,
    onDrop,
    toggleSelect,
    clearSelection,
    bulkMove,
    openNewLeadModal,
    openEstancadosDrawer,
    openLead360,
    saveLead360,
    deleteLead,
    markProposalResult,
    quickTaskForLead,
    startTimerForLead,
    quickInvoiceLead,
    openPitchForLead,
    applyCliFilters,
    linkOrphanLeads,
    recalcClient,
    openClientTimeline,
    openNewClientModal,
    openMergeModal,
    toggleTaskFilter,
    createQuickTask,
    completeTask,
    snoozeTask,
    deleteTask,
  };
})(window);