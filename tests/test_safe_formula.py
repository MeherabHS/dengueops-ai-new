from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

from safe_formula import SafeFormulaError, evaluate_formula, evaluate_formula_canonical  # noqa: E402


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("a + b", "5"),
        ("a - b", "1"),
        ("a * b", "6"),
        ("a / b", "1.5"),
        ("-a + +b", "-1"),
        ("min(a, b)", "2"),
        ("max(a, b)", "3"),
        ("ceil(c)", "2"),
    ],
)
def test_allowed_decimal_language(expression: str, expected: str) -> None:
    assert evaluate_formula_canonical(
        expression,
        {"a": Decimal("3"), "b": Decimal("2"), "c": Decimal("1.000001")},
    ) == expected


def test_canonical_decimal_is_deterministic() -> None:
    assert evaluate_formula("0.100000 + 0.200000", {}) == Decimal("0.300000")
    assert evaluate_formula_canonical("0.100000 + 0.200000", {}) == "0.3"
    assert evaluate_formula_canonical("-0.000000", {}) == "0"


@pytest.mark.parametrize(
    "expression",
    [
        "value ** 2",
        "value % 2",
        "value // 2",
        "value.attr",
        "value[0]",
        "value if value else 0",
        "[value]",
        "(lambda x: x)(value)",
        "[x for x in value]",
        "__import__('os')",
        "abs(value)",
        "open('x')",
        "f'{value}'",
    ],
)
def test_prohibited_ast_and_functions(expression: str) -> None:
    with pytest.raises(SafeFormulaError):
        evaluate_formula(expression, {"value": Decimal("1")})


def test_limits_and_binding_failures() -> None:
    with pytest.raises(SafeFormulaError, match="length"):
        evaluate_formula("1+" * 256 + "1", {})
    with pytest.raises(SafeFormulaError, match="complexity"):
        evaluate_formula("+".join("1" for _ in range(40)), {})
    with pytest.raises(SafeFormulaError, match="Missing"):
        evaluate_formula("required + 1", {})
    with pytest.raises(SafeFormulaError, match="Unknown"):
        evaluate_formula("known", {"known": Decimal("1"), "extra": Decimal("1")}, allowed_variables={"known"})
    with pytest.raises(SafeFormulaError, match="division by zero"):
        evaluate_formula("1 / zero", {"zero": Decimal("0")})
    with pytest.raises(SafeFormulaError, match="magnitude"):
        evaluate_formula("value + 1", {"value": Decimal("1000000000000")})
    with pytest.raises(SafeFormulaError, match="scale"):
        evaluate_formula("value", {"value": Decimal("0.0000001")})
    with pytest.raises(SafeFormulaError, match="float"):
        evaluate_formula("value", {"value": 1.0})


def test_identifier_and_variable_count_limits() -> None:
    with pytest.raises(SafeFormulaError, match="identifier"):
        evaluate_formula("max", {"max": Decimal("1")})
    bindings = {f"v{index}": Decimal(index) for index in range(17)}
    with pytest.raises(SafeFormulaError, match="too large"):
        evaluate_formula("v0", bindings)
