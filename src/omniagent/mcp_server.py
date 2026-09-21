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
    return (
        "产品目录包含 Atlas Desk（P-100）和 Orbit Chair（P-200）。"
        "可按产品编号查询名称、价格和币种。"
        "两款产品的标准保修期为 24 个月，具体设备是否在保需按设备序列号查询。"
    )


if __name__ == "__main__":
    server.run(transport="stdio")
