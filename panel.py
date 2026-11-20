import os
import sys
import sqlite3
import subprocess

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core_ia import SESSION, generar_texto_ia

PY_EXE = sys.executable
DB_PATH = os.path.join(ROOT_DIR, "estado_radar_v4.db")

def ver_crm() -> None:
    if not os.path.exists(DB_PATH):
        print("\n[!] Todavia no hay base de datos local. Corre primero una prueba o ciclo del radar.\n")
        return
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha DATETIME DEFAULT CURRENT_TIMESTAMP,
                fuente TEXT, titulo TEXT, categoria TEXT, presupuesto TEXT,
                score INTEGER, link TEXT, estado TEXT DEFAULT 'nuevo', ganancia_usd REAL DEFAULT 0
            )
            """
        )
        filas = conn.execute(
            "SELECT id, fuente, score, presupuesto, estado, ganancia_usd, titulo FROM leads ORDER BY id DESC LIMIT 12"
        ).fetchall()
        total_usd = conn.execute("SELECT COALESCE(SUM(ganancia_usd), 0) FROM leads WHERE estado = 'ganado'").fetchone()[0]

        print(f"\n=== MINI-CRM ZEROTOUCH | TOTAL GANADO: ${total_usd:.2f} USD ===")
        if not filas:
            print("Aun no hay leads guardados localmente.")
        else:
            for r in filas:
                print(f"#{r[0]} [{r[4].upper()}] {r[1]} ({r[2]}/10 | {r[3]} | ${r[5]:.0f}) -> {r[6][:55]}")

        opcion = input("\nEscribe el #ID para marcar como GANADO y anotar USD (o Enter para volver): ").strip()
        if opcion.isdigit():
            monto = input("Cuantos USD cobraste por este cliente?: ").strip()
            try:
                val = float(monto)
                conn.execute("UPDATE leads SET estado = 'ganado', ganancia_usd = ? WHERE id = ?", (val, int(opcion)))
                conn.commit()
                print(f"[+] Lead #{opcion} marcado como GANADO (+${val:.2f} USD)!\n")
            except ValueError:
                print("[!] Monto invalido.\n")
    finally:
        conn.close()

def diagnostico_sistema() -> None:
    print("\n=== DIAGNOSTICO DE SALUD ZEROTOUCH v7.0 ===")
    key = os.getenv("GEMINI_API_KEY_FREE")
    tg_tok = os.getenv("TELEGRAM_TOKEN")
    tg_id = os.getenv("TELEGRAM_CHAT_ID")
    print(f"1. Archivo .env      : {'OK' if os.path.exists(os.path.join(ROOT_DIR, '.env')) else 'FALTA'}")
    print(f"2. GEMINI_API_KEY    : {'Cargada' if key else 'FALTA'}")
    print(f"3. TELEGRAM_TOKEN    : {'Cargada' if tg_tok else 'FALTA'}")
    print(f"4. TELEGRAM_CHAT_ID  : {tg_id if tg_id else 'FALTA'}")

    if tg_tok:
        try:
            r = SESSION.get(f"https://api.telegram.org/bot{tg_tok}/getMe", timeout=8)
            estado_tg = f"OK (@{r.json()['result']['username']})" if r.status_code == 200 else f"Error {r.status_code}"
        except Exception as e:
            estado_tg = f"Error ({e})"
        print(f"5. Conexion Telegram : {estado_tg}")

    if key:
        resp = generar_texto_ia("Responde solo con la palabra: OK", temperatura=0.0, timeout=12)
        print(f"6. Conexion Gemini   : {'OK' if resp else 'SIN RESPUESTA'}")
    print()

def main() -> None:
    while True:
        print("\n==============================================")
        print("       ZEROTOUCH SUITE v7.0 - PANEL")
        print("==============================================")
        print(" [1] Cazar oferta (Copiloto: Link Reddit / Texto)")
        print(" [2] Empaquetar script a .ZIP para Whop")
        print(" [3] Mini-CRM de Leads y Ganancias (USD)")
        print(" [4] Probar Radar (envia alerta de prueba a TG)")
        print(" [5] Diagnostico de salud (.env + Gemini + TG)")
        print(" [0] Salir")
        op = input("\nElige una opcion: ").strip()

        if op == "1":
            subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "modulo_b_ejecutor", "copiloto.py")])
        elif op == "2":
            subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "modulo_c_whop", "empaquetador.py")])
        elif op == "3":
            ver_crm()
        elif op == "4":
            subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "modulo_a_radar_whop", "motor_zerotouch_v4.py"), "--test"])
        elif op == "5":
            diagnostico_sistema()
        elif op == "0":
            print("A facturar, bro.")
            break
        else:
            print("[!] Opcion no valida.")

if __name__ == "__main__":
    main()