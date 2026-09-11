"""Render authorized tool data using trusted labels, without another model call."""

import json

from omniagent.conversation import public_catalog


def tool_result_text(tool_name: str, data: object) -> str:
    catalog = public_catalog()
    title = catalog["tools"].get(tool_name, {}).get("label", "工具查询")
    if data is None or data == {} or data == []:
        return f"{title}：没有返回可展示的记录。"
    if not isinstance(data, dict):
        return f"{title}\n{_value(data)}"
    fields = catalog.get("result_fields", {})
    lines = [title]
    for key, value in data.items():
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
    return "\n".join(lines)


def _value(value: object) -> str:
    if value is None:
        return "未提供"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)
