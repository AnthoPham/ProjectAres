# tests/test_combat_state.py
import pytest
from datetime import datetime, timezone, timedelta
from ares.state.encounter import EncounterManager, EncounterOutcome
from ares.log.writer import LogMessageType

def ts(offset_secs=0):
    base = datetime(2026, 3, 13, 20, 0, 0, tzinfo=timezone.utc)
    return base + timedelta(seconds=offset_secs)

def test_first_damage_starts_encounter():
    mgr = EncounterManager()
    mgr.on_action_effect(source_id=0x1234, target_id=0x5678, damage=5000, timestamp=ts(0))
    assert mgr.current is not None
    assert mgr.current.active is True

def test_no_combat_for_timeout_ends_encounter():
    mgr = EncounterManager(timeout_secs=15)
    mgr.on_action_effect(source_id=0x1234, target_id=0x5678, damage=5000, timestamp=ts(0))
    mgr.tick(ts(16))
    assert mgr.current is None
    assert len(mgr.completed) == 1
    assert mgr.completed[0].outcome == EncounterOutcome.TIMEOUT

def test_wipe_signal_ends_encounter():
    mgr = EncounterManager()
    mgr.on_action_effect(source_id=0x1234, target_id=0x5678, damage=5000, timestamp=ts(0))
    mgr.on_wipe(timestamp=ts(10))
    assert mgr.current is None
    assert mgr.completed[0].outcome == EncounterOutcome.WIPE

def test_boss_death_ends_as_kill():
    mgr = EncounterManager()
    mgr.on_action_effect(source_id=0x1234, target_id=0x5678, damage=5000, timestamp=ts(0))
    mgr.on_death(target_id=0x5678, source_id=0x1234, timestamp=ts(30), is_boss=True)
    assert mgr.completed[0].outcome == EncounterOutcome.KILL

def test_dps_calculation():
    mgr = EncounterManager()
    mgr.on_action_effect(source_id=0x1234, target_id=0x5678, damage=10000, timestamp=ts(0))
    mgr.on_action_effect(source_id=0x1234, target_id=0x5678, damage=10000, timestamp=ts(10))
    mgr.tick(ts(10))
    enc = mgr.current
    stats = enc.combatant_stats.get(0x1234)
    assert stats is not None
    assert stats.total_damage == 20000
    assert abs(stats.dps - 2000.0) < 1.0

def test_multiple_pulls_tracked():
    mgr = EncounterManager(timeout_secs=15)
    mgr.on_action_effect(source_id=0x1234, target_id=0x5678, damage=5000, timestamp=ts(0))
    mgr.tick(ts(16))  # end pull 1
    mgr.on_action_effect(source_id=0x1234, target_id=0x5678, damage=5000, timestamp=ts(20))
    assert mgr.current is not None
    assert len(mgr.completed) == 1
    assert mgr.current.pull_id == 2

def test_progression_boss_hp_tracked():
    mgr = EncounterManager()
    mgr.on_action_effect(source_id=0x1234, target_id=0x5678, damage=5000, timestamp=ts(0))
    mgr.on_boss_hp_update(boss_id=0x5678, hp_pct=62.4, timestamp=ts(5))
    mgr.on_wipe(timestamp=ts(10))
    assert abs(mgr.completed[0].boss_hp_pct_at_end - 62.4) < 0.1
