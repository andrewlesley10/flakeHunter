from pathlib import Path

from flakehunter.models import FileDiff
from flakehunter.parsers.diff import changed_files, load_diff, parse_diff

PR_DIFF = load_diff(Path(__file__).parent / "fixtures" / "diff" / "pr.diff")


def by_path(files: list[FileDiff]) -> dict[str, FileDiff]:
    return {f.path: f for f in files}


def test_parses_every_file_section() -> None:
    assert len(parse_diff(PR_DIFF)) == 6


def test_modified_file_added_lines() -> None:
    f = by_path(parse_diff(PR_DIFF))["src/pricing.py"]
    assert f.status == "modified"
    assert f.added_lines == ("    return price - price * pct / 10",)


def test_added_file() -> None:
    f = by_path(parse_diff(PR_DIFF))["tests/test_refunds.py"]
    assert f.status == "added"
    assert len(f.added_lines) == 2


def test_deleted_file() -> None:
    f = by_path(parse_diff(PR_DIFF))["src/legacy.py"]
    assert f.status == "deleted"
    assert f.added_lines == ()


def test_pure_rename_has_no_hunks() -> None:
    f = by_path(parse_diff(PR_DIFF))["src/helpers.py"]
    assert f.status == "renamed"
    assert f.old_path == "src/utils.py"
    assert f.added_lines == ()


def test_binary_file() -> None:
    f = by_path(parse_diff(PR_DIFF))["assets/logo.png"]
    assert f.binary
    assert f.status == "modified"


def test_selector_change_visible_in_cypress_spec() -> None:
    f = by_path(parse_diff(PR_DIFF))["cypress/e2e/checkout.cy.ts"]
    assert "  cy.get('#purchase').click()" in f.added_lines


def test_changed_files_excludes_deleted() -> None:
    files = changed_files(PR_DIFF)
    assert "src/legacy.py" not in files
    assert "src/helpers.py" in files
    assert "src/utils.py" not in files  # old name of a rename


def test_added_line_starting_with_plus_plus_is_content_not_header() -> None:
    diff = (
        "diff --git a/app.js b/app.js\n"
        "--- a/app.js\n"
        "+++ b/app.js\n"
        "@@ -1 +1,2 @@\n"
        " let counter = 0\n"
        "+++counter\n"  # added line whose content is "++counter"
    )
    (f,) = parse_diff(diff)
    assert f.path == "app.js"
    assert f.added_lines == ("++counter",)


def test_path_with_spaces() -> None:
    diff = (
        "diff --git a/docs/my notes.md b/docs/my notes.md\n"
        "--- a/docs/my notes.md\n"
        "+++ b/docs/my notes.md\n"
        "@@ -0,0 +1 @@\n"
        "+hello\n"
    )
    assert changed_files(diff) == ["docs/my notes.md"]


def test_empty_diff() -> None:
    assert parse_diff("") == []
    assert changed_files("") == []
