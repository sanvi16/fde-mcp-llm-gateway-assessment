from fastapi import FastAPI

app = FastAPI(title="Mock Backup Model Provider")


@app.post("/v1/chat/completions")
async def completions():
    return {
        "id": "backup-demo",
        "choices": [{"message": {"role": "assistant", "content": "backup response"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
    }
