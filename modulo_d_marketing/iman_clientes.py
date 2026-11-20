import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core_ia import C, cargar_config, preparar_db, generar_texto_ia, extraer_etiqueta, copiar_al_portapapeles

def responder_objecion_ia(contexto: str, mensaje_cliente: str) -> dict | None:
    prompt = (
        "Eres un cerrador experto de ventas freelance tecnicas en ingles.\n"
        f"Contexto del proyecto: {contexto or 'Proyecto freelance de Python/Automatizacion'}\n"
        f"Mensaje del cliente: {mensaje_cliente}\n"
        "Responde UNICAMENTE con estas 4 etiquetas XML:\n"
        "<RED_FLAG>Nivel de riesgo del cliente (Bajo / Medio / Alto + motivo en 1 linea en espanol).</RED_FLAG>\n"
        "<CONSEJO_ES>Lectura tactica rapida en 2 lineas (espanol).</CONSEJO_ES>\n"
        "<RESPUESTA_FIRME>Respuesta corta y segura en ingles (35-55 palabras) defendiendo tu precio con valor tecnico.</RESPUESTA_FIRME>\n"
        "<RESPUESTA_FLEXIBLE>Respuesta corta en ingles (35-55 palabras) ajustando alcance para encajar en su presupuesto sin regalarte.</RESPUESTA_FLEXIBLE>"
    )
    res = generar_texto_ia(prompt, temperatura=0.35)
    if not res:
        return None
    return {
        "red_flag": extraer_etiqueta(res, "RED_FLAG"),
        "consejo": extraer_etiqueta(res, "CONSEJO_ES"),
        "firme": extraer_etiqueta(res, "RESPUESTA_FIRME"),
        "flexible": extraer_etiqueta(res, "RESPUESTA_FLEXIBLE"),
    }

def generar_secuencia_followup_ia(contexto: str) -> dict | None:
    prompt = (
        "Crea una secuencia profesional de 3 mensajes cortos en ingles (sin sonar desesperado) para recuperar un prospecto freelance que te dejo en visto.\n"
        f"Proyecto / contexto: {contexto or 'Python scraper / automation script'}\n"
        "Responde UNICAMENTE con estas 3 etiquetas XML:\n"
        "<DIA_1>Seguimiento amable 24h despues (25-35 palabras).</DIA_1>\n"
        "<DIA_3>Seguimiento de valor 3 dias despues ofreciendo muestra o solucion rapida (25-40 palabras).</DIA_3>\n"
        "<CIERRE_SUAVE>Mensaje de despedida elegante (breakup email, 20-30 palabras) que suele reactivar respuestas.</CIERRE_SUAVE>"
    )
    res = generar_texto_ia(prompt, temperatura=0.4)
    if not res:
        return None
    return {
        "dia_1": extraer_etiqueta(res, "DIA_1"),
        "dia_3": extraer_etiqueta(res, "DIA_3"),
        "cierre": extraer_etiqueta(res, "CIERRE_SUAVE"),
    }

def generar_cierre_y_review_ia(proyecto: str, cliente: str = "") -> dict | None:
    prompt = (
        "Crea un kit post-entrega en ingles para enviar a un cliente que acaba de pagar su script/bot freelance.\n"
        f"Cliente: {cliente or 'Client'}\nProyecto entregado: {proyecto or 'Custom Python automation script'}\n"
        "Responde UNICAMENTE con estas 3 etiquetas XML:\n"
        "<ENTREGA>Mensaje profesional entregando el .zip/codigo y explicando que hacer si necesita un ajuste menor (40-55 palabras).</ENTREGA>\n"
        "<REVIEW>Mensaje corto 2 dias despues pidiendo feedback/testimonio o recomendacion (25-40 palabras).</REVIEW>\n"
        "<UPSELL>Oferta sutil de mantenimiento mensual o nueva automatizacion para generar ingresos recurrentes (30-45 palabras).</UPSELL>"
    )
    res = generar_texto_ia(prompt, temperatura=0.4)
    if not res:
        return None
    return {
        "entrega": extraer_etiqueta(res, "ENTREGA"),
        "review": extraer_etiqueta(res, "REVIEW"),
        "upsell": extraer_etiqueta(res, "UPSELL"),
    }

def generar_post_for_hire() -> None:
    cfg = cargar_config()
    print(f"\n{C.BOLD}{C.CYAN}--- GENERADOR DE POSTS [For Hire] / [Offer] ---{C.RESET}")
    print(" [1] r/forhire ($15/hr+ o proyectos $50+)")
    print(" [2] r/slavelabour (tareas rapidas $20-$80, usar [Offer])")
    print(" [3] r/DoneDirtCheap (encargos rapidos $15-$60, usar [Offer])")
    print(" [4] r/Jobs4Bitcoins (pagos en USDT/cripto, usar [For Hire])")
    print(" [5] r/freelance_forhire ([For Hire])")
    sub_map = {"1": "r/forhire", "2": "r/slavelabour", "3": "r/DoneDirtCheap", "4": "r/Jobs4Bitcoins", "5": "r/freelance_forhire"}
    sub = sub_map.get(input("Elige [1-5]: ").strip(), "r/forhire")
    enfoque = input("Especialidad [Enter para usar tu config]: ").strip() or cfg.get("especialidad")

    prompt = (
        f"Crea una publicacion altamente persuasiva en ingles para {sub} que atraiga clientes freelance reales.\n"
        f"Especialidad: {enfoque}\n"
        f"Metodos de pago: {cfg.get('metodos_pago')}\n"
        f"GitHub: {cfg.get('github_url')}\n"
        f"Reglas: Respeta estrictamente el prefijo de {sub} ([For Hire] o [Offer]). Lista problemas concretos con solucion rapida (24-48h) y muestra de prueba antes del pago final. Tono humano, directo, sin cliches de IA.\n"
        "Responde UNICAMENTE con estas 2 etiquetas XML:\n"
        "<TITULO>Titulo listo para pegar</TITULO>\n"
        "<CUERPO>Cuerpo en Markdown limpio de Reddit</CUERPO>"
    )
    print(f"{C.DIM}[*] Redactando post magnetico para {sub}...{C.RESET}", flush=True)
    res = generar_texto_ia(prompt, temperatura=0.4)
    if not res:
        print(f"{C.RED}[!] No se pudo generar en este momento.{C.RESET}")
        return

    titulo = extraer_etiqueta(res, "TITULO")
    cuerpo = extraer_etiqueta(res, "CUERPO")
    copiar_al_portapapeles(f"{titulo}\n\n{cuerpo}")

    print("\n" + "=" * 68)
    print(f"{C.BOLD}{C.GREEN}TITULO:{C.RESET}\n{titulo}\n")
    print(f"{C.BOLD}CUERPO:{C.RESET}\n{cuerpo}")
    print("=" * 68)
    print(f"{C.GREEN}[+] Post copiado al portapapeles! Ve a {sub} y publicalo.{C.RESET}\n")

def negociador_objeciones() -> None:
    print(f"\n{C.BOLD}{C.YELLOW}--- NEGOCIADOR IA EN VIVO (MATA-OBJECIONES) ---{C.RESET}")
    contexto = input("De que es el trabajo y cuanto pediste? (ej. Bot Telegram, pedi $90): ").strip()
    mensaje_cliente = input("Que te acaba de escribir el cliente?: ").strip()
    if not mensaje_cliente:
        return

    print(f"{C.DIM}[*] Calculando contraofertas...{C.RESET}", flush=True)
    res = responder_objecion_ia(contexto, mensaje_cliente)
    if not res:
        return

    copiar_al_portapapeles(res["firme"])
    print("\n" + "=" * 68)
    if res.get("red_flag"):
        print(f"{C.YELLOW}RIESGO:{C.RESET} {res['red_flag']}")
    print(f"{C.BOLD}LECTURA TACTICA:{C.RESET}\n{res['consejo']}\n")
    print(f"{C.BOLD}{C.GREEN}OPCION A — FIRME (Copiada al portapapeles):{C.RESET}\n{res['firme']}\n")
    print(f"{C.BOLD}{C.CYAN}OPCION B — FLEXIBLE (Recortando alcance):{C.RESET}\n{res['flexible']}")
    print("=" * 68 + "\n")

def generar_bio_perfil() -> None:
    cfg = cargar_config()
    print(f"\n{C.BOLD}{C.MAGENTA}--- GENERADOR DE BIOS PROFESIONALES ---{C.RESET}")
    prompt = (
        f"Crea 3 bios de alto impacto en ingles para un dev freelance: {cfg.get('especialidad')}.\n"
        "Responde UNICAMENTE con estas 3 etiquetas XML:\n"
        "<REDDIT_BIO>Max 180 caracteres para perfil de Reddit.</REDDIT_BIO>\n"
        "<GITHUB_BIO>Bio profesional para perfil de GitHub.</GITHUB_BIO>\n"
        "<WHOP_BIO>Descripcion de tienda para Whop.</WHOP_BIO>"
    )
    res = generar_texto_ia(prompt, temperatura=0.4)
    if not res:
        return
    r_bio = extraer_etiqueta(res, "REDDIT_BIO")
    g_bio = extraer_etiqueta(res, "GITHUB_BIO")
    w_bio = extraer_etiqueta(res, "WHOP_BIO")
    copiar_al_portapapeles(r_bio)
    print("\n" + "=" * 68)
    print(f"{C.BOLD}REDDIT BIO (copiada al portapapeles):{C.RESET}\n{r_bio}\n")
    print(f"{C.BOLD}GITHUB BIO:{C.RESET}\n{g_bio}\n")
    print(f"{C.BOLD}WHOP BIO:{C.RESET}\n{w_bio}")
    print("=" * 68 + "\n")

def generar_portafolio_md() -> None:
    cfg = cargar_config()
    conn = preparar_db()
    try:
        ganados = conn.execute("SELECT titulo, categoria FROM leads WHERE estado = 'ganado' ORDER BY id DESC LIMIT 6").fetchall()
    finally:
        conn.close()

    proj_dir = os.path.join(ROOT_DIR, "proyectos")
    carpetas = os.listdir(proj_dir)[:8] if os.path.exists(proj_dir) else []
    extra = input("Proyectos propios extra a destacar [Enter para defaults]: ").strip()

    prompt = (
        "Crea un archivo PORTAFOLIO.md impresionante y directo en ingles para GitHub y clientes freelance.\n"
        f"Marca: {cfg.get('nombre_marca')}\nEspecialidad: {cfg.get('especialidad')}\n"
        f"Ganados: {ganados}\nProyectos locales: {carpetas}\n"
        f"Extra: {extra or 'ZeroTouch 24/7 Lead Radar (Python + GitHub Actions + Telegram + Gemini API), Local AI Assistant'}\n"
        "Incluye: Resumen de 3 lineas, Stack tecnico, 3-4 Casos de Estudio (Problema -> Solucion -> Impacto), Metodos de pago y CTA.\n"
        "Devuelve UNICAMENTE el contenido dentro de <PORTAFOLIO>...</PORTAFOLIO>."
    )
    print(f"{C.CYAN}[*] Construyendo PORTAFOLIO.md profesional...{C.RESET}", flush=True)
    res = generar_texto_ia(prompt, temperatura=0.35)
    if not res:
        return
    md = extraer_etiqueta(res, "PORTAFOLIO") or res
    ruta = os.path.join(ROOT_DIR, "PORTAFOLIO.md")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"{C.GREEN}[+] Portafolio guardado en: {ruta}{C.RESET}\n")

def main() -> None:
    modo = sys.argv[1] if len(sys.argv) > 1 else ""
    if modo == "--negociar":
        negociador_objeciones()
        return
    print(f"\n{C.BOLD}{C.MAGENTA}=== MODULO D: IMAN DE CLIENTES & MARKETING v12.0 ==={C.RESET}")
    print(" [1] Generar post [For Hire] / [Offer] para Reddit")
    print(" [2] Negociador IA en vivo (responder objeciones)")
    print(" [3] Generar Bios (Reddit, GitHub y Whop)")
    print(" [4] Generar PORTAFOLIO.md en ingles")
    op = input("\nElige una opcion: ").strip()
    if op == "1":
        generar_post_for_hire()
    elif op == "2":
        negociador_objeciones()
    elif op == "3":
        generar_bio_perfil()
    elif op == "4":
        generar_portafolio_md()

if __name__ == "__main__":
    main()