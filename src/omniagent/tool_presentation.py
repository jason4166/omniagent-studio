"""Render authorized tool data using trusted labels, without another model call."""

import json
from collections.abc import Mapping

from omniagent.conversation import public_catalog
from omniagent.redaction import redact_text


def tool_error_text(
    tool_name: str, error_code: str | None, *, arguments: Mapping[str, object] | None = None
) -> str:
    catalog = public_catalog()
    field = catalog["tools"].get(tool_name, {}).get("record_identifier")
    if error_code == "record_not_found" and field:
        label = catalog["result_fields"][field]["label"]
        identifier = (arguments or {}).get(field)
        reference = f"{label}“{redact_text(str(identifier))[:64]}”" if identifier else label
        return f"未找到与{reference}对应的记录。请核对{label}后重新提供。"
    return "未能完成这项查询或操作，请检查输入的信息。"


def tool_result_text(
    tool_name: str, data: object, *, arguments: Mapping[str, object] | None = None
) -> str:
    catalog = public_catalog()
    title = catalog["tools"].get(tool_name, {}).get("label", "工具查询")
    if data is None or data == {} or data == []:
        return f"{title}：没有返回可展示的记录。"
    if not isinstance(data, dict):
        return f"{title}\n{_value(data)}"
    fields = catalog.get("result_fields", {})
    lines = [title]
    values = {**(arguments or {}), **data}
    for key, value in values.items():
        if arguments is not None and key == "tool":
            continue
        metadata = fields.get(str(key), {})
        if metadata.get("display") == "details":
            continue
        label = metadata.get("label", str(key))
        text = _value(value)
        if isinstance(value, (str, bool)):
            code = str(value).lower() if isinstance(value, bool) else value
            text = metadata.get(code, text)
        if key == "tool" and isinstance(value, str):
            text = catalog["tools"].get(value, {}).get("label", text)
        lines.append(f"{label}：{text}")
    if len(lines) == 1:
        lines.append("已返回记录，可在操作详情中查看。")
    note = catalog["tools"].get(tool_name, {}).get("result_note")
    if note and "months" in data:
        lines.append(note)
    return "\n".join(lines)


def _value(value: object) -> str:
    if value is None:
        return "未提供"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)
