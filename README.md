# FDE Assessment — MCP & LLM Gateways

This repository contains my implementation of the FDE technical assessment focused on MCP servers, MCP security gateways, streaming LLM guardrails, and token-aware model routing.

## Overview

The repository contains four independent tasks:

1. **Custom MCP Server** — MCP tools with strict input validation and stdio transport.
2. **MCP Security Gateway** — JSON-RPC proxy with role-based tool authorization.
3. **LLM Streaming Guardrail** — streaming proxy with real-time PII redaction.
4. **Rate Limiting & Model Fallback Router** — tenant-level token rate limiting with SQLite and automatic provider fallback.

The implementation uses Python 3.11 and includes automated tests for all four tasks.

---

## Repository Structure

```text
fde-mcp-llm-assessment/
├── .github/
│   └── workflows/
│       └── tests.yml
├── task1_mcp_server/
│   ├── __init__.py
│   ├── server.py
│   ├── manual_test.py
│   └── test_task1.py
├── task2_mcp_gateway/
│   ├── __init__.py
│   ├── gateway.py
│   ├── mock_downstream.py
│   └── test_task2.py
├── task3_llm_guardrail/
│   ├── __init__.py
│   ├── gateway.py
│   ├── mock_provider.py
│   ├── redactor.py
│   └── test_task3.py
├── task4_model_router/
│   ├── __init__.py
│   ├── gateway.py
│   ├── rate_limiter.py
│   ├── router.py
│   ├── primary_provider.py
│   ├── backup_provider.py
│   └── test_task4.py
├── .gitignore
├── pytest.ini
├── requirements.txt
└── README.md
```

---

# Setup

## Requirements

- Python 3.11+
- pip

Create and activate a virtual environment:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

# Automated Tests

Run the complete test suite from the repository root:

```bash
pytest -v
```

The test suite covers validation, authorization, PII redaction, chunk-boundary handling, rate limiting, concurrency, provider fallback, and error handling.

---

# Task 1 — Custom MCP Server

## Purpose

Implements an MCP server exposing two tools:

- `get_customer_record`
- `trigger_refund`

The server uses the MCP Python SDK low-level `Server` API to provide explicit control over tool schemas, validation behavior, JSON-RPC errors, and stdio transport.

## Validation

`get_customer_record(customer_id)` requires a customer ID matching:

```text
CUST-XXXXX
```

where `XXXXX` contains exactly five digits.

`trigger_refund(customer_id, amount, reason)` requires:

- Valid `CUST-XXXXX` customer ID
- Positive floating-point amount
- Reason containing at least 10 characters

Pydantic models use strict validation and reject unexpected fields.

Invalid tool arguments are returned using the standard JSON-RPC invalid-params error code:

```text
-32602
```

## Transport

The server communicates over MCP stdio transport.

Application logging is directed to `stderr` so that `stdout` remains reserved for MCP protocol communication.

## Run Directly

From the repository root:

```bash
python task1_mcp_server/server.py
```

The process waits for MCP messages over stdin.

## End-to-End stdio Verification

A manual MCP client is included:

```bash
python task1_mcp_server/manual_test.py
```

The client launches the MCP server as a subprocess using `StdioServerParameters` and communicates with it through the actual stdio transport.

The manual test demonstrates:

- MCP protocol initialization
- `tools/list`
- Valid `get_customer_record`
- Invalid customer ID rejection with `-32602`
- Valid `trigger_refund`
- Negative refund amount rejection with `-32602`

The low-level MCP `Server` is intentionally used for precise protocol and validation control. The MCP CLI `mcp dev` command targets the high-level `MCPServer`, so the included client is used for end-to-end testing of this low-level stdio implementation.

---

# Task 2 — MCP Security Gateway Proxy

## Purpose

Implements an HTTP/JSON-RPC reverse proxy between an MCP client and a downstream MCP service.

The gateway enforces role-based authorization before forwarding tool calls.

## Demo Authentication

The implementation includes two demonstration bearer tokens:

```text
viewer-secret-token → viewer
admin-secret-token  → admin
```

These are intentionally local assessment credentials and are not intended for production use.

## Authorization Policy

`tools/list` requests are forwarded transparently.

For `tools/call`:

- Tools whose names begin with `admin_` require the `admin` role.
- Other tools may be invoked by authenticated users.
- Unauthorized `admin_*` calls are rejected at the gateway before the downstream service is contacted.

Unauthorized tool calls return:

```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32001,
    "message": "Unauthorized Tool Call"
  }
}
```

## Run

Start the mock downstream MCP service:

```bash
uvicorn task2_mcp_gateway.mock_downstream:app --port 9000
```

In another terminal, start the gateway:

```bash
uvicorn task2_mcp_gateway.gateway:app --port 8000
```

## Example — Viewer Blocked From Admin Tool

```bash
curl -s -X POST http://127.0.0.1:8000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer viewer-secret-token' \
  -d '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"tools/call",
    "params":{
      "name":"admin_reset_key",
      "arguments":{}
    }
  }'
```

Expected JSON-RPC error:

```text
-32001 Unauthorized Tool Call
```

## Example — Admin Allowed

Use:

```text
Authorization: Bearer admin-secret-token
```

The `admin_reset_key` request is then forwarded to the downstream MCP service.

---

# Task 3 — LLM Streaming PII Guardrail

## Purpose

Implements a streaming LLM gateway that intercepts provider output and redacts sensitive information before it reaches the client.

The guardrail detects:

- Email addresses
- U.S. Social Security numbers
- Credit card numbers

Credit-card candidates are additionally checked using the Luhn algorithm.

Detected PII is replaced with:

```text
[REDACTED]
```

## Streaming Design

The gateway does not wait for the complete LLM response before processing output.

A bounded carry buffer is maintained so that PII patterns split across provider chunks can still be detected before sensitive bytes are released.

The gateway currently uses:

```text
carry_size = 64
```

This keeps buffering bounded while allowing the demonstration stream to remain responsive.

The mock provider deliberately splits sensitive values across multiple chunks to exercise chunk-boundary handling.

## Run

Start the mock provider:

```bash
uvicorn task3_llm_guardrail.mock_provider:app --port 9100
```

In another terminal, start the guardrail gateway:

```bash
uvicorn task3_llm_guardrail.gateway:app --port 8100
```

Then stream a request:

```bash
curl -N -X POST http://127.0.0.1:8100/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"demo"}],"stream":true}'
```

The client receives incremental SSE output while sensitive values are replaced with `[REDACTED]`.

For example, the resulting content is equivalent to:

```text
Hello. Email me at [REDACTED]. My SSN is [REDACTED]. Test card: [REDACTED]. Thanks.
```

The raw email, SSN, and credit-card values are not released to the client.

---

# Task 4 — Rate Limiting & Model Fallback Router

## Purpose

Implements a tenant-aware LLM gateway with:

- 50,000-token-per-minute tenant limit
- Sliding 60-second usage window
- SQLite persistence
- Concurrency-safe reservations
- Primary model routing
- Automatic backup-provider fallback
- Sanitized client-facing errors

## Token Rate Limiting

The API key acts as the tenant identifier.

Before a request is routed, the gateway estimates its token requirement and attempts to reserve that usage.

The implementation uses a conservative token estimate based on request text length plus requested output tokens.

SQLite stores usage on disk.

Expired entries are removed from the rolling window before usage is calculated.

The check-and-reserve operation uses a SQLite transaction with:

```text
BEGIN IMMEDIATE
```

This prevents concurrent requests from independently passing the limit check and collectively exceeding the configured tenant limit.

The default limit is:

```text
50,000 tokens / 60 seconds / tenant
```

## Provider Routing

Normal requests are sent to the primary provider.

The gateway falls back to the backup provider only when:

- Primary returns HTTP `429`
- Primary exceeds the configured 3-second timeout

Other provider failures, such as HTTP `500`, do not trigger fallback.

## Error Sanitization

Internal provider failures are logged internally.

Clients receive sanitized gateway errors without raw stack traces, internal exception details, or provider implementation information.

## Run

Start the primary provider:

```bash
uvicorn task4_model_router.primary_provider:app --port 9200
```

Start the backup provider:

```bash
uvicorn task4_model_router.backup_provider:app --port 9300
```

Start the gateway:

```bash
uvicorn task4_model_router.gateway:app --port 8200
```

## Normal Primary Request

```bash
curl -s -X POST http://127.0.0.1:8200/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: tenant-primary-test' \
  -d '{
    "messages":[{"role":"user","content":"hello"}],
    "max_tokens":100
  }'
```

The response includes:

```json
"_gateway": {
  "route": "primary"
}
```

## Primary 429 Fallback

For the included mock provider, `_mock_primary` can be used to simulate failures:

```json
"_mock_primary": "429"
```

A primary HTTP `429` causes the request to be retried through the backup provider.

The response reports:

```json
"_gateway": {
  "route": "backup"
}
```

## Primary Timeout Fallback

Using:

```json
"_mock_primary": "timeout"
```

causes the mock primary provider to exceed the gateway timeout.

After the 3-second primary timeout, the request is routed to the backup provider.

## Non-Retryable Failure

Using:

```json
"_mock_primary": "500"
```

simulates an HTTP `500` response.

The gateway does not contact the backup provider for this failure and instead returns a sanitized error such as:

```json
{
  "error": {
    "code": "UPSTREAM_UNAVAILABLE",
    "message": "The requested model is temporarily unavailable.",
    "request_id": "req_..."
  }
}
```

## Rate-Limit Example

A request reserving approximately 49,000 tokens can succeed for a fresh tenant.

An immediate request for another 2,000 tokens from that same tenant exceeds the 50,000-token rolling-window limit and returns:

```json
{
  "error": {
    "code": "TOKEN_RATE_LIMIT_EXCEEDED",
    "message": "Tenant token rate limit exceeded.",
    "request_id": "req_..."
  }
}
```

---

# Design Decisions

## MCP Protocol Control

Task 1 uses the low-level MCP `Server` API because the assessment requires precise schemas, validation behavior, JSON-RPC errors, and transport control.

## Authorization Before Forwarding

Task 2 performs authorization before making a downstream request. This ensures an unauthorized tool invocation cannot create a downstream side effect.

## Bounded Streaming Inspection

Task 3 keeps only a bounded amount of pending text rather than buffering an entire model completion. This allows sensitive patterns crossing provider chunk boundaries to be detected while preserving streaming behavior.

## Transactional Rate Limiting

Task 4 performs the tenant usage check and reservation in the same SQLite transaction, preventing concurrent requests from bypassing the token limit.

## Controlled Fallback

Fallback is intentionally limited to rate limiting and timeout conditions. Other upstream failures are surfaced as sanitized gateway errors instead of automatically retrying another provider.

---

# Testing

Run all tests:

```bash
pytest -v
```

The repository also includes a GitHub Actions workflow that installs the dependencies and runs the automated test suite on pushes and pull requests.

---

# Production Considerations

This repository is intentionally scoped to the assessment and uses local mock providers and demonstration credentials.

For production deployment, I would additionally consider:

- External secret management and real authentication/authorization
- Distributed rate limiting for horizontally scaled gateways
- Provider-specific tokenization instead of approximate token estimation
- Reservation reconciliation using actual provider usage
- Structured observability, metrics, and tracing
- Configurable PII policies and additional detectors
- TLS and network-level service authentication
- Persistent production-grade provider and tenant configuration