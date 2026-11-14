# FlakeHunter demo app

A tiny FastAPI shop whose tests fail **on purpose**, one or more per category, so you can
see FlakeHunter's PR comment on real failures. [EXPECTED.md](EXPECTED.md) lists each
deliberate failure and its true category.

```bash
cd examples/demo-app
uv venv && uv pip install -r requirements.txt
.venv/bin/python -m pytest --junitxml=reports/pytest.xml   # some tests fail
uv run --project ../.. flakehunter analyze --junit "reports/*.xml"   # needs Ollama, or add --no-llm
```

In CI, [.github/workflows/demo.yml](../../.github/workflows/demo.yml) runs the pytest and
Cypress tests, re-runs the API tests once to detect flakiness, and then runs FlakeHunter
with GitHub Models.
