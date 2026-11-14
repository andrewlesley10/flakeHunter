"""Send one real fixture failure to a local model and print the verdict.

    uv run python scripts/try_llm.py [path/to/junit.xml] [model]

Needs Ollama running (`ollama serve`) and the model pulled (`ollama pull llama3.2:3b`).
"""

import sys
from pathlib import Path

from flakehunter.combine import combine
from flakehunter.config import LLMSettings
from flakehunter.llm import OpenAICompatClassifier
from flakehunter.parsers.junit import parse_junit
from flakehunter.redact import prepare_for_llm
from flakehunter.rules import RuleContext, classify_with_rules

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = ROOT / "tests" / "fixtures" / "junit" / "pytest" / "report.xml"


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    settings = LLMSettings.from_env().with_model(sys.argv[2] if len(sys.argv) > 2 else None)
    classifier = OpenAICompatClassifier(settings)
    print(f"model: {settings.model} via {settings.provider}\n")
    for failure in parse_junit(path):
        hint = classify_with_rules(failure, RuleContext())
        context = prepare_for_llm(failure).text
        result = classifier.classify(failure, context, hint, [])
        final = combine(failure, hint, result.verdict, llm_error=result.error)
        print(f"{failure.id}")
        print(f"  rule:   {hint.rule if hint else '-'}")
        print(f"  llm:    {result.verdict.category if result.verdict else result.error}")
        print(f"  final:  {final.category} ({final.confidence:.2f}, {final.decided_by})")
        print(f"  cause:  {final.likely_cause}")
        print(f"  next:   {final.suggested_next_step}")
        print(
            f"  cost:   {result.tokens_in}+{result.tokens_out} tokens, "
            f"{result.elapsed_s:.1f}s, {result.attempts} attempt(s)\n"
        )


if __name__ == "__main__":
    main()
