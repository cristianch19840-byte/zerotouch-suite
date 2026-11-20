import os
import re
import ast
import sys
import subprocess
from datetime import datetime
from urllib.parse import quote

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core_ia import (
    C,
    SESSION,
    log_evento,
    cargar_config,
    preparar_db,
    verificar_confianza_reddit,
    generar_texto_ia,
    extraer_etiqueta,
    copiar_al_portapapeles,
    validar_y_reparar_python,
    analizar_dependencias,
)

def descargar_post_reddit(url: str) -> tuple[str | None, str, str]:
    headers = {"User-Agent": "python:zerotouch-copiloto:v12.0 (by /u/zerotouch_freelance)"}
    try:
        objetivo = url.strip()
        if "/s/" in objetivo or "redd.it" in objetivo or "old.reddit.com" in objetivo or "m.reddit.com" in objetivo:
            r_res = SESSION.get(objetivo, headers=headers, allow_redirects=True, timeout=10)
            if r_res.url:
                objetivo = r_res.url
        limpia = objetivo.split("?")[0].rstrip("/")
        json_url = limpia if limpia.endswith(".json") else f"{limpia}.json?raw_json=1"
        r = SESSION.get(json_url, headers=headers, timeout=12)
        if r.status_code == 200:
            payload = r.json()
            if isinstance(payload, list) and payload:
                children = payload[0].get("data", {}).get("children", [])
                if children:
                    data = children[0].get("data", {})
                    titulo = data.get("title", "")
                    cuerpo = data.get("selftext", "")
                    sub = data.get("subreddit_name_prefixed", "Reddit")
                    autor = data.get("author", "")
                    return f"Fuente: {sub}\nAutor: u/{autor}\nTitulo: {titulo}\n\n{cuerpo}".strip(), autor, titulo
    except Exception as e:
        log_evento(f"Copiloto no pudo leer link Reddit: {e}")
        print(f"{C.YELLOW}[!] No pude leer el link automatico ({e}).{C.RESET}")
    return None, "", ""

def cargar_desde_crm(lead_id: int) -> tuple[str | None, str, str]:
    conn = preparar_db()
    try:
        row = conn.execute("SELECT fuente, autor, titulo, presupuesto, link FROM leads WHERE id = ?", (lead_id,)).fetchone()
        if not row:
            return None, "", ""
        fuente, autor, titulo, pres, link = row
        if link and ("reddit.com" in link or "redd.it" in link):
            oferta, a_red, t_red = descargar_post_reddit(link)
            if oferta:
                return oferta, a_red or autor, t_red or titulo
        return f"Fuente: {fuente}\nPresupuesto: {pres}\nTitulo: {titulo}\nLink: {link}", autor, titulo
    finally:
        conn.close()

def crear_slug(texto: str) -> str:
    palabras = re.sub(r"[^a-zA-Z0-9\s]", "", texto.lower()).split()[:5]
    return "_".join(palabras) or "proyecto"

def resolver_ruta_script(ruta_script: str = "") -> str:
    ruta = (ruta_script or "").strip() or os.path.join("modulo_b_ejecutor", "borrador_cliente.py")
    if not os.path.isabs(ruta):
        ruta = os.path.join(ROOT_DIR, ruta)
    return ruta

def leer_borrador_actual(ruta_script: str = "") -> dict:
    ruta = resolver_ruta_script(ruta_script)
    if not os.path.isfile(ruta):
        return {"error": f"No existe todavia: {ruta}", "codigo": "", "ast_valido": False, "todos_pip": [], "faltantes_pip": []}
    with open(ruta, "r", encoding="utf-8") as f:
        codigo = f.read()
    try:
        ast.parse(codigo)
        valido = True
    except SyntaxError:
        valido = False
    todos_pip, faltantes_pip = analizar_dependencias(codigo)
    return {
        "ruta": os.path.relpath(ruta, ROOT_DIR).replace("\\", "/"),
        "codigo": codigo,
        "lineas": len(codigo.splitlines()),
        "ast_valido": valido,
        "todos_pip": todos_pip,
        "faltantes_pip": faltantes_pip,
    }

def refinar_borrador_ia(instruccion: str, ruta_script: str = "") -> dict:
    info = leer_borrador_actual(ruta_script)
    if info.get("error"):
        return info
    if not (instruccion or "").strip():
        return {"error": "Escribe que cambio o mejora quieres hacerle al codigo."}

    prompt = (
        "Eres un ingeniero senior de Python 3.12.\n"
        "Aplica la instruccion solicitada al siguiente script manteniendo codigo limpio, modular, sin errores de sintaxis y listo para ejecutar.\n"
        f"INSTRUCCION DEL DEV:\n{instruccion}\n\n"
        "Responde UNICAMENTE usando estas 2 etiquetas XML:\n"
        "<RESUMEN_CAMBIOS>Resumen de 2 lineas en espanol explicando que mejoraste.</RESUMEN_CAMBIOS>\n"
        "<CODIGO_NUEVO>Codigo completo actualizado en Python 3.12.</CODIGO_NUEVO>\n\n"
        f"CODIGO ACTUAL:\n{info['codigo']}"
    )
    resp = generar_texto_ia(prompt, temperatura=0.2, json_mode=False, timeout=34)
    if not resp:
        return {"error": "Gemini no respondio al refinar el codigo."}

    resumen = extraer_etiqueta(resp, "RESUMEN_CAMBIOS") or "Codigo actualizado."
    nuevo_raw = extraer_etiqueta(resp, "CODIGO_NUEVO") or resp
    codigo_ok, valido = validar_y_reparar_python(nuevo_raw, descripcion=instruccion)
    if not codigo_ok:
        return {"error": "No se pudo extraer codigo valido."}

    ruta_abs = resolver_ruta_script(ruta_script)
    with open(ruta_abs, "w", encoding="utf-8") as f:
        f.write(codigo_ok)

    todos_pip, faltantes_pip = analizar_dependencias(codigo_ok)
    log_evento(f"Codigo refinado ({os.path.basename(ruta_abs)} | {'AST OK' if valido else 'Revisar'})")
    return {
        "ruta": info["ruta"],
        "resumen": resumen,
        "codigo": codigo_ok,
        "lineas": len(codigo_ok.splitlines()),
        "ast_valido": valido,
        "todos_pip": todos_pip,
        "faltantes_pip": faltantes_pip,
    }

def analizar_oferta_completo(oferta: str, autor: str = "", titulo: str = "", guardar_archivos: bool = True) -> dict | None:
    cfg = cargar_config()
    confianza = verificar_confianza_reddit(autor) if autor else ""
    tarifa = cfg.get("tarifa_hora_usd", 25)

    prompt = (
        "Eres un desarrollador senior y cerrador freelance de Python/Automatizacion.\n"
        f"Tarifa base de referencia del dev: ${tarifa} USD/hora.\n"
        f"Metodos de pago: {cfg.get('metodos_pago')}\n"
        f"GitHub: {cfg.get('github_url')}\n"
        "Analiza esta oferta y responde UNICAMENTE usando estas 10 etiquetas XML (sin texto fuera):\n\n"
        "<DIAGNOSTICO>\n"
        "Que pide el cliente, stack exacto y el detalle tecnico clave para demostrar dominio (2-3 lineas en espanol).\n"
        "</DIAGNOSTICO>\n\n"
        "<RED_FLAGS>\n"
        "Senales de alerta (presupuesto bajo, alcance vago, riesgo de no pago o bloqueos anti-bot) o escribe 'Ninguna alerta critica — buen cliente' (1-2 lineas en espanol).\n"
        "</RED_FLAGS>\n\n"
        "<PRECIOS>\n"
        "3 opciones en USD en 3 lineas (calculadas con la tarifa base y complejidad): Basico (script rapido), Estandar (robusto + CSV/JSON), Premium (automatizacion + soporte).\n"
        "</PRECIOS>\n\n"
        "<PITCH_A>\n"
        "Pitch estilo A — Directo y Tecnico en ingles (45-65 palabras): diagnostico inmediato, plazo concreto, cero relleno.\n"
        "</PITCH_A>\n\n"
        "<PITCH_B>\n"
        "Pitch estilo B — Consultivo y Cercano en ingles (45-65 palabras): enfocado en el resultado de negocio y oferta de prototipo rapido.\n"
        "</PITCH_B>\n\n"
        "<PREGUNTAS_CIERRE>\n"
        "2 preguntas tecnicas cortas en ingles para cerrar alcance y precio cuando responda.\n"
        "</PREGUNTAS_CIERRE>\n\n"
        "<FOLLOWUP>\n"
        "Mensaje corto de seguimiento en ingles (25-35 palabras) para enviar 24h despues si te dejan en visto.\n"
        "</FOLLOWUP>\n\n"
        "<MENSAJE_COBRO>\n"
        f"Mensaje profesional en ingles (35-50 palabras) para enviar junto a la captura de muestra pidiendo 50% o pago final via {cfg.get('metodos_pago')}.\n"
        "</MENSAJE_COBRO>\n\n"
        "<MICRO_CONTRATO>\n"
        "Acuerdo de alcance (Scope of Work) de 4 vinetas cortas en ingles para pegar en el chat antes de empezar: entregables exactos, 1 ronda de ajustes incluida, cambios extra se cotizan aparte, entrega del codigo tras confirmar pago.\n"
        "</MICRO_CONTRATO>\n\n"
        "<CODIGO>\n"
        "Script completo, modular y limpio en Python 3.12 listo como base funcional para resolver el pedido, con manejo de errores, logging claro y exportacion ordenada.\n"
        "</CODIGO>\n\n"
        f"OFERTA DEL CLIENTE:\n{oferta}"
    )

    texto = generar_texto_ia(prompt, temperatura=0.25, json_mode=False, timeout=36)
    if not texto:
        return None

    diag = extraer_etiqueta(texto, "DIAGNOSTICO")
    red_flags = extraer_etiqueta(texto, "RED_FLAGS")
    precios = extraer_etiqueta(texto, "PRECIOS")
    pitch_a = extraer_etiqueta(texto, "PITCH_A")
    pitch_b = extraer_etiqueta(texto, "PITCH_B")
    preguntas = extraer_etiqueta(texto, "PREGUNTAS_CIERRE")
    followup = extraer_etiqueta(texto, "FOLLOWUP")
    cobro = extraer_etiqueta(texto, "MENSAJE_COBRO")
    contrato = extraer_etiqueta(texto, "MICRO_CONTRATO")
    codigo_raw = extraer_etiqueta(texto, "CODIGO")

    codigo, valido = validar_y_reparar_python(codigo_raw, descripcion=diag)
    todos_pip, faltantes_pip = analizar_dependencias(codigo) if codigo else ([], [])

    dm_url = ""
    if autor and autor.lower() not in ("[deleted]", "automoderator", "github", "hackernews"):
        dm_url = f"https://www.reddit.com/message/compose/?to={quote(autor)}&subject={quote('Re: ' + (titulo or 'Project')[:65])}&message={quote(pitch_a[:380])}"

    ruta_borrador = ""
    carpeta_proj = ""
    if guardar_archivos and codigo:
        ruta_borrador = os.path.join(ROOT_DIR, "modulo_b_ejecutor", "borrador_cliente.py")
        with open(ruta_borrador, "w", encoding="utf-8") as f:
            f.write(codigo)

        carpeta_proj = os.path.join(
            ROOT_DIR,
            "proyectos",
            f"{datetime.now().strftime('%Y%m%d_%H%M')}_{crear_slug(titulo or oferta.splitlines()[0])}",
        )
        os.makedirs(carpeta_proj, exist_ok=True)
        with open(os.path.join(carpeta_proj, "script.py"), "w", encoding="utf-8") as f:
            f.write(codigo)
        with open(os.path.join(carpeta_proj, "kit_cierre_apex.txt"), "w", encoding="utf-8") as f:
            f.write(
                f"CONFIANZA CLIENTE: {confianza}\nRED FLAGS: {red_flags}\n\nDIAGNOSTICO:\n{diag}\n\nPRECIOS:\n{precios}\n\n"
                f"PITCH A (TECNICO):\n{pitch_a}\n\nPITCH B (CONSULTIVO):\n{pitch_b}\n\n"
                f"PREGUNTAS:\n{preguntas}\n\nMICRO-CONTRATO:\n{contrato}\n\n"
                f"FOLLOWUP 24H:\n{followup}\n\nCOBRO:\n{cobro}\n"
            )
        log_evento(f"Copiloto APEX genero kit + borrador ({'AST OK' if valido else 'Revisar'})")

    return {
        "confianza": confianza,
        "red_flags": red_flags,
        "diagnostico": diag,
        "precios": precios,
        "pitch_a": pitch_a,
        "pitch_b": pitch_b,
        "preguntas": preguntas,
        "followup": followup,
        "cobro": cobro,
        "micro_contrato": contrato,
        "codigo": codigo,
        "ast_valido": valido,
        "todos_pip": todos_pip,
        "faltantes_pip": faltantes_pip,
        "dm_url": dm_url,
        "ruta_borrador": ruta_borrador,
        "carpeta_proj": carpeta_proj,
    }

def main() -> None:
    print(f"\n{C.BOLD}{C.CYAN}=== MODULO B: COPILOTO APEX v12.0 (A/B + RED FLAGS + REFINADOR) ==={C.RESET}")
    print("Opcion 1: Pega un LINK de Reddit (PC o App Movil /s/) y dale Enter.")
    print("Opcion 2: Escribe #<ID> de tu CRM (ej. #4) y dale Enter.")
    print("Opcion 3: Escribe REFINAR para mejorar tu borrador_cliente.py actual.")
    print("Opcion 4: Pega el texto de la oferta, escribe FIN en linea nueva y dale Enter.\n")

    primera = input(f"{C.GREEN}> {C.RESET}").strip()
    if not primera:
        print("[!] No ingresaste nada.")
        return

    if primera.upper() == "REFINAR":
        instr = input("Que mejora o cambio le metemos a borrador_cliente.py?: ").strip()
        r = refinar_borrador_ia(instr)
        if r.get("error"):
            print(f"{C.RED}[!] {r['error']}{C.RESET}")
        else:
            print(f"\n{C.GREEN}[+] {r['resumen']} ({r['lineas']} lineas | {'AST OK' if r['ast_valido'] else 'Revisar'}){C.RESET}\n")
        return

    autor_reddit = ""
    titulo_reddit = ""
    if primera.startswith("#") and primera[1:].isdigit():
        print(f"{C.DIM}[*] Cargando lead {primera} desde tu CRM...{C.RESET}", flush=True)
        oferta, autor_reddit, titulo_reddit = cargar_desde_crm(int(primera[1:]))
        if not oferta:
            print(f"{C.RED}[!] No existe el lead {primera} en tu CRM.{C.RESET}")
            return
    elif primera.startswith("http") and ("reddit.com" in primera or "redd.it" in primera):
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

    print(f"{C.CYAN}[*] Ejecutando motor Copiloto APEX...{C.RESET}", flush=True)
    res = analizar_oferta_completo(oferta, autor=autor_reddit, titulo=titulo_reddit, guardar_archivos=True)
    if not res:
        print(f"{C.RED}[!] No se pudo generar respuesta en este momento.{C.RESET}")
        return

    copiado = copiar_al_portapapeles(res["pitch_a"])

    print("\n" + "=" * 72)
    if res["confianza"]:
        print(f"{C.MAGENTA}CLIENT TRUST RADAR:{C.RESET} {res['confianza']}")
    if res["red_flags"]:
        print(f"{C.YELLOW}ALERTAS / RED FLAGS:{C.RESET} {res['red_flags']}\n")
    print(f"{C.BOLD}DIAGNOSTICO TECNICO:{C.RESET}\n{res['diagnostico']}\n")
    print(f"{C.BOLD}{C.GREEN}ESCALERA DE PRECIOS:{C.RESET}\n{res['precios']}\n")
    print("-" * 72)
    print(f"{C.BOLD}{C.CYAN}PITCH A — DIRECTO TECNICO:{C.RESET}\n{res['pitch_a']}\n")
    if copiado:
        print(f"{C.GREEN}[+] Pitch A copiado automaticamente al portapapeles (Ctrl+V)!{C.RESET}\n")
    print(f"{C.BOLD}{C.BLUE}PITCH B — CONSULTIVO:{C.RESET}\n{res['pitch_b']}\n")
    if res["dm_url"]:
        print(f"{C.MAGENTA}DM DIRECTO PRE-LLENADO:\n{res['dm_url']}{C.RESET}\n")
    print("-" * 72)
    print(f"{C.BOLD}MICRO-CONTRATO:{C.RESET}\n{res['micro_contrato']}\n")
    print(f"{C.BOLD}MENSAJE DE COBRO:{C.RESET}\n{res['cobro']}")
    print("=" * 72)

    if res["ruta_borrador"]:
        estado_ast = f"{C.GREEN}AST VALIDO{C.RESET}" if res["ast_valido"] else f"{C.YELLOW}REVISAR SINTAXIS{C.RESET}"
        print(f"\nScript base [{estado_ast}] -> {res['ruta_borrador']}")
        print(f"{C.DIM}Respaldo guardado en      -> {res['carpeta_proj']}{C.RESET}")
        if res["faltantes_pip"]:
            pkgs = " ".join(res["faltantes_pip"])
            print(f"{C.YELLOW}[!] Paquetes faltantes en tu PC: {pkgs}{C.RESET}")
            if input("Quieres instalarlos automaticamente ahora? [s/N]: ").strip().lower() == "s":
                subprocess.run([sys.executable, "-m", "pip", "install", *res["faltantes_pip"]])
        elif res["todos_pip"]:
            print(f"{C.GREEN}[+] Todas las librerias ({', '.join(res['todos_pip'])}) ya estan instaladas!{C.RESET}")
        print()

if __name__ == "__main__":
    main()