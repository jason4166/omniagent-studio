"""Bounded public help, separate from evidence-backed business answers."""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from omniagent.approvals import needs_approval
from omniagent.identity import DevUserContext
from omniagent.profiles import AgentProfile
from omniagent.redaction import redact_text
from omniagent.tool_registry import ToolRegistry

ConversationIntent = Literal["greeting", "capabilities", "thanks"]


@lru_cache(maxsize=1)
def public_catalog() -> dict[str, dict[str, dict[str, str]]]:
    value: dict[str, dict[str, dict[str, str]]] = json.loads(
        Path(__file__).with_name("conversation_catalog.json").read_text(encoding="utf-8")
    )
    return value


@dataclass(frozen=True)
class Capability:
    label: str
    detail: str
    example: str | None = None


def available_capabilities(
    profile: AgentProfile, actor: DevUserContext, registry: ToolRegistry
) -> list[Capability]:
    actor.authorize_profile(profile)
    catalog = public_catalog()
    result: list[Capability] = []
    for identifier in profile.knowledge_base_ids:
        metadata = catalog["knowledge"].get(identifier, {})
        label = metadata.get("label", "当前知识库中的资料")
        capability = Capability("查询" + label, "可查看引用原文", metadata.get("example"))
        if capability not in result:
            result.append(capability)
    for definition in registry.definitions():
        if (
            definition.name not in profile.tool_ids
            or not definition.enabled
            or actor.permission_role not in definition.allowed_roles
        ):
            continue
        metadata = catalog["tools"].get(definition.name, {})
        label = redact_text(metadata.get("label") or definition.description or definition.name)
        detail = (
            "先生成提案，经人工审批后执行" if needs_approval(definition, profile) else "只读查询"
        )
        result.append(Capability(label[:140], detail, metadata.get("example")))
    return result


def conversation_reply(
    intent: ConversationIntent, profile: AgentProfile, actor: DevUserContext, registry: ToolRegistry
) -> str:
    capabilities = available_capabilities(profile, actor, registry)
    name = redact_text(profile.name)
    if intent == "thanks":
        return "不客气！还有需要查询的内容，随时告诉我。"
    if not capabilities:
        return (
            f"你好，我是{name}。当前账号下暂时没有可用的知识问答或业务操作，"
            "请联系管理员配置权限和资料。"
        )
    example = next((item.example for item in capabilities if item.example), None)
    if intent == "greeting":
        labels = "、".join(item.label for item in capabilities[:3])
        text = f"你好！我是{name}，可以帮你{labels}。"
    else:
        text = f"我是{name}，可以帮你：\n\n" + "\n".join(
            f"• {item.label}：{item.detail}。" for item in capabilities[:8]
        )
        if len(capabilities) > 8:
            text += "\n这里只列出部分能力；你可以继续描述具体需求。"
    if example:
        text += f"\n\n你可以先问：“{example}”"
    if intent == "greeting" and any("审批" in item.detail for item in capabilities):
        text += "\n涉及需要审批的操作，我会先给出提案，等待确认后再执行。"
    return text


def clarification_fallback(
    profile: AgentProfile, actor: DevUserContext, registry: ToolRegistry
) -> str:
    capabilities = available_capabilities(profile, actor, registry)
    example = next((item.example for item in capabilities if item.example), None)
    text = "请告诉我你想查询的具体问题或要办理的操作；涉及某条业务记录时，请提供对应编号。"
    return text + (f"例如：“{example}”" if example else "")
