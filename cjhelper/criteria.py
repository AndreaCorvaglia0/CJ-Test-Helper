"""Decision-split criteria: parse the FilterDefinition XML and evaluate one condition.

Spec, "Input: the package export": "Split criteria are XML (FilterDefinition) with
nested AND/OR groups. Each condition names a table, a field, an operator and a value."
Spec, "Journey model and coverage", step 2: "Each decision split outcome becomes a
logical formula over table fields."

Shape read here (docs/plan.md, "criteria.py"; docs/export-format.md)::

    <FilterDefinition>
      <ConditionSet Operator="AND">
        <Condition Key="<attribute set>.<field>" Operator="Is">
          <AttributePath RelationshipID="..."><Value><![CDATA[true]]></Value></AttributePath>
        </Condition>
        <ConditionSet Operator="OR"> ... </ConditionSet>
      </ConditionSet>
    </FilterDefinition>

The condition's ``table`` is the attribute-set name as written in the key; loader.py
maps it to the table name. The value may be wrapped in any number of
``<AttributePath>`` elements; an empty CDATA is an empty value.

Operators. Spec: "New activity types and operators are added by extending one lookup
table each." ``OPERATORS`` below is that one table for operators: to support a new
operator, add one entry to it (and, if the operator takes no value, list its name in
``OPERATORS_WITHOUT_VALUE`` right below it). Nothing else in the generator changes.
The table holds the spec's pilot operators ``Is``, ``Equal``, ``IsNull`` and the
earlier tool's operators that "can be carried over at low cost" (spec, "Supported in
the PoC"). Any other operator raises ``UnsupportedOperator`` when evaluated; spec:
"Anything else is not an error: it is listed in the report, and the branches behind
it are marked as not covered."

Assumptions (the spec does not say; each is listed in the developer report):

- A comparison with a null value is false for every operator except ``IsNull`` and
  ``IsNotNull``, as in SQL. An empty string is null, as in the CSV files
  (spec, "File format": "empty cell for null").
- Ordering operators on text compare the strings (folded when text comparisons
  ignore letter case); on Booleans they compare the normalised ``true``/``false``.
- A number or a date that cannot be parsed is compared as text by ``Is``/``Equal``/
  ``NotEqual`` and never satisfies an ordering operator.
- Dates are read as ISO 8601 (``YYYY-MM-DD[ HH:MM[:SS]]``); a time zone offset is
  converted to UTC and dropped, values without one are compared as written.
- A field type not listed in the model (or missing) is compared as text.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable, Optional, Union

from .model import Condition, ConditionGroup, Formula, Value, formula_text


class CriteriaError(Exception):
    """The criteria XML cannot be read: not XML, not the expected shape, an empty group or an unknown element."""


class UnsupportedOperator(Exception):
    """A condition uses an operator that is not in OPERATORS."""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_criteria(xml: str) -> Formula:
    """Turn one outcome's FilterDefinition XML into a formula.

    Plan: "A set with one item collapses to that item. An empty set or an unknown
    element -> CriteriaError." The root must be ``<FilterDefinition>`` holding exactly
    one ``<ConditionSet>`` (or one ``<Condition>``); several top-level items are not a
    documented shape and raise CriteriaError rather than being guessed as AND.
    """
    if not isinstance(xml, str) or not xml.strip():
        raise CriteriaError("The criteria are empty.")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as error:
        raise CriteriaError(f"The criteria are not valid XML ({error}).") from None
    if _tag(root) != "FilterDefinition":
        raise CriteriaError(f"The criteria start with <{_tag(root)}> instead of <FilterDefinition>.")
    children = list(root)
    if len(children) != 1:
        raise CriteriaError(
            f"<FilterDefinition> holds {len(children)} top-level elements; exactly one condition set is expected."
        )
    return _parse_item(children[0])


def _parse_item(element: ET.Element) -> Formula:
    tag = _tag(element)
    if tag == "ConditionSet":
        return _parse_set(element)
    if tag == "Condition":
        return _parse_condition(element)
    raise CriteriaError(f"Unknown element <{tag}> in the criteria.")


def _parse_set(element: ET.Element) -> Formula:
    """A ``<ConditionSet>``: its items joined by AND or OR; a single item stands alone."""
    items = [_parse_item(child) for child in element]
    if not items:
        raise CriteriaError("A <ConditionSet> in the criteria is empty.")
    if len(items) == 1:
        return items[0]
    operator = (element.get("Operator") or "").strip().upper()
    if operator not in ("AND", "OR"):
        raise CriteriaError(f"A <ConditionSet> has operator {element.get('Operator')!r}; AND or OR is expected.")
    return ConditionGroup(operator, tuple(items))


def _parse_condition(element: ET.Element) -> Condition:
    """A ``<Condition Key="Set.Field" Operator="..">`` with its value.

    Plan: "Key splits on the first . into set and field (field names may contain spaces)."
    The value is None for operators without a value (model.Condition).
    """
    key = element.get("Key") or ""
    set_name, dot, field_name = key.partition(".")
    if not dot or not set_name or not field_name:
        raise CriteriaError(f"Condition key {key!r} is not written as <attribute set>.<field>.")
    operator = (element.get("Operator") or "").strip()
    if not operator:
        raise CriteriaError(f"Condition {key} has no operator.")
    values = _values(element)
    if len(values) > 1:
        raise CriteriaError(f"Condition {key} holds {len(values)} values; one is expected.")
    if operator in OPERATORS_WITHOUT_VALUE:
        value: Value = None
    elif values:
        value = values[0]
    elif operator in OPERATORS:
        raise CriteriaError(f"Condition {key} {operator} has no <Value>.")
    else:
        value = None    # unknown operator: UnsupportedOperator is raised when it is evaluated
    return Condition(table=set_name, field=field_name, operator=operator, value=value)


def _values(element: ET.Element) -> list[str]:
    """Texts of the ``<Value>`` elements under a condition, looking through ``<AttributePath>`` wrappers."""
    found: list[str] = []
    for child in element:
        tag = _tag(child)
        if tag == "Value":
            found.append(child.text or "")
        elif tag == "AttributePath":
            found.extend(_values(child))
        else:
            raise CriteriaError(f"Unknown element <{tag}> in a condition.")
    return found


def _tag(element: ET.Element) -> str:
    """Element name without an XML namespace."""
    return element.tag.rsplit("}", 1)[-1]


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate_condition(cond: Condition, value: Value, field_type: str, case_insensitive: bool) -> bool:
    """Is ``cond`` true for a contact whose field holds ``value``?

    ``value`` is the CSV string or None for null; ``field_type`` is the schema type of
    the field (``Text``, ``Boolean``, ``Date``, ...); ``case_insensitive`` is the
    setting "Text comparisons ignore letter case" (spec default: off).
    Plan: "IsNull: None or "". IsNotNull: the opposite. Any other operator on None ->
    False." Raises UnsupportedOperator for an operator that is not in OPERATORS.
    """
    test = OPERATORS.get(cond.operator)
    if test is None:
        raise UnsupportedOperator(f"Operator {cond.operator!r} is not supported ({formula_text(cond)}).")
    if cond.operator in OPERATORS_WITHOUT_VALUE:
        return test(value, None, field_type, case_insensitive)
    if _is_null(value) or cond.value is None:
        return False
    return test(value, cond.value, field_type, case_insensitive)


# Each test receives (field value, condition value, field type, case_insensitive).
# evaluate_condition handles nulls before calling a test that takes a value, so those
# tests always receive two strings.
OperatorTest = Callable[[Value, Value, str, bool], bool]


def _is_null(value: Value) -> bool:
    return value is None or value == ""


def _test_is_null(actual: Value, _expected: Value, _field_type: str, _case_insensitive: bool) -> bool:
    return _is_null(actual)


def _test_is_not_null(actual: Value, _expected: Value, _field_type: str, _case_insensitive: bool) -> bool:
    return not _is_null(actual)


def _test_equal(actual: str, expected: str, field_type: str, case_insensitive: bool) -> bool:
    order = _compare(actual, expected, field_type, case_insensitive)
    if order is None:   # a number or a date that does not parse: compare the text
        return _fold(actual, case_insensitive) == _fold(expected, case_insensitive)
    return order == 0


def _test_not_equal(actual: str, expected: str, field_type: str, case_insensitive: bool) -> bool:
    return not _test_equal(actual, expected, field_type, case_insensitive)


def _test_greater_than(actual: str, expected: str, field_type: str, case_insensitive: bool) -> bool:
    return _compare(actual, expected, field_type, case_insensitive) == 1


def _test_less_than(actual: str, expected: str, field_type: str, case_insensitive: bool) -> bool:
    return _compare(actual, expected, field_type, case_insensitive) == -1


def _test_greater_or_equal(actual: str, expected: str, field_type: str, case_insensitive: bool) -> bool:
    return _compare(actual, expected, field_type, case_insensitive) in (0, 1)


def _test_less_or_equal(actual: str, expected: str, field_type: str, case_insensitive: bool) -> bool:
    return _compare(actual, expected, field_type, case_insensitive) in (-1, 0)


def _test_contains(actual: str, expected: str, field_type: str, case_insensitive: bool) -> bool:
    return _text_form(expected, field_type, case_insensitive) in _text_form(actual, field_type, case_insensitive)


def _test_begins_with(actual: str, expected: str, field_type: str, case_insensitive: bool) -> bool:
    return _text_form(actual, field_type, case_insensitive).startswith(_text_form(expected, field_type, case_insensitive))


def _test_ends_with(actual: str, expected: str, field_type: str, case_insensitive: bool) -> bool:
    return _text_form(actual, field_type, case_insensitive).endswith(_text_form(expected, field_type, case_insensitive))


# The one lookup table for operators (spec: "New activity types and operators are added
# by extending one lookup table each"). Names as written in the criteria XML.
OPERATORS: dict[str, OperatorTest] = {
    # used by the pilot journey (spec, "Supported in the PoC")
    "Is": _test_equal,
    "Equal": _test_equal,
    "IsNull": _test_is_null,
    # carried over from the earlier tool (spec: "they can be carried over at low cost")
    "NotEqual": _test_not_equal,
    "IsNotNull": _test_is_not_null,
    "GreaterThan": _test_greater_than,
    "LessThan": _test_less_than,
    "GreaterThanOrEqual": _test_greater_or_equal,
    "LessThanOrEqual": _test_less_or_equal,
    "Contains": _test_contains,
    "BeginsWith": _test_begins_with,
    "EndsWith": _test_ends_with,
}

# Operators of the table above that take no value: their condition value is None.
OPERATORS_WITHOUT_VALUE: frozenset[str] = frozenset({"IsNull", "IsNotNull"})


# ---------------------------------------------------------------------------
# Comparison by field type (plan, "criteria.py": semantics in evaluate_condition)
# ---------------------------------------------------------------------------

_TYPE_FAMILIES = {"boolean": "boolean", "number": "number", "decimal": "number", "date": "date"}
_DATE_ONLY = re.compile(r"\d{4}-?\d{2}-?\d{2}")

Comparable = Union[str, Decimal, datetime, date]


def _family(field_type: Optional[str]) -> str:
    """boolean, number, date, or text (Text, EmailAddress, Phone, Locale and anything unknown)."""
    return _TYPE_FAMILIES.get((field_type or "").strip().lower(), "text")


def _compare(actual: str, expected: str, field_type: str, case_insensitive: bool) -> Optional[int]:
    """-1, 0 or 1 as ``actual`` is below, equal to or above ``expected``; None when they cannot be compared.

    Plan: "Boolean: compare after lower-casing, accepting true/false/1/0. Text,
    EmailAddress, Phone, Locale: exact match; case-insensitive when the setting says so.
    Number/Decimal: numeric compare. Date: parse both sides; date-only condition values
    compare on the date part."
    """
    family = _family(field_type)
    left: Optional[Comparable]
    right: Optional[Comparable]
    if family == "boolean":
        left, right = _boolean_text(actual), _boolean_text(expected)
    elif family == "number":
        left, right = _number(actual), _number(expected)
    elif family == "date":
        left, right = _date(actual), _date(expected)
        if left is not None and right is not None and _DATE_ONLY.fullmatch(expected.strip()):
            left, right = left.date(), right.date()
    else:
        left, right = _fold(actual, case_insensitive), _fold(expected, case_insensitive)
    if left is None or right is None:
        return None
    return (left > right) - (left < right)


def _fold(text: str, case_insensitive: bool) -> str:
    return text.casefold() if case_insensitive else text


def _text_form(text: str, field_type: str, case_insensitive: bool) -> str:
    """The string Contains / BeginsWith / EndsWith look at."""
    if _family(field_type) == "boolean":
        return _boolean_text(text)
    return _fold(text, case_insensitive)


def _boolean_text(text: str) -> str:
    """``true`` / ``false`` for the spellings True, true, TRUE, 1, False, false, 0; anything else lower-cased."""
    lowered = text.strip().lower()
    return {"1": "true", "0": "false"}.get(lowered, lowered)


def _number(text: str) -> Optional[Decimal]:
    try:
        number = Decimal(text.strip())
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _date(text: str) -> Optional[datetime]:
    """An ISO 8601 date or date and time (``YYYY-MM-DD[ HH:MM[:SS]]``), or None."""
    try:
        moment = datetime.fromisoformat(text.strip())
    except ValueError:
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment
