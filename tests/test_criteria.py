"""Unit tests for cjhelper.criteria: FilterDefinition parsing and condition evaluation."""

import pytest

from cjhelper.criteria import (
    OPERATORS,
    OPERATORS_WITHOUT_VALUE,
    CriteriaError,
    UnsupportedOperator,
    between_bounds,
    evaluate_condition,
    parse_criteria,
    split_attribute,
)
from cjhelper.model import SOURCE_CONTACT, SOURCE_JOURNEY, Condition, ConditionGroup, formula_text


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
    # Between used to be the example here; the extension section of the spec added it to the operators.
    condition = parse_criteria(filter_xml(condition_xml("A.x", "NotContains", "1")))
    assert condition == Condition("A", "x", "NotContains", "1")
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
    # Spec, "Extensions beyond the pilot", "Operators, types and values": the supported operators.
    assert set(OPERATORS) == {
        "Is", "Equal", "IsNull",
        "NotEqual", "IsNotNull", "GreaterThan", "LessThan", "GreaterThanOrEqual", "LessThanOrEqual",
        "Contains", "BeginsWith", "EndsWith", "Between",
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
    "Contains", "BeginsWith", "EndsWith", "Between",
])
@pytest.mark.parametrize("actual", [None, ""])
def test_any_other_operator_on_null_is_false(operator, actual):
    assert check(operator, actual, "x") is False
    assert check(operator, actual, "false", "Boolean") is False


def test_condition_without_value_is_false_for_a_value_operator():
    assert evaluate_condition(Condition("T", "f", "Equal", None), "x", "Text", False) is False


def test_null_operators_ignore_the_condition_value():
    assert evaluate_condition(Condition("T", "f", "IsNull", "ignored"), None, "Text", False) is True


@pytest.mark.parametrize("operator", ["NotContains", "equal", "IsIn", ""])
def test_unknown_operator_raises_unsupported_operator(operator):
    with pytest.raises(UnsupportedOperator):
        evaluate_condition(Condition("T", "f", operator, "x"), "x", "Text", False)


# ---------------------------------------------------------------------------
# Extensions beyond the pilot: Journey Data, attribute comparisons, Between
# ---------------------------------------------------------------------------

def journey_condition_xml(key, operator, value=""):
    """A Journey Data condition as the real exports write it: ephemeral attribute, no AttributePath."""
    return (f'<Condition IsEphemeralAttribute="true" Key="{key}" Operator="{operator}" UiMetaData="{{}}">'
            f"<Value><![CDATA[{value}]]></Value></Condition>")


def test_journey_data_key_names_the_event_and_the_field():
    xml = filter_xml(journey_condition_xml("Event.DEAudience-1.Score", "GreaterThan", "15"))
    assert parse_criteria(xml) == Condition("DEAudience-1", "Score", "GreaterThan", "15",
                                            source=SOURCE_JOURNEY)


def test_journey_data_key_without_the_ephemeral_attribute_is_journey_data():
    xml = filter_xml(condition_xml("Event.APIEvent-1.Field With Spaces", "IsNull"))
    condition = parse_criteria(xml)
    assert (condition.source, condition.table, condition.field) == (SOURCE_JOURNEY, "APIEvent-1", "Field With Spaces")


def test_contact_data_key_keeps_the_contact_source():
    condition = parse_criteria(filter_xml(condition_xml("Optin.SubscriberKey", "IsNull")))
    assert (condition.source, condition.table, condition.value_attribute) == (SOURCE_CONTACT, "Optin", None)


def test_ephemeral_attribute_on_a_key_that_is_not_journey_data_is_rejected():
    xml = filter_xml('<Condition IsEphemeralAttribute="true" Key="Master.Perm" Operator="Is">'
                     "<Value><![CDATA[true]]></Value></Condition>")
    with pytest.raises(CriteriaError, match="Journey Data"):
        parse_criteria(xml)


def test_value_parameter_name_is_an_attribute_not_an_empty_value():
    xml = filter_xml('<Condition Key="Optin.SubscriberKey" Operator="Equal" UiMetaData="{}" '
                     'ValueParameterName="Event.CloudPagesSma-7.SubscriberKey"><Value><![CDATA[]]></Value></Condition>')
    condition = parse_criteria(xml)
    assert condition == Condition("Optin", "SubscriberKey", "Equal", None, source=SOURCE_CONTACT,
                                  value_attribute="Event.CloudPagesSma-7.SubscriberKey")
    assert formula_text(condition) == "Optin.SubscriberKey Equal Event.CloudPagesSma-7.SubscriberKey"


def test_value_is_reference_takes_the_attribute_from_the_value():
    xml = filter_xml('<Condition IsEphemeralAttribute="true" Key="Event.DEAudience-1.SubscriberKey" Operator="Equal" '
                     'ValueIsReference="true"><Value><![CDATA[Log Set.SubscriberKey]]></Value></Condition>')
    condition = parse_criteria(xml)
    assert (condition.source, condition.table, condition.field) == (SOURCE_JOURNEY, "DEAudience-1", "SubscriberKey")
    assert (condition.value, condition.value_attribute) == (None, "Log Set.SubscriberKey")


@pytest.mark.parametrize("xml", [
    # an attribute and a literal at the same time
    '<Condition Key="A.x" Operator="Equal" ValueParameterName="Event.E.y"><Value><![CDATA[1]]></Value></Condition>',
    # a reference without the attribute it refers to
    '<Condition Key="A.x" Operator="Equal" ValueIsReference="true"><Value><![CDATA[]]></Value></Condition>',
])
def test_contradictory_attribute_comparisons_are_rejected(xml):
    with pytest.raises(CriteriaError):
        parse_criteria(filter_xml(xml))


@pytest.mark.parametrize("text, parts", [
    ("Event.DEAudience-1.Score", (SOURCE_JOURNEY, "DEAudience-1", "Score")),
    ("Config Set.Control Group", (SOURCE_CONTACT, "Config Set", "Control Group")),
    ("Event.Field", (SOURCE_CONTACT, "Event", "Field")),     # no event key: read as a set called Event
    ("NoDot", None),
    (".x", None),
])
def test_split_attribute(text, parts):
    assert split_attribute(text) == parts


@pytest.mark.parametrize("value, bounds", [
    ("10|20", ("10", "20")),
    (" 8 | 15 ", ("8", "15")),
    ("10000", None),
    ("1|2|3", None),
    ("|5", None),
    (None, None),
])
def test_between_bounds(value, bounds):
    assert between_bounds(value) == bounds


@pytest.mark.parametrize("actual, result", [
    ("100", True), ("100.0000", True), ("250.5", True), ("300", True),     # both bounds included (confirmed)
    ("99.9999", False), ("300.0001", False), ("-1", False), ("abc", False),
])
@pytest.mark.parametrize("field_type", ["Number", "Decimal"])
def test_between_includes_both_bounds(field_type, actual, result):
    assert check("Between", actual, "100|300", field_type) is result


def test_between_on_dates_and_text():
    assert check("Between", "2026-10-11 10:00", "2026-10-11|2026-10-12", "Date") is True
    assert check("Between", "2026-10-13 00:00", "2026-10-11|2026-10-12", "Date") is False
    assert check("Between", "b", "a|c") is True
    assert check("Between", "d", "a|c") is False
    assert check("Between", "5", "10|1", "Number") is False      # reversed bounds match nothing


def test_between_value_not_written_low_high_cannot_be_evaluated():
    with pytest.raises(UnsupportedOperator, match="basso\\|alto"):
        check("Between", "5", "10000", "Number")


@pytest.mark.parametrize("actual, result", [("TST_R01_C0001", True), ("x", True), (None, False), ("", False)])
def test_attribute_comparison_reads_whether_the_row_is_there(actual, result):
    condition = Condition("Optin", "SubscriberKey", "Equal", None, value_attribute="Event.E.SubscriberKey")
    assert evaluate_condition(condition, actual, "Text", False) is result


def test_attribute_comparison_with_another_operator_cannot_be_evaluated():
    condition = Condition("Optin", "SubscriberKey", "NotEqual", None, value_attribute="Event.E.SubscriberKey")
    with pytest.raises(UnsupportedOperator):
        evaluate_condition(condition, "x", "Text", False)
