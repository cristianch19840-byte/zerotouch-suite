#!/usr/bin/env python3
"""
ZeroTouch TITAN-OS v16.0 — CLI Maestro Unificado.
Uso:
  python titan_cli.py doctor
  python titan_cli.py serve --port 8765
  python titan_cli.py audit [--strict]
  python titan_cli.py backup create|list|verify|restore
  python titan_cli.py crm pipeline|leads|agenda
  python titan_cli.py finanzas resumen|pasarelas
  python titan_cli.py aegis simular|drift|calibrar
  python titan_cli.py sandbox audit|run <archivo.py>
  python titan_cli.py factory license-emit|license-verify
  python titan_cli.py db optimize
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def _out(data: Any, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        return
    if isinstance(data, str):
        print(data)
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def cmd_doctor(args: argparse.Namespace) -> int:
    from titan_core.api_v2_app import construir_servicios_titan
    from titan_core.security_hardening import SecurityAuditor

    svc = construir_servicios_titan(db_path=args.db, iniciar_workflows=False)
    try:
        db_s = svc.db.verificar_salud().to_dict()
        sec = SecurityAuditor(db=svc.db).auditar().to_dict()
        ai_s = svc.ai_router.estado_salud()
        drift = svc.aegis.calibrador.analizar_drift().to_dict()
        rep = {
            "version": "16.0.0-titan",
            "db": {
                "integridad_ok": db_s["integridad_ok"],
                "version_esquema": db_s["version_esquema"],
                "tablas": len(db_s["tablas"]),
                "tamano_kb": db_s["tamano_kb"],
            },
            "seguridad": {
                "score": sec["score_0_100"],
                "grado": sec["grado"],
                "resumen": sec["resumen"],
            },
            "ai_router": {
                "estrategia": ai_s["estrategia"],
                "gemini_keys": ai_s["proveedores"]["gemini"]["keys_count"],
                "ollama_online": ai_s["proveedores"]["ollama"]["disponible"],
                "cache_hit_pct": ai_s["cache"]["hit_rate_pct"],
            },
            "aegis_drift": {
                "psi": drift["psi"],
                "nivel": drift["nivel_alerta"],
            },
            "workflows_activas": sum(1 for r in svc.workflows.listar_reglas() if r.activa),
        }
        _out(rep, as_json=True)
        return 0 if db_s["integridad_ok"] and sec["resumen"]["criticos"] == 0 else 1
    finally:
        svc.cerrar()


def cmd_audit(args: argparse.Namespace) -> int:
    from titan_core.db_engine import TitanDBEngine, obtener_db_engine
    from titan_core.security_hardening import SecurityAuditor

    db = TitanDBEngine(db_path=args.db) if args.db else obtener_db_engine()
    try:
        rep = SecurityAuditor(root_dir=args.root or ROOT_DIR, db=db).auditar()
        _out(rep.to_dict(), as_json=True)
        if args.strict and (rep.criticos > 0 or rep.altos > 0):
            return 2
        return 0 if rep.criticos == 0 else 1
    finally:
        if args.db:
            db.cerrar_todo()


def cmd_backup(args: argparse.Namespace) -> int:
    from titan_core.db_engine import TitanDBEngine, obtener_db_engine
    from titan_core.security_hardening import EncryptedBackupVault

    db = TitanDBEngine(db_path=args.db) if args.db else obtener_db_engine()
    vault = EncryptedBackupVault(db=db, vault_dir=args.vault_dir)
    try:
        if args.action == "create":
            res = vault.crear_backup_cifrado(etiqueta=args.label, max_backups=args.keep)
            _out(res, as_json=True)
            return 0 if res.get("ok") else 1
        if args.action == "list":
            _out({"ok": True, "backups": vault.listar_backups()}, as_json=True)
            return 0
        if args.action == "verify":
            if not args.file:
                print("ERROR: especifica --file <archivo.ztvault>", file=sys.stderr)
                return 2
            res = vault.verificar_backup(args.file)
            _out(res, as_json=True)
            return 0 if res.get("ok") else 1
        if args.action == "restore":
            if not args.file or not args.dest:
                print("ERROR: especifica --file <archivo.ztvault> y --dest <carpeta>", file=sys.stderr)
                return 2
            res = vault.restaurar_backup(args.file, args.dest)
            _out(res, as_json=True)
            return 0 if res.get("ok") else 1
        return 2
    finally:
        if args.db:
            db.cerrar_todo()


def cmd_serve(args: argparse.Namespace) -> int:
    from titan_core.api_v2_app import crear_app_titan_v16

    srv, svc = crear_app_titan_v16(
        host=args.host,
        port=args.port,
        db_path=args.db,
        api_token=args.token,
        iniciar_workflows=not args.no_workflows,
    )
    print(f"[TITAN-OS v16] Servidor REST + SSE activo en http://{args.host}:{args.port} (Ctrl+C para salir)")
    try:
        srv.servir_bloqueante()
    except KeyboardInterrupt:
        print("\n[TITAN-OS v16] Apagado limpio.")
    finally:
        srv.detener()
        svc.cerrar()
    return 0


def cmd_crm(args: argparse.Namespace) -> int:
    from titan_core.api_v2_app import construir_servicios_titan

    svc = construir_servicios_titan(db_path=args.db, iniciar_workflows=False)
    try:
        if args.action == "pipeline":
            _out(svc.crm.resumen_pipeline(trm_cop=args.trm), as_json=True)
        elif args.action == "leads":
            _out(svc.crm.buscar_leads(estado=args.estado or "", limite=args.limit), as_json=True)
        elif args.action == "agenda":
            _out(svc.crm.resumen_agenda(), as_json=True)
        return 0
    finally:
        svc.cerrar()


def cmd_finanzas(args: argparse.Namespace) -> int:
    from titan_core.api_v2_app import construir_servicios_titan
    from titan_core.finance_service import comparar_pasarelas

    if args.action == "pasarelas":
        _out(comparar_pasarelas(args.monto, trm_cop=args.trm), as_json=True)
        return 0
    svc = construir_servicios_titan(db_path=args.db, iniciar_workflows=False)
    try:
        _out(svc.finance.resumen_financiero(trm_cop=args.trm), as_json=True)
        return 0
    finally:
        svc.cerrar()


def cmd_aegis(args: argparse.Namespace) -> int:
    from modulo_a_radar_whop.motor_filtrado.modelos import ContextoFiltro
    from titan_core.api_v2_app import construir_servicios_titan

    svc = construir_servicios_titan(db_path=args.db, iniciar_workflows=False)
    try:
        if args.action == "drift":
            _out(svc.aegis.calibrador.analizar_drift().to_dict(), as_json=True)
            return 0
        if args.action == "calibrar":
            _out(svc.aegis.calibrar_automatico(perfil_nombre=args.perfil or None, aplicar=True), as_json=True)
            return 0
        if args.action == "simular":
            ctx = ContextoFiltro(plataforma=args.plataforma, fuente=args.plataforma, perfil_nombre=args.perfil or "equilibrado")
            v = svc.aegis.evaluar(args.titulo or "", args.cuerpo or "", post_id="cli_sim", ctx=ctx, simular_sin_dedup=True, registrar_dedup=False, registrar_auditoria=False)
            _out(svc.aegis.radiografia_dict(v), as_json=True)
            return 0 if v.aprobado else 1
        return 2
    finally:
        svc.cerrar()


def cmd_sandbox(args: argparse.Namespace) -> int:
    from titan_core.sandbox_runner import TitanSandboxRunner, auditar_codigo_ast

    if not os.path.isfile(args.file):
        print(f"ERROR: archivo no encontrado: {args.file}", file=sys.stderr)
        return 2
    with open(args.file, "r", encoding="utf-8", errors="replace") as f:
        code = f.read()
    if args.action == "audit":
        rep = auditar_codigo_ast(code)
        _out(rep.to_dict(), as_json=True)
        return 0 if (rep.ast_valido and not rep.bloqueado) else 1
    sbx = TitanSandboxRunner(usar_sqlite=False)
    res = sbx.ejecutar_codigo(code, nombre_ref=args.file, timeout_seg=args.timeout, persistir=False)
    _out(res.to_dict(), as_json=True)
    return 0 if res.ok else 1


def cmd_db(args: argparse.Namespace) -> int:
    from titan_core.db_engine import TitanDBEngine, obtener_db_engine

    db = TitanDBEngine(db_path=args.db) if args.db else obtener_db_engine()
    try:
        if args.action == "optimize":
            _out(db.optimizar(), as_json=True)
        elif args.action == "health":
            _out(db.verificar_salud().to_dict(), as_json=True)
        return 0
    finally:
        if args.db:
            db.cerrar_todo()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="titan_cli", description="ZeroTouch TITAN-OS v16.0 — CLI Maestro")
    p.add_argument("--db", default=None, help="Ruta alternativa de SQLite DB")
    sub = p.add_subparsers(dest="comando", required=True)

    sp_doc = sub.add_parser("doctor", help="Diagnóstico integral DB + Seguridad + AI + AEGIS")
    sp_doc.set_defaults(func=cmd_doctor)

    sp_aud = sub.add_parser("audit", help="Auditoría de seguridad anti-secretos y postura")
    sp_aud.add_argument("--root", default=None)
    sp_aud.add_argument("--strict", action="store_true", help="Falla también ante hallazgos altos")
    sp_aud.set_defaults(func=cmd_audit)

    sp_bkp = sub.add_parser("backup", help="Bóveda de backups cifrados .ztvault")
    sp_bkp.add_argument("action", choices=["create", "list", "verify", "restore"])
    sp_bkp.add_argument("--label", default="cli")
    sp_bkp.add_argument("--keep", type=int, default=12)
    sp_bkp.add_argument("--vault-dir", default=None)
    sp_bkp.add_argument("--file", default="")
    sp_bkp.add_argument("--dest", default="")
    sp_bkp.set_defaults(func=cmd_backup)

    sp_srv = sub.add_parser("serve", help="Levanta servidor REST v2 + SSE TITAN-OS v16")
    sp_srv.add_argument("--host", default="127.0.0.1")
    sp_srv.add_argument("--port", type=int, default=8765)
    sp_srv.add_argument("--token", default=None)
    sp_srv.add_argument("--no-workflows", action="store_true")
    sp_srv.set_defaults(func=cmd_serve)

    sp_crm = sub.add_parser("crm", help="Consultas rápidas de CRM")
    sp_crm.add_argument("action", choices=["pipeline", "leads", "agenda"])
    sp_crm.add_argument("--estado", default="")
    sp_crm.add_argument("--limit", type=int, default=20)
    sp_crm.add_argument("--trm", type=float, default=4200.0)
    sp_crm.set_defaults(func=cmd_crm)

    sp_fin = sub.add_parser("finanzas", help="Resumen financiero y comparador pasarelas")
    sp_fin.add_argument("action", choices=["resumen", "pasarelas"])
    sp_fin.add_argument("--monto", type=float, default=300.0)
    sp_fin.add_argument("--trm", type=float, default=4200.0)
    sp_fin.set_defaults(func=cmd_finanzas)

    sp_ag = sub.add_parser("aegis", help="Simulador, drift y calibración AEGIS-X v16")
    sp_ag.add_argument("action", choices=["simular", "drift", "calibrar"])
    sp_ag.add_argument("--titulo", default="")
    sp_ag.add_argument("--cuerpo", default="")
    sp_ag.add_argument("--plataforma", default="Reddit")
    sp_ag.add_argument("--perfil", default="equilibrado")
    sp_ag.set_defaults(func=cmd_aegis)

    sp_sbx = sub.add_parser("sandbox", help="Auditoría AST y ejecución aislada de scripts")
    sp_sbx.add_argument("action", choices=["audit", "run"])
    sp_sbx.add_argument("file")
    sp_sbx.add_argument("--timeout", type=float, default=10.0)
    sp_sbx.set_defaults(func=cmd_sandbox)

    sp_db = sub.add_parser("db", help="Mantenimiento de base de datos SQLite")
    sp_db.add_argument("action", choices=["optimize", "health"])
    sp_db.set_defaults(func=cmd_db)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())