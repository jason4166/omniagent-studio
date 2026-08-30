import ast

MAX_EXPRESSION_LENGTH = 200
MAX_AST_NODES = 64
ALLOWED_NODE_TYPES: tuple[type[ast.AST], ...] = (
    ast.Expression,
    ast.BinOp,
    ast.Constant,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
)


class CalculatorSecurityError(ValueError):
    pass


def parse_calculator_expression(expression: str) -> ast.Expression:
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise CalculatorSecurityError("calculator expression is too long")
    tree = ast.parse(expression, mode="eval")

    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_AST_NODES:
        raise CalculatorSecurityError("calculator expression is too complex")

    for node in nodes:
        if type(node) not in ALLOWED_NODE_TYPES:
            raise CalculatorSecurityError(f"calculator node is not allowed: {type(node).__name__}")

    return tree


def evaluate_calculator_expression(expression: str) -> int | float:

    tree = parse_calculator_expression(expression)
    return _evaluate_node(tree.body)


def _evaluate_node(node: ast.AST) -> int | float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            raise CalculatorSecurityError("calculator constants must be numbers")
        if isinstance(node.value, int):
            return node.value
        if isinstance(node.value, float):
            return node.value
        raise CalculatorSecurityError("calculator constants must be numbers")

    if isinstance(node, ast.BinOp):
        left = _evaluate_node(node.left)
        right = _evaluate_node(node.right)

        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
    raise CalculatorSecurityError(f"calculator node cannot be evaluated: {type(node).__name__}")
