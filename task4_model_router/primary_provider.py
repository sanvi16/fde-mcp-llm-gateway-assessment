import asyncio

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Mock Primary Model Provider")


@app.post("/v1/chat/completions")
async def completions(request: Request):
    payload = await request.json()
    mode = payload.get("_mock_primary")

    if mode == "429":
        return JSONResponse(
            status_code=429,
            content={"error": "mock primary rate limit"},
        )

    if mode == "timeout":
        await asyncio.sleep(5)

    if mode == "500":
        return JSONResponse(
            status_code=500,
            content={"error": "mock primary failure"},
        )

    return {
        "id": "primary-demo",
        "choices": [{"message": {"role": "assistant", "content": "primary response"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
    }
