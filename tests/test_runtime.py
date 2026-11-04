"""Behaviour the language-neutral scenarios cannot cover: the real httpx transports against a
local HTTP server, asyncio cancellation and redaction of the client objects."""

from __future__ import annotations

import asyncio
import json
import re
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from sursolver import AsyncSurSolver, SurSolver, TransportError

KEY = "sur_00000000000000000000000000000000"
TASK_ID = "tsk_4f7a9c1e2b8d3a6f5c0e9d21"
TASK = {
    "type": "TurnstileTokenProxyLess",
    "websiteURL": "https://example.com/",
    "websiteKey": "k",
    "userAgent": "ua",
}

Handler = Callable[[BaseHTTPRequestHandler, bytes], None]


@pytest.fixture
def serve() -> Iterator[Callable[[Handler], str]]:
    servers: list[ThreadingHTTPServer] = []

    def start(handle: Handler) -> str:
        class RequestHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("content-length", "0"))
                handle(self, self.rfile.read(length))

            def log_message(self, format: str, *args: Any) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), RequestHandler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}"

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def reply(handler: BaseHTTPRequestHandler, body: dict[str, Any], status: int = 200) -> None:
    data = json.dumps(body).encode()
    handler.send_response(status)
    handler.send_header("content-type", "application/json")
    handler.send_header("content-length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def test_sends_the_key_only_in_the_body(serve: Callable[[Handler], str]) -> None:
    seen: dict[str, Any] = {}

    def handle(handler: BaseHTTPRequestHandler, body: bytes) -> None:
        headers = {name.lower(): value for name, value in handler.headers.items()}
        seen.update(path=handler.path, headers=headers, body=json.loads(body))
        reply(handler, {"errorId": 0, "taskId": TASK_ID, "status": "idle"})

    with SurSolver(KEY, base_url=serve(handle)) as client:
        assert client.create_task(TASK) == TASK_ID
    assert seen["path"] == "/createTask"
    assert seen["headers"]["user-agent"].startswith("sursolver-python/")
    assert KEY not in json.dumps(seen["headers"])
    assert seen["body"] == {"clientKey": KEY, "task": TASK}


def test_request_timeout_is_a_transport_error(serve: Callable[[Handler], str]) -> None:
    release = threading.Event()

    def handle(handler: BaseHTTPRequestHandler, body: bytes) -> None:
        release.wait(5)  # never answers within the client's timeout

    # A real 0.2 s wait: the behaviour under test is httpx's own read timeout, which a fake
    # clock cannot drive.
    try:
        with (
            SurSolver(KEY, base_url=serve(handle), request_timeout=0.2) as client,
            pytest.raises(TransportError, match=re.escape("timed out after 0.2 s")) as caught,
        ):
            client.get_balance()
        assert caught.value.may_have_created_task is False
    finally:
        release.set()


def test_redirects_are_not_followed(serve: Callable[[Handler], str]) -> None:
    hits: list[str] = []

    def handle(handler: BaseHTTPRequestHandler, body: bytes) -> None:
        hits.append(handler.path)
        handler.send_response(307)
        handler.send_header("location", "/elsewhere")
        handler.send_header("content-length", "0")
        handler.end_headers()

    with SurSolver(KEY, base_url=serve(handle)) as client, pytest.raises(TransportError) as caught:
        client.create_task(TASK)
    assert caught.value.status == 307
    assert caught.value.may_have_created_task is True
    assert hits == ["/createTask"]


def test_async_cancellation_keeps_the_task_id(serve: Callable[[Handler], str]) -> None:
    polled = threading.Event()

    def handle(handler: BaseHTTPRequestHandler, body: bytes) -> None:
        if handler.path == "/createTask":
            reply(handler, {"errorId": 0, "taskId": TASK_ID, "status": "idle"})
        else:
            reply(handler, {"errorId": 0, "status": "processing"})
            polled.set()

    base_url = serve(handle)

    async def main() -> list[str]:
        created: list[str] = []
        async with AsyncSurSolver(KEY, base_url=base_url, poll_interval=10) as client:
            task = asyncio.create_task(client.solve(TASK, on_task_created=created.append))
            await asyncio.get_running_loop().run_in_executor(None, polled.wait, 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        return created

    assert asyncio.run(main()) == [TASK_ID]


def test_repr_never_shows_the_key() -> None:
    with SurSolver(KEY) as client:
        assert KEY not in repr(client)
        assert KEY not in str(vars(client).keys())
    assert KEY not in repr(AsyncSurSolver(KEY))
