# tests/test_handlers.py
import struct
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, call
from ares.parser.router import IPCHeader, SEGMENT_HEADER_SIZE
from ares.parser.handlers import (
    ActionEffectHandler, ActorControlHandler, ActorControlSelfHandler
)
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


# ---- ActorControlSelf (DoT/HoT) tests ----

def make_actor_control_self_payload(category, buff_id, amount, source_id, cur_hp, max_hp):
    """Build an ActorControlSelf payload for DoT/HoT ticks.

    Layout:
      offset 0:  u16 category
      offset 2:  u16 padding
      offset 4:  u32 buff_id (param1)
      offset 8:  u32 amount (param2)
      offset 12: u32 source_id (param3)
      offset 16: u32 cur_hp (param4)
      offset 20: u32 max_hp (param5)
    """
    return struct.pack('<HH IIIII', category, 0, buff_id, amount, source_id, cur_hp, max_hp)


def test_dot_tick_writes_log_line():
    log_writer = MagicMock()
    combatant_mgr = MagicMock()
    combatant_mgr.get_by_id.return_value = None

    handler = ActorControlSelfHandler(
        log_writer=log_writer, combatant_manager=combatant_mgr
    )

    payload = make_actor_control_self_payload(
        category=24, buff_id=0x4B1, amount=8500,
        source_id=0xAAAAAAAA, cur_hp=50000, max_hp=100000
    )
    # source_actor in header = target (self) for ActorControlSelf
    header = make_header(0x0217, payload, source_actor=0xBBBBBBBB)
    handler(header)

    assert log_writer.write.called
    call_args = log_writer.write.call_args
    assert call_args[0][0] == LogMessageType.DoTHoT
    payload_str = call_args[0][2]
    assert 'DoT' in payload_str
    assert 'BBBBBBBB' in payload_str  # target
    assert 'AAAAAAAA' in payload_str  # source


def test_hot_tick_writes_log_line():
    log_writer = MagicMock()
    combatant_mgr = MagicMock()
    combatant_mgr.get_by_id.return_value = None

    handler = ActorControlSelfHandler(
        log_writer=log_writer, combatant_manager=combatant_mgr
    )

    payload = make_actor_control_self_payload(
        category=23, buff_id=0x1F4, amount=3000,
        source_id=0xCCCCCCCC, cur_hp=90000, max_hp=100000
    )
    header = make_header(0x0217, payload, source_actor=0xDDDDDDDD)
    handler(header)

    assert log_writer.write.called
    payload_str = log_writer.write.call_args[0][2]
    assert 'HoT' in payload_str


def test_dot_tick_feeds_encounter_manager():
    log_writer = MagicMock()
    combatant_mgr = MagicMock()
    combatant_mgr.get_by_id.return_value = None
    enc_mgr = MagicMock()

    handler = ActorControlSelfHandler(
        log_writer=log_writer, combatant_manager=combatant_mgr,
        encounter_manager=enc_mgr
    )

    payload = make_actor_control_self_payload(
        category=24, buff_id=0x4B1, amount=8500,
        source_id=0xAAAAAAAA, cur_hp=50000, max_hp=100000
    )
    header = make_header(0x0217, payload, source_actor=0xBBBBBBBB)
    handler(header)

    enc_mgr.on_action_effect.assert_called_once()
    kwargs = enc_mgr.on_action_effect.call_args
    assert kwargs[1]['damage'] == 8500
    assert kwargs[1]['source_id'] == 0xAAAAAAAA
    assert kwargs[1]['target_id'] == 0xBBBBBBBB


def test_hot_tick_does_not_feed_encounter_damage():
    log_writer = MagicMock()
    combatant_mgr = MagicMock()
    combatant_mgr.get_by_id.return_value = None
    enc_mgr = MagicMock()

    handler = ActorControlSelfHandler(
        log_writer=log_writer, combatant_manager=combatant_mgr,
        encounter_manager=enc_mgr
    )

    payload = make_actor_control_self_payload(
        category=23, buff_id=0x1F4, amount=3000,
        source_id=0xCCCCCCCC, cur_hp=90000, max_hp=100000
    )
    header = make_header(0x0217, payload, source_actor=0xDDDDDDDD)
    handler(header)

    enc_mgr.on_action_effect.assert_not_called()


def test_actor_control_self_ignores_unknown_category():
    log_writer = MagicMock()
    combatant_mgr = MagicMock()
    combatant_mgr.get_by_id.return_value = None

    handler = ActorControlSelfHandler(
        log_writer=log_writer, combatant_manager=combatant_mgr
    )

    # category=99 is not DoT or HoT
    payload = make_actor_control_self_payload(
        category=99, buff_id=0, amount=0,
        source_id=0, cur_hp=0, max_hp=0
    )
    header = make_header(0x0217, payload)
    handler(header)

    log_writer.write.assert_not_called()


def test_actor_control_self_short_payload():
    log_writer = MagicMock()
    combatant_mgr = MagicMock()

    handler = ActorControlSelfHandler(
        log_writer=log_writer, combatant_manager=combatant_mgr
    )

    header = make_header(0x0217, b'\x00' * 10)  # too short
    handler(header)

    log_writer.write.assert_not_called()


# ---- ActorControl (death, combat state) tests ----

def make_actor_control_payload(category, param1, param2=0, param3=0, param4=0):
    """Build an ActorControl payload.

    Layout:
      offset 0:  u16 category
      offset 2:  u16 padding
      offset 4:  u32 param1
      offset 8:  u32 param2
      offset 12: u32 param3
      offset 16: u32 param4
    """
    return struct.pack('<HH IIII', category, 0, param1, param2, param3, param4)


def test_death_writes_log_line():
    log_writer = MagicMock()
    combatant_mgr = MagicMock()
    combatant_mgr.get_by_id.return_value = None

    handler = ActorControlHandler(
        log_writer=log_writer, combatant_manager=combatant_mgr
    )

    # category=6 (death), param1=source_id
    payload = make_actor_control_payload(category=6, param1=0x11111111)
    header = make_header(0x020B, payload, source_actor=0x22222222)  # target dies
    handler(header)

    assert log_writer.write.called
    call_args = log_writer.write.call_args
    assert call_args[0][0] == LogMessageType.Death
    payload_str = call_args[0][2]
    assert '22222222' in payload_str  # target
    assert '11111111' in payload_str  # source


def test_death_notifies_encounter_manager():
    log_writer = MagicMock()
    combatant_mgr = MagicMock()
    combatant_mgr.get_by_id.return_value = None
    enc_mgr = MagicMock()

    handler = ActorControlHandler(
        log_writer=log_writer, combatant_manager=combatant_mgr,
        encounter_manager=enc_mgr
    )

    payload = make_actor_control_payload(category=6, param1=0x11111111)
    header = make_header(0x020B, payload, source_actor=0x22222222)
    handler(header)

    enc_mgr.on_death.assert_called_once()
    kwargs = enc_mgr.on_death.call_args
    assert kwargs[1]['target_id'] == 0x22222222
    assert kwargs[1]['source_id'] == 0x11111111


def test_actor_control_ignores_unknown_category():
    log_writer = MagicMock()
    combatant_mgr = MagicMock()

    handler = ActorControlHandler(
        log_writer=log_writer, combatant_manager=combatant_mgr
    )

    payload = make_actor_control_payload(category=99, param1=0)
    header = make_header(0x020B, payload)
    handler(header)

    log_writer.write.assert_not_called()


def test_actor_control_short_payload():
    log_writer = MagicMock()
    combatant_mgr = MagicMock()

    handler = ActorControlHandler(
        log_writer=log_writer, combatant_manager=combatant_mgr
    )

    header = make_header(0x020B, b'\x00' * 8)  # too short
    handler(header)

    log_writer.write.assert_not_called()
