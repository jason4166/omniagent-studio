"""Administrator-owned adapter catalog, independent from model tool proposals."""

from copy import copy

from omniagent.demo_data import business_schemas
from omniagent.errors import ErrorCode, PlatformError
from omniagent.http_tools import HTTPConnectorConfig, HTTPToolAdapter
from omniagent.mcp_tools import MCPToolAdapter
from omniagent.postgres_repositories import SqlAlchemyToolDefinitionRepository
from omniagent.session_store import SessionStore
from omniagent.tool_registry import ToolAdapter, ToolRegistry
from omniagent.tooling import ToolDefinition, ToolRisk

_PRODUCT_LOOKUP_DESCRIPTION = (
    "Read a product catalog record by sku. Returns only: sku, name, price, currency. "
    "It does not return warranty terms, device coverage, setup instructions or other policies. "
    "Use authorized knowledge for policy or how-to questions, even when a product ID is given."
)
_BUSINESS_DESCRIPTIONS = {
    "lookup_product": _PRODUCT_LOOKUP_DESCRIPTION,
    "check_warranty": (
        "Read the warranty record of a specific device by serial_number. "
        "Returns only: serial_number, covered, months. "
        "A product sku is not a device serial number. "
        "General warranty duration, terms and exclusions come from authorized knowledge; "
        "do not request a serial number just to answer a general policy question."
    ),
    "lookup_customer": (
        "Read a customer record by customer_id. Returns only: customer_id, name, tier. "
        "Use authorized knowledge for sales policies; this record contains no policy terms."
    ),
    "create_followup": (
        "Propose creating a follow-up record with the supplied customer_id and note. "
        "Requires server-enforced approval before writing. "
        "Returns only: operation_id, tool, status."
    ),
    "request_discount": (
        "Propose a discount request with the supplied customer_id, percent and reason. "
        "Requires server-enforced approval before writing; request creation does not grant "
        "the discount. Returns only: operation_id, tool, status."
    ),
}
PREVIOUS_TOOL_DESCRIPTIONS = {
    name: f"Synthetic business operation: {name}" for name in _BUSINESS_DESCRIPTIONS
} | {"catalog.lookup_product": "", "catalog.resource": ""}


def catalog(host: str, port: int) -> tuple[list[ToolDefinition], dict[str, HTTPConnectorConfig]]:
    definitions: list[ToolDefinition] = []
    connectors: dict[str, HTTPConnectorConfig] = {}
    for name, schema in business_schemas().items():
        write = name in {"create_followup", "request_discount"}
        definitions.append(
            ToolDefinition(
                name=name,
                description=_BUSINESS_DESCRIPTIONS[name],
                adapter_id=f"http:{name}",
                parameters_schema=schema,
                effect="write" if write else "read",
                risk=ToolRisk.HIGH
                if name == "request_discount"
                else ToolRisk.MEDIUM
                if write
                else ToolRisk.LOW,
                allowed_roles=("admin", "member"),
                requires_approval=write,
            )
        )
        connectors[name] = HTTPConnectorConfig(
            host=host,
            port=port,
            path=f"/tools/{name}",
            method="POST" if write else "GET",
            parameters_schema=schema,
            output_schema={"type": "object"},
        )
    definitions.extend(
        [
            ToolDefinition(
                name="catalog.lookup_product",
                description=_PRODUCT_LOOKUP_DESCRIPTION + " Accessed through MCP.",
                adapter_id="mcp:lookup_product",
                parameters_schema=business_schemas()["lookup_product"],
                risk=ToolRisk.LOW,
                allowed_roles=("admin", "member"),
                requires_approval=False,
                timeout_seconds=10,
            ),
            ToolDefinition(
                name="catalog.resource",
                description=(
                    "Read the fixed MCP catalog://policy resource without arguments. "
                    "Returns only: text. It contains a synthetic catalog notice and a brief "
                    "general warranty statement, not product records or device coverage. "
                    "Use authorized knowledge for cited policy answers unless the user "
                    "explicitly requests this MCP resource."
                ),
                adapter_id="mcp:resource",
                risk=ToolRisk.LOW,
                allowed_roles=("admin", "member"),
                requires_approval=False,
                timeout_seconds=10,
            ),
        ]
    )
    return definitions, connectors


def build_adapters(host: str, port: int) -> dict[str, ToolAdapter]:
    _, configs = catalog(host, port)
    adapters: dict[str, ToolAdapter] = {
        f"http:{name}": HTTPToolAdapter(
            config, approved_origins=frozenset({(host, port)}), local_mock_hosts=frozenset({host})
        )
        for name, config in configs.items()
    }
    adapters["mcp:lookup_product"] = MCPToolAdapter()
    adapters["mcp:resource"] = MCPToolAdapter(resource=True)
    return adapters


def validate_definition(definition: ToolDefinition, baselines: list[ToolDefinition]) -> None:
    baseline = next((item for item in baselines if item.name == definition.name), None)
    if (
        baseline is None
        or definition.adapter_id != baseline.adapter_id
        or definition.parameters_schema != baseline.parameters_schema
        or definition.output_schema != baseline.output_schema
        or definition.effect != baseline.effect
        or (baseline.requires_approval and not definition.requires_approval)
        or set(definition.allowed_roles) - set(baseline.allowed_roles)
    ):
        raise PlatformError(ErrorCode.VALIDATION, "Tool must match an approved adapter contract")
    ranks = {ToolRisk.LOW: 0, ToolRisk.MEDIUM: 1, ToolRisk.HIGH: 2}
    if ranks[definition.risk] < ranks[baseline.risk]:
        raise PlatformError(ErrorCode.VALIDATION, "Configured risk cannot downgrade adapter risk")


def build_registry(
    store: SessionStore, adapters: dict[str, ToolAdapter], baselines: list[ToolDefinition]
) -> ToolRegistry:
    from omniagent.conversation import public_catalog

    registry = ToolRegistry()
    with store.factory() as db:
        for definition in SqlAlchemyToolDefinitionRepository(db).list_all():
            if definition.adapter_id not in adapters:
                continue
            validate_definition(definition, baselines)
            adapter = copy(adapters[definition.adapter_id])
            if isinstance(adapter, HTTPToolAdapter):
                adapter.config = adapter.config.model_copy(
                    update={"timeout_seconds": definition.timeout_seconds}
                )
            elif isinstance(adapter, MCPToolAdapter):
                adapter.timeout_seconds = definition.timeout_seconds
            presentation = public_catalog()["tools"].get(definition.name, {})
            facts = (
                {
                    key: presentation[key]
                    for key in ("effect_summary", "completion_note", "business_effect", "next_step")
                    if key in presentation
                }
                if presentation.get("adapter_id") == definition.adapter_id
                else {}
            )
            registry.register(definition, adapter, operation_facts=facts)
    return registry
