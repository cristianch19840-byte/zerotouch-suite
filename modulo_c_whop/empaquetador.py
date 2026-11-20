import os
import re
import sys
import zipfile

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core_ia import generar_texto_ia, extraer_etiqueta, limpiar_bloque_codigo

def main() -> None:
    print("\n=== MODULO C: EMPAQUETADOR 1-CLICK PARA WHOP v7.0 ===")
    ruta_default = os.path.join(ROOT_DIR, "modulo_b_ejecutor", "borrador_cliente.py")
    ruta = input(f"Ruta del script a empaquetar [Enter para {ruta_default}]: ").strip() or ruta_default

    if not os.path.exists(ruta):
        print(f"[!] No encontre el archivo: {ruta}")
        return

    nombre = input("Nombre comercial para tu herramienta (ej. AutoLead Scraper Pro): ").strip() or "ZeroTouch Automation Tool"
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", nombre.lower()).strip("_") or "producto_whop"

    with open(ruta, "r", encoding="utf-8") as f:
        codigo_raw = f.read()

    prompt = (
        f"Eres un creador de herramientas de automatizacion en Python que vende en Whop.\n"
        f"Convierte este script en un producto comercial reutilizable llamado '{nombre}'.\n"
        "Responde UNICAMENTE usando estas 4 etiquetas XML exactas:\n\n"
        "<CODIGO_LIMPIO>\n"
        "Codigo en Python 3.12 refactorizado, sin URLs ni datos privados hardcodeados (pide inputs o lee config.json), con mensajes claros en consola en ingles y manejo de errores.\n"
        "</CODIGO_LIMPIO>\n\n"
        "<REQUIREMENTS>\n"
        "Lista limpia de paquetes pip necesarios (uno por linea, solo librerias externas). Si no usa externas, escribe: # No external packages required\n"
        "</REQUIREMENTS>\n\n"
        "<README>\n"
        "Archivo README.md profesional en ingles con: que hace la herramienta, requisitos, instalacion (pip install -r requirements.txt) y uso paso a paso.\n"
        "</README>\n\n"
        "<WHOP_COPY>\n"
        "Copy de ventas persuasivo en ingles para Whop: Titulo llamativo, subtitulo, 5 beneficios clave, publico ideal y precio sugerido en USD.\n"
        "</WHOP_COPY>\n\n"
        f"SCRIPT ORIGINAL:\n{codigo_raw}"
    )

    print("[*] Empaquetando producto y generando .zip comercial...", flush=True)
    texto = generar_texto_ia(prompt, temperatura=0.25, json_mode=False, timeout=30)
    if not texto:
        print("[!] No se pudo empaquetar en este intento.")
        return

    cod = limpiar_bloque_codigo(extraer_etiqueta(texto, "CODIGO_LIMPIO"))
    reqs = limpiar_bloque_codigo(extraer_etiqueta(texto, "REQUIREMENTS")) or "requests\nbeautifulsoup4"
    readme = limpiar_bloque_codigo(extraer_etiqueta(texto, "README"))
    whop = extraer_etiqueta(texto, "WHOP_COPY")

    carpeta_salida = os.path.join(ROOT_DIR, "modulo_c_whop", "producto_listo")
    os.makedirs(carpeta_salida, exist_ok=True)

    f_main = os.path.join(carpeta_salida, "main.py")
    f_req = os.path.join(carpeta_salida, "requirements.txt")
    f_readme = os.path.join(carpeta_salida, "README.md")
    f_whop = os.path.join(carpeta_salida, "WHOP_LISTING.md")
    f_zip = os.path.join(carpeta_salida, f"{slug}.zip")

    with open(f_main, "w", encoding="utf-8") as f:
        f.write(cod)
    with open(f_req, "w", encoding="utf-8") as f:
        f.write(reqs + "\n")
    with open(f_readme, "w", encoding="utf-8") as f:
        f.write(readme)
    with open(f_whop, "w", encoding="utf-8") as f:
        f.write(whop)

    with zipfile.ZipFile(f_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(f_main, arcname="main.py")
        zf.write(f_req, arcname="requirements.txt")
        zf.write(f_readme, arcname="README.md")

    print("\n" + "=" * 62)
    print(f"PAQUETE WHOP GENERADO EN: {carpeta_salida}")
    print(f"  -> ZIP listo para subir : {slug}.zip")
    print("  -> Texto de ventas      : WHOP_LISTING.md")
    print("=" * 62 + "\n")

if __name__ == "__main__":
    main()