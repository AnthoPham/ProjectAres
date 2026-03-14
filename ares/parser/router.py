# ares/parser/router.py
import struct
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Callable, Optional
from ares.config import Config

log = logging.getLogger(__name__)

_EPOCH_BASE = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass
class DeucalionFrame:
    op: int       # 1=Recv, 2=Send, 3=Ping, 4=Pong
    channel: int  # 1=recv, 2=send
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
class IPCHeader:
    magic: int
    opcode: int
    server_id: int
    epoch: int    # milliseconds since unix epoch
    payload: bytes

    @classmethod
    def from_bytes(cls, data: bytes) -> 'IPCHeader':
        if len(data) < 16:
            raise ValueError(f"IPC data too short: {len(data)} bytes")
        magic, opcode, _pad, server_id, epoch = struct.unpack_from('<HHHHI', data, 0)
        payload = data[16:]
        return cls(magic=magic, opcode=opcode, server_id=server_id, epoch=epoch, payload=payload)

    @property
    def timestamp(self) -> datetime:
        return _EPOCH_BASE + timedelta(milliseconds=self.epoch)


HandlerFn = Callable[[IPCHeader], None]


class PacketRouter:
    def __init__(self, config: Config):
        self._config = config
        self._handlers: dict[int, HandlerFn] = {}

    def register(self, opcode: int, handler: HandlerFn):
        self._handlers[opcode] = handler

    def dispatch(self, frame: DeucalionFrame):
        if frame.op not in (1, 2):  # only Recv/Send IPC frames
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
