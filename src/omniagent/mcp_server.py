"""Fixed local MCP server using the locked v1 Python SDK and stdio transport."""

from mcp.server.fastmcp import FastMCP

from omniagent.demo_data import read_business
from omniagent.tooling import ToolBusinessError

server = FastMCP("OmniAgent synthetic catalog")


@server.tool()
def lookup_product(sku: str) -> dict[str, object]:
    """Read an original synthetic product record."""
    if len(sku) > 64:
        raise ValueError("Invalid product identifier")
    try:
        return read_business("lookup_product", {"sku": sku})
    except ToolBusinessError as exc:
        if exc.code != "not_found":
            raise
        return {
            "error": {
                "code": "record_not_found",
                "operation": "lookup_product",
                "arguments": {"sku": sku},
            }
        }


@server.resource("catalog://policy")
def catalog_policy() -> str:
    return "Synthetic catalog v1. Product warranty lasts 24 months. No real customer data."


if __name__ == "__main__":
    server.run(transport="stdio")
