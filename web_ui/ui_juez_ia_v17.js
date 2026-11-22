(function (global) {
  'use strict';

  let mapaPorId = {};
  let mapaLista = [];
  let observador = null;
  let decorando = false;

  function toast(m, t) {
    if (global.TitanUI && typeof global.TitanUI.toast === 'function') global.TitanUI.toast(m, t || 'ok');
    else if (typeof global.toast === 'function') global.toast(m);
  }

  function injectStyles() {
    if (document.getElementById('t17JuezStyle')) return;
    const s = document.createElement('style');
    s.id = 't17JuezStyle';
    s.textContent = `
      .t17-btn-juez{display:inline-flex;align-items:center;gap:6px;padding:7px 12px!important;font-size:12px!important;font-weight:700!important;color:#a7f3d0!important;background:linear-gradient(135deg,rgba(16,185,129,.22),rgba(6,182,212,.14))!important;border:1px solid rgba(16,185,129,.48)!important;border-radius:10px!important;cursor:pointer}
      .t17-btn-juez:hover{filter:brightness(1.12);box-shadow:0 4px 16px rgba(16,185,129,.28)}
      :root[data-titan-theme="light"] .t17-btn-juez{color:#047857!important;background:rgba(16,185,129,.12)!important}
      .t17-juez-box{margin-top:8px;padding:8px 10px;border-radius:10px;border:1px solid var(--t17-border,rgba(148,163,184,.2));background:var(--t17-surface-elev,rgba(15,23,42,.55));font-size:12px;line-height:1.45;display:flex;flex-direction:column;gap:4px}
      .t17-juez-box.apta{border-left:3px solid #10b981}
      .t17-juez-box.noapta{border-left:3px solid #f43f5e}
      .t17-juez-top{display:flex;align-items:center;flex-wrap:wrap;gap:6px}
      .t17-juez-pill{display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700}
      .t17-juez-pill.ok{background:rgba(16,185,129,.18);color:#6ee7b7;border:1px solid rgba(16,185,129,.4)}
      .t17-juez-pill.bad{background:rgba(244,63,94,.18);color:#fda4af;border:1px solid rgba(244,63,94,.4)}
      .t17-juez-pill.wait{background:rgba(148,163,184,.16);color:var(--t17-muted,#94a3b8);border:1px solid var(--t17-border)}
      :root[data-titan-theme="light"] .t17-juez-pill.ok{color:#047857}
      :root[data-titan-theme="light"] .t17-juez-pill.bad{color:#be123c}
      .t17-juez-es{color:var(--t17-text,#eef2ff)}
      .t17-juez-es b{color:var(--t17-accent-2,#22d3ee)}
      :root[data-titan-theme="light"] .t17-juez-es b{color:#0369a1}
      .t17-juez-mot{color:var(--t17-muted,#94a3b8);font-size:11.5px}
      .t17-juez-tip{color:#93c5fd;font-size:11.5px}
      :root[data-titan-theme="light"] .t17-juez-tip{color:#1d4ed8}
      .t17-juez-mini{padding:2px 8px!important;font-size:11px!important;border-radius:7px!important;background:rgba(99,102,241,.2)!important;color:#c7d2fe!important;border:1px solid rgba(99,102,241,.4)!important;cursor:pointer}
      :root[data-titan-theme="light"] .t17-juez-mini{color:#4338ca!important}
    `;
    document.head.appendChild(s);
  }

  function esc(str) {
    return String(str || '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function extraerLeadId(tr) {
    if (tr.dataset && (tr.dataset.id || tr.dataset.leadId)) return String(tr.dataset.id || tr.dataset.leadId);
    const html = tr.innerHTML || '';
    const m = html.match(/(?:cambiarEstado|abrirCopiloto|generarPitch|eliminarLead|verLead|marcar|nota)\s*\(\s*(\d+)/i)
      || html.match(/data-(?:lead-)?id=["'](\d+)["']/i);
    if (m) return m[1];
    return '';
  }

  function buscarInfo(tr, leadId) {
    if (leadId && mapaPorId[leadId]) return mapaPorId[leadId];
    const txt = (tr.textContent || '').toLowerCase();
    for (let i = 0; i < mapaLista.length; i++) {
      const it = mapaLista[i];
      const frag = String(it.titulo_original || '').trim().toLowerCase().slice(0, 32);
      if (frag.length >= 10 && txt.includes(frag)) return it;
    }
    return null;
  }

  function encontrarCeldaTitulo(tr) {
    const tds = Array.from(tr.querySelectorAll('td'));
    if (!tds.length) return null;
    const conLink = tds.find((td) => td.querySelector('a[href^="http"]') && !td.querySelector('select'));
    if (conLink) return conLink;
    let mejor = null;
    let maxLen = -1;
    tds.forEach((td) => {
      if (td.querySelector('select')) return;
      const l = (td.textContent || '').trim().length;
      if (l > maxLen) { maxLen = l; mejor = td; }
    });
    return mejor || tds[0];
  }

  async function verificarUno(leadId, btnEl) {
    if (!leadId) return;
    if (btnEl) { btnEl.disabled = true; btnEl.textContent = '\u23F3 Analizando...'; }
    try {
      const r = await fetch('/api/v2/juez-ia/verificar-una', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lead_id: Number(leadId), forzar: true }),
      });
      const d = await r.json();
      if (r.ok && d && d.ok && d.resultado) {
        mapaPorId[String(leadId)] = d.resultado;
        mapaLista = Object.values(mapaPorId);
        decorarTabla();
        toast(`\uD83E\uDDE0 Lead #${leadId}: ${d.resultado.veredicto}`, d.resultado.suficiente_gemini_38_high ? 'ok' : 'warn');
      } else {
        toast('\u274C No se pudo verificar esta oferta', 'err');
      }
    } catch (_) {
      toast('\u274C Error de conexi\u00f3n con el Juez IA', 'err');
    }
  }
  function decorarTabla() {
    if (decorando) return;
    const tbody = document.getElementById('tbodyLeads');
    if (!tbody) return;
    decorando = true;
    try {
      Array.from(tbody.querySelectorAll('tr')).forEach((tr) => {
        const tds = tr.querySelectorAll('td');
        if (tds.length < 2) return;
        const lid = extraerLeadId(tr);
        const info = buscarInfo(tr, lid);
        const key = info ? `${info.hash_oferta || ''}|${info.veredicto}|${info.actualizado_ts || ''}` : `wait|${lid}`;
        const prev = tr.querySelector('.t17-juez-box');
        if (prev && prev.dataset.key === key) return;
        if (prev) prev.remove();

        const celda = encontrarCeldaTitulo(tr);
        if (!celda) return;

        const box = document.createElement('div');
        box.dataset.key = key;

        if (!info) {
          box.className = 't17-juez-box';
          box.innerHTML = `<div class="t17-juez-top"><span class="t17-juez-pill wait">\u23F3 Sin traducir / verificar por IA</span>${lid ? `<button type="button" class="t17-juez-mini">\uD83E\uDDE0 Traducir y verificar</button>` : ''}</div>`;
          const b = box.querySelector('.t17-juez-mini');
          if (b) b.onclick = (e) => { e.stopPropagation(); verificarUno(lid, b); };
        } else {
          const sinIa = info.veredicto === 'SIN_IA' || info.veredicto === 'REVISAR' || info.modelo_usado === 'heuristica_offline';
          const ok = !sinIa && Boolean(info.suficiente_gemini_38_high);
          box.className = 't17-juez-box ' + (sinIa ? '' : (ok ? 'apta' : 'noapta'));
          const pill = sinIa
            ? `<span class="t17-juez-pill wait">\u26A0\uFE0F Pendiente de IA (cuota / sin conexi\u00f3n)</span>`
            : (ok
              ? `<span class="t17-juez-pill ok">\u2705 Gemini 3.8 High: APTA (${esc(info.nivel_dificultad || 'media')})</span>`
              : `<span class="t17-juez-pill bad">\u26D4 NO APTA para Gemini 3.8 High (${esc(info.nivel_dificultad || 'alta')})</span>`);
          const tip = ok && info.pasos_sugeridos_es
            ? `<div class="t17-juez-tip">\uD83D\uDCA1 <b>C\u00f3mo pedirlo:</b> ${esc(info.pasos_sugeridos_es)}</div>`
            : '';
          box.innerHTML = `
            <div class="t17-juez-top">${pill}${lid ? `<button type="button" class="t17-juez-mini" title="Re-analizar con IA">\uD83D\uDD04</button>` : ''}</div>
            <div class="t17-juez-es"><b>Qu\u00e9 pide (ES):</b> ${esc(info.resumen_es)}</div>
            <div class="t17-juez-mot"><b>Motivo:</b> ${esc(info.motivo_es)}</div>
            ${tip}
          `;
          const b = box.querySelector('.t17-juez-mini');
          if (b) b.onclick = (e) => { e.stopPropagation(); verificarUno(lid, b); };
        }
        celda.appendChild(box);
      });
    } finally {
      decorando = false;
    }
  }

  async function cargarMapa() {
    try {
      const r = await fetch('/api/v2/juez-ia/mapa', { cache: 'no-store' });
      const d = await r.json();
      if (r.ok && d && d.ok && d.mapa) {
        mapaPorId = d.mapa;
        mapaLista = Object.values(mapaPorId);
        decorarTabla();
      }
    } catch (_) {}
  }

  function crearModal() {
    if (document.getElementById('titanV17JuezModal')) return;
    injectStyles();
    const w = document.createElement('div');
    w.id = 'titanV17JuezModal';
    w.className = 't17-modal-bg';
    w.innerHTML = `
      <div class="t17-modal" style="max-width:520px">
        <div class="t17-m-head">
          <h3>\uD83E\uDDE0 Traducir y Verificar TODAS con IA</h3>
          <button type="button" class="t17-m-close" id="t17JzClose">&times;</button>
        </div>
        <div class="t17-m-body">
          <p style="margin:0;font-size:13px;color:var(--t17-text-soft,#cbd5e1)">
            La IA traducir\u00e1 al espa\u00f1ol qu\u00e9 necesita cada cliente y auditar\u00e1 si <b>Gemini 3.8 Flash (High)</b> basta para completarla sin saber scripting.
          </p>
          <div class="t17-checks">
            <label><input type="checkbox" id="t17JzDescartar"> \uD83D\uDDD1\uFE0F Marcar autom\u00e1ticamente como <b>descartado</b> las ofertas NO APTAS</label>
            <label><input type="checkbox" id="t17JzForzar"> \uD83D\uDD04 Re-analizar tambi\u00e9n las que ya estaban en cach\u00e9</label>
          </div>
          <div class="t17-ia-res" id="t17JzStatus"></div>
        </div>
        <div class="t17-m-foot">
          <button type="button" class="t17-btn-sec" id="t17JzCancel">Cerrar</button>
          <button type="button" class="primary" id="t17JzRun" style="padding:8px 16px">\uD83E\uDDE0 Verificar TODAS ahora</button>
        </div>
      </div>
    `;
    document.body.appendChild(w);
    const cerrar = () => w.classList.remove('open');
    w.addEventListener('click', (e) => { if (e.target === w) cerrar(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && w.classList.contains('open')) cerrar(); });
    w.querySelector('#t17JzClose').onclick = cerrar;
    w.querySelector('#t17JzCancel').onclick = cerrar;

    w.querySelector('#t17JzRun').onclick = async () => {
      const btn = w.querySelector('#t17JzRun');
      const box = w.querySelector('#t17JzStatus');
      btn.disabled = true; btn.textContent = '\u23F3 Analizando con IA...';
      box.className = 't17-ia-res ok';
      box.textContent = '\u23F3 Traduciendo y verificando todas las ofertas guardadas...';
      try {
        const r = await fetch('/api/v2/juez-ia/verificar-todas', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            forzar: w.querySelector('#t17JzForzar').checked,
            marcar_no_aptas: w.querySelector('#t17JzDescartar').checked,
            limite: 50,
          }),
        });
        const d = await r.json();
        if (!r.ok || !d || !d.ok) throw new Error((d && d.error) || 'Error del servidor');
        box.className = 't17-ia-res ok';
        box.textContent = `\u2705 Listo: ${d.total_verificadas} verificadas \u2022 ${d.aptas} APTAS \u2022 ${d.no_aptas} NO APTAS (${d.desde_cache} desde cach\u00e9).`;
        toast(`\uD83E\uDDE0 ${d.total_verificadas} ofertas verificadas (${d.aptas} APTAS)`, 'ok');
        await cargarMapa();
        if (typeof global.cargarDatos === 'function') global.cargarDatos(false);
      } catch (err) {
        box.className = 't17-ia-res bad';
        box.textContent = `\u274C ${err.message || 'No se pudo conectar con el servidor'}`;
      } finally {
        btn.disabled = false; btn.textContent = '\uD83E\uDDE0 Verificar TODAS ahora';
      }
    };
  }

  function montarBoton() {
    if (document.getElementById('titanV17JuezAllBtn')) return;
    const btn = document.createElement('button');
    btn.id = 'titanV17JuezAllBtn'; btn.type = 'button'; btn.className = 't17-btn-juez';
    btn.textContent = '\uD83E\uDDE0 Verificar Todas';
    btn.title = 'Traducir al espa\u00f1ol y verificar con IA si basta Gemini 3.8 Flash (High)';
    btn.onclick = () => { crearModal(); document.getElementById('titanV17JuezModal').classList.add('open'); };
    const ancla = document.getElementById('titanV17PerfilBtn')
      || document.getElementById('titanV17CleanBtn')
      || Array.from(document.querySelectorAll('header button, .topbar button, button')).find((b) => /\bCSV\b|Escanear/i.test(b.textContent || ''));
    if (ancla && ancla.parentNode) ancla.parentNode.insertBefore(btn, ancla.nextSibling);
  }

  function iniciarObservador() {
    const tbody = document.getElementById('tbodyLeads');
    if (!tbody || observador) return;
    observador = new MutationObserver(() => { if (!decorando) decorarTabla(); });
    observador.observe(tbody, { childList: true });
  }

  function init() {
    crearModal();
    let n = 0;
    const t = setInterval(() => {
      montarBoton(); iniciarObservador();
      if ((document.getElementById('titanV17JuezAllBtn') && observador) || ++n >= 20) clearInterval(t);
    }, 120);
    cargarMapa();
    setInterval(cargarMapa, 20000);
  }

  global.TitanJuezIAUI = { refrescar: cargarMapa, abrir: () => { crearModal(); document.getElementById('titanV17JuezModal').classList.add('open'); } };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})(window);
