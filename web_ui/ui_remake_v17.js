(function (global) {
  'use strict';

  const API_PREVIEW = '/api/v2/leads/limpiar/preview';
  const API_LIMPIAR = '/api/v2/leads/limpiar';
  let state = { modo: 'nuevos', scoreMax: 6, backup: true, vistos: false, preview: null, busy: false };

  function injectModalStyles() {
    if (document.getElementById('titanV17CleanStyle')) return;
    const st = document.createElement('style');
    st.id = 'titanV17CleanStyle';
    st.textContent = `
      .t17-modal-bg{position:fixed;inset:0;z-index:9999;background:rgba(2,6,23,.72);backdrop-filter:blur(8px);display:none;align-items:center;justify-content:center;padding:16px}
      .t17-modal-bg.open{display:flex}
      .t17-modal{width:100%;max-width:520px;background:var(--t17-surface-solid,#111726);color:var(--t17-text,#eef2ff);border:1px solid var(--t17-border-strong,rgba(148,163,184,.28));border-radius:16px;box-shadow:0 24px 60px rgba(0,0,0,.55);overflow:hidden;font-family:inherit}
      .t17-m-head{display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid var(--t17-border,rgba(148,163,184,.15))}
      .t17-m-head h3{margin:0;font-size:16px;font-weight:700;display:flex;align-items:center;gap:8px}
      .t17-m-close{background:transparent!important;border:none!important;color:var(--t17-muted,#8b9bb4);font-size:20px;cursor:pointer;padding:2px 8px}
      .t17-m-body{padding:18px 20px;display:flex;flex-direction:column;gap:14px}
      .t17-stats-row{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
      .t17-stat{background:var(--t17-surface-elev,rgba(23,30,48,.85));border:1px solid var(--t17-border);border-radius:10px;padding:10px;text-align:center}
      .t17-stat b{display:block;font-size:18px;font-variant-numeric:tabular-nums}
      .t17-stat span{font-size:11px;color:var(--t17-muted,#8b9bb4)}
      .t17-opt{display:flex;align-items:flex-start;gap:10px;padding:11px 12px;border-radius:11px;border:1px solid var(--t17-border);background:var(--t17-surface-elev);cursor:pointer;transition:.15s}
      .t17-opt.sel{border-color:var(--t17-accent,#6366f1);box-shadow:0 0 0 2px var(--t17-accent-glow,rgba(99,102,241,.28))}
      .t17-opt.danger.sel{border-color:var(--t17-red,#f43f5e);box-shadow:0 0 0 2px rgba(244,63,94,.28)}
      .t17-opt-txt{flex:1}
      .t17-opt-txt strong{display:block;font-size:13px;margin-bottom:2px}
      .t17-opt-txt small{color:var(--t17-muted,#8b9bb4);font-size:11.5px}
      .t17-badge-cnt{font-size:12px;font-weight:700;padding:2px 8px;border-radius:999px;background:rgba(99,102,241,.18);color:var(--t17-text)}
      .t17-opt.danger .t17-badge-cnt{background:rgba(244,63,94,.22);color:#fda4af}
      .t17-checks{display:flex;flex-direction:column;gap:8px;padding:10px 12px;border-radius:10px;background:var(--t17-surface-elev);border:1px solid var(--t17-border);font-size:12.5px}
      .t17-checks label{display:flex;align-items:center;gap:8px;cursor:pointer}
      .t17-m-foot{display:flex;justify-content:flex-end;gap:10px;padding:14px 20px;border-top:1px solid var(--t17-border)}
      .t17-btn-sec{padding:8px 14px;background:var(--t17-surface-elev)!important;color:var(--t17-text)!important;border:1px solid var(--t17-border)!important;cursor:pointer}
      .t17-btn-exec{padding:8px 16px;background:linear-gradient(135deg,#f43f5e,#e11d48)!important;color:#fff!important;border:none!important;cursor:pointer;box-shadow:0 4px 16px rgba(244,63,94,.35)}
      .t17-btn-exec:disabled{opacity:.5;cursor:not-allowed}
      .t17-score-in{width:54px;padding:2px 6px!important;margin-left:6px;text-align:center;font-size:12px}
    `;
    document.head.appendChild(st);
  }

  function toast(msg, tipo) {
    if (global.TitanUI && typeof global.TitanUI.toast === 'function') global.TitanUI.toast(msg, tipo || 'ok');
    else if (typeof global.toast === 'function') global.toast(msg);
  }

  function countForMode() {
    const p = state.preview;
    if (!p) return 0;
    if (state.modo === 'todos') return p.total || 0;
    if (state.modo === 'bajo_score') return p.bajo_score || 0;
    return p.nuevos_y_descartados || 0;
  }

  function renderModal() {
    const el = document.getElementById('titanV17CleanModal');
    if (!el) return;
    const p = state.preview || { total: 0, nuevos_y_descartados: 0, protegidos: 0, bajo_score: 0, vistos_registrados: 0 };
    el.querySelector('[data-st="total"]').textContent = p.total;
    el.querySelector('[data-st="prot"]').textContent = p.protegidos;
    el.querySelector('[data-st="vistos"]').textContent = p.vistos_registrados;
    el.querySelector('[data-cnt="nuevos"]').textContent = p.nuevos_y_descartados;
    el.querySelector('[data-cnt="bajo_score"]').textContent = p.bajo_score;
    el.querySelector('[data-cnt="todos"]').textContent = p.total;

    el.querySelectorAll('.t17-opt').forEach((o) => {
      const m = o.dataset.modo;
      o.classList.toggle('sel', m === state.modo);
      o.querySelector('input[type="radio"]').checked = m === state.modo;
    });

    const n = countForMode();
    const btn = el.querySelector('#t17ExecCleanBtn');
    btn.disabled = state.busy || (n === 0 && !state.vistos);
    btn.textContent = state.busy
      ? '⏳ Limpiando...'
      : n > 0
      ? `🧹 Limpiar ${n} detectado${n === 1 ? '' : 's'}`
      : state.vistos
      ? '♻️ Limpiar solo caché de vistos'
      : 'Nada para limpiar';
  }

  async function cargarPreview() {
    try {
      const r = await fetch(`${API_PREVIEW}?score_max=${encodeURIComponent(state.scoreMax)}`, { cache: 'no-store' });
      const d = await r.json();
      if (d && d.ok) state.preview = d;
    } catch (_) {}
    renderModal();
  }

  async function ejecutarLimpieza() {
    if (state.busy) return;
    const n = countForMode();
    if (state.modo === 'todos' && n > 0) {
      const ok = global.confirm(`¿Seguro que quieres borrar TODOS los ${n} leads detectados del Radar/OMNI?`);
      if (!ok) return;
    }
    state.busy = true;
    renderModal();
    try {
      const r = await fetch(API_LIMPIAR, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          modo: state.modo,
          score_max: Number(state.scoreMax) || 6,
          limpiar_vistos: Boolean(state.vistos),
          backup_previo: Boolean(state.backup),
        }),
      });
      const d = await r.json();
      if (!d || !d.ok) throw new Error((d && d.error) || 'Error limpiando radar');

      cerrarModal();
      const extraBkp = d.backup_archivo ? ` • Backup: ${d.backup_archivo}` : '';
      const extraVis = d.vistos_limpiados ? ` • ${d.vistos_limpiados} vistos reseteados` : '';
      toast(`🧹 ${d.eliminados} detectados eliminados (quedan ${d.restantes})${extraVis}${extraBkp}`, 'ok');

      if (typeof global.cargarDatos === 'function') global.cargarDatos(false);
      if (global.TitanStore && typeof global.TitanStore.refreshOverview === 'function') global.TitanStore.refreshOverview();
      if (global.TitanCRM && typeof global.TitanCRM.cargar === 'function') global.TitanCRM.cargar();
    } catch (err) {
      toast(`❌ ${err.message || err}`, 'err');
    } finally {
      state.busy = false;
      renderModal();
    }
  }

  function crearModal() {
    if (document.getElementById('titanV17CleanModal')) return;
    injectModalStyles();
    const wrap = document.createElement('div');
    wrap.id = 'titanV17CleanModal';
    wrap.className = 't17-modal-bg';
    wrap.innerHTML = `
      <div class="t17-modal" role="dialog" aria-modal="true">
        <div class="t17-m-head">
          <h3>🧹 Limpiar Detecciones OMNI / Radar</h3>
          <button type="button" class="t17-m-close" id="t17CloseCleanBtn" title="Cerrar">&times;</button>
        </div>
        <div class="t17-m-body">
          <div class="t17-stats-row">
            <div class="t17-stat"><b data-st="total">0</b><span>Total detectados</span></div>
            <div class="t17-stat"><b data-st="prot">0</b><span>En proceso / Ganados</span></div>
            <div class="t17-stat"><b data-st="vistos">0</b><span>Caché de vistos</span></div>
          </div>
          <label class="t17-opt sel" data-modo="nuevos">
            <input type="radio" name="t17Modo" value="nuevos" checked>
            <div class="t17-opt-txt">
              <strong>Solo nuevos y descartados (Recomendado)</strong>
              <small>Borra el ruido sin tocar leads contactados, negociando o ganados.</small>
            </div>
            <span class="t17-badge-cnt" data-cnt="nuevos">0</span>
          </label>
          <label class="t17-opt" data-modo="bajo_score">
            <input type="radio" name="t17Modo" value="bajo_score">
            <div class="t17-opt-txt">
              <strong>Solo bajo score &le; <input type="number" min="0" max="10" value="6" id="t17ScoreMaxIn" class="t17-score-in"></strong>
              <small>Limpia oportunidades flojas (solo en estado nuevo/descartado).</small>
            </div>
            <span class="t17-badge-cnt" data-cnt="bajo_score">0</span>
          </label>
          <label class="t17-opt danger" data-modo="todos">
            <input type="radio" name="t17Modo" value="todos">
            <div class="t17-opt-txt">
              <strong>Limpiar TODO lo detectado (Dejar en 0)</strong>
              <small>Vacía por completo la lista del Radar manteniendo facturas e historial de caja.</small>
            </div>
            <span class="t17-badge-cnt" data-cnt="todos">0</span>
          </label>
          <div class="t17-checks">
            <label><input type="checkbox" id="t17ChkBackup" checked> 🛡️ Crear backup automático SQLite antes de borrar</label>
            <label><input type="checkbox" id="t17ChkVistos"> ♻️ Resetear caché de vistos/dedup (permite re-detectar en el próximo escaneo)</label>
          </div>
        </div>
        <div class="t17-m-foot">
          <button type="button" class="t17-btn-sec" id="t17CancelCleanBtn">Cancelar</button>
          <button type="button" class="t17-btn-exec" id="t17ExecCleanBtn">🧹 Limpiar</button>
        </div>
      </div>
    `;
    document.body.appendChild(wrap);

    wrap.addEventListener('click', (e) => { if (e.target === wrap) cerrarModal(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && wrap.classList.contains('open')) cerrarModal(); });
    wrap.querySelector('#t17CloseCleanBtn').addEventListener('click', cerrarModal);
    wrap.querySelector('#t17CancelCleanBtn').addEventListener('click', cerrarModal);
    wrap.querySelector('#t17ExecCleanBtn').addEventListener('click', ejecutarLimpieza);

    wrap.querySelectorAll('.t17-opt').forEach((o) => {
      o.addEventListener('click', () => { state.modo = o.dataset.modo; renderModal(); });
    });
    const scIn = wrap.querySelector('#t17ScoreMaxIn');
    scIn.addEventListener('click', (e) => e.stopPropagation());
    scIn.addEventListener('change', () => {
      state.scoreMax = Math.max(0, Math.min(10, parseInt(scIn.value || '6', 10)));
      scIn.value = state.scoreMax;
      state.modo = 'bajo_score';
      cargarPreview();
    });
    wrap.querySelector('#t17ChkBackup').addEventListener('change', (e) => { state.backup = e.target.checked; });
    wrap.querySelector('#t17ChkVistos').addEventListener('change', (e) => { state.vistos = e.target.checked; renderModal(); });
  }

  function abrirModal() {
    crearModal();
    const el = document.getElementById('titanV17CleanModal');
    if (el) el.classList.add('open');
    cargarPreview();
  }

  function cerrarModal() {
    const el = document.getElementById('titanV17CleanModal');
    if (el) el.classList.remove('open');
  }

  function montarBotonLimpiar() {
    if (document.getElementById('titanV17CleanBtn')) return;
    const btn = document.createElement('button');
    btn.id = 'titanV17CleanBtn';
    btn.type = 'button';
    btn.className = 't17-btn-clean';
    btn.title = 'Limpiar detecciones del Radar / OMNI';
    btn.innerHTML = '🧹 Limpiar Radar';
    btn.addEventListener('click', abrirModal);

    // Ubicar justo junto al boton CSV o Escanear en la barra superior
    const candidatos = Array.from(document.querySelectorAll('header button, .topbar button, .top-bar button, button'));
    const ancla = candidatos.find((b) => /\bCSV\b/i.test(b.textContent || ''))
      || candidatos.find((b) => /Escanear/i.test(b.textContent || ''));
    if (ancla && ancla.parentNode) {
      ancla.parentNode.insertBefore(btn, ancla.nextSibling);
    } else {
      const topbar = document.querySelector('header, .topbar, .top-bar');
      if (topbar) topbar.appendChild(btn);
    }
  }

  function init() {
    crearModal();
    montarBotonLimpiar();
  }

  global.TitanRadarCleanerUI = { abrir: abrirModal, cerrar: cerrarModal, refrescar: cargarPreview };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})(window);