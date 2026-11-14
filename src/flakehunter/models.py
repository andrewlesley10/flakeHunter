"""Core data models shared by every pipeline stage."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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


Outcome = Literal["passed", "failed", "skipped"]


Category = Literal["product_bug", "flaky_test", "environment", "test_code", "unknown"]
"""The five verdicts. Definitions and precedence: docs/categories.md."""


class RuleHint(BaseModel):
    """What a deterministic rule concluded about one failure, and why."""

    model_config = ConfigDict(frozen=True)

    rule: str  # name of the rule that fired, shown in the PR comment
    category: Category
    confidence: float = Field(ge=0, le=1)
    evidence: tuple[str, ...] = ()  # the exact lines that matched


class Verdict(BaseModel):
    """What the LLM must return for one failure. Validated before it is trusted.

    Field limits are part of the contract: a reply that breaks them is invalid and
    gets one repair attempt (see ``llm.py``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: Category
    confidence: float = Field(ge=0, le=1)
    likely_cause: str = Field(min_length=1, max_length=400)
    evidence: list[str] = Field(default_factory=list, max_length=5)  # exact log lines
    suggested_next_step: str = Field(min_length=1, max_length=400)
    related_changed_files: list[str] = Field(default_factory=list, max_length=10)


DecidedBy = Literal["rules", "llm", "combined", "fallback"]


class FinalVerdict(BaseModel):
    """The verdict shown on the PR: rules and LLM merged. Filled in by our code, not the model."""

    model_config = ConfigDict(frozen=True)

    test_id: str
    test_name: str
    file: str | None = None
    category: Category
    confidence: float = Field(ge=0, le=1)
    likely_cause: str
    evidence: tuple[str, ...] = ()
    suggested_next_step: str
    related_changed_files: tuple[str, ...] = ()
    decided_by: DecidedBy
    rule: str | None = None  # the rule that fired, if any
    note: str | None = None  # e.g. why the LLM result was not used
