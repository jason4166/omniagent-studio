"""Resolve conversational references against this session's execution evidence."""

import json

from omniagent.context import HistoryMessage, OperationRecord
from omniagent.redaction import redact


def operation_record(result: dict[str, object], run_id: str | None) -> OperationRecord | None:
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


def referenced_operation(history: list[HistoryMessage], reference: str) -> OperationRecord | None:
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


def operation_followup_text(record: OperationRecord, question: str) -> str:
    from omniagent.conversation import public_catalog
    from omniagent.tool_presentation import tool_result_text

    metadata = public_catalog()["tools"].get(record.tool_name, {})
    label = metadata.get("label", "这项操作")
    if record.status != "succeeded":
        state = "执行失败" if record.status == "failed" else "未执行"
        return f"{label}：{state}，没有成功完成的确认。可展开本条消息下方的“执行记录”查看详情。"
    result = tool_result_text(record.tool_name, record.data, arguments=record.arguments)
    note = metadata.get("completion_note", "")
    location = "可展开本条消息下方的“执行记录”，查看操作参数和返回信息；原操作消息下也保留了记录。"
    if question == "location":
        return f"{location}\n\n{result}" + (f"\n{note}" if note else "")
    if question == "next_step":
        next_step = metadata.get(
            "next_step", "本次操作已完成。你可以查看执行记录，或继续提出新的问题。"
        )
        return f"{result}\n{next_step}" + (f"\n{note}" if note else "")
    return f"{result}" + (f"\n{note}" if note else "") + f"\n{location}"
