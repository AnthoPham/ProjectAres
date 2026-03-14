# ares/parser/router.py
import struct
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional
from ares.config import Config

log = logging.getLogger(__name__)

# Deucalion data layout:
#   Segment header (16 bytes):
#     source_actor: u32 (0-3)
#     target_actor: u32 (4-7)
#     segment_data: u64 (8-15, timestamp + flags)
#   IPC header (16 bytes, starting at offset 16):
#     magic: u16 = 0x0014 (16-17)
#     opcode: u16 (18-19)
#     padding: u16 (20-21)
#     server_id: u16 (22-23)
#     epoch: u32 (24-27)
#     padding: u32 (28-31)
#   IPC payload (starting at offset 32)
SEGMENT_HEADER_SIZE = 16
IPC_HEADER_SIZE = 16
TOTAL_HEADER_SIZE = SEGMENT_HEADER_SIZE + IPC_HEADER_SIZE


@dataclass
class DeucalionFrame:
    op: int       # 3=Recv, 4=Send
    channel: int
    data: bytes

    @classmethod
    def from_bytes(cls, raw: bytes) -> 'DeucalionFrame':
        op, channel, length = struct.unpack_from('<BBH', raw, 0)
        data = raw[4:4 + length]
        return cls(op=op, channel=channel, data=data)

    @property
    def frame_length(self) -> int:
        return 4 + len(self.data)


@dataclass
class SegmentHeader:
    source_actor: int
    target_actor: int

    @classmethod
    def from_bytes(cls, data: bytes) -> 'SegmentHeader':
        if len(data) < SEGMENT_HEADER_SIZE:
            raise ValueError(f"Segment data too short: {len(data)} bytes")
        source, target = struct.unpack_from('<II', data, 0)
        return cls(source_actor=source, target_actor=target)


@dataclass
class IPCHeader:
    magic: int
    opcode: int
    server_id: int
    epoch: int
    source_actor: int
    target_actor: int
    payload: bytes

    @classmethod
    def from_bytes(cls, data: bytes) -> 'IPCHeader':
        if len(data) < TOTAL_HEADER_SIZE:
            raise ValueError(f"Data too short for segment+IPC: {len(data)} bytes")

        # Parse segment header
        source_actor, target_actor = struct.unpack_from('<II', data, 0)

        # Parse IPC header (at offset 16)
        magic, opcode, _pad, server_id, epoch = struct.unpack_from(
            '<HHHHI', data, SEGMENT_HEADER_SIZE
        )

        payload = data[TOTAL_HEADER_SIZE:]
        return cls(
            magic=magic, opcode=opcode, server_id=server_id, epoch=epoch,
            source_actor=source_actor, target_actor=target_actor, payload=payload
        )

    @property
    def timestamp(self) -> datetime:
        # The IPC header epoch field does not contain a valid Unix timestamp
        # in patch 7.45 (observed value: 64 / 0x40). Return wall-clock time
        # so all handlers get a consistent, usable timestamp.
        return datetime.now(timezone.utc)


HandlerFn = Callable[[IPCHeader], None]


class PacketRouter:
    def __init__(self, config: Config):
        self._config = config
        self._handlers: dict[int, HandlerFn] = {}

    def register(self, opcode: int, handler: HandlerFn):
        self._handlers[opcode] = handler

    def dispatch(self, frame: DeucalionFrame):
        if frame.op not in (3, 4):  # only Recv/Send IPC frames
            return
        try:
            header = IPCHeader.from_bytes(frame.data)
        except (ValueError, struct.error) as e:
            log.debug(f"Failed to parse IPC header: {e}")
            return

        handler = self._handlers.get(header.opcode)
        if handler is None:
            return
        try:
            handler(header)
        except Exception as e:
            log.warning(f"Handler error for opcode {header.opcode:#06x}: {e}")
