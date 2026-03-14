# ares/memory/reader.py
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

try:
    import pymem
    import pymem.process
    PYMEM_AVAILABLE = True
except ImportError:
    PYMEM_AVAILABLE = False

from ares.config import Config

log = logging.getLogger(__name__)

# Job ID to abbreviation mapping (FFXIV job IDs)
JOB_MAP = {
    1: "GLA", 2: "PGL", 3: "MRD", 4: "LNC", 5: "ARC",
    6: "CNJ", 7: "THM", 8: "CRP", 9: "BSM", 10: "ARM",
    11: "GSM", 12: "LTW", 13: "WVR", 14: "ALC", 15: "CUL",
    16: "MIN", 17: "BTN", 18: "FSH", 19: "PLD", 20: "MNK",
    21: "WAR", 22: "DRG", 23: "BRD", 24: "WHM", 25: "BLM",
    26: "ACN", 27: "SMN", 28: "SCH", 29: "ROG", 30: "NIN",
    31: "MCH", 32: "DRK", 33: "AST", 34: "SAM", 35: "RDM",
    36: "BLU", 37: "GNB", 38: "DNC", 39: "RPR", 40: "SGE",
    41: "VPR", 42: "PCT",
}

# Combatant struct offsets within each entity slot (from FFXIVClientStructs)
_OFF_ACTOR_ID   = 0x74
_OFF_NAME       = 0x30
_OFF_JOB        = 0x1BC
_OFF_HP         = 0x1B4
_OFF_MAX_HP     = 0x1B8
_OFF_MP         = 0x1B0
_ENTITY_SIZE    = 0x27A0


@dataclass
class Combatant:
    actor_id: int
    name: str
    job: int
    hp: int
    max_hp: int
    mp: int = 0

    @property
    def job_abbrev(self) -> str:
        return JOB_MAP.get(self.job, '???')

    @property
    def hp_pct(self) -> float:
        return (self.hp / self.max_hp * 100) if self.max_hp > 0 else 0.0


class MemoryReader:
    POLL_INTERVAL = 0.1  # 100ms - matches ACT source

    def __init__(self, config: Config):
        self._config = config
        self._cache: dict[int, Combatant] = {}
        self._lock = threading.Lock()
        self._pm = None
        self._base = 0
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def attach(self, process_name: str = "ffxiv_dx11.exe") -> bool:
        if not PYMEM_AVAILABLE:
            log.warning("pymem not available - memory reading disabled")
            return False
        try:
            self._pm = pymem.Pymem(process_name)
            self._base = pymem.process.module_from_name(
                self._pm.process_handle, process_name
            ).lpBaseOfDll
            log.info(f"Attached to {process_name}, base: {self._base:#010x}")
            return True
        except Exception as e:
            log.warning(f"Could not attach to {process_name}: {e}")
            self._pm = None
            return False

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="MemoryReader")
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def get_by_id(self, actor_id: int) -> Optional[Combatant]:
        with self._lock:
            return self._cache.get(actor_id)

    def _poll_loop(self):
        while self._running:
            if self._pm:
                try:
                    self._refresh()
                except Exception as e:
                    log.debug(f"Memory read error: {e}")
            time.sleep(self.POLL_INTERVAL)

    def _refresh(self):
        actor_table_offset = self._config.offset('actor_table')
        table_size = self._config.offset('actor_table_size')
        actor_table_addr = self._base + actor_table_offset

        new_cache = {}
        for i in range(table_size):
            try:
                ptr_addr = actor_table_addr + (i * 8)
                entity_ptr = self._pm.read_longlong(ptr_addr)
                if not entity_ptr:
                    continue
                actor_id = self._pm.read_uint(entity_ptr + _OFF_ACTOR_ID)
                if not actor_id or actor_id == 0xE0000000:
                    continue
                name_bytes = self._pm.read_bytes(entity_ptr + _OFF_NAME, 32)
                name = name_bytes.split(b'\x00')[0].decode('utf-8', errors='replace')
                job = self._pm.read_uchar(entity_ptr + _OFF_JOB)
                hp = self._pm.read_uint(entity_ptr + _OFF_HP)
                max_hp = self._pm.read_uint(entity_ptr + _OFF_MAX_HP)
                new_cache[actor_id] = Combatant(actor_id=actor_id, name=name, job=job, hp=hp, max_hp=max_hp)
            except Exception:
                continue

        with self._lock:
            self._cache = new_cache
