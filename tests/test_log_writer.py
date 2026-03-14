# tests/test_log_writer.py
import pytest
from datetime import datetime, timezone, timedelta
from ares.log.writer import LogWriter, LogMessageType

@pytest.fixture
def writer(tmp_path):
    return LogWriter(log_dir=str(tmp_path))

def test_log_message_type_values():
    assert LogMessageType.ChatLog == 0
    assert LogMessageType.Territory == 1
    assert LogMessageType.AddCombatant == 3
    assert LogMessageType.ActionEffect == 21
    assert LogMessageType.AOEActionEffect == 22
    assert LogMessageType.DoTHoT == 24
    assert LogMessageType.Death == 25
    assert LogMessageType.StatusAdd == 26
    assert LogMessageType.UpdateHp == 39

def test_format_death_line(writer):
    ts = datetime(2026, 3, 13, 20, 4, 33, 123000, tzinfo=timezone(timedelta(hours=-5)))
    line = writer.format_line(LogMessageType.Death, ts, "00001234|Vatarris|00005678|Ketuduke")
    assert line.startswith("25|2026-03-13T20:04:33.1230000-05:00|")
    assert "00001234|Vatarris|00005678|Ketuduke" in line

def test_format_territory_line(writer):
    ts = datetime(2026, 3, 13, 20, 0, 0, tzinfo=timezone(timedelta(hours=-5)))
    line = writer.format_line(LogMessageType.Territory, ts, "0062|Anabaseios: The Twelfth Circle (Savage)")
    assert line.startswith("01|")
    assert "Anabaseios" in line

def test_write_line_creates_file(writer, tmp_path):
    ts = datetime(2026, 3, 13, 20, 4, 33, tzinfo=timezone(timedelta(hours=-5)))
    writer.open_session(ts)
    writer.write(LogMessageType.Death, ts, "00001234|Vatarris|00005678|Ketuduke")
    log_files = list(tmp_path.glob("Network_*.log"))
    assert len(log_files) == 1
    content = log_files[0].read_text()
    assert "25|" in content

def test_log_filename_format(writer, tmp_path):
    ts = datetime(2026, 3, 13, 20, 4, 33, tzinfo=timezone(timedelta(hours=-5)))
    writer.open_session(ts)
    log_files = list(tmp_path.glob("Network_*.log"))
    assert log_files[0].name == "Network_20260313_2004.log"

def test_export_pull_segment(writer, tmp_path):
    ts = datetime(2026, 3, 13, 20, 4, 33, tzinfo=timezone(timedelta(hours=-5)))
    writer.open_session(ts)
    writer.write(LogMessageType.Death, ts, "00001234|Vatarris|00005678|Ketuduke")
    writer.mark_pull_start(pull_id=1)
    writer.write(LogMessageType.ActionEffect, ts, "00001234|Vatarris|0009|Fast Blade|00005678|Ketuduke|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|")
    export_path = writer.export_pull(pull_id=1, output_dir=str(tmp_path))
    assert export_path is not None
    content = open(export_path).read()
    assert "Fast Blade" in content
    assert "Vatarris|00005678|Ketuduke" not in content  # pre-pull line excluded
