"""Core data models shared by every pipeline stage."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

SourceFormat = Literal["pytest", "cypress", "jest", "surefire", "unknown"]


class TestFailure(BaseModel):
    """One failing test case, normalised from any JUnit XML dialect."""

    __test__ = False  # stop pytest trying to collect this class as a test

    model_config = ConfigDict(frozen=True)

    id: str
    suite: str
    name: str
    classname: str | None = None
    file: str | None = None
    kind: Literal["failure", "error"]
    message: str = ""
    details: str = ""
    stdout: str | None = None
    duration_s: float | None = None
    source_format: SourceFormat = "unknown"


FileStatus = Literal["added", "modified", "deleted", "renamed"]


class FileDiff(BaseModel):
    """One file changed by a pull request, parsed from a unified git diff."""

    model_config = ConfigDict(frozen=True)

    path: str  # path after the change (for deletions: the path that was removed)
    old_path: str | None = None  # set only for renames
    status: FileStatus
    binary: bool = False
    added_lines: tuple[str, ...] = ()  # content of "+" lines, without the "+"
