import asyncio

import httpx
import pytest

from task4_model_router.rate_limiter import RateLimitExceeded, SQLiteTokenRateLimiter
from task4_model_router.router import ProviderFailed, route_model_request


@pytest.mark.asyncio
async def test_sliding_window_and_eviction(tmp_path):
    db = tmp_path / "rate.db"
    limiter = SQLiteTokenRateLimiter(
        str(db),
        limit_tokens=100,
        window_ms=60_000,
    )
    await limiter.initialize()

    await limiter.reserve("tenant-a", 60, now_ms=100_000)
    assert await limiter.usage("tenant-a", now_ms=100_000) == 60

    with pytest.raises(RateLimitExceeded):
        await limiter.reserve("tenant-a", 50, now_ms=100_001)

    # First event is now outside the rolling window.
    await limiter.reserve("tenant-a", 50, now_ms=160_001)
    assert await limiter.usage("tenant-a", now_ms=160_001) == 50


@pytest.mark.asyncio
async def test_tenants_are_isolated(tmp_path):
    db = tmp_path / "rate.db"
    limiter = SQLiteTokenRateLimiter(str(db), limit_tokens=100)
    await limiter.initialize()

    await limiter.reserve("tenant-a", 90, now_ms=100_000)
    await limiter.reserve("tenant-b", 90, now_ms=100_000)

    assert await limiter.usage("tenant-a", now_ms=100_000) == 90
    assert await limiter.usage("tenant-b", now_ms=100_000) == 90


@pytest.mark.asyncio
async def test_concurrent_reservations_do_not_over_admit(tmp_path):
    db = tmp_path / "rate.db"
    limiter = SQLiteTokenRateLimiter(str(db), limit_tokens=100)
    await limiter.initialize()

    async def reserve():
        try:
            await limiter.reserve("tenant-a", 60, now_ms=100_000)
            return "allowed"
        except RateLimitExceeded:
            return "blocked"

    results = await asyncio.gather(reserve(), reserve())
    assert sorted(results) == ["allowed", "blocked"]


def mock_transport(primary_status=200, primary_delay=False):
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "primary.local":
            if primary_delay:
                await asyncio.sleep(0.05)
            if primary_status == 429:
                return httpx.Response(429, json={"error": "rate limited"})
            if primary_status >= 400:
                return httpx.Response(primary_status, json={"error": "failed"})
            return httpx.Response(200, json={"provider": "primary"})

        return httpx.Response(200, json={"provider": "backup"})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_primary_success():
    async with httpx.AsyncClient(transport=mock_transport()) as client:
        result, route = await route_model_request(
            {"messages": []},
            primary_url="https://primary.local/chat",
            backup_url="https://backup.local/chat",
            client=client,
        )
    assert route == "primary"
    assert result["provider"] == "primary"


@pytest.mark.asyncio
async def test_429_falls_back():
    async with httpx.AsyncClient(transport=mock_transport(primary_status=429)) as client:
        result, route = await route_model_request(
            {"messages": []},
            primary_url="https://primary.local/chat",
            backup_url="https://backup.local/chat",
            client=client,
        )
    assert route == "backup"
    assert result["provider"] == "backup"


@pytest.mark.asyncio
async def test_timeout_falls_back():
    async with httpx.AsyncClient(transport=mock_transport(primary_delay=True)) as client:
        result, route = await route_model_request(
            {"messages": []},
            primary_url="https://primary.local/chat",
            backup_url="https://backup.local/chat",
            primary_timeout_seconds=0.01,
            client=client,
        )
    assert route == "backup"
    assert result["provider"] == "backup"


@pytest.mark.asyncio
async def test_non_retryable_primary_failure_does_not_fallback():
    async with httpx.AsyncClient(transport=mock_transport(primary_status=500)) as client:
        with pytest.raises(ProviderFailed):
            await route_model_request(
                {"messages": []},
                primary_url="https://primary.local/chat",
                backup_url="https://backup.local/chat",
                client=client,
            )
