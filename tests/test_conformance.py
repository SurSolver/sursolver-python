"""Runs the vendored language-neutral conformance scenarios (conformance/README.md) against
both clients with a scripted fake transport, a virtual clock and a fixed random source.
Cancellation scenarios run on the asyncio client only: the synchronous client has no
cancellation mechanism of its own."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import re
from pathlib import Path
from typing import Any

import pytest

import sursolver
from sursolver import AsyncSurSolver, HttpRequest, HttpResponse, SurSolver

ROOT = Path(__file__).resolve().parent.parent
SCENARIO_DIR = ROOT / "conformance" / "scenarios"
RECORDED_DIR = ROOT / "conformance" / "recorded"
TEST_API_KEY = "sur_00000000000000000000000000000000"

FIELD_NAMES = {
    "operation": "operation",
    "code": "code",
    "retryable": "retryable",
    "taskId": "task_id",
    "status": "status",
    "serverCode": "server_code",
    "retryAfterSeconds": "retry_after_seconds",
    "mayHaveCreatedTask": "may_have_created_task",
}


def to_wire(value: Any) -> Any:
    """Results as plain JSON-like data; dataclass fields already use the wire spelling. A
    processing TaskResult has no solution on the wire, so its None solution is dropped."""
    if isinstance(value, sursolver.TaskResult) and value.solution is None:
        return {"status": value.status}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {field.name: to_wire(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, (list, tuple)):
        return [to_wire(entry) for entry in value]
    if isinstance(value, dict):
        return {key: to_wire(entry) for key, entry in value.items()}
    return value


def normalize(value: Any, inside_solution: bool = False) -> Any:
    """README rule: keys compare lowercased without underscores, except inside a solution."""
    if isinstance(value, list):
        return [normalize(entry, inside_solution) for entry in value]
    if isinstance(value, dict):
        if inside_solution:
            return value
        return {
            key.lower().replace("_", ""): normalize(entry, key == "solution") for key, entry in value.items()
        }
    return value


def pointer_get(root: Any, pointer: str) -> Any:
    current = root
    for raw in pointer.split("/")[1:]:
        segment = raw.replace("~1", "/").replace("~0", "~")
        current = current[int(segment)] if isinstance(current, list) else current[segment]
    return current


def transport_failure(kind: str) -> Exception:
    if kind == "request_timeout":
        return TimeoutError("timed out")
    if kind == "connection_reset":
        return ConnectionResetError("connection reset by peer")
    return ConnectionError("server closed the connection without a response")


def scripted_response(respond: dict[str, Any]) -> HttpResponse:
    if "respondFrom" in respond:
        fixture = json.loads((RECORDED_DIR / respond["respondFrom"]).read_text("utf-8"))
        recorded = fixture["response"]
        text = json.dumps(recorded["body"]) if recorded["body_is_json"] else str(recorded.get("body") or "")
        return HttpResponse(
            status=respond.get("status", recorded["status"]),
            body=text.encode("utf-8"),
            headers=recorded["headers"],
        )
    text = json.dumps(respond["json"]) if "json" in respond else respond.get("text", "")
    return HttpResponse(
        status=respond.get("status", 200), body=text.encode("utf-8"), headers=respond.get("headers", {})
    )


def header_matches(expected: Any, actual: str | None) -> bool:
    if actual is None:
        return False
    if isinstance(expected, dict):
        return re.search(expected["matches"], actual) is not None
    return bool(expected == actual)


class Harness:
    def __init__(self, scenario: dict[str, Any]) -> None:
        self.scenario = scenario
        self.requests: list[HttpRequest] = []
        self.failures: list[str] = []
        self.step = 0
        self.sleeps: list[int] = []
        self.now_ms = 0
        self.created: list[str] = []

    def respond(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        script = self.scenario["script"]
        entry = script[self.step] if self.step < len(script) else None
        self.step += 1
        url_path = re.sub(r"^https?://[^/]+", "", request.url)
        path, _, query = url_path.partition("?")
        problem = None
        if entry is None:
            problem = f"unexpected request {request.method} {path}"
        else:
            expected = entry["expect"]
            if expected["method"] != request.method or expected["path"] != path:
                wanted = f"{expected['method']} {expected['path']}"
                problem = f"request {self.step}: expected {wanted}, got {request.method} {path}"
            elif expected.get("noQuery") and query:
                problem = f"request {self.step}: unexpected query string"
            elif "json" in expected and json.loads(request.body or b"null") != expected["json"]:
                problem = f"request {self.step}: body {request.body!r} != {expected['json']!r}"
            else:
                for name, value in expected.get("headers", {}).items():
                    if not header_matches(value, request.headers.get(name.lower())):
                        problem = f"request {self.step}: header {name} mismatch: {dict(request.headers)}"
        if problem is not None or entry is None:
            self.failures.append(problem or "unexpected request")
            raise RuntimeError(f"harness: {problem}")
        if "fail" in entry:
            raise transport_failure(entry["fail"])
        return scripted_response(entry.get("respond", {"status": 200}))

    def record_sleep(self, seconds: float) -> None:
        ms = round(seconds * 1000)
        self.sleeps.append(ms)
        self.now_ms += ms

    def options(self) -> tuple[str, dict[str, Any]]:
        client = self.scenario.get("client", {})
        options: dict[str, Any] = {"random": lambda: self.scenario.get("random", 0)}
        mapping = {
            "baseUrl": ("base_url", None),
            "requestTimeoutMs": ("request_timeout", 1000),
            "pollIntervalMs": ("poll_interval", 1000),
            "solveTimeoutMs": ("solve_timeout", 1000),
            "maxSubmitRetries": ("max_submit_retries", None),
            "appId": ("app_id", None),
            "userAgentSuffix": ("user_agent_suffix", None),
        }
        for name, (option, divisor) in mapping.items():
            if name in client:
                options[option] = client[name] / divisor if divisor else client[name]
        return client.get("apiKey", TEST_API_KEY), options


def solve_kwargs(harness: Harness, args: dict[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"on_task_created": harness.created.append}
    if "pollIntervalMs" in args:
        kwargs["poll_interval"] = args["pollIntervalMs"] / 1000
    if "solveTimeoutMs" in args:
        kwargs["solve_timeout"] = args["solveTimeoutMs"] / 1000
    return kwargs


def run_sync(harness: Harness) -> tuple[Any, BaseException | None]:
    scenario = harness.scenario

    class Clock:
        def now(self) -> float:
            return harness.now_ms / 1000

        def sleep(self, seconds: float) -> None:
            harness.record_sleep(seconds)

    api_key, options = harness.options()
    call, args = scenario["call"]["method"], scenario["call"].get("args", {})
    try:
        client = SurSolver(api_key, transport=harness.respond, clock=Clock(), **options)
        if call == "construct":
            return None, None
        if call == "createTask":
            return client.create_task(args["task"]), None
        if call == "getTaskResult":
            return client.get_task_result(args["taskId"]), None
        if call == "getBalance":
            return client.get_balance(), None
        if call == "listTaskTypes":
            return client.list_task_types(), None
        if call == "listServices":
            return client.list_services(), None
        return client.solve(args["task"], **solve_kwargs(harness, args)), None
    except Exception as error:
        return None, error


def run_async(harness: Harness) -> tuple[Any, BaseException | None]:
    scenario = harness.scenario
    cancel_after = scenario["call"].get("cancelAfterSleeps")

    class Clock:
        def now(self) -> float:
            return harness.now_ms / 1000

        async def sleep(self, seconds: float) -> None:
            harness.record_sleep(seconds)
            if cancel_after == len(harness.sleeps):
                task = asyncio.current_task()
                assert task is not None
                task.cancel()
            await asyncio.sleep(0)

    async def transport(request: HttpRequest) -> HttpResponse:
        return harness.respond(request)

    async def main() -> tuple[Any, BaseException | None]:
        api_key, options = harness.options()
        call, args = scenario["call"]["method"], scenario["call"].get("args", {})
        try:
            client = AsyncSurSolver(api_key, transport=transport, clock=Clock(), **options)
            if call == "construct":
                return None, None
            if call == "createTask":
                return await client.create_task(args["task"]), None
            if call == "getTaskResult":
                return await client.get_task_result(args["taskId"]), None
            if call == "getBalance":
                return await client.get_balance(), None
            if call == "listTaskTypes":
                return await client.list_task_types(), None
            if call == "listServices":
                return await client.list_services(), None
            return await client.solve(args["task"], **solve_kwargs(harness, args)), None
        except asyncio.CancelledError as error:
            task = asyncio.current_task()
            assert task is not None
            task.uncancel()
            return None, error
        except Exception as error:
            return None, error

    return asyncio.run(main())


def check(harness: Harness, result: Any, error: BaseException | None) -> None:
    scenario = harness.scenario
    assert harness.failures == []
    assert harness.step == len(scenario["script"]), "every scripted request is consumed"
    expectations = scenario.get("expect", {})
    if "sleeps" in expectations:
        assert harness.sleeps == expectations["sleeps"]
    if "lastTaskId" in expectations:
        assert harness.created and harness.created[-1] == expectations["lastTaskId"]

    expected_error = expectations.get("outcome", {}).get("error")
    if expected_error is None:
        if error is not None:
            raise error
        if "ok" in expectations.get("outcome", {}):
            assert normalize(to_wire(result)) == normalize(expectations["outcome"]["ok"])
        for subset in expectations.get("outcomeSubset", []):
            value = pointer_get(to_wire(result), subset["pointer"])
            if "length" in subset:
                assert len(value) == subset["length"]
            if "equals" in subset:
                assert normalize(value) == normalize(subset["equals"])
    else:
        assert error is not None, f"the call should have failed, got {result!r}"
        if expected_error["type"] == "Cancelled":
            assert isinstance(error, asyncio.CancelledError)
        else:
            assert type(error) is getattr(sursolver, expected_error["type"]), repr(error)
            for name, attribute in FIELD_NAMES.items():
                if name in expected_error:
                    assert getattr(error, attribute) == expected_error[name], name
            if "supportedUserAgents" in expected_error:
                assert list(error.supported_user_agents) == expected_error["supportedUserAgents"]  # type: ignore[attr-defined]
            if "lastErrorType" in expected_error:
                last = error.last_error  # type: ignore[attr-defined]
                assert (None if last is None else type(last).__name__) == expected_error["lastErrorType"]
            rendered = f"{error}\n{error!r}"
            for text in expected_error.get("messageIncludes", []):
                assert text in rendered
            for text in expected_error.get("messageExcludes", []):
                assert text not in rendered

    if expectations.get("redaction"):
        api_key = scenario.get("client", {}).get("apiKey", TEST_API_KEY)
        for request in harness.requests:
            assert api_key not in request.url
            assert all(api_key not in value for value in request.headers.values())
            body = (request.body or b"").decode("utf-8")
            assert body.count(api_key) == 1
            assert json.loads(body)["clientKey"] == api_key
        if error is not None:
            assert api_key not in f"{error}\n{error!r}"


SCENARIOS = sorted(SCENARIO_DIR.glob("*.json"))


def test_scenarios_are_vendored() -> None:
    assert SCENARIOS


@pytest.mark.parametrize("path", SCENARIOS, ids=lambda path: path.stem)
def test_async_client(path: Path) -> None:
    harness = Harness(json.loads(path.read_text("utf-8")))
    check(harness, *run_async(harness))


@pytest.mark.parametrize(
    "path",
    [path for path in SCENARIOS if "cancelAfterSleeps" not in json.loads(path.read_text("utf-8"))["call"]],
    ids=lambda path: path.stem,
)
def test_sync_client(path: Path) -> None:
    harness = Harness(json.loads(path.read_text("utf-8")))
    check(harness, *run_sync(harness))
