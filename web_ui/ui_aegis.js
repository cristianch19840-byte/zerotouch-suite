// ==================== ZERO-TOUCH UI v15.0 — AEGIS-X LAB (FORENSE & ML) ====================
let AEGIS_DATA = null;

const AEGIS_PRESETS = {
  oro: {
    titulo: "[Hiring] Urgent Python Playwright scraper for 5 Shopify stores -> CSV ($350 USD)",
    cuerpo: "Need a clean Python Playwright script to extract product titles, variants, SKU and prices from 5 Shopify stores into UTF-8 CSV with retries. Not looking for WordPress. Happy to pay 50% upfront via Binance or PayPal today.",
    fuente: "r/forhire",
    plataforma: "Reddit",
    monto: 350,
  },
  scam: {
    titulo: "[Hiring] Qu\u200bick K\u0423C v\u0435rify Binance \u0430ccount ($100)",
    cuerpo: "Easy money! Contact me on w.h.a.t.s.a.p.p via https://bit.ly/fast-verify-99 and run our test_setup.exe first.",
    fuente: "Freelancer.com",
    plataforma: "Freelancer",
    monto: 100,
  },
  lowball: {
    titulo: "[Hiring] Build Uber clone mobile app for iOS and Android ($40)",
    cuerpo: "Need full Python backend, admin dashboard, Stripe payments and iOS and Android app from scratch. Fixed budget $40, cheapest bid wins. Should only take 10 minutes for an expert.",
    fuente: "r/slavelabour",
    plataforma: "Reddit",
    monto: 40,
  },
  geo: {
    titulo: "Senior Python Automation Engineer ($130k/yr)",
    cuerpo: "Full-time salaried role with 401k, health, dental, and vision. Must be US citizen, W2 only. Hybrid 3 days/week in Austin TX.",
    fuente: "RemoteOK",
    plataforma: "RemoteOK",
    monto: 130000,
  },
};

function cargarPresetAegis(clave) {
  const p = AEGIS_PRESETS[clave];
  if (!p) return;
  const setV = (id, v) => { const e = document.getElementById(id); if (e) e.value = v; };
  setV('agSimTitulo', p.titulo);
  setV('agSimCuerpo', p.cuerpo);
  setV('agSimPlat', p.plataforma);
  setV('agSimMonto', p.monto);
  correrSimulacionAegis();
}

async function cargarAegisLab() {
  const d = await apiJson('/api/aegis_resumen');
  if (d.error) return toast('Error cargando AEGIS Lab: ' + d.error, 'err');
  AEGIS_DATA = d;
  renderPerfilesAegis(d);
  renderAuditoriaAegis(d);
  renderInsightsMlAegis(d);
}

function renderPerfilesAegis(d) {
  const wrap = document.getElementById('agPerfilesGrid');
  if (!wrap) return;
  const activo = d.perfil_activo || 'equilibrado';
  const perfiles = d.perfiles || [];

  const setV = (id, v) => { const e = document.getElementById(id); if (e) e.value = v; };
  setV('agPresMin', d.presupuesto_minimo_usd ?? 20);
  setV('agWhitelist', (d.whitelist_vip || []).join(', '));
  const simSel = document.getElementById('agSimPerfil');
  if (simSel && !simSel.dataset.init) {
    simSel.value = activo;
    simSel.dataset.init = '1';
  }

  wrap.innerHTML = perfiles.map(p => {
    const isAct = p.nombre === activo;
    return `
      <div class="plat-card" style="cursor:pointer;${isAct ? 'border-color:var(--accent);box-shadow:0 0 20px var(--accent-soft);' : ''}" onclick="activarPerfilAegis('${esc(p.nombre)}')">
        <div class="plat-head">
          <div class="plat-title">
            <span class="status-dot ${isAct ? 'st-ok' : 'st-idle'}"></span>
            <span style="text-transform:uppercase;">${esc(p.nombre.replace('_', ' '))}</span>
          </div>
          <span class="badge ${isAct ? 'b-remoto' : 'b-freelance'}">${isAct ? 'ACTIVO' : 'Usar'}</span>
        </div>
        <div class="muted" style="font-size:12px;">${esc(p.descripcion)}</div>
        <div class="plat-metrics">
          <div class="plat-m"><span>Umbral</span><b>${p.umbral_aprobacion}</b></div>
          <div class="plat-m"><span>Min USD</span><b class="c-green">$${p.presupuesto_minimo_usd}</b></div>
          <div class="plat-m"><span>Min $/hr</span><b class="c-cyan">$${p.tarifa_minima_usd_hr}</b></div>
        </div>
      </div>
    `;
  }).join('');
}

async function activarPerfilAegis(nombre) {
  const d = await apiJson('/api/aegis_perfil', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ perfil: nombre }),
  });
  if (d.error) return toast(d.error, 'err');
  const simSel = document.getElementById('agSimPerfil');
  if (simSel) simSel.value = nombre;
  toast(`Perfil AEGIS-X cambiado a ${nombre.toUpperCase()}`, 'ok');
  cargarAegisLab();
}

async function guardarReglasAegis() {
  const presMin = parseFloat(document.getElementById('agPresMin')?.value || '20');
  const rawWl = document.getElementById('agWhitelist')?.value || '';
  const wl = rawWl.split(',').map(s => s.trim()).filter(Boolean);
  const d = await apiJson('/api/aegis_perfil', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ presupuesto_minimo_usd: presMin, palabras_extra_whitelist: wl }),
  });
  if (d.error) return toast(d.error, 'err');
  toast('Reglas AEGIS-X (piso USD y Whitelist VIP) guardadas', 'ok');
  cargarAegisLab();
}

async function correrSimulacionAegis(btn) {
  const titulo = (document.getElementById('agSimTitulo')?.value || '').trim();
  const cuerpo = (document.getElementById('agSimCuerpo')?.value || '').trim();
  const plataforma = document.getElementById('agSimPlat')?.value || 'Reddit';
  const perfil = document.getElementById('agSimPerfil')?.value || 'equilibrado';
  const monto_api = parseFloat(document.getElementById('agSimMonto')?.value || '0') || 0;

  if (!titulo && !cuerpo) return toast('Escribe un titulo o carga un preset para simular', 'err');
  if (btn) btn.disabled = true;

  const out = document.getElementById('agSimResultado');
  if (out) out.innerHTML = '<div class="muted">Ejecutando 7 capas forenses de AEGIS-X (0 tokens)...</div>';

  const d = await apiJson('/api/aegis_simular', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ titulo, cuerpo, plataforma, fuente: plataforma, perfil, monto_api }),
  });
  if (btn) btn.disabled = false;
  if (d.error) {
    if (out) out.innerHTML = `<div class="prebox c-red">${esc(d.error)}</div>`;
    return;
  }

  renderRadiografiaVisual(d.radiografia, d.texto_reporte);
}

function renderRadiografiaVisual(r, textoPlano) {
  const out = document.getElementById('agSimResultado');
  if (!out || !r) return;

  const ok = !!r.aprobado;
  const col = ok ? 'var(--green)' : 'var(--red)';
  const bg = ok ? 'var(--green-soft)' : 'var(--red-soft)';
  const tax = r.taxonomia || {};
  const intent = r.intencion || {};
  const econ = r.economia || {};
  const sec = r.seguridad || {};
  const ded = r.dedup || {};
  const ml = r.ml_crm || {};
  const doc = r.documento || {};
  const idTxt = regClip(textoPlano || '');

  const senalesHtml = (r.senales_top || []).map(s => {
    const pos = Number(s.peso) >= 0;
    return `
      <div class="legend-row" style="padding:5px 8px;border-radius:7px;background:rgba(5,7,14,0.65);border:1px solid var(--border);font-size:11.5px;">
        <div style="min-width:0;">
          <b class="${pos ? 'c-green' : 'c-red'}">${pos ? '+' : ''}${s.peso}</b>
          <span style="margin-left:6px;color:var(--text-0);font-weight:600;">${esc(s.codigo)}</span>
          <span class="muted" style="margin-left:6px;">${esc(s.descripcion)}</span>
        </div>
        <span class="kbd">${esc(s.zona)}</span>
      </div>
    `;
  }).join('') || '<div class="muted">Sin senales destacadas</div>';

  out.innerHTML = `
    <div style="border:1px solid ${col};background:${bg};border-radius:12px;padding:14px 16px;margin-bottom:14px;">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
        <div>
          <div style="font-size:15px;font-weight:800;color:${col};">${ok ? 'APROBADO PARA GEMINI' : 'BLOQUEADO 0-TOKENS'} &bull; ${esc(r.decision)}</div>
          <div style="font-size:12.5px;color:var(--text-0);margin-top:3px;">${esc(r.razon_principal)}</div>
        </div>
        <div style="text-align:right;font-family:var(--font-mono);">
          <div style="font-size:24px;font-weight:800;color:${col};">${r.score_0_100}/100</div>
          <div class="muted">${r.tiempo_ms} ms &bull; Cola #${r.prioridad_cola}</div>
        </div>
      </div>
      ${(r.etiquetas || []).length ? `<div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap;">${r.etiquetas.map(t => `<span class="badge b-freelance">${esc(t)}</span>`).join('')}</div>` : ''}
    </div>

    <div class="grid-3" style="margin-bottom:14px;">
      <div class="plat-m" style="text-align:left;padding:10px 12px;">
        <span>Capa 2 &bull; Taxonomia</span>
        <b class="${tax.es_tech ? 'c-green' : 'c-red'}">${tax.score_0_100 ?? 0}/100 (${esc(tax.familia_principal || 'n/a')})</b>
        <div class="muted" style="font-size:11px;margin-top:4px;">Skills: ${esc((tax.skills || []).slice(0, 5).join(', ') || 'ninguna')}</div>
        ${(tax.combos || []).length ? `<div class="c-cyan" style="font-size:11px;margin-top:2px;">Combos: ${esc(tax.combos.join(', '))}</div>` : ''}
      </div>

      <div class="plat-m" style="text-align:left;padding:10px 12px;">
        <span>Capa 3 &bull; Intencion &amp; LATAM</span>
        <b class="${intent.es_comprador_real ? 'c-green' : 'c-red'}">${esc(intent.tipo || 'n/a')}</b>
        <div class="muted" style="font-size:11px;margin-top:4px;">Modalidad: ${esc(intent.modalidad || 'n/a')} (${Math.round((intent.confianza || 0) * 100)}%)</div>
        <div class="${intent.bloqueo_geo ? 'c-red' : 'c-green'}" style="font-size:11px;margin-top:2px;">${intent.bloqueo_geo ? 'Geo Bloq: ' + esc(intent.motivo_geo) : 'Apto remoto LATAM/Global'}</div>
      </div>

      <div class="plat-m" style="text-align:left;padding:10px 12px;">
        <span>Capa 4 &bull; Economia</span>
        <b class="${econ.lowball ? 'c-red' : (econ.high_ticket ? 'c-green' : 'c-cyan')}">${esc(econ.etiqueta || 'Por definir')}</b>
        <div class="muted" style="font-size:11px;margin-top:4px;">Esfuerzo: ${econ.horas_min ?? 0}-${econ.horas_max ?? 0}h &bull; Eff: $${econ.tarifa_eff_usd_hr ?? 0}/hr</div>
        <div class="muted" style="font-size:11px;margin-top:2px;">Score Econ: ${econ.score_0_100 ?? 0}/100 (${esc(econ.moneda || 'USD')})</div>
      </div>

      <div class="plat-m" style="text-align:left;padding:10px 12px;">
        <span>Capa 5 &bull; Escudo Seguridad</span>
        <b class="${sec.bloqueo_duro ? 'c-red' : (sec.riesgo_0_100 >= 25 ? 'c-amber' : 'c-green')}">${esc((sec.nivel || 'seguro').toUpperCase())} (${sec.riesgo_0_100 ?? 0}/100)</b>
        <div class="muted" style="font-size:11px;margin-top:4px;">${esc((sec.banderas_rojas || []).slice(0, 2).join(' • ') || 'Sin banderas rojas')}</div>
      </div>

      <div class="plat-m" style="text-align:left;padding:10px 12px;">
        <span>Capa 1 &amp; 6 &bull; Forense / SimHash</span>
        <b class="c-cyan">${esc((doc.idioma || 'en').toUpperCase())} &bull; Cal: ${doc.calidad ?? 0}/100</b>
        <div class="muted" style="font-size:11px;margin-top:4px;">SimHash: <code>${esc(ded.simhash_hex || '0')}</code></div>
        <div class="muted" style="font-size:11px;margin-top:2px;">Homoglifos: ${doc.homoglifos ?? 0} &bull; Inv: ${doc.invisibles ?? 0}</div>
      </div>

      <div class="plat-m" style="text-align:left;padding:10px 12px;">
        <span>Capa 7 &bull; ML Naive Bayes CRM</span>
        <b class="${ml.habilitado ? 'c-purple' : ''}">${ml.habilitado ? (ml.prob_ganar_pct + '% cierre (' + (ml.ajuste_score >= 0 ? '+' : '') + ml.ajuste_score + ' pts)') : 'En aprendizaje (<4 leads)'}</b>
        <div class="muted" style="font-size:11px;margin-top:4px;">Muestras CRM: ${ml.muestras ?? 0}</div>
        ${(ml.impulsoras || []).length ? `<div class="muted" style="font-size:11px;margin-top:2px;">${esc(ml.impulsoras.slice(0, 3).join(', '))}</div>` : ''}
      </div>
    </div>

    <div class="field">
      <label><span>Top Senales Explicables</span><button class="btn btn-ghost btn-xs" onclick="copyId('${idTxt}')">Copiar Radiografia TXT</button></label>
      <div style="display:flex;flex-direction:column;gap:5px;">${senalesHtml}</div>
    </div>
  `;
}

function renderAuditoriaAegis(d) {
  const aud = d.auditoria || {};
  const ded = d.dedup_stats || {};
  const setT = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
  setT('agAudTot', aud.total_auditadas || 0);
  setT('agAudApr', `${aud.total_aprobadas || 0} (${aud.tasa_aprobacion_pct || 0}%)`);
  setT('agDedRam', ded.en_ram || 0);

  renderBarrasModernas('agAudBarras', aud.por_decision || [], '', ' ofertas');

  const box = document.getElementById('agAudLista');
  if (!box) return;
  const recs = aud.recientes || [];
  if (!recs.length) {
    box.innerHTML = '<div class="muted">Corre un escaneo normal para poblar el log de auditoria forense.</div>';
    return;
  }
  box.innerHTML = recs.slice(0, 18).map(r => {
    const cls = r.aprobado ? 'log-ok' : 'log-err';
    const ic = r.aprobado ? '[PASS]' : '[STOP]';
    return `<div class="term-line ${cls}">${ic} [${String(r.score).padStart(4)}/100 | ${esc(r.plataforma).padEnd(11)}] ${esc((r.titulo || '').slice(0, 52))} &rarr; ${esc(r.decision)} (${esc((r.razon || '').slice(0, 68))})</div>`;
  }).join('');
}

function renderInsightsMlAegis(d) {
  const ml = d.ml_insights || {};
  const box = document.getElementById('agMlResumen');
  if (!box) return;

  const posTok = (ml.top_tokens?.positivos || []).map(([k, v]) => `<span class="badge b-remoto">+${esc(k)} (${v})</span>`).join(' ');
  const negTok = (ml.top_tokens?.negativos || []).map(([k, v]) => `<span class="badge b-hot">${esc(k)} (${v})</span>`).join(' ');

  const platsHtml = (ml.rentabilidad_plataformas || []).slice(0, 5).map(p =>
    `<div class="legend-row"><span><b>${esc(p.nombre)}</b> (${p.positivos} ok / ${p.descartados} desc)</span><span class="c-green" style="font-family:var(--font-mono);">$${p.usd_ganados} (${p.tasa_exito_pct}%)</span></div>`
  ).join('') || '<div class="muted">Aun no hay suficientes leads marcados como ganado/descartado.</div>';

  box.innerHTML = `
    <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px;">
      <span class="badge ${ml.modelo_habilitado ? 'b-remoto' : 'b-custom'}">${ml.modelo_habilitado ? 'MODELO ACTIVO' : 'MODO COLD-START'}</span>
      <span class="muted">Positivos: <b>${ml.muestras_pos || 0}</b> &bull; Negativos: <b>${ml.muestras_neg || 0}</b> &bull; Vocab: <b>${ml.vocab_size || 0}</b> &bull; F1 CV: <b>${ml.cv_f1 || 0}</b></span>
    </div>
    <div class="field"><label>Palabras que MAS te cierran clientes</label><div style="display:flex;gap:5px;flex-wrap:wrap;">${posTok || '<span class="muted">Marca 2+ leads ganados y 2+ descartados para activar</span>'}</div></div>
    <div class="field"><label>Palabras que sueles DESCARTAR</label><div style="display:flex;gap:5px;flex-wrap:wrap;">${negTok || '<span class="muted">Sin suficientes muestras aun</span>'}</div></div>
    <div class="field"><label>Rentabilidad por Plataforma</label><div style="display:flex;flex-direction:column;gap:6px;">${platsHtml}</div></div>
  `;
}

async function reentrenarMlWeb(btn) {
  if (btn) btn.disabled = true;
  const d = await apiJson('/api/aegis_reentrenar', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
  if (btn) btn.disabled = false;
  if (d.error) return toast(d.error, 'err');
  toast(`Modelo ML re-entrenado (${d.muestras_pos} pos / ${d.muestras_neg} neg)`, 'ok');
  cargarAegisLab();
}

async function enviarFeedbackMlWeb(etiqueta) {
  const titulo = (document.getElementById('agFbTitulo')?.value || '').trim();
  const plataforma = document.getElementById('agFbPlat')?.value || 'Reddit';
  if (!titulo) return toast('Escribe el titulo o ejemplo para entrenar al modelo', 'err');
  const d = await apiJson('/api/aegis_feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ titulo, plataforma, etiqueta }),
  });
  if (d.error) return toast(d.error, 'err');
  document.getElementById('agFbTitulo').value = '';
  toast(etiqueta ? 'Ejemplo POSITIVO aprendido por AEGIS-X' : 'Ejemplo NEGATIVO aprendido por AEGIS-X', 'ok');
  cargarAegisLab();
}