// ==================== ZERO-TOUCH TITAN-OS v16.0 — REUSABLE UI COMPONENTS & LIVE HUD ====================
(function (global) {
  'use strict';

  function escHtml(v) {
    return String(v === null || v === undefined ? '' : v)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function fmtUSD(n, decimals = 2) {
    const val = Number(n || 0);
    return '$' + val.toLocaleString('en-US', {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
  }

  function fmtCOP(n) {
    return '$' + Math.round(Number(n || 0)).toLocaleString('es-CO') + ' COP';
  }

  function fmtHMS(seg) {
    const s = Math.max(0, Math.floor(Number(seg || 0)));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const r = s % 60;
    return [h, m, r].map((x) => String(x).padStart(2, '0')).join(':');
  }

  function fmtRelTime(ts) {
    if (!ts) return '';
    const ep = typeof ts === 'number' ? (ts > 1e12 ? ts : ts * 1000) : Date.parse(String(ts));
    if (Number.isNaN(ep)) return String(ts).slice(0, 16);
    const diff = Math.max(0, Math.floor((Date.now() - ep) / 1000));
    if (diff < 10) return 'ahora';
    if (diff < 60) return `hace ${diff}s`;
    if (diff < 3600) return `hace ${Math.floor(diff / 60)}m`;
    if (diff < 86400) return `hace ${Math.floor(diff / 3600)}h`;
    return `hace ${Math.floor(diff / 86400)}d`;
  }

  // ==================== 1. TOASTS, MODALS & SLIDE-OVER DRAWER ====================
  function ensureToastStack() {
    let el = document.getElementById('t16ToastStack');
    if (!el) {
      el = document.createElement('div');
      el.id = 't16ToastStack';
      el.className = 't16-toast-stack';
      document.body.appendChild(el);
    }
    return el;
  }

  function toast(msg, tipo = 'info', ms = 3600) {
    if (typeof global.toast === 'function' && global.toast !== toast) {
      try {
        global.toast(msg, tipo);
        return;
      } catch (_) {}
    }
    const stack = ensureToastStack();
    const item = document.createElement('div');
    item.className = `t16-toast ${escHtml(tipo)}`;
    item.textContent = String(msg || '');
    stack.appendChild(item);
    setTimeout(() => {
      item.style.opacity = '0';
      setTimeout(() => item.remove(), 200);
    }, ms);
  }

  function ensureDrawerShell() {
    let bd = document.getElementById('t16Backdrop');
    let dr = document.getElementById('t16Drawer');
    if (!bd) {
      bd = document.createElement('div');
      bd.id = 't16Backdrop';
      bd.className = 't16-backdrop';
      bd.addEventListener('click', closeDrawer);
      document.body.appendChild(bd);
    }
    if (!dr) {
      dr = document.createElement('aside');
      dr.id = 't16Drawer';
      dr.className = 't16-drawer';
      dr.innerHTML = `
        <div class="t16-drawer-head">
          <h3 id="t16DrawerTitle" class="t16-drawer-title">Panel</h3>
          <button class="t16-pill" onclick="TitanUI.closeDrawer()">✕ Cerrar</button>
        </div>
        <div id="t16DrawerBody" class="t16-drawer-body"></div>
        <div id="t16DrawerFoot" class="t16-drawer-foot" style="display:none;"></div>
      `;
      document.body.appendChild(dr);
    }
    return { bd, dr };
  }

  function openDrawer({ title = 'Detalle', html = '', footerHtml = '', width = '' } = {}) {
    const { bd, dr } = ensureDrawerShell();
    document.getElementById('t16DrawerTitle').textContent = title;
    document.getElementById('t16DrawerBody').innerHTML = html;
    const ft = document.getElementById('t16DrawerFoot');
    if (footerHtml) {
      ft.innerHTML = footerHtml;
      ft.style.display = 'flex';
    } else {
      ft.innerHTML = '';
      ft.style.display = 'none';
    }
    dr.style.width = width || '';
    bd.classList.add('open');
    dr.classList.add('open');
  }

  function closeDrawer() {
    const bd = document.getElementById('t16Backdrop');
    const dr = document.getElementById('t16Drawer');
    if (bd) bd.classList.remove('open');
    if (dr) dr.classList.remove('open');
  }

  function ensureModalShell() {
    let wrap = document.getElementById('t16ModalWrap');
    if (!wrap) {
      wrap = document.createElement('div');
      wrap.id = 't16ModalWrap';
      wrap.className = 't16-modal-wrap';
      wrap.innerHTML = `
        <div class="t16-modal" role="dialog" aria-modal="true">
          <div class="t16-drawer-head">
            <h3 id="t16ModalTitle" class="t16-drawer-title">Modal</h3>
            <button class="t16-pill" id="t16ModalCloseBtn">✕</button>
          </div>
          <div id="t16ModalBody" class="t16-drawer-body"></div>
          <div id="t16ModalFoot" class="t16-drawer-foot"></div>
        </div>
      `;
      wrap.addEventListener('click', (e) => {
        if (e.target === wrap) closeModal();
      });
      document.body.appendChild(wrap);
      document.getElementById('t16ModalCloseBtn').addEventListener('click', closeModal);
    }
    return wrap;
  }

  let _activeModalResolve = null;

  function openModal({ title = 'TITAN-OS', html = '', footerHtml = '', onOpen = null } = {}) {
    const wrap = ensureModalShell();
    document.getElementById('t16ModalTitle').textContent = title;
    document.getElementById('t16ModalBody').innerHTML = html;
    document.getElementById('t16ModalFoot').innerHTML =
      footerHtml || '<button class="t16-pill" onclick="TitanUI.closeModal()">Cerrar</button>';
    wrap.classList.add('open');
    if (typeof onOpen === 'function') onOpen(wrap);
  }

  function closeModal(result = null) {
    const wrap = document.getElementById('t16ModalWrap');
    if (wrap) wrap.classList.remove('open');
    if (_activeModalResolve) {
      const r = _activeModalResolve;
      _activeModalResolve = null;
      r(result);
    }
  }

  function confirmDialog(title, message, confirmLabel = 'Confirmar') {
    return new Promise((resolve) => {
      _activeModalResolve = resolve;
      openModal({
        title,
        html: `<p style="margin:0;color:var(--t16-text-1);line-height:1.55;">${escHtml(message)}</p>`,
        footerHtml: `
          <button class="t16-pill" id="t16CfgNo">Cancelar</button>
          <button class="t16-pill t16-pill-live" id="t16CfgYes">${escHtml(confirmLabel)}</button>
        `,
        onOpen: () => {
          document.getElementById('t16CfgNo')?.addEventListener('click', () => closeModal(false));
          document.getElementById('t16CfgYes')?.addEventListener('click', () => closeModal(true));
        },
      });
    });
  }

  // ==================== 2. PURE SVG CHARTS (SPARKLINE, BARRAS AGRUPADAS, DONUT) ====================
  function svgSparkline(values, { width = 160, height = 38, color = '#22d3ee', fill = true } = {}) {
    const nums = (values || []).map((v) => Number(v || 0));
    if (!nums.length) return '';
    const max = Math.max(...nums, 1);
    const min = Math.min(...nums, 0);
    const span = Math.max(0.0001, max - min);
    const step = nums.length > 1 ? width / (nums.length - 1) : width;
    const pts = nums.map((v, i) => {
      const x = Math.round(i * step * 10) / 10;
      const y = Math.round((height - 4 - ((v - min) / span) * (height - 8)) * 10) / 10;
      return `${x},${y}`;
    });
    const area = fill ? `<polygon points="0,${height} ${pts.join(' ')} ${width},${height}" fill="${color}" fill-opacity="0.14"/>` : '';
    return `<svg viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" style="display:block;overflow:visible;">
      ${area}
      <polyline fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" points="${pts.join(' ')}"/>
    </svg>`;
  }

  function svgBarChart(series, { width = 540, height = 180, colorPos = '#10b981', colorNeg = '#ef4444' } = {}) {
    // series: [{ label, a, b }]
    const items = series || [];
    if (!items.length) return renderEmptyState('Sin datos para graficar');
    const maxV = Math.max(1, ...items.flatMap((x) => [Number(x.a || 0), Number(x.b || 0)]));
    const padL = 12, padB = 26, padT = 16;
    const plotH = height - padB - padT;
    const slotW = (width - padL * 2) / items.length;
    const barW = Math.max(8, Math.min(24, slotW * 0.34));

    const bars = items.map((it, idx) => {
      const cx = padL + idx * slotW + slotW / 2;
      const va = Number(it.a || 0);
      const vb = Number(it.b || 0);
      const ha = Math.max(2, (va / maxV) * plotH);
      const hb = vb > 0 ? Math.max(2, (vb / maxV) * plotH) : 0;
      const xa = vb > 0 ? cx - barW - 2 : cx - barW / 2;
      const xb = cx + 2;
      return `
        <g>
          <rect x="${xa.toFixed(1)}" y="${(padT + plotH - ha).toFixed(1)}" width="${barW.toFixed(1)}" height="${ha.toFixed(1)}" rx="4" fill="${colorPos}">
            <title>${escHtml(it.label)}: ${fmtUSD(va, 0)}</title>
          </rect>
          ${vb > 0 ? `<rect x="${xb.toFixed(1)}" y="${(padT + plotH - hb).toFixed(1)}" width="${barW.toFixed(1)}" height="${hb.toFixed(1)}" rx="4" fill="${colorNeg}"><title>${escHtml(it.label)} Gasto: ${fmtUSD(vb, 0)}</title></rect>` : ''}
          <text x="${cx.toFixed(1)}" y="${height - 8}" text-anchor="middle" fill="#94a3b8" font-size="10" font-family="Consolas,monospace">${escHtml(it.label)}</text>
        </g>
      `;
    }).join('');

    return `<svg viewBox="0 0 ${width} ${height}" style="width:100%;height:${height}px;display:block;">
      <line x1="${padL}" y1="${padT + plotH}" x2="${width - padL}" y2="${padT + plotH}" stroke="rgba(148,163,184,0.22)" stroke-width="1"/>
      ${bars}
    </svg>`;
  }

  function svgDonut(segments, { size = 128, stroke = 16, centerText = '' } = {}) {
    const items = (segments || []).filter((s) => Number(s.value || 0) > 0);
    const total = items.reduce((a, b) => a + Number(b.value || 0), 0);
    if (!total) return renderEmptyState('Sin distribución');
    const r = (size - stroke) / 2;
    const c = 2 * Math.PI * r;
    let acc = 0;
    const arcs = items.map((s) => {
      const frac = Number(s.value) / total;
      const dash = frac * c;
      const offset = -acc * c;
      acc += frac;
      return `<circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="${s.color || '#22d3ee'}" stroke-width="${stroke}" stroke-dasharray="${dash.toFixed(2)} ${c.toFixed(2)}" stroke-dashoffset="${offset.toFixed(2)}" transform="rotate(-90 ${size / 2} ${size / 2})"><title>${escHtml(s.label)}: ${s.value}</title></circle>`;
    }).join('');
    return `<svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" style="display:block;">
      <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="rgba(148,163,184,0.14)" stroke-width="${stroke}"/>
      ${arcs}
      ${centerText ? `<text x="50%" y="52%" text-anchor="middle" fill="#f1f5f9" font-size="14" font-weight="800" font-family="Consolas,monospace">${escHtml(centerText)}</text>` : ''}
    </svg>`;
  }

  function renderEmptyState(msg, sub = '') {
    return `<div class="t16-empty"><div style="font-weight:700;color:var(--t16-text-1);">${escHtml(msg)}</div>${sub ? `<div style="margin-top:4px;font-size:12px;">${escHtml(sub)}</div>` : ''}</div>`;
  }

  function renderDiff(diffText) {
    if (!diffText) return renderEmptyState('Sin diferencias');
    const htmlLines = String(diffText).split('\n').map((ln) => {
      if (ln.startsWith('+++') || ln.startsWith('---') || ln.startsWith('@@')) {
        return `<span class="t16-diff-hunk">${escHtml(ln)}</span>`;
      }
      if (ln.startsWith('+')) return `<span class="t16-diff-add">${escHtml(ln)}</span>`;
      if (ln.startsWith('-')) return `<span class="t16-diff-del">${escHtml(ln)}</span>`;
      return `<span>${escHtml(ln)}</span>\n`;
    }).join('');
    return `<pre class="t16-diff">${htmlLines}</pre>`;
  }

  function badge(texto, tono = 'muted') {
    return `<span class="t16-badge t16-b-${escHtml(tono)}">${escHtml(texto)}</span>`;
  }

  // ==================== 3. LIVE HUD (SSE BADGE + TIMER GLOBAL + EVENT STREAM DRAWER) ====================
  function openEventsDrawer() {
    if (global.TitanStore) {
      global.TitanStore.patch('events', { unread: 0 });
    }
    const buildEventsHtml = () => {
      const st = global.TitanStore ? global.TitanStore.get('sse') : {};
      const feed = (global.TitanStore ? global.TitanStore.get('events.feed') : []) || [];
      const rows = feed.slice(0, 60).map((ev) => {
        const p = ev.payload || {};
        const summary = Object.entries(p)
          .filter(([k]) => !k.startsWith('_'))
          .slice(0, 5)
          .map(([k, v]) => `<b>${escHtml(k)}</b>=${escHtml(typeof v === 'object' ? JSON.stringify(v) : v)}`)
          .join(' &bull; ');
        return `
          <div class="t16-event-item lvl-${escHtml(ev.nivel || 'info')}">
            <div class="t16-event-head">
              <span class="t16-event-topic">${escHtml(ev.topico)}</span>
              <span class="t16-event-time">#${escHtml(ev.seq_id)} &bull; ${escHtml(fmtRelTime(ev.ts_epoch || ev.ts_iso))}</span>
            </div>
            <div class="t16-event-body">${summary || escHtml(ev.origen || 'sistema')}</div>
          </div>
        `;
      }).join('');
      return `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;gap:8px;flex-wrap:wrap;">
          <div>${badge('SSE: ' + String(st.status || 'offline').toUpperCase(), st.status === 'live' ? 'ok' : 'warn')} ${badge('Seq #' + (st.last_seq || 0), 'cyan')}</div>
          <div style="display:flex;gap:6px;">
            <button class="t16-pill" onclick="TitanAPI.syncHistory(60).then(() => TitanUI.openEventsDrawer())">🔄 Sincronizar</button>
            <button class="t16-pill" onclick="TitanSSE.connect()">⚡ Reconectar</button>
          </div>
        </div>
        ${rows || renderEmptyState('Sin eventos recientes en el bus', 'Los eventos en vivo de CRM, Radar, Finanzas y Workflows aparecerán aquí.')}
      `;
    };

    openDrawer({
      title: '⚡ TITAN-OS Live Event Stream (SSE)',
      html: buildEventsHtml(),
      footerHtml: `<button class="t16-pill" onclick="TitanUI.openTokenConfig()">🔐 API Token</button><button class="t16-pill" onclick="TitanUI.closeDrawer()">Cerrar</button>`,
    });
  }

  function openTokenConfig() {
    const cur = global.TitanAPI ? global.TitanAPI.getToken() : '';
    openModal({
      title: '🔐 Autenticación API v2 (Opcional)',
      html: `
        <p style="margin:0 0 10px 0;color:var(--t16-text-1);font-size:12.5px;">
          Solo necesario si configuraste <code>TITAN_API_TOKEN</code> en tu entorno <code>.env</code>. En local sin token déjalo vacío.
        </p>
        <input id="t16TokenInput" type="password" value="${escHtml(cur)}" placeholder="Pega tu TITAN_API_TOKEN..." style="width:100%;padding:9px 11px;border-radius:8px;background:#070b14;border:1px solid var(--t16-border);color:#f1f5f9;">
      `,
      footerHtml: `
        <button class="t16-pill" onclick="TitanUI.closeModal()">Cancelar</button>
        <button class="t16-pill t16-pill-live" onclick="TitanAPI.setToken(document.getElementById('t16TokenInput').value);TitanSSE.connect();TitanAPI.refreshOverview();TitanUI.toast('Token actualizado','ok');TitanUI.closeModal();">Guardar</button>
      `,
    });
  }

  async function toggleQuickTimer() {
    if (!global.TitanStore || !global.TitanAPI) return;
    const t = global.TitanStore.get('timer');
    if (t && t.activa) {
      const res = await global.TitanAPI.post('/api/v2/tiempo/detener', {});
      if (res && res.ok) {
        toast(`⏹️ Sesión guardada: ${res.sesion.formato_hms} (${fmtUSD(res.sesion.valor_devengado_usd)})`, 'ok');
        global.TitanAPI.refreshOverview();
      }
      return;
    }
    openModal({
      title: '⏱️ Iniciar Cronómetro TITAN-OS',
      html: `
        <div style="display:flex;flex-direction:column;gap:10px;">
          <label style="font-size:12px;color:var(--t16-text-1);">Proyecto / Tarea
            <input id="t16QuickProj" type="text" placeholder="Ej. Scraper Shopify Playwright" style="width:100%;margin-top:4px;padding:8px 10px;border-radius:8px;background:#070b14;border:1px solid var(--t16-border);color:#f1f5f9;">
          </label>
          <label style="font-size:12px;color:var(--t16-text-1);">Tarifa objetivo (USD/hr)
            <input id="t16QuickRate" type="number" value="25" min="1" step="1" style="width:100%;margin-top:4px;padding:8px 10px;border-radius:8px;background:#070b14;border:1px solid var(--t16-border);color:#f1f5f9;">
          </label>
        </div>
      `,
      footerHtml: `
        <button class="t16-pill" onclick="TitanUI.closeModal()">Cancelar</button>
        <button class="t16-pill t16-pill-timer-on" id="t16StartTimerBtn">▶️ Iniciar Ahora</button>
      `,
      onOpen: () => {
        document.getElementById('t16StartTimerBtn')?.addEventListener('click', async () => {
          const proy = (document.getElementById('t16QuickProj')?.value || '').trim() || 'Desarrollo Freelance';
          const rate = Number(document.getElementById('t16QuickRate')?.value || 25);
          const res = await global.TitanAPI.post('/api/v2/tiempo/iniciar', { proyecto_nombre: proy, tarifa_hora_usd: rate });
          if (res && res.ok) {
            toast(`⏱️ Cronómetro iniciado: ${proy}`, 'ok');
            global.TitanAPI.refreshOverview();
            closeModal(true);
          }
        });
      },
    });
  }

  function updateHudDOM() {
    if (!global.TitanStore) return;
    const sse = global.TitanStore.get('sse') || {};
    const timer = global.TitanStore.get('timer') || {};
    const events = global.TitanStore.get('events') || {};

    const ssePill = document.getElementById('t16HudSse');
    if (ssePill) {
      const st = sse.status || 'offline';
      ssePill.className = 't16-pill ' + (st === 'live' ? 't16-pill-live' : (st === 'offline' ? 't16-pill-err' : 't16-pill-warn'));
      const dotCls = st === 'live' ? 't16-dot-ok' : (st === 'offline' ? 't16-dot-err' : 't16-dot-warn');
      ssePill.innerHTML = `<span class="t16-dot ${dotCls}"></span><span>${st === 'live' ? 'LIVE SSE' : st.toUpperCase()}</span>`;
    }

    const timerPill = document.getElementById('t16HudTimer');
    if (timerPill) {
      if (timer.activa) {
        timerPill.className = 't16-pill t16-pill-mono t16-pill-timer-on';
        timerPill.title = `Activo: ${timer.activa.proyecto_nombre} — clic para detener`;
        timerPill.innerHTML = `<span class="t16-dot t16-dot-cyan"></span><span>${fmtHMS(timer.elapsed_seg)}</span>`;
      } else {
        timerPill.className = 't16-pill t16-pill-mono';
        timerPill.title = 'Iniciar cronómetro TITAN-OS';
        timerPill.innerHTML = `<span>⏱️ Timer</span>`;
      }
    }

    const bellPill = document.getElementById('t16HudBell');
    if (bellPill) {
      const u = Number(events.unread || 0);
      bellPill.innerHTML = `<span>🔔</span>${u > 0 ? `<span class="t16-counter">${u > 99 ? '99+' : u}</span>` : '<span>Live</span>'}`;
    }
  }

  function initTopbarHUD() {
    if (document.getElementById('t16HudRoot')) return;
    const hud = document.createElement('div');
    hud.id = 't16HudRoot';
    hud.innerHTML = `
      <button id="t16HudTimer" class="t16-pill t16-pill-mono" onclick="TitanUI.toggleQuickTimer()">⏱️ Timer</button>
      <button id="t16HudBell" class="t16-pill" onclick="TitanUI.openEventsDrawer()">🔔 Live</button>
      <button id="t16HudSse" class="t16-pill t16-pill-warn" onclick="TitanUI.openEventsDrawer()"><span class="t16-dot t16-dot-warn"></span><span>SSE</span></button>
    `;

    // Montaje inteligente: busca topbar existente de Obsidian UI v14 o cae en dock flotante limpio
    const topbar = document.querySelector('.topbar-actions, .topbar-right, header.topbar, .topbar');
    if (topbar) {
      hud.className = 't16-hud';
      topbar.appendChild(hud);
    } else {
      hud.className = 't16-hud t16-hud-floating';
      document.body.appendChild(hud);
    }

    if (global.TitanStore) {
      global.TitanStore.subscribe('sse', updateHudDOM);
      global.TitanStore.subscribe('timer', updateHudDOM);
      global.TitanStore.subscribe('events', updateHudDOM);
    }
    updateHudDOM();

    // Atajo Esc global para cerrar drawer/modal
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closeModal(null);
        closeDrawer();
      }
    });
  }

  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', initTopbarHUD);
    } else {
      setTimeout(initTopbarHUD, 50);
    }
  }

  global.TitanUI = {
    escHtml,
    fmtUSD,
    fmtCOP,
    fmtHMS,
    fmtRelTime,
    toast,
    openDrawer,
    closeDrawer,
    openModal,
    closeModal,
    confirmDialog,
    svgSparkline,
    svgBarChart,
    svgDonut,
    renderEmptyState,
    renderDiff,
    badge,
    openEventsDrawer,
    openTokenConfig,
    toggleQuickTimer,
    initTopbarHUD,
  };
})(window);