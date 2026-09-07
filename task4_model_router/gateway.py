from __future__ import annotations

import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from task4_model_router.rate_limiter import (
    RateLimitExceeded,
    SQLiteTokenRateLimiter,
)
from task4_model_router.router import (
    ProviderFailed,
    ProviderRateLimited,
    ProviderTimedOut,
    route_model_request,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("model-router")

DB_PATH = os.getenv("RATE_LIMIT_DB", "gateway.db")
PRIMARY_URL = os.getenv(
    "PRIMARY_MODEL_URL",
    "http://127.0.0.1:9200/v1/chat/completions",
)
BACKUP_URL = os.getenv(
    "BACKUP_MODEL_URL",
    "http://127.0.0.1:9300/v1/chat/completions",
)

limiter = SQLiteTokenRateLimiter(DB_PATH)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await limiter.initialize()
    yield


app = FastAPI(title="Resilient LLM Gateway", lifespan=lifespan)


def gateway_error(
    *,
    status_code: int,
    code: str,
    message: str,
    request_id: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": request_id,
            }
        },
    )


def estimate_tokens(payload: dict[str, Any]) -> int:
    """Conservative pre-flight token reservation.

    A production implementation should use the tokenizer for the selected
    model. This dependency-free assessment approximation is documented and
    intentionally reserves requested output capacity.
    """

    messages = payload.get("messages", [])
    if not isinstance(messages, list):
        messages = []

    chars = 0
    for message in messages:
        if isinstance(message, dict):
            chars += len(str(message.get("content", "")))

    # Common approximation for English text. Always reserve at least one
    # input token for non-empty/metadata-only requests.
    input_tokens = max(1, (chars + 3) // 4)

    raw_max = payload.get("max_tokens", 1024)
    try:
        max_output_tokens = int(raw_max)
    except (TypeError, ValueError):
        max_output_tokens = 1024

    max_output_tokens = max(1, max_output_tokens)
    return input_tokens + max_output_tokens


@app.post("/v1/chat/completions")
async def completions(
    request: Request,
    x_api_key: str | None = Header(default=None),
):
    request_id = "req_" + uuid.uuid4().hex[:12]

    if not x_api_key:
        return gateway_error(
            status_code=401,
            code="UNAUTHORIZED",
            message="Missing API key.",
            request_id=request_id,
        )

    try:
        payload = await request.json()
    except Exception:
        return gateway_error(
            status_code=400,
            code="INVALID_REQUEST",
            message="Invalid JSON request.",
            request_id=request_id,
        )

    if not isinstance(payload, dict):
        return gateway_error(
            status_code=400,
            code="INVALID_REQUEST",
            message="Request body must be a JSON object.",
            request_id=request_id,
        )

    reservation = estimate_tokens(payload)

    try:
        await limiter.reserve(x_api_key, reservation)
    except RateLimitExceeded:
        return gateway_error(
            status_code=429,
            code="TOKEN_RATE_LIMIT_EXCEEDED",
            message="Tenant token rate limit exceeded.",
            request_id=request_id,
        )
    except Exception:
        logger.exception("rate limiter failure request_id=%s", request_id)
        return gateway_error(
            status_code=503,
            code="GATEWAY_UNAVAILABLE",
            message="The gateway is temporarily unavailable.",
            request_id=request_id,
        )

    try:
        result, route = await route_model_request(
            payload,
            primary_url=PRIMARY_URL,
            backup_url=BACKUP_URL,
            primary_timeout_seconds=3.0,
            backup_timeout_seconds=5.0,
        )

        # Safe gateway metadata; no private endpoint/stack information.
        result["_gateway"] = {
            "request_id": request_id,
            "route": route,
        }
        return result

    except (ProviderRateLimited, ProviderTimedOut, ProviderFailed):
        logger.exception("all applicable model routes failed request_id=%s", request_id)
        return gateway_error(
            status_code=503,
            code="UPSTREAM_UNAVAILABLE",
            message="The requested model is temporarily unavailable.",
            request_id=request_id,
        )
