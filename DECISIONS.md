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

## 004 · Reject DTDs in JUnit reports to prevent XXE

**Context:** JUnit reports come from CI runs that a pull request can influence, so they are untrusted input. XML allows a DTD to declare *entities*, which can read local files (XXE) or expand into gigabytes of text ("billion laughs"). FlakeHunter sends failure text to an LLM and posts it in a public PR comment, so a leaked file would be published. junitparser silently switches to lxml if it's installed, and lxml resolves entities by default.

**Decision:** Before junitparser sees a file, parse it with the standard library's expat parser with handlers that raise `UnsafeXMLError` on any DOCTYPE, entity declaration or external entity reference. Real JUnit reports never contain a DTD, so legitimate files are unaffected.

**Why:**
- It works whichever XML backend junitparser picks.
- Expat decodes the document's declared encoding before checking, and stops at the first DTD, before anything is expanded.
- It needs no new dependency (`defusedxml` would also work, but expat is already in the standard library).

**How I got here:** my first version searched the raw bytes for `<!DOCTYPE`. An automated security review pointed out that a UTF-16 file stores it as `<\0!\0D\0...`, which a byte search never matches. I reproduced the bypass, switched to expat, and now test every attack in both UTF-8 and UTF-16. Lesson: to make a security decision about a format, use a parser for that format rather than a text search.

**Trade-offs:**
- Each report is parsed twice (expat, then junitparser). Reports are small, so the cost is negligible.
- A file with a harmless DTD is rejected outright rather than sanitised.

**Would revisit if:** a widely used test runner started emitting DTDs in its reports.

## 005 · Rules as data, highest confidence wins, LLM below 0.8

**Context:** Many CI failures are obvious (`Connection refused`, a test that passed on retry). Sending those to an LLM wastes time and rate limit, and makes the verdict harder to explain. Some patterns, like timeouts, are genuinely ambiguous.

**Decision:**
- Rules are a list of `Rule(name, category, confidence, check)` objects, not an if/else chain.
- Every rule is checked; the **highest confidence wins**, and ties go to the rule listed first.
- Hints at or above **0.8** are final. Below that, the failure goes to the LLM *with the hint attached* as context.
- Rules search the failure output (message, stack trace, stdout), never the test name.

**Why:**
- Data-driven rules can be tested by parametrising over the list, and the evals can report per-rule hit rates.
- Confidence routes work instead of being decoration: `timeout_generic` is 0.6 on purpose, because a timeout can be a slow environment *or* a flaky race.
- "Passed on retry" is the strongest evidence there is (0.95), so it beats an environment match in the same output.
- Searching the test name would misfire on names like `test_connection_refused_is_retried`.

**Trade-offs:**
- Confidence values are hand-picked until the evals (M9) calibrate them.
- Conservative patterns miss some cases. That's deliberate: a wrong rule is worse than no rule, because it is confidently wrong *and* skips the LLM.

**Would revisit if:** the M9 evals show a rule's precision below its confidence, or the LLM clearly beats a rule on its own category.

## 006 · One gate before the LLM: trim, then redact, then truncate

**Context:** CI logs are sensitive (tokens, passwords in URLs, auth headers, env dumps) and large (often tens of thousands of lines). In M5, failure text goes to a model, which in CI is a third-party service (GitHub Models). Leaking a user's token into a prompt or a public PR comment would be a serious incident.

**Decision:** `redact.prepare_for_llm()` is the only way to turn raw failure output into prompt text. It works in a fixed order:
1. **Trim** to whole lines around the failure (merged windows, gaps marked, tail fallback, hard line cap).
2. **Redact** with an ordered pattern table: PEM keys, then vendor tokens (GitHub, AWS, Slack, Stripe, OpenAI, Google, npm, JWT), then auth headers and URL credentials, then generic `key=value` and `--password` flags. Secrets become typed placeholders such as `[REDACTED:github_token]`, and the counts feed the report footer.
3. **Truncate** over-long lines.

**Why:**
- With exactly one path from raw text to prompt, a reviewer audits one function.
- Trimming first means less text to scan, and working on whole lines never cuts a secret in half.
- Truncating *after* redaction matters: cutting first could leave a partial token too short for its pattern, which would then leak.
- Typed placeholders keep diagnostic value ("an auth token was sent") without the value.

**Found by the tests:** a Redis URL with an empty username (`redis://:password@host`) leaked, because the pattern required a username. The adversarial test caught it before it shipped.

**Trade-offs:**
- Regex redaction is best-effort. It's one layer of several, alongside least-privilege tokens (M7) and minimal context.
- Generic `key=value` masking over-redacts (`pwd=/home/runner/work` becomes `pwd=[REDACTED]`). Hiding a harmless path costs much less than leaking a password.
- Tests guard against *under*-redaction too: git SHAs, UUIDs and the word "token" in prose are kept.

**Would revisit if:** false positives start hiding real evidence in the evals, or a new widely used token format appears (add a pattern and a test).
