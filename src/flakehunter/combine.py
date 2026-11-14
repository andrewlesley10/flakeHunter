"""Merge the rule hint and the LLM verdict into the one verdict shown on the PR.

Policy (see DECISIONS.md 007):
1. Rules confident (>= LLM_THRESHOLD) and no LLM call: ``rules``.
2. Rule and LLM agree: ``combined``; confidence is the higher of the two.
3. They disagree: trust the LLM if its confidence is >= LLM_TRUST, otherwise the
   rule; either way confidence is scaled down by DISAGREEMENT_PENALTY.
4. LLM only (no rule fired): ``llm``.
5. LLM failed or wasn't asked: the rule hint, capped at FALLBACK_CAP if the LLM was
   asked and failed, or ``unknown`` at 0.0: ``fallback``.
"""

from flakehunter.models import Category, FinalVerdict, RuleHint, TestFailure, Verdict
from flakehunter.rules import is_settled

LLM_TRUST = 0.7
DISAGREEMENT_PENALTY = 0.75
FALLBACK_CAP = 0.5

# What to tell the engineer when a rule decides. Keyed by rule name.
RULE_EXPLANATIONS: dict[str, tuple[str, str]] = {
    "passed_on_retry": (
        "The test failed and then passed on re-run with no code change, so the outcome "
        "is non-deterministic.",
        "Look for timing, ordering or shared-state assumptions in the test; quarantine it "
        "if it blocks merges.",
    ),
    "connection_refused": (
        "A service the test depends on refused the connection, so it was not running or "
        "not reachable.",
        "Check that the service or container started in CI (and its health check) before "
        "the tests ran.",
    ),
    "dns_failure": (
        "A host name could not be resolved, so the test could not reach a dependency.",
        "Check the host name, the CI network, and whether the service is defined in the "
        "job's services.",
    ),
    "disk_full": (
        "The CI machine ran out of disk space.",
        "Free space (caches, Docker images) or use a larger runner, then re-run.",
    ),
    "out_of_memory": (
        "The process ran out of memory or was killed by the system.",
        "Reduce parallelism or memory use, or raise the memory limit, then re-run.",
    ),
    "service_unavailable": (
        "A dependency returned 502/503 or reset the connection, so it was unhealthy.",
        "Check the dependency's status and re-run; add a readiness wait if it starts slowly.",
    ),
    "selector_changed_in_pr": (
        "The test could not find an element, and this PR changed the test file, so the "
        "selector is probably stale.",
        "Compare the selector in the changed test file with the current markup.",
    ),
    "timeout_generic": (
        "The test timed out; this can be a slow environment or a race in the test.",
        "Check whether it passes on re-run and whether the environment was slow.",
    ),
}

GENERIC_NEXT_STEP: dict[Category, str] = {
    "product_bug": "Reproduce locally and check the code changed in this PR.",
    "flaky_test": "Re-run the test and look for timing or ordering assumptions.",
    "environment": "Check the CI services and network, then re-run.",
    "test_code": "Check the test's selectors, expected values and fixtures.",
    "unknown": "Read the full log; FlakeHunter could not find enough evidence.",
}


def _base(failure: TestFailure) -> dict[str, object]:
    return {"test_id": failure.id, "test_name": failure.name, "file": failure.file}


def _from_hint(
    failure: TestFailure,
    hint: RuleHint,
    decided_by: str,
    confidence: float,
    note: str | None = None,
) -> FinalVerdict:
    cause, step = RULE_EXPLANATIONS.get(
        hint.rule, (f"Rule '{hint.rule}' matched.", GENERIC_NEXT_STEP[hint.category])
    )
    changed = tuple(
        line.removeprefix("test file changed in this PR: ")
        for line in hint.evidence
        if line.startswith("test file changed in this PR: ")
    )
    return FinalVerdict.model_validate(
        {
            **_base(failure),
            "category": hint.category,
            "confidence": round(confidence, 2),
            "likely_cause": cause,
            "evidence": hint.evidence,
            "suggested_next_step": step,
            "related_changed_files": changed,
            "decided_by": decided_by,
            "rule": hint.rule,
            "note": note,
        }
    )


def _from_llm(
    failure: TestFailure,
    verdict: Verdict,
    decided_by: str,
    confidence: float,
    rule: str | None = None,
    note: str | None = None,
) -> FinalVerdict:
    return FinalVerdict.model_validate(
        {
            **_base(failure),
            "category": verdict.category,
            "confidence": round(confidence, 2),
            "likely_cause": verdict.likely_cause,
            "evidence": tuple(verdict.evidence),
            "suggested_next_step": verdict.suggested_next_step,
            "related_changed_files": tuple(verdict.related_changed_files),
            "decided_by": decided_by,
            "rule": rule,
            "note": note,
        }
    )


def combine(
    failure: TestFailure,
    hint: RuleHint | None,
    llm: Verdict | None,
    *,
    llm_error: str | None = None,
) -> FinalVerdict:
    """Apply the policy in the module docstring. Pure: no I/O, never raises on valid input."""
    if llm is None:
        if hint is None:
            return FinalVerdict.model_validate(
                {
                    **_base(failure),
                    "category": "unknown",
                    "confidence": 0.0,
                    "likely_cause": "No rule matched and no model verdict is available.",
                    "evidence": (failure.message,) if failure.message else (),
                    "suggested_next_step": GENERIC_NEXT_STEP["unknown"],
                    "decided_by": "fallback",
                    "note": llm_error,
                }
            )
        if llm_error is None and is_settled(hint):
            return _from_hint(failure, hint, "rules", hint.confidence)
        confidence = min(hint.confidence, FALLBACK_CAP) if llm_error else hint.confidence
        return _from_hint(failure, hint, "fallback", confidence, note=llm_error)

    if hint is None:
        return _from_llm(failure, llm, "llm", llm.confidence)

    if hint.category == llm.category:
        return _from_llm(
            failure, llm, "combined", max(hint.confidence, llm.confidence), rule=hint.rule
        )

    note = f"rule '{hint.rule}' said {hint.category}; model said {llm.category}"
    if llm.confidence >= LLM_TRUST:
        return _from_llm(
            failure,
            llm,
            "combined",
            llm.confidence * DISAGREEMENT_PENALTY,
            rule=hint.rule,
            note=note,
        )
    return _from_hint(failure, hint, "combined", hint.confidence * DISAGREEMENT_PENALTY, note=note)
