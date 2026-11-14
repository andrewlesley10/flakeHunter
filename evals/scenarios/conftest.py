"""Local stand-ins for infrastructure, so environment failures are real but offline.

- ``closed_port``: nothing listens there (connection refused).
- ``silent_server``: accepts connections but never answers (read timeouts).
- ``unhealthy_server``: an HTTP server that answers 503 / 429 / 502.
"""

import http.server
import socket
import threading
from collections.abc import Iterator

import pytest


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def closed_port() -> int:
    return _free_port()


@pytest.fixture
def silent_server() -> Iterator[int]:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(8)
    yield int(sock.getsockname()[1])
    sock.close()


class _Handler(http.server.BaseHTTPRequestHandler):
    status = 503

    def do_GET(self) -> None:
        self.send_response(self.status)
        self.end_headers()
        self.wfile.write(b"upstream unavailable")

    do_POST = do_GET

    def log_message(self, *args: object) -> None:
        pass


def _serve(status: int) -> Iterator[str]:
    handler = type("H", (_Handler,), {"status": status})
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture
def unhealthy_server() -> Iterator[str]:
    yield from _serve(503)


@pytest.fixture
def throttling_server() -> Iterator[str]:
    yield from _serve(429)


@pytest.fixture
def bad_gateway_server() -> Iterator[str]:
    yield from _serve(502)


@pytest.fixture
def api_client() -> dict[str, str]:
    return {"base_url": "http://localhost", "token": "test"}
