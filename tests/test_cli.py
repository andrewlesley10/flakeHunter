import json
from pathlib import Path

import pytest

from flakehunter import cli
from flakehunter.cli import main
from flakehunter.pipeline import Report

FIXTURES = Path(__file__).parent / "fixtures"
JUNIT = str(FIXTURES / "junit" / "**" / "*.xml")


def test_analyze_markdown(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        ["analyze", "--junit", JUNIT, "--diff", str(FIXTURES / "diff" / "pr.diff"), "--no-llm"]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith("<!-- flakehunter -->")
    assert "9 failing tests analysed" in out
    assert "selector" in out  # the Cypress failure is matched against the diff


def test_analyze_json_validates(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["analyze", "--junit", JUNIT, "--no-llm", "--format", "json"]) == 0
    report = Report.model_validate_json(capsys.readouterr().out)
    assert report.total_failures == 9


def test_retry_report_marks_flaky(capsys: pytest.CaptureFixture[str]) -> None:
    retry = FIXTURES / "retry"
    args = [
        "analyze",
        "--junit",
        str(retry / "first.xml"),
        "--retry-report",
        str(retry / "retry.xml"),
    ]
    main([*args, "--no-llm", "--format", "json"])
    report = json.loads(capsys.readouterr().out)
    assert {v["test_name"]: v["category"] for v in report["verdicts"]} == {
        "test_order_confirmation_arrives": "flaky_test",
        "test_discount_applied": "unknown",
    }


def test_no_failures_message(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "ok.xml").write_text('<testsuite name="s"><testcase name="t"/></testsuite>')
    assert main(["analyze", "--junit", str(tmp_path / "*.xml"), "--no-llm"]) == 0
    captured = capsys.readouterr()
    assert "No failing tests found" in captured.err
    assert "no failing tests found" in captured.out


def test_internal_error_returns_zero_with_warning(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*_: object, **__: object) -> Report:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(cli, "run_pipeline", boom)
    assert main(["analyze", "--junit", JUNIT, "--no-llm"]) == 0
    assert "flakehunter: warning: RuntimeError: kaboom" in capsys.readouterr().err


def test_strict_reraises(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: object, **__: object) -> Report:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(cli, "run_pipeline", boom)
    with pytest.raises(RuntimeError):
        main(["analyze", "--junit", JUNIT, "--no-llm", "--strict"])


def test_missing_diff_file_fails_open(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["analyze", "--junit", JUNIT, "--diff", "nope.diff", "--no-llm"]) == 0
    assert "warning" in capsys.readouterr().err


def test_ollama_down_still_reports(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Point at a closed port: every model call fails, the report falls back to rules.
    monkeypatch.setenv("FLAKEHUNTER_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("FLAKEHUNTER_TIMEOUT_S", "2")
    code = main(["analyze", "--junit", str(FIXTURES / "junit" / "pytest" / "report.xml")])
    out = capsys.readouterr().out
    assert code == 0
    assert "fallback" in out
    assert "connection_refused" in out
