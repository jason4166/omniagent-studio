import pytest

from omniagent.semantic_cache import canonical_terms


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Alice reimburses Bob", "Bob reimburses Alice"),
        ("allow not deny", "deny not allow"),
        ("amount > 10", "amount < 10"),
        ("US policy", "us policy"),
        ("annual leave 10", "annual leave 20"),
        ("annual leave", "not annual leave"),
        ("annual leave policy", "年假 policy"),
        ("inwarranty", "in保修"),
        ("warranty?", "warranty"),
        ("①", "1"),
    ],
)
def test_query_key_preserves_meaning_bearing_order_case_punctuation_and_numbers(left, right):
    assert canonical_terms(left) != canonical_terms(right)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("annual leave", "年假"),
        ("  Annual   Leave\n", "年假"),
        ("leave allowance", "年假"),
        ("warranty", "保修"),
        ("Alice   reimburses\tBob", "Alice reimburses Bob"),
        ("caf\u00e9", "cafe\u0301"),
    ],
)
def test_query_key_only_reuses_explicit_whole_query_aliases_and_formatting(left, right):
    assert canonical_terms(left) == canonical_terms(right)
