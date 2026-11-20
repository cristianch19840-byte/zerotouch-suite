import os
import re
import sys
from datetime import datetime

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core_ia import SESSION, generar_texto_ia, extraer_etiqueta, limpiar_bloque_codigo, copiar_al_portapapeles

def descargar_post_reddit(url: str) -> str | None:
    limpia = url.split("?")[0].rstrip("/")
    json_url = f"{limpia}.json?raw_json=1"
    headers = {"User-Agent": "python:zerotouch-copiloto:v7.0 (by /u/zerotouch_freelance)"}
    try:
        r = SESSION.get(json_url, headers=headers, timeout=12)
        if r.status_code == 200:
            data = r.json()[0]["data"]["children"][0]["data"]
            titulo = data.get("title", "")
            cuerpo = data.get("selftext", "")
            sub = data.get("subreddit_name_prefixed", "Reddit")
            return f"Fuente: {sub}\nTitulo: {titulo}\n\n{cuerpo}".strip()
    except Exception as e:
        print(f"[!] No pude leer el link automatico ({e}).")
    return None

def crear_slug(texto: str) -> str:
    palabras = re.sub(r"[^a-zA-Z0-9\s]", "", texto.lower()).split()[:5]
    return "_".join(palabras) or "proyecto"

def main() -> None:
    print("\n=== MODULO B: COPILOTO DE CIERRE Y CODIGO ZERO-TOUCH v7.0 ===")
    print("Opcion 1: Pega directamente un LINK de Reddit y dale Enter.")
    print("Opcion 2: Pega el texto de la oferta, escribe FIN en una linea nueva y dale Enter.\n")

    primera = input("> ").strip()
    if not primera:
        print("[!] No ingresaste nada.")
        return

    if primera.startswith("http") and "reddit.com" in primera:
        print("[*] Descargando post directamente desde Reddit...", flush=True)
        oferta = descargar_post_reddit(primera)
        if not oferta:
            print("[!] Copia y pega el texto manual del post mejor.")
            return
        print(f"[+] Post cargado ({len(oferta)} caracteres).\n")
    else:
        lineas = [primera]
        while True:
            try:
                linea = input()
            except EOFError:
                break
            if linea.strip().upper() == "FIN":
                break
            lineas.append(linea)
        oferta = "\n".join(lineas).strip()

    prompt = (
        "Eres un desarrollador senior de Python y automatizacion ayudando a cerrar un cliente freelance.\n"
        "Analiza esta oferta y responde UNICAMENTE usando estas 5 etiquetas XML (sin texto fuera):\n\n"
        "<DIAGNOSTICO>\n"
        "Que pide exactamente el cliente, que libreria usar y que detalle tecnico mencionar para demostrar dominio (2 lineas en espanol).\n"
        "</DIAGNOSTICO>\n\n"
        "<PRECIO>\n"
        "Rango justo en USD y tiempo estimado de entrega.\n"
        "</PRECIO>\n\n"
        "<PITCH>\n"
        "Mensaje corto de respuesta inicial en ingles natural (45-65 palabras), directo al grano, demostrando diagnostico tecnico inmediato, sin saludos roboticos ni cliches de IA.\n"
        "</PITCH>\n\n"
        "<MENSAJE_COBRO>\n"
        "Mensaje corto y profesional en ingles (30-45 palabras) para enviar despues de mostrar una captura de avance y pedir el 50% de adelanto o pago final por USDT/PayPal/Airtm antes de entregar el script completo.\n"
        "</MENSAJE_COBRO>\n\n"
        "<CODIGO>\n"
        "Script completo, modular y limpio en Python 3.12 listo como base funcional para resolver el pedido, con manejo de errores y exportacion ordenada.\n"
        "</CODIGO>\n\n"
        f"OFERTA DEL CLIENTE:\n{oferta}"
    )

    print("[*] Generando pitch, mensaje de cobro y script base...", flush=True)
    texto = generar_texto_ia(prompt, temperatura=0.25, json_mode=False, timeout=25)
    if not texto:
        print("[!] No se pudo generar respuesta en este momento.")
        return

    diag = extraer_etiqueta(texto, "DIAGNOSTICO")
    precio = extraer_etiqueta(texto, "PRECIO")
    pitch = extraer_etiqueta(texto, "PITCH")
    cobro = extraer_etiqueta(texto, "MENSAJE_COBRO")
    codigo = limpiar_bloque_codigo(extraer_etiqueta(texto, "CODIGO"))

    copiado = copiar_al_portapapeles(pitch)

    print("\n" + "=" * 64)
    print(f"DIAGNOSTICO TECNICO:\n{diag}\n")
    print(f"PRECIO Y TIEMPO SUGERIDO:\n{precio}\n")
    print("-" * 64)
    print(f"PITCH INICIAL (EN INGLES):\n\n{pitch}\n")
    if copiado:
        print("[+] Pitch copiado automaticamente al portapapeles (solo haz Ctrl+V)!\n")
    print("-" * 64)
    print(f"MENSAJE PARA PEDIR PAGO AL MOSTRAR MUESTRA:\n\n{cobro}")
    print("=" * 64)

    if codigo:
        ruta_borrador = os.path.join(ROOT_DIR, "modulo_b_ejecutor", "borrador_cliente.py")
        with open(ruta_borrador, "w", encoding="utf-8") as f:
            f.write(codigo)

        carpeta_proj = os.path.join(
            ROOT_DIR,
            "proyectos",
            f"{datetime.now().strftime('%Y%m%d_%H%M')}_{crear_slug(oferta.splitlines()[0])}",
        )
        os.makedirs(carpeta_proj, exist_ok=True)
        with open(os.path.join(carpeta_proj, "script.py"), "w", encoding="utf-8") as f:
            f.write(codigo)
        with open(os.path.join(carpeta_proj, "propuesta.txt"), "w", encoding="utf-8") as f:
            f.write(f"DIAGNOSTICO:\n{diag}\n\nPRECIO:\n{precio}\n\nPITCH:\n{pitch}\n\nCOBRO:\n{cobro}\n")

        print(f"\nScript base listo en : {ruta_borrador}")
        print(f"Respaldo guardado en : {carpeta_proj}\n")

if __name__ == "__main__":
    main()