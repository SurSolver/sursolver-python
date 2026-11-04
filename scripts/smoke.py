"""Live smoke test against the real API. Costs nothing: it reads the public catalog and calls
get_balance with a fake key (expects AuthenticationError), with both clients. Set
SURSOLVER_API_KEY to also read your real balance."""

from __future__ import annotations

import asyncio
import os

from sursolver import AsyncSurSolver, AuthenticationError, SurSolver

FAKE_KEY = "sur_00000000000000000000000000000000"
BASE_URL = os.environ.get("SURSOLVER_BASE_URL", "https://api.sursolver.com")


def sync_smoke() -> None:
    with SurSolver(FAKE_KEY, base_url=BASE_URL) as client:
        catalog = client.list_task_types()
        print(f"list_task_types: {len(catalog.task_types)} types, {len(catalog.error_codes)} error codes")
        print(f"list_services: {len(client.list_services())} active services")
        try:
            client.get_balance()
        except AuthenticationError as error:
            print(f"get_balance (fake key): {type(error).__name__} {error.code}")
        else:
            raise SystemExit("get_balance with a fake key unexpectedly succeeded")
    real_key = os.environ.get("SURSOLVER_API_KEY")
    if real_key:
        with SurSolver(real_key, base_url=BASE_URL) as client:
            print(f"get_balance (your key): {client.get_balance()} USD")


async def async_smoke() -> None:
    async with AsyncSurSolver(FAKE_KEY, base_url=BASE_URL) as client:
        services = await client.list_services()
        print(f"async list_services: {len(services)} active services")
        try:
            await client.get_balance()
        except AuthenticationError as error:
            print(f"async get_balance (fake key): {type(error).__name__} {error.code}")
        else:
            raise SystemExit("async get_balance with a fake key unexpectedly succeeded")


sync_smoke()
asyncio.run(async_smoke())
print("smoke: OK")
