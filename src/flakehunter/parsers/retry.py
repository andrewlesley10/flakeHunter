"""Read retry reports: JUnit XML from re-running only the tests that failed.

"Failed, then passed on retry with no code change" is the strongest flaky-test signal
there is. Most runners can produce it as a second JUnit file:

- pytest:   ``pytest --lf --junitxml=retry.xml``  (re-run last failures)
- Jest:     ``jest --onlyFailures`` with jest-junit
- Cypress:  a second ``cypress run --spec <failed specs>``
- Surefire: ``-Dsurefire.rerunFailingTestsCount=N`` (writes ``<flakyFailure>`` in place)
"""

from glob import glob
from pathlib import Path
from typing import Literal

from flakehunter.parsers.junit import parse_outcomes

RetryResult = Literal["passed", "failed"]


def load_retry_report(pattern: str) -> dict[str, RetryResult]:
    """Map test id to its retry result, merged across every file matching the glob.

    If a test was retried more than once, a single pass is enough to report it as
    "passed": one pass on unchanged code already proves the failure was not
    deterministic. Skipped tests are left out, as a skip says nothing about flakiness.
    An empty pattern returns an empty dict, because retry reports are optional.
    """
    results: dict[str, RetryResult] = {}
    if not pattern:
        return results
    for match in sorted(glob(pattern, recursive=True)):
        for test_id, outcome in parse_outcomes(Path(match)).items():
            if outcome == "skipped":
                continue
            if outcome == "passed" or results.get(test_id) != "passed":
                results[test_id] = outcome
    return results
