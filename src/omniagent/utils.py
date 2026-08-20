"""Small deterministic helpers for OmniAgent Studio."""


def normalize_identifier(value: str) -> str:
    """Normalize a human-readable value into a simple identifier."""
    res = value.strip().lower().replace(" ", "_").replace("-", "_")
    return res


def unique_non_empty(values: list[str]) -> list[str]:
    """Return stripped, non-empty values while preserving first-seen order."""
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = value.strip()
        if cleaned != "":
            if cleaned not in seen:
                seen.add(cleaned)
                result.append(cleaned)
    return result


def group_by_prefix(values: list[str]) -> dict[str, list[str]]:
    """Group values by the text before their first underscore."""
    groups: dict[str, list[str]] = {}
    for value in values:
        value = value.strip()
        if value != "":
            prefix = value.split("_", 1)[0]
            if prefix not in groups:
                groups[prefix] = []
            groups[prefix].append(value)
    return groups


def parse_positive_int(raw: str, default: int) -> int:
    """Parse a positive integer, falling back to default when invalid."""
    try:
        parsed = int(raw)
    except ValueError:
        parsed = default
    if parsed <= 0:
        parsed = default
    return parsed
