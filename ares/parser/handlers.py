# ares/parser/handlers.py
import struct
import logging
from datetime import datetime
from typing import Optional
from ares.parser.router import IPCHeader
from ares.log.writer import LogWriter, LogMessageType

log = logging.getLogger(__name__)

# Effect type byte from FFXIV network packets
EFFECT_TYPE_DAMAGE = 3
EFFECT_TYPE_HEAL = 4


def _read_str(data: bytes, offset: int, max_len: int = 32) -> str:
    end = data.find(b'\x00', offset, offset + max_len)
    if end == -1:
        end = offset + max_len
    try:
        return data[offset:end].decode('utf-8', errors='replace')
    except Exception:
        return ''


class ActionEffectHandler:
    """
    Handles ActionEffect1/8/16/24/32 packets.
    target_count: 1, 8, 16, 24, or 32 - used to determine AOE vs single.
    Exact struct layout: Machina Server_ActionEffect<N> (confirmed via decompilation).
    """
    # Struct offsets within the IPC payload (after 16-byte IPC header stripped by router)
    _OFF_SOURCE_ID   = 0
    _OFF_ACTION_ID   = 4
    _OFF_ANIM_ID     = 8
    _OFF_ROTATION    = 10
    _OFF_ANIM_LOCK   = 12
    _OFF_EFFECT_DISP = 16
    _OFF_NUM_TARGETS = 18
    _OFF_EFFECTS     = 24   # 8 bytes * 8 effects = 64 bytes
    _OFF_TARGET_ID   = 88

    def __init__(self, opcode: int, log_writer: LogWriter, combatant_manager, target_count: int):
        self._opcode = opcode
        self._writer = log_writer
        self._combatants = combatant_manager
        self._target_count = target_count

    def __call__(self, header: IPCHeader):
        payload = header.payload
        if len(payload) < self._OFF_TARGET_ID + 4:
            log.debug(f"ActionEffect payload too short: {len(payload)}")
            return

        source_id = struct.unpack_from('<I', payload, self._OFF_SOURCE_ID)[0]
        action_id = struct.unpack_from('<I', payload, self._OFF_ACTION_ID)[0]
        target_id = struct.unpack_from('<I', payload, self._OFF_TARGET_ID)[0]

        source = self._combatants.get_by_id(source_id)
        target = self._combatants.get_by_id(target_id)
        source_name = source.name if source else f"{source_id:08X}"
        target_name = target.name if target else f"{target_id:08X}"

        # Read 8 effect slots (8 bytes each)
        effects = []
        for i in range(8):
            off = self._OFF_EFFECTS + (i * 8)
            if off + 8 > len(payload):
                effects.append((0, 0))
            else:
                effect_data = struct.unpack_from('<Q', payload, off)[0]
                effects.append((effect_data & 0xFFFFFFFF, effect_data >> 32))

        effect_str = '|'.join(f"{lo:X}|{hi:X}" for lo, hi in effects)

        msg_type = LogMessageType.ActionEffect if self._target_count == 1 else LogMessageType.AOEActionEffect
        payload_str = (
            f"{source_id:08X}|{source_name}|{action_id:08X}|Action_{action_id:X}|"
            f"{target_id:08X}|{target_name}|{effect_str}|"
            f"0|0|0|0|0.00|0.00|0.00|0.00|"   # target HP (enriched by memory reader when available)
            f"0|0|0|0|0.00|0.00|0.00|0.00"    # source HP
        )
        self._writer.write(msg_type, header.timestamp, payload_str)


class DeathHandler:
    def __init__(self, log_writer: LogWriter, combatant_manager):
        self._writer = log_writer
        self._combatants = combatant_manager

    def __call__(self, header: IPCHeader):
        payload = header.payload
        if len(payload) < 8:
            return
        target_id = struct.unpack_from('<I', payload, 0)[0]
        source_id = struct.unpack_from('<I', payload, 4)[0]

        target = self._combatants.get_by_id(target_id)
        source = self._combatants.get_by_id(source_id)
        target_name = target.name if target else f"{target_id:08X}"
        source_name = source.name if source else f"{source_id:08X}"

        payload_str = f"{target_id:08X}|{target_name}|{source_id:08X}|{source_name}"
        self._writer.write(LogMessageType.Death, header.timestamp, payload_str)


class DoTHoTHandler:
    def __init__(self, log_writer: LogWriter, combatant_manager):
        self._writer = log_writer
        self._combatants = combatant_manager

    def __call__(self, header: IPCHeader):
        payload = header.payload
        if len(payload) < 24:
            return
        target_id, source_id, dot_type, buff_id, amount = struct.unpack_from('<IIIHHxxxx', payload, 0)

        target = self._combatants.get_by_id(target_id)
        source = self._combatants.get_by_id(source_id)
        target_name = target.name if target else f"{target_id:08X}"
        source_name = source.name if source else f"{source_id:08X}"

        is_heal = dot_type == 1
        payload_str = (
            f"{target_id:08X}|{target_name}|{'HoT' if is_heal else 'DoT'}|"
            f"{buff_id:X}|{amount:X}|0|0|0|0|0.00|0.00|0.00|0.00|"
            f"{source_id:08X}|{source_name}|0|0|0|0|0|0.00|0.00|0.00|0.00"
        )
        self._writer.write(LogMessageType.DoTHoT, header.timestamp, payload_str)
