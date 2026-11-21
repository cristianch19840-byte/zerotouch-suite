// ==================== ZERO-TOUCH TITAN-OS v16.0 — SANDBOX PYTHON IDE & AUTO-FIX IA ====================
(function (global) {
  'use strict';

  const PRESETS_CODE = {
    ok: `# Demo limpia — Scraper parser JSON -> CSV en memoria
import json, csv, io

items = [
    {"sku": "SH-01", "title": "Wireless Mouse 8K", "price": 59.99},
    {"sku": "SH-02", "title": "Mechanical Keyboard", "price": 89.50},
]
buf = io.StringIO()
w = csv.DictWriter(buf, fieldnames=["sku", "title", "price"])
w.writeheader()
w.writerows(items)
print(buf.getvalue().strip())
print("TOTAL_USD =", sum(x["price"] for x in items))
`,
    bug: `# Demo con bug intencional para probar Auto-Fix IA iterativo
def calcular_margen(ventas, costos):
    return (ventas - costos) / ventas

for v, c in [(500, 120), (0, 50), (300, 90)]:
    print(f"Margen: {calcular_margen(v, c):.2%}")
`,
    sec: `# Demo de bloqueo AST anti-comandos peligrosos
import os
os.system("whoami")
`,
    pip: `# Demo deteccion de paquetes PIP faltantes
import json
import playwright
import pandas as pd
print("Verificando dependencias")
`,
  };

  const SSTATE = {
    hostId: 't16EngBody',
    code: PRESETS_CODE.ok,
    nombreRef: 'sandbox_demo.py',
    stdin: '',
    argsStr: '',
    timeoutSeg: 10,
    instruccion: '',
    lastAudit: null,
    lastRun: null,
    lastFix: null,
    stats: null,
    historial: [],
    snapshots: [],
    busy: false,
  };

  const U = () => global.TitanUI;
  const API = () => global.TitanAPI;

  function updateGutter() {
    const ed = document.getElementById('t16SbxCode');
    const gt = document.getElementById('t16SbxGutter');
    if (!ed || !gt) return;
    SSTATE.code = ed.value;
    const n = Math.max(12, ed.value.split('\n').length);
    let html = '';
    for (let i = 1; i <= n; i++) html += i + '<br>';
    gt.innerHTML = html;
    gt.scrollTop = ed.scrollTop;
  }

  function syncScroll() {
    const ed = document.getElementById('t16SbxCode');
    const gt = document.getElementById('t16SbxGutter');
    if (ed && gt) gt.scrollTop = ed.scrollTop;
  }

  function handleTabKey(ev) {
    if (ev.key !== 'Tab') return;
    ev.preventDefault();
    const el = ev.target;
    const s = el.selectionStart;
    const e = el.selectionEnd;
    el.value = el.value.substring(0, s) + '    ' + el.value.substring(e);
    el.selectionStart = el.selectionEnd = s + 4;
    updateGutter();
  }

  function loadPreset(key) {
    if (!PRESETS_CODE[key]) return;
    SSTATE.code = PRESETS_CODE[key];
    SSTATE.lastFix = null;
    const ed = document.getElementById('t16SbxCode');
    if (ed) {
      ed.value = SSTATE.code;
      updateGutter();
    }
    auditCode();
  }

  async function render(hostId = 't16EngBody', silent = false) {
    SSTATE.hostId = hostId;
    const [rSt, rHi, rSn] = await Promise.all([
      API().get('/api/v2/sandbox/estadisticas', { silent: true }),
      API().get('/api/v2/sandbox/historial?limit=20', { silent: true }),
      API().get('/api/v2/sandbox/snapshots', { silent: true }),
    ]);
    if (rSt?.ok) SSTATE.stats = rSt.estadisticas;
    if (rHi?.ok) SSTATE.historial = rHi.items || [];
    if (rSn?.ok) SSTATE.snapshots = rSn.items || [];
    paint();
  }

  function paint() {
    const host = document.getElementById(SSTATE.hostId);
    if (!host) return;
    const st = SSTATE.stats || {};

    host.innerHTML = `
      <div class="t16-kpi-grid">
        <div class="t16-kpi">
          <span class="t16-kpi-lbl">Ejecuciones Sandbox</span>
          <span class="t16-kpi-val">${st.total || 0}</span>
          <span class="t16-kpi-sub">OK: ${st.exitosas || 0} &bull; Fallos: ${st.fallidas || 0}</span>
        </div>
        <div class="t16-kpi">
          <span class="t16-kpi-lbl">Tasa de Éxito</span>
          <span class="t16-kpi-val" style="color:var(--t16-green);">${st.tasa_exito_pct || 0}%</span>
          <span class="t16-kpi-sub">Latencia prom: ${st.latencia_avg_ms || 0} ms</span>
        </div>
        <div class="t16-kpi">
          <span class="t16-kpi-lbl">Auto-Reparaciones IA</span>
          <span class="t16-kpi-val" style="color:var(--t16-purple);">${st.auto_reparadas || 0}</span>
          <span class="t16-kpi-sub">Snapshots rollback: ${SSTATE.snapshots.length}</span>
        </div>
      </div>

      <div class="t16-split-2" style="margin-bottom:14px;">
        <div class="t16-card-box">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px;">
            <h3 style="margin:0;font-size:14px;">🐍 Sandbox Python IDE (Aislado &bull; Sin Secretos .env)</h3>
            <div style="display:flex;gap:5px;flex-wrap:wrap;">
              <button class="t16-btn-xs" onclick="TitanSandboxUI.loadPreset('ok')">Preset OK</button>
              <button class="t16-btn-xs" onclick="TitanSandboxUI.loadPreset('bug')">Preset Bug</button>
              <button class="t16-btn-xs" onclick="TitanSandboxUI.loadPreset('sec')">Test AST</button>
              <button class="t16-btn-xs" onclick="TitanSandboxUI.loadPreset('pip')">Test PIP</button>
            </div>
          </div>

          <div class="t16-ide-shell" style="margin-bottom:10px;">
            <div id="t16SbxGutter" class="t16-ide-gutter">1</div>
            <textarea id="t16SbxCode" class="t16-ide-editor" spellcheck="false"
                      oninput="TitanSandboxUI.updateGutter()"
                      onscroll="TitanSandboxUI.syncScroll()"
                      onkeydown="TitanSandboxUI.handleTabKey(event)">${U().escHtml(SSTATE.code)}</textarea>
          </div>

          <div style="display:grid;grid-template-columns:1fr 1fr 90px;gap:8px;margin-bottom:10px;">
            <input id="t16SbxRef" class="t16-input" value="${U().escHtml(SSTATE.nombreRef)}" placeholder="Nombre ref (script.py)">
            <input id="t16SbxArgs" class="t16-input" value="${U().escHtml(SSTATE.argsStr)}" placeholder="Args CLI separados por espacio">
            <input id="t16SbxTimeout" class="t16-input" type="number" min="1" max="60" value="${SSTATE.timeoutSeg}" title="Timeout segundos">
          </div>

          <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px;">
            <button class="t16-pill" onclick="TitanSandboxUI.auditCode()">🛡️ Auditar AST</button>
            <button class="t16-pill t16-pill-live" id="t16SbxRunBtn" onclick="TitanSandboxUI.runCode()">▶️ Ejecutar en Sandbox</button>
            <button class="t16-pill t16-pill-timer-on" id="t16SbxFixBtn" onclick="TitanSandboxUI.autoFixCode()">🛠️ Auto-Fix IA (3 iter.)</button>
            <button class="t16-pill" onclick="TitanSandboxUI.sendToFactory()">🏭 Enviar a Whop Factory</button>
          </div>

          <div style="display:flex;gap:6px;align-items:center;">
            <input id="t16SbxInst" class="t16-input" style="flex:1;" value="${U().escHtml(SSTATE.instruccion)}" placeholder="Instrucción IA para refinar y verificar (ej. 'Agrega manejo de errores y type hints')">
            <button class="t16-pill" id="t16SbxRefBtn" onclick="TitanSandboxUI.refineCode()">✨ Refinar + Test</button>
          </div>
        </div>

        <div class="t16-card-box">
          <h3 style="margin:0 0 10px 0;font-size:14px;">📟 Salida Forense, Diagnóstico AST &amp; Diff IA</h3>
          <div id="t16SbxOutput">${renderOutputBlock()}</div>
        </div>
      </div>

      <div class="t16-split-2">
        <div class="t16-card-box">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
            <h3 style="margin:0;font-size:14px;">📜 Historial de Ejecuciones (${SSTATE.historial.length})</h3>
            <button class="t16-btn-xs" onclick="TitanSandboxUI.render()">🔄 Refrescar</button>
          </div>
          ${SSTATE.historial.length ? SSTATE.historial.slice(0, 12).map((h) => `
            <div class="t16-stat-line">
              <span>${h.exit_code === 0 ? '✅' : '❌'} <b>${U().escHtml(h.ruta_script)}</b> ${h.auto_reparado ? U().badge('AUTO-FIX', 'purple') : ''}</span>
              <span style="font-family:var(--t16-mono);font-size:11px;color:var(--t16-muted);">exit=${h.exit_code} &bull; ${h.duracion_ms}ms &bull; ${U().fmtRelTime(h.ts_epoch)}</span>
            </div>
          `).join('') : U().renderEmptyState('Sin ejecuciones registradas')}
        </div>

        <div class="t16-card-box">
          <h3 style="margin:0 0 8px 0;font-size:14px;">⏪ Snapshots de Rollback (${SSTATE.snapshots.length})</h3>
          ${SSTATE.snapshots.length ? SSTATE.snapshots.slice(0, 10).map((s) => `
            <div class="t16-stat-line">
              <span style="font-family:var(--t16-mono);font-size:11.5px;">${U().escHtml(s.archivo)}</span>
              <span style="font-size:11px;color:var(--t16-muted);">${Math.round((s.bytes || 0) / 1024 * 10) / 10} KB</span>
            </div>
          `).join('') : U().renderEmptyState('Sin snapshots aún', 'Al auto-reparar archivos en disco se guarda un respaldo automático aquí.')}
        </div>
      </div>
    `;

    updateGutter();
  }

  function renderOutputBlock() {
    const parts = [];

    if (SSTATE.lastAudit) {
      const a = SSTATE.lastAudit;
      const tono = a.bloqueado ? 'err' : (a.ast_valido ? 'ok' : 'err');
      parts.push(`
        <div class="t16-event-item lvl-${tono}" style="margin-bottom:10px;">
          <div class="t16-event-head">
            <span class="t16-event-topic">AUDITORÍA AST ${a.bloqueado ? 'BLOQUEADA' : (a.ast_valido ? 'OK' : 'SINTAXIS ROTA')}</span>
            <div>${U().badge('Riesgo ' + a.riesgo_score + '/100', tono)} ${U().badge('CC ' + a.complejidad_ciclomatica, 'muted')}</div>
          </div>
          <div class="t16-event-body">
            Líneas: <b>${a.lineas_codigo}</b> &bull; Funciones: <b>${(a.funciones || []).length}</b> &bull; Imports: <span class="t16-code-inline">${U().escHtml((a.imports_detectados || []).join(', ') || 'ninguno')}</span>
            ${(a.paquetes_pip_faltantes || []).length ? `<div style="margin-top:5px;color:var(--t16-amber);">📦 PIP faltantes: <code>pip install ${U().escHtml(a.paquetes_pip_faltantes.join(' '))}</code></div>` : ''}
            ${a.error_sintaxis ? `<div style="margin-top:5px;color:var(--t16-red);">❌ L${a.linea_sintaxis}: ${U().escHtml(a.error_sintaxis)}</div>` : ''}
            ${(a.hallazgos || []).map((h) => `<div style="margin-top:4px;color:${h.bloqueante ? 'var(--t16-red)' : 'var(--t16-amber)'};">• [L${h.linea}] ${U().escHtml(h.descripcion)}</div>`).join('')}
          </div>
        </div>
      `);
    }

    if (SSTATE.lastRun) {
      const r = SSTATE.lastRun;
      const cls = r.ok ? 'ok' : 'err';
      parts.push(`
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;flex-wrap:wrap;gap:6px;">
          <div>
            ${U().badge(r.ok ? 'EXIT 0 · PASS' : `EXIT ${r.exit_code} · FAIL`, r.ok ? 'ok' : 'err')}
            ${r.bloqueado_seguridad ? U().badge('BLOQUEO SEGURIDAD AST', 'err') : ''}
            ${r.timed_out ? U().badge('TIMEOUT', 'warn') : ''}
          </div>
          <span style="font-family:var(--t16-mono);font-size:11.5px;color:var(--t16-muted);">${r.duracion_ms} ms</span>
        </div>
        ${r.stdout ? `<div style="font-size:11px;color:var(--t16-muted);margin-bottom:3px;">STDOUT</div><pre class="t16-console ${cls}" style="margin:0 0 8px 0;">${U().escHtml(r.stdout)}</pre>` : ''}
        ${r.stderr ? `<div style="font-size:11px;color:var(--t16-red);margin-bottom:3px;">STDERR</div><pre class="t16-console err" style="margin:0 0 8px 0;">${U().escHtml(r.stderr)}</pre>` : ''}
        ${r.diagnostico && r.diagnostico.tipo_error ? `<div style="font-size:11.5px;color:var(--t16-amber);margin-bottom:8px;">🔎 Diagnóstico: <b>${U().escHtml(r.diagnostico.tipo_error)}</b> (L${r.diagnostico.linea}) — ${U().escHtml(r.diagnostico.mensaje)}</div>` : ''}
      `);
    }

    if (SSTATE.lastFix) {
      const fx = SSTATE.lastFix;
      parts.push(`
        <div class="t16-event-item lvl-${fx.exito ? 'ok' : 'warn'}" style="margin-top:8px;">
          <div class="t16-event-head">
            <span class="t16-event-topic">🛠️ AUTO-FIX IA (${fx.iteraciones_usadas} iter. &bull; ${fx.duracion_total_ms}ms)</span>
            ${U().badge(fx.exito ? 'REPARADO' : 'INCOMPLETO', fx.exito ? 'ok' : 'warn')}
          </div>
          <div class="t16-event-body">${U().escHtml(fx.mensaje)}</div>
        </div>
        ${fx.diff_unificado ? `<div style="margin-top:8px;"><div style="font-size:11px;color:var(--t16-muted);margin-bottom:4px;">DIFF UNIFICADO</div>${U().renderDiff(fx.diff_unificado)}</div>` : ''}
      `);
    }

    return parts.join('') || U().renderEmptyState('Listo para auditar o ejecutar', 'Presiona "Auditar AST" o "Ejecutar en Sandbox".');
  }

  function readEditorParams() {
    SSTATE.code = document.getElementById('t16SbxCode')?.value || SSTATE.code;
    SSTATE.nombreRef = (document.getElementById('t16SbxRef')?.value || 'sandbox_demo.py').trim();
    SSTATE.argsStr = (document.getElementById('t16SbxArgs')?.value || '').trim();
    SSTATE.timeoutSeg = Number(document.getElementById('t16SbxTimeout')?.value || 10);
    SSTATE.instruccion = (document.getElementById('t16SbxInst')?.value || '').trim();
  }

  async function auditCode() {
    readEditorParams();
    const r = await API().post('/api/v2/sandbox/auditar', { codigo: SSTATE.code });
    if (r?.ok) {
      SSTATE.lastAudit = r.auditoria;
      const out = document.getElementById('t16SbxOutput');
      if (out) out.innerHTML = renderOutputBlock();
    }
  }

  async function runCode() {
    readEditorParams();
    const btn = document.getElementById('t16SbxRunBtn');
    if (btn) btn.disabled = true;
    const args = SSTATE.argsStr ? SSTATE.argsStr.split(/\s+/).filter(Boolean) : [];
    const r = await API().post('/api/v2/sandbox/ejecutar', {
      codigo: SSTATE.code,
      nombre_ref: SSTATE.nombreRef,
      args,
      timeout_seg: SSTATE.timeoutSeg,
      persistir: true,
    });
    if (btn) btn.disabled = false;
    if (r && r.resultado) {
      SSTATE.lastRun = r.resultado;
      SSTATE.lastAudit = r.resultado.auditoria || SSTATE.lastAudit;
      SSTATE.lastFix = null;
      U().toast(r.ok ? `Sandbox OK (${r.resultado.duracion_ms}ms)` : `Sandbox fallo (exit=${r.resultado.exit_code})`, r.ok ? 'ok' : 'warn');
      await render(SSTATE.hostId, true);
    }
  }

  async function autoFixCode() {
    readEditorParams();
    const btn = document.getElementById('t16SbxFixBtn');
    if (btn) btn.disabled = true;
    U().toast('🛠️ Lanzando bucle Auto-Fix IA + Sandbox...', 'info');
    const r = await API().post('/api/v2/sandbox/autofix', {
      codigo: SSTATE.code,
      nombre_ref: SSTATE.nombreRef,
      instruccion: SSTATE.instruccion,
      max_iteraciones: 3,
      timeout_seg: SSTATE.timeoutSeg,
    });
    if (btn) btn.disabled = false;
    if (r && r.autofix) {
      SSTATE.lastFix = r.autofix;
      SSTATE.lastRun = r.autofix.resultado_final || SSTATE.lastRun;
      if (r.codigo_final) SSTATE.code = r.codigo_final;
      U().toast(r.ok ? '✅ Código reparado y verificado en Sandbox!' : 'Auto-Fix no logró exit=0', r.ok ? 'ok' : 'warn');
      await render(SSTATE.hostId, true);
    }
  }

  async function refineCode() {
    readEditorParams();
    if (!SSTATE.instruccion) return U().toast('Escribe una instrucción de refinamiento primero', 'err');
    const btn = document.getElementById('t16SbxRefBtn');
    if (btn) btn.disabled = true;
    const r = await API().post('/api/v2/sandbox/refinar', {
      codigo: SSTATE.code,
      instruccion: SSTATE.instruccion,
      nombre_ref: SSTATE.nombreRef,
      ejecutar_sandbox: true,
      auto_fix_si_falla: true,
      timeout_seg: SSTATE.timeoutSeg,
    });
    if (btn) btn.disabled = false;
    if (r && r.autofix) {
      SSTATE.lastFix = r.autofix;
      SSTATE.lastRun = r.autofix.resultado_final || SSTATE.lastRun;
      if (r.codigo_final) SSTATE.code = r.codigo_final;
      U().toast(r.ok ? '✨ Refinado y verificado OK!' : 'Refinamiento con advertencias', r.ok ? 'ok' : 'warn');
      await render(SSTATE.hostId, true);
    }
  }

  function sendToFactory() {
    readEditorParams();
    if (global.TitanStudioUI) {
      global.TitanStudioUI.sendCodeToFactory(SSTATE.code, SSTATE.nombreRef.replace(/\.py$/i, ''));
    }
  }

  global.TitanSandboxUI = {
    render,
    updateGutter,
    syncScroll,
    handleTabKey,
    loadPreset,
    auditCode,
    runCode,
    autoFixCode,
    refineCode,
    sendToFactory,
  };
})(window);