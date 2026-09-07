import asyncio
import sys

from mcp import Client, MCPError, StdioServerParameters


async def main():
    server = StdioServerParameters(
        command=sys.executable,
        args=["task1_mcp_server/server.py"],
    )

    async with Client(server) as client:
        print("\n1. Connected to MCP server")
        print("Protocol version:", client.protocol_version)

        print("\n2. Listing tools")
        tools_result = await client.list_tools()

        for tool in tools_result.tools:
            print(" -", tool.name)

        print("\n3. Valid get_customer_record call")
        result = await client.call_tool(
            "get_customer_record",
            {
                "customer_id": "CUST-12345",
            },
        )

        print(result.content)

        print("\n4. Invalid customer ID")
        try:
            await client.call_tool(
                "get_customer_record",
                {
                    "customer_id": "12345",
                },
            )
        except MCPError as exc:
            print("Rejected correctly")
            print("JSON-RPC code:", exc.error.code)
            print("Message:", exc.error.message)

        print("\n5. Valid refund")
        result = await client.call_tool(
            "trigger_refund",
            {
                "customer_id": "CUST-12345",
                "amount": 25.50,
                "reason": "Duplicate payment",
            },
        )

        print(result.content)

        print("\n6. Negative refund amount")
        try:
            await client.call_tool(
                "trigger_refund",
                {
                    "customer_id": "CUST-12345",
                    "amount": -10.0,
                    "reason": "Duplicate payment",
                },
            )
        except MCPError as exc:
            print("Rejected correctly")
            print("JSON-RPC code:", exc.error.code)
            print("Message:", exc.error.message)


if __name__ == "__main__":
    asyncio.run(main())