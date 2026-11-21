from __future__ import annotations

import csv
import html
import io
import os
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from titan_core.crm_clientes import ClienteService, utc_now_str
from titan_core.db_engine import ROOT_DIR, TitanDBEngine, obtener_db_engine
from titan_core.event_bus import TitanEventBus, obtener_event_bus
from titan_core.time_tracker import TitanTimeTracker, obtener_time_tracker


# ==================== MOTOR DE COMISIONES DE PASARELAS (GROSS-UP + NETO USD/COP) ====================
@dataclass(frozen=True, slots=True)
class ReglaPasarela:
    clave: str
    nombre: str
    pct: float  # ej. 0.054 = 5.4%
    fijo_usd: float  # ej. 0.30
    notas: str = ""


PASARELAS_COMISION: dict[str, ReglaPasarela] = {
    "binance":       ReglaPasarela("binance", "Binance USDT (TRC20/Pay)", 0.0, 0.0, "0% comision directa"),
    "usdt":          ReglaPasarela("usdt", "Crypto USDT / USDC", 0.0, 0.0, "0% comision"),
    "transferencia": ReglaPasarela("transferencia", "Transferencia / Bancolombia / Nequi", 0.0, 0.0, "Sin comision internacional"),
    "wise":          ReglaPasarela("wise", "Wise", 0.012, 0.50, "~1.2% + $0.50"),
    "airtm":         ReglaPasarela("airtm", "Airtm", 0.020, 0.0, "~2.0% P2P"),
    "payoneer":      ReglaPasarela("payoneer", "Payoneer", 0.020, 0.0, "~2.0% retiro"),
    "stripe":        ReglaPasarela("stripe", "Stripe", 0.029, 0.30, "2.9% + $0.30"),
    "whop":          ReglaPasarela("whop", "Whop Marketplace", 0.030, 0.30, "3.0% + $0.30"),
    "paypal":        ReglaPasarela("paypal", "PayPal Internacional", 0.054, 0.30, "5.4% + $0.30"),
}

TIPOS_MOVIMIENTO_VALIDOS = {"ingreso", "gasto", "retiro", "ajuste"}
ESTADOS_FACTURA_VALIDOS = {"emitida", "pagada", "vencida", "anulada"}


def normalizar_pasarela(pasarela: str | None) -> str:
    k = re.sub(r"[^a-z0-9]", "", (pasarela or "binance").lower())
    for clave in PASARELAS_COMISION:
        if clave == k or clave in k:
            return clave
    return "binance"


def calcular_desglose_pasarela(
    monto_bruto_usd: float,
    pasarela: str = "binance",
    trm_cop: float = 4200.0,
) -> dict[str, Any]:
    bruto = max(0.0, round(float(monto_bruto_usd or 0.0), 2))
    trm = max(1.0, float(trm_cop or 4200.0))
    clave = normalizar_pasarela(pasarela)
    regla = PASARELAS_COMISION[clave]

    if bruto <= 0.0:
        comision = 0.0
        neto = 0.0
        gross_up = 0.0
    else:
        comision = round(bruto * regla.pct + regla.fijo_usd, 2)
        neto = round(max(0.0, bruto - comision), 2)
        gross_up = round((bruto + regla.fijo_usd) / max(0.1, 1.0 - regla.pct), 2)

    return {
        "pasarela": regla.clave,
        "nombre": regla.nombre,
        "notas": regla.notas,
        "monto_bruto_usd": bruto,
        "comision_usd": comision,
        "comision_pct_efectiva": round((comision / bruto) * 100.0, 2) if bruto > 0 else 0.0,
        "monto_neto_usd": neto,
        "gross_up_usd": gross_up,
        "trm_cop": round(trm, 2),
        "monto_neto_cop": int(round(neto * trm)),
    }


def comparar_pasarelas(monto_usd: float, trm_cop: float = 4200.0) -> list[dict[str, Any]]:
    claves = ("binance", "wise", "airtm", "stripe", "whop", "paypal")
    lista = [calcular_desglose_pasarela(monto_usd, c, trm_cop) for c in claves]
    lista.sort(key=lambda x: x["monto_neto_usd"], reverse=True)
    return lista


def _cargar_cfg_finanzas() -> dict[str, Any]:
    defaults = {
        "nombre_marca": "ZeroTouch Automation Studio",
        "detalle_pago_factura": "Binance Pay (USDT) / PayPal / Wise / Airtm",
        "trm_cop": 4200.0,
        "meta_mensual_usd": 1500.0,
        "reserva_impuestos_pct": 15.0,
    }
    try:
        from core_ia import cargar_config, safe_float
        cfg = cargar_config()
        defaults["nombre_marca"] = str(cfg.get("nombre_marca") or defaults["nombre_marca"])
        defaults["detalle_pago_factura"] = str(cfg.get("detalle_pago_factura") or cfg.get("metodos_pago") or defaults["detalle_pago_factura"])
        defaults["trm_cop"] = max(100.0, safe_float(cfg.get("trm_cop"), 4200.0))
        defaults["meta_mensual_usd"] = max(50.0, safe_float(cfg.get("meta_mensual_usd"), 1500.0))
        defaults["reserva_impuestos_pct"] = max(0.0, min(50.0, safe_float(cfg.get("reserva_impuestos_pct"), 15.0)))
    except Exception:
        pass
    return defaults


def renderizar_factura_html_v16(
    *,
    numero: str,
    cliente_nombre: str,
    concepto: str,
    modalidad: str,
    pasarela_nombre: str,
    monto_bruto_usd: float,
    comision_usd: float,
    monto_neto_usd: float,
    notas: str = "",
    marca: str = "ZeroTouch Automation Studio",
    detalle_pago: str = "Binance Pay (USDT) / PayPal / Wise",
) -> str:
    fecha = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    nota_bloque = f"<p><strong>Deliverables / Notes:</strong> {html.escape(notas)}</p>" if notas else ""
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>Invoice {html.escape(numero)}</title>
<style>
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; background:#f8fafc; color:#0f172a; margin:0; padding:32px; }}
  .sheet {{ max-width:780px; margin:0 auto; background:#fff; border:1px solid #e2e8f0; border-radius:14px; padding:36px 40px; box-shadow:0 12px 32px rgba(15,23,42,.08); }}
  .top {{ display:flex; justify-content:space-between; align-items:flex-start; border-bottom:2px solid #0ea5e9; padding-bottom:18px; margin-bottom:24px; }}
  .brand {{ font-size:22px; font-weight:800; color:#0f172a; }}
  .brand small {{ display:block; font-size:12px; color:#64748b; font-weight:500; margin-top:4px; }}
  .inv-meta {{ text-align:right; font-size:13px; color:#334155; }}
  .inv-meta b {{ font-size:18px; color:#0284c7; display:block; }}
  table {{ width:100%; border-collapse:collapse; margin:20px 0; }}
  th, td {{ padding:12px 14px; border-bottom:1px solid #e2e8f0; text-align:left; font-size:14px; }}
  th {{ background:#f1f5f9; font-size:12px; text-transform:uppercase; color:#475569; }}
  .num {{ text-align:right; font-family:Consolas,monospace; font-weight:700; }}
  .total-row td {{ font-size:17px; font-weight:800; color:#0f172a; border-top:2px solid #0f172a; border-bottom:none; }}
  .box {{ background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:16px 18px; margin-top:18px; font-size:13px; line-height:1.55; }}
  .box h4 {{ margin:0 0 8px 0; font-size:13px; text-transform:uppercase; color:#0284c7; letter-spacing:.04em; }}
  .print-btn {{ background:#0284c7; color:#fff; border:none; padding:10px 18px; border-radius:8px; font-weight:700; cursor:pointer; margin-top:22px; }}
  @media print {{ body {{ background:#fff; padding:0; }} .sheet {{ box-shadow:none; border:none; }} .print-btn {{ display:none; }} }}
</style></head><body>
<div class="sheet">
  <div class="top">
    <div class="brand">{html.escape(marca)}<small>Software Automation &amp; Python Engineering</small></div>
    <div class="inv-meta"><b>INVOICE #{html.escape(numero)}</b>Date: {fecha}<br>Terms: {html.escape(modalidad)}</div>
  </div>
  <div><strong>Billed To:</strong> {html.escape(cliente_nombre)}</div>
  {nota_bloque}
  <table>
    <thead><tr><th>Service Description</th><th>Payment Method</th><th class="num">Amount (USD)</th></tr></thead>
    <tbody>
      <tr><td>{html.escape(concepto)}</td><td>{html.escape(pasarela_nombre)}</td><td class="num">${monto_bruto_usd:,.2f}</td></tr>
      <tr class="total-row"><td colspan="2">TOTAL DUE (USD)</td><td class="num">${monto_bruto_usd:,.2f} USD</td></tr>
    </tbody>
  </table>
  <div class="box">
    <h4>Payment Instructions</h4>
    <div>{html.escape(detalle_pago)}</div>
    <div style="color:#64748b;font-size:12px;margin-top:6px;">Internal ref — Net after gateway fees: ${monto_neto_usd:,.2f} USD (Est. fee: ${comision_usd:,.2f} USD)</div>
  </div>
  <div class="box">
    <h4>Micro-Contract &amp; Scope of Work</h4>
    <ul style="margin:0;padding-left:18px;">
      <li>Scope is limited strictly to the deliverables listed above. Additional features are quoted separately.</li>
      <li>Includes 1 round of minor revisions within 5 days of delivery to ensure spec compliance.</li>
      <li>Full source code ownership transfers to the Client upon confirmation of full payment.</li>
    </ul>
  </div>
  <button class="print-btn" onclick="window.print()">Print / Save as PDF</button>
</div>
</body></html>"""


# ==================== SERVICIO FINANCIERO COMPLETO (FACTURAS + CAJA + FORECAST) ====================
class TitanFinanceService:
    """
    Motor Financiero y Contable de TITAN-OS v16.0:
    - Facturacion persistente en SQLite ('facturas_db') con calculo automatico de comisiones y HTML/PDF
    - Libro mayor de caja ('movimientos_caja') en USD y COP (ingresos, gastos, retiros, ajustes)
    - Sincronizacion atomica al cobrar factura -> asiento de caja + lead 'ganado' + LTV del cliente
    - Analytics de cashflow mensual (ultimos 12 meses), cuentas por cobrar, fuga de comisiones,
      progreso de meta mensual y tarifa efectiva global cruzada con TitanTimeTracker
    """

    def __init__(
        self,
        db: TitanDBEngine | None = None,
        bus: TitanEventBus | None = None,
        clientes: ClienteService | None = None,
        time_tracker: TitanTimeTracker | None = None,
        carpeta_facturas: str | None = None,
    ) -> None:
        self.db = db or obtener_db_engine()
        self.bus = bus or obtener_event_bus()
        self.clientes = clientes or ClienteService(db=self.db, bus=self.bus)
        self.time_tracker = time_tracker or TitanTimeTracker(db=self.db, bus=self.bus)
        self.carpeta_facturas = os.path.abspath(carpeta_facturas or os.path.join(ROOT_DIR, "entregas_clientes"))
        self._lock = threading.RLock()

    def _generar_numero_factura(self) -> str:
        fecha = datetime.now(timezone.utc).strftime("%Y%m%d")
        suf = uuid.uuid4().hex[:4].upper()
        return f"ZT-{fecha}-{suf}"

    # ==================== 1. FACTURACION PERSISTENTE (facturas_db) ====================
    def emitir_factura(
        self,
        cliente_nombre: str,
        concepto: str,
        monto_bruto_usd: float,
        *,
        modalidad: str = "Final Payment (Full Delivery)",
        pasarela: str = "binance",
        trm_cop: float | None = None,
        lead_id: int | None = None,
        cliente_id: int | None = None,
        notas: str = "",
        guardar_html: bool = True,
        marcar_pagada: bool = False,
    ) -> dict[str, Any]:
        cfg = _cargar_cfg_finanzas()
        trm = float(trm_cop) if (trm_cop and float(trm_cop) > 0) else float(cfg["trm_cop"])
        desg = calcular_desglose_pasarela(monto_bruto_usd, pasarela=pasarela, trm_cop=trm)

        lid_valid: int | None = None
        cid_valid: int | None = int(cliente_id) if cliente_id is not None else None
        if lead_id is not None:
            row_l = self.db.consultar_uno("SELECT id, cliente_id FROM leads WHERE id = ?", (int(lead_id),))
            if row_l:
                lid_valid = int(row_l["id"])
                if cid_valid is None and row_l.get("cliente_id"):
                    cid_valid = int(row_l["cliente_id"])
        if cid_valid is not None and not self.db.escalar("SELECT 1 FROM clientes WHERE id = ?", (cid_valid,)):
            cid_valid = None

        numero = self._generar_numero_factura()
        cli_nom = str(cliente_nombre or "Client").strip()[:120]
        conc = str(concepto or "Custom Python Automation").strip()[:240]
        mod = str(modalidad or "Final Payment").strip()[:80]
        notas_c = str(notas or "").strip()[:500]

        html_doc = renderizar_factura_html_v16(
            numero=numero,
            cliente_nombre=cli_nom,
            concepto=conc,
            modalidad=mod,
            pasarela_nombre=desg["nombre"],
            monto_bruto_usd=desg["monto_bruto_usd"],
            comision_usd=desg["comision_usd"],
            monto_neto_usd=desg["monto_neto_usd"],
            notas=notas_c,
            marca=cfg["nombre_marca"],
            detalle_pago=cfg["detalle_pago_factura"],
        )

        ruta_html = ""
        if guardar_html:
            os.makedirs(self.carpeta_facturas, exist_ok=True)
            slug = re.sub(r"[^a-zA-Z0-9]+", "_", cli_nom.lower()).strip("_")[:24] or "client"
            ruta_html = os.path.join(self.carpeta_facturas, f"factura_{numero}_{slug}.html")
            with open(ruta_html, "w", encoding="utf-8") as f:
                f.write(html_doc)

        fid = self.db.ejecutar(
            """
            INSERT INTO facturas_db (
                numero, lead_id, cliente_id, cliente_nombre, concepto, modalidad,
                pasarela, monto_bruto_usd, comision_usd, monto_neto_usd,
                trm_cop, monto_neto_cop, estado_pago, ruta_html, notas
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'emitida', ?, ?)
            """,
            (
                numero,
                lid_valid,
                cid_valid,
                cli_nom,
                conc,
                mod,
                desg["pasarela"],
                desg["monto_bruto_usd"],
                desg["comision_usd"],
                desg["monto_neto_usd"],
                desg["trm_cop"],
                desg["monto_neto_cop"],
                ruta_html,
                notas_c,
            ),
        )

        self.bus.publicar(
            "finanzas.factura.emitida",
            {
                "factura_id": fid,
                "numero": numero,
                "cliente": cli_nom,
                "monto_bruto_usd": desg["monto_bruto_usd"],
                "monto_neto_usd": desg["monto_neto_usd"],
                "pasarela": desg["pasarela"],
            },
            origen="finanzas",
            nivel="info",
        )

        if marcar_pagada:
            fac = self.marcar_factura_pagada(fid)
            assert fac is not None
        else:
            fac = self.obtener_factura(fid)
            assert fac is not None

        fac["html"] = html_doc
        return fac

    def obtener_factura(self, factura_id: int) -> dict[str, Any] | None:
        row = self.db.consultar_uno(
            """
            SELECT f.*, COALESCE(l.titulo, '') AS lead_titulo
            FROM facturas_db f
            LEFT JOIN leads l ON l.id = f.lead_id
            WHERE f.id = ?
            """,
            (int(factura_id),),
        )
        return dict(row) if row else None

    def obtener_html_factura(self, factura_id: int) -> str | None:
        fac = self.obtener_factura(factura_id)
        if not fac:
            return None
        ruta = str(fac.get("ruta_html") or "")
        if ruta and os.path.isfile(ruta):
            try:
                with open(ruta, "r", encoding="utf-8") as f:
                    return f.read()
            except OSError:
                pass
        cfg = _cargar_cfg_finanzas()
        regla = PASARELAS_COMISION.get(normalizar_pasarela(fac.get("pasarela")), PASARELAS_COMISION["binance"])
        return renderizar_factura_html_v16(
            numero=str(fac["numero"]),
            cliente_nombre=str(fac["cliente_nombre"]),
            concepto=str(fac["concepto"]),
            modalidad=str(fac.get("modalidad") or "Final Payment"),
            pasarela_nombre=regla.nombre,
            monto_bruto_usd=float(fac["monto_bruto_usd"]),
            comision_usd=float(fac["comision_usd"]),
            monto_neto_usd=float(fac["monto_neto_usd"]),
            notas=str(fac.get("notas") or ""),
            marca=cfg["nombre_marca"],
            detalle_pago=cfg["detalle_pago_factura"],
        )

    def marcar_factura_pagada(
        self,
        factura_id: int,
        *,
        pasarela: str | None = None,
        trm_cop: float | None = None,
        registrar_en_caja: bool = True,
        sincronizar_lead: bool = True,
    ) -> dict[str, Any] | None:
        with self._lock:
            fid = int(factura_id)
            fac = self.obtener_factura(fid)
            if not fac or fac["estado_pago"] == "anulada":
                return None
            # Idempotencia: si ya estaba pagada, no duplicar asiento en caja
            if fac["estado_pago"] == "pagada":
                return fac

            pas_final = normalizar_pasarela(pasarela or fac.get("pasarela"))
            trm_final = float(trm_cop) if (trm_cop and float(trm_cop) > 0) else float(fac.get("trm_cop") or 4200.0)
            desg = calcular_desglose_pasarela(float(fac["monto_bruto_usd"]), pasarela=pas_final, trm_cop=trm_final)

            with self.db.transaccion() as tx:
                tx.execute(
                    """
                    UPDATE facturas_db
                    SET estado_pago = 'pagada',
                        pasarela = ?,
                        comision_usd = ?,
                        monto_neto_usd = ?,
                        trm_cop = ?,
                        monto_neto_cop = ?,
                        pagada_ts = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        desg["pasarela"],
                        desg["comision_usd"],
                        desg["monto_neto_usd"],
                        desg["trm_cop"],
                        desg["monto_neto_cop"],
                        fid,
                    ),
                )

                if registrar_en_caja:
                    ya_mov = tx.execute("SELECT 1 FROM movimientos_caja WHERE factura_id = ? LIMIT 1", (fid,)).fetchone()
                    if not ya_mov:
                        tx.execute(
                            """
                            INSERT INTO movimientos_caja (tipo, categoria, descripcion, monto_usd, trm_cop, pasarela, factura_id)
                            VALUES ('ingreso', 'factura_freelance', ?, ?, ?, ?, ?)
                            """,
                            (
                                f"Cobro Factura {fac['numero']} — {fac['cliente_nombre']} ({fac['concepto'][:60]})",
                                desg["monto_neto_usd"],
                                desg["trm_cop"],
                                desg["pasarela"],
                                fid,
                            ),
                        )

                if sincronizar_lead and fac.get("lead_id"):
                    lid = int(fac["lead_id"])
                    total_pagado_lead = tx.execute(
                        "SELECT COALESCE(SUM(monto_neto_usd), 0) FROM facturas_db WHERE lead_id = ? AND estado_pago = 'pagada'",
                        (lid,),
                    ).fetchone()[0]
                    tx.execute(
                        "UPDATE leads SET estado = 'ganado', ganancia_usd = MAX(ganancia_usd, ?), actualizado_ts = CURRENT_TIMESTAMP WHERE id = ?",
                        (round(float(total_pagado_lead or desg["monto_neto_usd"]), 2), lid),
                    )

            if fac.get("cliente_id"):
                self.clientes.recalcular_metricas_cliente(int(fac["cliente_id"]))

        actualizada = self.obtener_factura(fid)
        if actualizada:
            self.bus.publicar(
                "finanzas.factura.pagada",
                {
                    "factura_id": fid,
                    "numero": actualizada["numero"],
                    "cliente": actualizada["cliente_nombre"],
                    "monto_neto_usd": actualizada["monto_neto_usd"],
                    "monto_neto_cop": actualizada["monto_neto_cop"],
                    "pasarela": actualizada["pasarela"],
                },
                origen="finanzas",
                nivel="ok",
            )
        return actualizada

    def anular_factura(self, factura_id: int, motivo: str = "") -> dict[str, Any] | None:
        fid = int(factura_id)
        fac = self.obtener_factura(fid)
        if not fac:
            return None
        notas_n = (f"{fac.get('notas') or ''} | Anulada: {motivo}".strip(" |"))[:500] if motivo else str(fac.get("notas") or "")
        with self.db.transaccion() as tx:
            tx.execute("UPDATE facturas_db SET estado_pago = 'anulada', notas = ? WHERE id = ?", (notas_n, fid))
            tx.execute("DELETE FROM movimientos_caja WHERE factura_id = ?", (fid,))
        if fac.get("cliente_id"):
            self.clientes.recalcular_metricas_cliente(int(fac["cliente_id"]))
        return self.obtener_factura(fid)

    def listar_facturas(
        self,
        *,
        estado_pago: str = "",
        cliente_id: int | None = None,
        lead_id: int | None = None,
        limite: int = 80,
    ) -> list[dict[str, Any]]:
        where = ["1=1"]
        params: list[Any] = []
        if estado_pago.strip().lower() in ESTADOS_FACTURA_VALIDOS:
            where.append("f.estado_pago = ?")
            params.append(estado_pago.strip().lower())
        if cliente_id is not None:
            where.append("f.cliente_id = ?")
            params.append(int(cliente_id))
        if lead_id is not None:
            where.append("f.lead_id = ?")
            params.append(int(lead_id))
        params.append(max(1, min(300, int(limite))))

        return self.db.consultar_todos(
            f"""
            SELECT f.*, COALESCE(l.titulo, '') AS lead_titulo
            FROM facturas_db f
            LEFT JOIN leads l ON l.id = f.lead_id
            WHERE {' AND '.join(where)}
            ORDER BY f.id DESC
            LIMIT ?
            """,
            params,
        )

    # ==================== 2. LIBRO MAYOR DE CAJA (movimientos_caja) ====================
    def registrar_movimiento(
        self,
        tipo: str,
        descripcion: str,
        monto_usd: float,
        *,
        categoria: str = "freelance",
        pasarela: str = "binance",
        trm_cop: float | None = None,
        factura_id: int | None = None,
        fecha_ts: str | None = None,
    ) -> dict[str, Any]:
        tp = str(tipo or "ingreso").strip().lower()
        if tp not in TIPOS_MOVIMIENTO_VALIDOS:
            raise ValueError(f"Tipo de movimiento invalido: {tp}")
        monto = round(float(monto_usd), 2)
        if tp in ("ingreso", "gasto", "retiro"):
            monto = abs(monto)

        cfg = _cargar_cfg_finanzas()
        trm = float(trm_cop) if (trm_cop and float(trm_cop) > 0) else float(cfg["trm_cop"])
        pas = normalizar_pasarela(pasarela)
        fts = fecha_ts or utc_now_str()

        mid = self.db.ejecutar(
            """
            INSERT INTO movimientos_caja (tipo, categoria, descripcion, monto_usd, trm_cop, pasarela, factura_id, fecha_ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (tp, str(categoria or "general")[:60], str(descripcion or "Movimiento")[:240], monto, round(trm, 2), pas, factura_id, fts),
        )
        mov = self.db.consultar_uno("SELECT * FROM movimientos_caja WHERE id = ?", (mid,))
        assert mov is not None
        self.bus.publicar(
            "finanzas.movimiento.registrado",
            {"movimiento_id": mid, "tipo": tp, "categoria": mov["categoria"], "monto_usd": monto, "pasarela": pas},
            origen="finanzas",
            nivel="ok" if tp == "ingreso" else "info",
        )
        return mov

    def eliminar_movimiento(self, movimiento_id: int) -> bool:
        return self.db.ejecutar("DELETE FROM movimientos_caja WHERE id = ?", (int(movimiento_id),)) > 0

    def listar_movimientos(
        self,
        *,
        tipo: str = "",
        categoria: str = "",
        limite: int = 120,
    ) -> list[dict[str, Any]]:
        where = ["1=1"]
        params: list[Any] = []
        if tipo.strip().lower() in TIPOS_MOVIMIENTO_VALIDOS:
            where.append("tipo = ?")
            params.append(tipo.strip().lower())
        if categoria.strip():
            where.append("lower(categoria) = ?")
            params.append(categoria.strip().lower())
        params.append(max(1, min(400, int(limite))))
        return self.db.consultar_todos(
            f"SELECT * FROM movimientos_caja WHERE {' AND '.join(where)} ORDER BY fecha_ts DESC, id DESC LIMIT ?",
            params,
        )

    # ==================== 3. ANALYTICS FINANCIEROS, CASHFLOW MENSUAL & EXPORT ====================
    def cashflow_mensual(self, meses: int = 6) -> list[dict[str, Any]]:
        n = max(1, min(24, int(meses)))
        rows = self.db.consultar_todos(
            """
            SELECT strftime('%Y-%m', fecha_ts) AS mes,
                   ROUND(COALESCE(SUM(CASE WHEN tipo = 'ingreso' THEN monto_usd ELSE 0 END), 0), 2) AS ingresos_usd,
                   ROUND(COALESCE(SUM(CASE WHEN tipo = 'gasto' THEN monto_usd ELSE 0 END), 0), 2) AS gastos_usd,
                   ROUND(COALESCE(SUM(CASE WHEN tipo = 'retiro' THEN monto_usd ELSE 0 END), 0), 2) AS retiros_usd,
                   ROUND(COALESCE(SUM(CASE WHEN tipo = 'ajuste' THEN monto_usd ELSE 0 END), 0), 2) AS ajustes_usd
            FROM movimientos_caja
            GROUP BY mes
            ORDER BY mes DESC
            LIMIT ?
            """,
            (n,),
        )
        mapa = {str(r["mes"]): dict(r) for r in rows if r.get("mes")}

        # Construir secuencia continua de los ultimos N meses (ideal para graficos SVG)
        hoy = datetime.now(timezone.utc)
        y, m = hoy.year, hoy.month
        claves: list[str] = []
        for _ in range(n):
            claves.append(f"{y:04d}-{m:02d}")
            m -= 1
            if m == 0:
                m = 12
                y -= 1
        claves.reverse()

        salida: list[dict[str, Any]] = []
        for k in claves:
            r = mapa.get(k, {})
            ing = float(r.get("ingresos_usd") or 0.0)
            gas = float(r.get("gastos_usd") or 0.0)
            ret = float(r.get("retiros_usd") or 0.0)
            aju = float(r.get("ajustes_usd") or 0.0)
            salida.append({
                "mes": k,
                "ingresos_usd": round(ing, 2),
                "gastos_usd": round(gas, 2),
                "retiros_usd": round(ret, 2),
                "neto_operativo_usd": round(ing - gas + aju, 2),
                "flujo_caja_usd": round(ing - gas - ret + aju, 2),
            })
        return salida

    def resumen_financiero(self, trm_cop: float | None = None, meta_mensual_usd: float | None = None) -> dict[str, Any]:
        cfg = _cargar_cfg_finanzas()
        trm = float(trm_cop) if (trm_cop and float(trm_cop) > 0) else float(cfg["trm_cop"])
        meta = float(meta_mensual_usd) if (meta_mensual_usd and float(meta_mensual_usd) > 0) else float(cfg["meta_mensual_usd"])
        reserva_pct = float(cfg["reserva_impuestos_pct"])

        mes_actual = datetime.now(timezone.utc).strftime("%Y-%m")

        row_tot = self.db.consultar_uno(
            """
            SELECT
                COALESCE(SUM(CASE WHEN tipo = 'ingreso' THEN monto_usd ELSE 0 END), 0) AS ingresos_tot,
                COALESCE(SUM(CASE WHEN tipo = 'gasto' THEN monto_usd ELSE 0 END), 0) AS gastos_tot,
                COALESCE(SUM(CASE WHEN tipo = 'retiro' THEN monto_usd ELSE 0 END), 0) AS retiros_tot,
                COALESCE(SUM(CASE WHEN tipo = 'ajuste' THEN monto_usd ELSE 0 END), 0) AS ajustes_tot
            FROM movimientos_caja
            """
        ) or {}

        row_mes = self.db.consultar_uno(
            """
            SELECT
                COALESCE(SUM(CASE WHEN tipo = 'ingreso' THEN monto_usd ELSE 0 END), 0) AS ing_mes,
                COALESCE(SUM(CASE WHEN tipo = 'gasto' THEN monto_usd ELSE 0 END), 0) AS gas_mes
            FROM movimientos_caja
            WHERE strftime('%Y-%m', fecha_ts) = ?
            """,
            (mes_actual,),
        ) or {}

        row_fac = self.db.consultar_uno(
            """
            SELECT
                COUNT(*) AS total_facturas,
                SUM(CASE WHEN estado_pago = 'pagada' THEN 1 ELSE 0 END) AS pagadas,
                SUM(CASE WHEN estado_pago IN ('emitida', 'vencida') THEN 1 ELSE 0 END) AS pendientes,
                COALESCE(SUM(CASE WHEN estado_pago IN ('emitida', 'vencida') THEN monto_bruto_usd ELSE 0 END), 0) AS por_cobrar_usd,
                COALESCE(SUM(CASE WHEN estado_pago = 'pagada' THEN comision_usd ELSE 0 END), 0) AS comisiones_pagadas_usd
            FROM facturas_db
            """
        ) or {}

        ing_tot = round(float(row_tot.get("ingresos_tot") or 0.0), 2)
        gas_tot = round(float(row_tot.get("gastos_tot") or 0.0), 2)
        ret_tot = round(float(row_tot.get("retiros_tot") or 0.0), 2)
        aju_tot = round(float(row_tot.get("ajustes_tot") or 0.0), 2)
        utilidad_neta = round(ing_tot - gas_tot + aju_tot, 2)
        balance_caja = round(utilidad_neta - ret_tot, 2)

        ing_mes = round(float(row_mes.get("ing_mes") or 0.0), 2)
        gas_mes = round(float(row_mes.get("gas_mes") or 0.0), 2)
        neto_mes = round(ing_mes - gas_mes, 2)
        reserva_mes = round(max(0.0, neto_mes) * (reserva_pct / 100.0), 2)

        prod_30d = self.time_tracker.resumen_productividad(dias=30, trm_cop=trm)
        horas_30d = float(prod_30d.get("horas_totales") or 0.0)
        tarifa_real_30d = round(ing_mes / horas_30d, 2) if horas_30d > 0.1 else 0.0

        por_pasarela = self.db.consultar_todos(
            """
            SELECT pasarela,
                   COUNT(*) AS facturas,
                   ROUND(COALESCE(SUM(monto_neto_usd), 0), 2) AS neto_usd,
                   ROUND(COALESCE(SUM(comision_usd), 0), 2) AS comision_usd
            FROM facturas_db
            WHERE estado_pago = 'pagada'
            GROUP BY pasarela
            ORDER BY neto_usd DESC
            """
        )

        gastos_cat = self.db.consultar_todos(
            """
            SELECT categoria, ROUND(COALESCE(SUM(monto_usd), 0), 2) AS usd
            FROM movimientos_caja
            WHERE tipo = 'gasto'
            GROUP BY categoria
            ORDER BY usd DESC
            LIMIT 8
            """
        )

        return {
            "mes_actual": mes_actual,
            "trm_cop": round(trm, 2),
            "ingresos_totales_usd": ing_tot,
            "gastos_totales_usd": gas_tot,
            "retiros_totales_usd": ret_tot,
            "utilidad_neta_usd": utilidad_neta,
            "utilidad_neta_cop": int(round(utilidad_neta * trm)),
            "balance_caja_usd": balance_caja,
            "balance_caja_cop": int(round(balance_caja * trm)),
            "ingresos_mes_usd": ing_mes,
            "ingresos_mes_cop": int(round(ing_mes * trm)),
            "gastos_mes_usd": gas_mes,
            "neto_mes_usd": neto_mes,
            "reserva_sugerida_mes_usd": reserva_mes,
            "reserva_pct": reserva_pct,
            "meta_mensual_usd": round(meta, 2),
            "progreso_meta_pct": round(min(200.0, (ing_mes / max(1.0, meta)) * 100.0), 1),
            "cuentas_por_cobrar_usd": round(float(row_fac.get("por_cobrar_usd") or 0.0), 2),
            "comisiones_perdidas_usd": round(float(row_fac.get("comisiones_pagadas_usd") or 0.0), 2),
            "facturas_totales": int(row_fac.get("total_facturas") or 0),
            "facturas_pagadas": int(row_fac.get("pagadas") or 0),
            "facturas_pendientes": int(row_fac.get("pendientes") or 0),
            "horas_trabajadas_30d": horas_30d,
            "tarifa_efectiva_mes_usd_hr": tarifa_real_30d,
            "cashflow_6m": self.cashflow_mensual(6),
            "por_pasarela": [dict(r) for r in por_pasarela],
            "gastos_por_categoria": [dict(r) for r in gastos_cat],
        }

    def exportar_libro_csv(self) -> str:
        movs = self.listar_movimientos(limite=1000)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["ID", "Fecha_UTC", "Tipo", "Categoria", "Descripcion", "Pasarela", "Monto_USD", "TRM_COP", "Equiv_COP", "Factura_ID"])
        for m in movs:
            usd = float(m["monto_usd"])
            trm = float(m.get("trm_cop") or 4200.0)
            w.writerow([
                m["id"], m["fecha_ts"], m["tipo"], m["categoria"], m["descripcion"],
                m["pasarela"], round(usd, 2), round(trm, 2), int(round(usd * trm)), m.get("factura_id") or "",
            ])
        return "\ufeff" + buf.getvalue()


_FIN_LOCK = threading.Lock()
_FIN_SINGLETON: TitanFinanceService | None = None


def obtener_finance_service() -> TitanFinanceService:
    global _FIN_SINGLETON
    with _FIN_LOCK:
        if _FIN_SINGLETON is None:
            _FIN_SINGLETON = TitanFinanceService()
        return _FIN_SINGLETON