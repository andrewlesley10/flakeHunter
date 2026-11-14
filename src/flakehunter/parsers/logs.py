"""Load raw CI log files as clean lines.

CI logs are full of terminal colour codes (``\\x1b[31m``) and Windows line endings,
and are not always valid UTF-8. Those codes waste LLM tokens and break the regexes
in the rules, so they are stripped here, once, at the edge.
"""

import re
from glob import glob
from pathlib import Path

# ANSI escape sequences: colours/styles (ESC [ ... m), cursor moves, and the
# OSC sequences some CI systems emit (ESC ] ... BEL).
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")


def strip_ansi(text: str) -> str:
    """Remove terminal colour and control sequences."""
    return _ANSI.sub("", text)


def load_log(path: Path) -> list[str]:
    """Read one log file as a list of lines without colour codes or line endings.

    Undecodable bytes are replaced (shown as U+FFFD) instead of raising.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    return strip_ansi(text).splitlines()


def load_logs(pattern: str) -> dict[str, list[str]]:
    """Load every file matching the glob, keyed by path, in a stable order.

    An empty pattern returns an empty dict, because logs are optional.
    """
    if not pattern:
        return {}
    return {match: load_log(Path(match)) for match in sorted(glob(pattern, recursive=True))}
