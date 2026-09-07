from __future__ import annotations

import json
import os
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from task3_llm_guardrail.redactor import StreamingPIIRedactor

app = FastAPI(title="Streaming LLM Guardrail Gateway")

PROVIDER_URL = os.getenv(
    "LLM_PROVIDER_URL",
    "http://127.0.0.1:9100/v1/chat/completions",
)


def make_delta(text: str) -> str:
    event = {"choices": [{"delta": {"content": text}}]}
    return f"data: {json.dumps(event, separators=(',', ':'))}\n\n"


async def sanitized_stream(payload: dict) -> AsyncIterator[str]:
    redactor = StreamingPIIRedactor(carry_size=64)

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST",
            PROVIDER_URL,
            json={**payload, "stream": True},
        ) as upstream:
            upstream.raise_for_status()

            async for line in upstream.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue

                raw = line[len("data:"):].strip()

                if raw == "[DONE]":
                    tail = redactor.flush()
                    if tail:
                        yield make_delta(tail)
                    yield "data: [DONE]\n\n"
                    return

                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                try:
                    content = event["choices"][0]["delta"].get("content")
                except (KeyError, IndexError, TypeError, AttributeError):
                    content = None

                if not isinstance(content, str) or not content:
                    continue

                safe = redactor.push(content)
                if safe:
                    yield make_delta(safe)

            # Defensive flush when the upstream closes without [DONE].
            tail = redactor.flush()
            if tail:
                yield make_delta(tail)
            yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def completions(request: Request):
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "INVALID_REQUEST", "message": "Invalid JSON."}},
        )

    return StreamingResponse(
        sanitized_stream(payload),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
