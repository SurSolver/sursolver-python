"""Validation, request building and response classification shared by both clients."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from ._errors import (
    ApiError,
    ConfigurationError,
    Operation,
    ProtocolError,
    SurSolverError,
    TransportError,
    api_error_for,
)
from ._types import (
    HttpRequest,
    HttpResponse,
    ServiceInfo,
    TaskResult,
    TaskTypeCatalog,
    TaskTypeInfo,
)
from ._version import VERSION

DEFAULT_BASE_URL = "https://api.sursolver.com"
DEFAULT_REQUEST_TIMEOUT = 30.0
DEFAULT_POLL_INTERVAL = 3.0
DEFAULT_SOLVE_TIMEOUT = 210.0
DEFAULT_MAX_SUBMIT_RETRIES = 1
SUBMIT_RETRY_JITTER_MS = 1000
"""Upper bound of the random delay added to a submit retry, so parallel callers spread out."""

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


@dataclass(frozen=True, slots=True)
class Settings:
    api_key: str
    base_url: str
    request_timeout: float
    poll_interval: float
    solve_timeout: float
    max_submit_retries: int
    app_id: str | None
    user_agent: str


def positive_seconds(name: str, value: float | None, fallback: float) -> float:
    if value is None:
        return fallback
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ConfigurationError(f"{name} must be a positive number of seconds")
    return float(value)


def _normalize_base_url(raw: str) -> str:
    parts = urlsplit(raw)
    loopback_http = parts.scheme == "http" and parts.hostname in _LOOPBACK_HOSTS
    if parts.scheme != "https" and not loopback_http:
        raise ConfigurationError("base_url must use https:// (plain http:// only for localhost)")
    if not parts.netloc:
        raise ConfigurationError("base_url has no host")
    if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        raise ConfigurationError("base_url must not carry credentials, a query or a fragment")
    return f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}"


def build_settings(
    api_key: str,
    *,
    base_url: str,
    request_timeout: float | None,
    poll_interval: float | None,
    solve_timeout: float | None,
    max_submit_retries: int | None,
    app_id: str | None,
    user_agent_suffix: str | None,
) -> Settings:
    if not isinstance(api_key, str) or api_key.strip() == "":
        raise ConfigurationError("api_key must be a non-empty string")
    if api_key.strip() != api_key:
        raise ConfigurationError("api_key has leading or trailing whitespace")
    retries = DEFAULT_MAX_SUBMIT_RETRIES if max_submit_retries is None else max_submit_retries
    if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0:
        raise ConfigurationError("max_submit_retries must be a non-negative integer")
    if user_agent_suffix is not None and not (
        user_agent_suffix and all(" " <= char <= "~" for char in user_agent_suffix)
    ):
        raise ConfigurationError("user_agent_suffix must be printable ASCII")
    user_agent = f"sursolver-python/{VERSION}"
    if user_agent_suffix is not None:
        user_agent = f"{user_agent} {user_agent_suffix}"
    trimmed_app_id = app_id.strip() if app_id is not None else ""
    return Settings(
        api_key=api_key,
        base_url=_normalize_base_url(base_url),
        request_timeout=positive_seconds("request_timeout", request_timeout, DEFAULT_REQUEST_TIMEOUT),
        poll_interval=positive_seconds("poll_interval", poll_interval, DEFAULT_POLL_INTERVAL),
        solve_timeout=positive_seconds("solve_timeout", solve_timeout, DEFAULT_SOLVE_TIMEOUT),
        max_submit_retries=retries,
        app_id=trimmed_app_id or None,
        user_agent=user_agent,
    )


def solver_request(settings: Settings, path: str, payload: dict[str, Any]) -> HttpRequest:
    return HttpRequest(
        method="POST",
        url=f"{settings.base_url}{path}",
        headers={
            "accept": "application/json",
            "content-type": "application/json",
            "user-agent": settings.user_agent,
        },
        body=json.dumps(payload).encode("utf-8"),
        timeout=settings.request_timeout,
    )


def catalog_request(settings: Settings, path: str) -> HttpRequest:
    return HttpRequest(
        method="GET",
        url=f"{settings.base_url}{path}",
        headers={"accept": "application/json", "user-agent": settings.user_agent},
        body=None,
        timeout=settings.request_timeout,
    )


def create_task_payload(settings: Settings, task: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"clientKey": settings.api_key, "task": task}
    if settings.app_id is not None:
        payload["appId"] = settings.app_id
    return payload


def transport_failure(operation: Operation, error: Exception, timeout: float) -> TransportError:
    """A transport that raised: no response arrived."""
    if isinstance(error, (httpx.TimeoutException, TimeoutError)):
        return TransportError(operation, f"request timed out after {timeout:g} s")
    return TransportError(operation, "connection failed")


def _load_json(body: bytes) -> Any:
    if not body:
        return None
    try:
        return json.loads(body)
    except ValueError:
        return None


def _is_integral(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    return isinstance(value, int) or (isinstance(value, float) and value.is_integer())


def _checked(operation: Operation, response: HttpResponse) -> Any:
    """Reject non-200 statuses; return the parsed JSON body (None when not JSON)."""
    parsed = _load_json(response.body)
    if response.status != 200:
        envelope = parsed.get("error") if isinstance(parsed, dict) else None
        envelope = envelope if isinstance(envelope, dict) else {}
        code = envelope.get("code")
        server_code = code if isinstance(code, str) else None
        retry_after = envelope.get("retry_after_seconds")
        reason = f"HTTP {response.status}" + ("" if server_code is None else f" ({server_code})")
        raise TransportError(
            operation,
            reason,
            status=response.status,
            server_code=server_code,
            retry_after_seconds=retry_after
            if isinstance(retry_after, (int, float)) and not isinstance(retry_after, bool)
            else None,
        )
    return parsed


def parse_solver(operation: Operation, response: HttpResponse, task_id: str | None = None) -> dict[str, Any]:
    """Return the ``errorId: 0`` body of a solver call or raise the classified error."""
    body = _checked(operation, response)
    if not isinstance(body, dict) or not _is_integral(body.get("errorId")):
        what = "not JSON" if body is None else "not the solver envelope"
        raise TransportError(operation, f"HTTP 200 body is {what}", status=200)
    error_id = body["errorId"]
    if error_id == 0:
        return body
    if error_id != 1:
        raise ProtocolError(operation, f"errorId {error_id}")
    code = body.get("errorCode")
    if not isinstance(code, str):
        raise ProtocolError(operation, "errorId 1 without a string errorCode")
    description = body.get("errorDescription")
    supported = body.get("supportedUserAgents")
    raise api_error_for(
        operation,
        code,
        description if isinstance(description, str) else "",
        task_id=task_id,
        supported_user_agents=[ua for ua in supported if isinstance(ua, str)]
        if isinstance(supported, list)
        else (),
    )


def parse_catalog(operation: Operation, response: HttpResponse) -> dict[str, Any]:
    """Return ``data`` of a ``{"success": true, "data": {...}}`` envelope."""
    body = _checked(operation, response)
    if (
        not isinstance(body, dict)
        or body.get("success") is not True
        or not isinstance(body.get("data"), dict)
    ):
        raise TransportError(operation, "HTTP 200 body is not the API envelope", status=200)
    data: dict[str, Any] = body["data"]
    return data


def task_id_from(body: dict[str, Any]) -> str:
    task_id = body.get("taskId")
    if not isinstance(task_id, str) or task_id == "":
        raise ProtocolError("createTask", "errorId 0 without a taskId")
    return task_id


def task_result_from(body: dict[str, Any]) -> TaskResult:
    status = body.get("status")
    if status == "processing":
        return TaskResult(status="processing")
    if status == "ready":
        solution = body.get("solution")
        if not isinstance(solution, dict):
            raise ProtocolError("getTaskResult", "status ready without a solution object")
        return TaskResult(status="ready", solution=solution)
    raise ProtocolError("getTaskResult", f"unknown status {json.dumps(status)}")


def balance_from(body: dict[str, Any]) -> float:
    balance = body.get("balance")
    if isinstance(balance, bool) or not isinstance(balance, (int, float)) or not math.isfinite(balance):
        raise ProtocolError("getBalance", "errorId 0 without a numeric balance")
    return balance


class _Entry:
    """Typed reads of one catalog entry; a missing or mistyped field is a ProtocolError."""

    def __init__(self, operation: Operation, value: Any) -> None:
        if not isinstance(value, dict):
            raise ProtocolError(operation, "a catalog entry is not an object")
        self._operation = operation
        self._value: dict[str, Any] = value

    def _fail(self, key: str, expected: str) -> ProtocolError:
        return ProtocolError(self._operation, f"catalog field {key} is not {expected}")

    def text(self, key: str) -> str:
        value = self._value.get(key)
        if not isinstance(value, str):
            raise self._fail(key, "a string")
        return value

    def optional_text(self, key: str) -> str | None:
        value = self._value.get(key)
        if value is not None and not isinstance(value, str):
            raise self._fail(key, "a string or null")
        return value

    def integer(self, key: str) -> int:
        value = self._value.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise self._fail(key, "an integer")
        return value

    def optional_integer(self, key: str) -> int | None:
        return None if self._value.get(key) is None else self.integer(key)

    def texts(self, key: str) -> tuple[str, ...]:
        value = self._value.get(key)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise self._fail(key, "a list of strings")
        return tuple(value)

    def groups(self, key: str) -> tuple[tuple[str, ...], ...]:
        value = self._value.get(key)
        if not isinstance(value, list) or not all(
            isinstance(group, list) and all(isinstance(item, str) for item in group) for group in value
        ):
            raise self._fail(key, "a list of string lists")
        return tuple(tuple(group) for group in value)


def task_types_from(data: dict[str, Any]) -> TaskTypeCatalog:
    entries, codes = data.get("task_types"), data.get("error_codes")
    if not isinstance(entries, list) or not isinstance(codes, list):
        raise ProtocolError("listTaskTypes", "data without task_types and error_codes arrays")
    task_types = []
    for raw in entries:
        entry = _Entry("listTaskTypes", raw)
        task_types.append(
            TaskTypeInfo(
                page_slug=entry.optional_text("page_slug"),
                display_name=entry.text("display_name"),
                task_type=entry.text("task_type"),
                task_type_proxyless=entry.optional_text("task_type_proxyless"),
                aliases=entry.texts("aliases"),
                proxy=entry.text("proxy"),
                required=entry.groups("required"),
                any_of=entry.groups("any_of"),
                optional=entry.texts("optional"),
                solution_keys=entry.texts("solution_keys"),
            )
        )
    if not all(isinstance(code, str) for code in codes):
        raise ProtocolError("listTaskTypes", "error_codes is not a list of strings")
    return TaskTypeCatalog(task_types=tuple(task_types), error_codes=tuple(codes))


def services_from(data: dict[str, Any]) -> list[ServiceInfo]:
    services = data.get("services")
    if not isinstance(services, list):
        raise ProtocolError("listServices", "data without a services array")
    result = []
    for raw in services:
        entry = _Entry("listServices", raw)
        result.append(
            ServiceInfo(
                id=entry.integer("id"),
                slug=entry.text("slug"),
                display_name=entry.text("display_name"),
                price_per_request=entry.text("price_per_request"),
                status=entry.text("status"),
                avg_latency_ms=entry.optional_integer("avg_latency_ms"),
            )
        )
    return result


def submit_retry_delay(poll_interval: float, random_value: float) -> float:
    """Wait before resubmitting after ERROR_NO_SLOT_AVAILABLE: one poll interval plus jitter."""
    return poll_interval + math.floor(random_value * SUBMIT_RETRY_JITTER_MS) / 1000


def is_transient_poll_error(error: SurSolverError) -> bool:
    """Poll failures that say nothing about the task and may be retried inside the deadline."""
    return isinstance(error, TransportError) or (
        isinstance(error, ApiError) and error.code == "ERROR_INTERNAL_ERROR"
    )
