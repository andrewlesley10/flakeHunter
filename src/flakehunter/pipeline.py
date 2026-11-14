"""The whole pipeline as one pure-ish function: failures in, ``Report`` out.

No argument parsing, no file reading, no posting. The CLI, the GitHub entry point
and the eval runner all call ``run_pipeline``, so they can't drift apart.
"""

import time
from collections import Counter
from collections.abc import Mapping, Sequence
from importlib.metadata import PackageNotFoundError, version

from pydantic import BaseModel, ConfigDict

from flakehunter.combine import combine
from flakehunter.llm import Classifier
from flakehunter.models import Category, FinalVerdict, TestFailure
from flakehunter.parsers.retry import RetryResult
from flakehunter.redact import prepare_for_llm
from flakehunter.rules import RuleContext, classify_with_rules, is_settled

DEFAULT_MAX_FAILURES = 10
# Smaller than prepare_for_llm's defaults: small models do better with less text.
LOG_LINES_BEFORE = 15
LOG_LINES_AFTER = 15
MAX_LOG_LINES = 80


def flakehunter_version() -> str:
    try:
        return version("flakehunter")
    except PackageNotFoundError:  # pragma: no cover - only when run from a raw checkout
        return "0.0.0"


class Report(BaseModel):
    """Everything the renderers need. JSON-serialisable for ``--format json``."""

    model_config = ConfigDict(frozen=True)

    verdicts: tuple[FinalVerdict, ...] = ()
    total_failures: int = 0
    skipped_count: int = 0  # failures beyond --max-failures, not analysed
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    elapsed_s: float = 0.0
    secrets_masked: int = 0
    model: str | None = None  # None means rules only
    provider: str | None = None
    notes: tuple[str, ...] = ()
    version: str = "0.0.0"

    @property
    def summary(self) -> Counter[Category]:
        return Counter(v.category for v in self.verdicts)


def run_pipeline(
    failures: Sequence[TestFailure],
    *,
    logs: Mapping[str, Sequence[str]] | None = None,
    changed_files: Sequence[str] = (),
    retry: Mapping[str, RetryResult] | None = None,
    classifier: Classifier | None = None,
    max_failures: int = DEFAULT_MAX_FAILURES,
) -> Report:
    """Rules first; the LLM only for failures the rules can't settle."""
    start = time.monotonic()
    ctx = RuleContext(changed_files=frozenset(changed_files), retry=retry or {})
    analysed = list(failures)[: max(max_failures, 0)]

    verdicts: list[FinalVerdict] = []
    notes: list[str] = []
    llm_calls = tokens_in = tokens_out = secrets = 0
    llm_available = classifier is not None

    for failure in analysed:
        hint = classify_with_rules(failure, ctx)
        if is_settled(hint) or not llm_available or classifier is None:
            verdicts.append(combine(failure, hint, None))
            continue

        prepared = prepare_for_llm(
            failure,
            logs,
            before=LOG_LINES_BEFORE,
            after=LOG_LINES_AFTER,
            max_log_lines=MAX_LOG_LINES,
        )
        secrets += prepared.total_masked
        result = classifier.classify(failure, prepared.text, hint, list(changed_files))
        llm_calls += 1
        tokens_in += result.tokens_in
        tokens_out += result.tokens_out
        verdicts.append(combine(failure, hint, result.verdict, llm_error=result.error))

        if result.rate_limited or result.unavailable:
            # Circuit breaker: more calls would only hit the same wall and slow the job.
            llm_available = False
            reason = "rate-limited" if result.rate_limited else "unreachable"
            notes.append(f"The model was {reason}; remaining failures use rule verdicts only.")

    skipped = len(failures) - len(analysed)
    if skipped:
        notes.append(f"{skipped} more failing tests were not analysed (max-failures).")

    return Report(
        verdicts=tuple(verdicts),
        total_failures=len(failures),
        skipped_count=skipped,
        llm_calls=llm_calls,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        elapsed_s=round(time.monotonic() - start, 2),
        secrets_masked=secrets,
        model=classifier.model if classifier else None,
        provider=classifier.provider if classifier else None,
        notes=tuple(notes),
        version=flakehunter_version(),
    )
