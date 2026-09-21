"""Resolve conversational references against this session's execution evidence."""

import json
from collections.abc import Mapping, Sequence

from omniagent.context import HistoryMessage, OperationRecord
from omniagent.redaction import redact


def operation_record(
    result: dict[str, object],
    run_id: str | None,
    *,
    history: Sequence[HistoryMessage] = (),
) -> OperationRecord | None:
    if result.get("route") == "direct" and result.get("response_kind") == "operation_followup":
        reference = result.get("operation")
        if isinstance(reference, dict) and isinstance(reference.get("run_id"), str):
            # Follow-up payloads identify evidence; only retained server history supplies it.
            return referenced_operation(history, reference["run_id"])
        return None
    raw = result.get("tool_result")
    if not run_id or result.get("route") != "tool" or not isinstance(raw, dict):
        return None
    arguments = redact(result.get("arguments", {}))
    data = redact(raw.get("data"))
    # Large raw responses remain in the bounded event log; history stays compact.
    if len(json.dumps(arguments, ensure_ascii=False)) > 8000:
        arguments = {"content": "参数较长，请在会话详情中查看。"}
    if len(json.dumps(data, ensure_ascii=False)) > 12000:
        data = {"content": "返回内容较长，请在会话详情中查看。"}
    return OperationRecord.model_validate(
        {
            "run_id": run_id,
            "tool_name": result["tool_name"],
            "status": raw["status"],
            "arguments": arguments,
            "data": data,
        }
    )


def referenced_operation(
    history: Sequence[HistoryMessage], reference: str
) -> OperationRecord | None:
    return next(
        (
            item.operation
            for item in reversed(history)
            if item.role == "assistant"
            and item.operation is not None
            and item.operation.run_id == reference
        ),
        None,
    )


def operation_followup_text(
    record: OperationRecord, question: str, *, facts: Mapping[str, str] | None = None
) -> str:
    from omniagent.conversation import public_catalog
    from omniagent.tool_presentation import tool_result_text

    metadata = public_catalog()["tools"].get(record.tool_name, {})
    facts = facts or {}
    label = metadata.get("label", "这项操作")
    if question == "storage":
        return (
            "这条操作的会话和执行记录保存在本站服务器的 PostgreSQL 数据库中；"
            "涉及审批时，申请参数与审批信息也保存在这里。"
            "页面上的“执行记录”读取的是这些服务端数据。"
            "详细记录按会话保留期限清理。"
        )
    location = "可展开本条消息下方的“执行记录”，查看操作参数和返回信息；原操作消息下也保留了记录。"
    if record.status == "rejected":
        expired = isinstance(record.data, dict) and record.data.get("approval_status") == "expired"
        state = "审批已过期，这项操作未执行" if expired else "操作已拒绝，未执行"
        output = f"{label}：{state}。"
        if question == "business_effect":
            output += "本次操作没有执行，因此不会由它发出通知或触发业务变更。"
            effect = facts.get("business_effect", "")
            return output + (f"\n{effect}" if effect else "")
        return f"{output}\n{location}"
    if record.status == "failed":
        return f"{label}：执行失败，没有成功完成的确认。{location}"
    if question == "business_effect":
        return facts.get(
            "business_effect",
            "现有工具契约没有提供后续业务生效流程，无法确认怎样完成这一步。"
            "执行记录只能说明这次工具调用的返回结果，不能据此确认其他业务状态已经改变。",
        )
    result = tool_result_text(record.tool_name, record.data, arguments=record.arguments)
    if question == "meaning":
        explanation = (
            facts.get("result_note")
            or metadata.get("result_note")
            or (
                "当前执行记录只确认上面列出的返回值；未提供的含义、时间范围或其他状态无法据此确定。"
            )
        )
        return result if explanation in result else f"{result}\n{explanation}"
    confirmed = (
        isinstance(record.data, dict)
        and record.data.get("status") == "created"
        and record.data.get("tool") == record.tool_name
        and isinstance(record.data.get("operation_id"), str)
        and bool(record.data["operation_id"])
    )
    note = facts.get("completion_note", "") if confirmed else ""
    if question == "location":
        return f"{location}\n\n{result}" + (f"\n{note}" if note else "")
    if question == "next_step":
        next_step = facts.get(
            "next_step", "工具调用已结束；返回信息没有提供下一步操作，请先核对执行记录。"
        )
        return f"{result}\n{next_step}" + (f"\n{note}" if note else "")
    return f"{result}" + (f"\n{note}" if note else "") + f"\n{location}"
