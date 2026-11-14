"""Parse JUnit XML from pytest, Jest, Cypress and Surefire into TestFailure records.

Every runner writes JUnit XML slightly differently. This module absorbs those
differences so the rest of FlakeHunter only ever sees ``TestFailure``:

- Surefire writes a bare ``<testsuite>`` root (junitparser wraps it for us).
- Jest omits the ``message`` attribute and pads names with a leading space.
- Cypress (mocha-junit-reporter) puts the spec file on a separate "Root Suite".
- Surefire's ``<flakyFailure>`` means the test passed on rerun, so it is not a failure.

Security: reports come from CI runs that a pull request can influence, so they are
untrusted input. Real JUnit reports never declare a DTD, and DTDs are what XML entity
attacks (XXE, "billion laughs") need, so any file containing one is rejected before
parsing. This holds whichever XML backend junitparser picks (lxml if installed,
otherwise the standard library).
"""

from glob import glob
from pathlib import Path
from typing import Any, NoReturn
from xml.parsers import expat

from junitparser import Error, Failure, JUnitXml

from flakehunter.models import Outcome, SourceFormat, TestFailure


class UnsafeXMLError(ValueError):
    """Raised when a report contains a DTD, which legitimate JUnit XML never needs."""


def parse_junit(path: Path) -> list[TestFailure]:
    """Return one TestFailure per failed or errored test case in the file.

    Passing and skipped tests are ignored.

    Raises:
        UnsafeXMLError: if the file declares a DTD or entities.
    """
    _reject_dtd(path)
    xml = JUnitXml.fromfile(str(path))
    source_format = detect_format(path, xml)
    failures: list[TestFailure] = []
    last_suite_file: str | None = None  # Cypress: file lives on the "Root Suite"

    for suite in xml:
        suite_file = _attr(suite, "file") or None
        if suite_file:
            last_suite_file = suite_file
        suite_name = _clean(suite.name)

        for case in suite:
            for result in case.result:
                if not isinstance(result, (Failure, Error)):
                    continue  # Skipped
                failures.append(
                    _to_failure(
                        case=case,
                        result=result,
                        suite_name=suite_name,
                        fallback_file=suite_file or last_suite_file,
                        source_format=source_format,
                    )
                )
    return failures


def parse_junit_glob(pattern: str) -> list[TestFailure]:
    """Parse every file matching the glob (e.g. ``reports/**/*.xml``), in a stable order."""
    failures: list[TestFailure] = []
    for match in sorted(glob(pattern, recursive=True)):
        failures.extend(parse_junit(Path(match)))
    return failures


def parse_outcomes(path: Path) -> dict[str, Outcome]:
    """Return the outcome of every test case in the file, keyed by the same id as TestFailure.

    Unlike ``parse_junit`` this includes passing tests, which is what a retry report
    needs: a test that is *missing* from the failures may have passed or never run.
    Shares the DTD check and id format with ``parse_junit`` so ids always line up.
    """
    _reject_dtd(path)
    outcomes: dict[str, Outcome] = {}
    for suite in JUnitXml.fromfile(str(path)):
        for case in suite:
            outcome: Outcome = "passed"
            for result in case.result:
                if isinstance(result, (Failure, Error)):
                    outcome = "failed"
                    break
                outcome = "skipped"
            outcomes[_make_id(_clean(case.classname), _clean(case.name))] = outcome
    return outcomes


def detect_format(path: Path, xml: JUnitXml) -> SourceFormat:
    """Best-effort guess of which runner produced the file.

    Returns ``unknown`` rather than a wrong guess.
    """
    if path.name.startswith("TEST-"):
        return "surefire"

    root_name = _clean(xml.name)
    suite_names = {_clean(s.name) for s in xml}
    files = {_attr(s, "file") for s in xml} | {_attr(c, "file") for s in xml for c in s}

    if root_name == "jest tests":
        return "jest"
    if root_name == "Mocha Tests" or any(".cy." in f for f in files):
        return "cypress"
    if root_name == "pytest tests" or "pytest" in suite_names:
        return "pytest"
    return "unknown"


def _to_failure(
    *,
    case: Any,
    result: Any,
    suite_name: str,
    fallback_file: str | None,
    source_format: SourceFormat,
) -> TestFailure:
    name = _clean(case.name)
    classname = _clean(case.classname)
    details = _clean(result.text)
    # Jest has no message attribute: fall back to the first non-empty line of the trace.
    message = _clean(result.message) or _first_line(details)
    duration = case.time

    return TestFailure(
        id=_make_id(classname, name),
        suite=suite_name,
        name=name,
        classname=classname or None,
        file=_attr(case, "file") or fallback_file,
        kind="error" if isinstance(result, Error) else "failure",
        message=message,
        details=details,
        stdout=_clean(case.system_out) or None,
        duration_s=float(duration) if duration is not None else None,
        source_format=source_format,
    )


def _make_id(classname: str, name: str) -> str:
    """Stable key ``classname::name``; just ``name`` when classname is empty or identical (Jest)."""
    if not classname or classname == name:
        return name
    return f"{classname}::{name}"


def _attr(element: Any, key: str) -> str:
    """Read a raw XML attribute junitparser doesn't expose (e.g. ``file``).

    Uses the private ``_elem`` in one place only, so a library change is a one-line fix.
    """
    return _clean(element._elem.get(key))


def _reject_dtd(path: Path) -> None:
    """Refuse files that declare a DTD or entities (XXE / entity-expansion defence).

    Uses a real XML parser (expat, from the standard library) rather than a byte
    search, so the check sees the document after its declared encoding is decoded.
    A UTF-16 file hides ``<!DOCTYPE`` from a byte search but not from expat. Parsing
    stops at the first DTD or entity declaration, before any entity is expanded.
    """

    def forbid(*_: object) -> NoReturn:
        raise UnsafeXMLError(f"{path}: DTD/entity declarations are not allowed in JUnit reports")

    parser = expat.ParserCreate()
    parser.StartDoctypeDeclHandler = forbid
    parser.EntityDeclHandler = forbid
    parser.ExternalEntityRefHandler = forbid
    with path.open("rb") as fh:
        parser.ParseFile(fh)


def _clean(value: object) -> str:
    """Turn a possibly-None, possibly-padded junitparser value into a stripped str."""
    return "" if value is None else str(value).strip()


def _first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")
