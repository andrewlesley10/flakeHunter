from pathlib import Path

import pytest

from flakehunter.parsers.logs import load_log, load_logs, strip_ansi

LOGS = Path(__file__).parent / "fixtures" / "logs"


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("\x1b[31mFAILED\x1b[0m", "FAILED"),
        ("\x1b[1m\x1b[31mbold red\x1b[0m", "bold red"),
        ("\x1b[38;5;196mcolour 256\x1b[0m", "colour 256"),
        ("\x1b[2Kcleared line", "cleared line"),
        ("\x1b]0;window title\x07text", "text"),
        ("no codes here", "no codes here"),
    ],
)
def test_strip_ansi(raw: str, clean: str) -> None:
    assert strip_ansi(raw) == clean


def test_load_log_has_no_escape_codes() -> None:
    lines = load_log(LOGS / "pytest-run.log")
    assert not any("\x1b" in line for line in lines)
    assert "E       ConnectionRefusedError: [Errno 111] Connection refused" in lines


def test_load_log_strips_line_endings() -> None:
    lines = load_log(LOGS / "pytest-run.log")
    assert not any(line.endswith(("\r", "\n")) for line in lines)
    assert lines[-1] == "Error: Process completed with exit code 1."


def test_load_log_tolerates_invalid_utf8() -> None:
    lines = load_log(LOGS / "bad-encoding.log")
    assert lines[0] == "line one"
    assert "�" in lines[1]  # replacement character instead of a crash
    assert lines[2] == "line three"


def test_load_logs_glob_is_sorted_and_keyed_by_path() -> None:
    logs = load_logs(str(LOGS / "*.log"))
    assert list(logs) == sorted(logs)
    assert len(logs) == 2


def test_load_logs_empty_pattern_returns_empty() -> None:
    assert load_logs("") == {}


def test_load_logs_no_match_returns_empty(tmp_path: Path) -> None:
    assert load_logs(str(tmp_path / "*.log")) == {}
