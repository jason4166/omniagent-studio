from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from omniagent import mcp_tools
from omniagent.connectors import catalog, validate_definition
from omniagent.errors import PlatformError
from omniagent.mcp_tools import MCPToolAdapter
from omniagent.tooling import ToolBusinessError, ToolRisk

pytestmark = pytest.mark.contract


def test_mcp_discovery_and_resource_are_real_local_protocol_calls() -> None:
    discovered = MCPToolAdapter().discover()
    assert discovered["tools"] == ["lookup_product"]
    assert "catalog://policy" in discovered["resources"]
    resource = MCPToolAdapter(resource=True).execute({})
    assert set(resource) == {"text"}
    assert "Atlas Desk（P-100）" in resource["text"]
    assert "Orbit Chair（P-200）" in resource["text"]
    assert "按产品编号查询名称、价格和币种" in resource["text"]
    assert "标准保修期为 24 个月" in resource["text"]
    assert "具体设备是否在保需按设备序列号查询" in resource["text"]


@pytest.mark.parametrize("sku,price", [("P-100", 1200), ("P-200", 800)])
def test_mcp_structured_result(sku, price) -> None:
    result = MCPToolAdapter().execute({"sku": sku})
    assert result["sku"] == sku
    assert result["price"] == price


@pytest.mark.parametrize("arguments", [{}, {"sku": "missing"}, {"sku": "x" * 100}])
def test_mcp_invalid_business_requests_fail_safely(arguments) -> None:
    with pytest.raises(ToolBusinessError) as found:
        MCPToolAdapter().execute(arguments)
    if arguments == {"sku": "missing"}:
        assert found.value.code == "record_not_found"


@pytest.mark.parametrize(
    "structured,is_error,expected",
    [
        (
            {
                "error": {
                    "code": "record_not_found",
                    "operation": "lookup_product",
                    "arguments": {"sku": "P-999"},
                }
            },
            False,
            "record_not_found",
        ),
        (
            {
                "error": {
                    "code": "record_not_found",
                    "operation": "lookup_product",
                    "arguments": {"sku": "P-100"},
                }
            },
            False,
            "mcp_tool_error",
        ),
        (
            {
                "error": {
                    "code": "record_not_found",
                    "operation": "other",
                    "arguments": {"sku": "P-999"},
                }
            },
            False,
            "mcp_tool_error",
        ),
        ({"error": "record_not_found"}, False, "mcp_tool_error"),
        (
            {
                "error": {
                    "code": "record_not_found",
                    "operation": "lookup_product",
                    "arguments": {"sku": "P-999"},
                }
            },
            True,
            "mcp_tool_error",
        ),
    ],
)
def test_mcp_missing_record_requires_exact_structured_business_contract(
    monkeypatch, structured, is_error, expected
):
    @asynccontextmanager
    async def transport(*_args, **_kwargs):
        yield None, None

    class Session:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def initialize(self):
            return SimpleNamespace()

        async def list_tools(self):
            return SimpleNamespace(
                tools=[
                    SimpleNamespace(
                        name="lookup_product",
                        inputSchema={
                            "type": "object",
                            "required": ["sku"],
                            "properties": {"sku": {"type": "string"}},
                        },
                    )
                ]
            )

        async def list_resources(self):
            return SimpleNamespace(resources=[])

        async def call_tool(self, *_args):
            return SimpleNamespace(isError=is_error, structuredContent=structured)

    monkeypatch.setattr(mcp_tools, "stdio_client", transport)
    monkeypatch.setattr(mcp_tools, "ClientSession", Session)
    with pytest.raises(ToolBusinessError) as found:
        MCPToolAdapter().execute({"sku": "P-999"})
    assert found.value.code == expected


def test_mcp_timeout_cannot_hang_the_runtime() -> None:
    with pytest.raises((TimeoutError, ToolBusinessError)):
        MCPToolAdapter(timeout_seconds=0.001).execute({"sku": "P-100"})


def test_remote_read_only_metadata_cannot_downgrade_local_risk() -> None:
    baselines = catalog("127.0.0.1", 18081)[0]
    definition = next(
        tool for tool in baselines if tool.name == "catalog.lookup_product"
    ).model_copy(deep=True)
    definition.risk = ToolRisk.HIGH
    definition.requires_approval = True
    validate_definition(definition, baselines)
    definition.adapter_id = "mcp:untrusted"
    with pytest.raises(PlatformError):
        validate_definition(definition, baselines)
