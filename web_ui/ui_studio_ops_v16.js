// ==================== ZERO-TOUCH TITAN-OS v16.0 — ENGINEERING STUDIO (WORKFLOWS IFTTT, WHOP FACTORY & OPS HEALTH) ====================
(function (global) {
  'use strict';

  const OSTATE = {
    subtab: 'sandbox', // sandbox | workflows | factory | ops
    wfData: null,
    wfSimOut: null,
    facProductos: [],
    facLicencias: [],
    facCode: 'import json\nAPI_KEY = "sk-proj-1234567890abcdefghijklmnopQRSTUVWX"\nprint("Ready:", bool(API_KEY))\n',
    facNombre: 'Shopify Radar Pro',
    facSanResult: null,
    facBuildResult: null,
    opsAi: null,
    opsHttp: null,
    opsDrift: null,
    opsWhatIf: null,
    opsAegis: null,
    opsAiTestOut: '',
  };

  const U = () => global.TitanUI;
  const API = () => global.TitanAPI;

  async function init(initialSubtab = null) {
    if (initialSubtab) OSTATE.subtab = initialSubtab;
    renderTabs();
    await refreshSubtab();
  }

  function renderTabs() {
    const bar = document.getElementById('t16EngSubtabs');
    if (!bar) return;
    const tabs = [
      { id: 'sandbox', label: '🐍 Sandbox IDE & Auto-Fix' },
      { id: 'workflows', label: '⚙️ Workflows IFTTT' },
      { id: 'factory', label: '🏭 Whop Factory & Licencias' },
      { id: 'ops', label: '🩺 AI Router, Circuits & Drift' },
    ];
    bar.innerHTML = tabs.map((t) =>
      `<button class="t16-subtab ${OSTATE.subtab === t.id ? 'active' : ''}" onclick="TitanStudioUI.switchSubtab('${t.id}')">${t.label}</button>`
    ).join('');
  }

  async function switchSubtab(id) {
    OSTATE.subtab = id;
    renderTabs();
    await refreshSubtab();
  }

  async function refreshSubtab() {
    if (OSTATE.subtab === 'sandbox' && global.TitanSandboxUI) {
      await global.TitanSandboxUI.render('t16EngBody');
    } else if (OSTATE.subtab === 'workflows') {
      await loadWorkflows();
    } else if (OSTATE.subtab === 'factory') {
      await loadFactory();
    } else if (OSTATE.subtab === 'ops') {
      await loadOps();
    }
  }

  function sendCodeToFactory(code, nombreSugerido) {
    OSTATE.facCode = code || OSTATE.facCode;
    if (nombreSugerido) OSTATE.facNombre = nombreSugerido;
    switchSubtab('factory');
    U().toast('Código transferido a Whop Factory v16', 'ok');
  }

  // ==================== 1. WORKFLOWS IFTTT BUILDER & DRY-RUN SIMULATOR ====================
  async function loadWorkflows() {
    const r = await API().get('/api/v2/workflows');
    if (r?.ok) OSTATE.wfData = r;
    renderWorkflows();
  }

  function renderWorkflows() {
    const host = document.getElementById('t16EngBody');
    if (!host) return;
    const d = OSTATE.wfData || {};
    const reglas = d.reglas || [];
    const hist = d.historial || [];

    const reglasHtml = reglas.length
      ? reglas.map((reg) => `
          <div class="t16-wf-card ${reg.activa ? '' : 'paused'}">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
              <div>
                <b style="font-size:13.5px;color:var(--t16-text-0);">#${reg.id} ${U().escHtml(reg.nombre)}</b>
                <div style="margin-top:4px;display:flex;gap:6px;flex-wrap:wrap;align-items:center;">
                  ${U().badge(reg.activa ? 'ACTIVA' : 'PAUSADA', reg.activa ? 'ok' : 'muted')}
                  <span class="t16-code-inline">${U().escHtml(reg.evento_disparador)}</span>
                  ${U().badge(`${reg.ejecuciones || 0} ejec.`, 'cyan')}
                  ${U().badge(`CD ${reg.cooldown_seg || 0}s`, 'muted')}
                </div>
              </div>
              <div style="display:flex;gap:6px;">
                <button class="t16-btn-xs" onclick="TitanStudioUI.toggleWorkflow(${reg.id})">${reg.activa ? '⏸️ Pausar' : '▶️ Activar'}</button>
                <button class="t16-btn-xs" onclick="TitanStudioUI.deleteWorkflow(${reg.id})">🗑️</button>
              </div>
            </div>
            <div style="font-size:11.5px;color:var(--t16-muted);margin-top:8px;">
              Acciones: ${(reg.acciones || []).map((a) => `<span class="t16-code-inline">${U().escHtml(a.tipo)}</span>`).join(' ') || 'ninguna'}
            </div>
          </div>
        `).join('')
      : U().renderEmptyState('Sin reglas IFTTT', 'Instala los 5 presets o crea tu primera regla.');

    const simResHtml = OSTATE.wfSimOut
      ? (OSTATE.wfSimOut.resultados || []).map((x) => `
          <div class="t16-event-item lvl-${x.matched ? 'ok' : 'info'}">
            <div class="t16-event-head">
              <span class="t16-event-topic">#${x.regla_id} ${U().escHtml(x.regla_nombre)}</span>
              ${U().badge(x.matched ? 'MATCH · EJECUTARÍA' : (x.omitida_por || 'NO MATCH'), x.matched ? 'ok' : 'muted')}
            </div>
            <div class="t16-event-body">
              Trazas: ${U().escHtml((x.trazas || []).join(' | '))}
              ${(x.acciones || []).map((a) => `<div style="color:var(--t16-cyan);">→ [${U().escHtml(a.tipo)}] ${U().escHtml(a.detalle)}</div>`).join('')}
            </div>
          </div>
        `).join('') || U().renderEmptyState('Ninguna regla escucha este tópico')
      : '';

    const histHtml = hist.length
      ? hist.slice(0, 12).map((h) => `
          <div class="t16-stat-line">
            <span><b>${U().escHtml(h.regla_nombre)}</b> <span class="t16-code-inline">${U().escHtml(h.topico)}</span></span>
            <span style="font-size:11px;color:var(--t16-muted);">${h.duracion_ms}ms &bull; ${U().fmtRelTime(h.ts_epoch)}</span>
          </div>
        `).join('')
      : U().renderEmptyState('Sin ejecuciones recientes en memoria');

    host.innerHTML = `
      <div class="t16-kpi-grid">
        <div class="t16-kpi"><span class="t16-kpi-lbl">Motor IFTTT</span><span class="t16-kpi-val" style="color:${d.activo ? 'var(--t16-green)' : 'var(--t16-amber)'};">${d.activo ? 'ACTIVO' : 'INACTIVO'}</span><span class="t16-kpi-sub">${d.reglas_activas || 0}/${d.total_reglas || 0} reglas activas</span></div>
        <div class="t16-kpi"><span class="t16-kpi-lbl">Acciones Nativas</span><span class="t16-kpi-val">${(d.acciones_disponibles || []).length}</span><span class="t16-kpi-sub">${(d.operadores_disponibles || []).length} operadores AND/OR/NOT</span></div>
      </div>

      <div class="t16-toolbar">
        <button class="t16-pill t16-pill-live" onclick="TitanStudioUI.openNewWorkflowModal()">+ Nueva Regla IFTTT</button>
        <button class="t16-pill" onclick="TitanStudioUI.installWfPresets()">📦 Instalar Presets Faltantes</button>
        <button class="t16-pill" onclick="TitanStudioUI.switchSubtab('workflows')">🔄 Refrescar</button>
      </div>

      <div class="t16-split-2">
        <div>
          <h3 style="margin:0 0 10px 0;font-size:14px;">📜 Reglas Configuradas (${reglas.length})</h3>
          ${reglasHtml}
        </div>
        <div>
          <div class="t16-card-box" style="margin-bottom:14px;">
            <h3 style="margin:0 0 8px 0;font-size:14px;">🧪 Simulador Dry-Run (0 Efectos Secundarios)</h3>
            <input id="t16WfSimTop" class="t16-input" style="width:100%;margin-bottom:8px;" value="crm.lead.nuevo" placeholder="Tópico del evento (ej. crm.lead.nuevo)">
            <textarea id="t16WfSimPay" class="t16-textarea" style="min-height:85px;font-family:var(--t16-mono);font-size:11.5px;margin-bottom:8px;">{"lead_id": 99, "titulo": "Shopify Playwright Scraper", "score": 9, "presupuesto_num": 350, "plataforma": "Reddit"}</textarea>
            <button class="t16-pill t16-pill-timer-on" onclick="TitanStudioUI.simulateWorkflow()">⚡ Simular Evento</button>
            <div style="margin-top:10px;">${simResHtml}</div>
          </div>
          <div class="t16-card-box">
            <h3 style="margin:0 0 8px 0;font-size:14px;">🕒 Ejecuciones Recientes</h3>
            ${histHtml}
          </div>
        </div>
      </div>
    `;
  }

  async function toggleWorkflow(id) {
    const r = await API().post(`/api/v2/workflows/${id}/toggle`, {});
    if (r?.ok) {
      U().toast(`Regla #${id} -> ${r.regla.activa ? 'ACTIVA' : 'PAUSADA'}`, 'ok');
      loadWorkflows();
    }
  }

  async function deleteWorkflow(id) {
    const ok = await U().confirmDialog('Eliminar Regla', `¿Eliminar la regla IFTTT #${id}?`, 'Eliminar');
    if (!ok) return;
    const r = await API().del(`/api/v2/workflows/${id}`);
    if (r?.ok) {
      U().toast(`Regla #${id} eliminada`, 'ok');
      loadWorkflows();
    }
  }

  async function installWfPresets() {
    const r = await API().post('/api/v2/workflows/presets', {});
    if (r?.ok) {
      U().toast(`${r.instaladas} preset(s) instalados`, 'ok');
      loadWorkflows();
    }
  }

  async function simulateWorkflow() {
    const topico = (document.getElementById('t16WfSimTop')?.value || '').trim();
    const rawPay = document.getElementById('t16WfSimPay')?.value || '{}';
    let payload = {};
    try { payload = JSON.parse(rawPay); } catch (_) { return U().toast('JSON de payload inválido', 'err'); }
    const r = await API().post('/api/v2/workflows/simular', { topico, payload });
    if (r?.ok) {
      OSTATE.wfSimOut = r;
      renderWorkflows();
    }
  }

  function openNewWorkflowModal() {
    const ops = OSTATE.wfData?.operadores_disponibles || ['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'icontains', 'in'];
    const accs = OSTATE.wfData?.acciones_disponibles || ['crear_tarea_crm', 'log_evento', 'telegram_alert', 'webhook_http', 'sonido_alerta'];
    U().openModal({
      title: '➕ Crear Regla de Automatización IFTTT',
      html: `
        <div style="display:flex;flex-direction:column;gap:9px;">
          <input id="t16WfNom" class="t16-input" placeholder="Nombre de la regla (ej. Alerta Bounty $300+)">
          <div style="display:grid;grid-template-columns:2fr 1fr;gap:8px;">
            <input id="t16WfEvt" class="t16-input" value="crm.lead.nuevo" placeholder="Evento (ej. crm.lead.*, finanzas.*)">
            <input id="t16WfCd" class="t16-input" type="number" value="60" placeholder="Cooldown (s)">
          </div>
          <div style="font-size:11.5px;color:var(--t16-muted);">Condición principal (opcional):</div>
          <div style="display:grid;grid-template-columns:1.4fr 1fr 1fr;gap:6px;">
            <input id="t16WfCampo" class="t16-input" value="payload.score" placeholder="Campo">
            <select id="t16WfOp" class="t16-select">${ops.map((o) => `<option value="${o}" ${o === 'gte' ? 'selected' : ''}>${o}</option>`).join('')}</select>
            <input id="t16WfVal" class="t16-input" value="8" placeholder="Valor">
          </div>
          <div style="font-size:11.5px;color:var(--t16-muted);">Acción a ejecutar:</div>
          <select id="t16WfAccTipo" class="t16-select">${accs.map((a) => `<option value="${a}">${a}</option>`).join('')}</select>
          <textarea id="t16WfAccParams" class="t16-textarea" style="min-height:80px;font-family:var(--t16-mono);font-size:11.5px;">{"titulo": "Revisar: {{payload.titulo|Lead}}", "prioridad": "alta", "vence_en_horas": 12}</textarea>
        </div>
      `,
      footerHtml: `<button class="t16-pill" onclick="TitanUI.closeModal()">Cancelar</button><button class="t16-pill t16-pill-live" id="t16WfSaveBtn">Guardar Regla</button>`,
      onOpen: () => {
        document.getElementById('t16WfSaveBtn')?.addEventListener('click', async () => {
          const nombre = (document.getElementById('t16WfNom')?.value || '').trim();
          const evento_disparador = (document.getElementById('t16WfEvt')?.value || '').trim();
          if (!nombre || !evento_disparador) return U().toast('Nombre y evento son obligatorios', 'err');
          let params = {};
          try { params = JSON.parse(document.getElementById('t16WfAccParams')?.value || '{}'); } catch (_) { return U().toast('JSON de params inválido', 'err'); }
          const campo = (document.getElementById('t16WfCampo')?.value || '').trim();
          const rawV = document.getElementById('t16WfVal')?.value || '';
          const valNorm = rawV !== '' && !Number.isNaN(Number(rawV)) ? Number(rawV) : rawV;
          const condiciones = campo ? [{ campo, op: document.getElementById('t16WfOp')?.value || 'eq', valor: valNorm }] : [];
          const acciones = [{ tipo: document.getElementById('t16WfAccTipo')?.value || 'log_evento', params }];
          const r = await API().post('/api/v2/workflows', {
            nombre, evento_disparador, condiciones, acciones,
            cooldown_seg: Number(document.getElementById('t16WfCd')?.value || 60),
            activa: true,
          });
          if (r?.ok) {
            U().toast(`Regla #${r.regla.id} creada`, 'ok');
            U().closeModal(true);
            loadWorkflows();
          }
        });
      },
    });
  }

  // ==================== 2. WHOP / SAAS FACTORY & LICENCIAS HMAC-SHA256 ====================
  async function loadFactory() {
    const [rP, rL] = await Promise.all([
      API().get('/api/v2/factory/productos?limit=40', { silent: true }),
      API().get('/api/v2/factory/licencias?limit=60', { silent: true }),
    ]);
    if (rP?.ok) OSTATE.facProductos = rP.items || [];
    if (rL?.ok) OSTATE.facLicencias = rL.items || [];
    renderFactory();
  }

  function renderFactory() {
    const host = document.getElementById('t16EngBody');
    if (!host) return;

    const prodsHtml = OSTATE.facProductos.length
      ? OSTATE.facProductos.map((p) => `
          <div class="t16-stat-line" style="flex-wrap:wrap;gap:6px;">
            <div>
              <b>${U().escHtml(p.nombre)}</b> <span class="t16-code-inline">v${U().escHtml(p.version)}</span>
              ${U().badge(p.slug, 'cyan')}
              <div style="font-size:11px;color:var(--t16-muted);">${Math.round((p.tamano_bytes || 0) / 1024 * 10) / 10} KB &bull; SHA256: <code>${U().escHtml(String(p.sha256_zip || '').slice(0, 14))}...</code></div>
            </div>
            <div style="display:flex;gap:5px;">
              <button class="t16-btn-xs" onclick="TitanStudioUI.verifyZip('${U().escHtml(String(p.ruta_zip || '').replace(/\\/g, '\\\\'))}')">✅ SHA-256</button>
              <button class="t16-btn-xs" onclick="TitanStudioUI.openEmitLicenseModal('${U().escHtml(p.slug)}')">🔑 Licencia</button>
              <button class="t16-btn-xs" onclick="TitanStudioUI.deleteProduct(${p.id})">🗑️</button>
            </div>
          </div>
        `).join('')
      : U().renderEmptyState('Sin productos construidos aún');

    const licsHtml = OSTATE.facLicencias.length
      ? OSTATE.facLicencias.slice(0, 15).map((l) => `
          <div class="t16-event-item lvl-${l.revocada ? 'error' : 'ok'}" style="margin-bottom:8px;">
            <div class="t16-event-head">
              <span class="t16-event-topic">${U().escHtml(l.licencia_id)} &bull; ${U().escHtml(l.producto_slug)}</span>
              <div>${U().badge(l.tier, 'purple')} ${U().badge(l.revocada ? 'REVOCADA' : 'ACTIVA', l.revocada ? 'err' : 'ok')}</div>
            </div>
            <div style="font-size:11.5px;color:var(--t16-text-1);">Cliente: <b>${U().escHtml(l.cliente)}</b> &bull; Seats: ${l.seats} ${l.hwid ? `&bull; HWID: ${U().escHtml(l.hwid)}` : ''}</div>
            <div class="t16-lic-key" style="margin-top:5px;">${U().escHtml(l.clave_licencia)}</div>
            <div style="display:flex;gap:6px;margin-top:6px;">
              <button class="t16-btn-xs" onclick="navigator.clipboard?.writeText('${U().escHtml(l.clave_licencia)}');TitanUI.toast('Clave copiada','ok')">📋 Copiar Clave</button>
              ${!l.revocada ? `<button class="t16-btn-xs" onclick="TitanStudioUI.revokeLicense('${U().escHtml(l.licencia_id)}')">🚫 Revocar</button>` : ''}
            </div>
          </div>
        `).join('')
      : U().renderEmptyState('Sin licencias emitidas');

    const buildOut = OSTATE.facBuildResult ? `
      <div class="t16-event-item lvl-ok" style="margin-top:10px;">
        <div class="t16-event-head">
          <span class="t16-event-topic">📦 PAQUETE LISTO: ${U().escHtml(OSTATE.facBuildResult.slug)} v${U().escHtml(OSTATE.facBuildResult.version)}</span>
          ${U().badge(`${OSTATE.facBuildResult.tamano_zip_kb} KB`, 'ok')}
        </div>
        <div class="t16-event-body">
          ZIP: <code>${U().escHtml(OSTATE.facBuildResult.ruta_zip)}</code><br>
          Secretos removidos: <b>${OSTATE.facBuildResult.sanitizacion?.total_secretos_removidos || 0}</b> &bull; Archivos: ${(OSTATE.facBuildResult.archivos_empaquetados || []).length}
          ${OSTATE.facBuildResult.licencia_demo ? `<div class="t16-lic-key" style="margin-top:6px;">Demo Key: ${U().escHtml(OSTATE.facBuildResult.licencia_demo.clave_licencia)}</div>` : ''}
        </div>
      </div>
    ` : '';

    const sanOut = OSTATE.facSanResult ? `
      <div class="t16-event-item lvl-${OSTATE.facSanResult.ok ? 'ok' : 'error'}" style="margin-top:10px;">
        <div class="t16-event-head">
          <span class="t16-event-topic">🧹 SANITIZACIÓN AST</span>
          ${U().badge(`${OSTATE.facSanResult.reporte?.total_secretos_removidos || 0} secreto(s) externalizados`, 'cyan')}
        </div>
        <div class="t16-event-body">
          PIP detectados: <span class="t16-code-inline">${U().escHtml((OSTATE.facSanResult.reporte?.requisitos_pip || []).join(', ') || 'solo stdlib')}</span>
          ${(OSTATE.facSanResult.reporte?.hallazgos || []).map((h) => `<div>• [L${h.linea}] ${U().escHtml(h.descripcion)} → <code>${U().escHtml(h.variable_config)}</code></div>`).join('')}
        </div>
      </div>
    ` : '';

    host.innerHTML = `
      <div class="t16-split-2" style="margin-bottom:14px;">
        <div class="t16-card-box">
          <h3 style="margin:0 0 10px 0;font-size:14px;">🏭 Empaquetador Comercial Whop / Gumroad (.ZIP + SHA-256)</h3>
          <div style="display:grid;grid-template-columns:2fr 1fr 1fr;gap:8px;margin-bottom:8px;">
            <input id="t16FacNom" class="t16-input" value="${U().escHtml(OSTATE.facNombre)}" placeholder="Nombre del producto">
            <input id="t16FacVer" class="t16-input" value="1.0.0" placeholder="Versión">
            <input id="t16FacUsd" class="t16-input" type="number" value="29" placeholder="Starter USD">
          </div>
          <input id="t16FacDesc" class="t16-input" style="width:100%;margin-bottom:8px;" value="Automated Python tool ready for 1-click local deployment." placeholder="Descripción corta comercial">
          <textarea id="t16FacCode" class="t16-textarea" style="min-height:150px;font-family:var(--t16-mono);font-size:11.5px;margin-bottom:8px;">${U().escHtml(OSTATE.facCode)}</textarea>
          <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:10px;font-size:12px;">
            <label><input id="t16FacGuard" type="checkbox" checked> Inyectar <code>license_guard.py</code> HMAC-SHA256</label>
            <label><input id="t16FacMkt" type="checkbox"> Generar Marketing Kit con IA</label>
          </div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;">
            <button class="t16-pill" onclick="TitanStudioUI.previewSanitize()">🧹 Previsualizar Sanitización</button>
            <button class="t16-pill t16-pill-live" id="t16FacBuildBtn" onclick="TitanStudioUI.buildProduct()">📦 Construir .ZIP Comercial</button>
          </div>
          ${sanOut}${buildOut}
        </div>

        <div class="t16-card-box">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
            <h3 style="margin:0;font-size:14px;">🔑 Consola de Licencias Offline HMAC-SHA256</h3>
            <button class="t16-pill t16-pill-live" onclick="TitanStudioUI.openEmitLicenseModal('')">+ Emitir Clave</button>
          </div>
          <div style="display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap;">
            <input id="t16LicChkSlug" class="t16-input" style="width:140px;" placeholder="slug producto">
            <input id="t16LicChkKey" class="t16-input" style="flex:1;" placeholder="Pegar ZT1.... para verificar">
            <button class="t16-pill" onclick="TitanStudioUI.verifyLicenseQuick()">Verificar</button>
          </div>
          <div style="max-height:360px;overflow-y:auto;">${licsHtml}</div>
        </div>
      </div>

      <div class="t16-card-box">
        <h3 style="margin:0 0 8px 0;font-size:14px;">📦 Productos Empaquetados (${OSTATE.facProductos.length})</h3>
        ${prodsHtml}
      </div>
    `;
  }

  async function previewSanitize() {
    OSTATE.facCode = document.getElementById('t16FacCode')?.value || '';
    const r = await API().post('/api/v2/factory/sanitizar', { codigo: OSTATE.facCode });
    if (r) {
      OSTATE.facSanResult = r;
      renderFactory();
    }
  }

  async function buildProduct() {
    OSTATE.facNombre = (document.getElementById('t16FacNom')?.value || '').trim();
    OSTATE.facCode = document.getElementById('t16FacCode')?.value || '';
    if (!OSTATE.facNombre || !OSTATE.facCode.trim()) return U().toast('Nombre y código son obligatorios', 'err');
    const btn = document.getElementById('t16FacBuildBtn');
    if (btn) btn.disabled = true;
    const r = await API().post('/api/v2/factory/construir', {
      nombre: OSTATE.facNombre,
      version: (document.getElementById('t16FacVer')?.value || '1.0.0').trim(),
      descripcion_corta: (document.getElementById('t16FacDesc')?.value || '').trim(),
      precio_starter_usd: Number(document.getElementById('t16FacUsd')?.value || 29),
      incluir_license_guard: !!document.getElementById('t16FacGuard')?.checked,
      generar_marketing_ia: !!document.getElementById('t16FacMkt')?.checked,
      codigo_fuente: OSTATE.facCode,
      emitir_licencia_demo: true,
    });
    if (btn) btn.disabled = false;
    if (r?.ok) {
      OSTATE.facBuildResult = r;
      U().toast(`📦 Producto '${r.slug}' v${r.version} empaquetado (${r.tamano_zip_kb} KB)`, 'ok');
      await loadFactory();
    }
  }

  async function verifyZip(rutaZip) {
    const r = await API().post('/api/v2/factory/verificar-zip', { ruta_zip: rutaZip });
    if (r) U().toast(r.ok ? `✅ ZIP íntegro (${r.verificados} archivos verificados SHA-256)` : `❌ Corrupto: ${r.error || (r.errores || []).join(', ')}`, r.ok ? 'ok' : 'err');
  }

  async function deleteProduct(id) {
    const ok = await U().confirmDialog('Eliminar Producto', `¿Eliminar registro del producto #${id}?`, 'Eliminar');
    if (!ok) return;
    const r = await API().del(`/api/v2/factory/productos/${id}`);
    if (r?.ok) {
      U().toast('Producto eliminado', 'ok');
      loadFactory();
    }
  }

  function openEmitLicenseModal(slugDefault = '') {
    U().openModal({
      title: '🔑 Emitir Licencia Offline HMAC-SHA256',
      html: `
        <div style="display:flex;flex-direction:column;gap:9px;">
          <input id="t16LeSlug" class="t16-input" value="${U().escHtml(slugDefault)}" placeholder="Slug del producto (ej. shopify-radar-pro)">
          <input id="t16LeCli" class="t16-input" placeholder="Email o nombre del comprador">
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;">
            <select id="t16LeTier" class="t16-select"><option value="starter">Starter</option><option value="pro" selected>Pro</option><option value="agency">Agency</option><option value="lifetime">Lifetime</option></select>
            <input id="t16LeDias" class="t16-input" type="number" value="0" placeholder="Días (0=Lifetime)">
            <input id="t16LeSeats" class="t16-input" type="number" value="1" min="1" placeholder="Seats">
          </div>
          <input id="t16LeHwid" class="t16-input" placeholder="HWID opcional (dejar vacío para cualquier PC)">
        </div>
      `,
      footerHtml: `<button class="t16-pill" onclick="TitanUI.closeModal()">Cancelar</button><button class="t16-pill t16-pill-live" id="t16LeGo">Emitir Clave ZT1</button>`,
      onOpen: () => {
        document.getElementById('t16LeGo')?.addEventListener('click', async () => {
          const producto_slug = (document.getElementById('t16LeSlug')?.value || '').trim();
          const cliente = (document.getElementById('t16LeCli')?.value || '').trim();
          if (!producto_slug || !cliente) return U().toast('Slug y cliente son obligatorios', 'err');
          const r = await API().post('/api/v2/factory/licencias/emitir', {
            producto_slug,
            cliente,
            tier: document.getElementById('t16LeTier')?.value || 'pro',
            dias_validez: Number(document.getElementById('t16LeDias')?.value || 0),
            seats: Number(document.getElementById('t16LeSeats')?.value || 1),
            hwid: (document.getElementById('t16LeHwid')?.value || '').trim(),
          });
          if (r?.ok) {
            navigator.clipboard?.writeText(r.licencia.clave_licencia);
            U().toast(`🔑 Licencia ${r.licencia.licencia_id} emitida y copiada`, 'ok');
            U().closeModal(true);
            loadFactory();
          }
        });
      },
    });
  }

  async function verifyLicenseQuick() {
    const slug = (document.getElementById('t16LicChkSlug')?.value || '').trim();
    const key = (document.getElementById('t16LicChkKey')?.value || '').trim();
    if (!slug || !key) return U().toast('Ingresa slug y clave ZT1', 'err');
    const r = await API().post('/api/v2/factory/licencias/verificar', { producto_slug: slug, clave_licencia: key });
    if (r && r.verificacion) {
      const v = r.verificacion;
      U().toast(v.valida ? `✅ Válida (${v.cliente} · ${v.tier})` : `❌ Inválida: ${v.motivo}`, v.valida ? 'ok' : 'err');
    }
  }

  async function revokeLicense(licId) {
    const ok = await U().confirmDialog('Revocar Licencia', `¿Revocar definitivamente la licencia ${licId}?`, 'Revocar');
    if (!ok) return;
    const r = await API().post(`/api/v2/factory/licencias/${encodeURIComponent(licId)}/revocar`, { motivo: 'Revocada desde Studio v16' });
    if (r?.ok) {
      U().toast(`Licencia ${licId} revocada`, 'warn');
      loadFactory();
    }
  }

  // ==================== 3. OPS CENTER: AI ROUTER, CIRCUIT BREAKERS, AEGIS DRIFT & DB ====================
  async function loadOps() {
    const [rAi, rHttp, rDrift, rAg] = await Promise.all([
      API().get('/api/v2/ai/salud', { silent: true }),
      API().get('/api/v2/http/salud', { silent: true }),
      API().get('/api/v2/aegis/drift', { silent: true }),
      API().get('/api/v2/aegis/resumen?limit=10', { silent: true }),
    ]);
    if (rAi?.ok) OSTATE.opsAi = rAi;
    if (rHttp?.ok) OSTATE.opsHttp = rHttp.http;
    if (rDrift?.ok) OSTATE.opsDrift = rDrift.drift;
    if (rAg?.ok) OSTATE.opsAegis = rAg;
    renderOps();
  }

  function renderOps() {
    const host = document.getElementById('t16EngBody');
    if (!host) return;
    const ai = OSTATE.opsAi?.ai || {};
    const estrList = OSTATE.opsAi?.estrategias || ['cloud_first', 'local_first', 'economy', 'cloud_only', 'local_only'];
    const bud = ai.budget_cloud_hoy || {};
    const cbs = OSTATE.opsHttp?.circuit_breakers || [];
    const drift = OSTATE.opsDrift || {};
    const dTono = drift.nivel_alerta === 'critico' ? 'err' : (drift.nivel_alerta === 'moderado' ? 'warn' : 'ok');

    const cbRows = cbs.length
      ? cbs.map((c) => `
          <div class="t16-stat-line">
            <span><b>${U().escHtml(c.dominio)}</b> <small style="color:var(--t16-muted);">(${c.tasa_exito_pct}% ok &bull; ${c.latencia_ema_ms}ms)</small></span>
            <div>${U().badge(c.estado.toUpperCase(), c.estado === 'closed' ? 'ok' : (c.estado === 'open' ? 'err' : 'warn'))}</div>
          </div>
        `).join('')
      : U().renderEmptyState('Todos los circuitos limpios (CLOSED)');

    const wiBox = OSTATE.opsWhatIf ? (OSTATE.opsWhatIf.disponible ? `
      <div class="t16-stat-line" style="margin-top:8px;border-color:var(--t16-border-strong);">
        <span>Umbral <b>${OSTATE.opsWhatIf.nuevo_umbral}</b> sobre ${OSTATE.opsWhatIf.muestra} ofertas: ${OSTATE.opsWhatIf.aprobadas_actual} &rarr; <b>${OSTATE.opsWhatIf.aprobadas_proyectadas}</b></span>
        ${U().badge(`Δ ${OSTATE.opsWhatIf.delta_tokens_ia_est} tokens IA`, OSTATE.opsWhatIf.delta_tokens_ia_est <= 0 ? 'ok' : 'warn')}
      </div>
    ` : `<div style="font-size:11.5px;color:var(--t16-muted);margin-top:6px;">${U().escHtml(OSTATE.opsWhatIf.motivo || 'Sin datos')}</div>`) : '';

    host.innerHTML = `
      <div class="t16-kpi-grid">
        <div class="t16-kpi">
          <span class="t16-kpi-lbl">AI Router Estrategia</span>
          <span class="t16-kpi-val" style="font-size:16px;color:var(--t16-cyan);">${U().escHtml(ai.estrategia || 'cloud_first')}</span>
          <span class="t16-kpi-sub">Cloud hoy: ${bud.pct || 0}% (${(bud.usados || 0).toLocaleString()} tok)</span>
        </div>
        <div class="t16-kpi">
          <span class="t16-kpi-lbl">Caché IA L1/L2</span>
          <span class="t16-kpi-val" style="color:var(--t16-green);">${ai.cache?.hit_rate_pct || 0}%</span>
          <span class="t16-kpi-sub">RAM: ${ai.cache?.en_ram || 0} &bull; SQLite: ${ai.cache?.en_sqlite || 0}</span>
        </div>
        <div class="t16-kpi">
          <span class="t16-kpi-lbl">AEGIS-X PSI Drift</span>
          <span class="t16-kpi-val" style="color:var(--t16-${dTono === 'ok' ? 'green' : (dTono === 'warn' ? 'amber' : 'red')});">${drift.psi ?? 0}</span>
          <span class="t16-kpi-sub">${U().badge(String(drift.nivel_alerta || 'normal').toUpperCase(), dTono)} &bull; Δ ${drift.delta_tasa_pct ?? 0}%</span>
        </div>
        <div class="t16-kpi">
          <span class="t16-kpi-lbl">HTTP Shield ETag/304</span>
          <span class="t16-kpi-val">${OSTATE.opsHttp?.cache_http?.hits_304 || 0}</span>
          <span class="t16-kpi-sub">TTL hits: ${OSTATE.opsHttp?.cache_http?.hits_ttl || 0} &bull; Circuitos: ${cbs.length}</span>
        </div>
      </div>

      <div class="t16-split-2" style="margin-bottom:14px;">
        <div class="t16-card-box">
          <h3 style="margin:0 0 10px 0;font-size:14px;">🧠 AI Router Multi-Modelo (Gemini + Ollama Local)</h3>
          <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px;">
            <select id="t16OpsEstr" class="t16-select">
              ${estrList.map((e) => `<option value="${e}" ${ai.estrategia === e ? 'selected' : ''}>${e}</option>`).join('')}
            </select>
            <input id="t16OpsBud" class="t16-input" type="number" value="${bud.limite || 800000}" style="width:120px;" title="Límite diario tokens cloud">
            <button class="t16-pill t16-pill-live" onclick="TitanStudioUI.saveAiStrategy()">Aplicar</button>
            <button class="t16-pill" onclick="TitanStudioUI.pruneAiCache()">🧹 Podar Caché</button>
          </div>
          <div style="font-size:11.5px;color:var(--t16-muted);margin-bottom:8px;">
            Gemini Keys: <b>${ai.proveedores?.gemini?.keys_count || 0}</b> &bull;
            Ollama: <b>${ai.proveedores?.ollama?.disponible ? 'ONLINE (' + U().escHtml(ai.proveedores?.ollama?.modelo_default) + ')' : 'OFFLINE'}</b>
          </div>
          <div style="display:flex;gap:6px;">
            <input id="t16OpsPrompt" class="t16-input" style="flex:1;" placeholder="Prompt rápido de diagnóstico IA..." value="Responde solo OK_TITAN_V16">
            <button class="t16-pill" onclick="TitanStudioUI.testAiPrompt()">⚡ Probar</button>
          </div>
          ${OSTATE.opsAiTestOut ? `<pre class="t16-console ok" style="margin-top:8px;">${U().escHtml(OSTATE.opsAiTestOut)}</pre>` : ''}
        </div>

        <div class="t16-card-box">
          <h3 style="margin:0 0 10px 0;font-size:14px;">🎛️ AEGIS-X v16 Calibración F-beta &amp; What-If</h3>
          <p style="font-size:12px;color:var(--t16-text-1);margin:0 0 10px 0;">${U().escHtml(drift.recomendacion || '')}</p>
          <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px;">
            <button class="t16-pill t16-pill-live" onclick="TitanStudioUI.autoCalibrateAegis()">🎛️ Auto-Calibrar Perfiles</button>
            <button class="t16-pill" onclick="TitanStudioUI.runDbBackup()">💾 Backup SQLite SHA-256</button>
            <button class="t16-pill" onclick="TitanStudioUI.runDbOptimize()">🧹 Optimizar WAL</button>
          </div>
          <div style="display:flex;gap:6px;align-items:center;">
            <input id="t16OpsWiU" class="t16-input" type="number" value="55" min="25" max="90" style="width:90px;">
            <button class="t16-pill" onclick="TitanStudioUI.runWhatIf()">🔮 Simular What-If Umbral</button>
          </div>
          ${wiBox}
        </div>
      </div>

      <div class="t16-card-box">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
          <h3 style="margin:0;font-size:14px;">🔌 HTTP Shield — Circuit Breakers por Dominio</h3>
          <div style="display:flex;gap:6px;">
            <button class="t16-pill" onclick="TitanStudioUI.resetCircuits()">🔌 Reset Todos</button>
            <button class="t16-pill" onclick="TitanStudioUI.switchSubtab('ops')">🔄 Refrescar</button>
          </div>
        </div>
        ${cbRows}
      </div>
    `;
  }

  async function saveAiStrategy() {
    const r = await API().post('/api/v2/ai/estrategia', {
      estrategia: document.getElementById('t16OpsEstr')?.value || 'cloud_first',
      budget_tokens_cloud_dia: Number(document.getElementById('t16OpsBud')?.value || 800000),
    });
    if (r?.ok) {
      U().toast(`Estrategia IA: ${r.estrategia}`, 'ok');
      loadOps();
    }
  }

  async function pruneAiCache() {
    const r = await API().post('/api/v2/ai/cache/podar', {});
    if (r?.ok) {
      U().toast(`Caché IA podada (${r.borradas} entradas)`, 'ok');
      loadOps();
    }
  }

  async function testAiPrompt() {
    const prompt = (document.getElementById('t16OpsPrompt')?.value || '').trim();
    if (!prompt) return;
    const r = await API().post('/api/v2/ai/test', { prompt, max_tokens: 128 });
    OSTATE.opsAiTestOut = r?.ok
      ? `[${r.meta?.proveedor}/${r.meta?.modelo} · ${r.meta?.latencia_ms}ms${r.meta?.desde_cache ? ' · CACHE' : ''}]\n${r.texto}`
      : `ERROR: ${r?.meta?.error || r?.error || 'Sin respuesta'}`;
    renderOps();
  }

  async function autoCalibrateAegis() {
    const r = await API().post('/api/v2/aegis/calibrar', { aplicar: true });
    if (r?.ok) {
      U().toast('Calibración F-beta ejecutada', 'ok');
      loadOps();
    }
  }

  async function runWhatIf() {
    const u = Number(document.getElementById('t16OpsWiU')?.value || 55);
    const r = await API().get(`/api/v2/aegis/what-if?umbral=${u}`);
    if (r?.ok) {
      OSTATE.opsWhatIf = r.what_if;
      renderOps();
    }
  }

  async function resetCircuits() {
    const r = await API().post('/api/v2/http/circuit/reset', {});
    if (r?.ok) {
      U().toast(`${r.reiniciados} circuit breaker(s) reiniciados`, 'ok');
      loadOps();
    }
  }

  async function runDbBackup() {
    const r = await API().post('/api/v2/system/db/backup', {});
    if (r?.ok) U().toast(`💾 Backup OK: ${r.backup.archivo} (SHA256 ${String(r.backup.sha256 || '').slice(0, 12)})`, 'ok');
  }

  async function runDbOptimize() {
    const r = await API().post('/api/v2/system/db/optimize', {});
    if (r?.ok) U().toast(`🧹 DB WAL optimizada en ${r.duracion_ms}ms`, 'ok');
  }

  global.TitanStudioUI = {
    init,
    switchSubtab,
    sendCodeToFactory,
    toggleWorkflow,
    deleteWorkflow,
    installWfPresets,
    simulateWorkflow,
    openNewWorkflowModal,
    previewSanitize,
    buildProduct,
    verifyZip,
    deleteProduct,
    openEmitLicenseModal,
    verifyLicenseQuick,
    revokeLicense,
    saveAiStrategy,
    pruneAiCache,
    testAiPrompt,
    autoCalibrateAegis,
    runWhatIf,
    resetCircuits,
    runDbBackup,
    runDbOptimize,
  };
})(window);