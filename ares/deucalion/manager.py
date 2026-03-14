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

# Win32 constants
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.wintypes.HANDLE(-1).value
PIPE_READMODE_BYTE = 0x00000000
ERROR_MORE_DATA = 234
ERROR_PIPE_NOT_CONNECTED = 233
ERROR_BROKEN_PIPE = 109

# Properly typed kernel32 functions with use_last_error=True
_k32 = ctypes.WinDLL('kernel32', use_last_error=True)

_CreateFileW = _k32.CreateFileW
_CreateFileW.restype = ctypes.wintypes.HANDLE
_CreateFileW.argtypes = [
    ctypes.wintypes.LPCWSTR, ctypes.wintypes.DWORD, ctypes.wintypes.DWORD,
    ctypes.c_void_p, ctypes.wintypes.DWORD, ctypes.wintypes.DWORD, ctypes.wintypes.HANDLE
]

_ReadFile = _k32.ReadFile
_ReadFile.restype = ctypes.wintypes.BOOL
_ReadFile.argtypes = [
    ctypes.wintypes.HANDLE, ctypes.c_void_p, ctypes.wintypes.DWORD,
    ctypes.POINTER(ctypes.wintypes.DWORD), ctypes.c_void_p
]

_CloseHandle = _k32.CloseHandle
_CloseHandle.restype = ctypes.wintypes.BOOL
_CloseHandle.argtypes = [ctypes.wintypes.HANDLE]

_SetNamedPipeHandleState = _k32.SetNamedPipeHandleState
_SetNamedPipeHandleState.restype = ctypes.wintypes.BOOL
_SetNamedPipeHandleState.argtypes = [
    ctypes.wintypes.HANDLE, ctypes.POINTER(ctypes.wintypes.DWORD),
    ctypes.c_void_p, ctypes.c_void_p
]


def find_ffxiv_pid() -> Optional[int]:
    """Find FFXIV process ID using Windows API."""
    import psutil
    for proc in psutil.process_iter(['pid', 'name']):
        if proc.info['name'] and proc.info['name'].lower() == FFXIV_EXE:
            return proc.info['pid']
    return None


def _pipe_name(pid: int) -> str:
    return f"{PIPE_BASE}{pid}"


def _try_open_pipe(pid: int) -> Optional[ctypes.wintypes.HANDLE]:
    """Try to open the Deucalion named pipe. Returns handle or None."""
    name = _pipe_name(pid)
    handle = _CreateFileW(name, GENERIC_READ | GENERIC_WRITE, 0, None, OPEN_EXISTING, 0, None)
    if handle == INVALID_HANDLE_VALUE:
        err = ctypes.get_last_error()
        log.debug(f"CreateFileW({name}) failed: error {err}")
        return None
    return handle


def _read_from_pipe(handle: ctypes.wintypes.HANDLE, max_size: int = 65536) -> bytes:
    """Read from pipe. Returns data bytes. Raises OSError on failure."""
    buf = ctypes.create_string_buffer(max_size)
    bytes_read = ctypes.wintypes.DWORD(0)

    ok = _ReadFile(handle, buf, max_size, ctypes.byref(bytes_read), None)

    if ok:
        if bytes_read.value == 0:
            raise OSError("Pipe returned 0 bytes (closed)")
        return buf.raw[:bytes_read.value]

    err = ctypes.get_last_error()

    if err == ERROR_MORE_DATA:
        # Got partial message, collect the rest
        data = buf.raw[:bytes_read.value]
        while True:
            buf2 = ctypes.create_string_buffer(max_size)
            br2 = ctypes.wintypes.DWORD(0)
            ok2 = _ReadFile(handle, buf2, max_size, ctypes.byref(br2), None)
            data += buf2.raw[:br2.value]
            if ok2:
                break
            err2 = ctypes.get_last_error()
            if err2 != ERROR_MORE_DATA:
                raise OSError(f"Pipe read continuation failed: Win32 error {err2}")
        return data

    if err in (ERROR_BROKEN_PIPE, ERROR_PIPE_NOT_CONNECTED):
        raise OSError(f"Pipe disconnected: Win32 error {err}")

    raise OSError(f"ReadFile failed: Win32 error {err}")


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
        handle = _try_open_pipe(pid)
        if handle is not None:
            log.info(f"Found existing Deucalion pipe for PID {pid}")
            return self._setup_pipe(handle)

        # Step 2: No existing pipe -- inject if allowed
        if not self._allow_inject:
            log.info(f"No Deucalion pipe for PID {pid}. "
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
            handle = _try_open_pipe(pid)
            if handle is not None:
                log.info(f"Deucalion pipe appeared after {(attempt + 1) * 0.5:.1f}s")
                return self._setup_pipe(handle)

        log.warning("Deucalion pipe did not appear after injection")
        return False

    def _setup_pipe(self, handle: ctypes.wintypes.HANDLE) -> bool:
        """Configure pipe and mark as connected."""
        # Try to set pipe to byte read mode
        mode = ctypes.wintypes.DWORD(PIPE_READMODE_BYTE)
        ok = _SetNamedPipeHandleState(handle, ctypes.byref(mode), None, None)
        if ok:
            log.info("Pipe set to byte read mode")
        else:
            err = ctypes.get_last_error()
            log.info(f"Could not set byte mode (error {err}), using default mode")

        self._pipe_handle = handle
        self.connected = True
        log.info(f"Connected to Deucalion pipe")
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
                _CloseHandle(self._pipe_handle)
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
                log.warning(f"Pipe error: {e}")
                self.connected = False
                if self._pipe_handle is not None:
                    try:
                        _CloseHandle(self._pipe_handle)
                    except Exception:
                        pass
                    self._pipe_handle = None

    def _read_frames(self):
        while self._running and self._pipe_handle is not None:
            raw = _read_from_pipe(self._pipe_handle)
            if len(raw) < 4:
                log.debug(f"Short read: {len(raw)} bytes, skipping")
                continue

            op, channel, length = struct.unpack_from('<BBH', raw, 0)
            log.debug(f"Frame: op={op} ch={channel} len={length} raw_len={len(raw)}")

            # Skip ping/pong
            if op in (3, 4):
                continue

            data = raw[4:]
            frame = DeucalionFrame(op=op, channel=channel, data=data)
            for cb in self._callbacks:
                try:
                    cb(frame)
                except Exception as e:
                    log.warning(f"Frame callback error: {e}")
