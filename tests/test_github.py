import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from flakehunter import cli
from flakehunter.cli import main
from flakehunter.github import GitHubClient, read_event, write_step_summary
from flakehunter.report import MARKER

API = "https://api.github.com"
REPO = "acme/shop"
COMMENTS = f"{API}/repos/{REPO}/issues/7/comments"
FIXTURES = Path(__file__).parent / "fixtures"
JUNIT = str(FIXTURES / "junit" / "pytest" / "report.xml")
RETRY = FIXTURES / "retry"


def client() -> GitHubClient:
    return GitHubClient("t0ken", REPO, http=httpx.Client())


def comment(id_: int, body: str) -> dict[str, Any]:
    return {"id": id_, "body": body}


# --- client ----------------------------------------------------------------


@respx.mock
def test_pr_diff_uses_diff_accept_header() -> None:
    route = respx.get(f"{API}/repos/{REPO}/pulls/7").mock(
        return_value=httpx.Response(200, text="diff --git a/x b/x")
    )
    assert client().pr_diff(7) == "diff --git a/x b/x"
    request = route.calls[0].request
    assert request.headers["accept"] == "application/vnd.github.diff"
    assert request.headers["authorization"] == "Bearer t0ken"


@respx.mock
def test_upsert_creates_when_no_marker() -> None:
    respx.get(COMMENTS).mock(return_value=httpx.Response(200, json=[comment(1, "LGTM")]))
    post = respx.post(COMMENTS).mock(return_value=httpx.Response(201, json={}))
    assert client().upsert_comment(7, f"{MARKER}\nreport") == "created"
    assert json.loads(post.calls[0].request.content) == {"body": f"{MARKER}\nreport"}


@respx.mock
def test_upsert_updates_existing_marker_comment() -> None:
    respx.get(COMMENTS).mock(
        return_value=httpx.Response(200, json=[comment(1, "hi"), comment(2, f"{MARKER} old")])
    )
    patch = respx.patch(f"{API}/repos/{REPO}/issues/comments/2").mock(
        return_value=httpx.Response(200, json={})
    )
    post = respx.post(COMMENTS)
    assert client().upsert_comment(7, f"{MARKER} new") == "updated"
    assert patch.called
    assert not post.called


@respx.mock
def test_upsert_paginates_comments() -> None:
    page1 = [comment(i, "noise") for i in range(100)]
    page2 = [comment(500, f"{MARKER} old")]
    respx.get(COMMENTS, params={"page": "1"}).mock(return_value=httpx.Response(200, json=page1))
    respx.get(COMMENTS, params={"page": "2"}).mock(return_value=httpx.Response(200, json=page2))
    patch = respx.patch(f"{API}/repos/{REPO}/issues/comments/500").mock(
        return_value=httpx.Response(200, json={})
    )
    assert client().upsert_comment(7, "new") == "updated"
    assert patch.called


@respx.mock
def test_add_label_payload() -> None:
    route = respx.post(f"{API}/repos/{REPO}/issues/7/labels").mock(
        return_value=httpx.Response(200, json=[])
    )
    client().add_label(7)
    assert json.loads(route.calls[0].request.content) == {"labels": ["likely-flaky"]}


# --- events ------------------------------------------------------------------


def write_event(tmp_path: Path, head_repo: str = REPO, pr: bool = True) -> dict[str, str]:
    event: dict[str, Any] = {"repository": {"full_name": REPO}}
    if pr:
        event["pull_request"] = {"number": 7, "head": {"repo": {"full_name": head_repo}}}
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event))
    return {
        "GITHUB_EVENT_PATH": str(path),
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_TOKEN": "t0ken",
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
    }


def test_read_event_pull_request(tmp_path: Path) -> None:
    event = read_event(write_event(tmp_path))
    assert event is not None
    assert (event.number, event.repo, event.is_fork) == (7, REPO, False)


def test_read_event_fork(tmp_path: Path) -> None:
    event = read_event(write_event(tmp_path, head_repo="mallory/shop"))
    assert event is not None
    assert event.is_fork


def test_read_event_push_is_none(tmp_path: Path) -> None:
    assert read_event(write_event(tmp_path, pr=False)) is None
    assert read_event({}) is None


def test_step_summary_drops_marker(tmp_path: Path) -> None:
    path = tmp_path / "s.md"
    write_step_summary(f"{MARKER}\n# hi", {"GITHUB_STEP_SUMMARY": str(path)})
    assert path.read_text() == "\n# hi\n"


# --- the entry point ---------------------------------------------------------


def run_github(monkeypatch: pytest.MonkeyPatch, env: dict[str, str], *extra: str) -> int:
    for key in ("GITHUB_EVENT_PATH", "GITHUB_TOKEN", "GITHUB_API_URL", "FLAKEHUNTER_PROVIDER"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return main(["github", "--junit", JUNIT, "--no-llm", *extra])


@respx.mock
def test_github_posts_comment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env = write_event(tmp_path)
    respx.get(f"{API}/repos/{REPO}/pulls/7").mock(return_value=httpx.Response(200, text=""))
    respx.get(COMMENTS).mock(return_value=httpx.Response(200, json=[]))
    post = respx.post(COMMENTS).mock(return_value=httpx.Response(201, json={}))
    label = respx.post(f"{API}/repos/{REPO}/issues/7/labels")

    assert run_github(monkeypatch, env) == 0
    body = json.loads(post.calls[0].request.content)["body"]
    assert body.startswith(MARKER)
    assert not label.called  # nothing flaky in this fixture
    assert "FlakeHunter" in (tmp_path / "summary.md").read_text()
    assert "created the PR comment" in capsys.readouterr().err


@respx.mock
def test_github_labels_flaky(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = write_event(tmp_path)
    respx.get(f"{API}/repos/{REPO}/pulls/7").mock(return_value=httpx.Response(200, text=""))
    respx.get(COMMENTS).mock(return_value=httpx.Response(200, json=[]))
    respx.post(COMMENTS).mock(return_value=httpx.Response(201, json={}))
    label = respx.post(f"{API}/repos/{REPO}/issues/7/labels").mock(
        return_value=httpx.Response(200, json=[])
    )
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    args = ["github", "--junit", str(RETRY / "first.xml"), "--no-llm"]
    assert main([*args, "--retry-report", str(RETRY / "retry.xml")]) == 0
    assert label.called
    label.reset()
    assert main([*args, "--retry-report", str(RETRY / "retry.xml"), "--label", "false"]) == 0
    assert not label.called


@respx.mock
def test_fork_pr_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env = write_event(tmp_path, head_repo="mallory/shop")
    assert run_github(monkeypatch, env) == 0  # respx.mock fails on any unmocked request
    assert "fork PRs get a read-only token" in capsys.readouterr().err
    assert "FlakeHunter" in (tmp_path / "summary.md").read_text()


def test_non_pr_event_prints_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env = write_event(tmp_path, pr=False)
    assert run_github(monkeypatch, env) == 0
    captured = capsys.readouterr()
    assert "not a pull_request event" in captured.err
    assert captured.out.startswith(MARKER)


@respx.mock
def test_github_entry_never_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env = write_event(tmp_path)
    respx.route(host="api.github.com").mock(return_value=httpx.Response(500))
    assert run_github(monkeypatch, env) == 0
    err = capsys.readouterr().err
    assert "::warning::FlakeHunter: could not read the PR diff" in err
    assert "::warning::FlakeHunter: HTTPStatusError" in err


def test_missing_token_falls_back_to_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env = write_event(tmp_path)
    del env["GITHUB_TOKEN"]
    for key in ("GITHUB_TOKEN", "GH_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert main(["github", "--junit", JUNIT]) == 0  # LLM wanted, but no token
    captured = capsys.readouterr()
    assert "using rules only" in captured.err
    assert "rules only" in captured.out


def test_github_defaults_to_github_models() -> None:
    args = cli.build_parser().parse_args(["github", "--junit", "x"])
    assert args.provider == "github-models"
