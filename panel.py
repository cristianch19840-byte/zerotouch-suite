import os
import csv
import sys
import shutil
import subprocess
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core_ia import C, DB_PATH, SESSION, cargar_config, guardar_config, preparar_db, generar_texto_ia

PY_EXE = sys.executable

def editar_config() -> None:
    cfg = cargar_config()
    print(f"\n{C.BOLD}{C.CYAN}=== CONFIGURACION DE PERFIL Y PAGOS (config.json) ==={C.RESET}")
    print(f"{C.DIM}Dale Enter sin escribir nada para dejar el valor actual.{C.RESET}\n")
    campos = [
        ("nombre_marca", "Nombre / Marca freelance"),
        ("especialidad", "Tu especialidad tecnica"),
        ("metodos_pago", "Metodos de pago para pitches (ingles)"),
        ("detalle_pago_factura", "Datos exactos de pago para Facturas HTML"),
        ("github_url", "Link de tu GitHub"),
        ("whop_url", "Link de tu tienda Whop"),
        ("score_minimo", "Score minimo para alertar en Telegram (ej. 6 o 7)"),
        ("intervalo_sniper_seg", "Segundos entre barridos en Modo Sniper (min 45)"),
    ]
    for clave, etiqueta in campos:
        actual = cfg.get(clave, "")
        nuevo = input(f"{etiqueta} [{actual}]: ").strip()
        if nuevo:
            if clave in ("score_minimo", "intervalo_sniper_seg"):
                try:
                    cfg[clave] = int(nuevo)
                except ValueError:
                    pass
            else:
                cfg[clave] = nuevo
    guardar_config(cfg)
    print(f"\n{C.GREEN}[+] Configuracion guardada localmente en config.json (protegida por .gitignore)!{C.RESET}\n")

def ver_crm() -> None:
    conn = preparar_db()
    try:
        filas = conn.execute(
            "SELECT id, fuente, score, presupuesto, estado, ganancia_usd, titulo FROM leads ORDER BY id DESC LIMIT 15"
        ).fetchall()
        total_usd = conn.execute("SELECT COALESCE(SUM(ganancia_usd), 0) FROM leads WHERE estado = 'ganado'").fetchone()[0]
        total_leads = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]

        print(f"\n{C.BOLD}{C.GREEN}=== MINI-CRM OMEGA | LEADS: {total_leads} | GANADO: ${total_usd:.2f} USD ==={C.RESET}")
        if not filas:
            print("Aun no hay leads locales. Corre [1] Sniper o [2] Dashboard Web.")
        else:
            for r in filas:
                col = C.GREEN if r[4] == "ganado" else (C.YELLOW if r[4] in ("contactado", "negociando") else C.CYAN)
                print(f"#{r[0]:<3} {col}[{r[4].upper():<10}]{C.RESET} {r[1]:<16} ({r[2]}/10 | {r[3]:<12} | ${r[5]:.0f}) -> {r[6][:46]}")

        print("\nComandos: #ID para editar | 'CSV' para exportar Excel | 'BACKUP' para respaldar DB | Enter para volver")
        cmd = input("> ").strip()
        if cmd.upper() == "CSV":
            ruta_csv = os.path.join(ROOT_DIR, f"crm_omega_{datetime.now().strftime('%Y%m%d')}.csv")
            todos = conn.execute("SELECT id, fecha, fuente, autor, titulo, categoria, presupuesto, score, competencia, confianza, estado, ganancia_usd, link FROM leads ORDER BY id DESC").fetchall()
            with open(ruta_csv, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["ID", "Fecha", "Fuente", "Autor", "Titulo", "Categoria", "Presupuesto", "Score", "Competencia", "Confianza", "Estado", "Ganancia_USD", "Link"])
                w.writerows(todos)
            print(f"{C.GREEN}[+] Exportado a: {ruta_csv}{C.RESET}\n")
        elif cmd.upper() == "BACKUP":
            os.makedirs(os.path.join(ROOT_DIR, "backups"), exist_ok=True)
            dst = os.path.join(ROOT_DIR, "backups", f"db_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.db")
            shutil.copy2(DB_PATH, dst)
            print(f"{C.GREEN}[+] Respaldo guardado en: {dst}{C.RESET}\n")
        elif cmd.isdigit():
            est = input("Nuevo estado (contactado / negociando / ganado / descartado): ").strip().lower() or "contactado"
            monto = 0.0
            if est == "ganado":
                try:
                    monto = float(input("Cuantos USD cobraste?: ").strip())
                except ValueError:
                    monto = 0.0
            conn.execute("UPDATE leads SET estado = ?, ganancia_usd = CASE WHEN ? > 0 THEN ? ELSE ganancia_usd END WHERE id = ?", (est, monto, monto, int(cmd)))
            conn.commit()
            print(f"{C.GREEN}[+] Lead #{cmd} actualizado!{C.RESET}\n")
    finally:
        conn.close()

def diagnostico_total() -> None:
    print(f"\n{C.BOLD}{C.CYAN}=== DIAGNOSTICO TOTAL OMEGA v9.0 ==={C.RESET}")
    key = os.getenv("GEMINI_API_KEY_FREE")
    tg_tok = os.getenv("TELEGRAM_TOKEN")
    tg_id = os.getenv("TELEGRAM_CHAT_ID")
    print(f"1. Archivo .env      : {'OK' if os.path.exists(os.path.join(ROOT_DIR, '.env')) else 'FALTA'}")
    print(f"2. config.json       : {'OK' if os.path.exists(os.path.join(ROOT_DIR, 'config.json')) else 'Default'}")
    print(f"3. GEMINI_API_KEY    : {'Cargada' if key else 'FALTA'}")
    print(f"4. TELEGRAM_TOKEN    : {'Cargada' if tg_tok else 'FALTA'}")
    print(f"5. TELEGRAM_CHAT_ID  : {tg_id if tg_id else 'FALTA'}")

    if tg_tok:
        try:
            r = SESSION.get(f"https://api.telegram.org/bot{tg_tok}/getMe", timeout=8)
            estado_tg = f"OK (@{r.json()['result']['username']})" if r.status_code == 200 else f"Error {r.status_code}"
        except Exception as e:
            estado_tg = f"Error ({e})"
        print(f"6. Conexion Telegram : {estado_tg}")

    try:
        r_red = SESSION.get("https://www.reddit.com/r/forhire/new.json?limit=1", headers={"User-Agent": "python:zerotouch-diag:v9.0"}, timeout=8)
        print(f"7. Conexion Reddit   : {'OK (JSON en vivo)' if r_red.status_code == 200 else f'Fallback XML Nativo (HTTP {r_red.status_code})'}")
    except Exception as e:
        print(f"7. Conexion Reddit   : Error ({e})")

    if key:
        resp = generar_texto_ia("Responde solo con la palabra: OK", temperatura=0.0, timeout=12)
        print(f"8. Conexion Gemini   : {'OK' if resp else 'SIN RESPUESTA'}")
    print()

def main() -> None:
    while True:
        print(f"\n{C.BOLD}{C.CYAN}==========================================================")
        print("           ZEROTOUCH SUITE v9.0 — OMEGA EDITION")
        print(f"=========================================================={C.RESET}")
        print(f" {C.MAGENTA}[1]{C.RESET} MODO FRANCOTIRADOR (Escaneo 75s + Trust Radar + Sonido)")
        print(f" {C.CYAN}[2]{C.RESET} DASHBOARD WEB LOCAL (Interfaz grafica en tu navegador)")
        print(f" {C.GREEN}[3]{C.RESET} Copiloto Auto-Reparable (Link Reddit / #ID CRM / Texto)")
        print(f" {C.YELLOW}[4]{C.RESET} Negociador IA en Vivo (Responder objeciones)")
        print(f" {C.BLUE}[5]{C.RESET} Iman de Clientes (Posts [For Hire] + Bios + Portafolio)")
        print(f" {C.MAGENTA}[6]{C.RESET} Fabrica Whop (.ZIP) & Factura HTML/PDF para Cliente")
        print(f" {C.GREEN}[7]{C.RESET} Mini-CRM en Consola + Exportar Excel + Backup DB")
        print(f" {C.YELLOW}[8]{C.RESET} Configurar Perfil, Metodos de Pago y Filtros (config.json)")
        print(f" {C.DIM}[9]{C.RESET} Probar Radar | Resumen Diario TG | Diagnostico Total")
        print(f" {C.RED}[0]{C.RESET} Salir")
        op = input(f"\n{C.BOLD}Elige una opcion: {C.RESET}").strip()

        if op == "1":
            subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "modulo_a_radar_whop", "motor_zerotouch_v4.py"), "--sniper"])
        elif op == "2":
            subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "dashboard_web.py")])
        elif op == "3":
            subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "modulo_b_ejecutor", "copiloto.py")])
        elif op == "4":
            subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "modulo_d_marketing", "iman_clientes.py"), "--negociar"])
        elif op == "5":
            subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "modulo_d_marketing", "iman_clientes.py")])
        elif op == "6":
            subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "modulo_c_whop", "empaquetador.py")])
        elif op == "7":
            ver_crm()
        elif op == "8":
            editar_config()
        elif op == "9":
            print("\n [a] Enviar alerta de prueba a Telegram\n [b] Enviar resumen diario de estadisticas a Telegram\n [c] Diagnostico total de conexiones")
            sub = input("Elige [a/b/c]: ").strip().lower()
            if sub == "a":
                subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "modulo_a_radar_whop", "motor_zerotouch_v4.py"), "--test"])
            elif sub == "b":
                subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "modulo_a_radar_whop", "motor_zerotouch_v4.py"), "--resumen"])
            else:
                diagnostico_total()
        elif op == "0":
            print(f"{C.GREEN}A romperla facturando, bro.{C.RESET}")
            break
        else:
            print(f"{C.RED}[!] Opcion no valida.{C.RESET}")

if __name__ == "__main__":
    main()