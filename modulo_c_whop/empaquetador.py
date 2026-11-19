import os
import re
import sys
import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

if os.path.exists(".env"):
    with open(".env", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

GEMINI_KEY = os.getenv("GEMINI_API_KEY_FREE")

def extraer_etiqueta(texto: str, tag: str) -> str:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", texto, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""

def empaquetar_para_whop(codigo_fuente: str, nombre_producto: str) -> dict | None:
    if not GEMINI_KEY:
        print("[!] Falta GEMINI_API_KEY_FREE en .env")
        return None

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_KEY
    }
    modelos = ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemma-3-27b-it"]
    prompt = (
        f"Eres un creador de productos SaaS y herramientas de automatización en Python que vende en Whop.\n"
        f"Toma este script base y conviértelo en un producto comercial reutilizable llamado '{nombre_producto}'.\n"
        "Responde ÚNICAMENTE usando estas 3 etiquetas XML exactas:\n\n"
        "<CODIGO_LIMPIO>\n"
        "Código en Python 3.12 refactorizado, sin URLs ni datos privados hardcodeados (pide inputs al usuario o lee un config.json/variables al inicio), con mensajes claros en consola en inglés y manejo de errores.\n"
        "</CODIGO_LIMPIO>\n\n"
        "<README>\n"
        "Archivo README.md profesional en inglés con: qué hace la herramienta, requisitos, instalación (`pip install ...`) y cómo ejecutarla paso a paso.\n"
        "</README>\n\n"
        "<WHOP_COPY>\n"
        "Texto de ventas persuasivo en inglés listo para pegar en Whop: Título llamativo, subtítulo, 5 beneficios clave en viñetas, público ideal y precio sugerido en USD (ej. $19 - $39).\n"
        "</WHOP_COPY>\n\n"
        f"SCRIPT ORIGINAL:\n{codigo_fuente}"
    )

    for modelo in modelos:
        print(f"[*] Empaquetando producto con {modelo}...", flush=True)
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3}
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=30)
            if r.status_code == 200:
                texto = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                cod = extraer_etiqueta(texto, "CODIGO_LIMPIO")
                readme = extraer_etiqueta(texto, "README")
                copy_whop = extraer_etiqueta(texto, "WHOP_COPY")
                if cod and copy_whop:
                    cod = re.sub(r"^```(?:python)?\s*|\s*```$", "", cod)
                    readme = re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", readme)
                    print(f"[+] ¡Producto generado con {modelo}!", flush=True)
                    return {"codigo": cod, "readme": readme, "whop": copy_whop}
            else:
                print(f"    [~] {modelo} HTTP {r.status_code}, probando siguiente...", flush=True)
        except Exception:
            print(f"    [~] {modelo} lento/error, probando siguiente...", flush=True)

    return None

def main():
    print("\n=== MÓDULO C: EMPAQUETADOR DE PRODUCTOS PARA WHOP ===")
    ruta_default = os.path.join("modulo_b_ejecutor", "borrador_cliente.py")
    ruta = input(f"Ruta del script a empaquetar [Enter para usar {ruta_default}]: ").strip() or ruta_default

    if not os.path.exists(ruta):
        print(f"[!] No encontré el archivo: {ruta}")
        return

    nombre = input("Nombre comercial para tu herramienta (ej. AutoLead Scraper Pro): ").strip() or "ZeroTouch Automation Tool"

    with open(ruta, "r", encoding="utf-8") as f:
        codigo_raw = f.read()

    res = empaquetar_para_whop(codigo_raw, nombre)
    if not res:
        print("[!] No se pudo empaquetar en este intento.")
        return

    carpeta_salida = os.path.join("modulo_c_whop", "producto_listo")
    os.makedirs(carpeta_salida, exist_ok=True)

    with open(os.path.join(carpeta_salida, "main.py"), "w", encoding="utf-8") as f:
        f.write(res["codigo"])
    with open(os.path.join(carpeta_salida, "README.md"), "w", encoding="utf-8") as f:
        f.write(res["readme"])
    with open(os.path.join(carpeta_salida, "WHOP_LISTING.md"), "w", encoding="utf-8") as f:
        f.write(res["whop"])

    print("\n" + "=" * 60)
    print(f"✅ ¡PAQUETE LISTO PARA SUBIR A WHOP EN: {carpeta_salida}\\")
    print("   1. main.py          -> Script limpio y generalizado")
    print("   2. README.md        -> Manual en inglés para el comprador")
    print("   3. WHOP_LISTING.md  -> Título, precio y copy de ventas")
    print("=" * 60 + "\n")

if __name__ == "__main__":
    main()
