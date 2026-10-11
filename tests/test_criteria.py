"""Unit tests for cjhelper.criteria: FilterDefinition parsing and condition evaluation."""

import pytest

from cjhelper.criteria import (
    OPERATORS,
    OPERATORS_WITHOUT_VALUE,
    CriteriaError,
    UnsupportedOperator,
    evaluate_condition,
    parse_criteria,
)
from cjhelper.model import Condition, ConditionGroup


def condition_xml(key, operator, value="", wrappers=0, with_value=True):
    """One <Condition>, its value optionally wrapped in <AttributePath> elements as in the pilot."""
    inner = f"<Value><![CDATA[{value}]]></Value>" if with_value else ""
    for level in range(wrappers):
        inner = f'<AttributePath RelationshipID="rel-{level}">{inner}</AttributePath>'
    return (f'<Condition Key="{key}" Operator="{operator}" '
            f'UiMetaData="{{&quot;groupToSetRelationshipId&quot;:&quot;rel-root&quot;}}">{inner}</Condition>')


def set_xml(*items, operator="AND"):
    return f'<ConditionSet Operator="{operator}" ConditionSetName="Individual Filter Grouping">{"".join(items)}</ConditionSet>'


def filter_xml(*items, operator="AND"):
    return f"<FilterDefinition>{set_xml(*items, operator=operator)}</FilterDefinition>"


# ---------------------------------------------------------------------------
# parse_criteria
# ---------------------------------------------------------------------------

def test_single_condition_collapses_to_the_condition():
    xml = filter_xml(condition_xml("Config Set.CHANNEL1", "Equal", "Email"))
    assert parse_criteria(xml) == Condition("Config Set", "CHANNEL1", "Equal", "Email")


def test_and_of_two_conditions():
    xml = filter_xml(condition_xml("Master.EmailOptOut", "Is", "false"),
                     condition_xml("Master.MarketingPermission", "Is", "true"))
    assert parse_criteria(xml) == ConditionGroup("AND", (
        Condition("Master", "EmailOptOut", "Is", "false"),
        Condition("Master", "MarketingPermission", "Is", "true"),
    ))


def test_nested_or_with_isnull_and_empty_cdata():
    # The pilot's "Phone consent" criteria: IsMailOffers AND (IsDunning false OR IsDunning null) AND PhoneConsent.
    xml = filter_xml(
        condition_xml("Master.IsMailOffers", "Is", "true"),
        set_xml(condition_xml("Master.IsDunning", "Is", "false"),
                condition_xml("Master.IsDunning", "IsNull", ""),
                operator="OR"),
        condition_xml("Master.PhoneConsent", "Is", "true"),
    )
    assert parse_criteria(xml) == ConditionGroup("AND", (
        Condition("Master", "IsMailOffers", "Is", "true"),
        ConditionGroup("OR", (
            Condition("Master", "IsDunning", "Is", "false"),
            Condition("Master", "IsDunning", "IsNull", None),
        )),
        Condition("Master", "PhoneConsent", "Is", "true"),
    ))


@pytest.mark.parametrize("wrappers", [1, 2, 3])
def test_value_inside_attribute_path_wrappers(wrappers):
    xml = filter_xml(condition_xml("Config.IGNOREPERM1", "Is", "true", wrappers=wrappers))
    assert parse_criteria(xml) == Condition("Config", "IGNOREPERM1", "Is", "true")


def test_field_name_with_a_space():
    xml = filter_xml(condition_xml("Config.Control Group Required", "Is", "true", wrappers=2))
    assert parse_criteria(xml) == Condition("Config", "Control Group Required", "Is", "true")


def test_key_splits_on_the_first_dot():
    xml = filter_xml(condition_xml("Config.Field.With.Dots", "Equal", "x"))
    condition = parse_criteria(xml)
    assert (condition.table, condition.field) == ("Config", "Field.With.Dots")


def test_nested_set_with_one_item_collapses():
    xml = filter_xml(condition_xml("A.x", "Is", "true"),
                     set_xml(condition_xml("A.y", "Is", "false"), operator="OR"))
    assert parse_criteria(xml) == ConditionGroup("AND", (
        Condition("A", "x", "Is", "true"),
        Condition("A", "y", "Is", "false"),
    ))


def test_set_operator_is_upper_cased():
    xml = filter_xml(condition_xml("A.x", "Is", "true"), condition_xml("A.y", "Is", "true"), operator="or")
    assert parse_criteria(xml).operator == "OR"


def test_values_are_kept_as_written():
    assert parse_criteria(filter_xml(condition_xml("A.x", "Equal", "EMAIL"))).value == "EMAIL"
    assert parse_criteria(filter_xml(condition_xml("A.x", "Equal", " Email "))).value == " Email "
    assert parse_criteria(filter_xml(condition_xml("A.x", "Equal", ""))).value == ""


def test_operators_without_value_get_none():
    assert parse_criteria(filter_xml(condition_xml("A.x", "IsNotNull", ""))).value is None
    assert parse_criteria(filter_xml(condition_xml("A.x", "IsNull", "", with_value=False))).value is None


def test_unknown_operator_is_parsed_and_rejected_only_when_evaluated():
    condition = parse_criteria(filter_xml(condition_xml("A.x", "Between", "1")))
    assert condition == Condition("A", "x", "Between", "1")
    with pytest.raises(UnsupportedOperator):
        evaluate_condition(condition, "1", "Number", False)


def test_xml_namespace_is_ignored():
    xml = ('<FilterDefinition xmlns="http://example.com/filter">'
           + set_xml(condition_xml("A.x", "Is", "true")) + "</FilterDefinition>")
    assert parse_criteria(xml) == Condition("A", "x", "Is", "true")


@pytest.mark.parametrize("xml", [
    "",
    "   ",
    "not xml at all",
    "<FilterDefinition><ConditionSet Operator='AND'>",
    "<ConditionSet Operator='AND'></ConditionSet>",
    "<FilterDefinition/>",
    "<FilterDefinition><ConditionSet Operator='AND'/></FilterDefinition>",
    filter_xml(condition_xml("A.x", "Is", "true"), set_xml(operator="OR")),
    filter_xml("<Unknown/>"),
    filter_xml(condition_xml("A.x", "Is", "true"), condition_xml("A.y", "Is", "true"), operator="XOR"),
    filter_xml(condition_xml("A.x", "Is", "true"), condition_xml("A.y", "Is", "true"), operator=""),
    filter_xml(condition_xml("NoDot", "Is", "true")),
    filter_xml(condition_xml(".x", "Is", "true")),
    filter_xml(condition_xml("A.", "Is", "true")),
    filter_xml(condition_xml("A.x", "", "true")),
    filter_xml(condition_xml("A.x", "Equal", "", with_value=False)),
    filter_xml('<Condition Key="A.x" Operator="Is"><Value>1</Value><Value>2</Value></Condition>'),
    filter_xml('<Condition Key="A.x" Operator="Is"><Other/><Value>1</Value></Condition>'),
    "<FilterDefinition>" + set_xml(condition_xml("A.x", "Is", "true"))
    + set_xml(condition_xml("A.y", "Is", "true")) + "</FilterDefinition>",
])
def test_bad_criteria_raise_criteria_error(xml):
    with pytest.raises(CriteriaError):
        parse_criteria(xml)


def test_non_string_criteria_raise_criteria_error():
    with pytest.raises(CriteriaError):
        parse_criteria(None)


# ---------------------------------------------------------------------------
# OPERATORS and evaluate_condition
# ---------------------------------------------------------------------------

def check(operator, actual, expected, field_type="Text", case_insensitive=False):
    """Evaluate one condition on a field holding ``actual``."""
    condition = Condition("T", "f", operator, None if operator in OPERATORS_WITHOUT_VALUE else expected)
    return evaluate_condition(condition, actual, field_type, case_insensitive)


def test_operator_table_holds_the_spec_operators():
    assert set(OPERATORS) == {
        "Is", "Equal", "IsNull",
        "NotEqual", "IsNotNull", "GreaterThan", "LessThan", "GreaterThanOrEqual", "LessThanOrEqual",
        "Contains", "BeginsWith", "EndsWith",
    }
    assert OPERATORS_WITHOUT_VALUE == {"IsNull", "IsNotNull"}


@pytest.mark.parametrize("actual, expected, result", [
    ("True", "true", True),
    ("true", "true", True),
    ("TRUE", "true", True),
    ("1", "true", True),
    ("False", "false", True),
    ("0", "false", True),
    ("false", "False", True),
    (" True ", "true", True),
    ("False", "true", False),
    ("1", "false", False),
    ("0", "true", False),
])
@pytest.mark.parametrize("operator", ["Is", "Equal"])
def test_boolean_equality_accepts_case_variants_and_digits(operator, actual, expected, result):
    assert check(operator, actual, expected, "Boolean") is result
    # Boolean comparison ignores letter case whatever the text setting says
    assert check(operator, actual, expected, "Boolean", case_insensitive=True) is result


def test_text_equality_follows_the_case_setting():
    assert check("Equal", "Email", "Email") is True
    assert check("Equal", "EMAIL", "Email") is False
    assert check("Equal", "EMAIL", "Email", case_insensitive=True) is True
    assert check("Is", "Email", "EMAIL", case_insensitive=True) is True
    assert check("Equal", "Email ", "Email") is False


@pytest.mark.parametrize("field_type", ["EmailAddress", "Phone", "Locale", "Geolocation", "", None])
def test_other_types_compare_as_text(field_type):
    assert check("Equal", "A@Example.com", "A@Example.com", field_type) is True
    assert check("Equal", "a@example.com", "A@Example.com", field_type) is False
    assert check("Equal", "a@example.com", "A@Example.com", field_type, case_insensitive=True) is True


def test_not_equal():
    assert check("NotEqual", "SMS", "Email") is True
    assert check("NotEqual", "Email", "Email") is False
    assert check("NotEqual", "EMAIL", "Email") is True
    assert check("NotEqual", "EMAIL", "Email", case_insensitive=True) is False
    assert check("NotEqual", "1", "true", "Boolean") is False


def test_number_comparisons_are_numeric():
    assert check("Equal", "5", "5.0", "Number") is True
    assert check("Equal", "5", "6", "Decimal") is False
    assert check("GreaterThan", "10", "9", "Number") is True       # as text "10" < "9"
    assert check("GreaterThan", "9", "9", "Number") is False
    assert check("LessThan", "9", "10", "Decimal") is True
    assert check("GreaterThanOrEqual", "9.0", "9", "Number") is True
    assert check("LessThanOrEqual", "8", "9", "Number") is True
    assert check("LessThanOrEqual", "10", "9", "Number") is False


def test_number_that_does_not_parse():
    assert check("GreaterThan", "abc", "9", "Number") is False
    assert check("LessThan", "abc", "9", "Number") is False
    assert check("Equal", "abc", "abc", "Number") is True
    assert check("Equal", "abc", "9", "Number") is False
    assert check("NotEqual", "abc", "9", "Number") is True


def test_date_only_condition_value_compares_the_date_part():
    assert check("Equal", "2026-10-11 10:30", "2026-10-11", "Date") is True
    assert check("Equal", "2026-10-12 00:00", "2026-10-11", "Date") is False
    assert check("GreaterThan", "2026-10-11 23:59", "2026-10-11", "Date") is False
    assert check("GreaterThan", "2026-10-12 00:00", "2026-10-11", "Date") is True
    assert check("GreaterThanOrEqual", "2026-10-11 08:00", "2026-10-11", "Date") is True
    assert check("LessThan", "2026-10-10 23:59", "2026-10-11", "Date") is True
    assert check("LessThanOrEqual", "2026-10-11 23:59", "2026-10-11", "Date") is True


def test_date_with_time_compares_the_time():
    assert check("Equal", "2026-10-11 10:30", "2026-10-11 10:00", "Date") is False
    assert check("Equal", "2026-10-11T10:30:00", "2026-10-11 10:30", "Date") is True
    assert check("GreaterThan", "2026-10-11 10:30", "2026-10-11 10:00", "Date") is True
    assert check("LessThan", "2026-10-11", "2026-10-11 10:00", "Date") is True
    assert check("Equal", "2026-10-11T10:30:00+02:00", "2026-10-11 08:30", "Date") is True


def test_date_that_does_not_parse():
    assert check("GreaterThan", "11/10/2026", "2026-10-11", "Date") is False
    assert check("Equal", "11/10/2026", "2026-10-11", "Date") is False
    assert check("Equal", "11/10/2026", "11/10/2026", "Date") is True


def test_text_ordering_compares_strings():
    assert check("GreaterThan", "b", "a") is True
    assert check("LessThan", "B", "a") is True
    assert check("LessThan", "B", "a", case_insensitive=True) is False


def test_contains_begins_with_ends_with():
    assert check("Contains", "NoClick_OB", "Click") is True
    assert check("Contains", "NoClick_OB", "click") is False
    assert check("Contains", "NoClick_OB", "click", case_insensitive=True) is True
    assert check("BeginsWith", "Open_Click_OB", "Open") is True
    assert check("BeginsWith", "Open_Click_OB", "open") is False
    assert check("BeginsWith", "Open_Click_OB", "open", case_insensitive=True) is True
    assert check("EndsWith", "Open_Click_OB", "_OB") is True
    assert check("EndsWith", "Open_Click_OB", "_ob") is False
    assert check("EndsWith", "Open_Click_OB", "_ob", case_insensitive=True) is True


@pytest.mark.parametrize("actual, result", [(None, True), ("", True), ("x", False), (" ", False), ("False", False)])
def test_is_null_and_is_not_null(actual, result):
    assert check("IsNull", actual, None) is result
    assert check("IsNotNull", actual, None) is (not result)


@pytest.mark.parametrize("operator", [
    "Is", "Equal", "NotEqual", "GreaterThan", "LessThan", "GreaterThanOrEqual", "LessThanOrEqual",
    "Contains", "BeginsWith", "EndsWith",
])
@pytest.mark.parametrize("actual", [None, ""])
def test_any_other_operator_on_null_is_false(operator, actual):
    assert check(operator, actual, "x") is False
    assert check(operator, actual, "false", "Boolean") is False


def test_condition_without_value_is_false_for_a_value_operator():
    assert evaluate_condition(Condition("T", "f", "Equal", None), "x", "Text", False) is False


def test_null_operators_ignore_the_condition_value():
    assert evaluate_condition(Condition("T", "f", "IsNull", "ignored"), None, "Text", False) is True


@pytest.mark.parametrize("operator", ["Between", "equal", "IsIn", ""])
def test_unknown_operator_raises_unsupported_operator(operator):
    with pytest.raises(UnsupportedOperator):
        evaluate_condition(Condition("T", "f", operator, "x"), "x", "Text", False)
