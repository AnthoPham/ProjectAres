# tests/test_deucalion.py
import pytest
from unittest.mock import MagicMock, patch
from ares.deucalion.manager import DeucalionManager

def test_manager_init():
    mgr = DeucalionManager(dll_path="bin/deucalion.dll")
    assert mgr.connected is False

def test_find_process_returns_none_when_not_running():
    mgr = DeucalionManager(dll_path="bin/deucalion.dll")
    with patch('ares.deucalion.manager.find_ffxiv_pid', return_value=None):
        pid = mgr._find_process()
    assert pid is None

def test_connect_returns_false_when_no_process():
    mgr = DeucalionManager(dll_path="bin/deucalion.dll")
    with patch.object(mgr, '_find_process', return_value=None):
        result = mgr.connect()
    assert result is False
    assert mgr.connected is False

def test_on_frame_callback_registered():
    mgr = DeucalionManager(dll_path="bin/deucalion.dll")
    called = []
    mgr.on_frame(lambda frame: called.append(frame))
    assert len(mgr._callbacks) == 1
