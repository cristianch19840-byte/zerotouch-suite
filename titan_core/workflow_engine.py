from __future__ import annotations

import fnmatch
import json
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from titan_core.db_engine import TitanDBEngine, obtener_db_engine
from titan_core.event_bus import EventoSistema, TitanEventBus, obtener_event_bus
from titan_core.http_shield import TitanHTTPShield, obtener_http_shield
from titan_core.telemetry import RotatingJSONLLogger, TitanTelemetry, obtener_logger, obtener_telemetry
from titan_core.workflow_actions import (
    ActionRegistry,
    ContextoAccion,
    ResultadoAccion,
    interpolar_texto,
    resolver_ruta_dato,
)


# ==================== EVALUADOR DE CONDICIONES COMPUESTAS (16 OPERADORES) ====================
OPERADORES_VALIDOS = {
    "eq", "ne", "gt", "gte", "lt", "lte",
    "contains", "not_contains", "icontains",
    "startswith", "endswith",
    "in", "not_in", "regex", "exists", "between",
}


def _a_float(val: Any) -> float | None:
    if isinstance(val, bool):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def evaluar_condicion_atomica(cond: dict[str, Any], contexto: dict[str, Any]) -> tuple[bool, str]:
    campo = str(cond.get("campo") or "").strip()
    op = str(cond.get("op") or "eq").strip().lower()
    esperado = cond.get("valor")
    actual = resolver_ruta_dato(contexto, campo, default=None)

    if op == "exists":
        existe = actual is not None and actual != "" and actual != []
        deseado = True if esperado is None else bool(esperado)
        ok = (existe == deseado)
        return ok, f"{campo} exists={existe}"

    if actual is None:
        return (op in ("ne", "not_contains", "not_in")), f"{campo}=None"

    if op == "eq":
        fa, fe = _a_float(actual), _a_float(esperado)
        ok = (fa == fe) if (fa is not None and fe is not None) else (str(actual).lower() == str(esperado).lower())
        return ok, f"{campo}({actual}) == {esperado}"

    if op == "ne":
        fa, fe = _a_float(actual), _a_float(esperado)
        ok = (fa != fe) if (fa is not None and fe is not None) else (str(actual).lower() != str(esperado).lower())
        return ok, f"{campo}({actual}) != {esperado}"

    if op in ("gt", "gte", "lt", "lte"):
        fa, fe = _a_float(actual), _a_float(esperado)
        if fa is None or fe is None:
            return False, f"{campo} no numerico para {op}"
        if op == "gt":
            ok = fa > fe
        elif op == "gte":
            ok = fa >= fe
        elif op == "lt":
            ok = fa < fe
        else:
            ok = fa <= fe
        return ok, f"{campo}({fa}) {op} {fe}"

    if op == "between":
        fa = _a_float(actual)
        if fa is None or not isinstance(esperado, (list, tuple)) or len(esperado) != 2:
            return False, f"{campo} between invalido"
        lo, hi = _a_float(esperado[0]), _a_float(esperado[1])
        if lo is None or hi is None:
            return False, f"{campo} rango no numerico"
        return (lo <= fa <= hi), f"{lo} <= {campo}({fa}) <= {hi}"

    if op == "contains":
        if isinstance(actual, (list, tuple, set)):
            ok = esperado in actual or str(esperado) in [str(x) for x in actual]
        else:
            ok = str(esperado) in str(actual)
        return ok, f"{campo} contains {esperado}"

    if op == "not_contains":
        if isinstance(actual, (list, tuple, set)):
            ok = esperado not in actual and str(esperado) not in [str(x) for x in actual]
        else:
            ok = str(esperado) not in str(actual)
        return ok, f"{campo} not_contains {esperado}"

    if op == "icontains":
        if isinstance(actual, (list, tuple, set)):
            esp_l = str(esperado).lower()
            ok = any(esp_l in str(x).lower() for x in actual)
        else:
            ok = str(esperado).lower() in str(actual).lower()
        return ok, f"{campo} icontains {esperado}"

    if op == "startswith":
        return str(actual).lower().startswith(str(esperado).lower()), f"{campo} startswith {esperado}"

    if op == "endswith":
        return str(actual).lower().endswith(str(esperado).lower()), f"{campo} endswith {esperado}"

    if op == "in":
        lista = esperado if isinstance(esperado, (list, tuple, set)) else [esperado]
        ok = str(actual).lower() in {str(x).lower() for x in lista}
        return ok, f"{campo}({actual}) in {lista}"

    if op == "not_in":
        lista = esperado if isinstance(esperado, (list, tuple, set)) else [esperado]
        ok = str(actual).lower() not in {str(x).lower() for x in lista}
        return ok, f"{campo}({actual}) not_in {lista}"

    if op == "regex":
        try:
            ok = bool(re.search(str(esperado), str(actual), re.IGNORECASE))
            return ok, f"{campo} =~ /{esperado}/"
        except re.error:
            return False, f"regex invalida: {esperado}"

    return False, f"operador desconocido: {op}"


def evaluar_arbol_condiciones(spec: Any, contexto: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Soporta 3 formatos de condiciones:
    1. Lista plana de condiciones -> AND implicito (ej. [{"campo": "payload.score", "op": "gte", "valor": 8}])
    2. Grupo logico recursivo -> {"logic": "AND"|"OR"|"NOT", "rules": [...]}
    3. Condicion atomica unica -> {"campo": ..., "op": ..., "valor": ...}
    """
    if not spec:
        return True, ["sin_condiciones"]

    if isinstance(spec, list):
        trazas: list[str] = []
        for item in spec:
            ok, tr = evaluar_arbol_condiciones(item, contexto)
            trazas.extend(tr)
            if not ok:
                return False, trazas
        return True, trazas

    if isinstance(spec, dict):
        if "logic" in spec and "rules" in spec:
            logica = str(spec.get("logic") or "AND").strip().upper()
            reglas = spec.get("rules") or []
            if not reglas:
                return True, ["grupo_vacio"]
            trazas = []
            if logica == "AND":
                for sub in reglas:
                    ok, tr = evaluar_arbol_condiciones(sub, contexto)
                    trazas.extend(tr)
                    if not ok:
                        return False, trazas
                return True, trazas
            if logica == "OR":
                for sub in reglas:
                    ok, tr = evaluar_arbol_condiciones(sub, contexto)
                    trazas.extend(tr)
                    if ok:
                        return True, trazas
                return False, trazas
            if logica == "NOT":
                ok_sub, tr = evaluar_arbol_condiciones(reglas[0], contexto)
                return (not ok_sub), [f"NOT({'; '.join(tr)})"]
            return False, [f"logica desconocida: {logica}"]

        ok, tr_single = evaluar_condicion_atomica(spec, contexto)
        return ok, [tr_single]

    return False, ["condicion_invalida"]


# ==================== MODELOS DE REGLA Y EJECUCION ====================
@dataclass(slots=True)
class ReglaWorkflow:
    id: int
    nombre: str
    activa: bool
    evento_disparador: str
    condiciones: Any
    acciones: list[dict[str, Any]]
    cooldown_seg: int = 60
    ejecuciones: int = 0
    ultima_ejecucion_ts: float = 0.0
    dedup_key_template: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "nombre": self.nombre,
            "activa": self.activa,
            "evento_disparador": self.evento_disparador,
            "condiciones": self.condiciones,
            "acciones": self.acciones,
            "cooldown_seg": self.cooldown_seg,
            "ejecuciones": self.ejecuciones,
            "ultima_ejecucion_ts": round(self.ultima_ejecucion_ts, 2),
        }


@dataclass(slots=True)
class ResultadoEjecucionRegla:
    regla_id: int
    regla_nombre: str
    topico: str
    matched: bool
    ejecutada: bool
    omitida_por: str = ""  # "" | inactiva | cooldown_regla | cooldown_entidad | anti_bucle | condiciones
    trazas_condiciones: list[str] = field(default_factory=list)
    resultados_acciones: list[ResultadoAccion] = field(default_factory=list)
    duracion_ms: float = 0.0
    ts_epoch: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "regla_id": self.regla_id,
            "regla_nombre": self.regla_nombre,
            "topico": self.topico,
            "matched": self.matched,
            "ejecutada": self.ejecutada,
            "omitida_por": self.omitida_por,
            "trazas": self.trazas_condiciones[:8],
            "acciones": [a.to_dict() for a in self.resultados_acciones],
            "duracion_ms": round(self.duracion_ms, 2),
            "ts_epoch": round(self.ts_epoch, 2),
        }


# ==================== PRESETS LISTOS PARA PRODUCCION ====================
PRESETS_WORKFLOWS: tuple[dict[str, Any], ...] = (
    {
        "nombre": "Ballena VIP ($250+ y Score 8+) -> Tarea Inmediata + Sonido",
        "activa": True,
        "evento_disparador": "crm.lead.nuevo",
        "cooldown_seg": 30,
        "condiciones": {
            "logic": "AND",
            "rules": [
                {"campo": "payload.score", "op": "gte", "valor": 8},
                {
                    "logic": "OR",
                    "rules": [
                        {"campo": "payload.presupuesto_num", "op": "gte", "valor": 250},
                        {"campo": "payload.prioridad_tag", "op": "icontains", "valor": "HIGH-TICKET"},
                    ],
                },
            ],
        },
        "acciones": [
            {
                "tipo": "crear_tarea_crm",
                "params": {
                    "titulo": "Atacar Ballena: {{payload.titulo|Lead VIP}}",
                    "descripcion": "Plataforma: {{payload.plataforma|N/A}} | Presupuesto: {{payload.presupuesto|$?}} | Link: {{payload.link|}}",
                    "prioridad": "critica",
                    "vence_en_horas": 2,
                },
            },
            {"tipo": "sonido_alerta", "params": {"tipo": "ballena"}},
            {
                "tipo": "log_evento",
                "params": {"nivel": "ok", "mensaje": "Ballena VIP #{{payload.lead_id|?}} priorizada automaticamente"},
            },
        ],
    },
    {
        "nombre": "Lead Contactado -> Programar Tarea Follow-Up 20h",
        "activa": True,
        "evento_disparador": "crm.lead.estado_cambiado",
        "cooldown_seg": 15,
        "condiciones": [
            {"campo": "payload.estado", "op": "eq", "valor": "contactado"},
        ],
        "acciones": [
            {
                "tipo": "crear_tarea_crm",
                "params": {
                    "titulo": "Follow-Up 20h: {{payload.titulo|Cliente}}",
                    "descripcion": "Enviar mensaje de seguimiento corto si no respondio aun.",
                    "prioridad": "alta",
                    "vence_en_horas": 20,
                },
            },
        ],
    },
    {
        "nombre": "Cliente Ganado -> Tarea Entrega/Factura + Backup Atomico DB",
        "activa": True,
        "evento_disparador": "crm.lead.estado_cambiado",
        "cooldown_seg": 60,
        "condiciones": [
            {"campo": "payload.estado", "op": "eq", "valor": "ganado"},
        ],
        "acciones": [
            {
                "tipo": "crear_tarea_crm",
                "params": {
                    "titulo": "Emitir Factura PDF y Entrega: {{payload.titulo|Proyecto}}",
                    "descripcion": "Monto pactado: ${{payload.ganancia_usd|0}} USD. Archivar entrega y pedir review.",
                    "prioridad": "alta",
                    "vence_en_horas": 12,
                },
            },
            {"tipo": "ejecutar_backup", "params": {"max_backups": 10}},
            {
                "tipo": "log_evento",
                "params": {"nivel": "ok", "mensaje": "Lead #{{payload.lead_id|?}} ganado (+${{payload.ganancia_usd|0}}) — Backup automatico OK"},
            },
        ],
    },
    {
        "nombre": "Circuit Breaker Abierto -> Log Critico de Dominio",
        "activa": True,
        "evento_disparador": "http.circuit.open",
        "cooldown_seg": 180,
        "condiciones": [],
        "acciones": [
            {
                "tipo": "log_evento",
                "params": {
                    "nivel": "warn",
                    "componente": "resiliencia",
                    "mensaje": "Circuit Breaker OPEN en {{payload.dominio}} ({{payload.cooldown_seg}}s | {{payload.motivo}})",
                },
            },
        ],
    },
    {
        "nombre": "Budget Cloud IA Agotado -> Aviso Fallback Ollama Local",
        "activa": True,
        "evento_disparador": "ai.budget.exceeded",
        "cooldown_seg": 600,
        "condiciones": [],
        "acciones": [
            {
                "tipo": "log_evento",
                "params": {
                    "nivel": "warn",
                    "componente": "ai_router",
                    "mensaje": "Cuota cloud diaria alcanzada ({{payload.usados_hoy}}/{{payload.limite}}) — enrutando a Ollama local",
                },
            },
        ],
    },
)


# ==================== MOTOR WORKFLOW ENGINE IFTTT ====================
class TitanWorkflowEngine:
    """
    Motor de Automatizacion Event-Driven (IFTTT) para TITAN-OS v16.0:
    - Escucha eventos en tiempo real desde TitanEventBus con matching por wildcards
    - Evalua arboles de condiciones AND/OR/NOT con 16 operadores
    - Aplica cooldown por regla + deduplicacion por entidad y proteccion anti-bucle
    - Persiste reglas en SQLite ('reglas_automatizacion') + historial de ejecuciones en RAM
    - Soporta simulacion Dry-Run completa sin efectos secundarios
    """

    def __init__(
        self,
        db: TitanDBEngine | None = None,
        bus: TitanEventBus | None = None,
        shield: TitanHTTPShield | None = None,
        logger: RotatingJSONLLogger | None = None,
        telemetry: TitanTelemetry | None = None,
        registry: ActionRegistry | None = None,
        auto_presets: bool = False,
    ) -> None:
        self._lock = threading.RLock()
        self.db = db or obtener_db_engine()
        self.bus = bus or obtener_event_bus()
        self.shield = shield or obtener_http_shield()
        self.logger = logger or obtener_logger()
        self.telemetry = telemetry or obtener_telemetry()
        self.registry = registry or ActionRegistry()

        self._reglas: dict[int, ReglaWorkflow] = {}
        self._entidad_cooldowns: dict[str, float] = {}
        self._historial: deque[ResultadoEjecucionRegla] = deque(maxlen=200)
        self._sub_id: str | None = None

        self.recargar_reglas()
        if auto_presets and not self._reglas:
            self.instalar_presets_defecto()

    def iniciar(self) -> str:
        with self._lock:
            if self._sub_id is not None:
                return self._sub_id
            self._sub_id = self.bus.suscribir("*", self.procesar_evento, asincrono=False)
            return self._sub_id

    def detener(self) -> None:
        with self._lock:
            if self._sub_id is not None:
                self.bus.desuscribir(self._sub_id)
                self._sub_id = None

    def recargar_reglas(self) -> int:
        rows = self.db.consultar_todos("SELECT * FROM reglas_automatizacion ORDER BY id ASC")
        nuevas: dict[int, ReglaWorkflow] = {}
        for r in rows:
            try:
                conds = json.loads(r.get("condiciones_json") or "[]")
            except Exception:
                conds = []
            try:
                accs = json.loads(r.get("acciones_json") or "[]")
                if not isinstance(accs, list):
                    accs = []
            except Exception:
                accs = []
            rid = int(r["id"])
            nuevas[rid] = ReglaWorkflow(
                id=rid,
                nombre=str(r["nombre"]),
                activa=bool(r.get("activa", 1)),
                evento_disparador=str(r.get("evento_disparador") or "*").strip().lower(),
                condiciones=conds,
                acciones=accs,
                cooldown_seg=max(0, int(r.get("cooldown_seg") or 0)),
                ejecuciones=int(r.get("ejecuciones") or 0),
                ultima_ejecucion_ts=float(r.get("ultima_ejecucion_ts") or 0.0),
            )
        with self._lock:
            self._reglas = nuevas
            return len(self._reglas)

    def crear_regla(
        self,
        nombre: str,
        evento_disparador: str,
        condiciones: Any,
        acciones: list[dict[str, Any]],
        *,
        activa: bool = True,
        cooldown_seg: int = 60,
    ) -> ReglaWorkflow:
        nom = str(nombre or "Regla sin nombre").strip()[:120]
        evt = str(evento_disparador or "*").strip().lower()[:80]
        c_json = json.dumps(condiciones if condiciones is not None else [], ensure_ascii=False)
        a_json = json.dumps(acciones or [], ensure_ascii=False)
        rid = self.db.ejecutar(
            """
            INSERT INTO reglas_automatizacion (nombre, activa, evento_disparador, condiciones_json, acciones_json, cooldown_seg)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (nom, 1 if activa else 0, evt, c_json, a_json, max(0, int(cooldown_seg))),
        )
        self.recargar_reglas()
        return self._reglas[rid]

    def actualizar_regla(self, regla_id: int, cambios: dict[str, Any]) -> ReglaWorkflow | None:
        with self._lock:
            reg = self._reglas.get(int(regla_id))
        if reg is None:
            return None
        nombre = str(cambios.get("nombre", reg.nombre)).strip()[:120]
        activa = bool(cambios.get("activa", reg.activa))
        evento = str(cambios.get("evento_disparador", reg.evento_disparador)).strip().lower()[:80]
        conds = cambios.get("condiciones", reg.condiciones)
        accs = cambios.get("acciones", reg.acciones)
        cd = max(0, int(cambios.get("cooldown_seg", reg.cooldown_seg)))

        self.db.ejecutar(
            """
            UPDATE reglas_automatizacion
            SET nombre = ?, activa = ?, evento_disparador = ?, condiciones_json = ?, acciones_json = ?, cooldown_seg = ?
            WHERE id = ?
            """,
            (
                nombre,
                1 if activa else 0,
                evento,
                json.dumps(conds, ensure_ascii=False),
                json.dumps(accs, ensure_ascii=False),
                cd,
                int(regla_id),
            ),
        )
        self.recargar_reglas()
        return self._reglas.get(int(regla_id))

    def toggle_regla(self, regla_id: int, activa: bool | None = None) -> ReglaWorkflow | None:
        with self._lock:
            reg = self._reglas.get(int(regla_id))
        if reg is None:
            return None
        nuevo = (not reg.activa) if activa is None else bool(activa)
        return self.actualizar_regla(regla_id, {"activa": nuevo})

    def eliminar_regla(self, regla_id: int) -> bool:
        n = self.db.ejecutar("DELETE FROM reglas_automatizacion WHERE id = ?", (int(regla_id),))
        self.recargar_reglas()
        return n > 0

    def instalar_presets_defecto(self) -> int:
        existentes = {r.nombre for r in self.listar_reglas()}
        creadas = 0
        for p in PRESETS_WORKFLOWS:
            if p["nombre"] in existentes:
                continue
            self.crear_regla(
                nombre=p["nombre"],
                evento_disparador=p["evento_disparador"],
                condiciones=p["condiciones"],
                acciones=p["acciones"],
                activa=bool(p.get("activa", True)),
                cooldown_seg=int(p.get("cooldown_seg", 60)),
            )
            creadas += 1
        return creadas

    def listar_reglas(self) -> list[ReglaWorkflow]:
        with self._lock:
            return list(self._reglas.values())

    def _construir_variables(self, evt: EventoSistema, regla: ReglaWorkflow) -> dict[str, Any]:
        return {
            "seq_id": evt.seq_id,
            "event_id": evt.event_id,
            "topico": evt.topico,
            "origen": evt.origen,
            "nivel": evt.nivel,
            "ts_iso": evt.ts_iso,
            "hora": datetime.now().strftime("%H:%M:%S"),
            "payload": evt.payload,
            "regla": {"id": regla.id, "nombre": regla.nombre},
        }

    def _evaluar_una_regla(
        self,
        regla: ReglaWorkflow,
        evt: EventoSistema,
        dry_run: bool = False,
    ) -> ResultadoEjecucionRegla:
        t0 = time.perf_counter()
        profundidad = int(evt.payload.get("_wf_depth", 0)) if isinstance(evt.payload, dict) else 0
        parent_rule = evt.payload.get("_wf_parent_rule") if isinstance(evt.payload, dict) else None

        if not regla.activa and not dry_run:
            return ResultadoEjecucionRegla(regla.id, regla.nombre, evt.topico, False, False, omitida_por="inactiva")

        # Anti-bucle: nunca re-disparar la misma regla ni superar profundidad 3
        if profundidad >= 3 or (parent_rule is not None and int(parent_rule) == regla.id):
            return ResultadoEjecucionRegla(regla.id, regla.nombre, evt.topico, False, False, omitida_por="anti_bucle")

        variables = self._construir_variables(evt, regla)
        ok_cond, trazas = evaluar_arbol_condiciones(regla.condiciones, variables)
        if not ok_cond:
            return ResultadoEjecucionRegla(
                regla.id, regla.nombre, evt.topico, False, False,
                omitida_por="condiciones", trazas_condiciones=trazas,
                duracion_ms=(time.perf_counter() - t0) * 1000.0,
            )

        ahora = time.time()
        if not dry_run and regla.cooldown_seg > 0:
            with self._lock:
                # Si el evento trae lead_id/dominio especifico, aplicamos cooldown por entidad para no perder leads paralelos
                ent_id = (
                    resolver_ruta_dato(variables, "payload.lead_id")
                    or resolver_ruta_dato(variables, "payload.id")
                    or resolver_ruta_dato(variables, "payload.dominio")
                )
                if ent_id is not None:
                    clave_ent = f"{regla.id}:{ent_id}"
                    if self._entidad_cooldowns.get(clave_ent, 0.0) > ahora:
                        return ResultadoEjecucionRegla(
                            regla.id, regla.nombre, evt.topico, True, False,
                            omitida_por="cooldown_entidad", trazas_condiciones=trazas,
                        )
                    self._entidad_cooldowns[clave_ent] = ahora + regla.cooldown_seg
                    if len(self._entidad_cooldowns) > 1000:
                        self._entidad_cooldowns = {k: v for k, v in self._entidad_cooldowns.items() if v > ahora}
                else:
                    if (ahora - regla.ultima_ejecucion_ts) < regla.cooldown_seg:
                        return ResultadoEjecucionRegla(
                            regla.id, regla.nombre, evt.topico, True, False,
                            omitida_por="cooldown_regla", trazas_condiciones=trazas,
                        )

        ctx_acc = ContextoAccion(
            regla_id=regla.id,
            regla_nombre=regla.nombre,
            evento=evt,
            variables=variables,
            db=self.db,
            bus=self.bus,
            shield=self.shield,
            logger=self.logger,
            dry_run=dry_run,
            profundidad=profundidad,
        )

        resultados_acc = [self.registry.ejecutar(acc, ctx_acc) for acc in regla.acciones]
        dur_ms = (time.perf_counter() - t0) * 1000.0

        if not dry_run:
            with self._lock:
                regla.ejecuciones += 1
                regla.ultima_ejecucion_ts = ahora
            try:
                self.db.ejecutar(
                    "UPDATE reglas_automatizacion SET ejecuciones = ejecuciones + 1, ultima_ejecucion_ts = ? WHERE id = ?",
                    (ahora, regla.id),
                )
            except Exception:
                pass
            self.telemetry.registrar_latencia(
                "workflow",
                f"regla_{regla.id}",
                dur_ms,
                exito=all(r.ok for r in resultados_acc),
            )

        res = ResultadoEjecucionRegla(
            regla_id=regla.id,
            regla_nombre=regla.nombre,
            topico=evt.topico,
            matched=True,
            ejecutada=True,
            trazas_condiciones=trazas,
            resultados_acciones=resultados_acc,
            duracion_ms=round(dur_ms, 2),
        )
        if not dry_run:
            with self._lock:
                self._historial.append(res)
        return res

    def procesar_evento(self, evt: EventoSistema) -> list[ResultadoEjecucionRegla]:
        # Nunca procesar logs propios para evitar tormenta de eventos
        if evt.topico.startswith("log."):
            return []
        with self._lock:
            candidatas = [
                r for r in self._reglas.values()
                if r.activa and fnmatch.fnmatchcase(evt.topico, r.evento_disparador)
            ]
        resultados: list[ResultadoEjecucionRegla] = []
        for reg in candidatas:
            r_ev = self._evaluar_una_regla(reg, evt, dry_run=False)
            if r_ev.matched or r_ev.omitida_por in ("cooldown_regla", "cooldown_entidad", "anti_bucle"):
                resultados.append(r_ev)
        return resultados

    def simular_evento(self, topico: str, payload: dict[str, Any], origen: str = "simulador", nivel: str = "info") -> list[dict[str, Any]]:
        """Ejecuta Dry-Run de todas las reglas que coinciden con el topico sin producir efectos reales."""
        evt_sim = EventoSistema(
            seq_id=0,
            event_id="sim",
            topico=str(topico).strip().lower(),
            origen=origen,
            nivel=nivel,
            payload=dict(payload or {}),
        )
        with self._lock:
            candidatas = [
                r for r in self._reglas.values()
                if fnmatch.fnmatchcase(evt_sim.topico, r.evento_disparador)
            ]
        return [self._evaluar_una_regla(reg, evt_sim, dry_run=True).to_dict() for reg in candidatas]

    def historial_ejecuciones(self, limite: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._historial)
        return [x.to_dict() for x in reversed(items[-max(1, limite):])]

    def estado_resumen(self) -> dict[str, Any]:
        reglas = self.listar_reglas()
        return {
            "activo": self._sub_id is not None,
            "total_reglas": len(reglas),
            "reglas_activas": sum(1 for r in reglas if r.activa),
            "acciones_disponibles": self.registry.disponibles(),
            "operadores_disponibles": sorted(OPERADORES_VALIDOS),
            "reglas": [r.to_dict() for r in reglas],
            "historial": self.historial_ejecuciones(25),
        }


_WF_LOCK = threading.Lock()
_WF_SINGLETON: TitanWorkflowEngine | None = None


def obtener_workflow_engine(iniciar_auto: bool = True) -> TitanWorkflowEngine:
    global _WF_SINGLETON
    with _WF_LOCK:
        if _WF_SINGLETON is None:
            _WF_SINGLETON = TitanWorkflowEngine(auto_presets=True)
            if iniciar_auto:
                _WF_SINGLETON.iniciar()
        return _WF_SINGLETON