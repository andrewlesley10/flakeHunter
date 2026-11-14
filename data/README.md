# Evaluation data

No public dataset labels CI failures with FlakeHunter's five categories, so the labelled
set in [`evals/labels.csv`](../evals/labels.csv) is built from the sources below.
**Raw downloaded data is never committed** (`data/raw/` and `data/processed/` are
git-ignored). Only our own labels and our own generated failures are in git.

| Source | Items | What it is | Labels | Licence |
|---|---|---|---|---|
| Scenario suite (`evals/scenarios/`) | 92 | Small, realistic pytest tests that fail for a known reason when actually run: real bugs, wrong tests, local stand-ins for missing or broken services, and real nondeterminism. `scripts/harvest_scenarios.py` runs them 12 times plus a re-run of the failures and records each failure once. | By design (`manifest.csv`) | Ours (MIT) |
| Demo app (`examples/demo-app/`) | 4 | The pytest failures from the demo PR, run locally with a re-run (`EXPECTED.md`). The Cypress failures appear only in CI and are not in the set. | By design | Ours (MIT) |
| [LogChunks](https://zenodo.org/records/3632351) | 30 of 797 | Real failed Travis CI build logs from 80 open-source repos, with the chunk explaining the failure marked by hand. A fixed random sample (seed 2026) of the logs whose chunk is 1–15 lines is labelled; **all 797** are used for the log-trimming metric. | By Claude, to be reviewed (`labelled_by=claude`) | CC BY 4.0 |

## Download and rebuild

```bash
uv run python scripts/fetch_logchunks.py      # downloads 24 MB into data/raw/, writes data/processed/
uv run python scripts/harvest_scenarios.py    # regenerates evals/dataset/scenarios.jsonl
uv run python scripts/label.py                # review labels one by one in the terminal
uv run python evals/run_evals.py --models llama3.2:3b llama3.1:8b
```

## How LogChunks failures map onto the categories

LogChunks covers whole builds, not just tests, so the mapping is: a defect in the
project's own code or content (compile errors, lint, invalid YAML/Sass, broken docs)
→ `product_bug`; CI configuration, toolchain versions, downloads and third-party sites
→ `environment`; an outdated expected test output → `test_code`; and a chunk that doesn't
show which side is wrong → `unknown`. These labels were proposed by Claude and are
marked `labelled_by=claude` until reviewed with `scripts/label.py`.

## Not used (yet), and why

- **IDoFT** and **ReproFlake** (real flaky tests in open-source Java and Python
  projects): reproducing them means checking out and re-running third-party projects
  many times, and neither states a licence for redistribution. Listed under "What I'd
  do next" in the README.
- **FlaPy**: the same, for harvesting flaky Python tests.

## Credits

LogChunks: C. Brandt, A. Panichella, A. Zaidman, M. Beller. *LogChunks: A Data Set for
Build Log Analysis.* MSR 2020. [doi:10.5281/zenodo.3632351](https://doi.org/10.5281/zenodo.3632351),
licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
