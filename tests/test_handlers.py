# tests/test_handlers.py
import struct
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from ares.parser.router import IPCHeader, SEGMENT_HEADER_SIZE
from ares.parser.handlers import ActionEffectHandler
from ares.log.writer import LogMessageType

def make_header(opcode: int, payload: bytes, epoch: int = 1000000,
                source_actor: int = 0x12345678) -> IPCHeader:
    return IPCHeader(
        magic=0x0014,
        opcode=opcode,
        server_id=1,
        epoch=epoch,
        source_actor=source_actor,
        target_actor=source_actor,
        payload=payload
    )

def make_action_effect1_payload(
    source_id: int = 0x12345678,
    action_id: int = 0x0009,
    target_id: int = 0x87654321,
    damage: int = 5000,
) -> bytes:
    """Build an ActionEffect1 IPC payload matching live-confirmed 0x00B6 layout.

    Offsets (hex) confirmed from Deucalion pipe + ACT cross-reference:
      0x00: animationTargetId (u32)
      0x08: actionId (u32)
      0x24: actionAnimationId (u16)
      0x29: effectCount (u8)
      0x2A: effects[8] (8 x 8 bytes)
      0x6E: targetId[0] (u64)
    """
    buf = bytearray(256)
    struct.pack_into('<I', buf, 0x00, target_id)   # animationTargetId (target, not source)
    struct.pack_into('<I', buf, 0x08, action_id)   # actionId
    struct.pack_into('<H', buf, 0x24, action_id)   # actionAnimationId
    struct.pack_into('<B', buf, 0x29, 1)            # effectCount = 1
    # Effect entry at 0x2A: type=3 (damage), flags=0
    # lo = type byte, hi = (damage << 16) matching ACT hi field encoding
    effect_lo = 3                                   # type DAMAGE
    effect_hi = (damage & 0xFFFF) << 16             # damage in hi >> 16
    struct.pack_into('<I', buf, 0x2A, effect_lo)
    struct.pack_into('<I', buf, 0x2E, effect_hi)
    struct.pack_into('<Q', buf, 0x6E, target_id)    # targetId (u64)
    return bytes(buf)

def test_action_effect_handler_writes_log():
    log_writer = MagicMock()
    combatant_mgr = MagicMock()
    combatant_mgr.get_by_id.return_value = None

    handler = ActionEffectHandler(
        opcode=0x00B6,
        log_writer=log_writer,
        combatant_manager=combatant_mgr,
        target_count=1
    )

    payload = make_action_effect1_payload()
    header = make_header(0x00B6, payload)
    handler(header)

    assert log_writer.write.called
    call_args = log_writer.write.call_args
    assert call_args[0][0] in (LogMessageType.ActionEffect, LogMessageType.AOEActionEffect)

def test_single_target_produces_type_21():
    log_writer = MagicMock()
    combatant_mgr = MagicMock()
    combatant_mgr.get_by_id.return_value = None

    handler = ActionEffectHandler(
        opcode=0x00B6,
        log_writer=log_writer,
        combatant_manager=combatant_mgr,
        target_count=1
    )
    payload = make_action_effect1_payload()
    header = make_header(0x00B6, payload)
    handler(header)

    msg_type = log_writer.write.call_args[0][0]
    assert msg_type == LogMessageType.ActionEffect  # type 21
