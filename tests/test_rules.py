from pathlib import Path

import pytest

from flakehunter.models import RuleHint, TestFailure
from flakehunter.parsers.diff import changed_files, load_diff
from flakehunter.parsers.junit import parse_junit
from flakehunter.parsers.retry import load_retry_report
from flakehunter.rules import (
    LLM_THRESHOLD,
    RULES,
    RuleContext,
    classify_with_rules,
    find_changed_test_file,
    is_settled,
    split_for_llm,
)

FIXTURES = Path(__file__).parent / "fixtures"
NO_CTX = RuleContext()


def make(
    message: str = "",
    details: str = "",
    *,
    name: str = "test_x",
    file: str | None = None,
    classname: str | None = "tests.test_x",
) -> TestFailure:
    return TestFailure(
        id=f"{classname}::{name}" if classname else name,
        suite="s",
        name=name,
        classname=classname,
        file=file,
        kind="failure",
        message=message,
        details=details,
    )


def rule_name(hint: RuleHint | None) -> str | None:
    return hint.rule if hint else None


# --- one positive and one near-miss per text rule --------------------------------

POSITIVE = [
    ("ConnectionRefusedError: [Errno 111] Connection refused", "connection_refused"),
    ("ConnectionRefusedError: [Errno 61] Connection refused", "connection_refused"),  # macOS
    ("Error: connect ECONNREFUSED 127.0.0.1:5432", "connection_refused"),
    ("java.net.ConnectException: Connection refused", "connection_refused"),
    ("socket.gaierror: [Errno -2] Name or service not known", "dns_failure"),
    ("Error: getaddrinfo ENOTFOUND payments.internal", "dns_failure"),
    ("java.net.UnknownHostException: db", "dns_failure"),
    ("OSError: [Errno 28] No space left on device", "disk_full"),
    ("FATAL ERROR: Reached heap limit - JavaScript heap out of memory", "out_of_memory"),
    ("java.lang.OutOfMemoryError: Java heap space", "out_of_memory"),
    ("Error: Process completed with exit code 137.", "out_of_memory"),
    ("requests.exceptions.HTTPError: 503 Service Unavailable", "service_unavailable"),
    ("Error: read ECONNRESET", "service_unavailable"),
    ("TimeoutError: page.goto: Timeout 30000ms exceeded", "timeout_generic"),
    ('thrown: "Exceeded timeout of 5000 ms for a test."', "timeout_generic"),
    ("java.net.SocketTimeoutException: Read timed out", "timeout_generic"),
]


@pytest.mark.parametrize(("message", "expected"), POSITIVE)
def test_rule_fires(message: str, expected: str) -> None:
    assert rule_name(classify_with_rules(make(message), NO_CTX)) == expected


NEAR_MISSES = [
    "AssertionError: assert 401 == 200",  # plain assertion
    "AssertionError: expected the error page to mention the outage",  # prose, no keyword
    "TypeError: Cannot read properties of undefined (reading 'email')",
    "AssertionError: assert 'refused' in 'request accepted'",  # 'refused' alone
    "ValueError: memory_limit must be positive",  # 'memory' alone
    "AssertionError: expected status 500, got 200",  # a 500 from *our* app
    "Error: Process completed with exit code 1.",  # ordinary failure exit
    "AssertionError: 1370 != 1371",  # digits that contain 137
]


@pytest.mark.parametrize("message", NEAR_MISSES)
def test_near_miss_does_not_fire(message: str) -> None:
    assert classify_with_rules(make(message), NO_CTX) is None


def test_test_name_is_not_searched() -> None:
    f = make("AssertionError: assert 401 == 200", name="test_connection_refused_is_retried")
    assert classify_with_rules(f, NO_CTX) is None


def test_case_insensitive() -> None:
    assert rule_name(classify_with_rules(make("econnrefused"), NO_CTX)) == "connection_refused"


def test_matches_in_details_and_stdout() -> None:
    in_details = make("RuntimeError: setup failed", "...\nE   [Errno 111] Connection refused")
    assert rule_name(classify_with_rules(in_details, NO_CTX)) == "connection_refused"


def test_evidence_is_the_matched_line() -> None:
    f = make("setup failed", "line one\n  E  ECONNREFUSED 127.0.0.1:6379  \nline three")
    hint = classify_with_rules(f, NO_CTX)
    assert hint is not None
    assert hint.evidence == ("E  ECONNREFUSED 127.0.0.1:6379",)


def test_evidence_is_deduplicated_and_capped() -> None:
    f = make(
        "ECONNREFUSED", "\n".join(["ECONNREFUSED"] * 2 + [f"ECONNREFUSED {i}" for i in range(9)])
    )
    hint = classify_with_rules(f, NO_CTX)
    assert hint is not None
    assert hint.evidence == ("ECONNREFUSED", "ECONNREFUSED 0", "ECONNREFUSED 1")


# --- retry -----------------------------------------------------------------------


def test_passed_on_retry_is_flaky() -> None:
    f = make("AssertionError: assert 2 == 3")
    hint = classify_with_rules(f, RuleContext(retry={f.id: "passed"}))
    assert hint is not None
    assert (hint.rule, hint.category) == ("passed_on_retry", "flaky_test")


def test_failed_again_on_retry_is_not_flaky() -> None:
    f = make("AssertionError: assert 2 == 3")
    assert classify_with_rules(f, RuleContext(retry={f.id: "failed"})) is None


def test_retry_pass_beats_environment_match() -> None:
    f = make("ConnectionRefusedError: [Errno 111] Connection refused")
    hint = classify_with_rules(f, RuleContext(retry={f.id: "passed"}))
    assert rule_name(hint) == "passed_on_retry"


# --- selector + diff ------------------------------------------------------------

SELECTOR_MSG = "Timed out retrying after 4000ms: Expected to find element: `#buy-btn`"


def test_selector_rule_needs_changed_test_file() -> None:
    f = make(SELECTOR_MSG, file="cypress/e2e/checkout.cy.ts")
    assert classify_with_rules(f, NO_CTX) is None
    ctx = RuleContext(changed_files=frozenset({"cypress/e2e/checkout.cy.ts"}))
    hint = classify_with_rules(f, ctx)
    assert hint is not None
    assert (hint.rule, hint.category) == ("selector_changed_in_pr", "test_code")
    assert hint.evidence[-1] == "test file changed in this PR: cypress/e2e/checkout.cy.ts"


def test_selector_rule_ignores_unrelated_changes() -> None:
    f = make(SELECTOR_MSG, file="cypress/e2e/checkout.cy.ts")
    ctx = RuleContext(changed_files=frozenset({"src/pricing.py"}))
    assert classify_with_rules(f, ctx) is None


def test_selenium_selector_rule() -> None:
    f = make("org.openqa.selenium.NoSuchElementException: no such element", file="LoginTest.java")
    ctx = RuleContext(changed_files=frozenset({"src/test/java/com/acme/LoginTest.java"}))
    assert rule_name(classify_with_rules(f, ctx)) == "selector_changed_in_pr"


@pytest.mark.parametrize(
    ("file", "classname", "changed", "expected"),
    [
        ("cypress/e2e/a.cy.ts", None, "web/cypress/e2e/a.cy.ts", "web/cypress/e2e/a.cy.ts"),
        ("web/cypress/e2e/a.cy.ts", None, "cypress/e2e/a.cy.ts", "cypress/e2e/a.cy.ts"),
        ("./tests/test_a.py", None, "tests/test_a.py", "tests/test_a.py"),
        (None, "tests.test_api.TestLogin", "tests/test_api.py", "tests/test_api.py"),
        (None, "test_shop", "test_shop.py", "test_shop.py"),
        ("a.cy.ts", None, "b/xa.cy.ts", None),  # suffix of a name is not the same file
        (None, None, "tests/test_a.py", None),
    ],
)
def test_find_changed_test_file(
    file: str | None, classname: str | None, changed: str, expected: str | None
) -> None:
    f = make(file=file, classname=classname)
    assert find_changed_test_file(f, frozenset({changed})) == expected


# --- precedence, threshold, split ------------------------------------------------


def test_highest_confidence_wins() -> None:
    # timeout (0.6) and connection refused (0.9) in the same output
    f = make("TimeoutError: waited 30s", "caused by: ECONNREFUSED 127.0.0.1:5432")
    assert rule_name(classify_with_rules(f, NO_CTX)) == "connection_refused"


def test_rule_names_are_unique() -> None:
    names = [r.name for r in RULES]
    assert len(names) == len(set(names))


def test_confidences_are_valid() -> None:
    assert all(0 < r.confidence <= 1 for r in RULES)


def test_threshold_routing() -> None:
    assert is_settled(classify_with_rules(make("ECONNREFUSED"), NO_CTX))
    assert not is_settled(classify_with_rules(make("TimeoutError"), NO_CTX))
    assert not is_settled(None)
    assert LLM_THRESHOLD == 0.8


def test_split_for_llm() -> None:
    env = make("ECONNREFUSED", name="test_env")
    timeout = make("TimeoutError", name="test_slow")
    bug = make("AssertionError: 1 != 2", name="test_bug")
    settled, needs_llm = split_for_llm([env, timeout, bug], NO_CTX)
    assert [f.name for f, _ in settled] == ["test_env"]
    assert [(f.name, rule_name(h)) for f, h in needs_llm] == [
        ("test_slow", "timeout_generic"),  # low-confidence hint travels with it
        ("test_bug", None),
    ]


# --- end to end on the real M2 fixtures -------------------------------------------


def test_real_pytest_fixture() -> None:
    hints = {
        f.name: classify_with_rules(f, NO_CTX)
        for f in parse_junit(FIXTURES / "junit" / "pytest" / "report.xml")
    }
    assert rule_name(hints["test_payment_service_reachable"]) == "connection_refused"
    assert hints["test_discount_applied"] is None  # a product bug: for the LLM
    assert hints["test_uses_broken_fixture"] is None


def test_real_jest_timeout_goes_to_llm_with_hint() -> None:
    hints = {
        f.name: classify_with_rules(f, NO_CTX)
        for f in parse_junit(FIXTURES / "junit" / "jest" / "junit.xml")
    }
    timeout = hints["loads prices in time"]
    assert rule_name(timeout) == "timeout_generic"
    assert not is_settled(timeout)
    assert hints["totals two items"] is None
    assert hints["reads the user email"] is None


def test_real_cypress_fixture_with_real_diff() -> None:
    (failure,) = parse_junit(FIXTURES / "junit" / "cypress" / "checkout.xml")
    diff = load_diff(FIXTURES / "diff" / "pr.diff")
    hint = classify_with_rules(failure, RuleContext(changed_files=frozenset(changed_files(diff))))
    assert rule_name(hint) == "selector_changed_in_pr"


def test_real_retry_fixture() -> None:
    failures = parse_junit(FIXTURES / "retry" / "first.xml")
    ctx = RuleContext(retry=load_retry_report(str(FIXTURES / "retry" / "retry.xml")))
    hints = {f.name: rule_name(classify_with_rules(f, ctx)) for f in failures}
    assert hints == {
        "test_order_confirmation_arrives": "passed_on_retry",
        "test_discount_applied": None,
    }


def test_real_surefire_fixture() -> None:
    hints = {
        f.name: rule_name(classify_with_rules(f, NO_CTX))
        for f in parse_junit(FIXTURES / "junit" / "surefire" / "TEST-com.example.CartTest.xml")
    }
    assert hints == {"loadsPricesFromDb": "connection_refused", "totalAppliesDiscount": None}
