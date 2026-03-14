# tests/test_integration.py
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

def test_full_pipeline_writes_log(tmp_path):
    """Smoke test: action effect event flows from router to log file."""
    from ares.config import Config
    from ares.log.writer import LogWriter, LogMessageType
    from ares.parser.router import PacketRouter, DeucalionFrame, IPCHeader
    from ares.state.encounter import EncounterManager
    import struct, json

    # Config
    op = tmp_path / "opcodes.json"
    op.write_text(json.dumps({"_patch": "7.3", "ActionEffect1": "0x00B6"}))
    off = tmp_path / "offsets.json"
    off.write_text(json.dumps({"_patch": "7.3", "actor_table": "0x0", "actor_table_size": 1}))
    cfg = Config(str(op), str(off))

    # Log writer
    writer = LogWriter(log_dir=str(tmp_path))
    writer.open_session(datetime.now(timezone.utc))

    # Router
    router = PacketRouter(cfg)

    # Combatant manager stub
    cm = MagicMock()
    cm.get_by_id.return_value = None

    # Encounter manager
    enc_mgr = EncounterManager()

    # Handler
    from ares.parser.handlers import ActionEffectHandler
    handler = ActionEffectHandler(
        opcode=0x00B6,
        log_writer=writer,
        combatant_manager=cm,
        target_count=1
    )

    def combined_handler(header):
        handler(header)
        enc_mgr.on_action_effect(
            source_id=0x12345678,
            target_id=0x87654321,
            damage=5000,
            timestamp=datetime.now(timezone.utc)
        )

    router.register(0x00B6, combined_handler)

    # Build IPC payload (live-confirmed 0x00B6 layout)
    ipc_payload = bytearray(256)
    struct.pack_into('<I', ipc_payload, 0x00, 0x87654321)  # animationTargetId
    struct.pack_into('<I', ipc_payload, 0x08, 0x0009)       # actionId
    # Effect entry at 0x2A: type=3 (damage), damage in hi >> 16
    effect_lo = 3
    effect_hi = (5000 & 0xFFFF) << 16
    struct.pack_into('<I', ipc_payload, 0x2A, effect_lo)
    struct.pack_into('<I', ipc_payload, 0x2E, effect_hi)
    struct.pack_into('<Q', ipc_payload, 0x6E, 0x87654321)   # targetId (u64)

    # Build segment header (16 bytes) + IPC header (16 bytes) + payload
    seg_header = struct.pack('<II8s', 0x12345678, 0x87654321, b'\x00' * 8)
    ipc_header = struct.pack('<HHHHI', 0x0014, 0x00B6, 0, 1, 1000000) + b'\x00' * 4
    full_data = seg_header + ipc_header + bytes(ipc_payload)

    frame = DeucalionFrame(op=3, channel=3, data=full_data)
    router.dispatch(frame)

    # Verify log was written
    logs = list(tmp_path.glob("Network_*.log"))
    assert len(logs) == 1
    assert "21|" in logs[0].read_text()

    # Verify encounter started
    assert enc_mgr.current is not None
    assert enc_mgr.current.active
