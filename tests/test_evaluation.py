import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from flakehunter.evaluation import (
    CachedClassifier,
    LabelError,
    accuracy,
    cache_key,
    confusion,
    coverage_at,
    item_from_json,
    load_labels,
    macro_f1,
    markdown_table,
    per_class,
    trimming_recall,
)
from flakehunter.llm import LLMResult
from flakehunter.models import RuleHint, TestFailure, Verdict

HEADER = "failure_id,source,true_category,notes,labelled_by\n"


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "labels.csv"
    path.write_text(HEADER + body)
    return path


def test_label_loader_reads_rows(tmp_path: Path) -> None:
    labels = load_labels(write(tmp_path, "a,demo,flaky_test,note,human\n"))
    assert labels["a"].true_category == "flaky_test"
    assert labels["a"].labelled_by == "human"


@pytest.mark.parametrize(
    "body",
    [
        "a,demo,flakey_test,,\n",
        "a,demo,,,\n",
        ",demo,unknown,,\n",
        "a,d,unknown,,\na,d,unknown,,\n",
    ],
)
def test_label_loader_validates(tmp_path: Path, body: str) -> None:
    with pytest.raises(LabelError):
        load_labels(write(tmp_path, body))


def test_repo_labels_file_is_valid() -> None:
    labels = load_labels(Path(__file__).parent.parent / "evals" / "labels.csv")
    assert len(labels) >= 120
    assert {label.true_category for label in labels.values()} == {
        "product_bug",
        "flaky_test",
        "environment",
        "test_code",
        "unknown",
    }


def test_cache_key_changes_with_prompt_and_model() -> None:
    base = cache_key("m", "prompt")
    assert base == cache_key("m", "prompt")
    assert base != cache_key("m", "prompt!")
    assert base != cache_key("m2", "prompt")
    assert base != cache_key("m", "prompt", system_prompt="other")


class Counting:
    model = "m"
    provider = "fake"

    def __init__(self) -> None:
        self.calls = 0

    def classify(
        self, failure: TestFailure, context: str, hint: RuleHint | None, changed: Sequence[str]
    ) -> LLMResult:
        self.calls += 1
        verdict = Verdict(
            category="flaky_test",
            confidence=0.7,
            likely_cause="c",
            suggested_next_step="s",
        )
        return LLMResult(verdict=verdict, tokens_in=5, tokens_out=2, elapsed_s=3.0)


def test_cached_classifier_reuses_results(tmp_path: Path) -> None:
    inner = Counting()
    clf = CachedClassifier(inner, tmp_path)
    f = TestFailure(id="t", suite="s", name="t", kind="failure", message="x")
    first = clf.classify(f, "ctx", None, [])
    second = clf.classify(f, "ctx", None, [])
    assert inner.calls == 1
    assert (clf.hits, clf.misses) == (1, 1)
    assert second == first  # including tokens and the original timing
    clf.classify(f, "other ctx", None, [])
    assert inner.calls == 2


# Six hand-checked predictions:
TRUTH = ["product_bug", "product_bug", "flaky_test", "environment", "environment", "unknown"]
PRED = ["product_bug", "test_code", "flaky_test", "environment", "flaky_test", "unknown"]


def test_metrics_on_tiny_known_set() -> None:
    assert accuracy(TRUTH, PRED) == pytest.approx(4 / 6)
    m = per_class(TRUTH, PRED)
    assert (m["product_bug"].precision, m["product_bug"].recall) == (1.0, 0.5)
    assert (m["flaky_test"].precision, m["flaky_test"].recall) == (0.5, 1.0)
    assert m["test_code"].precision == 0.0  # predicted once, wrongly
    assert m["test_code"].support == 0
    # macro F1 over the 4 classes present in the truth: (2/3 + 2/3 + 2/3 + 1) / 4
    assert macro_f1(TRUTH, PRED) == pytest.approx((2 / 3 * 3 + 1) / 4)


def test_confusion_rows_are_truth() -> None:
    matrix = confusion(TRUTH, PRED)
    assert matrix[0] == [1, 0, 0, 1, 0]  # product_bug: 1 right, 1 called test_code
    assert sum(map(sum, matrix)) == 6


def test_coverage_at_threshold() -> None:
    cov, acc = coverage_at(["a", "b", "c", "d"], ["a", "x", "c", "d"], [0.9, 0.9, 0.5, 0.1], 0.8)
    assert (cov, acc) == (0.5, 0.5)


def test_trimming_recall_metric() -> None:
    assert trimming_recall(["  error: x ", "b"], ["error: x", "", "missing"]) == 0.5
    assert trimming_recall([], []) == 1.0


def test_markdown_table() -> None:
    table = markdown_table(["a", "b"], [[1.234, "x|y"]])
    assert table.splitlines() == ["| a | b |", "|---|---|", "| 1.23 | x\\|y |"]


def test_logchunks_item_uses_log_only() -> None:
    item = item_from_json(
        {
            "failure_id": "logchunks:Go/a@b/failed/123",
            "source": "logchunks",
            "language": "Go",
            "log": ["line"],
            "chunk": ["line"],
            "keywords": [],
        }
    )
    assert item.failure.name == "123"
    assert item.logs == {"build.log": ["line"]}


def test_scenario_item_roundtrip() -> None:
    f = TestFailure(id="m::t", suite="s", name="t", kind="failure", message="boom")
    data = json.loads(
        json.dumps(
            {
                "failure_id": "m::t",
                "source": "scenarios",
                "failure": f.model_dump(mode="json"),
                "retry": "passed",
                "changed_files": ["app/x.py"],
                "logs": {},
            }
        )
    )
    item = item_from_json(data)
    assert (item.failure, item.retry, item.changed_files) == (f, "passed", ("app/x.py",))
