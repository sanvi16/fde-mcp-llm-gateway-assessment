import asyncio
import json

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI(title="Mock Streaming LLM Provider")


def sse_delta(text: str) -> str:
    event = {"choices": [{"delta": {"content": text}}]}
    return f"data: {json.dumps(event)}\n\n"


@app.post("/v1/chat/completions")
async def completions():
    async def generate():
        # Deliberately split sensitive values across arbitrary provider chunks.
        chunks = [
            "Hello. Email me at alice@exa",
            "mple.com. My SSN is 123-",
            "45-6789. Test card: 4111 1111 ",
            "1111 1111. Thanks.",
        ]

        for chunk in chunks:
            yield sse_delta(chunk)
            await asyncio.sleep(0.05)

        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
