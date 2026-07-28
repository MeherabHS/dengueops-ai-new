"""Deterministic, bounded Decimal interpreter for governed formulas."""
from __future__ import annotations

import ast
import re
from decimal import Decimal, InvalidOperation, ROUND_CEILING, localcontext
from typing import Mapping

MAX_EXPRESSION_BYTES = 512
MAX_AST_NODES = 64
MAX_AST_DEPTH = 12
MAX_VARIABLES = 16
MAX_FUNCTION_ARGUMENTS = 8
MAX_OPERATIONS = 64
MAX_IDENTIFIER_LENGTH = 64
MAX_MAGNITUDE = Decimal("1000000000000")
MAX_DECIMAL_SCALE = 6
IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
DECIMAL_LITERAL = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
FUNCTIONS = frozenset({"min", "max", "ceil"})


class SafeFormulaError(ValueError):
    """Raised when a formula is unsafe, invalid, or outside numeric policy."""


def canonical_decimal(value: Decimal) -> str:
    checked = _checked(value)
    if checked == 0:
        return "0"
    text = format(checked, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _checked(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise SafeFormulaError("Formula value must be finite.")
    if abs(value) > MAX_MAGNITUDE:
        raise SafeFormulaError("Formula value exceeds governed magnitude.")
    scale = max(0, -value.as_tuple().exponent)
    if scale > MAX_DECIMAL_SCALE:
        raise SafeFormulaError("Formula value exceeds governed decimal scale.")
    return value


def _input_decimal(value: object) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise SafeFormulaError("Formula inputs cannot be boolean or float.")
    if isinstance(value, Decimal):
        return _checked(value)
    if isinstance(value, int):
        return _checked(Decimal(value))
    if isinstance(value, str) and DECIMAL_LITERAL.fullmatch(value):
        try:
            return _checked(Decimal(value))
        except InvalidOperation as exc:
            raise SafeFormulaError("Formula input is not a valid decimal.") from exc
    raise SafeFormulaError("Formula inputs must be Decimal, integer, or canonical decimal string.")


def _depth(node: ast.AST) -> int:
    children = list(ast.iter_child_nodes(node))
    return 1 if not children else 1 + max(_depth(child) for child in children)


class _Interpreter:
    def __init__(self, expression: str, variables: Mapping[str, Decimal]):
        self.expression = expression
        self.variables = variables
        self.operations = 0

    def _operation(self) -> None:
        self.operations += 1
        if self.operations > MAX_OPERATIONS:
            raise SafeFormulaError("Formula exceeds governed operation limit.")

    def visit(self, node: ast.AST) -> Decimal:
        if isinstance(node, ast.Expression):
            return self.visit(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise SafeFormulaError("Only numeric constants are allowed.")
            literal = ast.get_source_segment(self.expression, node)
            if literal is None or not DECIMAL_LITERAL.fullmatch(literal):
                raise SafeFormulaError("Numeric constants must use plain decimal notation.")
            return _checked(Decimal(literal))
        if isinstance(node, ast.Name):
            if node.id not in self.variables:
                raise SafeFormulaError(f"Missing governed variable: {node.id}.")
            return self.variables[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            self._operation()
            value = self.visit(node.operand)
            return _checked(value if isinstance(node.op, ast.UAdd) else -value)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            self._operation()
            left, right = self.visit(node.left), self.visit(node.right)
            if isinstance(node.op, ast.Add):
                result = left + right
            elif isinstance(node.op, ast.Sub):
                result = left - right
            elif isinstance(node.op, ast.Mult):
                result = left * right
            else:
                if right == 0:
                    raise SafeFormulaError("Formula division by zero.")
                with localcontext() as context:
                    context.prec = 40
                    result = left / right
            return _checked(result)
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
                raise SafeFormulaError("Formula function is not allowed.")
            if node.keywords or not 1 <= len(node.args) <= MAX_FUNCTION_ARGUMENTS:
                raise SafeFormulaError("Formula function arguments are invalid.")
            self._operation()
            values = [self.visit(argument) for argument in node.args]
            if node.func.id == "ceil":
                if len(values) != 1:
                    raise SafeFormulaError("ceil() requires exactly one argument.")
                return _checked(values[0].to_integral_value(rounding=ROUND_CEILING))
            return _checked(min(values) if node.func.id == "min" else max(values))
        raise SafeFormulaError(f"Unsupported formula AST node: {type(node).__name__}.")


def evaluate_formula(
    expression: str,
    variables: Mapping[str, object],
    *,
    allowed_variables: set[str] | frozenset[str] | None = None,
) -> Decimal:
    if not isinstance(expression, str) or not expression.strip():
        raise SafeFormulaError("Formula expression is required.")
    if len(expression.encode("utf-8")) > MAX_EXPRESSION_BYTES:
        raise SafeFormulaError("Formula expression exceeds governed length.")
    if not isinstance(variables, Mapping) or len(variables) > MAX_VARIABLES:
        raise SafeFormulaError("Formula variable binding is invalid or too large.")
    names = list(variables)
    if any(not isinstance(name, str) or not IDENTIFIER.fullmatch(name) or name in FUNCTIONS for name in names):
        raise SafeFormulaError("Formula variable identifier is invalid.")
    if allowed_variables is not None and any(name not in allowed_variables for name in names):
        raise SafeFormulaError("Unknown governed variable supplied.")
    converted = {name: _input_decimal(value) for name, value in variables.items()}
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError) as exc:
        raise SafeFormulaError("Formula expression is not valid expression syntax.") from exc
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_AST_NODES or _depth(tree) > MAX_AST_DEPTH:
        raise SafeFormulaError("Formula AST exceeds governed complexity.")
    allowed_types = (
        ast.Expression, ast.BinOp, ast.UnaryOp, ast.Name, ast.Load, ast.Constant, ast.Call,
        ast.Add, ast.Sub, ast.Mult, ast.Div, ast.UAdd, ast.USub,
    )
    if any(not isinstance(node, allowed_types) for node in nodes):
        raise SafeFormulaError("Formula contains a prohibited AST node.")
    return _Interpreter(expression, converted).visit(tree)


def evaluate_formula_canonical(
    expression: str,
    variables: Mapping[str, object],
    *,
    allowed_variables: set[str] | frozenset[str] | None = None,
) -> str:
    return canonical_decimal(evaluate_formula(expression, variables, allowed_variables=allowed_variables))
