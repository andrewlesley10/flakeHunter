"""Review and correct labels in evals/labels.csv, one failure at a time, in the terminal.

    uv run python scripts/label.py              # review rows not yet checked by you
    uv run python scripts/label.py --all        # review every row
    uv run python scripts/label.py --source logchunks

For each failure it shows the test, the message and the trimmed evidence, the current
label and what the rules think. Keys: p/f/e/t/u set the category (product_bug,
flaky_test, environment, test_code, unknown), Enter keeps it, n edits the note,
s skips, q saves and quits. Every reviewed row gets labelled_by=human, so you can
resume where you left off.
"""

import argparse
import csv
from pathlib import Path

from flakehunter.evaluation import load_items
from flakehunter.redact import prepare_for_llm
from flakehunter.rules import RuleContext, classify_with_rules

ROOT = Path(__file__).resolve().parent.parent
LABELS = ROOT / "evals" / "labels.csv"
DATASETS = [
    ROOT / "evals" / "dataset" / "scenarios.jsonl",
    ROOT / "evals" / "dataset" / "demo.jsonl",
    ROOT / "data" / "processed" / "logchunks.jsonl",
]
KEYS = {"p": "product_bug", "f": "flaky_test", "e": "environment", "t": "test_code", "u": "unknown"}
FIELDS = ["failure_id", "source", "true_category", "notes", "labelled_by"]


def save(rows: list[dict[str, str]]) -> None:
    tmp = LABELS.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(LABELS)  # atomic: a crash never leaves a half-written file


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--source", default=None)
    args = parser.parse_args()

    with LABELS.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    items = load_items(DATASETS)
    todo = [
        r
        for r in rows
        if (args.all or r.get("labelled_by") != "human")
        and (args.source is None or r["source"] == args.source)
    ]
    print(f"{len(todo)} rows to review. Re-read docs/categories.md first.\n")

    for n, row in enumerate(todo, 1):
        item = items.get(row["failure_id"])
        print("=" * 80)
        print(f"[{n}/{len(todo)}] {row['failure_id']}  ({row['source']})")
        if item is None:
            print("  (no data for this item; is the dataset downloaded?)")
        else:
            retry = {item.failure.id: item.retry} if item.retry else {}
            ctx = RuleContext(changed_files=frozenset(item.changed_files), retry=retry)
            hint = classify_with_rules(item.failure, ctx)
            text = prepare_for_llm(item.failure, item.logs, max_log_lines=40).text
            print("\n".join(text.splitlines()[:40]))
            print(f"\n  changed files: {', '.join(item.changed_files) or '-'}")
            print(f"  retry: {item.retry or '-'}")
            print(f"  rules say: {hint.category + ' (' + hint.rule + ')' if hint else '-'}")
        print(f"\n  CURRENT: {row['true_category']}  ({row.get('labelled_by') or '?'})")
        print(f"  note: {row.get('notes') or '-'}")

        while True:
            key = input("  [p/f/e/t/u, Enter=keep, n=note, s=skip, q=quit] > ").strip().lower()
            if key == "q":
                save(rows)
                print("saved.")
                return
            if key == "s":
                break
            if key == "n":
                row["notes"] = input("  note: ").strip()
                continue
            if key == "" or key in KEYS:
                if key:
                    row["true_category"] = KEYS[key]
                row["labelled_by"] = "human"
                save(rows)
                break
            print("  unknown key")
    print("done.")


if __name__ == "__main__":
    main()
