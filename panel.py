import os
import sys
import subprocess

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core_ia import C, crear_backup_rotativo

PY_EXE = sys.executable

def main() -> None:
    while True:
        print(f"\n{C.BOLD}{C.CYAN}======================================================")
        print("        ZEROTOUCH SUITE v10.5 — PANEL ORDENADO")
        print(f"======================================================{C.RESET}")
        print(f"{C.BOLD}  [CAZAR & AUTOMATIZAR]{C.RESET}")
        print(f"   {C.GREEN}[1]{C.RESET} Abrir Dashboard Web OS (TODO en 1 interfaz)")
        print(f"   {C.MAGENTA}[2]{C.RESET} Modo Francotirador 24/7 (Escaneo 70s + Sonido)")
        print(f"   {C.CYAN}[3]{C.RESET} Control Remoto Telegram 2-Vias (/scan /pitch)")
        print(f"\n{C.BOLD}  [CERRAR, COBRAR & VENDER]{C.RESET}")
        print(f"   {C.YELLOW}[4]{C.RESET} Copiloto de Ofertas en Consola (Pitch A/B + AST)")
        print(f"   {C.YELLOW}[5]{C.RESET} Negociador Mata-Objeciones en Vivo")
        print(f"   {C.BLUE}[6]{C.RESET} Marketing (Posts [For Hire] + Bios + Portafolio)")
        print(f"   {C.MAGENTA}[7]{C.RESET} Empaquetador Whop (.ZIP) & Factura HTML/PDF")
        print(f"\n{C.BOLD}  [SISTEMA]{C.RESET}")
        print(f"   {C.DIM}[8]{C.RESET} Enviar Alerta de Prueba a Telegram")
        print(f"   {C.DIM}[9]{C.RESET} Enviar Resumen Diario a Telegram | Backup DB")
        print(f"   {C.RED}[0]{C.RESET} Salir")
        op = input(f"\n{C.BOLD}Elige una opcion: {C.RESET}").strip()

        if op == "1":
            subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "dashboard_web.py")])
        elif op == "2":
            subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "modulo_a_radar_whop", "motor_zerotouch_v4.py"), "--sniper"])
        elif op == "3":
            subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "telegram_bot_control.py")])
        elif op == "4":
            subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "modulo_b_ejecutor", "copiloto.py")])
        elif op == "5":
            subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "modulo_d_marketing", "iman_clientes.py"), "--negociar"])
        elif op == "6":
            subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "modulo_d_marketing", "iman_clientes.py")])
        elif op == "7":
            subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "modulo_c_whop", "empaquetador.py")])
        elif op == "8":
            subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "modulo_a_radar_whop", "motor_zerotouch_v4.py"), "--test"])
        elif op == "9":
            subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "modulo_a_radar_whop", "motor_zerotouch_v4.py"), "--resumen"])
            dst = crear_backup_rotativo()
            if dst:
                print(f"{C.GREEN}[+] Backup creado en: {dst}{C.RESET}")
        elif op == "0":
            print(f"{C.GREEN}A facturar, bro.{C.RESET}")
            break
        else:
            print(f"{C.RED}[!] Opcion no valida.{C.RESET}")

if __name__ == "__main__":
    main()