from __future__ import annotations

import time

import aiosqlite

RATE_LIMIT_TOKENS = 50_000
WINDOW_MS = 60_000


class RateLimitExceeded(Exception):
    def __init__(self, current_usage: int, requested_tokens: int):
        super().__init__("token rate limit exceeded")
        self.current_usage = current_usage
        self.requested_tokens = requested_tokens


class SQLiteTokenRateLimiter:
    def __init__(
        self,
        db_path: str,
        *,
        limit_tokens: int = RATE_LIMIT_TOKENS,
        window_ms: int = WINDOW_MS,
    ):
        self.db_path = db_path
        self.limit_tokens = limit_tokens
        self.window_ms = window_ms

    async def initialize(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS token_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_key TEXT NOT NULL,
                    timestamp_ms INTEGER NOT NULL,
                    tokens INTEGER NOT NULL CHECK(tokens > 0)
                )
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_token_usage_tenant_time
                ON token_usage(tenant_key, timestamp_ms)
                """
            )
            await db.commit()

    async def reserve(
        self,
        tenant_key: str,
        tokens: int,
        *,
        now_ms: int | None = None,
    ) -> int:
        """Atomically check the rolling window and reserve tokens.

        Returns the usage after reservation.
        """

        if not tenant_key:
            raise ValueError("tenant_key is required")
        if tokens <= 0:
            raise ValueError("tokens must be positive")

        now = now_ms if now_ms is not None else int(time.time() * 1000)
        cutoff = now - self.window_ms

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute("BEGIN IMMEDIATE")

            try:
                # State eviction keeps the on-disk table bounded over time.
                await db.execute(
                    "DELETE FROM token_usage WHERE timestamp_ms < ?",
                    (cutoff,),
                )

                cursor = await db.execute(
                    """
                    SELECT COALESCE(SUM(tokens), 0)
                    FROM token_usage
                    WHERE tenant_key = ?
                      AND timestamp_ms >= ?
                    """,
                    (tenant_key, cutoff),
                )
                row = await cursor.fetchone()
                current = int(row[0]) if row else 0

                if current + tokens > self.limit_tokens:
                    await db.rollback()
                    raise RateLimitExceeded(current, tokens)

                await db.execute(
                    """
                    INSERT INTO token_usage(tenant_key, timestamp_ms, tokens)
                    VALUES (?, ?, ?)
                    """,
                    (tenant_key, now, tokens),
                )
                await db.commit()
                return current + tokens
            except Exception:
                if db.in_transaction:
                    await db.rollback()
                raise

    async def usage(self, tenant_key: str, *, now_ms: int | None = None) -> int:
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        cutoff = now - self.window_ms

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT COALESCE(SUM(tokens), 0)
                FROM token_usage
                WHERE tenant_key = ?
                  AND timestamp_ms >= ?
                """,
                (tenant_key, cutoff),
            )
            row = await cursor.fetchone()
            return int(row[0]) if row else 0
