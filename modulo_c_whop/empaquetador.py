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
    cargar_config,
    generar_texto_ia,
    extraer_etiqueta,
    limpiar_bloque_codigo,
    validar_y_reparar_python,
    detectar_paquetes_externos,
)

def empaquetar_whop() -> None:
    print(f"\n{C.BOLD}{C.MAGENTA}--- FABRICA 1-CLICK DE PRODUCTOS DIGITALES PARA WHOP ---{C.RESET}")
    ruta_default = os.path.join(ROOT_DIR, "modulo_b_ejecutor", "borrador_cliente.py")
    ruta = input(f"Ruta del script [Enter para {ruta_default}]: ").strip() or ruta_default
    if not os.path.exists(ruta):
        print(f"{C.RED}[!] No encontre el archivo: {ruta}{C.RESET}")
        return

    nombre = input("Nombre comercial de la herramienta (ej. AutoLead Scraper Pro): ").strip() or "ZeroTouch Automation Tool"
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", nombre.lower()).strip("_") or "producto_whop"

    with open(ruta, "r", encoding="utf-8") as f:
        codigo_raw = f.read()

    prompt = (
        f"Eres un creador de herramientas de automatizacion en Python que vende productos digitales en Whop.\n"
        f"Convierte este script en un producto comercial reutilizable llamado '{nombre}'.\n"
        "Responde UNICAMENTE usando estas 6 etiquetas XML exactas:\n\n"
        "<CODIGO_LIMPIO>\n"
        "Codigo en Python 3.12 refactorizado, sin URLs ni datos privados hardcodeados (lee config.json o pide inputs), con mensajes limpios en ingles y manejo de errores.\n"
        "</CODIGO_LIMPIO>\n\n"
        "<CONFIG_EJEMPLO>\n"
        "Archivo JSON valido de configuracion de ejemplo para el comprador.\n"
        "</CONFIG_EJEMPLO>\n\n"
        "<README>\n"
        "Archivo README.md profesional en ingles con: que hace, requisitos, instalacion (pip install -r requirements.txt) y uso paso a paso.\n"
        "</README>\n\n"
        "<WHOP_COPY>\n"
        "Copy de ventas persuasivo en ingles para Whop: Titulo, subtitulo, 5 beneficios clave, publico ideal y precio sugerido en USD.\n"
        "</WHOP_COPY>\n\n"
        "<POST_PROMO>\n"
        "Post natural en ingles para promocionar la herramienta en Reddit (r/SideProject, r/Python) o X sin sonar a spam.\n"
        "</POST_PROMO>\n\n"
        "<GUION_SHORT>\n"
        "Guion dinamico de 30 segundos en ingles (gancho + demo + llamado a la accion) para TikTok/Reels/Shorts vendiendo esta herramienta.\n"
        "</GUION_SHORT>\n\n"
        f"SCRIPT ORIGINAL:\n{codigo_raw}"
    )

    print(f"{C.CYAN}[*] Refactorizando codigo, validando AST y armando .zip comercial...{C.RESET}", flush=True)
    texto = generar_texto_ia(prompt, temperatura=0.25, json_mode=False, timeout=32)
    if not texto:
        print(f"{C.RED}[!] No se pudo empaquetar en este intento.{C.RESET}")
        return

    cod, valido = validar_y_reparar_python(extraer_etiqueta(texto, "CODIGO_LIMPIO"), descripcion=nombre)
    cfg_ej = limpiar_bloque_codigo(extraer_etiqueta(texto, "CONFIG_EJEMPLO")) or '{\n  "target_url": "https://example.com",\n  "output_file": "output.csv"\n}'
    readme = limpiar_bloque_codigo(extraer_etiqueta(texto, "README"))
    whop = extraer_etiqueta(texto, "WHOP_COPY")
    promo = extraer_etiqueta(texto, "POST_PROMO")
    guion = extraer_etiqueta(texto, "GUION_SHORT")
    paquetes = detectar_paquetes_externos(cod)
    reqs = "\n".join(paquetes) if paquetes else "# Standard library only"

    carpeta_salida = os.path.join(ROOT_DIR, "modulo_c_whop", "producto_listo")
    os.makedirs(carpeta_salida, exist_ok=True)

    f_main = os.path.join(carpeta_salida, "main.py")
    f_cfg = os.path.join(carpeta_salida, "config_ejemplo.json")
    f_req = os.path.join(carpeta_salida, "requirements.txt")
    f_readme = os.path.join(carpeta_salida, "README.md")
    f_whop = os.path.join(carpeta_salida, "WHOP_LISTING.md")
    f_promo = os.path.join(carpeta_salida, "POST_PROMO_GRATIS.txt")
    f_guion = os.path.join(carpeta_salida, "GUION_VIDEO_30S.txt")
    f_zip = os.path.join(carpeta_salida, f"{slug}_whop.zip")

    for ruta_f, contenido in [
        (f_main, cod),
        (f_cfg, cfg_ej),
        (f_req, reqs + "\n"),
        (f_readme, readme),
        (f_whop, whop),
        (f_promo, promo),
        (f_guion, guion),
    ]:
        with open(ruta_f, "w", encoding="utf-8") as f:
            f.write(contenido)

    with zipfile.ZipFile(f_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(f_main, arcname="main.py")
        zf.write(f_cfg, arcname="config_ejemplo.json")
        zf.write(f_req, arcname="requirements.txt")
        zf.write(f_readme, arcname="README.md")

    print("\n" + "=" * 68)
    print(f"{C.GREEN}PRODUCTO WHOP LISTO ({'AST OK' if valido else 'REVISAR'}) EN: {carpeta_salida}{C.RESET}")
    print(f"  -> ZIP comercial     : {slug}_whop.zip")
    print("  -> Copy de Whop      : WHOP_LISTING.md")
    print("  -> Trafico gratis    : POST_PROMO_GRATIS.txt")
    print("  -> Video TikTok/Reel : GUION_VIDEO_30S.txt")
    print("=" * 68 + "\n")

def generar_entrega_y_factura() -> None:
    cfg = cargar_config()
    print(f"\n{C.BOLD}{C.GREEN}--- GENERADOR DE ENTREGA PROFESIONAL + FACTURA HTML ---{C.RESET}")
    cliente = input("Nombre o usuario del cliente (ej. u/john_shop): ").strip() or "Client"
    proyecto = input("Concepto del proyecto (ej. Shopify Price Scraper Python): ").strip() or "Custom Python Automation Script"
    monto = input("Monto total en USD (ej. 120): ").strip() or "100"
    tipo = input("Tipo de cobro [1=50% Adelanto | 2=Pago Final 100%]: ").strip()
    estado_pago = "50% Deposit (Project Start)" if tipo == "1" else "Final Payment (Full Delivery)"

    ruta_default = os.path.join(ROOT_DIR, "modulo_b_ejecutor", "borrador_cliente.py")
    ruta_script = input(f"Script a empacar [Enter para {ruta_default} o escribe NO para solo factura]: ").strip() or ruta_default

    slug = re.sub(r"[^a-zA-Z0-9]+", "_", cliente.lower()).strip("_") or "cliente"
    carpeta = os.path.join(ROOT_DIR, "entregas_clientes", f"{datetime.now().strftime('%Y%m%d')}_{slug}")
    os.makedirs(carpeta, exist_ok=True)
    num_factura = f"ZT-{datetime.now().strftime('%Y%m%d-%H%M')}"
    fecha = datetime.now().strftime("%B %d, %Y")

    factura_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Invoice {num_factura}</title>
<style>
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; padding: 40px; }}
  .card {{ max-width: 720px; margin: 0 auto; background: #1e293b; border-radius: 14px; padding: 36px; border: 1px solid #334155; }}
  .top {{ display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 1px solid #334155; padding-bottom: 20px; }}
  h1 {{ margin: 0; color: #38bdf8; font-size: 24px; }}
  .badge {{ background: #0ea5e922; color: #38bdf8; padding: 6px 12px; border-radius: 999px; font-size: 13px; font-weight: 600; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin: 24px 0; }}
  .label {{ font-size: 12px; text-transform: uppercase; color: #94a3b8; letter-spacing: .06em; }}
  .val {{ font-size: 16px; margin-top: 4px; font-weight: 500; }}
  table {{ width: 100%; border-collapse: collapse; margin: 24px 0; }}
  th, td {{ text-align: left; padding: 14px; border-bottom: 1px solid #334155; }}
  th {{ color: #94a3b8; font-size: 13px; text-transform: uppercase; }}
  .total {{ font-size: 22px; color: #4ade80; font-weight: 700; text-align: right; }}
  .paybox {{ background: #0f172a; border: 1px solid #334155; border-radius: 10px; padding: 18px; margin-top: 24px; }}
  .foot {{ margin-top: 24px; font-size: 12px; color: #64748b; text-align: center; }}
  @media print {{ body {{ background: #fff; color: #0f172a; padding: 0; }} .card {{ background: #fff; border: 1px solid #cbd5e1; }} .paybox {{ background: #f8fafc; }} }}
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
      <div><div class="label">Milestone / Status</div><div class="val">{html.escape(estado_pago)}</div></div>
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
    <div class="foot">Thank you for your business! Source code & documentation delivered immediately upon payment confirmation.</div>
  </div>
</body>
</html>"""

    ruta_factura = os.path.join(carpeta, f"FACTURA_{num_factura}.html")
    with open(ruta_factura, "w", encoding="utf-8") as f:
        f.write(factura_html)

    if ruta_script.upper() != "NO" and os.path.exists(ruta_script):
        with open(ruta_script, "r", encoding="utf-8") as f:
            cod = f.read()
        paqs = detectar_paquetes_externos(cod)
        ruta_req = os.path.join(carpeta, "requirements.txt")
        with open(ruta_req, "w", encoding="utf-8") as f:
            f.write(("\n".join(paqs) if paqs else "# Standard library only") + "\n")
        ruta_zip = os.path.join(carpeta, f"ENTREGA_{slug}.zip")
        with zipfile.ZipFile(ruta_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(ruta_script, arcname=os.path.basename(ruta_script))
            zf.write(ruta_req, arcname="requirements.txt")
        print(f"{C.GREEN}[+] ZIP de entrega listo : {ruta_zip}{C.RESET}")

    print(f"{C.GREEN}[+] Factura HTML creada  : {ruta_factura}{C.RESET}")
    print(f"{C.DIM}    (Abriendo en navegador: presiona Ctrl+P -> Guardar como PDF para enviarla al cliente){C.RESET}\n")
    if os.name == "nt":
        try:
            os.startfile(ruta_factura)
        except Exception:
            pass

def main() -> None:
    print(f"\n{C.BOLD}{C.MAGENTA}=== MODULO C: WHOP & ENTREGABLES PROFESIONALES v9.0 ==={C.RESET}")
    print(" [1] Empaquetar script como Producto Digital para Whop (.ZIP + Copy + Guion Short)")
    print(" [2] Generar Kit de Entrega (.ZIP) + Factura HTML/PDF para cobrar a un Cliente")
    op = input("\nElige una opcion [1-2]: ").strip()
    if op == "2":
        generar_entrega_y_factura()
    else:
        empaquetar_whop()

if __name__ == "__main__":
    main()