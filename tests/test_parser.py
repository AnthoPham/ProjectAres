# tests/test_parser.py
import struct
import pytest
from unittest.mock import MagicMock
from ares.parser.router import PacketRouter, DeucalionFrame, IPCHeader

def make_ipc_bytes(opcode: int, payload: bytes) -> bytes:
    # IPC header: magic(2) + opcode(2) + pad(2) + server_id(2) + epoch(4) + pad(4) = 16 bytes
    header = struct.pack('<HHHHI4s', 0x0014, opcode, 0, 1, 1000000, b'\x00' * 4)
    return header + payload

def make_frame(opcode: int, payload: bytes) -> bytes:
    ipc = make_ipc_bytes(opcode, payload)
    # Deucalion frame: op(1) + channel(1) + length(2 LE) + data
    return struct.pack('<BBH', 1, 1, len(ipc)) + ipc

def test_parse_deucalion_frame():
    raw = make_frame(0x00A3, b'\x00' * 32)
    frame = DeucalionFrame.from_bytes(raw)
    assert frame.op == 1
    assert frame.channel == 1
    assert len(frame.data) == 16 + 32

def test_parse_ipc_header():
    ipc_bytes = make_ipc_bytes(0x00A3, b'\x00' * 32)
    header = IPCHeader.from_bytes(ipc_bytes)
    assert header.opcode == 0x00A3
    assert header.epoch == 1000000

def test_router_dispatches_to_handler():
    from ares.config import Config
    from unittest.mock import patch, MagicMock
    import json, tempfile, os

    with tempfile.TemporaryDirectory() as d:
        op_path = os.path.join(d, 'opcodes.json')
        off_path = os.path.join(d, 'offsets.json')
        with open(op_path, 'w') as f:
            json.dump({"_patch": "7.3", "ActionEffect1": "0x00A3"}, f)
        with open(off_path, 'w') as f:
            json.dump({"_patch": "7.3", "actor_table": "0x0"}, f)

        cfg = Config(op_path, off_path)
        handler = MagicMock()
        router = PacketRouter(cfg)
        router.register(0x00A3, handler)

        frame_bytes = make_frame(0x00A3, b'\x00' * 32)
        frame = DeucalionFrame.from_bytes(frame_bytes)
        router.dispatch(frame)
        handler.assert_called_once()

def test_router_ignores_unknown_opcode():
    from ares.config import Config
    import json, tempfile, os

    with tempfile.TemporaryDirectory() as d:
        op_path = os.path.join(d, 'opcodes.json')
        off_path = os.path.join(d, 'offsets.json')
        with open(op_path, 'w') as f:
            json.dump({"_patch": "7.3"}, f)
        with open(off_path, 'w') as f:
            json.dump({"_patch": "7.3"}, f)

        cfg = Config(op_path, off_path)
        router = PacketRouter(cfg)
        frame_bytes = make_frame(0xFFFF, b'\x00' * 32)
        frame = DeucalionFrame.from_bytes(frame_bytes)
        router.dispatch(frame)  # should not raise
