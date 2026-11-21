from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import platform
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from titan_core.db_engine import ROOT_DIR, TitanDBEngine, obtener_db_engine
from titan_core.event_bus import TitanEventBus, obtener_event_bus

TIERS_VALIDOS = {"starter", "pro", "agency", "lifetime", "trial"}
SECRET_FILE_DEFAULT = os.path.join(ROOT_DIR, ".titan_license_secret")


def _b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64u_decode(s: str) -> bytes:
    pad = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("ascii"))


def obtener_hwid_local() -> str:
    crudo = "|".join((
        platform.system(),
        platform.node(),
        platform.machine(),
        str(uuid.getnode()),
    ))
    return hashlib.sha256(crudo.encode("utf-8", errors="ignore")).hexdigest()[:16].upper()


@dataclass(slots=True)
class VerificacionLicencia:
    valida: bool
    motivo: str
    licencia_id: str = ""
    producto_slug: str = ""
    cliente: str = ""
    tier: str = ""
    seats: int = 1
    expira_epoch: int = 0
    dias_restantes: int | None = None
    hwid_requerido: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "valida": self.valida,
            "motivo": self.motivo,
            "licencia_id": self.licencia_id,
            "producto_slug": self.producto_slug,
            "cliente": self.cliente,
            "tier": self.tier,
            "seats": self.seats,
            "expira_epoch": self.expira_epoch,
            "dias_restantes": self.dias_restantes,
            "hwid_requerido": self.hwid_requerido,
        }


class TitanLicenseEngine:
    """
    Motor criptografico offline de licencias HMAC-SHA256 (formato ZT1.<payload>.<sig>):
    - Clave derivada independiente por producto: HMAC(master_secret, product_slug)
    - Soporte de tiers, asientos (seats), expiracion, HWID opcional y revocacion en SQLite
    - Generador de modulo embebible 'license_guard.py' (cero dependencias externas)
    """

    def __init__(
        self,
        db: TitanDBEngine | None = None,
        bus: TitanEventBus | None = None,
        master_secret: str | None = None,
        secret_file: str | None = None,
        usar_sqlite: bool = True,
    ) -> None:
        self._lock = threading.RLock()
        self.usar_sqlite = usar_sqlite
        self.db = db if db is not None else (obtener_db_engine() if usar_sqlite else None)
        self.bus = bus if bus is not None else obtener_event_bus()
        self._secret_file = os.path.abspath(secret_file or SECRET_FILE_DEFAULT)
        self._master_secret = self._resolver_master_secret(master_secret)
        self._esquema_ok = False
        if self.usar_sqlite and self.db is not None:
            self._asegurar_esquema()

    def _resolver_master_secret(self, override: str | None) -> bytes:
        if override and override.strip():
            return override.strip().encode("utf-8")
        env_sec = (os.getenv("TITAN_LICENSE_SECRET") or "").strip()
        if env_sec:
            return env_sec.encode("utf-8")
        if os.path.isfile(self._secret_file):
            try:
                with open(self._secret_file, "r", encoding="utf-8") as f:
                    txt = f.read().strip()
                if len(txt) >= 32:
                    return txt.encode("utf-8")
            except OSError:
                pass
        generado = secrets.token_hex(32)
        try:
            os.makedirs(os.path.dirname(self._secret_file) or ".", exist_ok=True)
            with open(self._secret_file, "w", encoding="utf-8", newline="\n") as f:
                f.write(generado + "\n")
        except OSError:
            pass
        return generado.encode("utf-8")

    def _asegurar_esquema(self) -> None:
        if self._esquema_ok or self.db is None:
            return
        with self.db.transaccion() as tx:
            tx.execute(
                """
                CREATE TABLE IF NOT EXISTS licencias_emitidas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    licencia_id TEXT UNIQUE NOT NULL,
                    producto_slug TEXT NOT NULL,
                    cliente TEXT NOT NULL,
                    tier TEXT NOT NULL DEFAULT 'pro',
                    seats INTEGER DEFAULT 1,
                    hwid TEXT DEFAULT '',
                    expira_epoch INTEGER DEFAULT 0,
                    clave_licencia TEXT NOT NULL,
                    revocada INTEGER DEFAULT 0,
                    motivo_revocacion TEXT DEFAULT '',
                    notas TEXT DEFAULT '',
                    creado_ts DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            tx.execute("CREATE INDEX IF NOT EXISTS idx_lic_prod ON licencias_emitidas(producto_slug, revocada)")
            tx.execute("CREATE INDEX IF NOT EXISTS idx_lic_cli ON licencias_emitidas(cliente)")
        self._esquema_ok = True

    def derivar_clave_producto(self, producto_slug: str) -> str:
        slug = str(producto_slug or "default").strip().lower()
        return hmac.new(self._master_secret, f"zt-prod-key:{slug}".encode("utf-8"), hashlib.sha256).hexdigest()

    def emitir_licencia(
        self,
        producto_slug: str,
        cliente: str,
        *,
        tier: str = "pro",
        dias_validez: int = 0,
        seats: int = 1,
        hwid: str = "",
        notas: str = "",
        expira_epoch_override: int | None = None,
    ) -> dict[str, Any]:
        slug = str(producto_slug or "").strip().lower()
        if not slug:
            raise ValueError("producto_slug es obligatorio")
        cli = str(cliente or "customer").strip()[:120]
        tier_c = str(tier or "pro").strip().lower()
        if tier_c not in TIERS_VALIDOS:
            tier_c = "pro"

        ahora = int(time.time())
        if expira_epoch_override is not None:
            exp_ep = int(expira_epoch_override)
        elif dias_validez and int(dias_validez) > 0:
            exp_ep = ahora + int(dias_validez) * 86400
        else:
            exp_ep = 0  # Lifetime

        lic_id = f"LIC-{uuid.uuid4().hex[:10].upper()}"
        hwid_c = str(hwid or "").strip().upper()[:32]
        seats_c = max(1, min(999, int(seats or 1)))

        payload = {
            "v": 1,
            "kid": lic_id,
            "pid": slug,
            "cid": cli,
            "tier": tier_c,
            "seats": seats_c,
            "iat": ahora,
            "exp": exp_ep,
            "hwid": hwid_c,
        }
        payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode("utf-8")
        payload_b64 = _b64u_encode(payload_bytes)

        prod_key = self.derivar_clave_producto(slug).encode("utf-8")
        sig_raw = hmac.new(prod_key, payload_b64.encode("ascii"), hashlib.sha256).digest()[:18]
        sig_b64 = _b64u_encode(sig_raw)
        clave_final = f"ZT1.{payload_b64}.{sig_b64}"

        if self.usar_sqlite and self.db is not None:
            self._asegurar_esquema()
            self.db.ejecutar(
                """
                INSERT INTO licencias_emitidas (
                    licencia_id, producto_slug, cliente, tier, seats, hwid,
                    expira_epoch, clave_licencia, revocada, notas
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (lic_id, slug, cli, tier_c, seats_c, hwid_c, exp_ep, clave_final, str(notas or "")[:300]),
            )

        res = {
            "licencia_id": lic_id,
            "producto_slug": slug,
            "cliente": cli,
            "tier": tier_c,
            "seats": seats_c,
            "hwid": hwid_c,
            "expira_epoch": exp_ep,
            "expira_iso": datetime.fromtimestamp(exp_ep, tz=timezone.utc).strftime("%Y-%m-%d") if exp_ep > 0 else "LIFETIME",
            "clave_licencia": clave_final,
        }
        if self.bus is not None:
            self.bus.publicar(
                "factory.licencia.emitida",
                {"licencia_id": lic_id, "producto_slug": slug, "cliente": cli, "tier": tier_c},
                origen="license_engine",
                nivel="ok",
            )
        return res

    def verificar_licencia(
        self,
        clave_licencia: str,
        producto_slug: str,
        *,
        hwid_actual: str = "",
        comprobar_revocacion: bool = True,
        ahora_epoch: int | None = None,
    ) -> VerificacionLicencia:
        raw = (clave_licencia or "").strip()
        slug = str(producto_slug or "").strip().lower()
        partes = raw.split(".")
        if len(partes) != 3 or partes[0] != "ZT1":
            return VerificacionLicencia(False, "Formato de licencia invalido (esperado ZT1.<payload>.<sig>)")

        payload_b64, sig_b64 = partes[1], partes[2]
        prod_key = self.derivar_clave_producto(slug).encode("utf-8")
        esperada = _b64u_encode(hmac.new(prod_key, payload_b64.encode("ascii"), hashlib.sha256).digest()[:18])
        if not hmac.compare_digest(sig_b64, esperada):
            return VerificacionLicencia(False, "Firma criptografica invalida o licencia de otro producto")

        try:
            data = json.loads(_b64u_decode(payload_b64).decode("utf-8"))
        except Exception:
            return VerificacionLicencia(False, "Payload de licencia corrupto")

        if str(data.get("pid") or "").lower() != slug:
            return VerificacionLicencia(False, f"Licencia emitida para '{data.get('pid')}', no para '{slug}'")

        lic_id = str(data.get("kid") or "")
        cli = str(data.get("cid") or "")
        tier = str(data.get("tier") or "pro")
        seats = int(data.get("seats") or 1)
        exp_ep = int(data.get("exp") or 0)
        hwid_req = str(data.get("hwid") or "").strip().upper()
        now = int(time.time()) if ahora_epoch is None else int(ahora_epoch)

        if comprobar_revocacion and self.usar_sqlite and self.db is not None and lic_id:
            self._asegurar_esquema()
            row = self.db.consultar_uno(
                "SELECT revocada, motivo_revocacion FROM licencias_emitidas WHERE licencia_id = ?",
                (lic_id,),
            )
            if row and int(row.get("revocada") or 0) == 1:
                mot = str(row.get("motivo_revocacion") or "revocada por administrador")
                return VerificacionLicencia(
                    False, f"Licencia revocada ({mot})",
                    licencia_id=lic_id, producto_slug=slug, cliente=cli, tier=tier,
                )

        dias_rest: int | None = None
        if exp_ep > 0:
            if now > exp_ep:
                return VerificacionLicencia(
                    False, "Licencia expirada",
                    licencia_id=lic_id, producto_slug=slug, cliente=cli, tier=tier,
                    expira_epoch=exp_ep, dias_restantes=0,
                )
            dias_rest = max(0, int((exp_ep - now) // 86400))

        if hwid_req:
            hw_check = (hwid_actual or "").strip().upper()
            if not hw_check or not hmac.compare_digest(hwid_req, hw_check):
                return VerificacionLicencia(
                    False, "HWID de maquina no autorizado para esta licencia",
                    licencia_id=lic_id, producto_slug=slug, cliente=cli, tier=tier,
                    expira_epoch=exp_ep, hwid_requerido=hwid_req,
                )

        return VerificacionLicencia(
            True, "Licencia valida",
            licencia_id=lic_id, producto_slug=slug, cliente=cli, tier=tier,
            seats=seats, expira_epoch=exp_ep, dias_restantes=dias_rest, hwid_requerido=hwid_req,
        )

    def revocar_licencia(self, licencia_id: str, motivo: str = "revocada") -> bool:
        if not self.usar_sqlite or self.db is None:
            return False
        self._asegurar_esquema()
        n = self.db.ejecutar(
            "UPDATE licencias_emitidas SET revocada = 1, motivo_revocacion = ? WHERE licencia_id = ?",
            (str(motivo or "revocada")[:200], str(licencia_id).strip()),
        )
        if n > 0 and self.bus is not None:
            self.bus.publicar("factory.licencia.revocada", {"licencia_id": licencia_id, "motivo": motivo}, origen="license_engine", nivel="warn")
        return n > 0

    def listar_licencias(self, producto_slug: str = "", solo_activas: bool = False, limite: int = 100) -> list[dict[str, Any]]:
        if not self.usar_sqlite or self.db is None:
            return []
        self._asegurar_esquema()
        where = ["1=1"]
        params: list[Any] = []
        if producto_slug.strip():
            where.append("lower(producto_slug) = ?")
            params.append(producto_slug.strip().lower())
        if solo_activas:
            where.append("revocada = 0")
        params.append(max(1, min(300, int(limite))))
        return self.db.consultar_todos(
            f"SELECT * FROM licencias_emitidas WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT ?",
            params,
        )

    def generar_modulo_license_guard(self, producto_slug: str, nombre_producto: str = "") -> str:
        """
        Genera un archivo 'license_guard.py' 100% autonomo (solo stdlib) para incrustar en el .ZIP comercial.
        Verifica firmas HMAC-SHA256 offline sin exponer la clave maestra global.
        """
        slug = str(producto_slug).strip().lower()
        prod_key = self.derivar_clave_producto(slug)
        nom_vis = (nombre_producto or slug).replace('"', "'")
        return f'''"""Offline License Verifier for {nom_vis} (ZeroTouch TITAN Factory v16)."""
import base64
import hashlib
import hmac
import json
import os
import platform
import sys
import time
import uuid

PRODUCT_SLUG = "{slug}"
PRODUCT_VERIFY_KEY = "{prod_key}"


def _b64u_decode(s: str) -> bytes:
    pad = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("ascii"))


def _b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def get_machine_hwid() -> str:
    raw = "|".join((platform.system(), platform.node(), platform.machine(), str(uuid.getnode())))
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:16].upper()


def _find_license_key() -> str:
    for env_name in ("PRODUCT_LICENSE_KEY", "WHOP_LICENSE_KEY", "LICENSE_KEY"):
        val = (os.getenv(env_name) or "").strip()
        if val:
            return val
    base_dir = os.path.dirname(os.path.abspath(__file__))
    key_file = os.path.join(base_dir, "license.key")
    if os.path.isfile(key_file):
        try:
            with open(key_file, "r", encoding="utf-8") as f:
                txt = f.read().strip()
            if txt:
                return txt
        except OSError:
            pass
    cfg_file = os.path.join(base_dir, "config.json")
    if os.path.isfile(cfg_file):
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            val = str(cfg.get("license_key") or "").strip()
            if val and not val.startswith("PASTE_"):
                return val
        except Exception:
            pass
    return ""


def verify_license(key: str | None = None) -> tuple[bool, dict]:
    token = (key if key is not None else _find_license_key()).strip()
    if not token:
        return False, {{"error": "Missing license key. Set license_key in config.json, license.key, or PRODUCT_LICENSE_KEY env."}}
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != "ZT1":
        return False, {{"error": "Invalid license key format."}}
    payload_b64, sig_b64 = parts[1], parts[2]
    expected = _b64u_encode(hmac.new(PRODUCT_VERIFY_KEY.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest()[:18])
    if not hmac.compare_digest(sig_b64, expected):
        return False, {{"error": "Invalid license signature."}}
    try:
        data = json.loads(_b64u_decode(payload_b64).decode("utf-8"))
    except Exception:
        return False, {{"error": "Corrupted license payload."}}
    if str(data.get("pid") or "").lower() != PRODUCT_SLUG:
        return False, {{"error": "License does not match this product."}}
    exp = int(data.get("exp") or 0)
    if exp > 0 and int(time.time()) > exp:
        return False, {{"error": "License expired."}}
    hwid_req = str(data.get("hwid") or "").strip().upper()
    if hwid_req and not hmac.compare_digest(hwid_req, get_machine_hwid()):
        return False, {{"error": f"License locked to another machine (local HWID: {{get_machine_hwid()}})."}}
    return True, data


def require_valid_license() -> dict:
    ok, info = verify_license()
    if not ok:
        print(f"[LICENSE ERROR] {{info.get('error', 'Unauthorized')}}", file=sys.stderr)
        sys.exit(42)
    return info
'''


_LIC_LOCK = threading.Lock()
_LIC_SINGLETON: TitanLicenseEngine | None = None


def obtener_license_engine() -> TitanLicenseEngine:
    global _LIC_SINGLETON
    with _LIC_LOCK:
        if _LIC_SINGLETON is None:
            _LIC_SINGLETON = TitanLicenseEngine()
        return _LIC_SINGLETON