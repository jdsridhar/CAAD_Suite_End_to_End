"""Restricted, non-eval expression language for configurable workflow gates."""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


class GateExpressionError(ValueError):
    """The expression is invalid, unsafe, or cannot be evaluated against the supplied data."""


class _MissingField(GateExpressionError):
    pass


@dataclass(frozen=True, slots=True)
class GateExpression:
    source: str
    allowed_fields: frozenset[str]
    _tree: ast.Expression

    def evaluate(self, context: Mapping[str, Any]) -> bool:
        """Evaluate against nested mappings and require a boolean result."""
        try:
            value = _evaluate(self._tree.body, context, self.allowed_fields)
        except GateExpressionError:
            raise
        except (ArithmeticError, TypeError, ValueError) as exc:
            raise GateExpressionError(f"gate evaluation failed: {exc}") from exc
        if not isinstance(value, bool):
            raise GateExpressionError("a gate expression must evaluate to a boolean")
        return value


def compile_gate(expression: str, *, allowed_fields: set[str] | frozenset[str]) -> GateExpression:
    """Parse and validate an expression against declared dotted result-field paths."""
    if not expression.strip():
        raise GateExpressionError("gate expression must not be blank")
    fields = frozenset(allowed_fields)
    for field in fields:
        if not field or "__" in field or any(not part.isidentifier() for part in field.split(".")):
            raise GateExpressionError(f"invalid declared field path {field!r}")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise GateExpressionError(f"invalid gate syntax: {exc.msg}") from exc
    _validate(tree.body, fields)
    return GateExpression(expression, fields, tree)


def _field_path(node: ast.AST) -> str | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def _validate(node: ast.AST, fields: frozenset[str]) -> None:
    if isinstance(node, ast.Constant):
        if not (node.value is None or isinstance(node.value, (str, int, float, bool))):
            raise GateExpressionError(
                "only string, numeric, boolean, and null literals are allowed"
            )
        if isinstance(node.value, float) and not math.isfinite(node.value):
            raise GateExpressionError("non-finite numeric literals are not allowed")
        return
    if isinstance(node, (ast.Name, ast.Attribute)):
        path = _field_path(node)
        if path is None or path not in fields:
            raise GateExpressionError(f"field {path or ast.dump(node)!r} is not declared")
        if "__" in path:
            raise GateExpressionError("dunder field access is forbidden")
        return
    if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
        for value in node.values:
            _validate(value, fields)
        return
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.Not, ast.USub, ast.UAdd)):
        _validate(node.operand, fields)
        return
    if isinstance(node, ast.Compare):
        if not all(
            isinstance(op, (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)) for op in node.ops
        ):
            raise GateExpressionError("comparison operator is not allowed")
        _validate(node.left, fields)
        for comparator in node.comparators:
            _validate(comparator, fields)
        return
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in {
            "abs",
            "min",
            "max",
            "len",
            "exists",
        }:
            raise GateExpressionError("only abs, min, max, len, and exists calls are allowed")
        if node.keywords or any(isinstance(arg, ast.Starred) for arg in node.args):
            raise GateExpressionError("keyword and expanded call arguments are not allowed")
        if node.func.id in {"abs", "len", "exists"} and len(node.args) != 1:
            raise GateExpressionError(f"{node.func.id}() requires exactly one argument")
        if node.func.id in {"min", "max"} and not node.args:
            raise GateExpressionError(f"{node.func.id}() requires at least one argument")
        if node.func.id == "exists":
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                path = arg.value
                if path not in fields or "__" in path:
                    raise GateExpressionError(f"field {path!r} is not declared")
            else:
                path = _field_path(arg)
                if path is None or path not in fields or "__" in path:
                    raise GateExpressionError("exists() requires a declared field path")
        else:
            for arg in node.args:
                _validate(arg, fields)
        return
    raise GateExpressionError(f"expression element {type(node).__name__} is not allowed")


def _resolve(path: str, context: Mapping[str, Any]) -> Any:
    value: Any = context
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            raise _MissingField(f"field {path!r} is missing from gate input")
        value = value[part]
    return value


def _path_exists(path: str, context: Mapping[str, Any]) -> bool:
    value: Any = context
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return False
        value = value[part]
    return True


_COMPARISONS: dict[type[ast.cmpop], Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


def _evaluate(node: ast.AST, context: Mapping[str, Any], fields: frozenset[str]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.Name, ast.Attribute)):
        path = _field_path(node)
        if path is None:
            raise GateExpressionError("invalid field path")
        return _resolve(path, context)
    if isinstance(node, ast.BoolOp):
        for expression in node.values:
            value = _evaluate(expression, context, fields)
            if not isinstance(value, bool):
                raise GateExpressionError("and/or operands must be booleans")
            if isinstance(node.op, ast.And) and not value:
                return False
            if isinstance(node.op, ast.Or) and value:
                return True
        return isinstance(node.op, ast.And)
    if isinstance(node, ast.UnaryOp):
        value = _evaluate(node.operand, context, fields)
        if isinstance(node.op, ast.Not):
            if not isinstance(value, bool):
                raise GateExpressionError("not operand must be a boolean")
            return not value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise GateExpressionError("unary +/- requires a numeric operand")
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.Compare):
        left = _evaluate(node.left, context, fields)
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            right = _evaluate(comparator, context, fields)
            comparison_fn = _COMPARISONS[type(op)]
            if not comparison_fn(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise GateExpressionError("only direct allow-listed function calls are allowed")
        builtin_name = node.func.id  # validated as a direct allow-listed name
        if builtin_name == "exists":
            arg = node.args[0]
            path = (
                arg.value
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                else _field_path(arg)
            )
            if path is None:
                raise GateExpressionError("exists() requires a declared field path")
            return _path_exists(path, context)
        values = [_evaluate(arg, context, fields) for arg in node.args]
        functions: dict[str, Callable[..., Any]] = {
            "abs": abs,
            "min": min,
            "max": max,
            "len": len,
        }
        return functions[builtin_name](*values)
    raise GateExpressionError(f"unhandled expression element {type(node).__name__}")
