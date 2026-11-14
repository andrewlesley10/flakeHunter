import asyncio
import os
import random
import smtplib
import string
import time
import urllib.request
from collections import deque
from pathlib import Path


def render_template(template: str, **values: str) -> str:
    return string.Template(template).safe_substitute(values)


def truncate_sms(text: str, limit: int = 160) -> str:
    return text[: limit - 1] + "…" if len(text) > limit else text


def quiet_hours(hour: int) -> bool:
    return hour >= 22 and hour < 7


def batch(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


class Outbox:
    def __init__(self) -> None:
        self.queue: deque[str] = deque()

    def push(self, msg: str) -> None:
        self.queue.append(msg)

    def pop(self) -> str:
        return self.queue.pop()


async def deliver(msg: str, delay: float) -> str:
    await asyncio.sleep(delay)
    return msg


def test_template_missing_value_is_left() -> None:
    assert render_template("Hi $name, $item shipped", name="Ada") == "Hi Ada, $item shipped"


def test_sms_truncated_to_limit() -> None:
    assert len(truncate_sms("x" * 300)) == 160


def test_quiet_hours_at_night() -> None:
    assert quiet_hours(23)


def test_batches_of_two() -> None:
    assert batch(["a", "b", "c"], 2) == [["a", "b"], ["c"]]


def test_outbox_is_fifo() -> None:
    box = Outbox()
    box.push("first")
    box.push("second")
    assert box.pop() == "first"


def test_messages_arrive_in_order() -> None:
    async def run() -> list[str]:
        tasks = [deliver(m, random.uniform(0, 0.02)) for m in ("a", "b", "c")]
        done = []
        for coro in asyncio.as_completed(tasks):
            done.append(await coro)
        return done

    assert asyncio.run(run()) == ["a", "b", "c"]


def test_smtp_relay(closed_port: int) -> None:
    smtplib.SMTP("127.0.0.1", closed_port, timeout=3)


def test_push_provider(unhealthy_server: str) -> None:
    urllib.request.urlopen(f"{unhealthy_server}/v1/push", timeout=3)


def test_webhook_receiver_timeout(silent_server: int) -> None:
    urllib.request.urlopen(f"http://127.0.0.1:{silent_server}/hook", timeout=1)


def test_template_cache_writable() -> None:
    Path("/var/cache/notifications/welcome.html").write_text("hi")


def test_sendgrid_key_present() -> None:
    assert os.environ.get("SENDGRID_API_KEY"), "SENDGRID_API_KEY is not set in this environment"


def test_digest_sent_before_deadline() -> None:
    deadline = time.monotonic() + 0.1
    time.sleep(random.choice([0.01, 0.01, 0.2]))
    assert time.monotonic() <= deadline
