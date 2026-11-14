"""Score FlakeHunter on the labelled set. Runs locally on Ollama, so it's free.

    uv run --group eval python evals/run_evals.py [--models llama3.2:3b llama3.1:8b] [--offline]

Three modes over the same items:
  rules     classify_with_rules only; no match means "unknown"
  llm       the model alone (no rule hint, no retry information)
  combined  the real pipeline: rules first, the model for what they can't settle

Model replies are cached in evals/.cache (keyed by model + full prompt), so re-running
is fast and changing the prompt invalidates exactly the affected entries. Writes
evals/results.md, evals/predictions.csv and evals/confusion_matrix.png.
"""

import argparse
import csv
import json
import re
import statistics
import sys
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from flakehunter.config import LLMSettings
from flakehunter.evaluation import (
    CATEGORIES,
    CachedClassifier,
    EvalItem,
    accuracy,
    confusion,
    coverage_at,
    load_items,
    load_labels,
    macro_f1,
    markdown_table,
    per_class,
    trimming_recall,
)
from flakehunter.llm import Classifier, LLMResult, OpenAICompatClassifier
from flakehunter.models import RuleHint, TestFailure
from flakehunter.pipeline import LOG_LINES_AFTER, LOG_LINES_BEFORE, MAX_LOG_LINES, run_pipeline
from flakehunter.prompts import PROMPT_VERSION
from flakehunter.redact import prepare_for_llm, trim_around
from flakehunter.rules import LLM_THRESHOLD, RuleContext, classify_with_rules

# Tried in M9 and not adopted (no better than the plain tail): see results.md.
ERROR_WORDS = re.compile(
    r"\b(error|errors|fail|failed|failure|failures|exception|traceback|fatal|panic)\b", re.I
)

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"
DATASETS = [
    EVALS / "dataset" / "scenarios.jsonl",
    EVALS / "dataset" / "demo.jsonl",
    ROOT / "data" / "processed" / "logchunks.jsonl",
]


@dataclass
class Prediction:
    failure_id: str
    source: str
    truth: str
    mode: str
    model: str
    category: str
    confidence: float
    decided_by: str
    tokens: int
    seconds: float


class Recording:
    """Sums the cost of every model call made through it (cached calls keep their
    original timing, so 'seconds per failure' reflects real inference)."""

    def __init__(self, inner: Classifier) -> None:
        self.inner = inner
        self.tokens = 0
        self.seconds = 0.0

    @property
    def model(self) -> str:
        return self.inner.model

    @property
    def provider(self) -> str:
        return self.inner.provider

    def classify(
        self, failure: TestFailure, context: str, hint: RuleHint | None, changed: Sequence[str]
    ) -> LLMResult:
        result = self.inner.classify(failure, context, hint, changed)
        self.tokens += result.tokens_in + result.tokens_out
        self.seconds += result.elapsed_s
        return result


class OfflineClassifier:
    """Used with --offline: every cache miss is an error instead of a model call."""

    def __init__(self, model: str) -> None:
        self.model = model
        self.provider = "offline"

    def classify(
        self, failure: TestFailure, context: str, hint: RuleHint | None, changed: Sequence[str]
    ) -> LLMResult:
        return LLMResult(verdict=None, error="not in cache (--offline)")


def ctx(item: EvalItem) -> RuleContext:
    retry = {item.failure.id: item.retry} if item.retry else {}
    return RuleContext(changed_files=frozenset(item.changed_files), retry=retry)


def run_rules(item: EvalItem, truth: str) -> Prediction:
    start = time.perf_counter()
    hint = classify_with_rules(item.failure, ctx(item))
    return Prediction(
        item.failure_id,
        item.source,
        truth,
        "rules",
        "-",
        hint.category if hint else "unknown",
        hint.confidence if hint else 0.0,
        "rules" if hint else "none",
        0,
        time.perf_counter() - start,
    )


def run_llm(item: EvalItem, truth: str, clf: Classifier) -> Prediction:
    rec = Recording(clf)
    prepared = prepare_for_llm(
        item.failure,
        item.logs,
        before=LOG_LINES_BEFORE,
        after=LOG_LINES_AFTER,
        max_log_lines=MAX_LOG_LINES,
    )
    result = rec.classify(item.failure, prepared.text, None, list(item.changed_files))
    v = result.verdict
    return Prediction(
        item.failure_id,
        item.source,
        truth,
        "llm",
        clf.model,
        v.category if v else "unknown",
        v.confidence if v else 0.0,
        "llm" if v else "fallback",
        rec.tokens,
        rec.seconds,
    )


def run_combined(item: EvalItem, truth: str, clf: Classifier) -> Prediction:
    rec = Recording(clf)
    start = time.perf_counter()
    report = run_pipeline(
        [item.failure],
        logs=item.logs,
        changed_files=item.changed_files,
        retry=ctx(item).retry,
        classifier=rec,
    )
    rules_time = time.perf_counter() - start if not rec.tokens else 0.0
    (v,) = report.verdicts
    return Prediction(
        item.failure_id,
        item.source,
        truth,
        "combined",
        clf.model,
        v.category,
        v.confidence,
        v.decided_by,
        rec.tokens,
        rec.seconds + rules_time,
    )


# --- reporting ------------------------------------------------------------------------


def config_name(p: Prediction) -> tuple[str, str]:
    return p.mode, p.model


def summary_rows(preds: list[Prediction]) -> list[list[object]]:
    rows: list[list[object]] = []
    for key in dict.fromkeys(config_name(p) for p in preds):
        ps = [p for p in preds if config_name(p) == key]
        truth, pred = [p.truth for p in ps], [p.category for p in ps]
        cov, acc_hi = coverage_at(truth, pred, [p.confidence for p in ps], LLM_THRESHOLD)
        seconds = [p.seconds for p in ps]
        rows.append(
            [
                key[0],
                key[1],
                len(ps),
                f"{accuracy(truth, pred):.0%}",
                f"{macro_f1(truth, pred):.2f}",
                f"{cov:.0%}",
                f"{acc_hi:.0%}",
                f"{statistics.mean(seconds):.1f}",
                f"{statistics.median(seconds):.1f}",
                round(statistics.mean(p.tokens for p in ps)),
            ]
        )
    return rows


def best_config(preds: list[Prediction]) -> tuple[str, str]:
    scores: dict[tuple[str, str], float] = {}
    for key in dict.fromkeys(config_name(p) for p in preds):
        ps = [p for p in preds if config_name(p) == key]
        scores[key] = macro_f1([p.truth for p in ps], [p.category for p in ps])
    return max(scores, key=lambda k: scores[k])


def save_confusion_png(truth: list[str], pred: list[str], title: str, path: Path) -> bool:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    matrix = confusion(truth, pred)
    fig, ax = plt.subplots(figsize=(6.4, 5.2))
    ax.imshow(matrix, cmap="Blues")
    labels = [c.replace("_", " ") for c in CATEGORIES]
    ax.set_xticks(range(len(labels)), labels, rotation=30, ha="right")
    ax.set_yticks(range(len(labels)), labels)
    ax.set_xlabel("predicted")
    ax.set_ylabel("true")
    ax.set_title(title)
    top = max(max(r) for r in matrix) or 1
    for i, row in enumerate(matrix):
        for j, n in enumerate(row):
            ax.text(
                j, i, str(n), ha="center", va="center", color="white" if n > top / 2 else "black"
            )
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return True


def _error_word_trim(log: list[str], args: tuple[int, int, int]) -> list[str]:
    hits = [line for line in log if ERROR_WORDS.search(line)]
    return trim_around(log, hits or [], *args) if hits else trim_around(log, [], *args)


def trimming_section() -> str:
    path = ROOT / "data" / "processed" / "logchunks.jsonl"
    if not path.is_file():
        return "_LogChunks not downloaded; run `scripts/fetch_logchunks.py`._\n"
    old, tail, err, kw, sizes = [], [], [], [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        log, chunk = d["log"], d["chunk"]
        sizes.append(len(log))
        args = (LOG_LINES_BEFORE, LOG_LINES_AFTER, MAX_LOG_LINES)
        old.append(trimming_recall(log[-(LOG_LINES_BEFORE + LOG_LINES_AFTER + 1) :], chunk))
        tail.append(trimming_recall(trim_around(log, [], *args), chunk))
        err.append(trimming_recall(_error_word_trim(log, args), chunk))
        kw.append(trimming_recall(trim_around(log, d["keywords"], *args), chunk))
    full_hits = lambda xs: sum(x == 1.0 for x in xs) / len(xs)  # noqa: E731
    rows = [
        [
            "no needle: before M9 (last 31 lines)",
            f"{statistics.mean(old):.0%}",
            f"{full_hits(old):.0%}",
        ],
        [
            "no needle: last 80 lines (what FlakeHunter does)",
            f"{statistics.mean(tail):.0%}",
            f"{full_hits(tail):.0%}",
        ],
        [
            "no needle: error-word windows, then last lines (tried, not adopted)",
            f"{statistics.mean(err):.0%}",
            f"{full_hits(err):.0%}",
        ],
        ["LogChunks keywords as needles", f"{statistics.mean(kw):.0%}", f"{full_hits(kw):.0%}"],
    ]
    return (
        f"All {len(tail)} LogChunks logs (median {statistics.median(sizes):.0f} lines) trimmed to "
        f"at most {MAX_LOG_LINES} lines. Recall = share of the hand-marked failure chunk's lines "
        "that survive trimming.\n\n"
        + markdown_table(["Needles", "Mean recall", "Chunk fully kept"], rows)
        + "\n"
    )


def write_results(preds: list[Prediction], items: dict[str, EvalItem], labels_n: int) -> None:
    out: list[str] = ["# Evaluation results", ""]
    out += [
        f"Generated by `evals/run_evals.py` (prompt {PROMPT_VERSION}). {labels_n} labelled "
        "failures. Models run locally through Ollama at temperature 0. "
        "Headline numbers use all items; see the per-source table for how they differ.",
        "",
        "## Dataset",
        "",
    ]
    truth_by_source: Counter[tuple[str, str]] = Counter()
    for p in preds:
        if p.mode == "rules":
            truth_by_source[(p.source, p.truth)] += 1
    sources = sorted({s for s, _ in truth_by_source})
    rows = [
        [
            s,
            *(truth_by_source[(s, c)] for c in CATEGORIES),
            sum(truth_by_source[(s, c)] for c in CATEGORIES),
        ]
        for s in sources
    ]
    rows.append(
        [
            "**total**",
            *(sum(truth_by_source[(s, c)] for s in sources) for c in CATEGORIES),
            sum(truth_by_source.values()),
        ]
    )
    out += [markdown_table(["Source", *CATEGORIES, "Total"], rows), ""]

    out += ["## Headline", ""]
    out += [
        markdown_table(
            [
                "Mode",
                "Model",
                "n",
                "Accuracy",
                "Macro F1",
                "Coverage @ ≥0.8",
                "Acc @ ≥0.8",
                "s / failure (mean)",
                "s / failure (median)",
                "tokens / failure",
            ],
            summary_rows(preds),
        ),
        "",
    ]

    best = best_config(preds)
    bp = [p for p in preds if config_name(p) == best]
    truth, pred = [p.truth for p in bp], [p.category for p in bp]
    out += [f"## Best configuration: {best[0]} ({best[1]})", "", "### Per category", ""]
    out += [
        markdown_table(
            ["Category", "Precision", "Recall", "F1", "Support"],
            [
                [c, m.precision, m.recall, m.f1, m.support]
                for c, m in per_class(truth, pred).items()
            ],
        ),
        "",
    ]
    out += ["### Confusion matrix (rows = truth, columns = prediction)", ""]
    out += [
        markdown_table(
            ["", *CATEGORIES],
            [[c, *row] for c, row in zip(CATEGORIES, confusion(truth, pred), strict=True)],
        ),
        "",
    ]
    if save_confusion_png(truth, pred, f"{best[0]} · {best[1]}", EVALS / "confusion_matrix.png"):
        out += ["![Confusion matrix](confusion_matrix.png)", ""]

    out += ["## Accuracy by source", ""]
    rows = []
    for key in dict.fromkeys(config_name(p) for p in preds):
        row: list[object] = [f"{key[0]} ({key[1]})"]
        for s in sources:
            ps = [p for p in preds if config_name(p) == key and p.source == s]
            row.append(f"{accuracy([p.truth for p in ps], [p.category for p in ps]):.0%}")
        rows.append(row)
    out += [markdown_table(["Configuration", *sources], rows), ""]

    out += ["## How much each part contributes (combined mode)", ""]
    rows = []
    for model in dict.fromkeys(p.model for p in preds if p.mode == "combined"):
        ps = [p for p in preds if p.mode == "combined" and p.model == model]
        for d in ("rules", "combined", "llm", "fallback"):
            sub = [p for p in ps if p.decided_by == d]
            if sub:
                rows.append(
                    [
                        model,
                        d,
                        len(sub),
                        f"{len(sub) / len(ps):.0%}",
                        f"{accuracy([p.truth for p in sub], [p.category for p in sub]):.0%}",
                    ]
                )
    out += [markdown_table(["Model", "Decided by", "Failures", "Share", "Accuracy"], rows), ""]

    out += ["## Log trimming recall (LogChunks)", "", trimming_section(), ""]

    out += ["## Most confident mistakes (best configuration)", ""]
    wrong = sorted((p for p in bp if p.truth != p.category), key=lambda p: -p.confidence)[:12]
    out += [
        markdown_table(
            ["Failure", "Truth", "Predicted", "Confidence", "Decided by", "Message"],
            [
                [
                    f"`{p.failure_id[:60]}`",
                    p.truth,
                    p.category,
                    p.confidence,
                    p.decided_by,
                    (items[p.failure_id].failure.message or "(log only)")[:70].replace("\n", " "),
                ]
                for p in wrong
            ],
        ),
        "",
    ]

    notes = EVALS / "notes.md"
    if notes.is_file():
        out += [notes.read_text(encoding="utf-8").strip(), ""]
    (EVALS / "results.md").write_text("\n".join(out), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="*", default=["llama3.2:3b"])
    parser.add_argument("--offline", action="store_true", help="use cached replies only")
    args = parser.parse_args()

    labels = load_labels(EVALS / "labels.csv")
    items = load_items(DATASETS)
    missing = sorted(set(labels) - set(items))
    if missing:
        print(
            f"warning: {len(missing)} labelled items have no data, e.g. {missing[0]}",
            file=sys.stderr,
        )
    ids = [i for i in labels if i in items]
    preds: list[Prediction] = [run_rules(items[i], labels[i].true_category) for i in ids]

    for model in args.models:
        inner: Classifier = (
            OfflineClassifier(model)
            if args.offline
            else OpenAICompatClassifier(LLMSettings.from_env({}).with_model(model))
        )
        clf = CachedClassifier(inner, EVALS / ".cache")
        for n, i in enumerate(ids, 1):
            truth = labels[i].true_category
            preds.append(run_llm(items[i], truth, clf))
            preds.append(run_combined(items[i], truth, clf))
            if n % 10 == 0:
                print(
                    f"{model}: {n}/{len(ids)} (cache hits {clf.hits}, calls {clf.misses})",
                    file=sys.stderr,
                )

    with (EVALS / "predictions.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "failure_id",
                "source",
                "truth",
                "mode",
                "model",
                "predicted",
                "confidence",
                "decided_by",
                "tokens",
                "seconds",
            ]
        )
        for p in preds:
            w.writerow(
                [
                    p.failure_id,
                    p.source,
                    p.truth,
                    p.mode,
                    p.model,
                    p.category,
                    f"{p.confidence:.2f}",
                    p.decided_by,
                    p.tokens,
                    f"{p.seconds:.2f}",
                ]
            )
    write_results(preds, items, len(ids))
    print("wrote evals/results.md, evals/predictions.csv", file=sys.stderr)


if __name__ == "__main__":
    main()
