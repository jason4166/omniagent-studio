"""Render argument corrections from authorized schemas, never model-supplied rules."""

import json
from itertools import islice

from jsonschema import Draft202012Validator

from omniagent.conversation import public_catalog
from omniagent.redaction import redact_text


def parameter_labels(schema: dict[str, object]) -> dict[str, str]:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return {}
    fields = public_catalog().get("result_fields", {})
    return {
        name: fields[name]["label"]
        for name in properties
        if name in fields and fields[name].get("label")
    }


def parameter_constraints(schema: object) -> str:
    if not isinstance(schema, dict):
        return "请核对后重新提供"
    kinds = {
        "integer": "整数",
        "number": "数字",
        "boolean": "是或否",
        "array": "列表",
        "object": "完整信息",
    }
    parts = [kinds.get(str(schema.get("type")), "")]
    lower, upper = schema.get("minimum"), schema.get("maximum")
    if isinstance(lower, (int, float)) and isinstance(upper, (int, float)):
        parts.append(f"范围 {lower} 到 {upper}（含边界）")
    else:
        if isinstance(lower, (int, float)):
            parts.append(f"不小于 {lower}")
        if isinstance(upper, (int, float)):
            parts.append(f"不大于 {upper}")
    for key, label in (
        ("exclusiveMinimum", "大于"),
        ("exclusiveMaximum", "小于"),
        ("multipleOf", "须为以下数值的整数倍："),
    ):
        value = schema.get(key)
        if isinstance(value, (int, float)):
            parts.append(f"{label} {value}")
    for key, label, unit in (
        ("minLength", "至少", "个字符"),
        ("maxLength", "最多", "个字符"),
        ("minItems", "至少", "项"),
        ("maxItems", "最多", "项"),
    ):
        value = schema.get(key)
        if isinstance(value, int) and not (key == "minLength" and value <= 1):
            parts.append(f"{label} {value} {unit}")
    choices = schema.get("enum")
    if isinstance(choices, list) and choices:
        encoded = json.dumps(choices, ensure_ascii=False)
        if len(encoded) <= 180:
            parts.append("可选值：" + redact_text(encoded))
    if "const" in schema:
        encoded = json.dumps(schema["const"], ensure_ascii=False)
        if len(encoded) <= 100:
            parts.append("须为：" + redact_text(encoded))
    return "，".join(part for part in parts if part) or "请填写有效内容"


def argument_clarification(schema: dict[str, object], arguments: dict[str, object]) -> str | None:
    errors = list(islice(Draft202012Validator(schema).iter_errors(arguments), 8))
    if not errors:
        return None
    properties = schema.get("properties")
    properties = properties if isinstance(properties, dict) else {}
    labels = parameter_labels(schema)
    issues: dict[str, str] = {}
    for error in errors:
        path = list(error.absolute_path)
        if not path and error.validator == "required":
            required = error.validator_value
            names = (
                [name for name in required if name not in arguments]
                if isinstance(required, list)
                else []
            )
        else:
            names = [path[0]] if path else []
        if not names:
            issues["信息格式"] = "请只提供本操作要求的信息，并核对格式"
        for name in names:
            field_schema = properties.get(name, {})
            title = field_schema.get("title") if isinstance(field_schema, dict) else None
            label = labels.get(name) or (title if isinstance(title, str) else "所填信息")
            label = redact_text(label)[:80]
            issue = parameter_constraints(field_schema)
            if path and (
                len(path) > 1 or error.validator in {"pattern", "format", "anyOf", "oneOf"}
            ):
                issue += "，请核对具体内容和格式"
            issues[label] = issue
    lines = [f"{label}：{constraint[:400]}" for label, constraint in list(issues.items())[:8]]
    return "请补充或调整以下信息：\n" + "\n".join(lines) + "\n补充或调整后即可继续。"
