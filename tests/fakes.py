"""Test doubles shared by pipeline, report and CLI tests."""

from collections.abc import Sequence
from dataclasses import dataclass, field

from flakehunter.llm import LLMResult
from flakehunter.models import Category, RuleHint, TestFailure, Verdict


@dataclass
class FakeClassifier:
    """Records every call; answers with a fixed category (or a fixed LLMResult)."""

    category: Category = "product_bug"
    result: LLMResult | None = None
    model: str = "fake-model"
    provider: str = "fake"
    calls: list[tuple[str, str, RuleHint | None, tuple[str, ...]]] = field(default_factory=list)

    def classify(
        self,
        failure: TestFailure,
        context: str,
        hint: RuleHint | None,
        changed_files: Sequence[str],
    ) -> LLMResult:
        self.calls.append((failure.id, context, hint, tuple(changed_files)))
        if self.result is not None:
            return self.result
        verdict = Verdict(
            category=self.category,
            confidence=0.8,
            likely_cause="The fake model thinks so.",
            evidence=[failure.message] if failure.message else [],
            suggested_next_step="Look at the code.",
            related_changed_files=list(changed_files)[:1],
        )
        return LLMResult(verdict=verdict, tokens_in=100, tokens_out=20, attempts=1)
