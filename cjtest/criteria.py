"""Parse and evaluate Journey Builder decision-split criteria (FilterDefinition XML)."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Callable

Var = tuple[str, str]  # (DE name, field name)

EQ = {"is", "equal", "equals", "isequalto"}
NE = {"isnot", "notequal", "notequals", "isnotequalto"}
NUMERIC = {"greaterthan", "greaterthanorequal", "lessthan", "lessthanorequal"}
TEXT = {"contains", "doesnotcontain", "notcontains", "beginswith", "startswith", "endswith"}
NULL = {"isnull", "isnotnull"}
SUPPORTED = EQ | NE | NUMERIC | TEXT | NULL


class UnsupportedOperator(ValueError):
    pass


@dataclass(frozen=True)
class Condition:
    var: Var
    op: str
    values: tuple[str, ...]

    def describe(self) -> str:
        v = ",".join(self.values)
        return f"{self.var[0]}.{self.var[1]} {self.op}" + (f" [{v}]" if v else "")


@dataclass(frozen=True)
class Group:
    op: str  # AND | OR
    items: tuple  # Condition | Group

    def describe(self) -> str:
        parts = [i.describe() if isinstance(i, Condition) else f"({i.describe()})" for i in self.items]
        return f" {self.op} ".join(parts)


def parse(xml_text: str | None, resolve_key: Callable[[str], Var]) -> Group | None:
    if not xml_text:
        return None
    root = ET.fromstring(xml_text)
    sets = root.findall("ConditionSet") if root.tag == "FilterDefinition" else [root]
    groups = [_parse_set(s, resolve_key) for s in sets]
    if not groups:
        return None
    return groups[0] if len(groups) == 1 else Group("AND", tuple(groups))


def _parse_set(node: ET.Element, resolve_key) -> Group:
    items = []
    for child in node:
        if child.tag == "Condition":
            values = tuple((v.text or "") for v in child.iter("Value") if (v.text or "") != "")
            items.append(Condition(resolve_key(child.get("Key", "")), child.get("Operator", ""), values))
        elif child.tag == "ConditionSet":
            items.append(_parse_set(child, resolve_key))
    return Group((node.get("Operator") or "AND").upper(), tuple(items))


def conditions(node) -> list[Condition]:
    if node is None:
        return []
    if isinstance(node, Condition):
        return [node]
    return [c for i in node.items for c in conditions(i)]


def variables(node) -> set[Var]:
    return {c.var for c in conditions(node)}


def evaluate(node, get: Callable[[Var], str | None], case_insensitive: bool = True) -> bool:
    """Short-circuit evaluation. `get` may raise to request a missing variable."""
    if isinstance(node, Condition):
        return _eval_condition(node, get(node.var), case_insensitive)
    if node.op == "OR":
        return any(evaluate(i, get, case_insensitive) for i in node.items)
    return all(evaluate(i, get, case_insensitive) for i in node.items)


def _norm(v: str, ci: bool) -> str:
    v = v.strip()
    low = v.lower()
    if low in ("true", "1"):
        return "true"
    if low in ("false", "0"):
        return "false"
    return low if ci else v


def _num(v: str) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _eval_condition(c: Condition, value: str | None, ci: bool) -> bool:
    op = c.op.lower()
    if op not in SUPPORTED:
        raise UnsupportedOperator(f"Operator '{c.op}' not supported ({c.describe()})")
    if op == "isnull":
        return value is None or value == ""
    if op == "isnotnull":
        return not (value is None or value == "")
    if value is None or value == "":
        # SQL-like semantics: a null never matches a comparison
        return False
    target = c.values[0] if c.values else ""
    if op in EQ:
        return _norm(value, ci) == _norm(target, ci)
    if op in NE:
        return _norm(value, ci) != _norm(target, ci)
    if op in NUMERIC:
        a, b = _num(value), _num(target)
        if a is None or b is None:
            return False
        return {"greaterthan": a > b, "greaterthanorequal": a >= b,
                "lessthan": a < b, "lessthanorequal": a <= b}[op]
    a, b = _norm(value, ci), _norm(target, ci)
    return {"contains": b in a, "doesnotcontain": b not in a, "notcontains": b not in a,
            "beginswith": a.startswith(b), "startswith": a.startswith(b), "endswith": a.endswith(b)}[op]
