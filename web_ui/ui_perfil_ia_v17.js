(function (global) {
  'use strict';

  function toast(m, t) {
    if (global.TitanUI && typeof global.TitanUI.toast === 'function') global.TitanUI.toast(m, t || 'ok');
    else if (typeof global.toast === 'function') global.toast(m);
  }

  function injectStyle() {
    if (document.getElementById('t17PerfilStyle')) return;
    const s = document.createElement('style');
    s.id = 't17PerfilStyle';
    s.textContent = `
      .t17-btn-ia{display:inline-flex;align-items:center;gap:6px;padding:7px 12px!important;font-size:12px!important;font-weight:700!important;color:#c7d2fe!important;background:linear-gradient(135deg,rgba(99,102,241,.24),rgba(34,211,238,.14))!important;border:1px solid rgba(99,102,241,.48)!important;border-radius:10px!important;cursor:pointer}
      .t17-btn-ia:hover{filter:brightness(1.12);box-shadow:0 4px 16px rgba(99,102,241,.3)}
      :root[data-titan-theme="light"] .t17-btn-ia{color:#4338ca!important;background:rgba(79,70,229,.1)!important}
      .t17-ia-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
      .t17-ia-field label{display:block;font-size:11.5px;color:var(--t17-muted,#8b9bb4);margin-bottom:4px}
      .t17-ia-field input{width:100%;padding:7px 10px!important;font-size:13px;box-sizing:border-box}
      .t17-ia-res{padding:10px 12px;border-radius:10px;font-size:12.5px;border:1px solid var(--t17-border);background:var(--t17-surface-elev);display:none}
      .t17-ia-res.ok{display:block;border-color:rgba(16,185,129,.5);color:#6ee7b7}
      .t17-ia-res.bad{display:block;border-color:rgba(244,63,94,.5);color:#fda4af}
      :root[data-titan-theme="light"] .t17-ia-res.ok{color:#047857}
      :root[data-titan-theme="light"] .t17-ia-res.bad{color:#be123c}
    `;
    document.head.appendChild(s);
  }

  function crearModal() {
    if (document.getElementById('titanV17PerfilModal')) return;
    injectStyle();
    const w = document.createElement('div');
    w.id = 'titanV17PerfilModal';
    w.className = 't17-modal-bg';
    w.innerHTML = `
      <div class="t17-modal" style="max-width:560px">
        <div class="t17-m-head">
          <h3>\uD83E\uDD16 Perfil Filtro: Gemini 3.8 Flash (High) + Menor</h3>
          <button type="button" class="t17-m-close" id="t17IaClose">&times;</button>
        </div>
        <div class="t17-m-body">
          <div class="t17-checks">
            <label><input type="checkbox" id="t17IaActivo"> \u2705 Activar filtro inteligente Gemini 3.8 Flash (High)</label>
            <label><input type="checkbox" id="t17IaKyc"> \uD83D\uDEE1\uFE0F Bloquear requisitos 18+, KYC, W-9, NDA y contratos formales</label>
            <label><input type="checkbox" id="t17IaEnt"> \uD83C\uDFA5 Bloquear entrevistas t\u00e9cnicas en vivo y daily standups</label>
            <label><input type="checkbox" id="t17IaPlats"> \uD83D\uDEAB Bloquear plataformas KYC estrictas (Freelancer, Upwork, Toptal, Fiverr)</label>
          </div>
          <div class="t17-ia-grid">
            <div class="t17-ia-field"><label>Presupuesto m\u00e1ximo (USD)</label><input type="number" id="t17IaMaxUsd" min="50" max="5000" step="50"></div>
            <div class="t17-ia-field"><label>M\u00e1ximo de ofertas/bids permitidos</label><input type="number" id="t17IaMaxBids" min="5" max="200" step="5"></div>
          </div>
          <div style="border-top:1px solid var(--t17-border);padding-top:12px;display:flex;flex-direction:column;gap:8px">
            <strong style="font-size:12.5px">\uD83E\uDDEA Probador r\u00e1pido de ofertas (sin gastar tokens)</strong>
            <input type="text" id="t17IaTestTit" placeholder="Pega el t\u00edtulo de una oferta (ej: Simple Google Sheets script $60)">
            <div style="display:flex;gap:8px">
              <input type="text" id="t17IaTestPlat" placeholder="Plataforma (ej: Reddit, GitHub, Freelancer.com)" style="flex:1">
              <button type="button" class="t17-btn-sec" id="t17IaTestBtn">Probar</button>
            </div>
            <div class="t17-ia-res" id="t17IaTestRes"></div>
          </div>
        </div>
        <div class="t17-m-foot">
          <button type="button" class="t17-btn-sec" id="t17IaCancel">Cerrar</button>
          <button type="button" class="primary" id="t17IaSave" style="padding:8px 16px">\uD83D\uDCBE Guardar Perfil</button>
        </div>
      </div>
    `;
    document.body.appendChild(w);
    const cerrar = () => w.classList.remove('open');
    w.addEventListener('click', (e) => { if (e.target === w) cerrar(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && w.classList.contains('open')) cerrar(); });
    w.querySelector('#t17IaClose').onclick = cerrar;
    w.querySelector('#t17IaCancel').onclick = cerrar;

    w.querySelector('#t17IaSave').onclick = async () => {
      const payload = {
        activo: w.querySelector('#t17IaActivo').checked,
        bloquear_kyc_y_edad: w.querySelector('#t17IaKyc').checked,
        bloquear_entrevistas_en_vivo: w.querySelector('#t17IaEnt').checked,
        bloquear_plataformas_kyc: w.querySelector('#t17IaPlats').checked,
        presupuesto_max_usd: Number(w.querySelector('#t17IaMaxUsd').value) || 600,
        max_bids_permitidos: Number(w.querySelector('#t17IaMaxBids').value) || 30,
      };
      try {
        const r = await fetch('/api/v2/perfil-ia', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        const d = await r.json();
        if (r.ok && d && d.ok) { toast('\uD83E\uDD16 Perfil Gemini 3.8 Flash guardado y activo', 'ok'); cerrar(); }
        else toast('\u274C No se pudo guardar el perfil', 'err');
      } catch (_) { toast('\u274C No se pudo conectar con el servidor', 'err'); }
    };

    w.querySelector('#t17IaTestBtn').onclick = async () => {
      const box = w.querySelector('#t17IaTestRes');
      try {
        const r = await fetch('/api/v2/perfil-ia/probar', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ titulo: w.querySelector('#t17IaTestTit').value, cuerpo: '', plataforma: w.querySelector('#t17IaTestPlat').value }),
        });
        const d = await r.json();
        if (!r.ok || !d || !d.ok) { toast('\u274C Error al probar la oferta', 'err'); return; }
        const res = d.resultado;
        box.className = 't17-ia-res ' + (res.bloqueado ? 'bad' : 'ok');
        box.textContent = res.bloqueado
          ? `\u26D4 BLOQUEADA: ${res.motivo}`
          : `\u2705 APTA PARA GEMINI 3.8 FLASH (+${res.delta_score} score)${res.hits_fit.length ? ' \u2022 Coincidencias: ' + res.hits_fit.join(', ') : ''}`;
      } catch (_) { toast('\u274C No se pudo conectar con el servidor', 'err'); }
    };

    ['#t17IaTestTit', '#t17IaTestPlat'].forEach((sel) => {
      w.querySelector(sel).addEventListener('keydown', (e) => { if (e.key === 'Enter') w.querySelector('#t17IaTestBtn').click(); });
    });
  }

  async function abrirModal() {
    crearModal();
    const w = document.getElementById('titanV17PerfilModal');
    w.classList.add('open');
    try {
      const r = await fetch('/api/v2/perfil-ia', { cache: 'no-store' });
      const d = await r.json();
      if (r.ok && d && d.ok && d.perfil) {
        const p = d.perfil;
        w.querySelector('#t17IaActivo').checked = Boolean(p.activo);
        w.querySelector('#t17IaKyc').checked = Boolean(p.bloquear_kyc_y_edad);
        w.querySelector('#t17IaEnt').checked = Boolean(p.bloquear_entrevistas_en_vivo);
        w.querySelector('#t17IaPlats').checked = Boolean(p.bloquear_plataformas_kyc);
        w.querySelector('#t17IaMaxUsd').value = p.presupuesto_max_usd || 600;
        w.querySelector('#t17IaMaxBids').value = p.max_bids_permitidos || 30;
      }
    } catch (_) {}
  }

  function montarBoton() {
    if (document.getElementById('titanV17PerfilBtn')) return;
    const btn = document.createElement('button');
    btn.id = 'titanV17PerfilBtn'; btn.type = 'button'; btn.className = 't17-btn-ia';
    btn.textContent = '\uD83E\uDD16 Perfil IA';
    btn.title = 'Configurar filtro Gemini 3.8 Flash (High) + Menor';
    btn.onclick = abrirModal;
    const ancla = document.getElementById('titanV17CleanBtn')
      || Array.from(document.querySelectorAll('header button, .topbar button, button')).find((b) => /\bCSV\b|Escanear/i.test(b.textContent || ''));
    if (ancla && ancla.parentNode) ancla.parentNode.insertBefore(btn, ancla.nextSibling);
  }

  function init() {
    crearModal();
    let n = 0;
    const t = setInterval(() => {
      montarBoton();
      if (document.getElementById('titanV17PerfilBtn') || ++n >= 12) clearInterval(t);
    }, 100);
  }

  global.TitanPerfilIAUI = { abrir: abrirModal };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})(window);
