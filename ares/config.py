# ares/config.py
import json
import os

_DEFAULT_OPCODES = os.path.join(os.path.dirname(__file__), '..', 'config', 'opcodes.json')
_DEFAULT_OFFSETS = os.path.join(os.path.dirname(__file__), '..', 'config', 'offsets.json')


class Config:
    def __init__(self, opcodes_path: str = _DEFAULT_OPCODES, offsets_path: str = _DEFAULT_OFFSETS):
        with open(opcodes_path) as f:
            self._opcodes = json.load(f)
        with open(offsets_path) as f:
            self._offsets = json.load(f)

    @property
    def patch(self) -> str:
        return self._opcodes.get('_patch', 'unknown')

    def opcode(self, name: str) -> int:
        val = self._opcodes.get(name, '0x0')
        if isinstance(val, int):
            return val
        return int(val, 16)

    def offset(self, name: str) -> int:
        val = self._offsets.get(name, 0)
        if isinstance(val, str):
            return int(val, 16)
        return int(val)

    def action_effect_opcodes(self) -> set[int]:
        return {
            self.opcode(f'ActionEffect{n}')
            for n in [1, 8, 16, 24, 32]
            if self.opcode(f'ActionEffect{n}') != 0
        }
