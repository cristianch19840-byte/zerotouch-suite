import os
import re
import sys
from datetime import datetime
from urllib.parse import quote

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core_ia import (
    C,
    SESSION,
    cargar_config,
    preparar_db,
    verificar_confianza_reddit,
    generar_texto_ia,
    extraer_etiqueta,
    copiar_al_portapapeles,
    validar_y_reparar_python,
    detectar_paquetes_externos,
)

def descargar_post_reddit(url: str) -> tuple[str | None, str, str]:
    limpia = url.split("?")[0].rstrip("/")
    json_url = f"{limpia}.json?raw_json=1"
    headers = {"User-Agent": "python:zerotouch-copiloto:v9.0 (by /u/zerotouch_freelance)"}
    try:
        r = SESSION.get(json_url, headers=headers, timeout=12)
        if r.status_code == 200:
            data = r.json()[0]["data"]["children"][0]["data"]
            titulo = data.get("title", "")
            cuerpo = data.get("selftext", "")
            sub = data.get("subreddit_name_prefixed", "Reddit")
            autor = data.get("author", "")
            return f"Fuente: {sub}\nAutor: u/{autor}\nTitulo: {titulo}\n\n{cuerpo}".strip(), autor, titulo
    except Exception as e:
        print(f"{C.YELLOW}[!] No pude leer el link automatico ({e}).{C.RESET}")
    return None, "", ""

def cargar_desde_crm(lead_id: int) -> tuple[str | None, str, str]:
    conn = preparar_db()
    try:
        row = conn.execute("SELECT fuente, autor, titulo, presupuesto, link FROM leads WHERE id = ?", (lead_id,)).fetchone()
        if not row:
            return None, "", ""
        fuente, autor, titulo, pres, link = row
        if link and "reddit.com" in link:
            oferta, a_red, t_red = descargar_post_reddit(link)
            if oferta:
                return oferta, a_red or autor, t_red or titulo
        return f"Fuente: {fuente}\nPresupuesto: {pres}\nTitulo: {titulo}\nLink: {link}", autor, titulo
    finally:
        conn.close()

def crear_slug(texto: str) -> str:
    palabras = re.sub(r"[^a-zA-Z0-9\s]", "", texto.lower()).split()[:5]
    return "_".join(palabras) or "proyecto"

def main() -> None:
    cfg = cargar_config()
    print(f"\n{C.BOLD}{C.CYAN}=== MODULO B: COPILOTO AUTO-REPARABLE v9.0 ==={C.RESET}")
    print("Opcion 1: Pega un LINK de Reddit y dale Enter.")
    print("Opcion 2: Escribe #<ID> de tu CRM (ej. #4) y dale Enter.")
    print("Opcion 3: Pega el texto de la oferta, escribe FIN en linea nueva y dale Enter.\n")

    primera = input(f"{C.GREEN}> {C.RESET}").strip()
    if not primera:
        print("[!] No ingresaste nada.")
        return

    autor_reddit = ""
    titulo_reddit = ""
    if primera.startswith("#") and primera[1:].isdigit():
        print(f"{C.DIM}[*] Cargando lead {primera} desde tu CRM...{C.RESET}", flush=True)
        oferta, autor_reddit, titulo_reddit = cargar_desde_crm(int(primera[1:]))
        if not oferta:
            print(f"{C.RED}[!] No existe el lead {primera} en tu CRM.{C.RESET}")
            return
    elif primera.startswith("http") and "reddit.com" in primera:
        print(f"{C.DIM}[*] Descargando post directo desde Reddit...{C.RESET}", flush=True)
        oferta, autor_reddit, titulo_reddit = descargar_post_reddit(primera)
        if not oferta:
            print("[!] Pega el texto manual del post mejor.")
            return
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

    if autor_reddit:
        confianza = verificar_confianza_reddit(autor_reddit)
        print(f"{C.MAGENTA}[*] Analisis Anti-Estafa de u/{autor_reddit}: {confianza}{C.RESET}\n")

    prompt = (
        "Eres un desarrollador senior de Python y automatizacion ayudando a cerrar un cliente freelance.\n"
        f"Metodos de pago disponibles del dev: {cfg.get('metodos_pago')}\n"
        f"GitHub del dev: {cfg.get('github_url')}\n"
        "Analiza esta oferta y responde UNICAMENTE usando estas 7 etiquetas XML (sin texto fuera):\n\n"
        "<DIAGNOSTICO>\n"
        "Que pide el cliente, arquitectura exacta y el detalle tecnico clave para demostrar dominio (2-3 lineas en espanol).\n"
        "</DIAGNOSTICO>\n\n"
        "<PRECIOS>\n"
        "3 opciones en USD en 3 lineas: Basico (script rapido), Estandar (script robusto + CSV/JSON), Premium (automatizacion completa + soporte).\n"
        "</PRECIOS>\n\n"
        "<PITCH>\n"
        "Mensaje inicial en ingles natural (45-65 palabras), directo al grano, demostrando diagnostico tecnico inmediato, sin sonar a IA.\n"
        "</PITCH>\n\n"
        "<PREGUNTAS_CIERRE>\n"
        "2 preguntas tecnicas cortas en ingles para hacerle al cliente si responde, que te permitan cerrar alcance y precio rapido.\n"
        "</PREGUNTAS_CIERRE>\n\n"
        "<FOLLOWUP>\n"
        "Mensaje corto de seguimiento en ingles (25-35 palabras) para enviar 24h despues si te dejan en visto.\n"
        "</FOLLOWUP>\n\n"
        "<MENSAJE_COBRO>\n"
        f"Mensaje profesional en ingles (35-50 palabras) para enviar con captura de avance pidiendo el 50% o pago final usando {cfg.get('metodos_pago')} antes de entregar el script completo.\n"
        "</MENSAJE_COBRO>\n\n"
        "<CODIGO>\n"
        "Script completo, modular y limpio en Python 3.12 listo como base funcional para resolver el pedido, con manejo de errores, logging claro y exportacion ordenada.\n"
        "</CODIGO>\n\n"
        f"OFERTA DEL CLIENTE:\n{oferta}"
    )

    print(f"{C.CYAN}[*] Generando estrategia, pitch, preguntas, cobro y codigo verificado...{C.RESET}", flush=True)
    texto = generar_texto_ia(prompt, temperatura=0.25, json_mode=False, timeout=30)
    if not texto:
        print(f"{C.RED}[!] No se pudo generar respuesta en este momento.{C.RESET}")
        return

    diag = extraer_etiqueta(texto, "DIAGNOSTICO")
    precios = extraer_etiqueta(texto, "PRECIOS")
    pitch = extraer_etiqueta(texto, "PITCH")
    preguntas = extraer_etiqueta(texto, "PREGUNTAS_CIERRE")
    followup = extraer_etiqueta(texto, "FOLLOWUP")
    cobro = extraer_etiqueta(texto, "MENSAJE_COBRO")
    codigo_raw = extraer_etiqueta(texto, "CODIGO")

    codigo, valido = validar_y_reparar_python(codigo_raw, descripcion=diag)
    paquetes = detectar_paquetes_externos(codigo) if codigo else []
    copiado = copiar_al_portapapeles(pitch)

    print("\n" + "=" * 70)
    print(f"{C.BOLD}DIAGNOSTICO TECNICO:{C.RESET}\n{diag}\n")
    print(f"{C.BOLD}{C.GREEN}ESCALERA DE PRECIOS:{C.RESET}\n{precios}\n")
    print("-" * 70)
    print(f"{C.BOLD}{C.CYAN}PITCH INICIAL (EN INGLES):{C.RESET}\n\n{pitch}\n")
    if copiado:
        print(f"{C.GREEN}[+] Pitch copiado automaticamente al portapapeles (haz Ctrl+V)!{C.RESET}\n")
    if autor_reddit and autor_reddit.lower() != "[deleted]":
        dm = f"https://www.reddit.com/message/compose/?to={quote(autor_reddit)}&subject={quote('Re: ' + titulo_reddit[:65])}&message={quote(pitch[:380])}"
        print(f"{C.MAGENTA}DM DIRECTO PRE-LLENADO:\n{dm}{C.RESET}\n")
    print("-" * 70)
    print(f"{C.BOLD}PREGUNTAS DE CIERRE (cuando responda):{C.RESET}\n{preguntas}\n")
    print(f"{C.BOLD}SEGUIMIENTO 24H:{C.RESET}\n{followup}\n")
    print(f"{C.BOLD}MENSAJE DE COBRO:{C.RESET}\n{cobro}")
    print("=" * 70)

    if codigo:
        ruta_borrador = os.path.join(ROOT_DIR, "modulo_b_ejecutor", "borrador_cliente.py")
        with open(ruta_borrador, "w", encoding="utf-8") as f:
            f.write(codigo)

        carpeta_proj = os.path.join(
            ROOT_DIR,
            "proyectos",
            f"{datetime.now().strftime('%Y%m%d_%H%M')}_{crear_slug(titulo_reddit or oferta.splitlines()[0])}",
        )
        os.makedirs(carpeta_proj, exist_ok=True)
        with open(os.path.join(carpeta_proj, "script.py"), "w", encoding="utf-8") as f:
            f.write(codigo)
        with open(os.path.join(carpeta_proj, "kit_cierre.txt"), "w", encoding="utf-8") as f:
            f.write(
                f"DIAGNOSTICO:\n{diag}\n\nPRECIOS:\n{precios}\n\nPITCH:\n{pitch}\n\n"
                f"PREGUNTAS CIERRE:\n{preguntas}\n\nFOLLOWUP 24H:\n{followup}\n\nCOBRO:\n{cobro}\n"
            )

        estado_ast = f"{C.GREEN}AST VALIDO{C.RESET}" if valido else f"{C.YELLOW}REVISAR SINTAXIS{C.RESET}"
        print(f"\nScript base [{estado_ast}] -> {ruta_borrador}")
        print(f"{C.DIM}Respaldo guardado en      -> {carpeta_proj}{C.RESET}")
        if paquetes:
            print(f"{C.YELLOW}Librerias detectadas      -> pip install {' '.join(paquetes)}{C.RESET}")
        print()

if __name__ == "__main__":
    main()