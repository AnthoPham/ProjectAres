# tests/test_parser.py
import struct
import pytest
from unittest.mock import MagicMock
from ares.parser.router import PacketRouter, DeucalionFrame, IPCHeader, SEGMENT_HEADER_SIZE

def make_segment_header(source_id: int = 0x12345678, target_id: int = 0x12345678) -> bytes:
    """16-byte FFXIV segment header: source_actor(4) + target_actor(4) + padding(8)"""
    return struct.pack('<II8s', source_id, target_id, b'\x00' * 8)

def make_ipc_bytes(opcode: int, payload: bytes, source_id: int = 0x12345678) -> bytes:
    """Segment header (16) + IPC header (16) + payload"""
    seg = make_segment_header(source_id, source_id)
    ipc_hdr = struct.pack('<HHHHI4s', 0x0014, opcode, 0, 1, 1000000, b'\x00' * 4)
    return seg + ipc_hdr + payload

def make_deucalion_frame(opcode: int, payload: bytes) -> DeucalionFrame:
    """Create a DeucalionFrame with op=3 (Recv) containing segment+IPC data."""
    data = make_ipc_bytes(opcode, payload)
    return DeucalionFrame(op=3, channel=3, data=data)

def test_parse_ipc_header():
    data = make_ipc_bytes(0x00A3, b'\x00' * 32)
    header = IPCHeader.from_bytes(data)
    assert header.opcode == 0x00A3
    assert header.epoch == 1000000
    assert header.source_actor == 0x12345678
    assert header.magic == 0x0014

def test_parse_ipc_header_too_short():
    with pytest.raises(ValueError):
        IPCHeader.from_bytes(b'\x00' * 20)

def test_router_dispatches_to_handler():
    from ares.config import Config
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

        frame = make_deucalion_frame(0x00A3, b'\x00' * 32)
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
        frame = make_deucalion_frame(0xFFFF, b'\x00' * 32)
        router.dispatch(frame)  # should not raise

def test_router_ignores_non_ipc_frames():
    from ares.config import Config
    import json, tempfile, os

    with tempfile.TemporaryDirectory() as d:
        op_path = os.path.join(d, 'opcodes.json')
        off_path = os.path.join(d, 'offsets.json')
        with open(op_path, 'w') as f:
            json.dump({"_patch": "7.3", "ActionEffect1": "0x00A3"}, f)
        with open(off_path, 'w') as f:
            json.dump({"_patch": "7.3"}, f)

        cfg = Config(op_path, off_path)
        handler = MagicMock()
        router = PacketRouter(cfg)
        router.register(0x00A3, handler)

        # op=1 (Ping) should be ignored
        frame = DeucalionFrame(op=1, channel=0, data=b'\x00' * 48)
        router.dispatch(frame)
        handler.assert_not_called()
