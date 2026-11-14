import pytest

from flakehunter.combine import FALLBACK_CAP, RULE_EXPLANATIONS, combine
from flakehunter.models import Category, RuleHint, TestFailure, Verdict
from flakehunter.rules import RULES

F = TestFailure(id="t::a", suite="s", name="a", kind="failure", message="boom")


def hint(category: Category = "environment", confidence: float = 0.9) -> RuleHint:
    return RuleHint(rule="connection_refused", category=category, confidence=confidence)


def verdict(category: Category = "product_bug", confidence: float = 0.8) -> Verdict:
    return Verdict(
        category=category,
        confidence=confidence,
        likely_cause="cause",
        evidence=["line"],
        suggested_next_step="step",
    )


def test_settled_rule_without_llm_is_rules() -> None:
    v = combine(F, hint(), None)
    assert (v.decided_by, v.category, v.confidence, v.rule) == (
        "rules",
        "environment",
        0.9,
        "connection_refused",
    )
    assert v.likely_cause == RULE_EXPLANATIONS["connection_refused"][0]


def test_agreement_is_combined_with_max_confidence() -> None:
    v = combine(F, hint("environment", 0.6), verdict("environment", 0.7))
    assert (v.decided_by, v.category, v.confidence) == ("combined", "environment", 0.7)


def test_disagreement_trusts_confident_llm_with_penalty() -> None:
    v = combine(F, hint("environment", 0.6), verdict("flaky_test", 0.8))
    assert (v.decided_by, v.category, v.confidence) == ("combined", "flaky_test", 0.6)
    assert v.note is not None
    assert "model said flaky_test" in v.note


def test_disagreement_with_unsure_llm_keeps_rule() -> None:
    v = combine(F, hint("environment", 0.6), verdict("product_bug", 0.5))
    assert (v.category, v.confidence) == ("environment", 0.45)


def test_llm_only() -> None:
    v = combine(F, None, verdict())
    assert (v.decided_by, v.category, v.confidence) == ("llm", "product_bug", 0.8)


def test_llm_failed_falls_back_to_capped_hint() -> None:
    v = combine(F, hint("environment", 0.6), None, llm_error="LLM unavailable")
    assert (v.decided_by, v.category, v.confidence) == ("fallback", "environment", FALLBACK_CAP)
    assert v.note == "LLM unavailable"


def test_weak_hint_without_llm_keeps_its_confidence() -> None:
    v = combine(F, hint("environment", 0.6), None)
    assert (v.decided_by, v.confidence) == ("rules", 0.6)


def test_nothing_is_unknown() -> None:
    v = combine(F, None, None, llm_error="LLM output was invalid twice")
    assert (v.decided_by, v.category, v.confidence) == ("fallback", "unknown", 0.0)
    assert v.evidence == ("boom",)


def test_selector_rule_reports_changed_file() -> None:
    h = RuleHint(
        rule="selector_changed_in_pr",
        category="test_code",
        confidence=0.75,
        evidence=("Expected to find element", "test file changed in this PR: a.cy.ts"),
    )
    assert combine(F, h, None).related_changed_files == ("a.cy.ts",)


@pytest.mark.parametrize("rule", [r.name for r in RULES])
def test_every_rule_has_an_explanation(rule: str) -> None:
    assert rule in RULE_EXPLANATIONS


GH = "ghp_" + "A1b2C3d4" * 5


def test_rule_evidence_is_redacted() -> None:
    h = RuleHint(
        rule="connection_refused",
        category="environment",
        confidence=0.9,
        evidence=(f"ECONNREFUSED https://x:{GH}@db:5432",),
    )
    v = combine(F, h, None)
    assert GH not in "".join(v.evidence)


def test_unknown_fallback_message_is_redacted() -> None:
    f = TestFailure(id="t", suite="s", name="t", kind="failure", message=f"token={GH}")
    assert GH not in "".join(combine(f, None, None).evidence)


def test_llm_text_is_redacted() -> None:
    leaky = Verdict(
        category="environment",
        confidence=0.9,
        likely_cause=f"auth failed with {GH}",
        evidence=[f"Authorization: Bearer {GH}"],
        suggested_next_step=f"rotate {GH}",
    )
    v = combine(F, None, leaky)
    assert GH not in v.model_dump_json()
