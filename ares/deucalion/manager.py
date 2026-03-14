# ares/deucalion/manager.py
import ctypes
import ctypes.wintypes
import logging
import os
import struct
import threading
import time
from typing import Callable, Optional

from ares.parser.router import DeucalionFrame

log = logging.getLogger(__name__)

PIPE_NAME = r'\\.\pipe\deucalion'
FFXIV_EXE = 'ffxiv_dx11.exe'


def find_ffxiv_pid() -> Optional[int]:
    """Find FFXIV process ID using Windows API."""
    import psutil
    for proc in psutil.process_iter(['pid', 'name']):
        if proc.info['name'] and proc.info['name'].lower() == FFXIV_EXE:
            return proc.info['pid']
    return None


def _inject_dll(pid: int, dll_path: str) -> bool:
    """Inject DLL into target process using CreateRemoteThread + LoadLibrary."""
    abs_path = os.path.abspath(dll_path).encode('utf-8') + b'\x00'
    kernel32 = ctypes.windll.kernel32

    h_process = kernel32.OpenProcess(0x1F0FFF, False, pid)
    if not h_process:
        log.error(f"OpenProcess failed for PID {pid}")
        return False

    try:
        remote_mem = kernel32.VirtualAllocEx(
            h_process, None, len(abs_path),
            0x3000,  # MEM_COMMIT | MEM_RESERVE
            0x04     # PAGE_READWRITE
        )
        if not remote_mem:
            log.error("VirtualAllocEx failed")
            return False

        written = ctypes.c_size_t(0)
        kernel32.WriteProcessMemory(h_process, remote_mem, abs_path, len(abs_path), ctypes.byref(written))

        load_library = kernel32.GetProcAddress(kernel32.GetModuleHandleW('kernel32.dll'), b'LoadLibraryA')
        h_thread = kernel32.CreateRemoteThread(h_process, None, 0, load_library, remote_mem, 0, None)
        if not h_thread:
            log.error("CreateRemoteThread failed")
            return False

        kernel32.WaitForSingleObject(h_thread, 5000)
        kernel32.CloseHandle(h_thread)
        log.info(f"DLL injected into PID {pid}")
        return True
    finally:
        kernel32.CloseHandle(h_process)


FrameCallback = Callable[[DeucalionFrame], None]


class DeucalionManager:
    RECONNECT_INTERVAL = 3.0

    def __init__(self, dll_path: str = 'bin/deucalion.dll'):
        self._dll_path = dll_path
        self._pipe = None
        self._callbacks: list[FrameCallback] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.connected = False

    def on_frame(self, callback: FrameCallback):
        self._callbacks.append(callback)

    def _find_process(self) -> Optional[int]:
        return find_ffxiv_pid()

    def connect(self) -> bool:
        pid = self._find_process()
        if pid is None:
            log.debug("FFXIV not running")
            return False

        if not _inject_dll(pid, self._dll_path):
            log.warning("DLL injection failed")
            return False

        # Give Deucalion time to initialize
        time.sleep(1.0)

        try:
            self._pipe = open(PIPE_NAME, 'rb')
            self.connected = True
            log.info("Connected to Deucalion named pipe")
            return True
        except OSError as e:
            log.warning(f"Could not open Deucalion pipe: {e}")
            return False

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="DeucalionManager")
        self._thread.start()

    def stop(self):
        self._running = False
        self.connected = False
        if self._pipe:
            try:
                self._pipe.close()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=3.0)

    def _run_loop(self):
        while self._running:
            if not self.connected:
                if not self.connect():
                    time.sleep(self.RECONNECT_INTERVAL)
                    continue

            try:
                self._read_frames()
            except (OSError, BrokenPipeError) as e:
                log.warning(f"Pipe disconnected: {e}")
                self.connected = False
                if self._pipe:
                    try:
                        self._pipe.close()
                    except Exception:
                        pass
                    self._pipe = None

    def _read_frames(self):
        while self._running and self._pipe:
            # Read 4-byte frame header
            header = self._pipe.read(4)
            if len(header) < 4:
                raise OSError("Pipe closed")

            op, channel, length = struct.unpack('<BBH', header)

            # Respond to ping with pong
            if op == 3:
                continue

            data = self._pipe.read(length)
            if len(data) < length:
                raise OSError("Incomplete frame")

            frame = DeucalionFrame(op=op, channel=channel, data=data)
            for cb in self._callbacks:
                try:
                    cb(frame)
                except Exception as e:
                    log.warning(f"Frame callback error: {e}")
