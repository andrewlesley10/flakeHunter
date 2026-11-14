"""Parse a unified git diff (``git diff`` / GitHub's ``.diff``) into FileDiff records.

The rules use this to ask "did this PR touch the failing test's file?", and the LLM
gets the added lines as evidence. A diff has two parts per file:

- headers (``diff --git``, ``---``/``+++``, ``rename from``, ``new file mode``, ...)
- hunks (after an ``@@`` line) holding the actual ``+``/``-`` content lines

The parser tracks which part it is in. Without that, an added line whose content
starts with ``++`` (it appears as ``+++counter``) would be mistaken for a header.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from flakehunter.models import FileDiff, FileStatus

# "diff --git a/old/path b/new/path". Paths may contain spaces, so match a/... b/...
# against the end of the line rather than splitting on whitespace.
_DIFF_GIT = re.compile(r"^diff --git a/(?P<old>.+) b/(?P<new>.+)$")


@dataclass
class _Builder:
    """Mutable scratch state for one file while its section is being read."""

    path: str
    old_path: str
    status: FileStatus = "modified"
    binary: bool = False
    added: list[str] = field(default_factory=list)

    def build(self) -> FileDiff:
        return FileDiff(
            path=self.path,
            old_path=self.old_path if self.status == "renamed" else None,
            status=self.status,
            binary=self.binary,
            added_lines=tuple(self.added),
        )


def parse_diff(diff_text: str) -> list[FileDiff]:
    """Return one FileDiff per file section in the diff, in diff order."""
    files: list[FileDiff] = []
    current: _Builder | None = None
    in_hunk = False

    for line in diff_text.splitlines():
        header = _DIFF_GIT.match(line)
        if header:
            if current:
                files.append(current.build())
            current = _Builder(path=header["new"], old_path=header["old"])
            in_hunk = False
            continue
        if current is None:
            continue  # preamble before the first file (e.g. email headers)

        if line.startswith("@@"):
            in_hunk = True
        elif in_hunk:
            if line.startswith("+"):
                current.added.append(line[1:])
        else:
            _apply_header(current, line)

    if current:
        files.append(current.build())
    return files


def changed_files(diff_text: str) -> list[str]:
    """Paths that exist after the PR and were changed by it (deleted files excluded)."""
    return [f.path for f in parse_diff(diff_text) if f.status != "deleted"]


def load_diff(path: Path) -> str:
    """Read a diff file; undecodable bytes are replaced rather than raising."""
    return path.read_text(encoding="utf-8", errors="replace")


def _apply_header(current: _Builder, line: str) -> None:
    if line.startswith("new file mode"):
        current.status = "added"
    elif line.startswith("deleted file mode"):
        current.status = "deleted"
        current.path = current.old_path
    elif line.startswith("rename from "):
        current.status = "renamed"
        current.old_path = line.removeprefix("rename from ")
    elif line.startswith("rename to "):
        current.status = "renamed"
        current.path = line.removeprefix("rename to ")
    elif line.startswith("Binary files ") or line == "GIT binary patch":
        current.binary = True
    elif line.startswith("+++ b/"):
        current.path = line.removeprefix("+++ b/")  # most reliable source of the new path
