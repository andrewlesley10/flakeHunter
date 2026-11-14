"""Command-line entry point: ``flakehunter analyze ...`` (and ``flakehunter github`` in M7).

A thin shell around ``run_pipeline``: parse arguments, load files, render. It fails
open: any internal error is printed to stderr as a warning and the exit code is 0,
because FlakeHunter must never be the reason a build goes red. ``--strict`` re-raises
for debugging.
"""

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from flakehunter import github
from flakehunter.config import ConfigError, LLMSettings
from flakehunter.llm import Classifier, OpenAICompatClassifier
from flakehunter.parsers.diff import changed_files, load_diff
from flakehunter.parsers.junit import parse_junit_glob
from flakehunter.parsers.logs import load_logs
from flakehunter.parsers.retry import load_retry_report
from flakehunter.pipeline import DEFAULT_MAX_FAILURES, Report, flakehunter_version, run_pipeline
from flakehunter.report import to_json, to_markdown


def warn(message: str) -> None:
    print(f"flakehunter: warning: {message}", file=sys.stderr)


def add_common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--junit", required=True, help='glob for JUnit XML files (quote it: "r/**/*.xml")'
    )
    p.add_argument("--logs", default="", help="glob for raw log files")
    p.add_argument("--retry-report", default="", help="glob for JUnit XML from a re-run")
    p.add_argument("--provider", choices=["ollama", "openai-compatible"], default=None)
    p.add_argument("--model", default=None, help="model name (default depends on provider)")
    p.add_argument("--max-failures", type=int, default=DEFAULT_MAX_FAILURES)
    p.add_argument("--no-llm", action="store_true", help="rules only, no model calls")
    p.add_argument("--strict", action="store_true", help="raise errors instead of failing open")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flakehunter", description="Classify failing CI tests and explain each one."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {flakehunter_version()}")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze", help="analyse local reports and print a report")
    add_common_args(analyze)
    analyze.add_argument("--diff", default="", help="unified diff of the PR (git diff output)")
    analyze.add_argument("--format", choices=["markdown", "json"], default="markdown")

    gh = sub.add_parser("github", help="run inside GitHub Actions: comment on the PR")
    add_common_args(gh)
    gh.add_argument("--label", default="true", help="add the likely-flaky label (true/false)")
    return parser


def make_classifier(args: argparse.Namespace) -> Classifier | None:
    if args.no_llm:
        return None
    try:
        settings = LLMSettings.from_env(provider=args.provider).with_model(args.model)
    except ConfigError as e:
        warn(f"{e}; using rules only")
        return None
    return OpenAICompatClassifier(settings)


def analyse(args: argparse.Namespace, diff_text: str | None) -> Report:
    """Load inputs named by ``args`` and run the pipeline."""
    failures = parse_junit_glob(args.junit)
    if not failures:
        return run_pipeline([])
    logs = load_logs(args.logs) if args.logs else {}
    retry = load_retry_report(args.retry_report) if args.retry_report else {}
    files = changed_files(diff_text) if diff_text else []
    return run_pipeline(
        failures,
        logs=logs,
        changed_files=files,
        retry=retry,
        classifier=make_classifier(args),
        max_failures=args.max_failures,
    )


def cmd_analyze(args: argparse.Namespace) -> int:
    diff_text = load_diff(Path(args.diff)) if args.diff else None
    report = analyse(args, diff_text)
    if not report.total_failures:
        print("No failing tests found.", file=sys.stderr)
    print(to_json(report) if args.format == "json" else to_markdown(report))
    return 0


def cmd_github(args: argparse.Namespace, env: dict[str, str]) -> int:
    """The Action's entry point. Every failure path logs and returns 0."""
    event = github.read_event(env)
    token = env.get("GITHUB_TOKEN", "")
    client = None
    diff_text = None

    if event is None:
        github.annotate("notice", "not a pull_request event; writing the job summary only")
    elif event.is_fork:
        github.annotate(
            "notice", "skipped commenting: fork PRs get a read-only token. See the job summary."
        )
    elif not token:
        github.annotate("warning", "no GITHUB_TOKEN; writing the job summary only")
    else:
        client = github.GitHubClient(token, event.repo, env.get("GITHUB_API_URL") or github.API_URL)
        try:
            diff_text = client.pr_diff(event.number)
        except Exception as e:  # a missing diff only weakens the analysis
            github.annotate("warning", f"could not read the PR diff ({type(e).__name__})")

    if event is not None and event.is_fork:
        args.no_llm = True  # don't spend CI minutes on a PR we can't comment on
    report = analyse(args, diff_text)
    markdown = to_markdown(report)
    print(markdown)
    github.write_step_summary(markdown, env)
    for v in report.verdicts:
        if v.decided_by == "fallback" and v.note:
            github.annotate("warning", f"{v.test_name}: {v.note}")
            break

    if client is None or event is None:
        return 0
    if not report.total_failures:
        github.annotate("notice", "no failing tests found; nothing to comment")
        return 0
    marker = github.comment_marker(env)
    action = client.upsert_comment(event.number, f"{marker}\n{markdown}", marker=marker)
    print(f"flakehunter: {action} the PR comment", file=sys.stderr)
    wants_label = str(args.label).lower() in {"true", "1", "yes"}
    if wants_label and any(v.category == "flaky_test" for v in report.verdicts):
        client.add_label(event.number)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "analyze":
            return cmd_analyze(args)
        if args.command == "github":
            return cmd_github(args, dict(os.environ))
        return 0  # pragma: no cover - argparse rejects unknown commands
    except Exception as e:
        if args.strict:
            raise
        warn(f"{type(e).__name__}: {e}")
        if args.command == "github":
            github.annotate("warning", f"{type(e).__name__}: {e}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
