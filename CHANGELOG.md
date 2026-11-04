# Changelog

## 0.1.0 — unreleased

First release. Tested against the SDK specification revision in `SPEC_VERSION` (catalog of
2026-11-04).

- `SurSolver` (synchronous) and `AsyncSurSolver` (asyncio) clients: `create_task`,
  `get_task_result`, `get_balance`, `list_task_types`, `list_services` and the `solve()`
  helper (3 s polling, 210 s deadline, `on_task_created`, asyncio cancellation).
- Typed errors: `AuthenticationError`, `InvalidTaskError` (with `supported_user_agents`),
  `InsufficientBalanceError`, `NoSlotAvailableError`, `TaskNotFoundError`, `TaskFailedError`,
  `ApiError`, `TransportError` (with `may_have_created_task`), `ProtocolError`,
  `SolveTimeoutError`, `ConfigurationError`.
- `TaskType` and `ErrorCode` enums generated from the public catalog.
- One dependency: `httpx`. Fully typed (`py.typed`).
