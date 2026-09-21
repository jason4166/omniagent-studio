import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from omniagent.profiles import AgentProfile
from omniagent.session_models import RunBudget


def test_display_presets_allow_million_tokens_without_changing_tool_or_deadline_limits() -> None:
    entries = json.loads(Path("presets/profiles.json").read_text(encoding="utf-8"))
    for entry in entries:
        budget = AgentProfile.model_validate(entry["profile"]).budgets
        assert (budget.max_tokens, budget.max_model_calls, budget.max_steps) == (1000000, 100, 200)
        assert budget.max_tool_calls == 4
        assert budget.deadline_seconds == 120
        assert budget.max_cost_microusd is None


@pytest.mark.parametrize(
    "change", [{"max_tokens": 1000001}, {"max_model_calls": 101}, {"max_steps": 201}]
)
def test_run_budget_still_rejects_values_beyond_supported_limits(change: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        RunBudget.model_validate(change)
