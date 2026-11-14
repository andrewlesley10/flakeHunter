## Error analysis (written by hand)

**The headline.** Rules alone are always right when they speak, but they speak for only 17% of failures. The 3B model alone reaches 52%. The combined pipeline reaches **62% accuracy (macro F1 0.55)** with 17% fewer tokens than the model alone, and everything it reports at confidence ≥ 0.8 (17% of failures) was correct.

**What the model gets wrong, in order of how often:**

1. **Product bug vs test bug, both ways (12 of the 48 errors).** From an assertion alone (`assert 0 == -2 where 0 = restock_amount(12, 10)`), you often can't tell whether the code or the expectation is wrong; a human needs the spec or the diff too. The model leans towards `test_code`. This is the hardest boundary and the one most dependent on PR context.
2. **Timing and randomness read as test bugs (7).** `assert (t1 - t0) < 0.1` or a shuffled list looks like a bad test to the model, and arguably it *is* a badly written test. These are labelled `flaky_test` because the outcome changes between runs. When a re-run passes, the `passed_on_retry` rule catches them (12 of 20 flaky failures). When the re-run fails too, the model has nothing to tell it the result varies.
3. **`unknown` is almost never predicted (1 of 12).** A small model prefers a confident guess to "not enough evidence", even though the prompt allows it. The `unknown` labels themselves are judgement calls (ambiguous specs, bare `assert False`).
4. **Real build logs are hard (LogChunks: 33%).** These are whole Travis builds, not test reports: lint, compiler and dependency failures, plus 30–1,600-line logs with no test name to search for. Trimming keeps only half of the hand-marked failure lines (see the trimming table), so the model often never sees the cause.

**What changed because of this evaluation:**

| Change | Combined accuracy |
|---|---|
| Prompt v2, model can override rules (first run) | 48% |
| + prompt v3 (two decision rules), rule wins disagreements, model-only confidence capped at 0.7 | 56% |
| + harvester fix: re-run results were missing for most items (see DECISIONS 014) | 62% |
| Log trimming: use the whole line budget for the no-match tail | LogChunks chunk recall 32% → 50% |

The second row was tuned and measured on the **same** set, with no held-out split, so treat it as optimistic. The third row is a data fix, not tuning: it restored the retry signal the rules are designed to use.

**Calibration.** The 3B model's own confidence is close to meaningless: its "≥ 0.8" answers were right about half the time. FlakeHunter therefore caps model-only confidence at 0.7, so a high-confidence verdict on a PR always means a rule backed it.

**The larger model.** Comparing against `llama3.1:8b` was planned, but its 4.9 GB download kept failing on this connection. Run `uv run python evals/run_evals.py --models llama3.2:3b llama3.1:8b` once it's pulled; the 3B rows will come from the cache.
