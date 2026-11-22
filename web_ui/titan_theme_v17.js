(function (global) {
  'use strict';

  const STORAGE_KEY = 'titan_theme_v17';
  const THEMES = [
    { id: 'obsidian', label: 'Obsidian', icon: '🌑' },
    { id: 'neon', label: 'Neon', icon: '⚡' },
    { id: 'light', label: 'Light', icon: '☀️' },
  ];

  function aplicarTema(themeId) {
    const valid = THEMES.some((t) => t.id === themeId) ? themeId : 'obsidian';
    document.documentElement.setAttribute('data-titan-theme', valid);
    try {
      localStorage.setItem(STORAGE_KEY, valid);
    } catch (_) {}
    document.querySelectorAll('.t17-theme-btn').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.themeId === valid);
    });
    return valid;
  }

  function actualizarBrandingV17() {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const nodos = [];
    let n;
    while ((n = walker.nextNode())) {
      if (!n.nodeValue) continue;
      if (/ZeroTouch\s+OMNI|v14\.0|OMNI-GRID\s*v14/i.test(n.nodeValue)) {
        nodos.push(n);
      }
    }
    nodos.forEach((node) => {
      node.nodeValue = node.nodeValue
        .replace(/ZeroTouch\s+OMNI/gi, 'ZeroTouch TITAN')
        .replace(/v14\.0\s*[•·\-]\s*Freelance Studio/gi, 'v17.0 • Obsidian Studio')
        .replace(/v14\.0/gi, 'v17.0')
        .replace(/OMNI-GRID\s*v14/gi, 'TITAN-OS v17');
    });
  }

  function montarSelectorTemas() {
    if (document.getElementById('titanV17ThemeDock')) return;
    const sidebar =
      document.querySelector('aside') ||
      document.querySelector('.sidebar') ||
      document.getElementById('sidebar');
    if (!sidebar) return;

    const dock = document.createElement('div');
    dock.id = 'titanV17ThemeDock';
    dock.className = 't17-theme-dock';
    dock.title = 'Cambiar tema visual TITAN-OS v17';

    const actual = document.documentElement.getAttribute('data-titan-theme') || 'obsidian';
    THEMES.forEach((t) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 't17-theme-btn' + (t.id === actual ? ' active' : '');
      btn.dataset.themeId = t.id;
      btn.textContent = `${t.icon} ${t.label}`;
      btn.addEventListener('click', () => {
        aplicarTema(t.id);
        if (global.TitanUI && typeof global.TitanUI.toast === 'function') {
          global.TitanUI.toast(`🎨 Tema ${t.label} activado`, 'ok');
        }
      });
      dock.appendChild(btn);
    });

    const footer = sidebar.querySelector('.sidebar-footer, .sb-footer, footer');
    if (footer && footer.parentNode === sidebar) {
      sidebar.insertBefore(dock, footer);
    } else {
      sidebar.appendChild(dock);
    }
  }

  function init() {
    let saved = 'obsidian';
    try {
      saved = localStorage.getItem(STORAGE_KEY) || 'obsidian';
    } catch (_) {}
    aplicarTema(saved);
    actualizarBrandingV17();
    montarSelectorTemas();
  }

  global.TitanThemeV17 = {
    aplicar: aplicarTema,
    actual: () => document.documentElement.getAttribute('data-titan-theme') || 'obsidian',
    temas: THEMES,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})(window);