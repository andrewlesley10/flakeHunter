"""Adversarial tests for redaction and trimming.

Fake secrets are assembled from parts so no realistic token is ever written in the
repo (GitHub push protection would block it, and it is a good habit anyway).
"""

import pytest

from flakehunter.models import TestFailure
from flakehunter.redact import (
    MAX_LINE_CHARS,
    head_tail,
    prepare_for_llm,
    redact,
    redact_with_stats,
    trim_around,
)

GH = "ghp_" + "A1b2C3d4" * 5  # 40 chars after the prefix
GH_PAT = "github_pat_" + "11ABCDEFG0" * 3
AWS = "AKIA" + "IOSFODNN7EXAMPLE"
SLACK = "xoxb-" + "123456789012-abcdefABCDEF"
JWT = (
    "eyJhbGciOiJIUzI1NiJ9"
    + ".eyJzdWIiOiIxMjM0NTY3ODkwIn0"
    + ".dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
)
STRIPE = "sk_" + "live_" + "4eC39HqLyjWDarjtT1zdp7dc"
OPENAI = "sk-" + "proj-" + "abcdefghijklmnopqrstuvwx1234"
GOOGLE = "AIza" + "SyA-1234567890abcdefghijklmnopqrstu"
NPM = "npm_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
PEM = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "MIIEowIBAAKCAQEA1234567890abcdef\n"
    "Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MA==\n"
    "-----END RSA PRIVATE KEY-----"
)


# --- each secret shape is masked ------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "secret", "label"),
    [
        (f'{{"token":"{GH}"}}', GH, "github_token"),  # inside JSON
        (f"export GITHUB_TOKEN={GH}", GH, "github_token"),
        (f"push failed for {GH}", GH, "github_token"),  # end of line, no trailing space
        (f"'{GH_PAT}'", GH_PAT, "github_token"),  # wrapped in quotes
        (f"AWS_ACCESS_KEY_ID={AWS}", AWS, "aws_access_key"),
        (f"slack webhook token {SLACK}", SLACK, "slack_token"),
        (f"stripe.api_key = '{STRIPE}'", STRIPE, "stripe_key"),
        (f"OPENAI_API_KEY={OPENAI}", OPENAI, "openai_key"),
        (f"maps?key={GOOGLE}", GOOGLE, "google_api_key"),
        (f"//registry.npmjs.org/:_authToken={NPM}", NPM, "npm_token"),
        (f"cookie session={JWT}", JWT, "jwt"),
    ],
)
def test_vendor_tokens_are_masked(text: str, secret: str, label: str) -> None:
    out, counts = redact_with_stats(text)
    assert secret not in out
    assert f"[REDACTED:{label}]" in out
    assert counts[label] == 1


def test_bearer_header_with_jwt_masked_once() -> None:
    out, counts = redact_with_stats(f"Authorization: Bearer {JWT}")
    assert out == "Authorization: Bearer [REDACTED:jwt]"  # not double-mangled
    assert sum(counts.values()) == 1


@pytest.mark.parametrize(
    "header",
    [
        "Authorization: Bearer abc123def456ghi789",
        "authorization: token abc123def456ghi789",
        "Authorization: Basic dXNlcjpodW50ZXIy",
        "curl -H 'Authorization: Bearer abc123def456ghi789' https://api",
        "Proxy-Authorization: Basic dXNlcjpodW50ZXIy",
    ],
)
def test_auth_headers_masked(header: str) -> None:
    out = redact(header)
    assert "abc123def456ghi789" not in out
    assert "dXNlcjpodW50ZXIy" not in out
    assert "[REDACTED:auth]" in out


@pytest.mark.parametrize(
    ("url", "password", "expected"),
    [
        (
            "postgres://admin:S3cr3t!@db:5432/app",
            "S3cr3t!",
            "postgres://admin:[REDACTED]@db:5432/app",
        ),
        ("https://user:p%40ss@host/x", "p%40ss", "https://user:[REDACTED]@host/x"),
        # empty username (common for Redis): this case leaked before the fix
        ("redis://:hunter22@cache:6379", "hunter22", "redis://:[REDACTED]@cache:6379"),
        ("mongodb+srv://bot:longpassword@cluster0/db", "longpassword", None),
    ],
)
def test_url_credentials_masked(url: str, password: str, expected: str | None) -> None:
    out = redact(f"connecting to {url}")
    assert password not in out
    if expected:
        assert out == f"connecting to {expected}"


@pytest.mark.parametrize(
    "text",
    [
        "PASSWORD=hunter2",
        'password: "hunter2"',
        "DB_PASSWORD: hunter2",
        "--password hunter2",
        "--password=hunter2",
        "client_secret='hunter2'",
        "aws_secret_access_key = hunter2hunter2",
        '{"apiKey": "hunter2", "user": "bob"}',
    ],
)
def test_key_value_and_flags_masked(text: str) -> None:
    out = redact(text)
    assert "hunter2" not in out
    assert "[REDACTED]" in out


def test_key_value_keeps_neighbouring_fields() -> None:
    assert (
        redact('{"apiKey": "hunter2", "user": "bob"}') == '{"apiKey": "[REDACTED]", "user": "bob"}'
    )


def test_aws_key_in_multiline_env_dump() -> None:
    dump = f"HOME=/home/runner\nAWS_ACCESS_KEY_ID={AWS}\nCI=true\n"
    out = redact(dump)
    assert AWS not in out
    assert "HOME=/home/runner" in out and "CI=true" in out


def test_pem_block_across_lines() -> None:
    out = redact(f"key loaded:\n{PEM}\ndone")
    assert "MIIEowIBAAKCAQEA" not in out
    assert out == "key loaded:\n[REDACTED:private_key]\ndone"


def test_pem_block_cut_by_trimming_is_still_masked() -> None:
    truncated = PEM.split("-----END")[0]  # END line lost to trimming
    out = redact(f"before\n{truncated}")
    assert "MIIEowIBAAKCAQEA" not in out
    assert "Zm9vYmFy" not in out


# --- things that must NOT be redacted -------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "HEAD is now at a3f9c1d2e4b5a6978f0e1d2c3b4a59687f0e1d2c",  # git SHA (40 hex)
        "request id 123e4567-e89b-12d3-a456-426614174000",  # UUID
        "the token expired, please log in again",  # 'token' in prose
        "Authorization required",  # header word, no value
        "GET https://example.com/api/v1/items?page=2",  # URL without credentials
        "AssertionError: assert 401 == 200",
        "sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    ],
)
def test_not_over_redacted(text: str) -> None:
    assert redact(text) == text


def test_documented_over_redaction() -> None:
    """Trade-off: any key=value whose key looks secret is masked, even harmless values.

    Leaking a real password costs far more than hiding a working directory.
    """
    assert redact("pwd=/home/runner/work") == "pwd=[REDACTED]"
    assert redact("pwd=abc") == "pwd=abc"  # values under 4 chars are kept


@pytest.mark.parametrize(
    "text",
    [
        f'{{"token":"{GH}"}}',
        f"Authorization: Bearer {JWT}",
        "postgres://admin:S3cr3t!@db/app",
        "PASSWORD=hunter2",
        PEM,
    ],
)
def test_redact_is_idempotent(text: str) -> None:
    once = redact(text)
    assert redact(once) == once


# --- trimming ----------------------------------------------------------------------------

LOG = [f"line {i}" for i in range(100)]


def test_window_keeps_lines_around_match() -> None:
    lines = [*LOG[:50], "FAILED test_login", *LOG[50:]]
    out = trim_around(lines, ["test_login"], before=2, after=2)
    assert out == [
        "[... 48 lines omitted ...]",
        "line 48",
        "line 49",
        "FAILED test_login",
        "line 50",
        "line 51",
        "[... 48 lines omitted ...]",
    ]


def test_match_is_case_insensitive() -> None:
    out = trim_around(["a", "Connection REFUSED", "b"], ["connection refused"], before=0, after=0)
    assert "Connection REFUSED" in out


def test_overlapping_windows_merged() -> None:
    lines = [*LOG[:10], "ERR one", "x", "x", "ERR two", *LOG[10:20]]
    out = trim_around(lines, ["ERR"], before=1, after=1)
    assert out.count("ERR one") == 1
    assert sum(1 for line in out if line.startswith("[...")) == 2  # one gap before, one after
    assert out[1:6] == ["line 9", "ERR one", "x", "x", "ERR two"]


def test_no_match_falls_back_to_tail() -> None:
    out = trim_around(LOG, ["nothing"], before=2, after=2)
    assert out == ["[... 95 lines omitted ...]", *LOG[-5:]]


def test_max_lines_cap_keeps_windows_nearest_the_end() -> None:
    lines = [f"ERR {i}" if i % 10 == 0 else f"ok {i}" for i in range(200)]
    out = trim_around(lines, ["ERR"], before=1, after=1, max_lines=9)
    content = [line for line in out if not line.startswith("[...")]
    assert len(content) == 9
    assert content[-1] == "ok 191"  # the last window survives


def test_empty_needles_and_lines() -> None:
    assert trim_around([], ["x"]) == []
    assert trim_around(["a", "b"], ["", "  "]) == ["a", "b"]  # blank needles ignored -> tail


def test_head_tail() -> None:
    assert head_tail(LOG, head=2, tail=2) == [
        "line 0",
        "line 1",
        "[... 96 lines omitted ...]",
        "line 98",
        "line 99",
    ]
    assert head_tail(["a"], head=2, tail=2) == ["a"]


# --- the single gate -----------------------------------------------------------------------


def make_failure(**overrides: object) -> TestFailure:
    data: dict[str, object] = {
        "id": "tests.test_api::test_login",
        "suite": "s",
        "name": "test_login",
        "kind": "failure",
        "message": "AssertionError: assert 401 == 200",
        "details": "def test_login():\n>   assert resp.status == 200\nE   AssertionError",
    }
    data.update(overrides)
    return TestFailure.model_validate(data)


def test_prepare_for_llm_never_contains_secret() -> None:
    far_away = [f"export GITHUB_TOKEN={GH}", *LOG]  # outside the trim window
    near = [*LOG[:50], f"curl -H 'Authorization: Bearer {JWT}'", "FAILED test_login", *LOG[50:]]
    failure = make_failure(stdout=f"connecting to postgres://app:{'pw' * 6}@db/app")
    ctx = prepare_for_llm(failure, {"build.log": far_away, "test.log": near}, before=3, after=3)
    for secret in (GH, JWT, "pw" * 6):
        assert secret not in ctx.text
    assert ctx.total_masked >= 2  # JWT in the window + URL password in stdout


def test_prepare_for_llm_structure() -> None:
    ctx = prepare_for_llm(make_failure(), {"ci.log": [*LOG, "FAILED test_login"]})
    assert ctx.text.startswith("### message\nAssertionError: assert 401 == 200")
    assert "### stack trace" in ctx.text
    assert "### log: ci.log" in ctx.text
    assert "FAILED test_login" in ctx.text
    assert "line 0" not in ctx.text  # trimmed away
    assert ctx.total_masked == 0


def test_long_lines_truncated_after_redaction() -> None:
    # A token sitting right at the truncation point must still be masked.
    line = "x" * (MAX_LINE_CHARS - 10) + " " + GH + " " + "y" * 300
    ctx = prepare_for_llm(make_failure(details=line))
    assert GH not in ctx.text
    assert GH[:20] not in ctx.text  # no partial token leaks either
    assert all(len(line) < MAX_LINE_CHARS + 50 for line in ctx.text.splitlines())


def test_prepare_for_llm_without_logs() -> None:
    ctx = prepare_for_llm(make_failure())
    assert "### log:" not in ctx.text


# --- regressions from the security review --------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgres://app:p@ssw0rd@db:5432/x", "postgres://app:[REDACTED]@db:5432/x"),
        ("https://u:a@b@c@host/path?next=x@y", "https://u:[REDACTED]@host/path?next=x@y"),
    ],
)
def test_url_password_containing_at_sign(url: str, expected: str) -> None:
    assert redact(url) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('password: "correct horse, battery"', 'password: "[REDACTED]"'),
        ("secret='a b;c&d'", "secret='[REDACTED]'"),
        ('{"apiKey": "has space", "user": "bob"}', '{"apiKey": "[REDACTED]", "user": "bob"}'),
    ],
)
def test_quoted_value_masked_to_closing_quote(text: str, expected: str) -> None:
    assert redact(text) == expected


@pytest.mark.parametrize("before", [0, 1, 5, 15])
def test_trim_window_starting_inside_private_key_does_not_leak(before: int) -> None:
    body = [f"MIIEowIBAAKCAQEA{i:04d}abcdefabcdefabcdef" for i in range(30)]
    log = ["-----BEGIN RSA PRIVATE KEY-----", *body, "-----END RSA PRIVATE KEY-----"]
    log.append("FAILED test_login")
    ctx = prepare_for_llm(make_failure(), {"ci.log": log}, before=before, after=1)
    assert "MIIEowIBAAKCAQEA" not in ctx.text
    assert ctx.secrets_masked["private_key"] == 1


def test_head_tail_inside_private_key_does_not_leak() -> None:
    body = [f"QUJDREVGR0hJSktMTU5PUFFSU1RVVldY{i:04d}" for i in range(100)]
    details = "\n".join(["-----BEGIN PRIVATE KEY-----", *body, "-----END PRIVATE KEY-----"])
    ctx = prepare_for_llm(make_failure(details=details))
    assert "QUJDREVGR0hJSktMTU5PUFFSU1RVVldY" not in ctx.text


@pytest.mark.parametrize(
    "url",
    [
        "postgres://app:pa#ss@db/x",
        "postgres://app:pa?ss@db/x",
        "postgres://app:a@b#c?d@db/x",
    ],
)
def test_url_password_with_hash_or_question_mark(url: str) -> None:
    assert redact(url) == "postgres://app:[REDACTED]@db/x"


def test_url_without_path_over_masks_rather_than_leaks() -> None:
    out = redact("redis://:pa?ss@cache?timeout=5")
    assert "pa?ss" not in out


def test_log_file_name_is_redacted() -> None:
    ctx = prepare_for_llm(make_failure(), {f"logs/run-{GH}.log": ["FAILED test_login"]})
    assert GH not in ctx.text
    assert "### log: logs/run-[REDACTED:github_token].log" in ctx.text
    assert ctx.secrets_masked["github_token"] == 1


def test_secret_counts_not_doubled_by_final_pass() -> None:
    ctx = prepare_for_llm(make_failure(message=f"push failed for {GH}"))
    assert ctx.secrets_masked["github_token"] == 1
