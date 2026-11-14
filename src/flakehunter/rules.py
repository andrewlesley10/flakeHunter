"""Deterministic rules: cheap, instant, explainable verdicts for the obvious failures.

Rules are *data*: a list of ``Rule`` objects rather than an if/else chain. Adding a
rule means adding a list item, tests can be parametrised over the list, and the
evals (M9) can report how often each rule fires.

Precedence: every rule is checked; the highest confidence wins, and ties go to the
rule listed first. Confidence also routes work: a hint below ``LLM_THRESHOLD`` is not
final, so the failure goes to the LLM with the hint attached as context.

Rules search the failure's message, details (stack trace) and stdout, never the test
*name*: a test called ``test_handles_connection_refused`` that fails on an assertion
is not an environment problem.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from flakehunter.models import Category, RuleHint, TestFailure
from flakehunter.parsers.retry import RetryResult

LLM_THRESHOLD = 0.8
"""Hints at or above this are final; below it the LLM takes a second look."""

MAX_EVIDENCE_LINES = 3


@dataclass(frozen=True)
class RuleContext:
    """Everything a rule may look at besides the failure itself."""

    changed_files: frozenset[str] = frozenset()
    retry: Mapping[str, RetryResult] = field(default_factory=dict)


Check = Callable[[TestFailure, RuleContext], tuple[str, ...] | None]
"""Returns the evidence lines if the rule matches, otherwise None."""


@dataclass(frozen=True)
class Rule:
    name: str
    category: Category
    confidence: float
    check: Check

    def apply(self, failure: TestFailure, ctx: RuleContext) -> RuleHint | None:
        evidence = self.check(failure, ctx)
        if evidence is None:
            return None
        return RuleHint(
            rule=self.name,
            category=self.category,
            confidence=self.confidence,
            evidence=evidence,
        )


# --- building blocks ----------------------------------------------------------


def _search_text(failure: TestFailure) -> str:
    return "\n".join(part for part in (failure.message, failure.details, failure.stdout) if part)


def _matching_lines(pattern: re.Pattern[str], text: str) -> tuple[str, ...]:
    lines = [line.strip() for line in text.splitlines() if pattern.search(line)]
    return tuple(dict.fromkeys(lines))[:MAX_EVIDENCE_LINES]  # de-duplicate, keep order


def regex_check(pattern: str) -> Check:
    """A check that matches a case-insensitive regex against the failure output."""
    compiled = re.compile(pattern, re.IGNORECASE)

    def check(failure: TestFailure, _ctx: RuleContext) -> tuple[str, ...] | None:
        return _matching_lines(compiled, _search_text(failure)) or None

    return check


def regex_rule(name: str, category: Category, confidence: float, pattern: str) -> Rule:
    return Rule(name, category, confidence, regex_check(pattern))


def _passed_on_retry(failure: TestFailure, ctx: RuleContext) -> tuple[str, ...] | None:
    if ctx.retry.get(failure.id) == "passed":
        return (f"{failure.id} failed, then passed when re-run with no code change",)
    return None


_SELECTOR_NOT_FOUND = re.compile(
    r"Expected to find element"  # Cypress
    r"|NoSuchElementException|Unable to locate element"  # Selenium
    r"|Unable to find an? (element|role|label)|TestingLibraryElementError"  # Testing Library
    r"|waiting for (selector|locator)",  # Playwright / Puppeteer
    re.IGNORECASE,
)


def _selector_changed_in_pr(failure: TestFailure, ctx: RuleContext) -> tuple[str, ...] | None:
    lines = _matching_lines(_SELECTOR_NOT_FOUND, _search_text(failure))
    if not lines:
        return None
    changed = find_changed_test_file(failure, ctx.changed_files)
    if changed is None:
        return None
    return (*lines, f"test file changed in this PR: {changed}")


def find_changed_test_file(failure: TestFailure, changed_files: frozenset[str]) -> str | None:
    """Return the changed path that is this failure's test file, if any.

    Runners report paths relative to different roots (``cypress/e2e/x.cy.ts`` vs
    ``web/cypress/e2e/x.cy.ts``), so paths match when one ends with the other.
    pytest omits ``file``, so its dotted classname (``tests.test_api.TestLogin``)
    is turned into candidate paths (``tests/test_api.py``, ``tests.py``...).
    """
    for candidate in _candidate_paths(failure):
        for path in changed_files:
            if _same_file(candidate, path):
                return path
    return None


def _candidate_paths(failure: TestFailure) -> list[str]:
    if failure.file:
        return [failure.file]
    if failure.classname and "." in failure.classname and "/" not in failure.classname:
        parts = failure.classname.split(".")
        # longest first: tests.test_api.TestLogin -> tests/test_api/TestLogin.py, tests/test_api.py
        return ["/".join(parts[:n]) + ".py" for n in range(len(parts), 0, -1)]
    if failure.classname:
        return [failure.classname + ".py"]  # pytest module at repo root: "test_shop"
    return []


def _same_file(a: str, b: str) -> bool:
    pa, pb = PurePosixPath(a.lstrip("./")).parts, PurePosixPath(b.lstrip("./")).parts
    shorter, longer = sorted((pa, pb), key=len)
    return bool(shorter) and longer[-len(shorter) :] == shorter


# --- the rules ----------------------------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule("passed_on_retry", "flaky_test", 0.95, _passed_on_retry),
    regex_rule(
        "connection_refused",
        "environment",
        0.9,
        r"connection refused|ECONNREFUSED|\[Errno (111|61)\]",
    ),
    regex_rule(
        "dns_failure",
        "environment",
        0.9,
        r"Name or service not known|Temporary failure in name resolution"
        r"|getaddrinfo (ENOTFOUND|EAI_AGAIN)|nodename nor servname provided"
        r"|UnknownHostException|Could not resolve host",
    ),
    regex_rule(
        "disk_full",
        "environment",
        0.9,
        r"No space left on device|ENOSPC",
    ),
    regex_rule(
        "out_of_memory",
        "environment",
        0.85,
        r"\bMemoryError\b|OutOfMemoryError|JavaScript heap out of memory"
        r"|exit code 137|\bOOMKilled\b|Cannot allocate memory",
    ),
    regex_rule(
        "service_unavailable",
        "environment",
        0.8,
        r"\b503 Service Unavailable\b|\b502 Bad Gateway\b|ESOCKETTIMEDOUT|ECONNRESET"
        r"|connection reset by peer",
    ),
    Rule("selector_changed_in_pr", "test_code", 0.75, _selector_changed_in_pr),
    regex_rule(
        "timeout_generic",
        "environment",
        0.6,  # deliberately low: a timeout may be a slow environment OR a flaky race
        r"\bTimeoutError\b|\btimed out after\b|Exceeded timeout of \d+ ?ms"
        r"|\bReadTimeout\b|SocketTimeoutException",
    ),
)


# --- entry points ---------------------------------------------------------------


def classify_with_rules(
    failure: TestFailure, ctx: RuleContext, rules: Sequence[Rule] = RULES
) -> RuleHint | None:
    """Return the winning hint (highest confidence, ties to list order) or None."""
    best: RuleHint | None = None
    for rule in rules:
        hint = rule.apply(failure, ctx)
        if hint and (best is None or hint.confidence > best.confidence):
            best = hint
    return best


def is_settled(hint: RuleHint | None) -> bool:
    """True when the rules alone are confident enough to skip the LLM."""
    return hint is not None and hint.confidence >= LLM_THRESHOLD


def split_for_llm(
    failures: Sequence[TestFailure], ctx: RuleContext, rules: Sequence[Rule] = RULES
) -> tuple[list[tuple[TestFailure, RuleHint]], list[tuple[TestFailure, RuleHint | None]]]:
    """Split failures into (settled by rules, needs the LLM), keeping each hint."""
    settled: list[tuple[TestFailure, RuleHint]] = []
    needs_llm: list[tuple[TestFailure, RuleHint | None]] = []
    for failure in failures:
        hint = classify_with_rules(failure, ctx, rules)
        if hint is not None and is_settled(hint):
            settled.append((failure, hint))
        else:
            needs_llm.append((failure, hint))
    return settled, needs_llm
