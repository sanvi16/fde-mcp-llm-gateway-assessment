"""Task 1: strict MCP stdio server.

Important: never print() from this process. stdout is the MCP transport.
Application logs are configured to stderr only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

import mcp.server.stdio
from mcp import MCPError
from mcp.server import Server, ServerRequestContext
from mcp.types import (
    INVALID_PARAMS,
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError


logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("customer-mcp")


class GetCustomerRecordInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    customer_id: str = Field(
        pattern=r"^CUST-\d{5}$",
        description="Customer ID formatted as CUST-XXXXX",
    )


class TriggerRefundInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    customer_id: str = Field(pattern=r"^CUST-\d{5}$")
    amount: float = Field(gt=0)
    reason: str = Field(min_length=10)


CUSTOMERS: dict[str, dict[str, Any]] = {
    "CUST-12345": {
        "customer_id": "CUST-12345",
        "name": "Alice Example",
        "status": "active",
        "balance": 125.50,
    },
    "CUST-54321": {
        "customer_id": "CUST-54321",
        "name": "Bob Example",
        "status": "active",
        "balance": 42.00,
    },
}


GET_CUSTOMER_TOOL = Tool(
    name="get_customer_record",
    description="Retrieve a customer record by customer ID.",
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "customer_id": {
                "type": "string",
                "pattern": r"^CUST-\d{5}$",
                "description": "Customer identifier in CUST-XXXXX format",
            }
        },
        "required": ["customer_id"],
    },
)

TRIGGER_REFUND_TOOL = Tool(
    name="trigger_refund",
    description="Issue a refund for a customer.",
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "customer_id": {
                "type": "string",
                "pattern": r"^CUST-\d{5}$",
            },
            "amount": {
                "type": "number",
                "exclusiveMinimum": 0,
            },
            "reason": {
                "type": "string",
                "minLength": 10,
            },
        },
        "required": ["customer_id", "amount", "reason"],
    },
)


def _validation_error(exc: ValidationError) -> MCPError:
    """Map Pydantic validation failures to JSON-RPC -32602."""

    details = [
        {
            "field": ".".join(str(part) for part in err["loc"]),
            "message": err["msg"],
        }
        for err in exc.errors()
    ]

    return MCPError(
        INVALID_PARAMS,
        "Invalid tool arguments",
        data={"errors": details},
    )


def validate_get_customer(arguments: dict[str, Any]) -> GetCustomerRecordInput:
    try:
        return GetCustomerRecordInput.model_validate(arguments)
    except ValidationError as exc:
        raise _validation_error(exc) from exc


def validate_refund(arguments: dict[str, Any]) -> TriggerRefundInput:
    try:
        return TriggerRefundInput.model_validate(arguments)
    except ValidationError as exc:
        raise _validation_error(exc) from exc


async def list_tools(
    ctx: ServerRequestContext,
    params: PaginatedRequestParams | None,
) -> ListToolsResult:
    return ListToolsResult(tools=[GET_CUSTOMER_TOOL, TRIGGER_REFUND_TOOL])


async def call_tool(
    ctx: ServerRequestContext,
    params: CallToolRequestParams,
) -> CallToolResult:
    arguments = params.arguments or {}

    logger.info(
        "tools/call name=%s request_id=%s",
        params.name,
        ctx.request_id,
    )

    if params.name == "get_customer_record":
        validated = validate_get_customer(arguments)
        record = CUSTOMERS.get(validated.customer_id)

        if record is None:
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=f"Customer {validated.customer_id} was not found.",
                    )
                ],
                is_error=True,
            )

        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(record))],
            structured_content=record,
        )

    if params.name == "trigger_refund":
        validated = validate_refund(arguments)

        if validated.customer_id not in CUSTOMERS:
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=f"Customer {validated.customer_id} was not found.",
                    )
                ],
                is_error=True,
            )

        result = {
            "status": "accepted",
            "customer_id": validated.customer_id,
            "amount": validated.amount,
            "reason": validated.reason,
        }

        logger.info(
            "refund accepted customer_id=%s amount=%.2f",
            validated.customer_id,
            validated.amount,
        )

        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result))],
            structured_content=result,
        )

    raise MCPError(INVALID_PARAMS, f"Unknown tool: {params.name}")


server = Server(
    "customer-service",
    version="1.0.0",
    on_list_tools=list_tools,
    on_call_tool=call_tool,
)


async def main() -> None:
    logger.info("Starting customer MCP server over stdio")

    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
