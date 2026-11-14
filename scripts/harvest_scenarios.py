"""Run the scenario suite for real and save each failure as an eval item.

    uv run python scripts/harvest_scenarios.py [--runs 12]

Each round runs ``evals/scenarios`` once, then re-runs only the tests that failed
(like ``pytest --lf``). The first time a test fails, its JUnit record and its re-run
outcome are saved. Flaky tests need several rounds before they show up, which is why
there are several. Output: ``evals/dataset/scenarios.jsonl`` (our own data, committed).
The true category of each test comes from ``evals/scenarios/manifest.csv``.
"""

import argparse
import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from flakehunter.parsers.junit import parse_junit, parse_outcomes

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = ROOT / "evals" / "scenarios"
OUT = ROOT / "evals" / "dataset" / "scenarios.jsonl"


def run_pytest(args: list[str], junit: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "no:randomly",
            "--continue-on-collection-errors",
            f"--junitxml={junit}",
            "--rootdir",
            str(SCENARIOS),
            *args,
        ],
        cwd=SCENARIOS,
        capture_output=True,
        check=False,
    )


def manifest() -> dict[str, dict[str, str]]:
    with (SCENARIOS / "manifest.csv").open(encoding="utf-8") as f:
        return {row["test"]: row for row in csv.DictReader(f)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=12)
    args = parser.parse_args()
    labels = manifest()
    items: dict[str, dict[str, object]] = {}

    with tempfile.TemporaryDirectory() as tmp:
        for round_no in range(1, args.runs + 1):
            first, retry = Path(tmp) / f"first-{round_no}.xml", Path(tmp) / f"retry-{round_no}.xml"
            run_pytest(["."], first)
            failures = [f for f in parse_junit(first) if f.id not in items]
            if not failures:
                continue
            node_ids = sorted({_node_id(f.classname, f.name) for f in failures})
            run_pytest(node_ids, retry)
            outcomes = parse_outcomes(retry) if retry.exists() else {}
            for f in failures:
                meta = labels.get(f.id, {})
                items[f.id] = {
                    "failure_id": f.id,
                    "source": "scenarios",
                    "failure": f.model_dump(mode="json"),
                    "retry": outcomes.get(f.id) if outcomes.get(f.id) != "skipped" else None,
                    "changed_files": [p for p in (meta.get("changed_files") or "").split(";") if p],
                    "logs": {},
                }
            print(f"round {round_no}: {len(items)} failures so far", file=sys.stderr)

    unknown = sorted(set(items) - set(labels))
    if unknown:
        print("not in manifest.csv (add them):\n  " + "\n  ".join(unknown), file=sys.stderr)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        for key in sorted(items):
            f.write(json.dumps(items[key], sort_keys=True) + "\n")
    print(f"wrote {len(items)} items to {OUT.relative_to(ROOT)}", file=sys.stderr)


def _node_id(classname: str | None, name: str) -> str:
    module = (classname or "").replace(".", "/")
    return f"{module}.py::{name}" if module else name


if __name__ == "__main__":
    main()
