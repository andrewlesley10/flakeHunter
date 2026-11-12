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
