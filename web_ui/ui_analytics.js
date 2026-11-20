// ==================== ZERO-TOUCH UI v14.0 — PLATAFORMAS & SVG ANALYTICS ====================

const COLORES_ESTADO = {
  nuevo:      '#38bdf8',
  contactado: '#c084fc',
  negociando: '#fbbf24',
  ganado:     '#34d399',
  descartado: '#64748b',
};

async function togglePlataforma(clave, activa) {
  const d = await apiJson('/api/fuentes_toggle', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ clave, activa }),
  });
  if (d.error) return toast(d.error, 'err');
  DATA.fuentes_activas = d.fuentes_activas || DATA.fuentes_activas;
  renderPlataformas();
  toast(activa ? `Plataforma ${clave} activada` : `Plataforma ${clave} pausada`, activa ? 'ok' : '');
}

async function toggleSoloCorto(activo) {
  const d = await apiJson('/api/fuentes_toggle', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ solo_freelance_corto: activo }),
  });
  if (d.error) return toast(d.error, 'err');
  DATA.solo_freelance_corto = activo;
  toast(activo ? 'Filtro activo: solo Freelance corto y Bounties' : 'Modo completo: Freelance + Bounties + Remoto', 'ok');
}

async function agregarRssWeb() {
  const nomEl = document.getElementById('rssNom');
  const urlEl = document.getElementById('rssUrl');
  const nombre = (nomEl?.value || '').trim();
  const url = (urlEl?.value || '').trim();
  if (!url.startsWith('http://') && !url.startsWith('https://')) {
    return toast('Ingresa una URL valida que empiece por http:// o https://', 'err');
  }
  const d = await apiJson('/api/rss_add', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ nombre, url }),
  });
  if (d.error) return toast(d.error, 'err');
  if (nomEl) nomEl.value = '';
  if (urlEl) urlEl.value = '';
  DATA.feeds_rss_custom = d.feeds || [];
  renderPlataformas();
  toast('Feed RSS agregado al radar', 'ok');
}

async function eliminarRssWeb(idx) {
  const d = await apiJson('/api/rss_del', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ idx }),
  });
  if (d.error) return toast(d.error, 'err');
  DATA.feeds_rss_custom = d.feeds || [];
  renderPlataformas();
  toast('Feed RSS eliminado', 'ok');
}

function renderPlataformas() {
  const grid = document.getElementById('gridPlataformas');
  if (!grid) return;

  const cat = DATA.catalogo || [];
  const act = DATA.fuentes_activas || {};
  const salud = DATA.salud || [];
  const chk = document.getElementById('chkSoloCorto');
  if (chk) chk.checked = !!DATA.solo_freelance_corto;

  const porClave = {};
  salud.forEach(s => {
    const k = s.clave_config || 'otros';
    if (!porClave[k]) porClave[k] = { ok: 0, tot: 0, bruto: 0, tech: 0, modos: new Set(), err: '' };
    porClave[k].tot += 1;
    if (s.ok) porClave[k].ok += 1;
    porClave[k].bruto += Number(s.bruto || 0);
    porClave[k].tech += Number(s.tech || 0);
    if (s.modo) porClave[k].modos.add(s.modo);
    if (s.ultimo_error) porClave[k].err = s.ultimo_error;
  });

  grid.innerHTML = cat.map(p => {
    const on = act[p.clave] !== false;
    const st = porClave[p.clave];
    const dotCls = !st ? 'st-idle' : (st.ok > 0 ? 'st-ok' : 'st-err');
    const saludVal = st ? `${st.ok}/${st.tot}` : '--';
    const brutoVal = st ? st.bruto : '--';
    const techVal = st ? st.tech : '--';
    const modoTxt = st ? Array.from(st.modos).slice(0, 2).join(', ') : 'Sin escanear';
    const errTxt = (st && st.ok === 0 && st.err) ? `<div class="c-red" style="font-size:11px;">${esc(st.err)}</div>` : '';

    return `
      <div class="plat-card ${on ? '' : 'is-off'}">
        <div class="plat-head">
          <div>
            <div class="plat-title">
              <span class="status-dot ${dotCls}"></span>
              <span>${esc(p.nombre)}</span>
            </div>
            <div class="lead-meta" style="margin-top:5px;">
              <span class="badge b-${esc(p.tipo)}">${esc(p.tipo)}</span>
              <span>${esc(modoTxt)}</span>
            </div>
          </div>
          <label class="switch" title="Activar o pausar ${esc(p.nombre)}">
            <input type="checkbox" ${on ? 'checked' : ''} onchange="togglePlataforma('${esc(p.clave)}', this.checked)">
            <span class="slider"></span>
          </label>
        </div>
        <div class="muted" style="font-size:12px;">${esc(p.desc)}</div>
        ${errTxt}
        <div class="plat-metrics">
          <div class="plat-m"><span>Salud</span><b class="${st && st.ok > 0 ? 'c-green' : ''}">${esc(saludVal)}</b></div>
          <div class="plat-m"><span>Bruto</span><b>${esc(brutoVal)}</b></div>
          <div class="plat-m"><span>Tech</span><b class="c-cyan">${esc(techVal)}</b></div>
        </div>
      </div>
    `;
  }).join('');

  const feeds = DATA.feeds_rss_custom || [];
  const boxRss = document.getElementById('listaRssCustom');
  if (boxRss) {
    if (!feeds.length) {
      boxRss.innerHTML = '<div class="muted">No tienes feeds RSS propios agregados todavia.</div>';
    } else {
      boxRss.innerHTML = feeds.map((f, idx) => {
        const nom = typeof f === 'string' ? f : (f.nombre || f.url);
        const url = typeof f === 'string' ? f : f.url;
        return `
          <div class="rss-item">
            <div style="min-width:0;">
              <div style="font-weight:700;color:var(--text-0);">${esc(nom)}</div>
              <div class="muted" style="font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(url)}</div>
            </div>
            <button class="btn btn-danger btn-xs" onclick="eliminarRssWeb(${idx})">Quitar</button>
          </div>
        `;
      }).join('');
    }
  }

  const detEl = document.getElementById('tablaSaludDetalle');
  if (detEl && salud.length) {
    detEl.innerHTML = salud.map(s => {
      const cls = s.ok ? 'log-ok' : 'log-err';
      const ic = s.ok ? '[OK ]' : '[ERR]';
      const err = s.ultimo_error ? ` | ${s.ultimo_error}` : '';
      return `<div class="term-line ${cls}">${ic} ${esc(s.fuente.padEnd(18))} | ${esc((s.modo || '').padEnd(15))} | raw:${String(s.bruto).padStart(3)} | tech:${String(s.tech).padStart(2)}${esc(err)}</div>`;
    }).join('');
  }
}

// ==================== GRAFICOS SVG INTERACTIVOS ====================
function renderDonutEmbudo(embudo) {
  const el = document.getElementById('chartEmbudoSvg');
  if (!el) return;
  const total = (embudo || []).reduce((acc, p) => acc + Number(p[1] || 0), 0);
  if (!total) {
    el.innerHTML = '<div class="empty-state"><b>Sin datos en el embudo</b>Ejecuta un escaneo para empezar a medir tus conversiones.</div>';
    return;
  }

  const r = 60;
  const circ = 2 * Math.PI * r;
  let offset = 0;

  const segs = embudo.map(([estado, count]) => {
    const frac = Number(count) / total;
    const dash = Math.max(2, frac * circ);
    const col = COLORES_ESTADO[estado] || '#38bdf8';
    const segHtml = `<circle cx="82" cy="82" r="${r}" fill="none" stroke="${col}" stroke-width="18" stroke-dasharray="${dash.toFixed(2)} ${(circ - dash).toFixed(2)}" stroke-dashoffset="${(-offset).toFixed(2)}" transform="rotate(-90 82 82)" />`;
    offset += dash;
    return { estado, count, pct: Math.round(frac * 100), col, segHtml };
  });

  el.innerHTML = `
    <div class="chart-wrap">
      <div class="donut-box">
        <svg viewBox="0 0 164 164" width="164" height="164">
          <circle cx="82" cy="82" r="${r}" fill="none" stroke="rgba(148,163,184,0.12)" stroke-width="18"/>
          ${segs.map(s => s.segHtml).join('')}
        </svg>
        <div class="donut-center">
          <b>${total}</b>
          <span>Leads CRM</span>
        </div>
      </div>
      <div class="legend-list">
        ${segs.map(s => `
          <div class="legend-row">
            <div class="legend-left">
              <span class="legend-swatch" style="background:${s.col};"></span>
              <span style="text-transform:capitalize;font-weight:600;">${esc(s.estado)}</span>
            </div>
            <span style="font-family:var(--font-mono);color:var(--text-1);"><b>${s.count}</b> <span class="muted">(${s.pct}%)</span></span>
          </div>
        `).join('')}
      </div>
    </div>
  `;
}

function renderGaugeTokens(usados, ahorrados) {
  const el = document.getElementById('chartTokensSvg');
  if (!el) return;
  const total = usados + ahorrados;
  const pct = total > 0 ? Math.round((ahorrados / total) * 100) : 0;
  const r = 60;
  const circ = 2 * Math.PI * r;
  const dash = (pct / 100) * circ;

  el.innerHTML = `
    <div class="chart-wrap">
      <div class="donut-box">
        <svg viewBox="0 0 164 164" width="164" height="164">
          <circle cx="82" cy="82" r="${r}" fill="none" stroke="rgba(148,163,184,0.12)" stroke-width="16"/>
          <circle cx="82" cy="82" r="${r}" fill="none" stroke="var(--green)" stroke-width="16" stroke-linecap="round"
            stroke-dasharray="${dash.toFixed(2)} ${(circ - dash).toFixed(2)}" transform="rotate(-90 82 82)"/>
        </svg>
        <div class="donut-center">
          <b class="c-green">${pct}%</b>
          <span>Ahorro IA</span>
        </div>
      </div>
      <div class="legend-list">
        <div class="legend-row">
          <div class="legend-left"><span class="legend-swatch" style="background:var(--green);"></span><span>Tokens Ahorrados</span></div>
          <b style="font-family:var(--font-mono);" class="c-green">${ahorrados.toLocaleString()}</b>
        </div>
        <div class="legend-row">
          <div class="legend-left"><span class="legend-swatch" style="background:var(--accent);"></span><span>Tokens Usados</span></div>
          <b style="font-family:var(--font-mono);" class="c-cyan">${usados.toLocaleString()}</b>
        </div>
        <div class="legend-row">
          <div class="legend-left"><span class="legend-swatch" style="background:var(--purple);"></span><span>Basura bloqueada</span></div>
          <b style="font-family:var(--font-mono);">${Number(DATA.kpis.descartados || 0).toLocaleString()}</b>
        </div>
      </div>
    </div>
  `;
}

function renderBarrasModernas(elId, pares, cls = '', sufijo = '', prefijo = '') {
  const el = document.getElementById(elId);
  if (!el) return;
  if (!pares || !pares.length) {
    el.innerHTML = '<div class="empty-state" style="padding:24px 10px;"><b>Sin datos registrados aun</b>Cierra leads o corre un escaneo para llenar esta metrica.</div>';
    return;
  }
  const max = Math.max(...pares.map(p => Number(p[1] || 0)), 1);
  el.innerHTML = pares.map(([k, v]) => {
    const val = Number(v || 0);
    const w = Math.max(5, Math.round((val / max) * 100));
    return `
      <div class="bar-item">
        <div class="bar-meta">
          <span style="font-weight:600;color:var(--text-1);">${esc(k)}</span>
          <b style="font-family:var(--font-mono);color:var(--text-0);">${prefijo}${val.toLocaleString()}${sufijo}</b>
        </div>
        <div class="bar-track"><div class="bar-fill ${cls}" style="width:${w}%"></div></div>
      </div>
    `;
  }).join('');
}

function renderAnalytics() {
  const a = DATA.analytics || {};
  renderDonutEmbudo(a.embudo || []);
  renderGaugeTokens(Number(DATA.kpis.tok_usados || 0), Number(DATA.kpis.tok_ahorrados || 0));
  renderBarrasModernas('chFuentes', a.por_fuente || [], '', ' leads');
  renderBarrasModernas('chCat', a.usd_categoria || [], 'green', ' USD', '$');
}