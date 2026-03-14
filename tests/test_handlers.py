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
    buf = bytearray(256)
    struct.pack_into('<I', buf, 0, source_id)
    struct.pack_into('<I', buf, 4, action_id)
    struct.pack_into('<H', buf, 8, action_id)  # animation_id
    struct.pack_into('<B', buf, 20, 1)          # num_targets = 1
    struct.pack_into('<BBHBBH', buf, 24, 3, 0, damage & 0xFFFF, 0, 0, 0)
    struct.pack_into('<I', buf, 88, target_id)
    return bytes(buf)

def test_action_effect_handler_writes_log():
    log_writer = MagicMock()
    combatant_mgr = MagicMock()
    combatant_mgr.get_by_id.return_value = None

    handler = ActionEffectHandler(
        opcode=0x00A3,
        log_writer=log_writer,
        combatant_manager=combatant_mgr,
        target_count=1
    )

    payload = make_action_effect1_payload()
    header = make_header(0x00A3, payload)
    handler(header)

    assert log_writer.write.called
    call_args = log_writer.write.call_args
    assert call_args[0][0] in (LogMessageType.ActionEffect, LogMessageType.AOEActionEffect)

def test_single_target_produces_type_21():
    log_writer = MagicMock()
    combatant_mgr = MagicMock()
    combatant_mgr.get_by_id.return_value = None

    handler = ActionEffectHandler(
        opcode=0x00A3,
        log_writer=log_writer,
        combatant_manager=combatant_mgr,
        target_count=1
    )
    payload = make_action_effect1_payload()
    header = make_header(0x00A3, payload)
    handler(header)

    msg_type = log_writer.write.call_args[0][0]
    assert msg_type == LogMessageType.ActionEffect  # type 21
