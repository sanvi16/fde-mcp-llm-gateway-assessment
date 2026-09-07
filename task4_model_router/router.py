from __future__ import annotations

import asyncio
from typing import Any

import httpx


class ProviderRateLimited(Exception):
    pass


class ProviderTimedOut(Exception):
    pass


class ProviderFailed(Exception):
    pass


async def invoke_provider(
    client: httpx.AsyncClient,
    url: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    try:
        async with asyncio.timeout(timeout_seconds):
            response = await client.post(url, json=payload)
    except TimeoutError as exc:
        raise ProviderTimedOut() from exc
    except httpx.RequestError as exc:
        raise ProviderFailed() from exc

    if response.status_code == 429:
        raise ProviderRateLimited()

    if response.status_code >= 400:
        raise ProviderFailed()

    try:
        return response.json()
    except ValueError as exc:
        raise ProviderFailed() from exc


async def route_model_request(
    payload: dict[str, Any],
    *,
    primary_url: str,
    backup_url: str,
    primary_timeout_seconds: float = 3.0,
    backup_timeout_seconds: float = 5.0,
    client: httpx.AsyncClient | None = None,
) -> tuple[dict[str, Any], str]:
    owns_client = client is None
    client = client or httpx.AsyncClient()

    try:
        try:
            result = await invoke_provider(
                client,
                primary_url,
                payload,
                timeout_seconds=primary_timeout_seconds,
            )
            return result, "primary"
        except (ProviderRateLimited, ProviderTimedOut):
            result = await invoke_provider(
                client,
                backup_url,
                payload,
                timeout_seconds=backup_timeout_seconds,
            )
            return result, "backup"
    finally:
        if owns_client:
            await client.aclose()
