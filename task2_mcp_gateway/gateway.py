from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, Response

app = FastAPI(title="MCP Security Gateway")

DOWNSTREAM_URL = os.getenv("MCP_DOWNSTREAM_URL", "http://127.0.0.1:9000/mcp")

# Demo-only credentials. Production should validate signed bearer tokens/JWTs.
TOKEN_ROLES = {
    "admin-secret-token": "admin",
    "viewer-secret-token": "viewer",
}


def jsonrpc_error(
    request_id: Any,
    code: int,
    message: str,
    *,
    http_status: int = 200,
) -> JSONResponse:
    return JSONResponse(
        status_code=http_status,
        content={
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        },
    )


def extract_role(authorization: str | None) -> str | None:
    if not authorization:
        return None

    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token:
        return None

    return TOKEN_ROLES.get(token)


def authorize_payload(payload: Any, role: str | None) -> JSONResponse | None:
    """Return an error response when blocked; None means forwarding is allowed."""

    if not isinstance(payload, dict):
        return jsonrpc_error(None, -32600, "Invalid Request")

    request_id = payload.get("id")

    if payload.get("jsonrpc") != "2.0":
        return jsonrpc_error(request_id, -32600, "Invalid Request")

    method = payload.get("method")
    if not isinstance(method, str):
        return jsonrpc_error(request_id, -32600, "Invalid Request")

    if role is None:
        return jsonrpc_error(request_id, -32000, "Authentication Required")

    if method == "tools/call":
        params = payload.get("params")
        if not isinstance(params, dict):
            return jsonrpc_error(request_id, -32602, "Invalid Params")

        tool_name = params.get("name")
        if not isinstance(tool_name, str):
            return jsonrpc_error(request_id, -32602, "Invalid Params")

        if tool_name.startswith("admin_") and role != "admin":
            return jsonrpc_error(request_id, -32001, "Unauthorized Tool Call")

    return None


@app.post("/mcp")
async def gateway(
    request: Request,
    authorization: str | None = Header(default=None),
):
    try:
        payload = await request.json()
    except Exception:
        return jsonrpc_error(None, -32700, "Parse error")

    role = extract_role(authorization)
    blocked = authorize_payload(payload, role)
    if blocked is not None:
        # Authorization terminates here. No downstream side effect can occur.
        return blocked

    request_id = payload.get("id")

    try:
        async with httpx.AsyncClient() as client:
            downstream = await client.post(
                DOWNSTREAM_URL,
                json=payload,
                timeout=10.0,
            )
    except httpx.TimeoutException:
        return jsonrpc_error(request_id, -32002, "Downstream MCP server timeout")
    except httpx.RequestError:
        return jsonrpc_error(
            request_id,
            -32003,
            "Downstream MCP server unavailable",
        )

    excluded_headers = {"content-length", "transfer-encoding", "connection"}
    headers = {
        key: value
        for key, value in downstream.headers.items()
        if key.lower() not in excluded_headers
    }

    return Response(
        content=downstream.content,
        status_code=downstream.status_code,
        headers=headers,
        media_type=downstream.headers.get("content-type", "application/json"),
    )
