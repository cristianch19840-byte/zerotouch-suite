import os
import re
import sys
import json
import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

if os.path.exists(".env"):
    with open(".env", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

GEMINI_KEY = os.getenv("GEMINI_API_KEY_FREE")

def consultar_copiloto(descripcion_oferta: str) -> dict | None:
    if not GEMINI_KEY:
        print("[!] Falta GEMINI_API_KEY_FREE en el archivo .env")
        return None

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_KEY
    }
    modelos = ["gemini-3.5-flash", "gemma-3-27b-it"]
    prompt = (
        "Eres un desarrollador senior de Python y automatización ayudando a cerrar un cliente freelance.\n"
        "Analiza esta oferta del cliente y responde ÚNICAMENTE con un objeto JSON válido con estas 4 claves:\n"
        "1. 'diagnostico_es': Qué pide exactamente el cliente, qué tecnología usar y qué detalle técnico mencionar para impresionarlo (2 líneas en español).\n"
        "2. 'precio_sugerido': Rango justo en USD y tiempo estimado de entrega.\n"
        "3. 'pitch_en': Mensaje de respuesta en inglés natural (45-65 palabras), directo al grano, demostrando diagnóstico técnico inmediato, sin saludos robóticos ni clichés de IA.\n"
        "4. 'codigo_python': Script completo en Python 3.12 (usando requests, bs4, csv o json según corresponda) listo como base funcional para resolver el pedido, con comentarios claros y manejo de errores.\n\n"
        f"OFERTA DEL CLIENTE:\n{descripcion_oferta}"
    )

    for modelo in modelos:
        print(f"[*] Generando propuesta y código base con {modelo}...")
        usa_json_nativo = "gemma" not in modelo.lower()
        gen_config = {"temperature": 0.3}
        if usa_json_nativo:
            gen_config["responseMimeType"] = "application/json"

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": gen_config
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=25)
            if r.status_code == 200:
                texto = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                match = re.search(r"\{.*\}", texto, re.DOTALL)
                if match:
                    return json.loads(match.group(0))
        except Exception as e:
            print(f"[!] {modelo} falló ({e}), probando respaldo...")

    return None

def main():
    print("\n=== MÓDULO B: COPILOTO DE CIERRE Y CÓDIGO ZERO-TOUCH ===")
    print("Pega la descripción de la oferta del cliente abajo.")
    print("Cuando termines de pegar, escribe FIN en una línea nueva y dale Enter:\n")

    lineas = []
    while True:
        try:
            linea = input()
        except EOFError:
            break
        if linea.strip().upper() == "FIN":
            break
        lineas.append(linea)

    oferta = "\n".join(lineas).strip()
    if not oferta:
        print("[!] No pegaste ningún texto.")
        return

    res = consultar_copiloto(oferta)
    if not res:
        print("[!] No se pudo generar respuesta en este momento.")
        return

    print("\n" + "=" * 60)
    print(f"🎯 DIAGNÓSTICO TÉCNICO:\n{res.get('diagnostico_es', '')}\n")
    print(f"💵 PRECIO Y TIEMPO SUGERIDO:\n{res.get('precio_sugerido', '')}\n")
    print("-" * 60)
    print(f"📩 PITCH LISTO PARA COPIAR Y PEGAR EN DM:\n\n{res.get('pitch_en', '')}")
    print("=" * 60)

    codigo = res.get("codigo_python", "")
    if codigo:
        ruta_salida = os.path.join("modulo_b_ejecutor", "borrador_cliente.py")
        with open(ruta_salida, "w", encoding="utf-8") as f:
            f.write(codigo)
        print(f"\n✅ Script base guardado automáticamente en: {ruta_salida}")
        print("   Ábrelo, ajusta la URL/selectores del cliente y ejecútalo.\n")

if __name__ == "__main__":
    main()
