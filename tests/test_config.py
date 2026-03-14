# tests/test_config.py
import pytest
from ares.config import Config

def test_loads_opcodes(tmp_path):
    opcodes = tmp_path / "opcodes.json"
    opcodes.write_text('{"_patch": "7.3", "ActionEffect1": "0x00A3"}')
    offsets = tmp_path / "offsets.json"
    offsets.write_text('{"_patch": "7.3", "actor_table": "0x1D23A80", "actor_table_size": 624}')

    cfg = Config(opcodes_path=str(opcodes), offsets_path=str(offsets))
    assert cfg.opcode("ActionEffect1") == 0x00A3

def test_loads_offsets(tmp_path):
    opcodes = tmp_path / "opcodes.json"
    opcodes.write_text('{"_patch": "7.3", "ActionEffect1": "0x00A3"}')
    offsets = tmp_path / "offsets.json"
    offsets.write_text('{"_patch": "7.3", "actor_table": "0x1D23A80", "actor_table_size": 624}')

    cfg = Config(opcodes_path=str(opcodes), offsets_path=str(offsets))
    assert cfg.offset("actor_table") == 0x1D23A80
    assert cfg.offset("actor_table_size") == 624

def test_unknown_opcode_returns_zero(tmp_path):
    opcodes = tmp_path / "opcodes.json"
    opcodes.write_text('{"_patch": "7.3"}')
    offsets = tmp_path / "offsets.json"
    offsets.write_text('{"_patch": "7.3"}')

    cfg = Config(opcodes_path=str(opcodes), offsets_path=str(offsets))
    assert cfg.opcode("NonExistentOpcode") == 0

def test_all_action_effect_opcodes_loaded():
    cfg = Config()
    assert cfg.opcode("ActionEffect1") == 0x00B6
    for variant in [1, 8, 16, 24, 32]:
        assert cfg.opcode(f"ActionEffect{variant}") != 0

def test_patch_version():
    cfg = Config()
    assert cfg.patch == "7.45"
