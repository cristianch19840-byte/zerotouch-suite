from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import re
import secrets
import shutil
import sqlite3
import struct
import tarfile
import tempfile
import time
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from titan_core.code_sanitizer import PATRONES_SECRETO
from titan_core.db_engine import ROOT_DIR, TitanDBEngine, obtener_db_engine
from titan_core.event_bus import TitanEventBus, obtener_event_bus

VAULT_MAGIC = b"ZTV1"
VAULT_KEY_FILE = os.path.join(ROOT_DIR, ".titan_vault_key")
DEFAULT_VAULT_DIR = os.path.join(ROOT_DIR, "vault_backups")

CARPETAS_IGNORAR_SCAN = {
    ".git", ".venv", "venv", "__pycache__", "node_modules", "backups",
    "vault_backups", "logs", "productos_whop", "entregas_clientes",
    ".titan_snapshots", ".pytest_cache", ".mypy_cache",
}

EXTENSIONES_SCAN = {".py", ".js", ".ts", ".json", ".yml", ".yaml", ".md", ".bat", ".sh", ".html", ".css", ".txt"}

ENTRADAS_GITIGNORE_CRITICAS = (
    ".env",
    "estado_radar_v4.db",
    ".titan_license_secret",
    ".titan_vault_key",
    "vault_backups/",
    "logs/",
)

REGEX_FALSO_POSITIVO_SECRETO = re.compile(
    r"(?:FAKE|DUMMY|EXAMPLE|TEST_SECRET|PASTE_|YOUR_|1234567890abcdef|ABCDEFGHIJKLMNOP)",
    re.IGNORECASE,
)


# ==================== 1. AUDITOR DE SEGURIDAD Y HARDENING DEL REPOSITORIO ====================
@dataclass(slots=True)
class HallazgoSeguridad:
    codigo: str
    severidad: str  # critico | alto | medio | bajo | info
    archivo: str
    linea: int
    descripcion: str
    recomendacion: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "codigo": self.codigo,
            "severidad": self.severidad,
            "archivo": self.archivo,
            "linea": self.linea,
            "descripcion": self.descripcion,
            "recomendacion": self.recomendacion,
        }


@dataclass(slots=True)
class ReporteSeguridad:
    score_0_100: int
    grado: str
    archivos_escaneados: int
    criticos: int
    altos: int
    medios: int
    bajos: int
    hallazgos: list[HallazgoSeguridad] = field(default_factory=list)
    checks_ok: list[str] = field(default_factory=list)
    duracion_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "score_0_100": self.score_0_100,
            "grado": self.grado,
            "archivos_escaneados": self.archivos_escaneados,
            "resumen": {
                "criticos": self.criticos,
                "altos": self.altos,
                "medios": self.medios,
                "bajos": self.bajos,
            },
            "checks_ok": self.checks_ok,
            "hallazgos": [h.to_dict() for h in self.hallazgos],
            "duracion_ms": round(self.duracion_ms, 2),
        }


class SecurityAuditor:
    """
    Auditor forense de seguridad para ZeroTouch TITAN-OS v16:
    - Escanea el arbol de codigo buscando secretos reales filtrados (API keys, tokens, webhooks)
    - Verifica reglas criticas de .gitignore para evitar fugas a GitHub
    - Comprueba postura de autenticacion API, configuracion .env e integridad SQLite WAL
    - Calcula Security Score 0..100 con grado A+/A/B/C/F
    """

    def __init__(self, root_dir: str | None = None, db: TitanDBEngine | None = None) -> None:
        self.root_dir = os.path.abspath(root_dir or ROOT_DIR)
        self.db = db

    def _escanear_secretos_repo(self, max_bytes_archivo: int = 512_000) -> tuple[int, list[HallazgoSeguridad]]:
        escaneados = 0
        hallazgos: list[HallazgoSeguridad] = []

        for dirpath, dirnames, filenames in os.walk(self.root_dir):
            dirnames[:] = [d for d in dirnames if d not in CARPETAS_IGNORAR_SCAN and not d.startswith(".venv")]
            for fn in filenames:
                if fn.startswith(".env") or fn.startswith(".titan_"):
                    continue
                ext = os.path.splitext(fn)[1].lower()
                if ext not in EXTENSIONES_SCAN:
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, self.root_dir).replace("\\", "/")
                try:
                    if os.path.getsize(full) > max_bytes_archivo:
                        continue
                    with open(full, "r", encoding="utf-8", errors="ignore") as f:
                        contenido = f.read()
                except OSError:
                    continue

                escaneados += 1
                # Omitir archivos de test que contienen patrones sinteticos intencionales
                if os.path.basename(rel).startswith("test_"):
                    continue

                for idx, linea in enumerate(contenido.splitlines(), 1):
                    if not linea.strip() or REGEX_FALSO_POSITIVO_SECRETO.search(linea):
                        continue
                    for cod_sec, desc_sec, rx in PATRONES_SECRETO:
                        if rx.search(linea):
                            hallazgos.append(HallazgoSeguridad(
                                codigo=f"LEAK_{cod_sec}",
                                severidad="critico",
                                archivo=rel,
                                linea=idx,
                                descripcion=f"Posible {desc_sec} hardcodeado en el repositorio",
                                recomendacion="Mueve esta credencial a .env y rotala inmediatamente.",
                            ))
        return escaneados, hallazgos

    def _verificar_gitignore(self) -> tuple[list[HallazgoSeguridad], list[str]]:
        hallazgos: list[HallazgoSeguridad] = []
        ok: list[str] = []
        gi_path = os.path.join(self.root_dir, ".gitignore")
        if not os.path.isfile(gi_path):
            hallazgos.append(HallazgoSeguridad(
                "NO_GITIGNORE", "critico", ".gitignore", 0,
                "Falta archivo .gitignore en la raiz del proyecto",
                "Crea .gitignore protegiendo .env, *.db, .titan_* y vault_backups/.",
            ))
            return hallazgos, ok

        with open(gi_path, "r", encoding="utf-8", errors="ignore") as f:
            lineas = {ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")}

        faltantes = [e for e in ENTRADAS_GITIGNORE_CRITICAS if e not in lineas and e.rstrip("/") not in lineas]
        if faltantes:
            hallazgos.append(HallazgoSeguridad(
                "GITIGNORE_INCOMPLETO", "alto", ".gitignore", 0,
                f"Faltan exclusiones criticas en .gitignore: {', '.join(faltantes)}",
                "Agrega todas las rutas sensibles a .gitignore antes de hacer git push.",
            ))
        else:
            ok.append(".gitignore protege .env, DB, claves de licencia, vault y logs")
        return hallazgos, ok

    def _verificar_postura_runtime(self) -> tuple[list[HallazgoSeguridad], list[str]]:
        hallazgos: list[HallazgoSeguridad] = []
        ok: list[str] = []

        # 1. Verificar config.json bien formado y sin claves privadas
        cfg_path = os.path.join(self.root_dir, "config.json")
        if os.path.isfile(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    raw_cfg = f.read()
                json.loads(raw_cfg)
                ok.append("config.json valido (JSON integro)")
            except Exception as e:
                hallazgos.append(HallazgoSeguridad(
                    "CONFIG_CORRUPTO", "alto", "config.json", 0,
                    f"config.json no es JSON valido: {e}",
                    "Repara o restaura config.json desde un backup.",
                ))

        # 2. Verificar TITAN_API_TOKEN recomendado si se expone en LAN
        tok = (os.getenv("TITAN_API_TOKEN") or "").strip()
        if not tok:
            hallazgos.append(HallazgoSeguridad(
                "API_TOKEN_OPCIONAL", "bajo", ".env", 0,
                "TITAN_API_TOKEN no definido (aceptable en 127.0.0.1 local, requerido si expones en red)",
                "Define TITAN_API_TOKEN=<32+ chars> en .env si accedes desde otro dispositivo.",
            ))
        elif len(tok) < 16:
            hallazgos.append(HallazgoSeguridad(
                "API_TOKEN_DEBIL", "medio", ".env", 0,
                "TITAN_API_TOKEN demasiado corto (<16 caracteres)",
                "Genera un token aleatorio de al menos 32 caracteres.",
            ))
        else:
            ok.append("TITAN_API_TOKEN robusto configurado")

        # 3. Verificar integridad DB SQLite WAL si existe
        if self.db is not None:
            try:
                salud = self.db.verificar_salud()
                if salud.integridad_ok:
                    ok.append(f"SQLite WAL integro (esquema v{salud.version_esquema}, {len(salud.tablas)} tablas)")
                else:
                    hallazgos.append(HallazgoSeguridad(
                        "DB_INTEGRIDAD", "critico", os.path.basename(self.db.db_path), 0,
                        f"PRAGMA quick_check fallo: {salud.detalle_integridad}",
                        "Restaura el ultimo backup verificado inmediatamente.",
                    ))
            except Exception as e:
                hallazgos.append(HallazgoSeguridad("DB_ERROR", "alto", "sqlite", 0, str(e)[:160]))

        return hallazgos, ok

    def auditar(self) -> ReporteSeguridad:
        t0 = time.perf_counter()
        esc, h_sec = self._escanear_secretos_repo()
        h_gi, ok_gi = self._verificar_gitignore()
        h_rt, ok_rt = self._verificar_postura_runtime()

        todos = h_sec + h_gi + h_rt
        checks_ok = ok_gi + ok_rt
        if not h_sec:
            checks_ok.insert(0, f"0 secretos filtrados en {esc} archivo(s) escaneados")

        crit = sum(1 for h in todos if h.severidad == "critico")
        alt = sum(1 for h in todos if h.severidad == "alto")
        med = sum(1 for h in todos if h.severidad == "medio")
        baj = sum(1 for h in todos if h.severidad == "bajo")

        score = max(0, min(100, 100 - (crit * 35) - (alt * 15) - (med * 7) - (baj * 2)))
        grado = "A+" if score >= 96 else ("A" if score >= 88 else ("B" if score >= 75 else ("C" if score >= 60 else "F")))

        return ReporteSeguridad(
            score_0_100=score,
            grado=grado,
            archivos_escaneados=esc,
            criticos=crit,
            altos=alt,
            medios=med,
            bajos=baj,
            hallazgos=todos,
            checks_ok=checks_ok,
            duracion_ms=(time.perf_counter() - t0) * 1000.0,
        )


# ==================== 2. VAULT DE BACKUPS CIFRADOS AUTENTICADOS (STDLIB PURO) ====================
def _derivar_claves_vault(passphrase: bytes, salt: bytes, iteraciones: int = 120_000) -> tuple[bytes, bytes]:
    """Deriva 64 bytes via PBKDF2-HMAC-SHA256 -> (enc_key 32B, mac_key 32B) independientes."""
    material = hashlib.pbkdf2_hmac("sha256", passphrase, salt, iteraciones, dklen=64)
    return material[:32], material[32:]


def _xor_keystream_sha256_ctr(data: bytes, enc_key: bytes, nonce: bytes) -> bytes:
    """Cifrado de flujo CTR usando bloques SHA-256(enc_key || nonce || counter_be64)."""
    out = bytearray(len(data))
    n = len(data)
    pos = 0
    ctr = 0
    while pos < n:
        bloque_ks = hashlib.sha256(enc_key + nonce + struct.pack(">Q", ctr)).digest()
        fin = min(n, pos + 32)
        for i in range(fin - pos):
            out[pos + i] = data[pos + i] ^ bloque_ks[i]
        pos = fin
        ctr += 1
    return bytes(out)


def cifrar_blob_autenticado(plaintext: bytes, passphrase: bytes, meta: dict[str, Any] | None = None) -> bytes:
    """
    Formato binario ZTV1 (Encrypt-then-MAC):
    [4B magic 'ZTV1'][2B meta_len][meta_json][16B salt][16B nonce][ciphertext][32B HMAC-SHA256]
    """
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(16)
    enc_key, mac_key = _derivar_claves_vault(passphrase, salt)

    comprimido = zlib.compress(plaintext, level=9)
    cipher = _xor_keystream_sha256_ctr(comprimido, enc_key, nonce)

    meta_bytes = json.dumps(meta or {}, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(meta_bytes) > 65535:
        raise ValueError("Metadata excede 64KB")

    cuerpo = VAULT_MAGIC + struct.pack(">H", len(meta_bytes)) + meta_bytes + salt + nonce + cipher
    tag = hmac.new(mac_key, cuerpo, hashlib.sha256).digest()
    return cuerpo + tag


def descifrar_blob_autenticado(blob: bytes, passphrase: bytes) -> tuple[bytes, dict[str, Any]]:
    if len(blob) < 4 + 2 + 16 + 16 + 32 or blob[:4] != VAULT_MAGIC:
        raise ValueError("Formato de archivo .ztvault invalido o corrupto")

    meta_len = struct.unpack(">H", blob[4:6])[0]
    off_salt = 6 + meta_len
    off_nonce = off_salt + 16
    off_cipher = off_nonce + 16
    off_tag = len(blob) - 32
    if off_cipher > off_tag:
        raise ValueError("Cabecera .ztvault truncada")

    meta_bytes = blob[6:off_salt]
    salt = blob[off_salt:off_nonce]
    nonce = blob[off_nonce:off_cipher]
    cipher = blob[off_cipher:off_tag]
    tag_recibido = blob[off_tag:]

    enc_key, mac_key = _derivar_claves_vault(passphrase, salt)
    tag_esperado = hmac.new(mac_key, blob[:off_tag], hashlib.sha256).digest()
    if not hmac.compare_digest(tag_recibido, tag_esperado):
        raise ValueError("Fallo de autenticacion HMAC: clave incorrecta o archivo manipulado")

    comprimido = _xor_keystream_sha256_ctr(cipher, enc_key, nonce)
    plaintext = zlib.decompress(comprimido)
    meta = json.loads(meta_bytes.decode("utf-8")) if meta_bytes else {}
    return plaintext, meta


class EncryptedBackupVault:
    """
    Boveda de backups cifrados autenticados (.ztvault) para TITAN-OS v16.0:
    - Toma snapshot atomico SQLite via sqlite3.backup() + config.json
    - Empaqueta en tar + compresion zlib + cifrado autenticado Encrypt-then-MAC
    - Soporta verificacion criptografica sin sobreescribir disco y restauracion atomica
    """

    def __init__(
        self,
        db: TitanDBEngine | None = None,
        bus: TitanEventBus | None = None,
        vault_dir: str | None = None,
        key_file: str | None = None,
        passphrase_override: str | None = None,
    ) -> None:
        self.db = db or obtener_db_engine()
        self.bus = bus or obtener_event_bus()
        self.vault_dir = os.path.abspath(vault_dir or DEFAULT_VAULT_DIR)
        self.key_file = os.path.abspath(key_file or VAULT_KEY_FILE)
        self._passphrase = self._resolver_clave(passphrase_override)

    def _resolver_clave(self, override: str | None) -> bytes:
        if override and override.strip():
            return override.strip().encode("utf-8")
        env_k = (os.getenv("TITAN_VAULT_KEY") or "").strip()
        if env_k:
            return env_k.encode("utf-8")
        if os.path.isfile(self.key_file):
            try:
                with open(self.key_file, "r", encoding="utf-8") as f:
                    txt = f.read().strip()
                if len(txt) >= 32:
                    return txt.encode("utf-8")
            except OSError:
                pass
        generada = secrets.token_hex(32)
        try:
            os.makedirs(os.path.dirname(self.key_file) or ".", exist_ok=True)
            with open(self.key_file, "w", encoding="utf-8", newline="\n") as f:
                f.write(generada + "\n")
        except OSError:
            pass
        return generada.encode("utf-8")

    def crear_backup_cifrado(
        self,
        *,
        incluir_config: bool = True,
        etiqueta: str = "auto",
        max_backups: int = 12,
    ) -> dict[str, Any]:
        os.makedirs(self.vault_dir, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        slug_etq = re.sub(r"[^a-zA-Z0-9_\-]", "", etiqueta or "auto")[:20] or "auto"
        nombre_arch = f"titan_vault_{stamp}_{slug_etq}.ztvault"
        ruta_dst = os.path.join(self.vault_dir, nombre_arch)

        tmp_dir = tempfile.mkdtemp(prefix="titan_vlt_")
        try:
            # 1. Snapshot atomico SQLite WAL
            db_snap = os.path.join(tmp_dir, "estado_radar_v4.db")
            src_conn = self.db.obtener_conexion()
            dst_conn = sqlite3.connect(db_snap)
            try:
                src_conn.backup(dst_conn, pages=256)
                chk = dst_conn.execute("PRAGMA quick_check").fetchone()
                if not chk or str(chk[0]).lower() != "ok":
                    raise RuntimeError(f"Integridad SQLite fallo en snapshot: {chk}")
            finally:
                dst_conn.close()

            # 2. Construir archivo TAR en memoria con DB + config.json opcional
            archivos_incluidos: list[str] = ["estado_radar_v4.db"]
            tar_buf = io.BytesIO()
            with tarfile.open(fileobj=tar_buf, mode="w") as tf:
                tf.add(db_snap, arcname="estado_radar_v4.db")
                cfg_path = os.path.join(ROOT_DIR, "config.json")
                if incluir_config and os.path.isfile(cfg_path):
                    tf.add(cfg_path, arcname="config.json")
                    archivos_incluidos.append("config.json")

            tar_bytes = tar_buf.getvalue()
            sha_plain = hashlib.sha256(tar_bytes).hexdigest()
            meta = {
                "version": "16.0.0-titan",
                "creado_utc": datetime.now(timezone.utc).isoformat(),
                "etiqueta": slug_etq,
                "version_esquema": self.db.version_esquema(),
                "archivos": archivos_incluidos,
                "sha256_tar": sha_plain,
                "bytes_plano": len(tar_bytes),
            }

            cifrado = cifrar_blob_autenticado(tar_bytes, self._passphrase, meta=meta)
            with open(ruta_dst, "wb") as f:
                f.write(cifrado)

            # Rotar backups antiguos
            existentes = sorted(
                [os.path.join(self.vault_dir, fn) for fn in os.listdir(self.vault_dir) if fn.endswith(".ztvault")],
                key=os.path.getmtime,
            )
            while len(existentes) > max(1, int(max_backups)):
                viejo = existentes.pop(0)
                try:
                    os.remove(viejo)
                except OSError:
                    pass

            res = {
                "ok": True,
                "archivo": nombre_arch,
                "ruta": ruta_dst,
                "bytes_cifrado": len(cifrado),
                "bytes_plano": len(tar_bytes),
                "ratio_compresion_pct": round((1.0 - len(cifrado) / max(1, len(tar_bytes))) * 100.0, 1),
                "sha256_vault": hashlib.sha256(cifrado).hexdigest(),
                "meta": meta,
            }
            if self.bus is not None:
                self.bus.publicar(
                    "system.vault.backup_ok",
                    {"archivo": nombre_arch, "bytes": len(cifrado), "etiqueta": slug_etq},
                    origen="vault",
                    nivel="ok",
                )
            return res
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def verificar_backup(self, ruta_vault: str, passphrase_override: str | None = None) -> dict[str, Any]:
        ruta_abs = os.path.abspath(ruta_vault if os.path.isabs(ruta_vault) else os.path.join(self.vault_dir, ruta_vault))
        if not os.path.isfile(ruta_abs):
            return {"ok": False, "error": f"Archivo no encontrado: {ruta_vault}"}
        clave = passphrase_override.encode("utf-8") if passphrase_override else self._passphrase
        try:
            with open(ruta_abs, "rb") as f:
                blob = f.read()
            tar_bytes, meta = descifrar_blob_autenticado(blob, clave)
            sha_real = hashlib.sha256(tar_bytes).hexdigest()
            if meta.get("sha256_tar") and sha_real != meta["sha256_tar"]:
                return {"ok": False, "error": "SHA-256 interno del TAR no coincide"}
            with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as tf:
                nombres = tf.getnames()
            return {
                "ok": True,
                "archivo": os.path.basename(ruta_abs),
                "archivos": nombres,
                "meta": meta,
                "bytes_cifrado": len(blob),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def restaurar_backup(
        self,
        ruta_vault: str,
        carpeta_destino: str,
        *,
        passphrase_override: str | None = None,
    ) -> dict[str, Any]:
        ruta_abs = os.path.abspath(ruta_vault if os.path.isabs(ruta_vault) else os.path.join(self.vault_dir, ruta_vault))
        if not os.path.isfile(ruta_abs):
            return {"ok": False, "error": f"Archivo no encontrado: {ruta_vault}"}
        clave = passphrase_override.encode("utf-8") if passphrase_override else self._passphrase
        try:
            with open(ruta_abs, "rb") as f:
                blob = f.read()
            tar_bytes, meta = descifrar_blob_autenticado(blob, clave)
            dest_real = os.path.realpath(carpeta_destino)
            os.makedirs(dest_real, exist_ok=True)
            extraidos: list[str] = []
            with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as tf:
                for member in tf.getmembers():
                    if not member.isfile():
                        continue
                    safe_name = os.path.basename(member.name)
                    if not safe_name:
                        continue
                    out_p = os.path.join(dest_real, safe_name)
                    src_f = tf.extractfile(member)
                    if src_f is not None:
                        with open(out_p, "wb") as dst_f:
                            dst_f.write(src_f.read())
                        extraidos.append(safe_name)
            return {
                "ok": True,
                "destino": dest_real,
                "archivos_restaurados": extraidos,
                "meta": meta,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def listar_backups(self) -> list[dict[str, Any]]:
        if not os.path.isdir(self.vault_dir):
            return []
        out: list[dict[str, Any]] = []
        for fn in sorted(os.listdir(self.vault_dir), reverse=True):
            if not fn.endswith(".ztvault"):
                continue
            full = os.path.join(self.vault_dir, fn)
            meta = {}
            try:
                with open(full, "rb") as f:
                    hdr = f.read(6)
                    if len(hdr) == 6 and hdr[:4] == VAULT_MAGIC:
                        mlen = struct.unpack(">H", hdr[4:6])[0]
                        meta = json.loads(f.read(mlen).decode("utf-8"))
            except Exception:
                pass
            out.append({
                "archivo": fn,
                "ruta": full,
                "bytes": os.path.getsize(full),
                "mtime": round(os.path.getmtime(full), 2),
                "meta": meta,
            })
        return out