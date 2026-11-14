"""Checks that keep the release honest: versions agree and every input is documented."""

import re
import tomllib
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def action_inputs() -> list[str]:
    """Input names from action.yml, read without a YAML library (no extra dependency)."""
    text = (ROOT / "action.yml").read_text(encoding="utf-8")
    block = text.split("\ninputs:\n", 1)[1].split("\nruns:\n", 1)[0]
    return re.findall(r"^  ([a-z][a-z0-9-]*):\s*$", block, flags=re.MULTILINE)


def test_version_matches_pyproject() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert version("flakehunter") == pyproject["project"]["version"]


def test_action_inputs_are_found() -> None:
    assert {"junit", "use-llm", "github-token"} <= set(action_inputs())


def test_action_yml_inputs_documented() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    missing = [name for name in action_inputs() if f"| `{name}` |" not in readme]
    assert not missing, f"inputs missing from the README table: {missing}"


def test_action_never_interpolates_inputs_into_scripts() -> None:
    """Script-injection guard: ${{ inputs.* }} may only appear in env/with/if, not in run."""
    text = (ROOT / "action.yml").read_text(encoding="utf-8")
    for run_block in re.findall(r"run: \|\n((?:        .*\n?)+)", text):
        assert "${{" not in run_block
