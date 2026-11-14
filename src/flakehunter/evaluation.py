"""Pure helpers for the eval harness (``evals/run_evals.py``): labels, items, caching, metrics.

Metrics are computed here in plain Python (about 40 lines) rather than with
scikit-learn, so they are unit-tested and the eval adds only one dependency
(matplotlib, for the confusion-matrix image). See DECISIONS 012.
"""

import csv
import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import get_args

from flakehunter.llm import Classifier, LLMResult
from flakehunter.models import Category, RuleHint, TestFailure, Verdict
from flakehunter.parsers.retry import RetryResult
from flakehunter.prompts import SYSTEM_PROMPT, build_user_message

CATEGORIES: tuple[Category, ...] = get_args(Category)


class LabelError(ValueError):
    """labels.csv has a row that can't be trusted."""


@dataclass(frozen=True)
class Label:
    failure_id: str
    source: str
    true_category: Category
    notes: str = ""
    labelled_by: str = ""


def load_labels(path: Path) -> dict[str, Label]:
    """Read labels.csv. A typo in a category or a duplicate id fails loudly."""
    labels: dict[str, Label] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for line_no, row in enumerate(csv.DictReader(f), start=2):
            category = (row.get("true_category") or "").strip()
            if category not in CATEGORIES:
                raise LabelError(f"line {line_no}: unknown category {category!r}")
            failure_id = (row.get("failure_id") or "").strip()
            if not failure_id:
                raise LabelError(f"line {line_no}: empty failure_id")
            if failure_id in labels:
                raise LabelError(f"line {line_no}: duplicate failure_id {failure_id!r}")
            labels[failure_id] = Label(
                failure_id=failure_id,
                source=(row.get("source") or "").strip(),
                true_category=category,
                notes=(row.get("notes") or "").strip(),
                labelled_by=(row.get("labelled_by") or "").strip(),
            )
    return labels


@dataclass(frozen=True)
class EvalItem:
    """One failure as the pipeline would see it in CI."""

    failure_id: str
    source: str
    failure: TestFailure
    retry: RetryResult | None = None
    changed_files: tuple[str, ...] = ()
    logs: dict[str, list[str]] = field(default_factory=dict)


def item_from_json(data: dict[str, object]) -> EvalItem:
    """Read one line of a dataset .jsonl file (scenarios, demo or LogChunks)."""
    if data.get("source") == "logchunks":
        failure_id = str(data["failure_id"])
        failure = TestFailure(
            id=failure_id,
            suite=str(data.get("language", "")),
            name=failure_id.rsplit("/", 1)[-1],  # the build id: matches no log line
            kind="error",
            message="",
        )
        log = [str(line) for line in data.get("log", [])]  # type: ignore[attr-defined]
        return EvalItem(failure_id, "logchunks", failure, logs={"build.log": log})
    retry = data.get("retry")
    return EvalItem(
        failure_id=str(data["failure_id"]),
        source=str(data["source"]),
        failure=TestFailure.model_validate(data["failure"]),
        retry=retry if retry in ("passed", "failed") else None,
        changed_files=tuple(str(p) for p in data.get("changed_files", [])),  # type: ignore[attr-defined]
        logs={str(k): list(v) for k, v in dict(data.get("logs") or {}).items()},  # type: ignore[call-overload]
    )


def load_items(paths: Iterable[Path]) -> dict[str, EvalItem]:
    items: dict[str, EvalItem] = {}
    for path in paths:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = item_from_json(json.loads(line))
                items[item.failure_id] = item
    return items


# --- caching ---------------------------------------------------------------------


def cache_key(model: str, user_message: str, system_prompt: str = SYSTEM_PROMPT) -> str:
    """Same model + same prompt = same answer (temperature 0), so reuse it."""
    return hashlib.sha256(f"{model}\0{system_prompt}\0{user_message}".encode()).hexdigest()


class CachedClassifier:
    """Wraps a classifier; stores each result on disk keyed by model and full prompt."""

    def __init__(self, inner: Classifier, cache_dir: Path) -> None:
        self.inner = inner
        self.cache_dir = cache_dir
        self.hits = 0
        self.misses = 0

    @property
    def model(self) -> str:
        return self.inner.model

    @property
    def provider(self) -> str:
        return self.inner.provider

    def classify(
        self,
        failure: TestFailure,
        context: str,
        hint: RuleHint | None,
        changed_files: Sequence[str],
    ) -> LLMResult:
        message = build_user_message(failure.id, context, hint, changed_files)
        path = self.cache_dir / f"{cache_key(self.model, message)}.json"
        if path.is_file():
            self.hits += 1
            return _result_from_json(json.loads(path.read_text(encoding="utf-8")))
        self.misses += 1
        result = self.inner.classify(failure, context, hint, changed_files)
        if not result.rate_limited:  # don't cache outages
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(_result_to_json(result)), encoding="utf-8")
        return result


def _result_to_json(r: LLMResult) -> dict[str, object]:
    return {
        "verdict": r.verdict.model_dump(mode="json") if r.verdict else None,
        "tokens_in": r.tokens_in,
        "tokens_out": r.tokens_out,
        "attempts": r.attempts,
        "elapsed_s": r.elapsed_s,
        "error": r.error,
    }


def _result_from_json(d: dict[str, object]) -> LLMResult:
    verdict = Verdict.model_validate(d["verdict"]) if d.get("verdict") else None
    return LLMResult(
        verdict=verdict,
        tokens_in=int(d.get("tokens_in", 0)),  # type: ignore[call-overload]
        tokens_out=int(d.get("tokens_out", 0)),  # type: ignore[call-overload]
        attempts=int(d.get("attempts", 0)),  # type: ignore[call-overload]
        elapsed_s=float(d.get("elapsed_s", 0.0)),  # type: ignore[arg-type]
        error=d.get("error"),  # type: ignore[arg-type]
    )


# --- metrics ------------------------------------------------------------------------


@dataclass(frozen=True)
class ClassMetrics:
    precision: float
    recall: float
    f1: float
    support: int


def accuracy(truth: Sequence[str], pred: Sequence[str]) -> float:
    if not truth:
        return 0.0
    return sum(t == p for t, p in zip(truth, pred, strict=True)) / len(truth)


def per_class(
    truth: Sequence[str], pred: Sequence[str], classes: Sequence[str] = CATEGORIES
) -> dict[str, ClassMetrics]:
    pairs = list(zip(truth, pred, strict=True))
    out: dict[str, ClassMetrics] = {}
    for c in classes:
        tp = sum(t == c and p == c for t, p in pairs)
        predicted = sum(p == c for _, p in pairs)
        actual = sum(t == c for t, _ in pairs)
        precision = tp / predicted if predicted else 0.0
        recall = tp / actual if actual else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        out[c] = ClassMetrics(precision, recall, f1, actual)
    return out


def macro_f1(
    truth: Sequence[str], pred: Sequence[str], classes: Sequence[str] = CATEGORIES
) -> float:
    """Mean F1 over classes that occur in the truth (so absent classes don't count as 0)."""
    metrics = [m for m in per_class(truth, pred, classes).values() if m.support]
    return sum(m.f1 for m in metrics) / len(metrics) if metrics else 0.0


def confusion(
    truth: Sequence[str], pred: Sequence[str], classes: Sequence[str] = CATEGORIES
) -> list[list[int]]:
    """Rows are the truth, columns the prediction, both in ``classes`` order."""
    counts = Counter(zip(truth, pred, strict=True))
    return [[counts[(t, p)] for p in classes] for t in classes]


def coverage_at(
    truth: Sequence[str], pred: Sequence[str], confidence: Sequence[float], threshold: float
) -> tuple[float, float]:
    """(share of items with confidence >= threshold, accuracy on those items)."""
    kept = [(t, p) for t, p, c in zip(truth, pred, confidence, strict=True) if c >= threshold]
    if not truth:
        return 0.0, 0.0
    cov = len(kept) / len(truth)
    acc = sum(t == p for t, p in kept) / len(kept) if kept else 0.0
    return cov, acc


def trimming_recall(kept_lines: Sequence[str], chunk: Sequence[str]) -> float:
    """Share of the hand-marked chunk's lines that survived trimming."""
    wanted = [line.strip() for line in chunk if line.strip()]
    if not wanted:
        return 1.0
    have = {line.strip() for line in kept_lines}
    return sum(line in have for line in wanted) / len(wanted)


def markdown_table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    """A GitHub Markdown table (avoids a pandas/tabulate dependency)."""

    def cell(v: object) -> str:
        if isinstance(v, float):
            return f"{v:.2f}"
        return str(v).replace("|", "\\|")

    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)
