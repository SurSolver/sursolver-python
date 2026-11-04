"""Public data types."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Task = Mapping[str, Any]
"""A task object: ``type`` plus that type's fields, sent verbatim. Browser task types require
``userAgent`` (the Windows Chrome User-Agent of the client that will use the result)."""

Solution = dict[str, Any]
"""A task's result. Keys differ per type (``token``, ``gRecaptchaResponse``, ``cf_clearance``,
``cookies``, ...) and are passed through untouched. Tokens and cookies are single-use."""


@dataclass(frozen=True, slots=True)
class TaskResult:
    status: Literal["processing", "ready"]
    solution: Solution | None = None


@dataclass(frozen=True, slots=True)
class SolveResult:
    task_id: str
    solution: Solution


@dataclass(frozen=True, slots=True)
class TaskTypeInfo:
    """One entry of ``GET /v1/task-types``."""

    page_slug: str | None
    display_name: str
    task_type: str
    """Canonical name (the proxy-capable one when a ProxyLess twin exists)."""
    task_type_proxyless: str | None
    aliases: tuple[str, ...]
    proxy: str
    """``none``, ``optional`` or ``required``."""
    required: tuple[tuple[str, ...], ...]
    """Groups of accepted spellings; supply one name per group."""
    any_of: tuple[tuple[str, ...], ...]
    """Alternatives; supply every field of at least one."""
    optional: tuple[str, ...]
    solution_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TaskTypeCatalog:
    task_types: tuple[TaskTypeInfo, ...]
    error_codes: tuple[str, ...]
    """The complete ``errorCode`` vocabulary of the solver endpoints."""


@dataclass(frozen=True, slots=True)
class ServiceInfo:
    """One entry of ``GET /v1/services``."""

    id: int
    slug: str
    display_name: str
    price_per_request: str
    """USD price per task as a decimal string, e.g. ``"0.0006"``."""
    status: str
    avg_latency_ms: int | None


@dataclass(frozen=True, slots=True)
class HttpRequest:
    method: Literal["GET", "POST"]
    url: str
    headers: Mapping[str, str]
    body: bytes | None
    timeout: float
    """Seconds."""


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


Transport = Callable[[HttpRequest], HttpResponse]
"""Sends one request. Return any status; raise only when no response arrived. Must not follow
redirects."""

AsyncTransport = Callable[[HttpRequest], Awaitable[HttpResponse]]


class Clock(Protocol):
    def now(self) -> float:
        """Seconds; only differences are used."""
        ...

    def sleep(self, seconds: float) -> None: ...


class AsyncClock(Protocol):
    def now(self) -> float: ...

    async def sleep(self, seconds: float) -> None: ...
