# ares/log/writer.py
import os
from datetime import datetime, timezone
from enum import IntEnum
from typing import Optional


class LogMessageType(IntEnum):
    ChatLog = 0
    Territory = 1
    ChangePrimaryPlayer = 2
    AddCombatant = 3
    RemoveCombatant = 4
    PartyList = 11
    PlayerStats = 12
    StartsCasting = 20
    ActionEffect = 21
    AOEActionEffect = 22
    CancelAction = 23
    DoTHoT = 24
    Death = 25
    StatusAdd = 26
    TargetIcon = 27
    WaymarkMarker = 28
    SignMarker = 29
    StatusRemove = 30
    Gauge = 31
    World = 32
    Director = 33
    NameToggle = 34
    Tether = 35
    LimitBreak = 36
    EffectResult = 37
    StatusList = 38
    UpdateHp = 39
    ChangeMap = 40
    SystemLogMessage = 41
    StatusList3 = 42
    Settings = 249
    Debug = 251
    PacketDump = 252
    Version = 253
    Error = 254


def _format_timestamp(ts: datetime) -> str:
    offset = ts.utcoffset()
    if offset is None:
        ts = ts.replace(tzinfo=timezone.utc)
        offset = ts.utcoffset()
    total_seconds = int(offset.total_seconds())
    sign = '+' if total_seconds >= 0 else '-'
    total_seconds = abs(total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    micros = ts.microsecond
    ticks = micros * 10  # convert microseconds to 100-nanosecond ticks
    return f"{ts.strftime('%Y-%m-%dT%H:%M:%S')}.{ticks:07d}{sign}{hours:02d}:{minutes:02d}"


class LogWriter:
    def __init__(self, log_dir: str = 'logs'):
        self._log_dir = log_dir
        self._log_file: Optional[str] = None
        self._file_handle = None
        self._pull_markers: dict[int, int] = {}  # pull_id -> byte offset in log file
        os.makedirs(log_dir, exist_ok=True)

    def format_line(self, msg_type: LogMessageType, timestamp: datetime, payload: str) -> str:
        ts_str = _format_timestamp(timestamp)
        return f"{int(msg_type):02d}|{ts_str}|{payload}"

    def open_session(self, timestamp: datetime) -> str:
        filename = f"Network_{timestamp.strftime('%Y%m%d_%H%M')}.log"
        self._log_file = os.path.join(self._log_dir, filename)
        self._file_handle = open(self._log_file, 'a', encoding='utf-8')
        return self._log_file

    def write(self, msg_type: LogMessageType, timestamp: datetime, payload: str):
        if self._file_handle is None:
            return
        line = self.format_line(msg_type, timestamp, payload)
        self._file_handle.write(line + '\n')
        self._file_handle.flush()

    def mark_pull_start(self, pull_id: int):
        if self._file_handle:
            self._file_handle.flush()
            self._pull_markers[pull_id] = self._file_handle.tell()

    def export_pull(self, pull_id: int, output_dir: str) -> Optional[str]:
        if pull_id not in self._pull_markers or self._log_file is None:
            return None
        start_offset = self._pull_markers[pull_id]
        end_offset = self._pull_markers.get(pull_id + 1)

        with open(self._log_file, 'r', encoding='utf-8') as f:
            f.seek(start_offset)
            if end_offset:
                content = f.read(end_offset - start_offset)
            else:
                content = f.read()

        out_path = os.path.join(output_dir, f"Pull_{pull_id}_{os.path.basename(self._log_file)}")
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return out_path

    def close(self):
        if self._file_handle:
            self._file_handle.close()
            self._file_handle = None
