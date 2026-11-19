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

def obtener_modelos_activos(headers: dict) -> list:
    prioritarios = ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemma-3-27b-it"]
    try:
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/models", headers=headers, timeout=10)
        if r.status_code == 200:
            candidatos = []
            ignorar = ("2.0", "2.5", "1.5", "embedding", "aqa", "imagen", "veo", "tts", "audio", "robotics", "computer-use", "deep-research")
            for m in r.json().get("models", []):
                nombre = m.get("name", "").replace("models/", "")
                metodos = m.get("supportedGenerationMethods", [])
                if "generateContent" not in metodos or any(bad in nombre.lower() for bad in ignorar):
                    continue
                if ("gemini" in nombre.lower() or "gemma" in nombre.lower()) and "image" not in nombre.lower():
                    candidatos.append(nombre)
            candidatos.sort(reverse=True)
            ordenados = [m for m in prioritarios if m in candidatos]
            for m in candidatos:
                if m not in ordenados:
                    ordenados.append(m)
            if ordenados:
                return ordenados
    except Exception:
        pass
    return prioritarios

def extraer_etiqueta(texto: str, tag: str) -> str:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", texto, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""

def consultar_copiloto(descripcion_oferta: str) -> dict | None:
    if not GEMINI_KEY:
        print("[!] Falta GEMINI_API_KEY_FREE en el archivo .env")
        return None

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_KEY
    }
    modelos = obtener_modelos_activos(headers)
    prompt = (
        "Eres un desarrollador senior de Python y automatización ayudando a cerrar un cliente freelance.\n"
        "Analiza esta oferta y responde ÚNICAMENTE usando exactamente estas 4 etiquetas XML (sin texto fuera de ellas):\n\n"
        "<DIAGNOSTICO>\n"
        "Qué pide exactamente el cliente, qué stack usar y qué detalle técnico mencionar para demostrar dominio (2 líneas en español).\n"
        "</DIAGNOSTICO>\n\n"
        "<PRECIO>\n"
        "Rango justo en USD y tiempo estimado de entrega.\n"
        "</PRECIO>\n\n"
        "<PITCH>\n"
        "Mensaje corto de respuesta en inglés natural (45-65 palabras), directo al grano, demostrando diagnóstico técnico inmediato, sin saludos robóticos ni clichés de IA.\n"
        "</PITCH>\n\n"
        "<CODIGO>\n"
        "Script completo y funcional en Python 3.12 (usando requests, bs4, csv o json según corresponda) listo como base para resolver el pedido, con comentarios claros y manejo de errores.\n"
        "</CODIGO>\n\n"
        f"OFERTA DEL CLIENTE:\n{descripcion_oferta}"
    )

    for modelo in modelos:
        print(f"[*] Probando con {modelo}...", flush=True)
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3}
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=25)
            if r.status_code == 200:
                texto = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                pitch = extraer_etiqueta(texto, "PITCH")
                codigo = extraer_etiqueta(texto, "CODIGO")
                if pitch or codigo:
                    codigo = re.sub(r"^```(?:python)?\s*|\s*```$", "", codigo)
                    print(f"[+] ¡Generado con {modelo}!", flush=True)
                    return {
                        "diagnostico_es": extraer_etiqueta(texto, "DIAGNOSTICO"),
                        "precio_sugerido": extraer_etiqueta(texto, "PRECIO"),
                        "pitch_en": pitch,
                        "codigo_python": codigo
                    }
            else:
                print(f"    [~] {modelo} respondió HTTP {r.status_code}, saltando...", flush=True)
        except Exception as e:
            print(f"    [~] {modelo} lento/error, saltando...", flush=True)

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
        print("[!] Ningún modelo pudo responder en este momento. Intenta de nuevo en unos segundos.")
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

