from pathlib import Path

from fakes import FakeClassifier

from flakehunter.llm import LLMResult
from flakehunter.models import TestFailure
from flakehunter.parsers.junit import parse_junit_glob
from flakehunter.pipeline import run_pipeline

FIXTURES = Path(__file__).parent / "fixtures"
GH = "ghp_" + "A1b2C3d4" * 5


def failures() -> list[TestFailure]:
    return parse_junit_glob(str(FIXTURES / "junit" / "**" / "*.xml"))


def make(n: int, message: str = "AssertionError: 1 != 2") -> list[TestFailure]:
    return [
        TestFailure(id=f"t{i}", suite="s", name=f"t{i}", kind="failure", message=message)
        for i in range(n)
    ]


def test_rules_only() -> None:
    report = run_pipeline(failures())
    assert report.total_failures == 9
    assert report.llm_calls == 0
    assert report.model is None
    by_name = {v.test_name: v for v in report.verdicts}
    assert by_name["test_payment_service_reachable"].decided_by == "rules"
    assert by_name["test_discount_applied"].category == "unknown"


def test_classifier_called_only_for_unsettled() -> None:
    fake = FakeClassifier()
    report = run_pipeline(failures(), classifier=fake)
    called = {call[0] for call in fake.calls}
    assert "test_shop::test_payment_service_reachable" not in called  # settled by a rule
    assert "test_shop::test_discount_applied" in called
    assert report.llm_calls == len(fake.calls) == 7
    assert (report.tokens_in, report.tokens_out) == (700, 140)
    assert (report.model, report.provider) == ("fake-model", "fake")


def test_low_confidence_hint_is_passed_to_classifier() -> None:
    fake = FakeClassifier()
    run_pipeline(failures(), classifier=fake)
    hints = {call[0]: call[2] for call in fake.calls}
    timeout_hint = hints["loads prices in time"]
    assert timeout_hint is not None
    assert timeout_hint.rule == "timeout_generic"


def test_max_failures_cap_and_skipped_count() -> None:
    fake = FakeClassifier()
    report = run_pipeline(make(15), classifier=fake, max_failures=10)
    assert len(report.verdicts) == 10
    assert report.skipped_count == 5
    assert len(fake.calls) == 10
    assert any("5 more failing tests" in n for n in report.notes)


def test_rate_limit_stops_further_calls() -> None:
    fake = FakeClassifier(
        result=LLMResult(verdict=None, error="LLM rate-limited", rate_limited=True)
    )
    report = run_pipeline(make(4), classifier=fake)
    assert len(fake.calls) == 1
    assert len(report.verdicts) == 4
    assert any("rate-limited" in n for n in report.notes)


def test_context_sent_to_classifier_is_redacted() -> None:
    fake = FakeClassifier()
    report = run_pipeline(make(1, f"auth failed: token={GH}"), classifier=fake)
    assert GH not in fake.calls[0][1]
    assert report.secrets_masked >= 1
    assert GH not in report.model_dump_json()


def test_changed_files_reach_classifier() -> None:
    fake = FakeClassifier()
    report = run_pipeline(make(1), classifier=fake, changed_files=["src/pricing.py"])
    assert fake.calls[0][3] == ("src/pricing.py",)
    assert report.verdicts[0].related_changed_files == ("src/pricing.py",)


def test_no_failures() -> None:
    report = run_pipeline([])
    assert (report.total_failures, report.verdicts) == (0, ())
