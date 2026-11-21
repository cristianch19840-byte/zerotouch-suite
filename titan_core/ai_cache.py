from __future__ import annotations

import hashlib
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from titan_core.db_engine import TitanDBEngine, obtener_db_engine


def _hash64_texto(txt: str) -> int:
    dig = hashlib.blake2b(txt.encode("utf-8", errors="ignore"), digest_size=8).digest()
    return int.from_bytes(dig, byteorder="big", signed=False)


def _normalizar_prompt_clave(texto: str) -> str:
    return re.sub(r"\s+", " ", (texto or "").strip())


def calcular_simhash_prompt(texto: str) -> int:
    toks = re.findall(r"[a-z0-9_+#.\-]{3,28}", (texto or "").lower())
    if not toks:
        return 0
    acum = [0] * 64
    for tok in toks[:240]:
        h = _hash64_texto(tok)
        for b in range(64):
            if (h >> b) & 1:
                acum[b] += 1
            else:
                acum[b] -= 1
    out = 0
    for b in range(64):
        if acum[b] > 0:
            out |= (1 << b)
    return out


def construir_clave_cache(
    prompt: str,
    system_prompt: str = "",
    json_mode: bool = False,
    tarea: str = "general",
    temperatura: float = 0.2,
) -> str:
    temp_bucket = "det" if temperatura <= 0.35 else "crea"
    payload = "|".join((
        "v16",
        str(tarea or "general").strip().lower(),
        "json" if json_mode else "txt",
        temp_bucket,
        _normalizar_prompt_clave(system_prompt),
        _normalizar_prompt_clave(prompt),
    ))
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


@dataclass(slots=True)
class EntradaCacheIA:
    clave_hash: str
    proveedor: str
    modelo: str
    respuesta: str
    tokens_in: int = 0
    tokens_out: int = 0
    hits: int = 0
    creado_epoch: float = 0.0
    expira_epoch: float = 0.0
    simhash_64: int = 0
    tarea: str = "general"
    json_mode: bool = False
    desde_semantica: bool = False


class TitanAICache:
    """
    Cache IA hibrida de 2 niveles:
    - L1: LRU en RAM (<0.05ms) con indice SimHash opcional para prompts casi identicos
    - L2: Persistencia SQLite ('ai_cache') con TTL, contador de hits y poda automatica
    """

    def __init__(
        self,
        db: TitanDBEngine | None = None,
        usar_sqlite: bool = True,
        max_ram_items: int = 256,
        max_db_items: int = 4000,
    ) -> None:
        self._lock = threading.RLock()
        self.usar_sqlite = usar_sqlite
        self.db = db if db is not None else (obtener_db_engine() if usar_sqlite else None)
        self._max_ram = max(32, int(max_ram_items))
        self._max_db = max(200, int(max_db_items))
        self._ram: OrderedDict[str, EntradaCacheIA] = OrderedDict()
        self._stats = {
            "hits_l1": 0,
            "hits_l2": 0,
            "hits_semanticos": 0,
            "misses": 0,
            "escrituras": 0,
            "tokens_ahorrados_in": 0,
            "tokens_ahorrados_out": 0,
        }

    def _put_l1(self, ent: EntradaCacheIA) -> None:
        self._ram[ent.clave_hash] = ent
        self._ram.move_to_end(ent.clave_hash)
        while len(self._ram) > self._max_ram:
            self._ram.popitem(last=False)

    def obtener(
        self,
        clave_hash: str,
        prompt_para_semantica: str = "",
        tarea: str = "general",
        json_mode: bool = False,
        permitir_semantica: bool = False,
        max_hamming: int = 3,
    ) -> EntradaCacheIA | None:
        ahora = time.time()

        # 1. L1 RAM exacto
        with self._lock:
            ent = self._ram.get(clave_hash)
            if ent is not None:
                if ent.expira_epoch > ahora:
                    ent.hits += 1
                    self._ram.move_to_end(clave_hash)
                    self._stats["hits_l1"] += 1
                    self._stats["tokens_ahorrados_in"] += ent.tokens_in
                    self._stats["tokens_ahorrados_out"] += ent.tokens_out
                    self._incrementar_hit_db_async(clave_hash)
                    return ent
                del self._ram[clave_hash]

        # 2. L2 SQLite exacto
        if self.usar_sqlite and self.db is not None:
            row = self.db.consultar_uno(
                """
                SELECT clave_hash, proveedor, modelo, respuesta, tokens_in, tokens_out, hits, creado_epoch, expira_epoch
                FROM ai_cache
                WHERE clave_hash = ? AND expira_epoch > ?
                """,
                (clave_hash, ahora),
            )
            if row is not None:
                ent_db = EntradaCacheIA(
                    clave_hash=str(row["clave_hash"]),
                    proveedor=str(row["proveedor"] or ""),
                    modelo=str(row["modelo"] or ""),
                    respuesta=str(row["respuesta"] or ""),
                    tokens_in=int(row["tokens_in"] or 0),
                    tokens_out=int(row["tokens_out"] or 0),
                    hits=int(row["hits"] or 0) + 1,
                    creado_epoch=float(row["creado_epoch"] or ahora),
                    expira_epoch=float(row["expira_epoch"] or ahora),
                    simhash_64=calcular_simhash_prompt(prompt_para_semantica) if prompt_para_semantica else 0,
                    tarea=tarea,
                    json_mode=json_mode,
                )
                with self._lock:
                    self._put_l1(ent_db)
                    self._stats["hits_l2"] += 1
                    self._stats["tokens_ahorrados_in"] += ent_db.tokens_in
                    self._stats["tokens_ahorrados_out"] += ent_db.tokens_out
                self._incrementar_hit_db_async(clave_hash)
                return ent_db

        # 3. Busqueda semantica rapida en L1 (solo cuando se solicita explicitamente)
        if permitir_semantica and prompt_para_semantica:
            sh = calcular_simhash_prompt(prompt_para_semantica)
            if sh != 0:
                with self._lock:
                    for cand in reversed(self._ram.values()):
                        if cand.expira_epoch <= ahora or cand.simhash_64 == 0:
                            continue
                        if cand.tarea != tarea or cand.json_mode != json_mode:
                            continue
                        if (sh ^ cand.simhash_64).bit_count() <= max_hamming:
                            cand.hits += 1
                            self._stats["hits_semanticos"] += 1
                            self._stats["tokens_ahorrados_in"] += cand.tokens_in
                            self._stats["tokens_ahorrados_out"] += cand.tokens_out
                            return EntradaCacheIA(
                                clave_hash=cand.clave_hash,
                                proveedor=cand.proveedor,
                                modelo=cand.modelo,
                                respuesta=cand.respuesta,
                                tokens_in=cand.tokens_in,
                                tokens_out=cand.tokens_out,
                                hits=cand.hits,
                                creado_epoch=cand.creado_epoch,
                                expira_epoch=cand.expira_epoch,
                                simhash_64=cand.simhash_64,
                                tarea=cand.tarea,
                                json_mode=cand.json_mode,
                                desde_semantica=True,
                            )

        with self._lock:
            self._stats["misses"] += 1
        return None

    def _incrementar_hit_db_async(self, clave_hash: str) -> None:
        if not self.usar_sqlite or self.db is None:
            return
        try:
            self.db.ejecutar("UPDATE ai_cache SET hits = hits + 1 WHERE clave_hash = ?", (clave_hash,))
        except Exception:
            pass

    def guardar(
        self,
        clave_hash: str,
        proveedor: str,
        modelo: str,
        prompt: str,
        respuesta: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        ttl_seg: float = 21600.0,
        tarea: str = "general",
        json_mode: bool = False,
    ) -> None:
        if not respuesta or ttl_seg <= 0:
            return
        ahora = time.time()
        expira = ahora + float(ttl_seg)
        ent = EntradaCacheIA(
            clave_hash=clave_hash,
            proveedor=proveedor,
            modelo=modelo,
            respuesta=respuesta,
            tokens_in=int(tokens_in),
            tokens_out=int(tokens_out),
            hits=0,
            creado_epoch=ahora,
            expira_epoch=expira,
            simhash_64=calcular_simhash_prompt(prompt),
            tarea=tarea,
            json_mode=json_mode,
        )
        with self._lock:
            self._put_l1(ent)
            self._stats["escrituras"] += 1

        if self.usar_sqlite and self.db is not None:
            try:
                self.db.ejecutar(
                    """
                    INSERT INTO ai_cache (
                        clave_hash, proveedor, modelo, prompt_preview, respuesta,
                        tokens_in, tokens_out, hits, creado_epoch, expira_epoch
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                    ON CONFLICT(clave_hash) DO UPDATE SET
                        proveedor = excluded.proveedor,
                        modelo = excluded.modelo,
                        respuesta = excluded.respuesta,
                        tokens_in = excluded.tokens_in,
                        tokens_out = excluded.tokens_out,
                        expira_epoch = excluded.expira_epoch
                    """,
                    (
                        clave_hash,
                        proveedor[:40],
                        modelo[:80],
                        _normalizar_prompt_clave(prompt)[:160],
                        respuesta,
                        int(tokens_in),
                        int(tokens_out),
                        ahora,
                        expira,
                    ),
                )
            except Exception:
                pass

    def podar(self) -> int:
        ahora = time.time()
        borrados = 0
        with self._lock:
            expiradas = [k for k, v in self._ram.items() if v.expira_epoch <= ahora]
            for k in expiradas:
                del self._ram[k]
                borrados += 1
        if self.usar_sqlite and self.db is not None:
            try:
                borrados += self.db.ejecutar("DELETE FROM ai_cache WHERE expira_epoch <= ?", (ahora,))
                borrados += self.db.ejecutar(
                    "DELETE FROM ai_cache WHERE clave_hash NOT IN (SELECT clave_hash FROM ai_cache ORDER BY expira_epoch DESC LIMIT ?)",
                    (self._max_db,),
                )
            except Exception:
                pass
        return borrados

    def limpiar(self) -> int:
        with self._lock:
            n = len(self._ram)
            self._ram.clear()
        if self.usar_sqlite and self.db is not None:
            try:
                self.db.ejecutar("DELETE FROM ai_cache")
            except Exception:
                pass
        return n

    def estadisticas(self) -> dict[str, Any]:
        with self._lock:
            st = dict(self._stats)
            st["en_ram"] = len(self._ram)
        tot_hits = st["hits_l1"] + st["hits_l2"] + st["hits_semanticos"]
        tot_q = tot_hits + st["misses"]
        st["hit_rate_pct"] = round((tot_hits / max(1, tot_q)) * 100.0, 1) if tot_q > 0 else 0.0
        if self.usar_sqlite and self.db is not None:
            st["en_sqlite"] = int(self.db.escalar("SELECT COUNT(*) FROM ai_cache WHERE expira_epoch > ?", (time.time(),), default=0) or 0)
        else:
            st["en_sqlite"] = 0
        return st