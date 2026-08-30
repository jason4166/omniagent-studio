import ast

import pytest

from omniagent.calculator import (
    MAX_AST_NODES,
    MAX_EXPRESSION_LENGTH,
    CalculatorSecurityError,
    evaluate_calculator_expression,
    parse_calculator_expression,
)


def test_parse_calculator_expression_accepts_addition() -> None:
    tree = parse_calculator_expression("1 + 2")

    node_names = [type(node).__name__ for node in ast.walk(tree)]

    assert node_names == [
        "Expression",
        "BinOp",
        "Constant",
        "Add",
        "Constant",
    ]


def test_parse_calculator_expression_rejects_function_call() -> None:
    attack_expression = '__import__("os")'
    expected_rejected_node = "Call"

    with pytest.raises(
        CalculatorSecurityError,
        match=expected_rejected_node,
    ):
        parse_calculator_expression(attack_expression)


def test_evaluate_calculator_expression_adds_numbers() -> None:
    assert evaluate_calculator_expression("1 + 2") == 3


def test_evaluate_calculator_expression_subtracts_numbers() -> None:
    assert evaluate_calculator_expression("5 - 2") == 3


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("3 * 4", 12),
        ("8 / 2", 4.0),
        ("(1 + 2) * 3", 9),
    ],
)
def test_evaluate_calculator_expression_handles_supported_operations(
    expression: str,
    expected: int | float,
) -> None:
    assert evaluate_calculator_expression(expression) == expected


def test_parse_calculator_expression_rejects_overlong_input() -> None:
    overlong_expression = "1" * (MAX_EXPRESSION_LENGTH + 1)

    with pytest.raises(
        CalculatorSecurityError,
        match="calculator expression is too long",
    ):
        parse_calculator_expression(overlong_expression)


def test_parse_calculator_expression_rejects_too_many_nodes() -> None:
    complex_expression = " + ".join(["1"] * 22)
    parsed_expression = ast.parse(complex_expression, mode="eval")

    assert len(complex_expression) <= MAX_EXPRESSION_LENGTH
    assert len(list(ast.walk(parsed_expression))) > MAX_AST_NODES

    with pytest.raises(
        CalculatorSecurityError,
        match="calculator expression is too complex",
    ):
        parse_calculator_expression(complex_expression)
