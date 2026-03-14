# tests/test_memory_reader.py
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from ares.memory.reader import MemoryReader, Combatant
from ares.config import Config
import json, tempfile, os

@pytest.fixture
def cfg(tmp_path):
    op = tmp_path / "opcodes.json"
    op.write_text('{"_patch": "7.3"}')
    off = tmp_path / "offsets.json"
    off.write_text(json.dumps({
        "_patch": "7.3",
        "actor_table": "0x1D23A80",
        "actor_table_size": 624,
        "player_id": "0x1D2FD20",
        "territory_id": "0x1D27508"
    }))
    return Config(str(op), str(off))

def test_get_by_id_returns_none_when_not_found(cfg):
    reader = MemoryReader(cfg)
    result = reader.get_by_id(0x12345678)
    assert result is None

def test_get_by_id_returns_combatant_when_cached(cfg):
    reader = MemoryReader(cfg)
    c = Combatant(actor_id=0x1234, name="Vatarris", job=32, hp=50000, max_hp=100000)
    reader._cache[0x1234] = c
    result = reader.get_by_id(0x1234)
    assert result is not None
    assert result.name == "Vatarris"
    assert result.job == 32

def test_combatant_job_abbreviation():
    c = Combatant(actor_id=1, name="Test", job=32, hp=100, max_hp=100)
    assert c.job_abbrev == "DRK"

def test_combatant_unknown_job():
    c = Combatant(actor_id=1, name="Test", job=255, hp=100, max_hp=100)
    assert c.job_abbrev == "???"

def test_attach_returns_false_when_process_not_found(cfg):
    reader = MemoryReader(cfg)
    with patch('ares.memory.reader.pymem') as mock_pymem:
        mock_pymem.Pymem.side_effect = Exception("Process not found")
        result = reader.attach("ffxiv_dx11.exe")
    assert result is False
