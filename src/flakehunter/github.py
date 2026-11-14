"""GitHub REST client and the ``flakehunter github`` entry point used by the Action.

Production concerns live here:
- **Idempotency:** one comment per PR, found again by a hidden marker and edited in
  place on every run (comments are paginated, so all pages are searched).
- **Forks:** PRs from forks get a read-only token, so they are detected up front and
  only the job summary is written.
- **Fail open:** every error becomes a ``::warning::`` annotation and exit code 0.
"""

import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from flakehunter.report import MARKER

API_URL = "https://api.github.com"
FLAKY_LABEL = "likely-flaky"
TIMEOUT_S = 30.0


class GitHubClient:
    """The few REST calls FlakeHunter needs. PR comments live under the *issues* API."""

    def __init__(
        self,
        token: str,
        repo: str,
        api_url: str = API_URL,
        http: httpx.Client | None = None,
    ) -> None:
        self.repo = repo
        self._http = http or httpx.Client(timeout=TIMEOUT_S)
        self._base = api_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "flakehunter",
        }

    def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        headers = {**self._headers, **kw.pop("headers", {})}
        resp = self._http.request(method, f"{self._base}{path}", headers=headers, **kw)
        resp.raise_for_status()
        return resp

    def pr_diff(self, number: int) -> str:
        resp = self._request(
            "GET",
            f"/repos/{self.repo}/pulls/{number}",
            headers={"Accept": "application/vnd.github.diff"},
        )
        return resp.text

    def find_comment(self, number: int, marker: str = MARKER) -> int | None:
        """Return the id of the first comment containing ``marker``, searching all pages."""
        page = 1
        while True:
            comments = self._request(
                "GET",
                f"/repos/{self.repo}/issues/{number}/comments",
                params={"per_page": 100, "page": page},
            ).json()
            for comment in comments:
                if marker in (comment.get("body") or ""):
                    return int(comment["id"])
            if len(comments) < 100:
                return None
            page += 1

    def upsert_comment(self, number: int, body: str, marker: str = MARKER) -> str:
        """Edit FlakeHunter's comment if it exists, otherwise create it. Returns the action."""
        existing = self.find_comment(number, marker)
        if existing is None:
            self._request(
                "POST", f"/repos/{self.repo}/issues/{number}/comments", json={"body": body}
            )
            return "created"
        self._request(
            "PATCH", f"/repos/{self.repo}/issues/comments/{existing}", json={"body": body}
        )
        return "updated"

    def add_label(self, number: int, label: str = FLAKY_LABEL) -> None:
        self._request(
            "POST", f"/repos/{self.repo}/issues/{number}/labels", json={"labels": [label]}
        )


@dataclass(frozen=True)
class PullRequestEvent:
    number: int
    repo: str
    is_fork: bool


def read_event(env: Mapping[str, str]) -> PullRequestEvent | None:
    """The PR this workflow run is about, or None if it isn't a pull_request event."""
    path = env.get("GITHUB_EVENT_PATH")
    if not path or not Path(path).is_file():
        return None
    event = json.loads(Path(path).read_text(encoding="utf-8"))
    pr = event.get("pull_request")
    if not isinstance(pr, dict):
        return None
    repo = env.get("GITHUB_REPOSITORY") or event["repository"]["full_name"]
    head_repo = ((pr.get("head") or {}).get("repo") or {}).get("full_name")
    return PullRequestEvent(
        number=int(pr["number"]),
        repo=repo,
        is_fork=head_repo is not None and head_repo != repo,
    )


def annotate(level: str, message: str) -> None:
    """A GitHub Actions workflow command: shows up on the run's summary page."""
    message = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::{level}::FlakeHunter: {message}", file=sys.stderr)


def write_step_summary(markdown: str, env: Mapping[str, str] | None = None) -> None:
    path = (env or os.environ).get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(markdown.replace(MARKER, "") + "\n")
