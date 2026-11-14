# Decisions

Key design decisions and their trade-offs. Each entry gives the context, the decision, why it was made, what it costs, and when to revisit it.

## 001 · Composite Action instead of Docker

**Context:** FlakeHunter is a Python CLI that has to run inside other people's GitHub Actions workflows. GitHub supports three kinds of custom action: Docker, JavaScript and composite.

**Decision:** Use a composite Action that installs uv with `astral-sh/setup-uv` and runs the CLI with `uvx --from "$GITHUB_ACTION_PATH" flakehunter ...`.

**Why:**
- It runs on Linux, macOS and Windows runners. Docker container actions run on Linux runners only.
- It starts in seconds. A Docker action builds or pulls an image on every run.
- Developing it doesn't need Docker installed locally.
- The package is pure Python, so it needs no system dependencies.
- A JavaScript action would mean rewriting the tool in TypeScript.

**Trade-offs:**
- Dependencies are resolved when the Action runs rather than baked into an image. A committed `uv.lock` keeps this reproducible.
- It relies on a third-party action (`setup-uv`), which is widely used and pinned to a major version.

**Would revisit if:** FlakeHunter needed system packages that can't be installed with pip, or runtime resolution became a reliability problem.

## 002 · uv for Python packaging and environments

**Context:** The project needs to manage the Python version, a virtual environment, runtime and dev dependencies, and a lock file, the same way on a laptop and in CI. The usual options are pip with venv, Poetry, or uv.

**Decision:** Use uv for everything. `pyproject.toml` declares the dependencies, `uv.lock` pins them, and CI installs with `uv sync --locked`.

**Why:**
- One tool covers the Python version (`uv python install`), the virtual environment, dependencies (`uv add`) and locking, so there's no juggling pip, venv and pip-tools.
- It's fast, which shortens every CI run.
- `uv sync --locked` fails if the lock file is out of date, so CI always tests exactly the versions that were locked.
- `uvx` runs the package without a separate install step. This is how the composite Action runs FlakeHunter (see 001).

**Trade-offs:**
- uv is newer than pip or Poetry, so some contributors won't know it yet.
- The project depends on one vendor's tooling (Astral).

**Would revisit if:** contributors found it a barrier, or the project had to fit an organisation standardised on another tool.

## 003 · mypy in strict mode

**Context:** Python doesn't check types before code runs. FlakeHunter handles messy input: JUnit XML where attributes may be missing, and LLM output, which is untrusted and can be anything.

**Decision:** Run mypy with `strict = true` on both `src` and `tests`, enforced in CI. Untyped third-party libraries get a targeted override (currently `junitparser`) instead of loosening the global settings.

**Why:**
- Missing XML attributes and malformed model replies produce lots of "this might be `None`" cases. Strict typing catches these before the code runs, not in a user's CI.
- Type hints document what each function takes and returns, which keeps the pipeline stages' contracts clear.
- Starting strict on an empty codebase costs almost nothing. Adding it later would mean fixing hundreds of errors at once.

**Trade-offs:**
- More annotations to write, including in tests.
- Untyped libraries need per-module overrides.
- pydantic needs its mypy plugin (`pydantic.mypy`) before mypy understands frozen models and model constructors.
- Some time goes on satisfying the checker rather than on features.

**Would revisit if:** the checker's overhead clearly outweighed the bugs it caught. That's unlikely for a project that parses untrusted input.
