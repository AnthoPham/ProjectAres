# ares/state/encounter.py
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

log = logging.getLogger(__name__)


class EncounterOutcome(str, Enum):
    ACTIVE = 'active'
    WIPE = 'wipe'
    KILL = 'kill'
    TIMEOUT = 'timeout'


@dataclass
class CombatantStats:
    actor_id: int
    name: str = ''
    job: str = '???'
    total_damage: int = 0
    total_healing: int = 0
    deaths: int = 0
    _last_ts: Optional[datetime] = field(default=None, repr=False)

    @property
    def dps(self) -> float:
        if not hasattr(self, '_encounter_duration') or self._encounter_duration <= 0:
            return 0.0
        return self.total_damage / self._encounter_duration

    @property
    def hps(self) -> float:
        if not hasattr(self, '_encounter_duration') or self._encounter_duration <= 0:
            return 0.0
        return self.total_healing / self._encounter_duration


@dataclass
class Encounter:
    pull_id: int
    start_time: datetime
    zone: str = ''
    outcome: EncounterOutcome = EncounterOutcome.ACTIVE
    end_time: Optional[datetime] = None
    boss_hp_pct_at_end: Optional[float] = None
    combatant_stats: dict = field(default_factory=dict)
    _last_event_time: Optional[datetime] = field(default=None, repr=False)
    _current_boss_hp_pct: Optional[float] = field(default=None, repr=False)

    @property
    def active(self) -> bool:
        return self.outcome == EncounterOutcome.ACTIVE

    @property
    def duration_secs(self) -> float:
        end = self.end_time or datetime.now(timezone.utc)
        return (end - self.start_time).total_seconds()

    @property
    def party_dps(self) -> float:
        d = self.duration_secs
        if d <= 0:
            return 0.0
        return sum(s.total_damage for s in self.combatant_stats.values()) / d

    def to_dict(self) -> dict:
        return {
            'pull_id': self.pull_id,
            'start_time': self.start_time.isoformat(),
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'zone': self.zone,
            'outcome': self.outcome.value,
            'duration_secs': self.duration_secs,
            'boss_hp_pct_at_end': self.boss_hp_pct_at_end,
            'party_dps': self.party_dps,
            'combatants': [
                {
                    'actor_id': s.actor_id,
                    'name': s.name,
                    'job': s.job,
                    'total_damage': s.total_damage,
                    'total_healing': s.total_healing,
                    'deaths': s.deaths,
                }
                for s in self.combatant_stats.values()
            ]
        }


class EncounterManager:
    def __init__(self, timeout_secs: float = 15.0):
        self._timeout = timeout_secs
        self._pull_counter = 0
        self.current: Optional[Encounter] = None
        self.completed: list[Encounter] = []
        self._callbacks: list = []

    def register_callback(self, fn):
        self._callbacks.append(fn)

    def _notify(self, event: str, data: dict):
        for cb in self._callbacks:
            try:
                cb(event, data)
            except Exception as e:
                log.warning(f"Callback error: {e}")

    def on_action_effect(self, source_id: int, target_id: int, damage: int, timestamp: datetime):
        if self.current is None:
            self._start_encounter(timestamp)

        enc = self.current
        enc._last_event_time = timestamp

        if source_id not in enc.combatant_stats:
            enc.combatant_stats[source_id] = CombatantStats(actor_id=source_id)
        stats = enc.combatant_stats[source_id]
        stats.total_damage += damage

        # Update DPS on all combatants using event timestamp, not wall clock
        duration = (timestamp - enc.start_time).total_seconds()
        if duration > 0:
            for s in enc.combatant_stats.values():
                s._encounter_duration = duration

    def on_death(self, target_id: int, source_id: int, timestamp: datetime, is_boss: bool = False):
        if self.current is None:
            return
        if target_id in self.current.combatant_stats:
            self.current.combatant_stats[target_id].deaths += 1
        if is_boss:
            self._end_encounter(EncounterOutcome.KILL, timestamp)

    def on_wipe(self, timestamp: datetime):
        if self.current:
            self._end_encounter(EncounterOutcome.WIPE, timestamp)

    def on_boss_hp_update(self, boss_id: int, hp_pct: float, timestamp: datetime):
        if self.current:
            self.current._current_boss_hp_pct = hp_pct

    def tick(self, now: datetime):
        if self.current is None:
            return
        last = self.current._last_event_time
        if last and (now - last).total_seconds() >= self._timeout:
            self._end_encounter(EncounterOutcome.TIMEOUT, now)

    def _start_encounter(self, timestamp: datetime):
        self._pull_counter += 1
        self.current = Encounter(pull_id=self._pull_counter, start_time=timestamp)
        self.current._last_event_time = timestamp
        log.info(f"Encounter started: Pull {self._pull_counter}")
        self._notify('encounter_start', {'pull_id': self._pull_counter})

    def _end_encounter(self, outcome: EncounterOutcome, timestamp: datetime):
        enc = self.current
        enc.outcome = outcome
        enc.end_time = timestamp
        enc.boss_hp_pct_at_end = enc._current_boss_hp_pct
        self.completed.append(enc)
        self.current = None
        log.info(f"Encounter ended: Pull {enc.pull_id} - {outcome.value}, "
                 f"boss HP: {enc.boss_hp_pct_at_end}%")
        self._notify('encounter_end', enc.to_dict())

    def progression_summary(self) -> list[dict]:
        return [e.to_dict() for e in self.completed]
