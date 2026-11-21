// ==================== ZERO-TOUCH TITAN-OS v16.0 — TIME TRACKER LIVE & RENTABILIDAD POR HORA ====================
(function (global) {
  'use strict';

  const TSTATE = {
    hostId: 't16FinBody',
    prod: null,
    sesiones: [],
    dias: 30,
    storeUnsub: null,
    rentResult: null,
  };

  const U = () => global.TitanUI;
  const API = () => global.TitanAPI;

  function syncLiveClockOnly() {
    const clock = document.getElementById('t16TmLiveClock');
    const devEl = document.getElementById('t16TmLiveUsd');
    if (!clock || !global.TitanStore) return;
    const t = global.TitanStore.get('timer') || {};
    if (t.activa) {
      const seg = Number(t.elapsed_seg || 0);
      clock.textContent = U().fmtHMS(seg);
      clock.classList.remove('idle');
      if (devEl) {
        const usd = (seg / 3600) * Number(t.activa.tarifa_hora_usd || 25);
        devEl.textContent = t.activa.facturable ? `Devengado en vivo: ${U().fmtUSD(usd)}` : 'Sesión interna (no facturable)';
      }
    } else {
      clock.textContent = '00:00:00';
      clock.classList.add('idle');
      if (devEl) devEl.textContent = 'Sin cronómetro activo';
    }
  }

  function wireStoreOnce() {
    if (TSTATE.storeUnsub || !global.TitanStore) return;
    TSTATE.storeUnsub = global.TitanStore.subscribe('timer', syncLiveClockOnly);
  }

  async function render(hostId = 't16FinBody', silent = false) {
    TSTATE.hostId = hostId;
    wireStoreOnce();
    await refresh(silent);
  }

  async function refresh(silent = false) {
    const host = document.getElementById(TSTATE.hostId);
    if (!host) return;
    const trm = Number(global.TitanStore?.get('prefs.trm_cop') || 4200);
    const [rProd, rSes] = await Promise.all([
      API().get(`/api/v2/tiempo/resumen?dias=${TSTATE.dias}&trm_cop=${encodeURIComponent(trm)}`, { silent }),
      API().get(`/api/v2/tiempo/sesiones?dias=${TSTATE.dias}&limit=100`, { silent }),
    ]);
    if (rProd?.ok) {
      TSTATE.prod = rProd.productividad;
      const act = TSTATE.prod?.sesion_activa || null;
      global.TitanStore?.set('timer', { activa: act, elapsed_seg: act ? Number(act.duracion_seg || 0) : 0 });
    }
    if (rSes?.ok) TSTATE.sesiones = rSes.items || [];
    paint();
  }

  function paint() {
    const host = document.getElementById(TSTATE.hostId);
    if (!host) return;
    const p = TSTATE.prod || {};
    const act = p.sesion_activa || global.TitanStore?.get('timer.activa') || null;
    const serie14 = p.serie_14d || [];
    const topProjs = p.top_proyectos || [];

    const chartHoras = U().svgBarChart(
      serie14.map(([dia, hrs]) => ({ label: String(dia || '').slice(5), a: Number(hrs || 0), b: 0 })),
      { width: 560, height: 175, colorPos: '#22d3ee' }
    );

    const topHtml = topProjs.length
      ? topProjs.map((pr) => `
          <div class="t16-stat-line">
            <span><b>${U().escHtml(pr.proyecto)}</b> <small style="color:var(--t16-muted);">(${pr.sesiones} ses. &bull; ${pr.formato_hms})</small></span>
            <span class="t16-num" style="color:var(--t16-green);">${U().fmtUSD(pr.usd)}</span>
          </div>
        `).join('')
      : U().renderEmptyState('Sin sesiones en esta ventana');

    const sesRows = TSTATE.sesiones.map((s) => `
      <tr>
        <td style="font-family:var(--t16-mono);font-size:11.5px;">${U().escHtml(String(s.inicio_iso || '').slice(0, 16))}</td>
        <td><b>${U().escHtml(s.proyecto_nombre)}</b>${s.lead_id ? ` ${U().badge('Lead #' + s.lead_id, 'cyan')}` : ''}<div style="font-size:11px;color:var(--t16-muted);">${U().escHtml(s.notas || '')}</div></td>
        <td class="t16-num">${s.activa ? U().badge('EN CURSO', 'ok') : U().escHtml(s.formato_hms)}</td>
        <td class="t16-num">${U().fmtUSD(s.tarifa_hora_usd, 0)}/hr</td>
        <td class="t16-num" style="color:${s.facturable ? 'var(--t16-green)' : 'var(--t16-muted)'};">${s.facturable ? U().fmtUSD(s.valor_devengado_usd) : 'No fact.'}</td>
        <td>
          <div style="display:flex;gap:5px;">
            ${s.activa ? `<button class="t16-btn-xs" onclick="TitanTimerUI.stopActive(${s.id})">⏹️ Stop</button>` : `<button class="t16-btn-xs" onclick="TitanTimerUI.deleteSession(${s.id})">🗑️</button>`}
          </div>
        </td>
      </tr>
    `).join('');

    const rentBox = TSTATE.rentResult ? (() => {
      const r = TSTATE.rentResult;
      const tono = r.veredicto === 'excelente' || r.veredicto === 'saludable' ? 'ok' : (r.veredicto === 'ajustado' ? 'warn' : 'err');
      return `
        <div class="t16-stat-line" style="margin-top:8px;border-color:var(--t16-border-strong);">
          <span>Lead #${r.lead_id}: <b>${U().escHtml(r.titulo || '')}</b> (${r.horas_totales}h &bull; Ingreso ${U().fmtUSD(r.ingreso_base_calculo_usd)})</span>
          <span>${U().badge(U().fmtUSD(r.tarifa_efectiva_usd_hr) + '/hr · ' + String(r.veredicto || '').toUpperCase(), tono)}</span>
        </div>
      `;
    })() : '';

    host.innerHTML = `
      <div class="t16-timer-hero">
        <div>
          <div style="font-size:11.5px;text-transform:uppercase;letter-spacing:0.06em;color:var(--t16-muted);font-weight:700;">
            ${act ? `🟢 SESIÓN EN CURSO: ${U().escHtml(act.proyecto_nombre)}` : '⏱️ CRONÓMETRO PERSISTENTE TITAN-OS'}
          </div>
          <div id="t16TmLiveClock" class="t16-timer-clock ${act ? '' : 'idle'}">${act ? U().fmtHMS(global.TitanStore?.get('timer.elapsed_seg') || act.duracion_seg) : '00:00:00'}</div>
          <div id="t16TmLiveUsd" style="font-size:12px;color:var(--t16-text-1);margin-top:4px;">${act ? `Tarifa: ${U().fmtUSD(act.tarifa_hora_usd, 0)}/hr` : 'Listo para medir tu próxima sesión de código'}</div>
        </div>
        <div style="display:flex;flex-direction:column;gap:8px;min-width:280px;flex:1;max-width:440px;">
          ${act ? `
            <input id="t16TmStopNotes" class="t16-input" placeholder="Notas de cierre de sesión (opcional)...">
            <button class="t16-pill t16-pill-err" style="justify-content:center;padding:10px;" onclick="TitanTimerUI.stopActive(${act.id})">⏹️ Detener y Guardar Sesión</button>
          ` : `
            <input id="t16TmProj" class="t16-input" placeholder="Proyecto (ej. Scraper Shopify Playwright)">
            <div style="display:grid;grid-template-columns:1fr 1fr auto;gap:7px;">
              <input id="t16TmLead" class="t16-input" type="number" placeholder="Lead ID (opc.)">
              <input id="t16TmRate" class="t16-input" type="number" value="25" placeholder="USD/hr">
              <button class="t16-pill t16-pill-timer-on" onclick="TitanTimerUI.startNew()">▶️ Iniciar</button>
            </div>
          `}
        </div>
      </div>

      <div class="t16-kpi-grid">
        <div class="t16-kpi"><span class="t16-kpi-lbl">Horas (${TSTATE.dias}d)</span><span class="t16-kpi-val" style="color:var(--t16-cyan);">${p.horas_totales || 0}h</span><span class="t16-kpi-sub">${U().escHtml(p.formato_total_hms || '00:00:00')} &bull; ${p.total_sesiones || 0} sesiones</span></div>
        <div class="t16-kpi"><span class="t16-kpi-lbl">% Facturable</span><span class="t16-kpi-val" style="color:var(--t16-green);">${p.pct_facturable || 0}%</span><span class="t16-kpi-sub">Facturables: ${p.horas_facturables || 0}h</span></div>
        <div class="t16-kpi"><span class="t16-kpi-lbl">Valor Devengado</span><span class="t16-kpi-val">${U().fmtUSD(p.valor_devengado_usd || 0)}</span><span class="t16-kpi-sub">${U().fmtCOP(p.valor_devengado_cop || 0)}</span></div>
      </div>

      <div class="t16-split-2" style="margin-bottom:14px;">
        <div class="t16-card-box">
          <h3 style="margin:0 0 10px 0;font-size:14px;">📊 Horas Trabajadas (Últimos 14 días)</h3>
          ${chartHoras}
        </div>
        <div class="t16-card-box">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
            <h3 style="margin:0;font-size:14px;">🏆 Top Proyectos &amp; Rentabilidad por Lead</h3>
            <button class="t16-btn-xs" onclick="TitanTimerUI.openManualModal()">+ Sesión Manual</button>
          </div>
          ${topHtml}
          <div style="display:flex;gap:6px;margin-top:10px;">
            <input id="t16TmRentLead" class="t16-input" type="number" placeholder="Lead ID para medir USD/hr real" style="flex:1;">
            <button class="t16-pill" onclick="TitanTimerUI.checkLeadRent()">Medir USD/hr</button>
          </div>
          ${rentBox}
        </div>
      </div>

      <div class="t16-card-box">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;flex-wrap:wrap;gap:8px;">
          <h3 style="margin:0;font-size:14px;">🗂️ Historial de Sesiones (${TSTATE.sesiones.length})</h3>
          <div style="display:flex;gap:6px;">
            <button class="t16-pill" onclick="TitanTimerUI.openManualModal()">+ Registro Manual</button>
            <a class="t16-pill" href="/api/v2/tiempo/export.csv?dias=${TSTATE.dias}" target="_blank" style="text-decoration:none;">⬇️ Timesheet CSV</a>
          </div>
        </div>
        ${TSTATE.sesiones.length ? `
          <div class="t16-table-wrap">
            <table class="t16-table">
              <thead><tr><th>Inicio UTC</th><th>Proyecto</th><th class="t16-num">Duración</th><th class="t16-num">Tarifa</th><th class="t16-num">Valor</th><th></th></tr></thead>
              <tbody>${sesRows}</tbody>
            </table>
          </div>
        ` : U().renderEmptyState('Sin sesiones registradas todavía')}
      </div>
    `;

    syncLiveClockOnly();
  }

  async function startNew() {
    const proyecto_nombre = (document.getElementById('t16TmProj')?.value || '').trim();
    const lead_id = Number(document.getElementById('t16TmLead')?.value || 0) || null;
    const tarifa_hora_usd = Number(document.getElementById('t16TmRate')?.value || 25);
    const r = await API().post('/api/v2/tiempo/iniciar', { proyecto_nombre, lead_id, tarifa_hora_usd, facturable: true });
    if (r?.ok) {
      U().toast(`▶️ Cronómetro iniciado: ${r.sesion.proyecto_nombre}`, 'ok');
      await refresh(true);
    }
  }

  async function stopActive(sesionId = null) {
    const notas = (document.getElementById('t16TmStopNotes')?.value || '').trim();
    const r = await API().post('/api/v2/tiempo/detener', { sesion_id: sesionId, notas: notas || undefined });
    if (r?.ok) {
      U().toast(`⏹️ Sesión guardada: ${r.sesion.formato_hms} (${U().fmtUSD(r.sesion.valor_devengado_usd)})`, 'ok');
      await refresh(true);
    }
  }

  function openManualModal() {
    U().openModal({
      title: '⏱️ Registrar Sesión Manual',
      html: `
        <div style="display:flex;flex-direction:column;gap:9px;">
          <input id="t16TmMProj" class="t16-input" placeholder="Nombre del proyecto (obligatorio)">
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;">
            <input id="t16TmMMins" class="t16-input" type="number" value="60" min="1" placeholder="Minutos">
            <input id="t16TmMRate" class="t16-input" type="number" value="25" min="1" placeholder="USD/hr">
            <input id="t16TmMLead" class="t16-input" type="number" placeholder="Lead ID (opc.)">
          </div>
          <input id="t16TmMNotes" class="t16-input" placeholder="Notas (ej. Deploy y testing)">
          <label style="font-size:12px;display:inline-flex;align-items:center;gap:6px;">
            <input id="t16TmMFact" type="checkbox" checked> Tiempo facturable
          </label>
        </div>
      `,
      footerHtml: `<button class="t16-pill" onclick="TitanUI.closeModal()">Cancelar</button><button class="t16-pill t16-pill-live" id="t16TmMSave">Guardar</button>`,
      onOpen: () => {
        document.getElementById('t16TmMSave')?.addEventListener('click', async () => {
          const proyecto_nombre = (document.getElementById('t16TmMProj')?.value || '').trim() || 'Desarrollo Freelance';
          const duracion_minutos = Number(document.getElementById('t16TmMMins')?.value || 0);
          if (duracion_minutos <= 0) return U().toast('Minutos debe ser > 0', 'err');
          const r = await API().post('/api/v2/tiempo/manual', {
            proyecto_nombre,
            duracion_minutos,
            tarifa_hora_usd: Number(document.getElementById('t16TmMRate')?.value || 25),
            lead_id: Number(document.getElementById('t16TmMLead')?.value || 0) || null,
            notas: document.getElementById('t16TmMNotes')?.value || '',
            facturable: !!document.getElementById('t16TmMFact')?.checked,
          });
          if (r?.ok) {
            U().toast(`Sesión manual registrada (${r.sesion.formato_hms})`, 'ok');
            U().closeModal(true);
            refresh(true);
          }
        });
      },
    });
  }

  async function checkLeadRent() {
    const lid = Number(document.getElementById('t16TmRentLead')?.value || 0);
    if (!lid) return U().toast('Ingresa un Lead ID válido', 'err');
    const r = await API().get(`/api/v2/tiempo/rentabilidad/${lid}`);
    if (r?.ok) {
      TSTATE.rentResult = r.rentabilidad;
      paint();
    }
  }

  async function deleteSession(id) {
    const r = await API().del(`/api/v2/tiempo/sesiones/${id}`);
    if (r?.ok) {
      U().toast('Sesión eliminada', 'ok');
      refresh(true);
    }
  }

  global.TitanTimerUI = {
    render,
    refresh,
    startNew,
    stopActive,
    openManualModal,
    checkLeadRent,
    deleteSession,
  };
})(window);