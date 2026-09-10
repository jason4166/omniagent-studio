import pytest

from omniagent.connectors import catalog, validate_definition
from omniagent.errors import PlatformError
from omniagent.mcp_tools import MCPToolAdapter
from omniagent.tooling import ToolBusinessError, ToolRisk

pytestmark = pytest.mark.contract


def test_mcp_discovery_and_resource_are_real_local_protocol_calls() -> None:
    discovered = MCPToolAdapter().discover()
    assert discovered["tools"] == ["lookup_product"]
    assert "catalog://policy" in discovered["resources"]
    assert MCPToolAdapter(resource=True).execute({})["text"].startswith("Synthetic catalog v1")


@pytest.mark.parametrize("sku,price", [("P-100", 1200), ("P-200", 800)])
def test_mcp_structured_result(sku, price) -> None:
    result = MCPToolAdapter().execute({"sku": sku})
    assert result["sku"] == sku
    assert result["price"] == price


@pytest.mark.parametrize("arguments", [{}, {"sku": "missing"}, {"sku": "x" * 100}])
def test_mcp_invalid_business_requests_fail_safely(arguments) -> None:
    with pytest.raises(ToolBusinessError):
        MCPToolAdapter().execute(arguments)


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
