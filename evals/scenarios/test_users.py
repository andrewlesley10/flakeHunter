import hashlib
import json
import os
import random
import re
import sqlite3
import threading
import time
import urllib.request

import pytest

EMAIL = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.]+$")


def normalise_email(email: str) -> str:
    return email.strip()


def is_valid_email(email: str) -> bool:
    return bool(EMAIL.match(email))


def display_name(first: str, last: str) -> str:
    return f"{first} {last}".title()


def password_hash(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode()).hexdigest()


def age_band(age: int) -> str:
    if age < 18:
        return "minor"
    if age < 65:
        return "adult"
    return "senior"


def load_profile(raw: str) -> dict[str, object]:
    return json.loads(raw)


class Counter:
    def __init__(self) -> None:
        self.value = 0

    def increment(self) -> None:
        current = self.value
        if random.random() < 0.02:
            time.sleep(0.001)
        self.value = current + 1


def test_email_is_lowercased() -> None:
    assert normalise_email("  Ada@Example.COM ") == "ada@example.com"


def test_plus_addresses_are_valid() -> None:
    assert is_valid_email("ada+shop@example.com")


def test_display_name() -> None:
    assert display_name("ada", "lovelace") == "Ada Lovelace"


def test_display_name_with_apostrophe() -> None:
    assert display_name("sean", "o'neil") == "Sean O'Neil"


def test_age_band_boundary() -> None:
    assert age_band(65) == "adult"


def test_password_hash_is_salted() -> None:
    assert password_hash("pw", "a") != password_hash("pw", "b")
    assert len(password_hash("pw", "a")) == 32


def test_profile_has_email() -> None:
    profile = load_profile('{"name": "Ada", "email": "ada@example.com"}')
    assert profile["e-mail"] == "ada@example.com"


def test_user_count_matches(api_client: dict[str, str]) -> None:
    users = [{"id": 1}, {"id": 2}, {"id": 3}]
    assert len(users) == api_client["expected_users"]


def test_concurrent_signups_are_counted() -> None:
    counter = Counter()
    threads = [threading.Thread(target=counter.increment) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert counter.value == 50


def test_user_store_opens() -> None:
    conn = sqlite3.connect("/nonexistent-volume/data/users.db")
    conn.execute("select 1")


def test_identity_provider_reachable(closed_port: int) -> None:
    urllib.request.urlopen(
        f"http://127.0.0.1:{closed_port}/.well-known/openid-configuration", timeout=3
    )


def test_admin_credentials_configured() -> None:
    os.environ.pop("ADMIN_API_TOKEN", None)
    token = os.environ["ADMIN_API_TOKEN"]
    assert token


def test_avatar_service(unhealthy_server: str) -> None:
    urllib.request.urlopen(f"{unhealthy_server}/avatars/1", timeout=3)


@pytest.fixture
def seeded_user() -> dict[str, str]:
    raise RuntimeError("could not seed user: table 'users' has no column named 'nickname'")


def test_user_can_rename(seeded_user: dict[str, str]) -> None:
    assert seeded_user["name"]
