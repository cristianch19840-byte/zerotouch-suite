// ==================== ZERO-TOUCH TITAN-OS v16.0 — REACTIVE STORE, API v2 CLIENT & SSE LIVE ====================
(function (global) {
  'use strict';

  const STORAGE_KEY_TOKEN = 'titan_v16_api_token';
  const STORAGE_KEY_PREFS = 'titan_v16_prefs';

  function deepGet(obj, path) {
    if (!path || path === '*') return obj;
    return String(path).split('.').reduce((acc, k) => (acc && acc[k] !== undefined ? acc[k] : undefined), obj);
  }

  function deepSet(target, path, value) {
    const parts = String(path).split('.');
    let cur = target;
    for (let i = 0; i < parts.length - 1; i++) {
      const k = parts[i];
      if (!cur[k] || typeof cur[k] !== 'object') cur[k] = {};
      cur = cur[k];
    }
    cur[parts[parts.length - 1]] = value;
  }

  function loadPrefs() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY_PREFS) || '{}') || {};
    } catch (_) {
      return {};
    }
  }

  // ==================== 1. REACTIVE PUB/SUB STORE ====================
  class ReactiveStore {
    constructor(initialState) {
      this._state = initialState;
      this._subs = new Map();
      this._subSeq = 0;
    }

    get(path) {
      return deepGet(this._state, path);
    }

    snapshot() {
      return this._state;
    }

    set(path, value) {
      deepSet(this._state, path, value);
      this._notify(path, value);
      return value;
    }

    patch(path, partial) {
      const prev = this.get(path);
      const next = Object.assign({}, (prev && typeof prev === 'object') ? prev : {}, partial);
      return this.set(path, next);
    }

    subscribe(path, listener) {
      const id = ++this._subSeq;
      this._subs.set(id, { path: String(path || '*'), fn: listener });
      return () => this._subs.delete(id);
    }

    _notify(changedPath, value) {
      const ch = String(changedPath || '');
      for (const sub of this._subs.values()) {
        if (
          sub.path === '*' ||
          sub.path === ch ||
          ch.startsWith(sub.path + '.') ||
          sub.path.startsWith(ch + '.')
        ) {
          try {
            sub.fn(this.get(sub.path), changedPath, value);
          } catch (err) {
            console.error('[TitanStore] subscriber error:', err);
          }
        }
      }
    }
  }

  const store = new ReactiveStore({
    version: '16.0.0-titan',
    prefs: Object.assign({ trm_cop: 4200, auto_refresh: true }, loadPrefs()),
    sse: {
      status: 'connecting', // connecting | live | reconnecting | offline
      sub_id: '',
      last_seq: 0,
      reconnects: 0,
      last_event_ts: 0,
    },
    overview: null,
    timer: {
      activa: null,
      elapsed_seg: 0,
    },
    events: {
      feed: [],
      unread: 0,
    },
    api: {
      in_flight: 0,
      last_latency_ms: 0,
      last_error: '',
    },
  });

  store.savePref = function (key, val) {
    const next = Object.assign({}, store.get('prefs') || {}, { [key]: val });
    store.set('prefs', next);
    try {
      localStorage.setItem(STORAGE_KEY_PREFS, JSON.stringify(next));
    } catch (_) {}
  };

  // ==================== 2. CLIENTE HTTP UNIFICADO PARA /api/v2/* ====================
  const TitanAPI = {
    getToken() {
      try {
        return (localStorage.getItem(STORAGE_KEY_TOKEN) || '').trim();
      } catch (_) {
        return '';
      }
    },

    setToken(tok) {
      try {
        const clean = String(tok || '').trim();
        if (clean) localStorage.setItem(STORAGE_KEY_TOKEN, clean);
        else localStorage.removeItem(STORAGE_KEY_TOKEN);
      } catch (_) {}
    },

    async request(method, path, body = null, opts = {}) {
      const url = path.startsWith('http') || path.startsWith('/') ? path : `/api/v2/${path}`;
      const headers = Object.assign({ Accept: 'application/json' }, opts.headers || {});
      const tok = this.getToken();
      if (tok) headers['X-Titan-Token'] = tok;

      const init = {
        method: String(method || 'GET').toUpperCase(),
        headers,
        signal: opts.signal,
      };
      if (body !== null && init.method !== 'GET' && init.method !== 'HEAD') {
        headers['Content-Type'] = 'application/json';
        init.body = typeof body === 'string' ? body : JSON.stringify(body);
      }

      const t0 = performance.now();
      store.patch('api', { in_flight: (store.get('api.in_flight') || 0) + 1 });
      try {
        const resp = await fetch(url, init);
        const dur = Math.round((performance.now() - t0) * 10) / 10;
        const ctype = (resp.headers.get('content-type') || '').toLowerCase();
        const data = ctype.includes('application/json')
          ? await resp.json()
          : { ok: resp.ok, text: await resp.text(), status: resp.status };

        store.patch('api', {
          in_flight: Math.max(0, (store.get('api.in_flight') || 1) - 1),
          last_latency_ms: dur,
          last_error: resp.ok ? '' : String(data.error || `HTTP ${resp.status}`),
        });

        if (!resp.ok && !opts.silent) {
          const msg = data.error || `HTTP ${resp.status}`;
          if (global.TitanUI && typeof global.TitanUI.toast === 'function') {
            global.TitanUI.toast(msg, 'err');
          }
        }
        if (typeof data === 'object' && data !== null && data._http_status === undefined) {
          data._http_status = resp.status;
        }
        return data;
      } catch (err) {
        store.patch('api', {
          in_flight: Math.max(0, (store.get('api.in_flight') || 1) - 1),
          last_error: String(err.message || err),
        });
        return { ok: false, error: String(err.message || err), _network_error: true };
      }
    },

    get(path, opts) { return this.request('GET', path, null, opts); },
    post(path, body = {}, opts) { return this.request('POST', path, body, opts); },
    patch(path, body = {}, opts) { return this.request('PATCH', path, body, opts); },
    put(path, body = {}, opts) { return this.request('PUT', path, body, opts); },
    del(path, opts) { return this.request('DELETE', path, null, opts); },

    async refreshOverview() {
      const trm = Number(store.get('prefs.trm_cop') || 4200);
      const data = await this.get(`/api/v2/overview?trm_cop=${encodeURIComponent(trm)}`, { silent: true });
      if (data && data.ok) {
        store.set('overview', data);
        const sesAct = data.tiempo && data.tiempo.sesion_activa ? data.tiempo.sesion_activa : null;
        store.set('timer', {
          activa: sesAct,
          elapsed_seg: sesAct ? Number(sesAct.duracion_seg || 0) : 0,
        });
      }
      return data;
    },

    async syncHistory(limit = 50) {
      const data = await this.get(`/api/v2/events/history?limit=${limit}`, { silent: true });
      if (data && data.ok && Array.isArray(data.events)) {
        const ordered = data.events.slice().reverse();
        store.patch('events', { feed: ordered.slice(0, 120) });
        if (data.seq_actual) store.patch('sse', { last_seq: Number(data.seq_actual) });
      }
      return data;
    },
  };

  // ==================== 3. CLIENTE SSE EN VIVO CON RECONEXION EXPONENCIAL ====================
  class TitanSSEClient {
    constructor() {
      this._es = null;
      this._timerReconnect = null;
      this._backoffMs = 1500;
      this._closed = false;
      this._topicHandlers = new Map();
      this._overviewDebounce = null;
    }

    on(topicPattern, fn) {
      const pat = String(topicPattern || '*').toLowerCase();
      if (!this._topicHandlers.has(pat)) this._topicHandlers.set(pat, new Set());
      this._topicHandlers.get(pat).add(fn);
      return () => {
        const s = this._topicHandlers.get(pat);
        if (s) s.delete(fn);
      };
    }

    _matchPattern(topic, pattern) {
      if (pattern === '*') return true;
      if (pattern.endsWith('.*')) return topic.startsWith(pattern.slice(0, -1));
      return topic === pattern;
    }

    _dispatchTopic(evObj) {
      const top = String(evObj.topico || '').toLowerCase();
      for (const [pat, setFns] of this._topicHandlers.entries()) {
        if (this._matchPattern(top, pat)) {
          for (const fn of setFns) {
            try { fn(evObj); } catch (e) { console.error('[TitanSSE] handler error:', e); }
          }
        }
      }
    }

    _handleIncomingEvent(rawData) {
      let ev = null;
      try {
        ev = typeof rawData === 'string' ? JSON.parse(rawData) : rawData;
      } catch (_) {
        return;
      }
      if (!ev || !ev.topico) return;

      const seq = Number(ev.seq_id || 0);
      const prevSeq = Number(store.get('sse.last_seq') || 0);
      if (seq > 0 && seq <= prevSeq) return; // Evita duplicados en reconexion

      if (seq > 0) store.patch('sse', { last_seq: seq, last_event_ts: Date.now() });

      const prevFeed = store.get('events.feed') || [];
      const nextFeed = [ev, ...prevFeed].slice(0, 140);
      const isLog = String(ev.topico).startsWith('log.');
      const unread = Number(store.get('events.unread') || 0) + (isLog ? 0 : 1);
      store.set('events', { feed: nextFeed, unread });

      // Sincronizacion reactiva automatica por dominio
      const top = String(ev.topico);
      if (top.startsWith('tiempo.')) {
        this._scheduleOverviewRefresh(250);
      } else if (
        top.startsWith('crm.') ||
        top.startsWith('finanzas.') ||
        top.startsWith('aegis.') ||
        top.startsWith('factory.') ||
        top.startsWith('sandbox.')
      ) {
        this._scheduleOverviewRefresh(700);
      }

      // Notificaciones toast para eventos de alto valor
      if (global.TitanUI && typeof global.TitanUI.toast === 'function') {
        const p = ev.payload || {};
        if (top === 'crm.lead.nuevo' && Number(p.score || 0) >= 8) {
          global.TitanUI.toast(`🎯 Nuevo Lead Oro (${p.score}/10): ${String(p.titulo || '').slice(0, 56)}`, 'ok');
        } else if (top === 'finanzas.factura.pagada') {
          global.TitanUI.toast(`💵 Pago recibido: +$${p.monto_neto_usd} USD (${p.cliente || ''})`, 'ok');
        } else if (top === 'aegis.drift.detectado') {
          global.TitanUI.toast(`🚨 AEGIS-X Drift crítico (PSI=${p.psi})`, 'warn');
        } else if (top === 'http.circuit.open') {
          global.TitanUI.toast(`🔌 Circuit OPEN en ${p.dominio} (${p.cooldown_seg}s)`, 'warn');
        } else if (top === 'sandbox.autofix.ok') {
          global.TitanUI.toast(`🛠️ Script auto-reparado en ${p.iteraciones} iter.`, 'ok');
        }
      }

      this._dispatchTopic(ev);
    }

    _scheduleOverviewRefresh(delayMs = 500) {
      if (this._overviewDebounce) clearTimeout(this._overviewDebounce);
      this._overviewDebounce = setTimeout(() => {
        TitanAPI.refreshOverview();
      }, delayMs);
    }

    connect() {
      if (typeof EventSource === 'undefined') {
        store.patch('sse', { status: 'offline' });
        return;
      }
      this.disconnect(false);
      this._closed = false;

      const lastId = Number(store.get('sse.last_seq') || 0);
      const tok = TitanAPI.getToken();
      const qs = new URLSearchParams({ topics: '*' });
      if (lastId > 0) qs.set('last_id', String(lastId));
      if (tok) qs.set('token', tok);

      store.patch('sse', { status: lastId > 0 ? 'reconnecting' : 'connecting' });
      const es = new EventSource(`/api/v2/events/stream?${qs.toString()}`);
      this._es = es;

      // Eventos nombrados conocidos + fallback generico
      const KNOWN_EVENTS = [
        'crm.lead.nuevo', 'crm.lead.estado_cambiado', 'crm.lead.eliminado',
        'crm.cliente.creado', 'crm.cliente.fusionado',
        'crm.propuesta.enviada', 'crm.propuesta.respondida',
        'crm.tarea.creada', 'crm.tarea.completada',
        'finanzas.factura.emitida', 'finanzas.factura.pagada', 'finanzas.movimiento.registrado',
        'tiempo.sesion.iniciada', 'tiempo.sesion.detenida', 'tiempo.sesion.registrada',
        'aegis.calibracion.aplicada', 'aegis.drift.detectado',
        'http.circuit.open', 'http.circuit.half_open', 'http.circuit.closed',
        'ai.request.ok', 'ai.fallback', 'ai.budget.exceeded', 'ai.cache.hit',
        'sandbox.exec.ok', 'sandbox.exec.error', 'sandbox.exec.blocked', 'sandbox.autofix.ok',
        'pitch.generado', 'pitch.enviado',
        'factory.producto.creado', 'factory.licencia.emitida', 'factory.licencia.revocada',
        'radar.conectores_pro.completado', 'system.db.optimized', 'system.db.backup',
      ];

      es.addEventListener('system.connected', (e) => {
        this._backoffMs = 1500;
        try {
          const info = JSON.parse(e.data || '{}');
          store.patch('sse', {
            status: 'live',
            sub_id: info.sub_id || '',
            last_seq: Math.max(Number(store.get('sse.last_seq') || 0), Number(info.seq_actual || 0)),
          });
        } catch (_) {
          store.patch('sse', { status: 'live' });
        }
      });

      es.onmessage = (e) => this._handleIncomingEvent(e.data);
      for (const evName of KNOWN_EVENTS) {
        es.addEventListener(evName, (e) => this._handleIncomingEvent(e.data));
      }

      es.onerror = () => {
        if (this._closed) return;
        try { es.close(); } catch (_) {}
        this._es = null;
        const recs = Number(store.get('sse.reconnects') || 0) + 1;
        store.patch('sse', { status: 'reconnecting', reconnects: recs });
        const wait = Math.min(20000, this._backoffMs);
        this._backoffMs = Math.min(20000, Math.round(this._backoffMs * 1.65));
        this._timerReconnect = setTimeout(() => this.connect(), wait);
      };
    }

    disconnect(permanent = true) {
      if (permanent) this._closed = true;
      if (this._timerReconnect) {
        clearTimeout(this._timerReconnect);
        this._timerReconnect = null;
      }
      if (this._es) {
        try { this._es.close(); } catch (_) {}
        this._es = null;
      }
      if (permanent) store.patch('sse', { status: 'offline' });
    }
  }

  const sse = new TitanSSEClient();

  // ==================== 4. TICKER LOCAL DE CRONOMETRO (1 SEGUNDO, CERO POLLING) ====================
  setInterval(() => {
    const t = store.get('timer');
    if (t && t.activa && t.activa.activa) {
      const startEp = Number(t.activa.inicio_epoch || 0);
      const elapsed = startEp > 0 ? Math.max(0, Math.floor(Date.now() / 1000 - startEp)) : (Number(t.elapsed_seg || 0) + 1);
      store.patch('timer', { elapsed_seg: elapsed });
    }
  }, 1000);

  // Arranque automatico no invasivo al cargar el DOM
  function bootstrapTitanStore() {
    TitanAPI.refreshOverview();
    TitanAPI.syncHistory(45);
    sse.connect();
  }

  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', bootstrapTitanStore);
    } else {
      setTimeout(bootstrapTitanStore, 40);
    }
  }

  global.TitanStore = store;
  global.TitanAPI = TitanAPI;
  global.TitanSSE = sse;
})(window);