"""Original synthetic business data, licensed CC0; no real customer information."""

from omniagent.tooling import ToolBusinessError

PRODUCTS: dict[str, dict[str, object]] = {
    "P-100": {"sku": "P-100", "name": "Atlas Desk", "price": 1200, "currency": "CNY"},
    "P-200": {"sku": "P-200", "name": "Orbit Chair", "price": 800, "currency": "CNY"},
}
WARRANTIES: dict[str, dict[str, object]] = {
    "SN-100": {"serial_number": "SN-100", "covered": True, "months": 24},
    "SN-200": {"serial_number": "SN-200", "covered": False, "months": 0},
}
CUSTOMERS: dict[str, dict[str, object]] = {
    "C-100": {"customer_id": "C-100", "name": "Fictional Acorn Lab", "tier": "standard"},
    "C-200": {"customer_id": "C-200", "name": "Fictional Harbor Studio", "tier": "partner"},
}


def read_business(operation: str, arguments: dict[str, object]) -> dict[str, object]:
    catalog = {
        "lookup_product": (PRODUCTS, "sku"),
        "check_warranty": (WARRANTIES, "serial_number"),
        "lookup_customer": (CUSTOMERS, "customer_id"),
    }
    if operation not in catalog:
        raise ToolBusinessError("unknown_tool", "Operation is not registered")
    rows, field = catalog[operation]
    row = rows.get(str(arguments.get(field, "")))
    if row is None:
        raise ToolBusinessError("not_found", "Synthetic business record not found")
    return dict(row)


def business_schemas() -> dict[str, dict[str, object]]:
    identifier: dict[str, object] = {"type": "string", "minLength": 1, "maxLength": 64}
    short_text: dict[str, object] = {"type": "string", "minLength": 1, "maxLength": 500}
    properties: dict[str, dict[str, object]] = {
        "lookup_product": {"sku": identifier},
        "check_warranty": {"serial_number": identifier},
        "lookup_customer": {"customer_id": identifier},
        "create_followup": {"customer_id": identifier, "note": short_text},
        "request_discount": {
            "customer_id": identifier,
            "percent": {"type": "integer", "minimum": 1, "maximum": 20},
            "reason": short_text,
        },
    }
    return {
        name: {
            "type": "object",
            "properties": fields,
            "required": list(fields),
            "additionalProperties": False,
        }
        for name, fields in properties.items()
    }
