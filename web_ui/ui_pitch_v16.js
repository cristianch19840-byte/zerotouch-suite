// ==================== ZERO-TOUCH TITAN-OS v16.0 — PITCH STUDIO A/B, AUDITOR 0-TOKENS & BANDIT TEMPLATES ====================
(function (global) {
  'use strict';

  const PSTATE = {
    hostId: 't16CrmBody',
    leadId: null,
    templates: [],
    stats: null,
    lastGen: null,
    lastAudit: null,
    auditTimer: null,
  };

  const U = () => global.TitanUI;
  const API = () => global.TitanAPI;

  async function render(hostId = 't16CrmBody', leadId = null) {
    PSTATE.hostId = hostId;
    if (leadId !== null) PSTATE.leadId = leadId;
    const host = document.getElementById(hostId);
    if (!host) return;

    const [rTpl, rStats, rLead] = await Promise.all([
      API().get('/api/v2/pitch/templates?bandit=true', { silent: true }),
      API().get('/api/v2/pitch/stats', { silent: true }),
      PSTATE.leadId ? API().get(`/api/v2/leads/${PSTATE.leadId}`, { silent: true }) : Promise.resolve(null),
    ]);

    if (rTpl?.ok) PSTATE.templates = rTpl.items || [];
    if (rStats?.ok) PSTATE.stats = rStats;
    const lead = rLead?.ok ? rLead.lead : null;

    const ab = PSTATE.stats?.analytics_ab || {};
    const porVar = ab.por_variante || [];
    const chartDonut = U().svgDonut(
      porVar.map((v, i) => ({
        label: `Var ${v.clave}`,
        value: Number(v.enviadas || 0),
        color: ['#22d3ee', '#a855f7', '#10b981', '#f59e0b'][i % 4],
      })),
      { size: 112, stroke: 14, centerText: ab.variante_ganadora ? `🏆 ${ab.variante_ganadora}` : 'A/B' }
    );

    const tplRows = PSTATE.templates.map((t) => `
      <div class="t16-agenda-row" style="align-items:flex-start;">
        <div style="flex:1;min-width:200px;">
          <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
            <b style="font-size:13px;color:var(--t16-text-0);">${U().escHtml(t.nombre)}</b>
            ${U().badge(t.plataforma, 'cyan')}
            ${U().badge(t.categoria, 'muted')}
            ${U().badge('UCB1: ' + (t.bandit_ucb1 ?? 0), 'purple')}
          </div>
          <div style="font-size:11.5px;color:var(--t16-muted);margin-top:4px;">
            Usos: <b>${t.usos}</b> &bull; Resp: <b>${t.respuestas}</b> (${t.tasa_respuesta_pct}%) &bull; Ganados: <b style="color:var(--t16-green);">${t.ganados}</b> (${t.tasa_cierre_pct}%) &bull; Wilson: <b>${t.wilson_score}</b>
          </div>
        </div>
        <div style="display:flex;gap:5px;flex-wrap:wrap;">
          <button class="t16-btn-xs" onclick="TitanPitchUI.loadTemplateIntoAuditor(${t.id})">📥 Probar</button>
          <button class="t16-btn-xs" onclick="TitanPitchUI.openTemplateModal(${t.id})">✏️</button>
          <button class="t16-btn-xs" onclick="TitanPitchUI.deleteTemplate(${t.id})">🗑️</button>
        </div>
      </div>
    `).join('') || U().renderEmptyState('Sin templates');

    host.innerHTML = `
      <div class="t16-kpi-grid">
        <div class="t16-kpi">
          <span class="t16-kpi-lbl">Propuestas Enviadas</span>
          <span class="t16-kpi-val">${ab.total_enviadas || 0}</span>
          <span class="t16-kpi-sub">Respuestas: ${ab.total_respondidas || 0} (${ab.tasa_respuesta_global_pct || 0}%)</span>
        </div>
        <div class="t16-kpi">
          <span class="t16-kpi-lbl">Tasa Cierre A/B</span>
          <span class="t16-kpi-val" style="color:var(--t16-green);">${ab.tasa_cierre_global_pct || 0}%</span>
          <span class="t16-kpi-sub">Ganadas: ${ab.total_ganadas || 0} &bull; Ganadora: <b>${U().escHtml(ab.variante_ganadora || '-')}</b></span>
        </div>
        <div class="t16-kpi">
          <span class="t16-kpi-lbl">Recomendado Reddit</span>
          <span class="t16-kpi-val" style="font-size:14px;color:var(--t16-cyan);">${U().escHtml(PSTATE.stats?.recomendado_reddit || '-')}</span>
          <span class="t16-kpi-sub">Freelancer: ${U().escHtml(PSTATE.stats?.recomendado_freelancer || '-')}</span>
        </div>
        <div class="t16-kpi" style="flex-direction:row;align-items:center;justify-content:space-between;">
          <div>
            <span class="t16-kpi-lbl">Distribución A/B</span>
            <div style="font-size:11.5px;color:var(--t16-muted);margin-top:6px;">${porVar.map((v) => `Var ${U().escHtml(v.clave)}: ${v.tasa_cierre_pct}%`).join('<br>') || 'Sin envíos'}</div>
          </div>
          ${chartDonut}
        </div>
      </div>

      <div class="t16-split-2" style="margin-bottom:14px;">
        <div class="t16-card-box">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;gap:8px;flex-wrap:wrap;">
            <h3 style="margin:0;font-size:14px;">⚡ Generador Pitch A/B + Auto-Refinamiento IA</h3>
            ${lead ? U().badge(`Lead #${lead.id}`, 'ok') : ''}
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:8px;">
            <input id="t16PGenLeadId" class="t16-input" type="number" placeholder="Lead ID (opc.)" value="${PSTATE.leadId || ''}">
            <select id="t16PGenPlat" class="t16-select">
              ${['reddit', 'freelancer', 'github', 'hackernews', 'remoto', 'general'].map((p) =>
                `<option value="${p}" ${(lead?.plataforma || '').toLowerCase().includes(p) ? 'selected' : ''}>${p}</option>`
              ).join('')}
            </select>
            <input id="t16PGenUsd" class="t16-input" type="number" placeholder="Precio USD" value="${Number(lead?.presupuesto_num || 250)}">
          </div>
          <input id="t16PGenTit" class="t16-input" style="width:100%;margin-bottom:8px;" placeholder="Título de la oferta..." value="${U().escHtml(lead?.titulo || '')}">
          <textarea id="t16PGenBody" class="t16-textarea" style="min-height:80px;margin-bottom:8px;" placeholder="Detalles del proyecto o requisitos clave...">${U().escHtml(lead?.notas || '')}</textarea>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
            <select id="t16PGenVars" class="t16-select"><option value="2">2 Variantes (A/B)</option><option value="3">3 Variantes (A/B/C)</option></select>
            <select id="t16PGenBandit" class="t16-select"><option value="ucb1">Bandit UCB1</option><option value="thompson">Thompson Sampling</option></select>
            <button class="t16-pill t16-pill-live" id="t16PGenBtn" onclick="TitanPitchUI.generateAB()">🚀 Generar Variantes A/B</button>
          </div>
          <div id="t16PGenOut" style="margin-top:12px;"></div>
        </div>

        <div class="t16-card-box">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
            <h3 style="margin:0;font-size:14px;">🔬 Auditor Anti-Cliché en Vivo (0 Tokens)</h3>
            <select id="t16PAudPlat" class="t16-select" onchange="TitanPitchUI.auditNow()">
              <option value="reddit">Reddit</option><option value="freelancer">Freelancer</option>
              <option value="github">GitHub</option><option value="hackernews">HN</option><option value="remoto">Remoto</option>
            </select>
          </div>
          <textarea id="t16PAudText" class="t16-textarea" style="min-height:135px;margin-bottom:8px;" placeholder="Pega o redacta tu pitch aquí para auditar clichés, gancho, CTA y personalización en tiempo real..." oninput="TitanPitchUI.scheduleAudit()"></textarea>
          <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px;">
            <button class="t16-pill" onclick="TitanPitchUI.auditNow()">🔍 Auditar Ahora</button>
            <button class="t16-pill t16-pill-timer-on" id="t16PImproveBtn" onclick="TitanPitchUI.improveManual()">✨ Auto-Mejorar con IA</button>
            <button class="t16-pill" onclick="TitanPitchUI.copyAuditorText()">📋 Copiar</button>
          </div>
          <div id="t16PAudOut">${U().renderEmptyState('Escribe un borrador para ver tu Score 0-100 y detector de clichés')}</div>
        </div>
      </div>

      <div class="t16-card-box">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;flex-wrap:wrap;gap:8px;">
          <h3 style="margin:0;font-size:14px;">📚 Biblioteca de Templates (Ranking Bandit UCB1 / Wilson)</h3>
          <button class="t16-pill t16-pill-live" onclick="TitanPitchUI.openTemplateModal(null)">+ Nuevo Template</button>
        </div>
        ${tplRows}
      </div>
    `;

    if (PSTATE.lastGen) renderGeneratedVariants(PSTATE.lastGen);
  }

  function scheduleAudit() {
    if (PSTATE.auditTimer) clearTimeout(PSTATE.auditTimer);
    PSTATE.auditTimer = setTimeout(auditNow, 380);
  }

  async function auditNow() {
    const txt = (document.getElementById('t16PAudText')?.value || '').trim();
    const out = document.getElementById('t16PAudOut');
    if (!out) return;
    if (!txt) {
      out.innerHTML = U().renderEmptyState('Escribe un borrador para auditar');
      return;
    }
    const plat = document.getElementById('t16PAudPlat')?.value || 'reddit';
    const oferta = `${document.getElementById('t16PGenTit')?.value || ''} ${document.getElementById('t16PGenBody')?.value || ''}`.trim();
    const r = await API().post('/api/v2/pitch/auditar', { texto: txt, plataforma: plat, oferta_texto: oferta }, { silent: true });
    if (!r?.ok) return;
    PSTATE.lastAudit = r.auditoria;
    renderAuditBox(out, r.auditoria);
  }

  function renderAuditBox(el, a) {
    const col = a.score_0_100 >= 80 ? 'var(--t16-green)' : (a.score_0_100 >= 62 ? 'var(--t16-cyan)' : 'var(--t16-red)');
    const subs = Object.entries(a.subscores || {}).map(([k, v]) => `
      <div style="display:flex;align-items:center;gap:8px;font-size:11px;margin-bottom:4px;">
        <span style="width:118px;color:var(--t16-muted);">${U().escHtml(k)}</span>
        <div class="t16-progress" style="flex:1;"><div class="t16-progress-fill" style="width:${Math.min(100, Number(v))}%;"></div></div>
        <span style="width:34px;text-align:right;font-family:var(--t16-mono);">${v}</span>
      </div>
    `).join('');

    el.innerHTML = `
      <div style="display:flex;gap:12px;align-items:center;margin-bottom:10px;">
        <div class="t16-score-ring" style="border-color:${col};color:${col};">
          <span style="font-size:18px;line-height:1;">${a.grado}</span>
          <span style="font-size:11px;">${a.score_0_100}</span>
        </div>
        <div style="flex:1;font-size:12px;">
          <div>Palabras: <b>${a.metricas?.palabras || 0}</b> &bull; Ratio You/I: <b>${a.metricas?.ratio_tu_yo ?? 0}</b> &bull; Overlap oferta: <b>${a.metricas?.overlap_pct ?? 0}%</b></div>
          <div style="margin-top:5px;display:flex;gap:5px;flex-wrap:wrap;">
            ${(a.cliches_detectados || []).map((c) => U().badge('🚫 ' + c, 'err')).join('')}
            ${(a.fortalezas || []).slice(0, 3).map((f) => U().badge('✓ ' + f, 'ok')).join('')}
          </div>
        </div>
      </div>
      ${subs}
      ${(a.mejoras_accionables || []).length ? `<div style="margin-top:8px;font-size:11.5px;color:var(--t16-amber);">💡 ${a.mejoras_accionables.map(U().escHtml).join(' &bull; ')}</div>` : ''}
    `;
  }

  async function improveManual() {
    const el = document.getElementById('t16PAudText');
    const txt = (el?.value || '').trim();
    if (!txt) return U().toast('Escribe primero un pitch para mejorar', 'err');
    const btn = document.getElementById('t16PImproveBtn');
    if (btn) btn.disabled = true;
    const plat = document.getElementById('t16PAudPlat')?.value || 'reddit';
    const oferta = `${document.getElementById('t16PGenTit')?.value || ''} ${document.getElementById('t16PGenBody')?.value || ''}`.trim();
    const r = await API().post('/api/v2/pitch/mejorar', { texto: txt, plataforma: plat, oferta_texto: oferta });
    if (btn) btn.disabled = false;
    if (r?.ok) {
      el.value = r.texto_mejorado || txt;
      U().toast(r.mejoro ? `Pitch mejorado: ${r.score_antes} -> ${r.score_despues} (+${r.delta_pts})` : 'Score ya era óptimo', 'ok');
      auditNow();
    }
  }

  async function generateAB() {
    const btn = document.getElementById('t16PGenBtn');
    const out = document.getElementById('t16PGenOut');
    const lid = Number(document.getElementById('t16PGenLeadId')?.value || 0) || null;
    const titulo = (document.getElementById('t16PGenTit')?.value || '').trim();
    const cuerpo = (document.getElementById('t16PGenBody')?.value || '').trim();
    if (!lid && !titulo && !cuerpo) return U().toast('Ingresa un Lead ID o título de oferta', 'err');

    if (btn) btn.disabled = true;
    if (out) out.innerHTML = '<div class="t16-skeleton" style="height:120px;"></div>';

    const r = await API().post('/api/v2/pitch/generar', {
      lead_id: lid,
      titulo,
      cuerpo,
      plataforma: document.getElementById('t16PGenPlat')?.value || 'reddit',
      precio_objetivo_usd: Number(document.getElementById('t16PGenUsd')?.value || 0),
      num_variantes: Number(document.getElementById('t16PGenVars')?.value || 2),
      modo_bandit: document.getElementById('t16PGenBandit')?.value || 'ucb1',
      auto_refinar: true,
    });
    if (btn) btn.disabled = false;
    if (!r?.ok) {
      if (out) out.innerHTML = U().renderEmptyState('Error generando pitch');
      return;
    }
    PSTATE.lastGen = r;
    renderGeneratedVariants(r);
  }

  function renderGeneratedVariants(r) {
    const out = document.getElementById('t16PGenOut');
    if (!out) return;
    const cards = (r.variantes || []).map((v, idx) => {
      const esTop = v.variante === r.mejor_variante;
      return `
        <div class="t16-event-item lvl-${esTop ? 'ok' : 'info'}" style="margin-bottom:10px;">
          <div class="t16-event-head">
            <span class="t16-event-topic">${esTop ? '🏆 ' : ''}VARIANTE ${U().escHtml(v.variante)} — ${U().escHtml(v.enfoque)}</span>
            <div>${U().badge(`Grado ${v.grado} (${v.score_0_100}/100)`, esTop ? 'ok' : 'cyan')} ${U().badge(U().fmtUSD(v.precio_sugerido_usd, 0), 'muted')}</div>
          </div>
          <pre style="white-space:pre-wrap;font-family:inherit;font-size:12px;color:var(--t16-text-0);margin:6px 0;background:rgba(5,8,17,0.65);padding:8px 10px;border-radius:8px;">${U().escHtml(v.texto)}</pre>
          <div style="display:flex;gap:6px;flex-wrap:wrap;">
            <button class="t16-btn-xs" onclick="TitanPitchUI.copyVariant(${idx})">📋 Copiar</button>
            <button class="t16-btn-xs" onclick="TitanPitchUI.sendVariantToAuditor(${idx})">🔬 Editar en Auditor</button>
            <button class="t16-btn-xs" style="border-color:var(--t16-green);color:#4ade80;" onclick="TitanPitchUI.registerVariantSent(${idx})">📤 Registrar Envío CRM</button>
          </div>
        </div>
      `;
    }).join('');
    out.innerHTML = `
      <div style="font-size:11.5px;color:var(--t16-muted);margin-bottom:8px;">
        Motor: <b>${U().escHtml(r.proveedor_ia)}/${U().escHtml(r.modelo_ia)}</b> &bull; Template base: <b>${U().escHtml(r.template_recomendado)}</b> &bull; ${r.duracion_ms}ms ${r.auto_refinado ? '&bull; ✨ Auto-Refinado' : ''}
      </div>
      ${cards}
    `;
  }

  function copyVariant(idx) {
    const v = PSTATE.lastGen?.variantes?.[idx];
    if (!v) return;
    navigator.clipboard?.writeText(v.texto);
    U().toast(`Variante ${v.variante} copiada al portapapeles`, 'ok');
  }

  function sendVariantToAuditor(idx) {
    const v = PSTATE.lastGen?.variantes?.[idx];
    const el = document.getElementById('t16PAudText');
    if (!v || !el) return;
    el.value = v.texto;
    auditNow();
  }

  async function registerVariantSent(idx) {
    const v = PSTATE.lastGen?.variantes?.[idx];
    if (!v) return;
    const lid = Number(document.getElementById('t16PGenLeadId')?.value || PSTATE.lastGen?.lead_id || 0) || null;
    const r = await API().post('/api/v2/pitch/enviar', {
      lead_id: lid,
      texto_pitch: v.texto,
      variante: v.variante,
      precio_cotizado_usd: v.precio_sugerido_usd,
      template_nombre: v.template_base,
      plataforma: PSTATE.lastGen?.plataforma || 'reddit',
    });
    if (r?.ok) {
      U().toast(`📤 Propuesta #${r.propuesta.id} (Var ${v.variante}) registrada en CRM`, 'ok');
      render(PSTATE.hostId, lid);
    }
  }

  async function loadTemplateIntoAuditor(tplId) {
    const r = await API().post('/api/v2/pitch/templates/render', {
      template_id: tplId,
      variables: {
        proyecto: (document.getElementById('t16PGenTit')?.value || 'your Python automation'),
        precio: `$${Number(document.getElementById('t16PGenUsd')?.value || 250)} USD`,
      },
    });
    if (r?.ok) {
      const el = document.getElementById('t16PAudText');
      if (el) el.value = r.texto;
      auditNow();
      U().toast(`Template '${r.template_nombre}' renderizado en Auditor`, 'ok');
    }
  }

  function copyAuditorText() {
    const txt = document.getElementById('t16PAudText')?.value || '';
    if (!txt) return;
    navigator.clipboard?.writeText(txt);
    U().toast('Pitch copiado al portapapeles', 'ok');
  }

  function openTemplateModal(tplId = null) {
    const cur = tplId ? PSTATE.templates.find((t) => Number(t.id) === Number(tplId)) : null;
    U().openModal({
      title: cur ? `✏️ Editar Template: ${cur.nombre}` : '➕ Nuevo Template de Propuesta',
      html: `
        <div style="display:flex;flex-direction:column;gap:9px;">
          <input id="t16TplNom" class="t16-input" placeholder="Nombre único (ej. Reddit_Scraper_VIP)" value="${U().escHtml(cur?.nombre || '')}">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            <select id="t16TplPlat" class="t16-select">
              ${['reddit', 'freelancer', 'github', 'hackernews', 'remoto', 'general'].map((p) =>
                `<option value="${p}" ${(cur?.plataforma || 'reddit') === p ? 'selected' : ''}>${p}</option>`
              ).join('')}
            </select>
            <input id="t16TplCat" class="t16-input" placeholder="Categoría (Scraping, Bots...)" value="${U().escHtml(cur?.categoria || 'Python')}">
          </div>
          <textarea id="t16TplBody" class="t16-textarea" style="min-height:150px;" placeholder="Usa variables {{cliente|there}}, {{proyecto}}, {{stack}}, {{precio}}, {{tiempo_entrega}}...">${U().escHtml(cur?.cuerpo || '')}</textarea>
        </div>
      `,
      footerHtml: `<button class="t16-pill" onclick="TitanUI.closeModal()">Cancelar</button><button class="t16-pill t16-pill-live" id="t16TplSave">Guardar Template</button>`,
      onOpen: () => {
        document.getElementById('t16TplSave')?.addEventListener('click', async () => {
          const payload = {
            nombre: (document.getElementById('t16TplNom')?.value || '').trim(),
            plataforma: document.getElementById('t16TplPlat')?.value || 'general',
            categoria: (document.getElementById('t16TplCat')?.value || 'Python').trim(),
            cuerpo: (document.getElementById('t16TplBody')?.value || '').trim(),
          };
          if (!payload.nombre || !payload.cuerpo) return U().toast('Nombre y cuerpo son obligatorios', 'err');
          const r = cur
            ? await API().patch(`/api/v2/pitch/templates/${cur.id}`, payload)
            : await API().post('/api/v2/pitch/templates', payload);
          if (r?.ok) {
            U().toast(`Template '${payload.nombre}' guardado`, 'ok');
            U().closeModal(true);
            render(PSTATE.hostId, PSTATE.leadId);
          }
        });
      },
    });
  }

  async function deleteTemplate(tplId) {
    const ok = await U().confirmDialog('Eliminar Template', '¿Eliminar este template de tu biblioteca?', 'Eliminar');
    if (!ok) return;
    const r = await API().del(`/api/v2/pitch/templates/${tplId}`);
    if (r?.ok) {
      U().toast('Template eliminado', 'ok');
      render(PSTATE.hostId, PSTATE.leadId);
    }
  }

  global.TitanPitchUI = {
    render,
    scheduleAudit,
    auditNow,
    improveManual,
    generateAB,
    copyVariant,
    sendVariantToAuditor,
    registerVariantSent,
    loadTemplateIntoAuditor,
    copyAuditorText,
    openTemplateModal,
    deleteTemplate,
  };
})(window);