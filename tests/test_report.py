import os
from pathlib import Path

from fakes import FakeClassifier
from test_pipeline import failures

from flakehunter.models import FinalVerdict
from flakehunter.parsers.diff import changed_files, load_diff
from flakehunter.pipeline import Report, run_pipeline
from flakehunter.report import MARKER, escape_cell, to_json, to_markdown

GOLDEN = Path(__file__).parent / "golden" / "report.md"
FIXTURES = Path(__file__).parent / "fixtures"


def fixed_report() -> Report:
    """A report with everything that varies between runs pinned."""
    diff = changed_files(load_diff(FIXTURES / "diff" / "pr.diff"))
    report = run_pipeline(failures(), classifier=FakeClassifier(), changed_files=diff)
    return report.model_copy(update={"elapsed_s": 1.25, "version": "9.9.9"})


def test_markdown_matches_golden() -> None:
    rendered = to_markdown(fixed_report())
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.write_text(rendered, encoding="utf-8")
    assert rendered == GOLDEN.read_text(encoding="utf-8")


def test_markdown_starts_with_marker() -> None:
    assert to_markdown(fixed_report()).startswith(MARKER)


def test_empty_report() -> None:
    md = to_markdown(Report())
    assert md.startswith(MARKER)
    assert "no failing tests" in md


def test_table_cell_escaping() -> None:
    assert escape_cell("a | b `c` <script>\n@octocat") == "a \\| b 'c' &lt;script&gt; @​octocat"


def test_hostile_test_name_cannot_break_table() -> None:
    v = FinalVerdict(
        test_id="x",
        test_name="evil | name `x` </summary> @team",
        category="unknown",
        confidence=0.0,
        likely_cause="c",
        suggested_next_step="s",
        decided_by="fallback",
    )
    md = to_markdown(Report(verdicts=(v,)))
    row = next(line for line in md.splitlines() if line.startswith("| `evil"))
    assert row.count(" | ") == 3  # still exactly four columns
    assert "</summary> @team" not in md
    assert "@team" not in md.replace("@​team", "")


def test_evidence_with_backticks_keeps_fence() -> None:
    v = FinalVerdict(
        test_id="x",
        test_name="x",
        category="unknown",
        confidence=0.0,
        likely_cause="c",
        evidence=("```", "after"),
        suggested_next_step="s",
        decided_by="fallback",
    )
    assert "````text" in to_markdown(Report(verdicts=(v,)))


def test_footer_shows_cost() -> None:
    md = to_markdown(fixed_report())
    assert "fake-model via fake" in md
    assert "7 model calls" in md
    assert "840 tokens" in md
    assert "FlakeHunter v9.9.9" in md


def test_json_roundtrip() -> None:
    report = fixed_report()
    assert Report.model_validate_json(to_json(report)) == report
