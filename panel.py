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
        print(f"\n{C.BOLD}{C.CYAN}==============================================================")
        print("         ZEROTOUCH SUITE v13.0 — OMNI-GRID PANEL")
        print(f"=============================================================={C.RESET}")
        print(f"{C.BOLD}  [OPERACION MULTI-PLATAFORMA (12+ FUENTES)]{C.RESET}")
        print(f"   {C.GREEN}[1]{C.RESET} Abrir Dashboard Web OS v13 (TODO en 1 interfaz)")
        print(f"   {C.MAGENTA}[2]{C.RESET} Modo Francotirador OMNI (12+ Fuentes + Batch IA)")
        print(f"   {C.CYAN}[3]{C.RESET} Control Remoto Telegram 2-Vias (/scan /fuentes /toggle)")
        print(f"   {C.BLUE}[4]{C.RESET} Test Dry-Run 0-Tokens + Ver Salud de Plataformas")
        print(f"\n{C.BOLD}  [CERRAR, COBRAR & VENDER]{C.RESET}")
        print(f"   {C.YELLOW}[5]{C.RESET} Copiloto Universal (Cualquier Link / #ID / Refinar)")
        print(f"   {C.YELLOW}[6]{C.RESET} Negociador Mata-Objeciones en Vivo")
        print(f"   {C.BLUE}[7]{C.RESET} Marketing (Posts [For Hire] + Bios + Portafolio)")
        print(f"   {C.MAGENTA}[8]{C.RESET} Fabrica Whop (.ZIP) & Factura + Micro-Contrato PDF")
        print(f"\n{C.BOLD}  [SISTEMA & AUDITORIA]{C.RESET}")
        print(f"   {C.DIM}[9]{C.RESET} Alerta de Prueba TG | Resumen Diario TG | Backup DB")
        print(f"   {C.DIM}[T]{C.RESET} Correr Auto-Test E2E Completo (test_e2e_v13.py)")
        print(f"   {C.RED}[0]{C.RESET} Salir")
        op = input(f"\n{C.BOLD}Elige una opcion: {C.RESET}").strip().upper()

        if op == "1":
            subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "dashboard_web.py")])
        elif op == "2":
            subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "modulo_a_radar_whop", "motor_zerotouch_v4.py"), "--sniper"])
        elif op == "3":
            subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "telegram_bot_control.py")])
        elif op == "4":
            subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "modulo_a_radar_whop", "motor_zerotouch_v4.py"), "--dry-run"])
            subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "modulo_a_radar_whop", "motor_zerotouch_v4.py"), "--fuentes"])
        elif op == "5":
            subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "modulo_b_ejecutor", "copiloto.py")])
        elif op == "6":
            subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "modulo_d_marketing", "iman_clientes.py"), "--negociar"])
        elif op == "7":
            subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "modulo_d_marketing", "iman_clientes.py")])
        elif op == "8":
            subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "modulo_c_whop", "empaquetador.py")])
        elif op == "9":
            print("\n [a] Enviar alerta de prueba a Telegram\n [b] Enviar resumen diario a Telegram\n [c] Crear backup rotativo de la DB")
            sub = input("Elige [a/b/c]: ").strip().lower()
            if sub == "a":
                subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "modulo_a_radar_whop", "motor_zerotouch_v4.py"), "--test"])
            elif sub == "b":
                subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "modulo_a_radar_whop", "motor_zerotouch_v4.py"), "--resumen"])
            else:
                dst = crear_backup_rotativo()
                print(f"{C.GREEN}[+] Backup creado: {dst}{C.RESET}" if dst else f"{C.YELLOW}[!] Sin DB aun.{C.RESET}")
        elif op == "T":
            subprocess.run([PY_EXE, os.path.join(ROOT_DIR, "test_e2e_v13.py")])
        elif op == "0":
            print(f"{C.GREEN}A romperla facturando duro, bro.{C.RESET}")
            break
        else:
            print(f"{C.RED}[!] Opcion no valida.{C.RESET}")

if __name__ == "__main__":
    main()