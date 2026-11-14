from pathlib import Path

import pytest

from flakehunter.parsers.junit import UnsafeXMLError, parse_junit, parse_outcomes
from flakehunter.parsers.retry import load_retry_report

RETRY = Path(__file__).parent / "fixtures" / "retry"


def junit(cases: str) -> str:
    return f'<?xml version="1.0"?><testsuites><testsuite name="s">{cases}</testsuite></testsuites>'


PASS = '<testcase classname="m" name="t"/>'
FAIL = '<testcase classname="m" name="t"><failure message="x">x</failure></testcase>'
SKIP = '<testcase classname="m" name="t"><skipped/></testcase>'


def test_parse_outcomes_includes_passing_tests() -> None:
    assert parse_outcomes(RETRY / "first.xml") == {
        "test_checkout::test_basket_total": "passed",
        "test_checkout::test_order_confirmation_arrives": "failed",
        "test_checkout::test_discount_applied": "failed",
    }


def test_retry_report_real_pytest_lf_run() -> None:
    assert load_retry_report(str(RETRY / "retry.xml")) == {
        "test_checkout::test_order_confirmation_arrives": "passed",  # flaky
        "test_checkout::test_discount_applied": "failed",  # real bug
    }


def test_retry_ids_match_failure_ids() -> None:
    """The whole point: ids from the first run must join to ids in the retry report."""
    failure_ids = {f.id for f in parse_junit(RETRY / "first.xml")}
    retry = load_retry_report(str(RETRY / "retry.xml"))
    assert failure_ids == set(retry)


def test_any_pass_across_multiple_retries_wins(tmp_path: Path) -> None:
    (tmp_path / "retry-1.xml").write_text(junit(FAIL))
    (tmp_path / "retry-2.xml").write_text(junit(PASS))
    (tmp_path / "retry-3.xml").write_text(junit(FAIL))
    assert load_retry_report(str(tmp_path / "*.xml")) == {"m::t": "passed"}


def test_skipped_on_retry_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "retry.xml").write_text(junit(SKIP))
    assert load_retry_report(str(tmp_path / "retry.xml")) == {}


def test_empty_pattern_and_no_match(tmp_path: Path) -> None:
    assert load_retry_report("") == {}
    assert load_retry_report(str(tmp_path / "*.xml")) == {}


def test_retry_report_rejects_dtd(tmp_path: Path) -> None:
    evil = tmp_path / "retry.xml"
    evil.write_text('<?xml version="1.0"?><!DOCTYPE t [<!ENTITY a "b">]>' + junit(PASS)[21:])
    with pytest.raises(UnsafeXMLError):
        load_retry_report(str(evil))
