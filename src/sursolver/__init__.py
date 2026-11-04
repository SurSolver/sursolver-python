"""Official Python client for the SurSolver captcha-solving API."""

from ._async_client import AsyncSurSolver
from ._client import SurSolver
from ._core import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_SUBMIT_RETRIES,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_SOLVE_TIMEOUT,
    SUBMIT_RETRY_JITTER_MS,
)
from ._errors import (
    ApiError,
    AuthenticationError,
    ConfigurationError,
    InsufficientBalanceError,
    InvalidTaskError,
    NoSlotAvailableError,
    Operation,
    ProtocolError,
    SolveTimeoutError,
    SurSolverError,
    TaskFailedError,
    TaskNotFoundError,
    TransportError,
)
from ._types import (
    AsyncClock,
    AsyncTransport,
    Clock,
    HttpRequest,
    HttpResponse,
    ServiceInfo,
    Solution,
    SolveResult,
    Task,
    TaskResult,
    TaskTypeCatalog,
    TaskTypeInfo,
    Transport,
)
from ._version import VERSION
from .task_types import ErrorCode, TaskType

__version__ = VERSION

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MAX_SUBMIT_RETRIES",
    "DEFAULT_POLL_INTERVAL",
    "DEFAULT_REQUEST_TIMEOUT",
    "DEFAULT_SOLVE_TIMEOUT",
    "SUBMIT_RETRY_JITTER_MS",
    "VERSION",
    "ApiError",
    "AsyncClock",
    "AsyncSurSolver",
    "AsyncTransport",
    "AuthenticationError",
    "Clock",
    "ConfigurationError",
    "ErrorCode",
    "HttpRequest",
    "HttpResponse",
    "InsufficientBalanceError",
    "InvalidTaskError",
    "NoSlotAvailableError",
    "Operation",
    "ProtocolError",
    "ServiceInfo",
    "Solution",
    "SolveResult",
    "SolveTimeoutError",
    "SurSolver",
    "SurSolverError",
    "Task",
    "TaskFailedError",
    "TaskNotFoundError",
    "TaskResult",
    "TaskType",
    "TaskTypeCatalog",
    "TaskTypeInfo",
    "Transport",
    "TransportError",
]
