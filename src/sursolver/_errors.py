"""Error types. Cancellation is never wrapped: it stays ``asyncio.CancelledError``."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

Operation = Literal["createTask", "getTaskResult", "getBalance", "listTaskTypes", "listServices"]


class SurSolverError(Exception):
    """Base class of every error this package raises."""

    operation: Operation | None

    def __init__(self, message: str, operation: Operation | None = None) -> None:
        super().__init__(message)
        self.operation = operation


class ConfigurationError(SurSolverError, ValueError):
    """The client was built with an unusable option. Nothing was sent."""


class TransportError(SurSolverError):
    """No usable answer: connection failure, timeout, a non-200 status, or a body that is not
    the API's envelope. It says nothing about the task.

    ``may_have_created_task`` is true for ``create_task``: the request may have been accepted
    and charged before the answer was lost. Check ``get_balance()`` before submitting again;
    the API has no idempotency.
    """

    def __init__(
        self,
        operation: Operation,
        reason: str,
        *,
        status: int | None = None,
        server_code: str | None = None,
        retry_after_seconds: int | float | None = None,
    ) -> None:
        self.may_have_created_task = operation == "createTask"
        note = (
            " The task may have been created and charged; check get_balance() before submitting again."
            if self.may_have_created_task
            else ""
        )
        super().__init__(f"{operation} failed: {reason}.{note}", operation)
        self.status = status
        self.server_code = server_code
        self.retry_after_seconds = retry_after_seconds


class ProtocolError(SurSolverError):
    """HTTP 200 JSON whose shape the API contract does not allow."""

    def __init__(self, operation: Operation, detail: str) -> None:
        super().__init__(f"{operation} returned an unexpected response: {detail}", operation)


class ApiError(SurSolverError):
    """The API answered ``errorId: 1``. Subclasses group the codes callers act on.

    ``code`` is the ``errorCode`` exactly as sent (including codes newer than this package);
    ``retryable`` is true only for ``ERROR_NO_SLOT_AVAILABLE``; ``supported_user_agents`` is
    the list sent with ``ERROR_WRONG_USERAGENT`` and empty otherwise.
    """

    def __init__(
        self,
        operation: Operation,
        code: str,
        description: str,
        *,
        task_id: str | None = None,
        supported_user_agents: Iterable[str] = (),
    ) -> None:
        task = "" if task_id is None else f" (task {task_id})"
        super().__init__(f"{code}: {description}{task}", operation)
        self.code = code
        self.description = description
        self.retryable = code == "ERROR_NO_SLOT_AVAILABLE"
        self.task_id = task_id
        self.supported_user_agents: tuple[str, ...] = tuple(supported_user_agents)


class AuthenticationError(ApiError):
    """``ERROR_WRONG_CLIENT_KEY`` or ``ERROR_KEY_DOES_NOT_EXIST``: fix the API key."""


class InvalidTaskError(ApiError):
    """``create_task`` refused the task itself: ``ERROR_INVALID_REQUEST``,
    ``ERROR_TYPE_NOT_SUPPORTED`` or ``ERROR_WRONG_USERAGENT`` (see ``supported_user_agents``).
    Nothing was created or charged."""


class InsufficientBalanceError(ApiError):
    """``ERROR_ZERO_BALANCE``: the balance or plan cannot cover the task. Nothing was charged."""


class NoSlotAvailableError(ApiError):
    """``ERROR_NO_SLOT_AVAILABLE``: the account's open tasks fill its thread limit, or the
    service is briefly not admitting work. Nothing was created; submitting later is safe."""


class TaskNotFoundError(ApiError):
    """``ERROR_TASK_NOT_FOUND``: unknown task id, or one owned by another account."""


class TaskFailedError(ApiError):
    """The task ended without a result: ``ERROR_FAILED``, ``ERROR_TASK_TIMEOUT``,
    ``ERROR_TASK_EXPIRED``, or ``ERROR_WRONG_USERAGENT`` after acceptance. Final for this
    task; the API returns a failed task's charge once."""


class SolveTimeoutError(SurSolverError):
    """``solve()`` reached its deadline. The task may still finish and stays charged: poll it
    with ``get_task_result(error.task_id)`` if you still need the result. ``last_error`` is the
    final poll's transient failure, when there was one."""

    def __init__(self, task_id: str, timeout: float, last_error: SurSolverError | None = None) -> None:
        super().__init__(
            f"task {task_id} was not ready within {timeout:g} s; it may still finish and stays charged",
            "getTaskResult",
        )
        self.task_id = task_id
        self.last_error = last_error
        self.__cause__ = last_error


_TASK_FAILURE_CODES = frozenset(
    {"ERROR_FAILED", "ERROR_TASK_TIMEOUT", "ERROR_TASK_EXPIRED", "ERROR_WRONG_USERAGENT"}
)

_CLASS_BY_CODE: dict[str, type[ApiError]] = {
    "ERROR_WRONG_CLIENT_KEY": AuthenticationError,
    "ERROR_KEY_DOES_NOT_EXIST": AuthenticationError,
    "ERROR_INVALID_REQUEST": InvalidTaskError,
    "ERROR_TYPE_NOT_SUPPORTED": InvalidTaskError,
    "ERROR_WRONG_USERAGENT": InvalidTaskError,
    "ERROR_ZERO_BALANCE": InsufficientBalanceError,
    "ERROR_NO_SLOT_AVAILABLE": NoSlotAvailableError,
    "ERROR_TASK_NOT_FOUND": TaskNotFoundError,
}


def api_error_for(
    operation: Operation,
    code: str,
    description: str,
    *,
    task_id: str | None = None,
    supported_user_agents: Iterable[str] = (),
) -> ApiError:
    """The error class for an ``errorId: 1`` answer: it depends on the operation and the code."""
    if operation == "getTaskResult" and code in _TASK_FAILURE_CODES:
        error_class: type[ApiError] = TaskFailedError
    else:
        error_class = _CLASS_BY_CODE.get(code, ApiError)
    return error_class(
        operation, code, description, task_id=task_id, supported_user_agents=supported_user_agents
    )
