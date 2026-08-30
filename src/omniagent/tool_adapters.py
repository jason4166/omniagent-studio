from omniagent.calculator import evaluate_calculator_expression
from omniagent.tooling import ToolBusinessError

SYNTHETIC_PRODUCTS: dict[str, dict[str, object]] = {
    "DEMO-100": {
        "sku": "DEMO-100",
        "name": "Synthetic Keyboard",
        "available": True,
    },
}
SYNTHETIC_WARRANTIES: dict[str, dict[str, object]] = {
    "SERIAL-DEMO-100": {
        "serial_number": "SERIAL-DEMO-100",
        "status": "active",
        "expires_on": "2030-12-31",
    },
}


class ProductNotFoundError(ToolBusinessError):
    def __init__(self) -> None:
        super().__init__(
            code="product_not_found",
            message="Product was not found",
        )


class CalculatorAdapter:
    def execute(self, arguments: dict[str, object]) -> object:
        expression = arguments["expression"]
        if not isinstance(expression, str):
            raise TypeError("calculator expression must be a string")

        value = evaluate_calculator_expression(expression)
        return {"value": value}


class LookupProductAdapter:
    def execute(self, arguments: dict[str, object]) -> object:
        sku = arguments["sku"]
        if not isinstance(sku, str):
            raise TypeError("product sku must be a string")

        product = SYNTHETIC_PRODUCTS.get(sku)
        if product is None:
            raise ProductNotFoundError()

        return product.copy()


class CheckWarrantyAdapter:
    def execute(self, arguments: dict[str, object]) -> object:
        serial_number = arguments["serial_number"]

        if not isinstance(serial_number, str):
            raise TypeError("warranty serial number must be a string")

        warranty = SYNTHETIC_WARRANTIES[serial_number]

        return warranty.copy()


class CreateFollowupAdapter:
    def execute(self, arguments: dict[str, object]) -> object:
        raise RuntimeError("create_followup execution is disabled in Day 8")
