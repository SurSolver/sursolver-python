"""Asynchronous client (asyncio)."""

from __future__ import annotations

import asyncio
import random as _random
from collections.abc import Callable
from types import TracebackType
from typing import Any, Self

import httpx

from . import _core
from ._errors import NoSlotAvailableError, Operation, SolveTimeoutError, SurSolverError
from ._types import (
    AsyncClock,
    AsyncTransport,
    HttpRequest,
    HttpResponse,
    ServiceInfo,
    SolveResult,
    Task,
    TaskResult,
    TaskTypeCatalog,
)


class _AsyncSystemClock:
    def now(self) -> float:
        return asyncio.get_running_loop().time()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class AsyncSurSolver:
    """asyncio client for the SurSolver solver API; same behaviour as ``SurSolver``.

    Cancel a call the asyncio way (``task.cancel()``, ``asyncio.timeout``): the call raises
    ``asyncio.CancelledError`` and never claims the task failed. Use as an async context
    manager (or call ``aclose()``) to release the default transport's connection pool.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = _core.DEFAULT_BASE_URL,
        request_timeout: float | None = None,
        poll_interval: float | None = None,
        solve_timeout: float | None = None,
        max_submit_retries: int | None = None,
        app_id: str | None = None,
        user_agent_suffix: str | None = None,
        transport: AsyncTransport | None = None,
        clock: AsyncClock | None = None,
        random: Callable[[], float] | None = None,
    ) -> None:
        self._settings = _core.build_settings(
            api_key,
            base_url=base_url,
            request_timeout=request_timeout,
            poll_interval=poll_interval,
            solve_timeout=solve_timeout,
            max_submit_retries=max_submit_retries,
            app_id=app_id,
            user_agent_suffix=user_agent_suffix,
        )
        self._http: httpx.AsyncClient | None = None
        if transport is None:
            self._http = httpx.AsyncClient(follow_redirects=False)
            transport = self._httpx_send
        self._transport = transport
        self._clock: AsyncClock = clock if clock is not None else _AsyncSystemClock()
        self._random = random if random is not None else _random.random

    def __repr__(self) -> str:
        return f"AsyncSurSolver(base_url={self._settings.base_url!r})"

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()

    async def create_task(self, task: Task) -> str:
        """Submit a task and return its id. The task is charged from this point. Never retried."""
        payload = _core.create_task_payload(self._settings, task)
        body = await self._solver_call("createTask", "/createTask", payload)
        return _core.task_id_from(body)

    async def get_task_result(self, task_id: str) -> TaskResult:
        """Read a task's state once. A terminal failure raises ``TaskFailedError``."""
        payload = {"clientKey": self._settings.api_key, "taskId": task_id}
        body = await self._solver_call("getTaskResult", "/getTaskResult", payload, task_id)
        return _core.task_result_from(body)

    async def get_balance(self) -> float:
        """Cash balance in USD as the JSON number the API sends (display only)."""
        body = await self._solver_call("getBalance", "/getBalance", {"clientKey": self._settings.api_key})
        return _core.balance_from(body)

    async def solve(
        self,
        task: Task,
        *,
        poll_interval: float | None = None,
        solve_timeout: float | None = None,
        on_task_created: Callable[[str], None] | None = None,
    ) -> SolveResult:
        """Create a task and poll it until it is ready, failed, or the deadline passes.

        Same rules as ``SurSolver.solve``. Pass ``on_task_created`` to keep the task id when
        the call is cancelled.
        """
        interval = _core.positive_seconds("poll_interval", poll_interval, self._settings.poll_interval)
        timeout = _core.positive_seconds("solve_timeout", solve_timeout, self._settings.solve_timeout)
        deadline = self._clock.now() + timeout

        retries = 0
        while True:
            try:
                task_id = await self.create_task(task)
                break
            except NoSlotAvailableError:
                if retries >= self._settings.max_submit_retries:
                    raise
                retries += 1
                await self._clock.sleep(_core.submit_retry_delay(interval, self._random()))
        if on_task_created is not None:
            on_task_created(task_id)

        while True:
            last_error: SurSolverError | None = None
            try:
                result = await self.get_task_result(task_id)
                if result.status == "ready" and result.solution is not None:
                    return SolveResult(task_id=task_id, solution=result.solution)
            except SurSolverError as error:
                if not _core.is_transient_poll_error(error):
                    raise
                last_error = error
            await self._clock.sleep(interval)
            if self._clock.now() >= deadline:
                raise SolveTimeoutError(task_id, timeout, last_error)

    async def list_task_types(self) -> TaskTypeCatalog:
        """The public task-type catalog: accepted names, fields, proxy modes and result keys."""
        return _core.task_types_from(await self._catalog_call("listTaskTypes", "/v1/task-types"))

    async def list_services(self) -> list[ServiceInfo]:
        """Active services with their current USD price per task (decimal strings)."""
        return _core.services_from(await self._catalog_call("listServices", "/v1/services"))

    async def _httpx_send(self, request: HttpRequest) -> HttpResponse:
        assert self._http is not None
        response = await self._http.request(
            request.method,
            request.url,
            headers=dict(request.headers),
            content=request.body,
            timeout=request.timeout,
        )
        return HttpResponse(
            status=response.status_code, body=response.content, headers=dict(response.headers)
        )

    async def _send(self, operation: Operation, request: HttpRequest) -> HttpResponse:
        try:
            return await self._transport(request)
        except Exception as error:
            raise _core.transport_failure(operation, error, request.timeout) from error

    async def _solver_call(
        self, operation: Operation, path: str, payload: dict[str, Any], task_id: str | None = None
    ) -> dict[str, Any]:
        response = await self._send(operation, _core.solver_request(self._settings, path, payload))
        return _core.parse_solver(operation, response, task_id)

    async def _catalog_call(self, operation: Operation, path: str) -> dict[str, Any]:
        response = await self._send(operation, _core.catalog_request(self._settings, path))
        return _core.parse_catalog(operation, response)
