"""Render a ``Report`` as Markdown (the PR comment body) or JSON.

The Markdown is built for scanning: a summary line, one table row per failure, and
the evidence collapsed in ``<details>`` blocks. Every piece of text that came from CI
output is escaped, so a test name can't break the table or inject HTML/mentions.
"""

import html
import re

from flakehunter.models import Category, FinalVerdict
from flakehunter.pipeline import Report

MARKER = "<!-- flakehunter -->"
MAX_COMMENT_CHARS = 60_000  # GitHub's limit is 65,536

LABELS: dict[Category, str] = {
    "product_bug": "🐛 product bug",
    "flaky_test": "🎲 flaky test",
    "environment": "🌩️ environment",
    "test_code": "🧪 test code",
    "unknown": "❓ unknown",
}
ORDER: tuple[Category, ...] = ("product_bug", "test_code", "flaky_test", "environment", "unknown")


def escape_cell(text: str) -> str:
    """Make arbitrary text safe inside a Markdown table cell."""
    text = html.escape(" ".join(text.split()), quote=False)
    text = text.replace("|", "\\|").replace("`", "'")
    return _no_mentions(text)


def _no_mentions(text: str) -> str:
    """Stop CI text from pinging GitHub users or teams (@someone)."""
    return re.sub(r"@(?=[A-Za-z0-9])", "@​", text)


def _code_block(lines: tuple[str, ...]) -> str:
    body = "\n".join(lines)
    fence = "```"
    while fence in body:
        fence += "`"
    return f"{fence}text\n{body}\n{fence}"


def _decided(v: FinalVerdict) -> str:
    if v.decided_by == "rules" and v.rule:
        return f"rules (`{v.rule}`)"
    return v.decided_by


def _details(v: FinalVerdict) -> str:
    parts = [
        f"<details><summary><code>{_no_mentions(html.escape(v.test_name))}</code>: why</summary>",
        f"**Test:** `{escape_cell(v.test_id)}`"
        + (f" in `{escape_cell(v.file)}`" if v.file else ""),
        f"**Likely cause:** {_no_mentions(html.escape(v.likely_cause, quote=False))}",
    ]
    if v.evidence:
        parts.append("**Evidence:**\n\n" + _code_block(v.evidence))
    parts.append(f"**Next step:** {_no_mentions(html.escape(v.suggested_next_step, quote=False))}")
    if v.related_changed_files:
        files = ", ".join(f"`{escape_cell(f)}`" for f in v.related_changed_files)
        parts.append(f"**Related changed files:** {files}")
    if v.note:
        parts.append(f"<sub>Note: {_no_mentions(html.escape(v.note, quote=False))}</sub>")
    return "\n\n".join(parts) + "\n\n</details>"


def _footer(r: Report) -> str:
    bits = [f"{r.model} via {r.provider}" if r.model else "rules only"]
    if r.llm_calls:
        bits.append(f"{r.llm_calls} model calls")
        bits.append(f"{r.tokens_in + r.tokens_out:,} tokens")
    bits.append(f"{r.elapsed_s:.1f} s")
    if r.secrets_masked:
        bits.append(f"{r.secrets_masked} secret{'s' if r.secrets_masked != 1 else ''} masked")
    bits.append(f"FlakeHunter v{r.version}")
    return "<sub>" + " · ".join(bits) + "</sub>"


def to_markdown(r: Report) -> str:
    if not r.verdicts:
        return f"{MARKER}\n## 🔎 FlakeHunter: no failing tests found\n\n{_footer(r)}\n"

    n = len(r.verdicts)
    counts = r.summary
    summary = ", ".join(f"{counts[c]} {LABELS[c]}" for c in ORDER if counts[c])
    lines = [
        MARKER,
        f"## 🔎 FlakeHunter: {n} failing test{'s' if n != 1 else ''} analysed",
        "",
        summary,
        "",
        "| Test | Verdict | Confidence | Decided by |",
        "|---|---|---|---|",
    ]
    ordered = sorted(r.verdicts, key=lambda v: ORDER.index(v.category))
    for v in ordered:
        lines.append(
            f"| `{escape_cell(v.test_name)}` | {LABELS[v.category]} | {v.confidence:.2f} "
            f"| {_decided(v)} |"
        )
    lines.append("")
    for v in ordered:
        lines.extend([_details(v), ""])
    for note in r.notes:
        lines.extend([f"> {html.escape(note, quote=False)}", ""])
    source = "rules and an open model" if r.model else "pattern rules"
    lines.append(f"<sub>Verdicts are suggestions from {source}; check before acting.</sub><br>")
    lines.append(_footer(r))
    body = "\n".join(lines) + "\n"
    if len(body) > MAX_COMMENT_CHARS:
        cut = body[: MAX_COMMENT_CHARS - 200]
        body = cut + "\n\n> Report truncated: too long for one comment.\n\n" + _footer(r) + "\n"
    return body


def to_json(r: Report) -> str:
    return r.model_dump_json(indent=2)
