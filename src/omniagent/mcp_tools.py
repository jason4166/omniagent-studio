"""MCP metadata is untrusted; only a fixed local executable and tool/resource are allowed."""

import asyncio
import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import TextIO

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import AnyUrl

from omniagent.reliability import dependency_timeout
from omniagent.tooling import ToolBusinessError

PACKAGE_ROOT = str(Path(__file__).resolve().parent.parent)


@contextmanager
def error_sink() -> Iterator[TextIO]:
    # The fixed local server's diagnostic stream is not part of its tool result.
    with open(os.devnull, "w") as stream:
        yield stream


class MCPToolAdapter:
    def __init__(self, *, resource: bool = False, timeout_seconds: float = 10) -> None:
        self.resource = resource
        self.timeout_seconds = timeout_seconds

    async def exchange(self, arguments: dict[str, object] | None) -> object:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "omniagent.mcp_server"],
            env={"PYTHONPATH": PACKAGE_ROOT},
        )
        timeout = min(self.timeout_seconds, dependency_timeout.get() or self.timeout_seconds)
        with anyio.fail_after(timeout), error_sink() as errors:
            async with stdio_client(parameters, errlog=errors) as (reader, writer):
                async with ClientSession(
                    reader, writer, read_timeout_seconds=timedelta(seconds=timeout)
                ) as session:
                    initialized = await session.initialize()
                    tools = await session.list_tools()
                    resources = await session.list_resources()
                    names = [tool.name for tool in tools.tools]
                    if names != ["lookup_product"]:
                        raise ToolBusinessError("mcp_schema", "MCP tool catalog changed")
                    schema = tools.tools[0].inputSchema
                    properties = schema.get("properties", {})
                    if (
                        schema.get("type") != "object"
                        or schema.get("required") != ["sku"]
                        or not isinstance(properties, dict)
                        or set(properties) != {"sku"}
                        or properties["sku"].get("type") != "string"
                    ):
                        raise ToolBusinessError("mcp_schema", "MCP business schema changed")
                    if arguments is None:
                        return {
                            "protocol_version": initialized.protocolVersion,
                            "capabilities": initialized.capabilities.model_dump(mode="json"),
                            "tools": names,
                            "resources": [str(r.uri) for r in resources.resources],
                        }
                    if self.resource:
                        if arguments:
                            raise ToolBusinessError(
                                "invalid_arguments", "Resource accepts no parameters"
                            )
                        response = await session.read_resource(AnyUrl("catalog://policy"))
                        result: object = {
                            "text": "\n".join(
                                item.text for item in response.contents if hasattr(item, "text")
                            )
                        }
                    else:
                        response_tool = await session.call_tool("lookup_product", arguments)
                        if response_tool.isError:
                            raise ToolBusinessError("mcp_tool_error", "MCP tool failed")
                        result = response_tool.structuredContent
                    if len(json.dumps(result).encode()) > 16000:
                        raise ToolBusinessError("mcp_response_size", "MCP response exceeded limit")
                    return result

    def execute(self, arguments: dict[str, object]) -> object:
        try:
            return asyncio.run(self.exchange(arguments))
        except TimeoutError:
            raise
        except ToolBusinessError:
            raise
        except Exception as exc:
            known = find_business_error(exc)
            if known:
                raise known from exc
            raise ToolBusinessError("mcp_unavailable", "Local MCP service is unavailable") from exc

    def discover(self) -> object:
        return asyncio.run(self.exchange(None))


def find_business_error(exc: BaseException) -> ToolBusinessError | None:
    if isinstance(exc, ToolBusinessError):
        return exc
    if isinstance(exc, BaseExceptionGroup):
        for child in exc.exceptions:
            found = find_business_error(child)
            if found is not None:
                return found
    return None
