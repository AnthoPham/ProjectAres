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

PIPE_BASE = r'\\.\pipe\deucalion-'
FFXIV_EXE = 'ffxiv_dx11.exe'

# Win32 constants for named pipe access
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.wintypes.HANDLE(-1).value
PIPE_READMODE_BYTE = 0x00000000
PIPE_READMODE_MESSAGE = 0x00000002
ERROR_MORE_DATA = 234


def find_ffxiv_pid() -> Optional[int]:
    """Find FFXIV process ID using Windows API."""
    import psutil
    for proc in psutil.process_iter(['pid', 'name']):
        if proc.info['name'] and proc.info['name'].lower() == FFXIV_EXE:
            return proc.info['pid']
    return None


def _pipe_exists(pid: int) -> bool:
    """Check if Deucalion named pipe already exists for this PID."""
    pipe_name = f"{PIPE_BASE}{pid}"
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateFileW(
        pipe_name,
        GENERIC_READ | GENERIC_WRITE,
        0, None, OPEN_EXISTING, 0, None
    )
    if handle == INVALID_HANDLE_VALUE:
        return False
    kernel32.CloseHandle(handle)
    return True


def _open_pipe(pid: int) -> Optional[int]:
    """Open Deucalion named pipe using Win32 API. Returns handle or None."""
    pipe_name = f"{PIPE_BASE}{pid}"
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateFileW(
        pipe_name,
        GENERIC_READ | GENERIC_WRITE,
        0, None, OPEN_EXISTING, 0, None
    )
    if handle == INVALID_HANDLE_VALUE:
        return None
    return handle


def _read_message(handle: int) -> bytes:
    """Read a complete message from a Win32 message-mode pipe."""
    # Start with a reasonable buffer size
    buf_size = 65536
    buf = ctypes.create_string_buffer(buf_size)
    bytes_read = ctypes.wintypes.DWORD(0)

    result = ctypes.windll.kernel32.ReadFile(
        handle, buf, buf_size, ctypes.byref(bytes_read), None
    )

    if result:
        # Complete message read
        return buf.raw[:bytes_read.value]

    error = ctypes.GetLastError()
    if error == ERROR_MORE_DATA:
        # Message larger than buffer -- collect remaining
        data = buf.raw[:bytes_read.value]
        while True:
            buf2 = ctypes.create_string_buffer(buf_size)
            bytes_read2 = ctypes.wintypes.DWORD(0)
            result = ctypes.windll.kernel32.ReadFile(
                handle, buf2, buf_size, ctypes.byref(bytes_read2), None
            )
            data += buf2.raw[:bytes_read2.value]
            if result:
                break
            if ctypes.GetLastError() != ERROR_MORE_DATA:
                raise OSError(f"Pipe read failed: error {ctypes.GetLastError()}")
        return data

    raise OSError(f"Pipe read failed: error {error}")


def _read_pipe(handle: int, size: int) -> bytes:
    """Read exactly size bytes from a Win32 pipe handle (byte mode)."""
    buf = ctypes.create_string_buffer(size)
    bytes_read = ctypes.wintypes.DWORD(0)
    result = ctypes.windll.kernel32.ReadFile(
        handle, buf, size, ctypes.byref(bytes_read), None
    )
    if not result:
        error = ctypes.GetLastError()
        if error == ERROR_MORE_DATA:
            log.debug(f"Pipe in message mode, got {bytes_read.value} of {size} bytes")
        raise OSError(f"Pipe read failed: error {error}")
    if bytes_read.value == 0:
        raise OSError("Pipe closed")
    if bytes_read.value < size:
        remaining = size - bytes_read.value
        data = buf.raw[:bytes_read.value]
        while remaining > 0:
            buf2 = ctypes.create_string_buffer(remaining)
            bytes_read2 = ctypes.wintypes.DWORD(0)
            result = ctypes.windll.kernel32.ReadFile(
                handle, buf2, remaining, ctypes.byref(bytes_read2), None
            )
            if not result or bytes_read2.value == 0:
                raise OSError("Pipe read failed during partial read")
            data += buf2.raw[:bytes_read2.value]
            remaining -= bytes_read2.value
        return data
    return buf.raw[:bytes_read.value]


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

    def __init__(self, dll_path: str = 'bin/deucalion.dll', allow_inject: bool = False):
        self._dll_path = dll_path
        self._allow_inject = allow_inject
        self._pipe_handle = None
        self._pid: Optional[int] = None
        self._message_mode = False
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

        self._pid = pid

        # Step 1: Try connecting to existing pipe (injected by ACT/Machina)
        if _pipe_exists(pid):
            log.info(f"Found existing Deucalion pipe for PID {pid}")
            return self._connect_pipe(pid)

        # Step 2: No existing pipe -- inject if allowed
        if not self._allow_inject:
            log.info(f"No Deucalion pipe found for PID {pid}. "
                     f"Start ACT/Machina first, or use --inject flag.")
            return False

        log.info(f"No existing pipe found. Injecting Deucalion into PID {pid}...")
        if not os.path.exists(self._dll_path):
            log.error(f"Deucalion DLL not found at {self._dll_path}")
            return False

        if not _inject_dll(pid, self._dll_path):
            log.warning("DLL injection failed")
            return False

        # Wait for Deucalion to initialize and create the pipe
        for attempt in range(10):
            time.sleep(0.5)
            if _pipe_exists(pid):
                log.info(f"Deucalion pipe appeared after {(attempt + 1) * 0.5:.1f}s")
                return self._connect_pipe(pid)

        log.warning("Deucalion pipe did not appear after injection")
        return False

    def _connect_pipe(self, pid: int) -> bool:
        """Connect to Deucalion named pipe for given PID."""
        handle = _open_pipe(pid)
        if handle is None:
            log.warning(f"Could not open Deucalion pipe for PID {pid}")
            return False

        # Try to set pipe to byte read mode for easier reading
        mode = ctypes.wintypes.DWORD(PIPE_READMODE_BYTE)
        result = ctypes.windll.kernel32.SetNamedPipeHandleState(
            handle, ctypes.byref(mode), None, None
        )
        if result:
            log.info("Pipe set to byte read mode")
            self._message_mode = False
        else:
            log.info("Pipe staying in message mode (SetNamedPipeHandleState failed)")
            self._message_mode = True

        self._pipe_handle = handle
        self.connected = True
        log.info(f"Connected to Deucalion pipe for PID {pid}")
        return True

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="DeucalionManager")
        self._thread.start()

    def stop(self):
        self._running = False
        self.connected = False
        if self._pipe_handle is not None:
            try:
                ctypes.windll.kernel32.CloseHandle(self._pipe_handle)
            except Exception:
                pass
            self._pipe_handle = None
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
            except OSError as e:
                log.warning(f"Pipe disconnected: {e}")
                self.connected = False
                if self._pipe_handle is not None:
                    try:
                        ctypes.windll.kernel32.CloseHandle(self._pipe_handle)
                    except Exception:
                        pass
                    self._pipe_handle = None

    def _read_frames(self):
        while self._running and self._pipe_handle is not None:
            if self._message_mode:
                self._read_frame_message_mode()
            else:
                self._read_frame_byte_mode()

    def _read_frame_message_mode(self):
        """Read a complete pipe message and parse as Deucalion frame."""
        raw = _read_message(self._pipe_handle)
        if len(raw) < 4:
            log.debug(f"Short message: {len(raw)} bytes")
            return

        op, channel, length = struct.unpack_from('<BBH', raw, 0)

        if op == 3:  # Ping
            return

        data = raw[4:]
        if len(data) < length:
            log.debug(f"Message data shorter than header length: {len(data)} < {length}")
            data = raw[4:]  # use what we have

        frame = DeucalionFrame(op=op, channel=channel, data=data)
        self._dispatch_frame(frame)

    def _read_frame_byte_mode(self):
        """Read frame header + data in byte mode."""
        header = _read_pipe(self._pipe_handle, 4)
        op, channel, length = struct.unpack('<BBH', header)

        if op == 3:  # Ping
            return

        if length == 0:
            return

        data = _read_pipe(self._pipe_handle, length)
        frame = DeucalionFrame(op=op, channel=channel, data=data)
        self._dispatch_frame(frame)

    def _dispatch_frame(self, frame: DeucalionFrame):
        for cb in self._callbacks:
            try:
                cb(frame)
            except Exception as e:
                log.warning(f"Frame callback error: {e}")
