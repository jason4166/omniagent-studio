from omniagent.utils import (
    group_by_prefix,
    normalize_identifier,
    parse_positive_int,
    unique_non_empty,
)


def test_normalize_identifier() -> None:
    assert normalize_identifier("  Sales-Agent  ") == "sales_agent"


def test_normalize_identifier_with_blank_value() -> None:
    assert normalize_identifier("   ") == ""


def test_unique_non_empty() -> None:
    assert unique_non_empty(["search", "", "search", " email "]) == ["search", "email"]


def test_unique_non_empty_with_only_blank_values() -> None:
    assert unique_non_empty(["", "   ", ""]) == []


def test_group_by_prefix_without_separator() -> None:
    assert group_by_prefix(["general"]) == {"general": ["general"]}


def test_group_by_prefix() -> None:
    assert group_by_prefix(["hr_resume", "sales_lead", "   ", "", "hr_interview"]) == {
        "hr": ["hr_resume", "hr_interview"],
        "sales": ["sales_lead"],
    }


def test_parse_positive_int() -> None:
    assert parse_positive_int("12", 5) == 12


def test_parse_positive_int_with_invalid_value() -> None:
    assert parse_positive_int("abc", 7) == 7


def test_parse_positive_int_with_zero() -> None:
    assert parse_positive_int("0", 9) == 9
