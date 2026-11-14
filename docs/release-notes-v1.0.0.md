# FlakeHunter v1.0.0

The first release: a GitHub Action and CLI that classify failing CI tests as **product bug, flaky test, environment problem, test-code bug or unknown**, and explain each one in a single sticky PR comment.

## Highlights

- **Five-line install.** Add one step after your tests with `if: failure()`. Works with any JUnit XML: pytest, Cypress, Jest and Maven Surefire.
- **Free, open model, no API key.** The Action runs Llama 3.2 3B on the GitHub runner with llama.cpp. The binary and model are pinned and SHA-256-verified, and the model is cached. Locally the same model runs through Ollama.
- **Rules first, model second.** Deterministic rules for connection errors, DNS, out-of-memory, "passed on re-run" and stale selectors in changed test files; the model handles the rest, returning schema-validated JSON.
- **Measured.** 125 labelled failures: 62% accuracy combined vs 52% model-only and 31% rules-only, and 100% accuracy on the 17% of verdicts with confidence ≥ 0.8. See `evals/results.md`.
- **Safe by default.** Secret redaction before anything reaches the model or the comment, least-privilege permissions, fork detection, prompt-injection hygiene, XXE-safe XML parsing, and it fails open: it never turns a build red.

## Inputs

`junit` (required), `logs`, `retry-report`, `max-failures` (10), `label` (true), `use-llm` (true), `model-url`, `model-sha256`, `github-token`.

## Known limitations

A 3B model is a weak judge on its own (model-only verdicts are capped at confidence 0.7); flaky detection needs a re-run report; CPU inference takes 15–40 s per unclear failure in CI. Full list in the README.
