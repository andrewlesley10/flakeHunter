from pathlib import Path

import pytest

from flakehunter.models import TestFailure
from flakehunter.parsers.junit import UnsafeXMLError, parse_junit, parse_junit_glob

FIXTURES = Path(__file__).parent / "fixtures" / "junit"
PYTEST = FIXTURES / "pytest" / "report.xml"
JEST = FIXTURES / "jest" / "junit.xml"
CYPRESS = FIXTURES / "cypress" / "checkout.xml"
SUREFIRE = FIXTURES / "surefire" / "TEST-com.example.CartTest.xml"


def by_name(failures: list[TestFailure]) -> dict[str, TestFailure]:
    return {f.name: f for f in failures}


# --- pytest -----------------------------------------------------------------


def test_pytest_failures_and_error() -> None:
    failures = parse_junit(PYTEST)
    kinds = sorted(f.kind for f in failures)
    assert kinds == ["error", "failure", "failure"]
    assert by_name(failures)["test_uses_broken_fixture"].kind == "error"


def test_pytest_skipped_and_passed_ignored() -> None:
    names = set(by_name(parse_junit(PYTEST)))
    assert "test_refunds" not in names
    assert "test_total_without_discount" not in names


def test_pytest_connection_refused_captured() -> None:
    f = by_name(parse_junit(PYTEST))["test_payment_service_reachable"]
    assert "Connection refused" in f.message
    assert "Connection refused" in f.details


def test_pytest_has_no_file_attribute() -> None:
    assert all(f.file is None for f in parse_junit(PYTEST))


def test_pytest_id_uses_classname() -> None:
    f = by_name(parse_junit(PYTEST))["test_discount_applied"]
    assert f.id == "test_shop::test_discount_applied"


# --- Jest -------------------------------------------------------------------


def test_jest_message_falls_back_to_first_line() -> None:
    f = by_name(parse_junit(JEST))["totals two items"]
    assert f.message.startswith("Error: expect(received).toBe(expected)")


def test_jest_names_are_stripped() -> None:
    for f in parse_junit(JEST):
        assert f.name == f.name.strip()
        assert f.id == f.name  # classname == name in Jest, so no "x::x" ids


def test_jest_has_file() -> None:
    assert {f.file for f in parse_junit(JEST)} == {"cart.test.js"}


def test_jest_all_failures_not_errors() -> None:
    failures = parse_junit(JEST)
    assert len(failures) == 3
    assert {f.kind for f in failures} == {"failure"}


# --- Cypress ----------------------------------------------------------------


def test_cypress_file_from_root_suite() -> None:
    (f,) = parse_junit(CYPRESS)
    assert f.file == "cypress/e2e/checkout.cy.ts"
    assert f.suite == "Checkout"
    assert "#buy-btn" in f.message


# --- Surefire ---------------------------------------------------------------


def test_surefire_without_wrapper() -> None:
    failures = by_name(parse_junit(SUREFIRE))
    assert set(failures) == {"totalAppliesDiscount", "loadsPricesFromDb"}
    assert failures["loadsPricesFromDb"].kind == "error"


def test_surefire_message_is_unescaped() -> None:
    f = by_name(parse_junit(SUREFIRE))["totalAppliesDiscount"]
    assert f.message == "expected: <81.0> but was: <90.0>"


def test_surefire_flaky_failure_not_reported() -> None:
    assert "checkoutIsIdempotent" not in by_name(parse_junit(SUREFIRE))


# --- all formats ------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    [(PYTEST, "pytest"), (JEST, "jest"), (CYPRESS, "cypress"), (SUREFIRE, "surefire")],
)
def test_format_detection(path: Path, expected: str) -> None:
    assert {f.source_format for f in parse_junit(path)} == {expected}


@pytest.mark.parametrize("path", [PYTEST, JEST, CYPRESS, SUREFIRE])
def test_required_fields_populated(path: Path) -> None:
    for f in parse_junit(path):
        assert f.id
        assert f.name
        assert f.message
        assert f.details
        assert f.duration_s is not None


def test_glob_parses_all_fixtures() -> None:
    failures = parse_junit_glob(str(FIXTURES / "**" / "*.xml"))
    assert len(failures) == 9  # pytest 3 + jest 3 + cypress 1 + surefire 2


def test_glob_ids_are_unique() -> None:
    ids = [f.id for f in parse_junit_glob(str(FIXTURES / "**" / "*.xml"))]
    assert len(ids) == len(set(ids))


def test_glob_no_match_returns_empty(tmp_path: Path) -> None:
    assert parse_junit_glob(str(tmp_path / "*.xml")) == []


# --- security ---------------------------------------------------------------


@pytest.mark.parametrize(
    "prolog",
    [
        '<!DOCTYPE t [<!ENTITY s SYSTEM "file:///etc/passwd">]>',  # XXE: read a local file
        '<!DOCTYPE t [<!ENTITY a "AAAA"><!ENTITY b "&a;&a;&a;&a;">]>',  # entity expansion
        "<!DOCTYPE t>",  # a bare DTD with no entities is still refused
    ],
)
@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])  # utf-16 defeats a byte search
def test_rejects_dtd_and_entities(tmp_path: Path, prolog: str, encoding: str) -> None:
    report = tmp_path / "evil.xml"
    report.write_bytes(
        (
            f'<?xml version="1.0" encoding="{encoding.upper()}"?>\n{prolog}\n'
            '<testsuites><testsuite name="s"><testcase classname="c" name="n">'
            '<failure message="m">x</failure></testcase></testsuite></testsuites>'
        ).encode(encoding)
    )
    with pytest.raises(UnsafeXMLError):
        parse_junit(report)


def test_utf16_report_without_dtd_still_parses(tmp_path: Path) -> None:
    report = tmp_path / "ok.xml"
    report.write_bytes(
        (
            '<?xml version="1.0" encoding="UTF-16"?>\n'
            '<testsuites><testsuite name="s"><testcase classname="c" name="n">'
            '<failure message="boom">trace</failure></testcase></testsuite></testsuites>'
        ).encode("utf-16")
    )
    (f,) = parse_junit(report)
    assert f.message == "boom"
