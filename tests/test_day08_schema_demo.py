import pytest
from pydantic import BaseModel, ConfigDict, ValidationError


class LookupProductArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str


def test_lookup_product_arguments_reject_extra_field() -> None:
    invalid_arguments = {
        "sku": "DEMO-100",
        "debug": True,
    }

    with pytest.raises(ValidationError) as exc_info:
        LookupProductArguments.model_validate(invalid_arguments)

    error = exc_info.value.errors()[0]
    assert error["loc"] == ("debug",)
    assert error["type"] == "extra_forbidden"
