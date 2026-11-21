// ==================== ZERO-TOUCH TITAN-OS v16.0 — FINANZAS PRO, CAJA, FACTURAS & PASARELAS ====================
(function (global) {
  'use strict';

  const FSTATE = {
    subtab: 'resumen', // resumen | facturas | caja | pasarelas | timer
    resumen: null,
    cashflowMeses: 6,
    cashflowSerie: [],
    facturas: [],
    movimientos: [],
    facFiltroEstado: '',
    movFiltroTipo: '',
    simMonto: 350,
    simTrm: 4200,
    simComparativa: [],
    sseWired: false,
    debounceTimer: null,
  };

  const U = () => global.TitanUI;
  const API = () => global.TitanAPI;

  function getTrm() {
    return Number(global.TitanStore?.get('prefs.trm_cop') || FSTATE.simTrm || 4200);
  }

  function wireSSEOnce() {
    if (FSTATE.sseWired || !global.TitanSSE) return;
    FSTATE.sseWired = true;
    const onEvt = () => {
      const sec = document.getElementById('t_finanzas_v16');
      if (!sec || !sec.classList.contains('active')) return;
      if (FSTATE.debounceTimer) clearTimeout(FSTATE.debounceTimer);
      FSTATE.debounceTimer = setTimeout(() => refreshSubtab(true), 450);
    };
    global.TitanSSE.on('finanzas.*', onEvt);
    global.TitanSSE.on('tiempo.*', () => {
      const sec = document.getElementById('t_finanzas_v16');
      if (sec && sec.classList.contains('active') && FSTATE.subtab === 'timer' && global.TitanTimerUI) {
        global.TitanTimerUI.refresh(true);
      }
    });
  }

  async function init(initialSubtab = null) {
    wireSSEOnce();
    FSTATE.simTrm = getTrm();
    if (initialSubtab) FSTATE.subtab = initialSubtab;
    renderTabs();
    await refreshSubtab(false);
  }

  function renderTabs() {
    const bar = document.getElementById('t16FinSubtabs');
    if (!bar) return;
    const tabs = [
      { id: 'resumen', label: '📊 Cashflow & Meta' },
      { id: 'facturas', label: '🧾 Facturación DB' },
      { id: 'caja', label: '📒 Libro Mayor Caja' },
      { id: 'pasarelas', label: '💳 Pasarelas & Gross-Up' },
      { id: 'timer', label: '⏱️ Time Tracker Pro' },
    ];
    bar.innerHTML = tabs.map((t) =>
      `<button class="t16-subtab ${FSTATE.subtab === t.id ? 'active' : ''}" onclick="TitanFinUI.switchSubtab('${t.id}')">${t.label}</button>`
    ).join('');
  }

  async function switchSubtab(id) {
    FSTATE.subtab = id;
    renderTabs();
    await refreshSubtab(false);
  }

  async function refreshSubtab(silent = false) {
    if (FSTATE.subtab === 'resumen') await loadResumen(silent);
    else if (FSTATE.subtab === 'facturas') await loadFacturas(silent);
    else if (FSTATE.subtab === 'caja') await loadCaja(silent);
    else if (FSTATE.subtab === 'pasarelas') await loadPasarelas(silent);
    else if (FSTATE.subtab === 'timer' && global.TitanTimerUI) await global.TitanTimerUI.render('t16FinBody', silent);
  }

  // ==================== 1. RESUMEN EJECUTIVO & CASHFLOW SVG ====================
  async function loadResumen(silent = false) {
    const host = document.getElementById('t16FinBody');
    if (!host) return;
    if (!silent && !FSTATE.resumen) host.innerHTML = '<div class="t16-skeleton" style="height:240px;"></div>';

    const trm = getTrm();
    const [rRes, rCf] = await Promise.all([
      API().get(`/api/v2/finanzas/resumen?trm_cop=${encodeURIComponent(trm)}`, { silent }),
      API().get(`/api/v2/finanzas/cashflow?meses=${FSTATE.cashflowMeses}`, { silent }),
    ]);
    if (rRes?.ok) FSTATE.resumen = rRes.resumen;
    if (rCf?.ok) FSTATE.cashflowSerie = rCf.serie || [];
    renderResumenView();
  }

  function renderResumenView() {
    const host = document.getElementById('t16FinBody');
    if (!host) return;
    const f = FSTATE.resumen || {};
    const serie = FSTATE.cashflowSerie.length ? FSTATE.cashflowSerie : (f.cashflow_6m || []);
    const pctMeta = Math.min(100, Number(f.progreso_meta_pct || 0));

    const chartCf = U().svgBarChart(
      serie.map((m) => ({
        label: String(m.mes || '').slice(2),
        a: Number(m.ingresos_usd || 0),
        b: Number(m.gastos_usd || 0),
      })),
      { width: 580, height: 195, colorPos: '#10b981', colorNeg: '#ef4444' }
    );

    const pasarelas = f.por_pasarela || [];
    const colores = ['#10b981', '#22d3ee', '#3b82f6', '#a855f7', '#f59e0b', '#ef4444'];
    const donutPas = U().svgDonut(
      pasarelas.map((p, i) => ({
        label: p.pasarela,
        value: Number(p.neto_usd || 0),
        color: colores[i % colores.length],
      })),
      { size: 132, stroke: 16, centerText: `${pasarelas.length} vías` }
    );

    const pasLegend = pasarelas.length
      ? pasarelas.map((p, i) => `
          <div class="t16-stat-line">
            <span><span class="t16-dot" style="background:${colores[i % colores.length]};margin-right:6px;"></span><b>${U().escHtml(p.pasarela)}</b> (${p.facturas} fac.)</span>
            <span class="t16-num" style="color:var(--t16-green);">${U().fmtUSD(p.neto_usd)} <small style="color:var(--t16-muted);">(-${U().fmtUSD(p.comision_usd)})</small></span>
          </div>
        `).join('')
      : U().renderEmptyState('Sin facturas cobradas aún');

    const gastosCat = (f.gastos_por_categoria || []).length
      ? f.gastos_por_categoria.map((g) => `
          <div class="t16-stat-line">
            <span>${U().escHtml(g.categoria)}</span>
            <span class="t16-num" style="color:var(--t16-red);">-${U().fmtUSD(g.usd)}</span>
          </div>
        `).join('')
      : U().renderEmptyState('Sin gastos registrados');

    host.innerHTML = `
      <div class="t16-kpi-grid">
        <div class="t16-kpi">
          <span class="t16-kpi-lbl">Ingresos Mes (${U().escHtml(f.mes_actual || '')})</span>
          <span class="t16-kpi-val" style="color:var(--t16-green);">${U().fmtUSD(f.ingresos_mes_usd || 0)}</span>
          <span class="t16-kpi-sub">${U().fmtCOP(f.ingresos_mes_cop || 0)} &bull; Neto mes: ${U().fmtUSD(f.neto_mes_usd || 0)}</span>
        </div>
        <div class="t16-kpi">
          <span class="t16-kpi-lbl">Balance en Caja</span>
          <span class="t16-kpi-val" style="color:var(--t16-cyan);">${U().fmtUSD(f.balance_caja_usd || 0)}</span>
          <span class="t16-kpi-sub">${U().fmtCOP(f.balance_caja_cop || 0)} &bull; Retiros: ${U().fmtUSD(f.retiros_totales_usd || 0)}</span>
        </div>
        <div class="t16-kpi">
          <span class="t16-kpi-lbl">Por Cobrar / Comisiones</span>
          <span class="t16-kpi-val" style="color:var(--t16-amber);">${U().fmtUSD(f.cuentas_por_cobrar_usd || 0)}</span>
          <span class="t16-kpi-sub">${f.facturas_pendientes || 0} pendiente(s) &bull; Fuga fees: ${U().fmtUSD(f.comisiones_perdidas_usd || 0)}</span>
        </div>
        <div class="t16-kpi">
          <span class="t16-kpi-lbl">Tarifa Real 30d &amp; Reserva</span>
          <span class="t16-kpi-val">${U().fmtUSD(f.tarifa_efectiva_mes_usd_hr || 0)}/hr</span>
          <span class="t16-kpi-sub">${f.horas_trabajadas_30d || 0}h reg. &bull; Reserva (${f.reserva_pct || 15}%): ${U().fmtUSD(f.reserva_sugerida_mes_usd || 0)}</span>
        </div>
      </div>

      <div class="t16-card-box" style="margin-bottom:14px;">
        <div class="t16-meta-bar">
          <span>🎯 <b>Progreso Meta Mensual:</b> ${U().fmtUSD(f.ingresos_mes_usd || 0)} / ${U().fmtUSD(f.meta_mensual_usd || 1500, 0)} (<b>${f.progreso_meta_pct || 0}%</b>)</span>
          <div style="display:flex;gap:6px;align-items:center;">
            <label style="font-size:11.5px;color:var(--t16-muted);">TRM COP:
              <input id="t16FinTrmInput" class="t16-input" type="number" value="${Math.round(f.trm_cop || getTrm())}" style="width:86px;padding:4px 7px;margin-left:4px;">
            </label>
            <button class="t16-pill" onclick="TitanFinUI.updateTrm()">Aplicar TRM</button>
            <button class="t16-pill t16-pill-live" onclick="TitanFinUI.openEmitInvoiceModal()">+ Emitir Factura</button>
            <button class="t16-pill" onclick="TitanFinUI.openMovementModal('gasto')">- Gasto</button>
          </div>
        </div>
        <div class="t16-progress"><div class="t16-progress-fill" style="width:${pctMeta}%;"></div></div>
      </div>

      <div class="t16-split-2" style="margin-bottom:14px;">
        <div class="t16-card-box">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
            <h3 style="margin:0;font-size:14px;">📈 Cashflow Mensual (Verde = Ingresos, Rojo = Gastos)</h3>
            <div style="display:flex;gap:5px;">
              <button class="t16-btn-xs" onclick="TitanFinUI.setCashflowRange(6)">6M</button>
              <button class="t16-btn-xs" onclick="TitanFinUI.setCashflowRange(12)">12M</button>
            </div>
          </div>
          ${chartCf}
        </div>

        <div class="t16-card-box">
          <h3 style="margin:0 0 10px 0;font-size:14px;">🏦 Cobros Netos por Pasarela</h3>
          <div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap;">
            <div>${donutPas}</div>
            <div style="flex:1;min-width:190px;">${pasLegend}</div>
          </div>
        </div>
      </div>

      <div class="t16-card-box">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
          <h3 style="margin:0;font-size:14px;">💸 Gastos por Categoría</h3>
          <a class="t16-pill" href="/api/v2/finanzas/export.csv" target="_blank" style="text-decoration:none;">⬇️ Exportar Libro CSV</a>
        </div>
        ${gastosCat}
      </div>
    `;
  }

  function updateTrm() {
    const v = Number(document.getElementById('t16FinTrmInput')?.value || 4200);
    if (v < 100) return U().toast('TRM inválida', 'err');
    FSTATE.simTrm = v;
    global.TitanStore?.savePref('trm_cop', v);
    U().toast(`TRM actualizada a $${v.toLocaleString('es-CO')} COP`, 'ok');
    loadResumen(false);
  }

  function setCashflowRange(meses) {
    FSTATE.cashflowMeses = Number(meses || 6);
    loadResumen(false);
  }

  // ==================== 2. FACTURACION DB (EMITIR, COBRAR 1-CLIC, PREVIEW HTML, ANULAR) ====================
  async function loadFacturas(silent = false) {
    const qs = new URLSearchParams({ limit: '100' });
    if (FSTATE.facFiltroEstado) qs.set('estado', FSTATE.facFiltroEstado);
    const r = await API().get(`/api/v2/facturas?${qs.toString()}`, { silent });
    if (r?.ok) FSTATE.facturas = r.items || [];
    renderFacturasView();
  }

  function renderFacturasView() {
    const host = document.getElementById('t16FinBody');
    if (!host) return;
    const rows = FSTATE.facturas.map((f) => {
      const tono = f.estado_pago === 'pagada' ? 'ok' : (f.estado_pago === 'anulada' ? 'err' : 'warn');
      return `
        <tr>
          <td><b style="font-family:var(--t16-mono);color:var(--t16-cyan);">${U().escHtml(f.numero)}</b><div style="font-size:10.5px;color:var(--t16-muted);">${U().escHtml(String(f.emitida_ts || '').slice(0, 16))}</div></td>
          <td><b>${U().escHtml(f.cliente_nombre)}</b><div style="font-size:11px;color:var(--t16-muted);">${U().escHtml(String(f.concepto || '').slice(0, 58))}</div></td>
          <td>${U().badge(f.pasarela || 'binance', 'muted')}</td>
          <td class="t16-num">${U().fmtUSD(f.monto_bruto_usd)}</td>
          <td class="t16-num" style="color:var(--t16-green);">${U().fmtUSD(f.monto_neto_usd)}<div style="font-size:10px;color:var(--t16-muted);">${U().fmtCOP(f.monto_neto_cop)}</div></td>
          <td>${U().badge(String(f.estado_pago || '').toUpperCase(), tono)}</td>
          <td>
            <div style="display:flex;gap:5px;flex-wrap:wrap;">
              <button class="t16-btn-xs" onclick="TitanFinUI.previewInvoiceHtml(${f.id}, '${U().escHtml(f.numero)}')">🖨️ HTML</button>
              ${f.estado_pago === 'emitida' ? `<button class="t16-btn-xs" style="border-color:var(--t16-green);color:#4ade80;" onclick="TitanFinUI.openPayInvoiceModal(${f.id}, '${U().escHtml(f.numero)}', '${U().escHtml(f.pasarela || 'binance')}')">💵 Cobrar</button>` : ''}
              ${f.estado_pago !== 'anulada' ? `<button class="t16-btn-xs" onclick="TitanFinUI.cancelInvoice(${f.id}, '${U().escHtml(f.numero)}')">🚫</button>` : ''}
            </div>
          </td>
        </tr>
      `;
    }).join('');

    host.innerHTML = `
      <div class="t16-toolbar">
        <select id="t16FacEstSel" class="t16-select" onchange="TitanFinUI.filterFacturas(this.value)">
          <option value="" ${FSTATE.facFiltroEstado === '' ? 'selected' : ''}>Todas las facturas</option>
          <option value="emitida" ${FSTATE.facFiltroEstado === 'emitida' ? 'selected' : ''}>⏳ Pendientes (Emitidas)</option>
          <option value="pagada" ${FSTATE.facFiltroEstado === 'pagada' ? 'selected' : ''}>✅ Pagadas</option>
          <option value="anulada" ${FSTATE.facFiltroEstado === 'anulada' ? 'selected' : ''}>🚫 Anuladas</option>
        </select>
        <button class="t16-pill" onclick="TitanFinUI.switchSubtab('facturas')">🔄 Refrescar</button>
        <button class="t16-pill t16-pill-live" style="margin-left:auto;" onclick="TitanFinUI.openEmitInvoiceModal()">+ Emitir Nueva Factura</button>
      </div>
      ${FSTATE.facturas.length ? `
        <div class="t16-table-wrap">
          <table class="t16-table">
            <thead><tr><th>Número</th><th>Cliente &amp; Concepto</th><th>Pasarela</th><th class="t16-num">Bruto</th><th class="t16-num">Neto</th><th>Estado</th><th>Acciones</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      ` : U().renderEmptyState('No hay facturas con este filtro', 'Emite tu primera factura profesional HTML/PDF con un clic.')}
    `;
  }

  function filterFacturas(est) {
    FSTATE.facFiltroEstado = est;
    loadFacturas(false);
  }

  function openEmitInvoiceModal() {
    U().openModal({
      title: '🧾 Emitir Factura Profesional (DB + HTML/PDF)',
      html: `
        <div style="display:flex;flex-direction:column;gap:9px;">
          <input id="t16IfCli" class="t16-input" placeholder="Nombre del cliente o empresa (obligatorio)">
          <input id="t16IfConc" class="t16-input" placeholder="Concepto / entregable (ej. Python Playwright Scraper)">
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;">
            <input id="t16IfUsd" class="t16-input" type="number" step="1" value="250" placeholder="Monto bruto USD">
            <select id="t16IfPas" class="t16-select">
              <option value="binance">Binance USDT (0%)</option>
              <option value="wise">Wise (~1.2%)</option>
              <option value="airtm">Airtm (2%)</option>
              <option value="stripe">Stripe (2.9%+$0.30)</option>
              <option value="whop">Whop (3%+$0.30)</option>
              <option value="paypal">PayPal (5.4%+$0.30)</option>
              <option value="transferencia">Transferencia (0%)</option>
            </select>
            <input id="t16IfLead" class="t16-input" type="number" placeholder="Lead ID (opc.)">
          </div>
          <input id="t16IfMod" class="t16-input" value="50% Upfront / 50% on Delivery" placeholder="Términos de pago">
          <textarea id="t16IfNotas" class="t16-textarea" style="min-height:66px;" placeholder="Notas o entregables incluidos..."></textarea>
          <label style="font-size:12px;display:inline-flex;align-items:center;gap:6px;">
            <input id="t16IfPaid" type="checkbox"> Marcar como PAGADA de inmediato (registra ingreso en Caja)
          </label>
        </div>
      `,
      footerHtml: `<button class="t16-pill" onclick="TitanUI.closeModal()">Cancelar</button><button class="t16-pill t16-pill-live" id="t16IfSaveBtn">Emitir Factura</button>`,
      onOpen: () => {
        document.getElementById('t16IfSaveBtn')?.addEventListener('click', async () => {
          const cliente_nombre = (document.getElementById('t16IfCli')?.value || '').trim();
          const concepto = (document.getElementById('t16IfConc')?.value || '').trim();
          const monto_bruto_usd = Number(document.getElementById('t16IfUsd')?.value || 0);
          if (!cliente_nombre || !concepto || monto_bruto_usd <= 0) {
            return U().toast('Completa cliente, concepto y monto > 0', 'err');
          }
          const lid = Number(document.getElementById('t16IfLead')?.value || 0) || null;
          const r = await API().post('/api/v2/facturas', {
            cliente_nombre,
            concepto,
            monto_bruto_usd,
            pasarela: document.getElementById('t16IfPas')?.value || 'binance',
            modalidad: document.getElementById('t16IfMod')?.value || 'Final Payment',
            notas: document.getElementById('t16IfNotas')?.value || '',
            lead_id: lid,
            trm_cop: getTrm(),
            marcar_pagada: !!document.getElementById('t16IfPaid')?.checked,
          });
          if (r?.ok) {
            U().toast(`🧾 Factura ${r.factura.numero} emitida (${U().fmtUSD(r.factura.monto_neto_usd)} neto)`, 'ok');
            U().closeModal(true);
            refreshSubtab(true);
          }
        });
      },
    });
  }

  function openPayInvoiceModal(facId, numero, pasDefault) {
    U().openModal({
      title: `💵 Registrar Cobro — ${numero}`,
      html: `
        <div style="display:flex;flex-direction:column;gap:10px;">
          <p style="margin:0;font-size:12.5px;color:var(--t16-text-1);">Confirma la pasarela real usada por el cliente para calcular comisiones netas y crear el asiento automático en Caja:</p>
          <select id="t16PayPas" class="t16-select">
            ${['binance', 'wise', 'airtm', 'stripe', 'whop', 'paypal', 'transferencia'].map((p) =>
              `<option value="${p}" ${p === pasDefault ? 'selected' : ''}>${p.toUpperCase()}</option>`
            ).join('')}
          </select>
          <input id="t16PayTrm" class="t16-input" type="number" value="${Math.round(getTrm())}" placeholder="TRM COP">
        </div>
      `,
      footerHtml: `<button class="t16-pill" onclick="TitanUI.closeModal()">Cancelar</button><button class="t16-pill t16-pill-live" id="t16PayGo">Confirmar Cobro</button>`,
      onOpen: () => {
        document.getElementById('t16PayGo')?.addEventListener('click', async () => {
          const r = await API().post(`/api/v2/facturas/${facId}/pagar`, {
            pasarela: document.getElementById('t16PayPas')?.value || pasDefault,
            trm_cop: Number(document.getElementById('t16PayTrm')?.value || getTrm()),
          });
          if (r?.ok) {
            U().toast(`✅ Factura ${numero} cobrada (+${U().fmtUSD(r.factura.monto_neto_usd)} neto)`, 'ok');
            U().closeModal(true);
            refreshSubtab(true);
          }
        });
      },
    });
  }

  async function cancelInvoice(facId, numero) {
    const ok = await U().confirmDialog('Anular Factura', `¿Anular factura ${numero}? Si estaba pagada también se revertirá su asiento en Caja.`, 'Anular');
    if (!ok) return;
    const r = await API().post(`/api/v2/facturas/${facId}/anular`, { motivo: 'Anulada desde panel v16' });
    if (r?.ok) {
      U().toast(`Factura ${numero} anulada`, 'warn');
      loadFacturas(true);
    }
  }

  function previewInvoiceHtml(facId, numero) {
    const url = `/api/v2/facturas/${facId}/html`;
    U().openDrawer({
      title: `🖨️ Factura ${numero}`,
      width: 'min(820px, 96vw)',
      html: `<iframe src="${url}" style="width:100%;height:75vh;border:1px solid var(--t16-border);border-radius:10px;background:#fff;"></iframe>`,
      footerHtml: `<a class="t16-pill t16-pill-live" href="${url}" target="_blank" style="text-decoration:none;">Abrir en nueva pestaña / Imprimir PDF</a><button class="t16-pill" onclick="TitanUI.closeDrawer()">Cerrar</button>`,
    });
  }

  // ==================== 3. LIBRO MAYOR DE CAJA ====================
  async function loadCaja(silent = false) {
    const qs = new URLSearchParams({ limit: '150' });
    if (FSTATE.movFiltroTipo) qs.set('tipo', FSTATE.movFiltroTipo);
    const r = await API().get(`/api/v2/finanzas/movimientos?${qs.toString()}`, { silent });
    if (r?.ok) FSTATE.movimientos = r.items || [];
    renderCajaView();
  }

  function renderCajaView() {
    const host = document.getElementById('t16FinBody');
    if (!host) return;
    const rows = FSTATE.movimientos.map((m) => {
      const esPos = m.tipo === 'ingreso' || (m.tipo === 'ajuste' && Number(m.monto_usd) >= 0);
      const col = esPos ? 'var(--t16-green)' : (m.tipo === 'retiro' ? 'var(--t16-amber)' : 'var(--t16-red)');
      const signo = m.tipo === 'ingreso' ? '+' : (m.tipo === 'gasto' || m.tipo === 'retiro' ? '-' : '');
      const cop = Math.round(Number(m.monto_usd || 0) * Number(m.trm_cop || getTrm()));
      return `
        <tr>
          <td style="font-family:var(--t16-mono);font-size:11.5px;">${U().escHtml(String(m.fecha_ts || '').slice(0, 16))}</td>
          <td>${U().badge(String(m.tipo || '').toUpperCase(), m.tipo === 'ingreso' ? 'ok' : (m.tipo === 'gasto' ? 'err' : 'warn'))}</td>
          <td>${U().escHtml(m.categoria || '')}</td>
          <td>${U().escHtml(m.descripcion || '')}</td>
          <td>${U().badge(m.pasarela || 'binance', 'muted')}</td>
          <td class="t16-num" style="color:${col};">${signo}${U().fmtUSD(m.monto_usd)}<div style="font-size:10px;color:var(--t16-muted);">${U().fmtCOP(cop)}</div></td>
          <td><button class="t16-btn-xs" onclick="TitanFinUI.deleteMovement(${m.id})">🗑️</button></td>
        </tr>
      `;
    }).join('');

    host.innerHTML = `
      <div class="t16-toolbar">
        <select class="t16-select" onchange="TitanFinUI.filterMovs(this.value)">
          <option value="" ${FSTATE.movFiltroTipo === '' ? 'selected' : ''}>Todos los movimientos</option>
          <option value="ingreso" ${FSTATE.movFiltroTipo === 'ingreso' ? 'selected' : ''}>🟢 Ingresos</option>
          <option value="gasto" ${FSTATE.movFiltroTipo === 'gasto' ? 'selected' : ''}>🔴 Gastos</option>
          <option value="retiro" ${FSTATE.movFiltroTipo === 'retiro' ? 'selected' : ''}>🟡 Retiros</option>
          <option value="ajuste" ${FSTATE.movFiltroTipo === 'ajuste' ? 'selected' : ''}>🔵 Ajustes</option>
        </select>
        <button class="t16-pill t16-pill-live" onclick="TitanFinUI.openMovementModal('ingreso')">+ Ingreso</button>
        <button class="t16-pill t16-pill-err" onclick="TitanFinUI.openMovementModal('gasto')">- Gasto</button>
        <button class="t16-pill t16-pill-warn" onclick="TitanFinUI.openMovementModal('retiro')">🏧 Retiro</button>
        <a class="t16-pill" href="/api/v2/finanzas/export.csv" target="_blank" style="text-decoration:none;margin-left:auto;">⬇️ CSV</a>
      </div>
      ${FSTATE.movimientos.length ? `
        <div class="t16-table-wrap">
          <table class="t16-table">
            <thead><tr><th>Fecha UTC</th><th>Tipo</th><th>Categoría</th><th>Descripción</th><th>Pasarela</th><th class="t16-num">Monto</th><th></th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      ` : U().renderEmptyState('Libro mayor vacío', 'Registra tu primer ingreso o gasto, o cobra una factura.')}
    `;
  }

  function filterMovs(tipo) {
    FSTATE.movFiltroTipo = tipo;
    loadCaja(false);
  }

  function openMovementModal(tipoDefault = 'gasto') {
    U().openModal({
      title: `📒 Registrar Movimiento (${tipoDefault.toUpperCase()})`,
      html: `
        <div style="display:flex;flex-direction:column;gap:9px;">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            <select id="t16MvTipo" class="t16-select">
              ${['ingreso', 'gasto', 'retiro', 'ajuste'].map((t) => `<option value="${t}" ${t === tipoDefault ? 'selected' : ''}>${t.toUpperCase()}</option>`).join('')}
            </select>
            <input id="t16MvCat" class="t16-input" placeholder="Categoría (vps, freelance, retiro...)" value="${tipoDefault === 'gasto' ? 'infraestructura' : (tipoDefault === 'retiro' ? 'retiro_personal' : 'freelance')}">
          </div>
          <input id="t16MvDesc" class="t16-input" placeholder="Descripción clara del movimiento (obligatorio)">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            <input id="t16MvUsd" class="t16-input" type="number" step="0.01" placeholder="Monto USD">
            <select id="t16MvPas" class="t16-select">
              <option value="binance">Binance</option><option value="transferencia">Transferencia / Nequi</option>
              <option value="wise">Wise</option><option value="airtm">Airtm</option>
              <option value="paypal">PayPal</option><option value="stripe">Stripe</option>
            </select>
          </div>
        </div>
      `,
      footerHtml: `<button class="t16-pill" onclick="TitanUI.closeModal()">Cancelar</button><button class="t16-pill t16-pill-live" id="t16MvSave">Registrar</button>`,
      onOpen: () => {
        document.getElementById('t16MvSave')?.addEventListener('click', async () => {
          const descripcion = (document.getElementById('t16MvDesc')?.value || '').trim();
          const monto_usd = Number(document.getElementById('t16MvUsd')?.value || 0);
          if (!descripcion || monto_usd === 0) return U().toast('Completa descripción y monto', 'err');
          const r = await API().post('/api/v2/finanzas/movimientos', {
            tipo: document.getElementById('t16MvTipo')?.value || tipoDefault,
            categoria: (document.getElementById('t16MvCat')?.value || 'general').trim(),
            descripcion,
            monto_usd,
            pasarela: document.getElementById('t16MvPas')?.value || 'binance',
            trm_cop: getTrm(),
          });
          if (r?.ok) {
            U().toast('Movimiento registrado en caja', 'ok');
            U().closeModal(true);
            refreshSubtab(true);
          }
        });
      },
    });
  }

  async function deleteMovement(id) {
    const r = await API().del(`/api/v2/finanzas/movimientos/${id}`);
    if (r?.ok) {
      U().toast('Movimiento eliminado', 'ok');
      loadCaja(true);
    }
  }

  // ==================== 4. SIMULADOR COMPARATIVO PASARELAS & GROSS-UP ====================
  async function loadPasarelas(silent = false) {
    const r = await API().get(`/api/v2/finanzas/pasarelas?monto_usd=${FSTATE.simMonto}&trm_cop=${FSTATE.simTrm}`, { silent });
    if (r?.ok) FSTATE.simComparativa = r.comparativa || [];
    renderPasarelasView();
  }

  function renderPasarelasView() {
    const host = document.getElementById('t16FinBody');
    if (!host) return;
    const rows = FSTATE.simComparativa.map((p, idx) => `
      <tr>
        <td><b>${idx === 0 ? '🏆 ' : ''}${U().escHtml(p.nombre)}</b><div style="font-size:11px;color:var(--t16-muted);">${U().escHtml(p.notas)}</div></td>
        <td class="t16-num" style="color:var(--t16-red);">-${U().fmtUSD(p.comision_usd)} <small>(${p.comision_pct_efectiva}%)</small></td>
        <td class="t16-num" style="color:var(--t16-green);">${U().fmtUSD(p.monto_neto_usd)}</td>
        <td class="t16-num" style="color:var(--t16-cyan);">${U().fmtCOP(p.monto_neto_cop)}</td>
        <td class="t16-num">
          <button class="t16-btn-xs" onclick="navigator.clipboard?.writeText('${p.gross_up_usd}');TitanUI.toast('Gross-Up ${U().fmtUSD(p.gross_up_usd)} copiado','ok')">📋 Cobrar ${U().fmtUSD(p.gross_up_usd)}</button>
        </td>
      </tr>
    `).join('');

    host.innerHTML = `
      <div class="t16-card-box" style="margin-bottom:14px;">
        <div class="t16-split-2">
          <div>
            <div class="t16-meta-bar"><span>💵 Monto objetivo a cobrar (USD)</span><b style="font-family:var(--t16-mono);font-size:18px;color:var(--t16-cyan);" id="t16SimMontoLbl">${U().fmtUSD(FSTATE.simMonto, 0)}</b></div>
            <input class="t16-range" type="range" min="25" max="3000" step="25" value="${FSTATE.simMonto}" oninput="document.getElementById('t16SimMontoLbl').textContent='$'+Number(this.value).toLocaleString()" onchange="TitanFinUI.updateSim(this.value, null)">
          </div>
          <div style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;">
            <label style="font-size:12px;color:var(--t16-muted);">Monto exacto USD
              <input id="t16SimUsdNum" class="t16-input" type="number" value="${FSTATE.simMonto}" style="width:110px;display:block;margin-top:4px;">
            </label>
            <label style="font-size:12px;color:var(--t16-muted);">TRM COP
              <input id="t16SimTrmNum" class="t16-input" type="number" value="${Math.round(FSTATE.simTrm)}" style="width:110px;display:block;margin-top:4px;">
            </label>
            <button class="t16-pill t16-pill-live" onclick="TitanFinUI.updateSim(document.getElementById('t16SimUsdNum').value, document.getElementById('t16SimTrmNum').value)">Recalcular</button>
          </div>
        </div>
      </div>
      <div class="t16-table-wrap">
        <table class="t16-table">
          <thead><tr><th>Pasarela</th><th class="t16-num">Comisión</th><th class="t16-num">Te queda Neto (USD)</th><th class="t16-num">Equivalente COP</th><th class="t16-num">Gross-Up (para recibir ${U().fmtUSD(FSTATE.simMonto, 0)} netos)</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `;
  }

  function updateSim(monto, trm) {
    if (monto !== null) FSTATE.simMonto = Math.max(1, Number(monto || 250));
    if (trm !== null) FSTATE.simTrm = Math.max(100, Number(trm || 4200));
    loadPasarelas(false);
  }

  global.TitanFinUI = {
    init,
    switchSubtab,
    refreshSubtab,
    updateTrm,
    setCashflowRange,
    filterFacturas,
    openEmitInvoiceModal,
    openPayInvoiceModal,
    cancelInvoice,
    previewInvoiceHtml,
    filterMovs,
    openMovementModal,
    deleteMovement,
    updateSim,
  };
})(window);