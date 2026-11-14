import base64
import hmac
import json
import time
import urllib.request

import pytest

SECRET = b"unit-test-secret"


def sign(payload: dict[str, object]) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    mac = hmac.new(SECRET, body.encode(), "sha256").hexdigest()
    return f"{body}.{mac}"


def verify(token: str) -> dict[str, object]:
    body, mac = token.rsplit(".", 1)
    expected = hmac.new(SECRET, body.encode(), "sha256").hexdigest()
    if mac != expected:
        raise PermissionError("bad signature")
    payload: dict[str, object] = json.loads(base64.urlsafe_b64decode(body))
    return payload


def is_expired(payload: dict[str, object], now: float) -> bool:
    return float(payload["exp"]) < now  # type: ignore[arg-type]


def has_role(user: dict[str, list[str]], role: str) -> bool:
    return role in user.get("roles", [])


def password_ok(pw: str) -> bool:
    return len(pw) >= 8 and any(c.isdigit() for c in pw)


def test_roundtrip() -> None:
    assert verify(sign({"sub": "ada"}))["sub"] == "ada"


def test_tampered_token_rejected() -> None:
    token = sign({"sub": "ada"})
    with pytest.raises(PermissionError):
        verify(token[:-1] + ("0" if token[-1] != "0" else "1"))


def test_token_expires() -> None:
    assert is_expired({"exp": 100}, now=100)


def test_admin_role() -> None:
    assert has_role({"roles": ["admin"]}, "Admin")


def test_password_needs_symbol() -> None:
    assert not password_ok("abcdefg1")


def test_password_length() -> None:
    assert password_ok("abc1")


def test_session_token_not_expired() -> None:
    payload = {"exp": time.time() + 0.05}
    time.sleep(0.03)
    assert not is_expired(payload, now=time.time())


def test_sso_metadata(closed_port: int) -> None:
    urllib.request.urlopen(f"http://127.0.0.1:{closed_port}/saml/metadata", timeout=3)


def test_login_fixture_user(login_user: dict[str, str]) -> None:
    assert login_user["name"] == "ada"


def test_mfa_code_window() -> None:
    step = int(time.time()) // 30
    code_a = step % 1_000_000
    time.sleep(0.01)
    code_b = (int(time.time()) // 30) % 1_000_000
    assert code_a == code_b
