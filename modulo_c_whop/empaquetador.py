import os
import re
import sys
import html
import zipfile
from datetime import datetime

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core_ia import (
    C,
    log_evento,
    cargar_config,
    generar_texto_ia,
    extraer_etiqueta,
    limpiar_bloque_codigo,
    validar_y_reparar_python,
    analizar_dependencias,
)

def crear_factura_html(cliente: str, proyecto: str, monto: str, tipo_cobro: str = "Final Payment (Full Delivery)", incluir_contrato: bool = True, notas_extra: str = "") -> tuple[str, str]:
    cfg = cargar_config()
    num_factura = f"ZT-{datetime.now().strftime('%Y%m%d-%H%M')}"
    fecha = datetime.now().strftime("%B %d, %Y")

    bloque_nota = f'<div class="paybox" style="margin-top:14px;"><div class="label">Notes / Deliverables</div><div class="val" style="font-size:13.5px;margin-top:6px;">{html.escape(notas_extra)}</div></div>' if notas_extra.strip() else ""
    bloque_contrato = ""
    if incluir_contrato:
        bloque_contrato = """
    <div class="terms">
      <div class="label" style="margin-bottom:8px;">Micro-Contract & Scope Terms</div>
      <ul>
        <li>Deliverables match the exact scope and specifications agreed in chat.</li>
        <li>Includes 1 minor revision round within 5 days of delivery for bug fixes.</li>
        <li>New features or out-of-scope site changes are quoted separately.</li>
        <li>Full source code and documentation are transferred immediately upon payment confirmation.</li>
      </ul>
    </div>"""

    factura_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Invoice {num_factura}</title>
<style>
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #0b1120; color: #e2e8f0; margin: 0; padding: 36px; }}
  .card {{ max-width: 740px; margin: 0 auto; background: #1e293b; border-radius: 16px; padding: 36px; border: 1px solid #334155; box-shadow: 0 20px 50px rgba(0,0,0,.35); }}
  .top {{ display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 1px solid #334155; padding-bottom: 20px; }}
  h1 {{ margin: 0; color: #38bdf8; font-size: 24px; }}
  .badge {{ background: #0ea5e922; color: #38bdf8; padding: 6px 14px; border-radius: 999px; font-size: 13px; font-weight: 700; border: 1px solid #0ea5e955; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin: 24px 0; }}
  .label {{ font-size: 11px; text-transform: uppercase; color: #94a3b8; letter-spacing: .07em; font-weight: 700; }}
  .val {{ font-size: 16px; margin-top: 4px; font-weight: 500; }}
  table {{ width: 100%; border-collapse: collapse; margin: 24px 0; }}
  th, td {{ text-align: left; padding: 14px; border-bottom: 1px solid #334155; }}
  th {{ color: #94a3b8; font-size: 12px; text-transform: uppercase; }}
  .total {{ font-size: 24px; color: #4ade80; font-weight: 800; text-align: right; }}
  .paybox, .terms {{ background: #0f172a; border: 1px solid #334155; border-radius: 10px; padding: 16px 18px; margin-top: 20px; }}
  .terms ul {{ margin: 0; padding-left: 18px; font-size: 13px; color: #cbd5e1; line-height: 1.55; }}
  .foot {{ margin-top: 24px; font-size: 12px; color: #64748b; text-align: center; }}
  @media print {{ body {{ background: #fff; color: #0f172a; padding: 0; }} .card {{ background: #fff; border: 1px solid #cbd5e1; box-shadow: none; }} .paybox, .terms {{ background: #f8fafc; }} .terms ul {{ color: #334155; }} }}
</style>
</head>
<body>
  <div class="card">
    <div class="top">
      <div>
        <h1>{html.escape(cfg.get('nombre_marca', 'ZeroTouch Dev'))}</h1>
        <div class="label" style="margin-top:6px;">{html.escape(cfg.get('github_url', ''))}</div>
      </div>
      <div style="text-align:right;">
        <div class="badge">INVOICE #{num_factura}</div>
        <div class="label" style="margin-top:8px;">Date: {fecha}</div>
      </div>
    </div>
    <div class="grid">
      <div><div class="label">Billed To</div><div class="val">{html.escape(cliente)}</div></div>
      <div><div class="label">Milestone / Status</div><div class="val">{html.escape(tipo_cobro)}</div></div>
    </div>
    <table>
      <thead><tr><th>Deliverable / Service Description</th><th style="text-align:right;">Amount (USD)</th></tr></thead>
      <tbody>
        <tr><td>{html.escape(proyecto)}</td><td style="text-align:right;">${html.escape(monto)} USD</td></tr>
      </tbody>
    </table>
    <div class="total">Total Due: ${html.escape(monto)} USD</div>
    <div class="paybox">
      <div class="label">Accepted Payment Methods</div>
      <div class="val" style="font-size:14px; margin-top:8px;">{html.escape(cfg.get('detalle_pago_factura', cfg.get('metodos_pago', '')))}</div>
    </div>
    {bloque_nota}
    {bloque_contrato}
    <div class="foot">Thank you for your trust! Press Ctrl+P to save as PDF.</div>
  </div>
</body>
</html>"""
    return num_factura, factura_html

def guardar_factura_local(cliente: str, proyecto: str, monto: str, tipo_cobro: str = "Final Payment (Full Delivery)", notas_extra: str = "") -> tuple[str, str, str]:
    num_factura, factura_html = crear_factura_html(cliente, proyecto, monto, tipo_cobro, incluir_contrato=True, notas_extra=notas_extra)
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", (cliente or "cliente").lower()).strip("_") or "cliente"
    carpeta = os.path.join(ROOT_DIR, "entregas_clientes", f"{datetime.now().strftime('%Y%m%d')}_{slug}")
    os.makedirs(carpeta, exist_ok=True)
    ruta_factura = os.path.join(carpeta, f"FACTURA_{num_factura}.html")
    with open(ruta_factura, "w", encoding="utf-8") as f:
        f.write(factura_html)
    log_evento(f"Factura archivada: {os.path.basename(ruta_factura)} (${monto} USD)")
    return num_factura, ruta_factura, factura_html

def empaquetar_producto_whop(ruta: str, nombre: str) -> dict:
    cfg = cargar_config()
    ruta_limpia = (ruta or "").strip() or os.path.join(ROOT_DIR, "modulo_b_ejecutor", "borrador_cliente.py")
    if not os.path.isabs(ruta_limpia):
        ruta_limpia = os.path.join(ROOT_DIR, ruta_limpia)
    if not os.path.isfile(ruta_limpia):
        return {"error": f"No existe el archivo: {ruta_limpia}"}

    nombre = (nombre or "").strip() or "ZeroTouch Automation Tool"
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", nombre.lower()).strip("_") or "producto_whop"

    with open(ruta_limpia, "r", encoding="utf-8") as f:
        codigo_raw = f.read()

    prompt = (
        f"Eres un creador de herramientas de automatizacion en Python que vende productos digitales en Whop.\n"
        f"Convierte este script en un producto comercial reutilizable llamado '{nombre}'.\n"
        "Responde UNICAMENTE usando estas 6 etiquetas XML exactas:\n\n"
        "<CODIGO_LIMPIO>\n"
        "Codigo en Python 3.12 refactorizado, sin URLs ni datos privados hardcodeados (lee config.json o pide inputs), con mensajes claros en ingles y manejo de errores.\n"
        "</CODIGO_LIMPIO>\n\n"
        "<CONFIG_EJEMPLO>\n"
        "Archivo JSON valido de configuracion de ejemplo para el comprador.\n"
        "</CONFIG_EJEMPLO>\n\n"
        "<README>\n"
        "Archivo README.md profesional en ingles con: que hace, requisitos, instalacion (incluyendo que en Windows basta doble clic en RUN_WINDOWS.bat) y uso paso a paso.\n"
        "</README>\n\n"
        "<WHOP_COPY>\n"
        "Copy de ventas persuasivo en ingles para Whop: Titulo, subtitulo, 5 beneficios clave, publico ideal, FAQ corto (3 preguntas) y precio sugerido en USD.\n"
        "</WHOP_COPY>\n\n"
        "<POST_PROMO>\n"
        "Post natural en ingles para promocionar la herramienta en Reddit (r/SideProject, r/Python) o X sin sonar a spam.\n"
        "</POST_PROMO>\n\n"
        "<GUION_SHORT>\n"
        "Guion dinamico de 30 segundos en ingles (gancho + demo + CTA) para TikTok/Reels/Shorts vendiendo esta herramienta.\n"
        "</GUION_SHORT>\n\n"
        f"SCRIPT ORIGINAL:\n{codigo_raw}"
    )

    texto = generar_texto_ia(prompt, temperatura=0.25, json_mode=False, timeout=36)
    if not texto:
        return {"error": "La IA no respondio en este intento."}

    cod, valido = validar_y_reparar_python(extraer_etiqueta(texto, "CODIGO_LIMPIO"), descripcion=nombre)
    cfg_ej = limpiar_bloque_codigo(extraer_etiqueta(texto, "CONFIG_EJEMPLO")) or '{\n  "target_url": "https://example.com",\n  "output_file": "output.csv"\n}'
    readme = limpiar_bloque_codigo(extraer_etiqueta(texto, "README"))
    whop = extraer_etiqueta(texto, "WHOP_COPY")
    promo = extraer_etiqueta(texto, "POST_PROMO")
    guion = extraer_etiqueta(texto, "GUION_SHORT")
    todos_pip, _ = analizar_dependencias(cod)
    reqs = "\n".join(todos_pip) if todos_pip else "# Standard library only"

    launcher_bat = (
        "@echo off\r\n"
        "echo Installing required packages...\r\n"
        "python -m pip install -r requirements.txt\r\n"
        "echo Running tool...\r\n"
        "python main.py\r\n"
        "pause\r\n"
    )
    licencia = (
        f"SINGLE-USER COMMERCIAL LICENSE — {nombre}\n"
        f"Copyright (c) {datetime.now().year} {cfg.get('nombre_marca', 'ZeroTouch Dev')}\n\n"
        "This purchase grants you a non-exclusive license to use and modify this software for personal or internal business projects.\n"
        "Redistribution, resale, or public re-uploading of the source code is strictly prohibited.\n"
    )

    carpeta_salida = os.path.join(ROOT_DIR, "modulo_c_whop", "producto_listo")
    os.makedirs(carpeta_salida, exist_ok=True)

    archivos = {
        "main.py": cod,
        "config_ejemplo.json": cfg_ej,
        "requirements.txt": reqs + "\n",
        "README.md": readme,
        "LICENSE.txt": licencia,
        "RUN_WINDOWS.bat": launcher_bat,
        "WHOP_LISTING.md": whop,
        "POST_PROMO_GRATIS.txt": promo,
        "GUION_VIDEO_30S.txt": guion,
    }
    for fname, content in archivos.items():
        with open(os.path.join(carpeta_salida, fname), "w", encoding="utf-8") as f:
            f.write(content)

    f_zip = os.path.join(carpeta_salida, f"{slug}_whop_apex.zip")
    with zipfile.ZipFile(f_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in ("main.py", "config_ejemplo.json", "requirements.txt", "README.md", "LICENSE.txt", "RUN_WINDOWS.bat"):
            zf.write(os.path.join(carpeta_salida, fname), arcname=fname)

    log_evento(f"Producto Whop empaquetado: {os.path.basename(f_zip)}")
    return {
        "zip_path": f_zip,
        "carpeta": carpeta_salida,
        "ast_valido": valido,
        "whop_copy": whop,
        "promo": promo,
        "guion": guion,
    }

def empaquetar_whop() -> None:
    print(f"\n{C.BOLD}{C.MAGENTA}--- FABRICA APEX DE PRODUCTOS DIGITALES PARA WHOP ---{C.RESET}")
    ruta_default = os.path.join(ROOT_DIR, "modulo_b_ejecutor", "borrador_cliente.py")
    ruta = input(f"Ruta del script [Enter para {ruta_default}]: ").strip() or ruta_default
    nombre = input("Nombre comercial (ej. AutoLead Scraper Pro): ").strip() or "ZeroTouch Automation Tool"
    print(f"{C.CYAN}[*] Refactorizando codigo, validando AST y armando paquete comercial...{C.RESET}", flush=True)
    res = empaquetar_producto_whop(ruta, nombre)
    if res.get("error"):
        print(f"{C.RED}[!] {res['error']}{C.RESET}")
        return
    print("\n" + "=" * 70)
    print(f"{C.GREEN}PRODUCTO WHOP APEX ({'AST OK' if res['ast_valido'] else 'REVISAR'}) EN: {res['carpeta']}{C.RESET}")
    print(f"  -> ZIP comprador     : {os.path.basename(res['zip_path'])} (incluye RUN_WINDOWS.bat + LICENSE)")
    print("  -> Copy de Whop      : WHOP_LISTING.md")
    print("  -> Trafico gratis    : POST_PROMO_GRATIS.txt")
    print("  -> Video TikTok/Reel : GUION_VIDEO_30S.txt")
    print("=" * 70 + "\n")

def generar_entrega_y_factura() -> None:
    print(f"\n{C.BOLD}{C.GREEN}--- GENERADOR DE ENTREGA + FACTURA Y MICRO-CONTRATO HTML/PDF ---{C.RESET}")
    cliente = input("Nombre o usuario del cliente (ej. u/john_shop): ").strip() or "Client"
    proyecto = input("Concepto del proyecto (ej. Shopify Price Scraper Python): ").strip() or "Custom Python Automation Script"
    monto = input("Monto total en USD (ej. 120): ").strip() or "100"
    tipo = input("Tipo [1=50% Adelanto | 2=Pago Final 100% | 3=Retainer Mensual]: ").strip()
    tipo_txt = {"1": "50% Deposit (Project Start)", "3": "Monthly Retainer / Maintenance"}.get(tipo, "Final Payment (Full Delivery)")
    ruta_default = os.path.join(ROOT_DIR, "modulo_b_ejecutor", "borrador_cliente.py")
    ruta_script = input(f"Script a empacar [Enter para {ruta_default} o escribe NO para solo factura]: ").strip() or ruta_default

    _, ruta_factura, _ = guardar_factura_local(cliente, proyecto, monto, tipo_txt)
    carpeta = os.path.dirname(ruta_factura)
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", cliente.lower()).strip("_") or "cliente"

    if ruta_script.upper() != "NO" and os.path.isfile(ruta_script):
        with open(ruta_script, "r", encoding="utf-8") as f:
            cod = f.read()
        todos_pip, _ = analizar_dependencias(cod)
        ruta_req = os.path.join(carpeta, "requirements.txt")
        with open(ruta_req, "w", encoding="utf-8") as f:
            f.write(("\n".join(todos_pip) if todos_pip else "# Standard library only") + "\n")
        ruta_zip = os.path.join(carpeta, f"ENTREGA_{slug}.zip")
        with zipfile.ZipFile(ruta_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(ruta_script, arcname=os.path.basename(ruta_script))
            zf.write(ruta_req, arcname="requirements.txt")
        print(f"{C.GREEN}[+] ZIP de entrega listo : {ruta_zip}{C.RESET}")

    print(f"{C.GREEN}[+] Factura HTML creada  : {ruta_factura}{C.RESET}")
    if os.name == "nt":
        try:
            os.startfile(ruta_factura)
        except Exception:
            pass

def main() -> None:
    print(f"\n{C.BOLD}{C.MAGENTA}=== MODULO C: WHOP APEX & FACTURACION v12.0 ==={C.RESET}")
    print(" [1] Empaquetar script como Producto Digital para Whop (.ZIP + Launcher + Copy + Short)")
    print(" [2] Generar Kit de Entrega (.ZIP) + Factura & Micro-Contrato HTML/PDF")
    op = input("\nElige una opcion [1-2]: ").strip()
    if op == "2":
        generar_entrega_y_factura()
    else:
        empaquetar_whop()

if __name__ == "__main__":
    main()