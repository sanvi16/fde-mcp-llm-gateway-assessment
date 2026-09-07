from fastapi import FastAPI, Request

app = FastAPI(title="Mock Downstream MCP Server")


@app.post("/mcp")
async def mcp(request: Request):
    payload = await request.json()
    request_id = payload.get("id")
    method = payload.get("method")

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [
                    {"name": "get_customer", "inputSchema": {"type": "object"}},
                    {"name": "admin_reset_key", "inputSchema": {"type": "object"}},
                ]
            },
        }

    if method == "tools/call":
        name = (payload.get("params") or {}).get("name")
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [
                    {"type": "text", "text": f"downstream executed {name}"}
                ],
                "isError": False,
            },
        }

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": "Method not found"},
    }
