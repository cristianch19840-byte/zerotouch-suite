import os
import io
import csv
import sys
import json
import threading
import webbrowser
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core_ia import C, preparar_db
from modulo_a_radar_whop.motor_zerotouch_v4 import ejecutar_ciclo

SCAN_LOCK = threading.Lock()
SCAN_STATE = {"running": False, "last_result": None}

HTML_DASHBOARD = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ZeroTouch OMEGA v9.0 — Dashboard</title>
<style>
  :root { --bg:#090d16; --card:#111827; --border:#1f2937; --text:#f3f4f6; --muted:#9ca3af; --accent:#38bdf8; --green:#4ade80; --amber:#fbbf24; --red:#f87171; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:'Segoe UI',system-ui,sans-serif; background:var(--bg); color:var(--text); padding:24px; }
  .wrap { max-width:1320px; margin:0 auto; }
  header { display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:14px; margin-bottom:22px; }
  h1 { margin:0; font-size:22px; letter-spacing:-.02em; }
  h1 span { color:var(--accent); }
  .actions { display:flex; gap:10px; flex-wrap:wrap; }
  button, a.btn { background:#1e293b; color:var(--text); border:1px solid #334155; padding:9px 15px; border-radius:8px; cursor:pointer; font-size:13px; font-weight:600; text-decoration:none; transition:.15s; }
  button:hover, a.btn:hover { background:#334155; border-color:var(--accent); }
  button.primary { background:linear-gradient(135deg,#0284c7,#2563eb); border:none; }
  button.primary:hover { filter:brightness(1.1); }
  .kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:14px; margin-bottom:22px; }
  .kpi { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:18px; }
  .kpi .lbl { font-size:12px; text-transform:uppercase; color:var(--muted); letter-spacing:.05em; }
  .kpi .num { font-size:28px; font-weight:700; margin-top:6px; }
  .num.green { color:var(--green); }
  .num.cyan { color:var(--accent); }
  .num.amber { color:var(--amber); }
  .toolbar { display:flex; gap:10px; flex-wrap:wrap; margin-bottom:14px; align-items:center; }
  input, select { background:#0f172a; color:var(--text); border:1px solid #334155; padding:8px 11px; border-radius:8px; font-size:13px; }
  .table-box { background:var(--card); border:1px solid var(--border); border-radius:12px; overflow:auto; }
  table { width:100%; border-collapse:collapse; min-width:960px; }
  th, td { padding:12px 14px; border-bottom:1px solid var(--border); text-align:left; font-size:13px; vertical-align:middle; }
  th { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.06em; background:#0f172a; }
  tr:hover { background:#172033; }
  .score { display:inline-block; padding:3px 8px; border-radius:6px; font-weight:700; font-size:12px; }
  .s-hi { background:#14532d; color:#86efac; }
  .s-mid { background:#1e3a8a; color:#93c5fd; }
  a.title-link { color:#e2e8f0; text-decoration:none; font-weight:600; }
  a.title-link:hover { color:var(--accent); text-decoration:underline; }
  .meta { font-size:11px; color:var(--muted); margin-top:3px; }
  .usd-in { width:78px; }
  .save-btn { padding:6px 10px; font-size:12px; background:#065f46; border-color:#10b981; }
  .status-bar { font-size:12px; color:var(--amber); margin-left:auto; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>⚡ ZeroTouch <span>OMEGA v9.0</span> — Centro de Mando</h1>
      <div class="meta">CRM local en vivo + Radar de oportunidades + Control de ingresos</div>
    </div>
    <div class="actions">
      <button class="primary" id="btnScan" onclick="lanzarEscaneo()">🚀 Escanear Reddit Ahora</button>
      <button onclick="cargarDatos()">🔄 Refrescar</button>
      <a class="btn" href="/api/export">📥 Exportar Excel (.CSV)</a>
    </div>
  </header>

  <div class="kpis">
    <div class="kpi"><div class="lbl">Facturado Total</div><div class="num green" id="kUsd">$0.00</div></div>
    <div class="kpi"><div class="lbl">Leads Detectados</div><div class="num cyan" id="kLeads">0</div></div>
    <div class="kpi"><div class="lbl">Clientes Cerrados</div><div class="num green" id="kGanados">0</div></div>
    <div class="kpi"><div class="lbl">Basura Filtrada (0 Tokens)</div><div class="num amber" id="kAhorro">0</div></div>
  </div>

  <div class="toolbar">
    <input type="text" id="qSearch" placeholder="Buscar titulo, subreddit o categoria..." oninput="renderTabla()" style="min-width:260px;">
    <select id="qEstado" onchange="renderTabla()">
      <option value="">Todos los estados</option>
      <option value="nuevo">Nuevo</option>
      <option value="contactado">Contactado</option>
      <option value="negociando">Negociando</option>
      <option value="ganado">Ganado</option>
      <option value="descartado">Descartado</option>
    </select>
    <div class="status-bar" id="scanStatus"></div>
  </div>

  <div class="table-box">
    <table>
      <thead>
        <tr>
          <th>ID</th><th>Score</th><th>Fuente</th><th>Proyecto & Cliente</th><th>Presupuesto</th><th>Estado</th><th>USD</th><th>Accion</th>
        </tr>
      </thead>
      <tbody id="tbodyLeads"></tbody>
    </table>
  </div>
</div>

<script>
let LEADS = [];
function esc(s){ return String(s||'').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }

async function cargarDatos(){
  const r = await fetch('/api/data');
  const d = await r.json();
  LEADS = d.leads || [];
  document.getElementById('kUsd').textContent = '$' + Number(d.kpis.usd || 0).toFixed(2);
  document.getElementById('kLeads').textContent = d.kpis.leads;
  document.getElementById('kGanados').textContent = d.kpis.ganados;
  document.getElementById('kAhorro').textContent = d.kpis.descartados;
  const st = document.getElementById('scanStatus');
  if(d.scan.running){ st.textContent = '⏳ Escaneando 14 fuentes en segundo plano...'; }
  else if(d.scan.last_result){ const lr = d.scan.last_result; st.textContent = `✅ Ultimo barrido: ${lr.alertas} alertas | ${lr.descartados} filtrados 0-tokens (${lr.segundos}s)`; }
  renderTabla();
}

function renderTabla(){
  const q = document.getElementById('qSearch').value.toLowerCase();
  const est = document.getElementById('qEstado').value;
  const filtrados = LEADS.filter(l => (!est || l.estado === est) && (!q || (l.titulo+' '+l.fuente+' '+l.categoria).toLowerCase().includes(q)));
  const tb = document.getElementById('tbodyLeads');
  if(!filtrados.length){ tb.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#9ca3af;padding:28px;">No hay leads con este filtro todavia. Haz clic en "Escanear Reddit Ahora".</td></tr>'; return; }
  tb.innerHTML = filtrados.map(l => `
    <tr>
      <td><b>#${l.id}</b></td>
      <td><span class="score ${l.score>=8?'s-hi':'s-mid'}">${l.score}/10</span></td>
      <td><div>${esc(l.fuente)}</div><div class="meta">${esc(l.categoria)}</div></td>
      <td>
        <a class="title-link" href="${esc(l.link)}" target="_blank">${esc(l.titulo)}</a>
        <div class="meta">${esc(l.competencia)} ${l.confianza ? ' • ' + esc(l.confianza) : ''}</div>
      </td>
      <td>${esc(l.presupuesto)}</td>
      <td>
        <select id="est_${l.id}">
          ${['nuevo','contactado','negociando','ganado','descartado'].map(o => `<option value="${o}" ${l.estado===o?'selected':''}>${o}</option>`).join('')}
        </select>
      </td>
      <td><input class="usd-in" type="number" step="1" id="usd_${l.id}" value="${l.ganancia_usd || 0}"></td>
      <td><button class="save-btn" onclick="guardarLead(${l.id})">Guardar</button></td>
    </tr>
  `).join('');
}

async function guardarLead(id){
  const estado = document.getElementById('est_'+id).value;
  const usd = parseFloat(document.getElementById('usd_'+id).value || 0);
  await fetch('/api/update', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id, estado, usd}) });
  await cargarDatos();
}

async function lanzarEscaneo(){
  document.getElementById('scanStatus').textContent = '⏳ Iniciando escaneo OMEGA...';
  await fetch('/api/scan', { method:'POST' });
  setTimeout(cargarDatos, 2000);
}

cargarDatos();
setInterval(cargarDatos, 12000);
</script>
</body>
</html>
"""

def correr_scan_bg() -> None:
    if not SCAN_LOCK.acquire(blocking=False):
        return
    SCAN_STATE["running"] = True
    try:
        res = ejecutar_ciclo(modo_sonido=True)
        SCAN_STATE["last_result"] = res
    finally:
        SCAN_STATE["running"] = False
        SCAN_LOCK.release()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send(self, code: int, content_type: str, data: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/":
            self._send(200, "text/html; charset=utf-8", HTML_DASHBOARD.encode("utf-8"))
        elif self.path == "/api/data":
            conn = preparar_db()
            try:
                rows = conn.execute(
                    "SELECT id, fecha, fuente, autor, titulo, categoria, presupuesto, score, competencia, confianza, link, estado, ganancia_usd FROM leads ORDER BY id DESC LIMIT 120"
                ).fetchall()
                leads = [
                    {
                        "id": r[0], "fecha": r[1], "fuente": r[2], "autor": r[3], "titulo": r[4],
                        "categoria": r[5], "presupuesto": r[6], "score": r[7], "competencia": r[8],
                        "confianza": r[9], "link": r[10], "estado": r[11], "ganancia_usd": r[12],
                    }
                    for r in rows
                ]
                usd = conn.execute("SELECT COALESCE(SUM(ganancia_usd), 0) FROM leads WHERE estado = 'ganado'").fetchone()[0]
                ganados = conn.execute("SELECT COUNT(*) FROM leads WHERE estado = 'ganado'").fetchone()[0]
                descartados = conn.execute("SELECT COALESCE(SUM(descartados_local), 0) FROM stats_diarias").fetchone()[0]
                payload = {
                    "leads": leads,
                    "kpis": {"usd": usd, "leads": len(leads), "ganados": ganados, "descartados": descartados},
                    "scan": SCAN_STATE,
                }
                self._send(200, "application/json; charset=utf-8", json.dumps(payload).encode("utf-8"))
            finally:
                conn.close()
        elif self.path == "/api/export":
            conn = preparar_db()
            try:
                rows = conn.execute(
                    "SELECT id, fecha, fuente, autor, titulo, categoria, presupuesto, score, competencia, confianza, estado, ganancia_usd, link FROM leads ORDER BY id DESC"
                ).fetchall()
                buf = io.StringIO()
                w = csv.writer(buf)
                w.writerow(["ID", "Fecha", "Fuente", "Autor", "Titulo", "Categoria", "Presupuesto", "Score", "Competencia", "Confianza", "Estado", "Ganancia_USD", "Link"])
                w.writerows(rows)
                data = ("\ufeff" + buf.getvalue()).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="crm_omega_{datetime.now().strftime("%Y%m%d")}.csv"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            finally:
                conn.close()
        else:
            self._send(404, "text/plain", b"Not Found")

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else b"{}"
        if self.path == "/api/update":
            data = json.loads(body.decode("utf-8"))
            conn = preparar_db()
            try:
                conn.execute(
                    "UPDATE leads SET estado = ?, ganancia_usd = ? WHERE id = ?",
                    (str(data.get("estado", "nuevo")), float(data.get("usd", 0)), int(data.get("id"))),
                )
                conn.commit()
            finally:
                conn.close()
            self._send(200, "application/json", b'{"ok": true}')
        elif self.path == "/api/scan":
            threading.Thread(target=correr_scan_bg, daemon=True).start()
            self._send(200, "application/json", b'{"started": true}')
        else:
            self._send(404, "text/plain", b"Not Found")

def main() -> None:
    puerto = 8765
    server = ThreadingHTTPServer(("127.0.0.1", puerto), Handler)
    url = f"http://127.0.0.1:{puerto}"
    print(f"\n{C.BOLD}{C.GREEN}=== DASHBOARD WEB ZEROTOUCH OMEGA CORRIENDO EN: {url} ==={C.RESET}")
    print(f"{C.DIM}Presiona Ctrl+C en esta consola cuando quieras apagar el servidor web.{C.RESET}\n")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\n{C.YELLOW}[*] Dashboard web cerrado.{C.RESET}\n")
    finally:
        server.server_close()

if __name__ == "__main__":
    main()