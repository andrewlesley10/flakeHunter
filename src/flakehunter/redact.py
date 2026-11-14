"""Redaction and trimming: the single gate between raw CI output and the LLM.

CI logs are both *sensitive* (they leak tokens, passwords in URLs, auth headers) and
*large* (tens of thousands of lines). Before anything is sent to a model, which may be
a third-party service, ``prepare_for_llm`` does three things in a fixed order:

1. **Redact** each *whole* block (message, stack trace, stdout, each full log), replacing
   likely secrets with typed placeholders such as ``[REDACTED:github_token]``. The model
   and the reader still see that *something* was there ("auth failed"), but not the value.
2. **Trim**: keep only lines near the failure.
3. **Truncate long lines**.

Redaction must come first. Any cut made before it (a trim window, a head/tail, a
line-length limit) can split a secret so its pattern no longer matches: a window that
starts inside a multi-line private key drops the ``-----BEGIN`` line and the key body
leaks. Cutting text that has already been redacted can only cut placeholders.

Regex redaction is best-effort: no pattern list catches every secret. It is one layer
of several, alongside least-privilege tokens (M7) and sending as little text as
possible (trimming). ``llm.py`` must only ever build prompts from ``prepare_for_llm``.
"""

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from flakehunter.models import TestFailure

# Values that are already placeholders must not be redacted again (keeps redact idempotent).
_NOT_PLACEHOLDER = r"(?!\[REDACTED)"

_KV_KEYS = (
    r"password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key|client[_-]?secret"
    r"|private[_-]?key|auth[_-]?token|credentials?"
)

# (name, pattern, replacement). Order matters: whole-structure and vendor-specific
# patterns run before generic key=value ones, so the most specific label wins.
PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "private_key",
        # Also matches a block whose END line was trimmed away.
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"
            r"(?:.*?-----END [A-Z0-9 ]*PRIVATE KEY-----|.*\Z)",
            re.DOTALL,
        ),
        "[REDACTED:private_key]",
    ),
    (
        "github_token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{22,255})\b"),
        "[REDACTED:github_token]",
    ),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), "[REDACTED:aws_access_key]"),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "[REDACTED:slack_token]"),
    (
        "stripe_key",
        re.compile(r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{16,}\b"),
        "[REDACTED:stripe_key]",
    ),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}"), "[REDACTED:openai_key]"),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "[REDACTED:google_api_key]"),
    ("npm_token", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b"), "[REDACTED:npm_token]"),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}"),
        "[REDACTED:jwt]",
    ),
    (
        "auth_header",
        re.compile(
            rf"(?i)(\b(?:proxy-)?authorization\s*[:=]\s*[\"']?(?:bearer|basic|token|digest)\s+)"
            rf"{_NOT_PLACEHOLDER}[^\s\"']+"
        ),
        r"\1[REDACTED:auth]",
    ),
    (
        "bearer",
        re.compile(rf"(?i)(\bbearer\s+){_NOT_PLACEHOLDER}[A-Za-z0-9._~+/=-]{{8,}}"),
        r"\1[REDACTED:auth]",
    ),
    (
        "url_credentials",
        # User may be empty (redis://:pw@host). The password is greedy up to the LAST "@"
        # before the path: unencoded "@", "?" and "#" all appear in real passwords
        # (p@ss@host, pa#ss@host). It stops only at "/" or whitespace; when a URL has no
        # path, this can also mask the host. Over-masking is the safe direction.
        re.compile(rf"(?i)(\b[a-z][a-z0-9+.-]*://[^\s:/@]*:){_NOT_PLACEHOLDER}[^\s/]*@"),
        r"\1[REDACTED]@",
    ),
    (
        "cli_flag",
        re.compile(
            rf"(?i)(--?(?:password|passwd|token|api-key|secret)(?:=|\s+)){_NOT_PLACEHOLDER}\S+"
        ),
        r"\1[REDACTED]",
    ),
    (
        "key_value",
        # Quoted value: mask everything up to the matching closing quote, so spaces and
        # commas inside the secret ("correct horse, battery") don't end the match early.
        re.compile(
            rf"(?i)((?:{_KV_KEYS})[A-Za-z0-9_-]*[\"']?\s*[:=]\s*)([\"']){_NOT_PLACEHOLDER}[^\n]*?\2"
        ),
        r"\1\2[REDACTED]\2",
    ),
    (
        "key_value",
        # Unquoted value: password=..., DB_PASSWORD: ..., --token abc
        re.compile(
            rf"(?i)((?:{_KV_KEYS})[A-Za-z0-9_-]*[\"']?\s*[:=]\s*[\"']?)"
            rf"{_NOT_PLACEHOLDER}[^\s\"',;&}}]{{4,}}"
        ),
        r"\1[REDACTED]",
    ),
)

SKIP_MARKER = "[... {n} lines omitted ...]"
MAX_LINE_CHARS = 500


# --- redaction ----------------------------------------------------------------------


def redact_with_stats(text: str) -> tuple[str, Counter[str]]:
    """Mask likely secrets; also return how many of each kind were masked."""
    counts: Counter[str] = Counter()
    for name, pattern, replacement in PATTERNS:
        text, n = pattern.subn(replacement, text)
        if n:
            counts[name] += n
    return text, counts


def redact(text: str) -> str:
    """Mask likely secrets in ``text``. Idempotent: ``redact(redact(x)) == redact(x)``."""
    return redact_with_stats(text)[0]


# --- trimming -------------------------------------------------------------------------


def trim_around(
    lines: Sequence[str],
    needles: Sequence[str],
    before: int = 20,
    after: int = 20,
    max_lines: int = 120,
) -> list[str]:
    """Keep only whole lines near any needle (case-insensitive), merging overlapping windows.

    Gaps are replaced by a marker line. If no needle matches, the *last* lines are kept,
    because CI errors cluster at the end of a log. Output never exceeds ``max_lines``
    content lines; when it would, the windows nearest the end are kept.
    """
    wanted = [n.lower() for n in needles if n.strip()]
    hits = [i for i, line in enumerate(lines) if any(n in line.lower() for n in wanted)]
    if not hits:
        tail = list(lines[-min(max_lines, before + after + 1) :])
        skipped = len(lines) - len(tail)
        return ([SKIP_MARKER.format(n=skipped)] if skipped else []) + tail

    windows: list[list[int]] = []  # merged [start, end) ranges
    for i in hits:
        start, end = max(0, i - before), min(len(lines), i + after + 1)
        if windows and start <= windows[-1][1]:
            windows[-1][1] = max(windows[-1][1], end)
        else:
            windows.append([start, end])

    # Respect max_lines by keeping windows from the end backwards.
    kept: list[list[int]] = []
    budget = max_lines
    for start, end in reversed(windows):
        if budget <= 0:
            break
        start = max(start, end - budget)
        kept.insert(0, [start, end])
        budget -= end - start

    out: list[str] = []
    cursor = 0
    for start, end in kept:
        if start > cursor:
            out.append(SKIP_MARKER.format(n=start - cursor))
        out.extend(lines[start:end])
        cursor = end
    if cursor < len(lines):
        out.append(SKIP_MARKER.format(n=len(lines) - cursor))
    return out


def head_tail(lines: Sequence[str], head: int = 30, tail: int = 30) -> list[str]:
    """Keep the first and last lines of a long block (stack traces matter at both ends)."""
    if len(lines) <= head + tail:
        return list(lines)
    return [*lines[:head], SKIP_MARKER.format(n=len(lines) - head - tail), *lines[-tail:]]


def _truncate_line(line: str) -> str:
    if len(line) <= MAX_LINE_CHARS:
        return line
    return line[:MAX_LINE_CHARS] + f" [... {len(line) - MAX_LINE_CHARS} chars omitted]"


# --- the single gate --------------------------------------------------------------------


@dataclass(frozen=True)
class PreparedContext:
    """Text that is safe to send to a model, plus what was masked (for the report footer)."""

    text: str
    secrets_masked: Counter[str] = field(default_factory=Counter)

    @property
    def total_masked(self) -> int:
        return sum(self.secrets_masked.values())


def prepare_for_llm(
    failure: TestFailure,
    logs: Mapping[str, Sequence[str]] | None = None,
    *,
    before: int = 20,
    after: int = 20,
    max_log_lines: int = 120,
) -> PreparedContext:
    """Build the failure's evidence for the LLM: redact, then trim, then truncate lines.

    This is the only function allowed to turn raw failure output into prompt text.
    Every block is redacted *whole* before any cutting happens (see module docstring).
    """
    counts: Counter[str] = Counter()

    def clean(text: str) -> list[str]:
        redacted, found = redact_with_stats(text)
        counts.update(found)
        return redacted.splitlines()

    message = clean(failure.message)
    needles = [failure.name, *message[:1]]
    sections: list[tuple[str, list[str]]] = [
        ("message", message),
        ("stack trace", head_tail(clean(failure.details))),
    ]
    if failure.stdout:
        sections.append(("stdout", head_tail(clean(failure.stdout), head=0, tail=40)))
    for name, lines in (logs or {}).items():
        trimmed = trim_around(clean("\n".join(lines)), needles, before, after, max_log_lines)
        sections.append((f"log: {name}", trimmed))

    text = "\n".join(
        f"### {title}\n" + "\n".join(_truncate_line(line) for line in lines)
        for title, lines in sections
        if any(lines)
    )
    # Final pass over the assembled text. Section titles (e.g. log file names) were
    # never redacted above, and redact is idempotent, so this only adds masking.
    text, found = redact_with_stats(text)
    counts.update(found)
    return PreparedContext(text=text, secrets_masked=counts)
