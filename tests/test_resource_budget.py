import pytest
from pydantic import ValidationError

from omniagent.llm import LLMUsage
from omniagent.resource_budget import ResourceBudget, accumulate_reported_tokens


def test_inconsistent_usage_is_unknown() -> None:
    assert (
        accumulate_reported_tokens(10, LLMUsage(input_tokens=3, output_tokens=4, total_tokens=99))
        is None
    )


@pytest.mark.parametrize("value", [-1, 1.5, True])
def test_budget_requires_nonnegative_integer_limits(value: object) -> None:
    with pytest.raises(ValidationError):
        ResourceBudget.model_validate({"max_total_tokens": value})
