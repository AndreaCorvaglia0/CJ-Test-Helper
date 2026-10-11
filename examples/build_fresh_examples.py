"""Builders for the fresh test engineer's examples (package.json only; expected.json and README.md by hand).

Reuses the helpers of examples/build_examples.py so every package has the pilot's shape.
Run:  python examples/build_fresh_examples.py [name ...]   (writes examples/<name>/package.json and validates)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

EXAMPLES_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EXAMPLES_DIR))
import build_examples as B  # noqa: E402
from build_examples import (Journey, Package, add_email_asset, add_entry_source, add_journey, boolean, criteria,  # noqa: E402
                            cset, date, email_field, export, log_table, log_update, phone, setup_contact_only,
                            setup_with_config, sql_master_config, sql_master_only, table_sql, text)


# 1 ---------------------------------------------------------------------------------------------
def build_boolean_order() -> dict:
    pkg = Package("boolean_order", "EX boolean order")
    setup_contact_only(pkg, [boolean("OptIn"), boolean("Strict", nullable=False, default="False")])
    m = "DE_Master"
    j = Journey(pkg, "EX_BooleanOrder")
    j.decision("SPLIT-1", "Opt-in", [
        ("path_a", "not true", criteria(cset("OR", pkg.cond(m, "OptIn", "Is", "false"), pkg.cond(m, "OptIn", "IsNull", ""))),
         "UPDATE-1", "( OptIn is False OR OptIn is null )"),
        ("path_b", "false", criteria(pkg.cond(m, "OptIn", "Is", "false")), "UPDATE-2", "OptIn is False"),
        ("path_c", "true", criteria(pkg.cond(m, "OptIn", "Is", "true")), "UPDATE-3", "OptIn is True"),
        ("remainder_path", "Remainder", None, "UPDATE-4", None)])
    log_update(j, "UPDATE-1", "Not opted in", "NotOptedIn", "SPLIT-2")
    log_update(j, "UPDATE-2", "Opted out", "OptedOut", None)
    log_update(j, "UPDATE-3", "Opted in", "OptedIn", "SPLIT-2")
    log_update(j, "UPDATE-4", "Opt-in other", "OptInOther", None)
    j.decision("SPLIT-2", "Strict", [
        ("path_a", "null", criteria(pkg.cond(m, "Strict", "IsNull", "")), "UPDATE-5", "Strict is null"),
        ("path_b", "false", criteria(pkg.cond(m, "Strict", "Is", "false")), "UPDATE-6", "Strict is False"),
        ("path_c", "true", criteria(pkg.cond(m, "Strict", "Is", "true")), "UPDATE-7", "Strict is True"),
        ("remainder_path", "Remainder", None, "UPDATE-8", None)])
    log_update(j, "UPDATE-5", "Strict empty", "StrictEmpty", None)
    log_update(j, "UPDATE-6", "Strict false", "StrictFalse", None)
    log_update(j, "UPDATE-7", "Strict true", "StrictTrue", None)
    log_update(j, "UPDATE-8", "Strict other", "StrictOther", None)
    event = add_entry_source(pkg, j.name, "DE_Entry", "Q_EX_BooleanOrder_Entry", sql_master_only(pkg))
    add_journey(pkg, j, event)
    return export(pkg)


# 2 ---------------------------------------------------------------------------------------------
def build_update_scenario_field() -> dict:
    pkg = Package("update_scenario_field", "EX update scenario field")
    setup_with_config(pkg, [], [text("MODE", 20)])
    c = "DE_Config"

    def mode(v):
        return criteria(pkg.cond(c, "MODE", "Equal", v))

    j = Journey(pkg, "EX_UpdateScenarioField")
    j.decision("SPLIT-1", "Mode A?", [
        ("path_a", "A", mode("A"), "UPDATE-1", "MODE equal A"),
        ("remainder_path", "Remainder", None, "SPLIT-3", None)])
    j.update("UPDATE-1", "Switch mode to B", c, [("MODE", "B")], "SPLIT-2")
    j.decision("SPLIT-2", "Mode after switch", [
        ("path_a", "A", mode("A"), "UPDATE-3", "MODE equal A"),
        ("path_b", "B", mode("B"), "UPDATE-4", "MODE equal B"),
        ("remainder_path", "Remainder", None, "UPDATE-5", None)])
    j.decision("SPLIT-3", "Mode B?", [
        ("path_a", "B", mode("B"), "UPDATE-6", "MODE equal B"),
        ("remainder_path", "Remainder", None, "UPDATE-7", None)])
    log_update(j, "UPDATE-3", "Still A", "StillA", None)
    log_update(j, "UPDATE-4", "Switched to B", "SwitchedB", None)
    log_update(j, "UPDATE-5", "Switch lost", "SwitchLost", None)
    log_update(j, "UPDATE-6", "Was B", "WasB", None)
    log_update(j, "UPDATE-7", "Neither", "Neither", None)
    event = add_entry_source(pkg, j.name, "DE_Entry", "Q_EX_UpdateScenarioField_Entry", sql_master_config(pkg))
    add_journey(pkg, j, event)
    return export(pkg)


# 3 ---------------------------------------------------------------------------------------------
def build_two_emails_engagement() -> dict:
    pkg = Package("two_emails_engagement", "EX two emails engagement")
    setup_with_config(pkg, [boolean("Perm")], [date("WAIT1", nullable=False, default="GETDATE()"),
                                               date("WAIT2", nullable=False, default="GETDATE()")])
    add_email_asset(pkg, "900301", "Welcome", "WELCOME", with_link=False)
    add_email_asset(pkg, "900302", "Reminder", "REMINDER", with_link=True)
    j = Journey(pkg, "EX_TwoEmailsEngagement")
    j.decision("SPLIT-1", "Permission", [
        ("path_a", "true", criteria(pkg.cond("DE_Master", "Perm", "Is", "true")), "EMAIL-1", "Perm is True"),
        ("remainder_path", "false", None, "UPDATE-4", None)])
    j.email("EMAIL-1", "900301", "WAITATTR-1")
    j.wait_attribute("WAITATTR-1", "DE_Config", "WAIT1", "ENGAGE-1")
    j.engagement("ENGAGE-1", "Open Welcome", "open", "EMAIL-1", "Welcome", yes_next="UPDATE-1", no_next="EMAIL-2")
    j.email("EMAIL-2", "900302", "WAITATTR-2")
    j.wait_attribute("WAITATTR-2", "DE_Config", "WAIT2", "ENGAGE-2")
    j.engagement("ENGAGE-2", "Click Reminder", "click", "EMAIL-2", "Reminder", yes_next="UPDATE-2", no_next="UPDATE-3")
    log_update(j, "UPDATE-1", "Opened welcome", "OpenedWelcome", None)
    log_update(j, "UPDATE-2", "Clicked reminder", "ClickedReminder", None)
    log_update(j, "UPDATE-3", "Ignored both", "IgnoredBoth", None)
    log_update(j, "UPDATE-4", "No permission", "NoPermission", None)
    event = add_entry_source(pkg, j.name, "DE_Entry", "Q_EX_TwoEmailsEngagement_Entry", sql_master_config(pkg))
    add_journey(pkg, j, event)
    return export(pkg)


# 4 ---------------------------------------------------------------------------------------------
def build_engagement_after_join() -> dict:
    pkg = Package("engagement_after_join", "EX engagement after join")
    setup_contact_only(pkg, [boolean("Perm")])
    add_email_asset(pkg, "900401", "Welcome", "WELCOME", with_link=False)
    j = Journey(pkg, "EX_EngagementAfterJoin")
    j.decision("SPLIT-1", "Permission", [
        ("path_a", "true", criteria(pkg.cond("DE_Master", "Perm", "Is", "true")), "EMAIL-1", "Perm is True"),
        ("remainder_path", "false", None, "WAIT-1", None)])
    j.email("EMAIL-1", "900401", "WAIT-1")
    j.wait_duration("WAIT-1", "ENGAGE-1", 2, "DAYS")
    j.engagement("ENGAGE-1", "Open Welcome", "open", "EMAIL-1", "Welcome", yes_next="UPDATE-1", no_next="UPDATE-2")
    log_update(j, "UPDATE-1", "Opened", "Opened", None)
    log_update(j, "UPDATE-2", "Not opened", "NotOpened", None)
    event = add_entry_source(pkg, j.name, "DE_Entry", "Q_EX_EngagementAfterJoin_Entry", sql_master_only(pkg))
    add_journey(pkg, j, event)
    return export(pkg)


# 5 ---------------------------------------------------------------------------------------------
def build_random_then_contact_split() -> dict:
    pkg = Package("random_then_contact_split", "EX random then contact split")
    setup_contact_only(pkg, [boolean("Flag")])
    j = Journey(pkg, "EX_RandomThenContactSplit")
    j.random_split("RANDOM-1", [("branchResult-1", 70, "SPLIT-2"), ("branchResult-2", 30, "UPDATE-3")])
    j.decision("SPLIT-2", "Flag", [
        ("path_a", "true", criteria(pkg.cond("DE_Master", "Flag", "Is", "true")), "UPDATE-1", "Flag is True"),
        ("remainder_path", "false", None, "UPDATE-2", None)])
    log_update(j, "UPDATE-1", "Flag set", "FlagSet", None)
    log_update(j, "UPDATE-2", "Flag not set", "FlagNotSet", None)
    log_update(j, "UPDATE-3", "Holdout", "Holdout", None)
    event = add_entry_source(pkg, j.name, "DE_Entry", "Q_EX_RandomThenContactSplit_Entry", sql_master_only(pkg))
    add_journey(pkg, j, event)
    return export(pkg)


# 6 ---------------------------------------------------------------------------------------------
def build_wait_contact_date_engagement() -> dict:
    pkg = Package("wait_contact_date_engagement", "EX wait contact date engagement")
    pkg.table("DE_Entry", [text("ContactId", 50, pk=True, nullable=False), email_field()], sendable_field="ContactId")
    pkg.table("DE_Master", [text("ContactId", 50, pk=True, nullable=False), text("FirstName"), email_field(),
                            phone(), boolean("Perm")], sendable_field="ContactId")
    pkg.table("DE_Dates", [text("ContactId", 50, pk=True, nullable=False), date("NextContact"),
                           date("LastSeen")], sendable_field="ContactId")
    log_table(pkg)
    pkg.contact_model([("DE_Master", "ContactId", ""), ("DE_Entry", "ContactId", "ContactId"),
                       ("DE_Dates", "ContactId", "ContactId")])
    add_email_asset(pkg, "900601", "Welcome", "WELCOME", with_link=False)
    j = Journey(pkg, "EX_WaitContactDateEngagement")
    j.decision("SPLIT-1", "Permission", [
        ("path_a", "true", criteria(pkg.cond("DE_Master", "Perm", "Is", "true")), "EMAIL-1", "Perm is True"),
        ("remainder_path", "false", None, "UPDATE-3", None)])
    j.email("EMAIL-1", "900601", "WAITATTR-1")
    j.wait_attribute("WAITATTR-1", "DE_Dates", "NextContact", "ENGAGE-1")
    j.engagement("ENGAGE-1", "Open Welcome", "open", "EMAIL-1", "Welcome", yes_next="UPDATE-1", no_next="UPDATE-2")
    log_update(j, "UPDATE-1", "Opened", "Opened", None)
    log_update(j, "UPDATE-2", "Not opened", "NotOpened", None)
    log_update(j, "UPDATE-3", "No permission", "NoPermission", None)
    event = add_entry_source(pkg, j.name, "DE_Entry", "Q_EX_WaitContactDateEngagement_Entry", sql_master_only(pkg))
    add_journey(pkg, j, event)
    return export(pkg)


# 7 ---------------------------------------------------------------------------------------------
def build_short_text_field() -> dict:
    pkg = Package("short_text_field", "EX short text field")
    setup_contact_only(pkg, [text("Code", 3), text("Tag", 3), text("Two", 2), text("One", 1, nullable=False)])
    m = "DE_Master"

    def code(v):
        return criteria(pkg.cond(m, "Code", "Equal", v))

    j = Journey(pkg, "EX_ShortTextField")
    j.decision("SPLIT-1", "Code", [
        ("path_a", "A", code("A"), "UPDATE-1", "Code equal A"),
        ("path_b", "B", code("B"), "UPDATE-2", "Code equal B"),
        ("path_c", "ABC", code("ABC"), "UPDATE-3", "Code equal ABC"),
        ("path_d", "ABCD", code("ABCD"), "UPDATE-4", "Code equal ABCD"),
        ("remainder_path", "Remainder", None, "UPDATE-5", None)])
    log_update(j, "UPDATE-1", "Code A", "CodeA", None)
    log_update(j, "UPDATE-2", "Code B", "CodeB", None)
    log_update(j, "UPDATE-3", "Code ABC", "CodeABC", None)
    log_update(j, "UPDATE-4", "Code ABCD", "CodeABCD", None)
    log_update(j, "UPDATE-5", "Code other", "CodeOther", None)
    event = add_entry_source(pkg, j.name, "DE_Entry", "Q_EX_ShortTextField_Entry", sql_master_only(pkg))
    add_journey(pkg, j, event)
    return export(pkg)


# 8 ---------------------------------------------------------------------------------------------
def build_entry_left_join_literal() -> dict:
    pkg = Package("entry_left_join_literal", "EX entry left join literal")
    pkg.table("DE_Entry", [text("ContactId", 50, pk=True, nullable=False), email_field(), text("Source", 20),
                           text("Segment", 20), date("LoadedOn")], sendable_field="ContactId")
    pkg.table("DE_Master", [text("ContactId", 50, pk=True, nullable=False), text("FirstName"), email_field(),
                            phone(), boolean("Active", nullable=False, default="False"), boolean("Perm")],
              sendable_field="ContactId")
    pkg.table("DE_Extra", [text("ContactId", 50, pk=True, nullable=False), text("Segment", 20)],
              sendable_field="ContactId")
    log_table(pkg)
    pkg.contact_model([("DE_Master", "ContactId", ""), ("DE_Entry", "ContactId", "ContactId")])
    j = Journey(pkg, "EX_EntryLeftJoinLiteral")
    j.decision("SPLIT-1", "Permission", [
        ("path_a", "true", criteria(pkg.cond("DE_Master", "Perm", "Is", "true")), "UPDATE-1", "Perm is True"),
        ("remainder_path", "false", None, "UPDATE-2", None)])
    log_update(j, "UPDATE-1", "Allowed", "Allowed", None)
    log_update(j, "UPDATE-2", "Not allowed", "NotAllowed", None)
    sql = ("SELECT\n    M.ContactId,\n    M.Emailaddress,\n    'WELCOME' AS Source,\n    X.Segment,\n"
           "    GETDATE() AS LoadedOn\nFROM %s M\nLEFT JOIN %s X ON M.ContactId = X.ContactId\n"
           "WHERE M.Active = 'True'" % (table_sql(pkg.tables["DE_Master"]), table_sql(pkg.tables["DE_Extra"])))
    event = add_entry_source(pkg, j.name, "DE_Entry", "Q_EX_EntryLeftJoinLiteral_Entry", sql)
    add_journey(pkg, j, event)
    return export(pkg)


# 9 ---------------------------------------------------------------------------------------------
def build_custom_keys() -> dict:
    pkg = Package("custom_keys", "EX custom keys")
    pkg.table("DE_Entry", [text("SubscriberKey", 30, pk=True, nullable=False), email_field(),
                           text("WaveRef", 30, nullable=False)], sendable_field="SubscriberKey")
    pkg.table("DE_Customer", [text("CustNo", 30, pk=True, nullable=False), email_field(), phone(),
                              text("WaveRef", 30, nullable=False), text("Tier", 10)], sendable_field="CustNo")
    pkg.table("DE_Wave", [text("WaveCode", 30, pk=True, nullable=False), text("CHANNEL", 10, nullable=False),
                          boolean("ACTIVE", nullable=False, default="False")])
    log_table(pkg)
    pkg.contact_model([("DE_Customer", "CustNo", ""), ("DE_Entry", "CustNo", "SubscriberKey"),
                       ("DE_Wave", "WaveRef", "WaveCode")])
    j = Journey(pkg, "EX_CustomKeys")
    j.decision("SPLIT-1", "Channel", [
        ("path_a", "Email", criteria(pkg.cond("DE_Wave", "CHANNEL", "Equal", "Email")), "SPLIT-2", "CHANNEL equal Email"),
        ("path_b", "SMS", criteria(pkg.cond("DE_Wave", "CHANNEL", "Equal", "SMS")), "UPDATE-2", "CHANNEL equal SMS"),
        ("remainder_path", "Remainder", None, "UPDATE-3", None)])
    j.decision("SPLIT-2", "Gold tier", [
        ("path_a", "Gold", criteria(pkg.cond("DE_Customer", "Tier", "Equal", "Gold")), "UPDATE-4", "Tier equal Gold"),
        ("remainder_path", "Remainder", None, "UPDATE-5", None)])
    log_update(j, "UPDATE-2", "SMS wave", "SmsWave", None)
    log_update(j, "UPDATE-3", "Other wave", "OtherWave", None)
    log_update(j, "UPDATE-4", "Gold email", "GoldEmail", None)
    log_update(j, "UPDATE-5", "Standard email", "StandardEmail", None)
    sql = ("SELECT\n    C.CustNo AS SubscriberKey,\n    C.Emailaddress,\n    W.WaveCode AS WaveRef\n"
           "FROM %s C\nJOIN %s W ON C.WaveRef = W.WaveCode\nWHERE W.ACTIVE = 'True'"
           % (table_sql(pkg.tables["DE_Customer"]), table_sql(pkg.tables["DE_Wave"])))
    event = add_entry_source(pkg, j.name, "DE_Entry", "Q_EX_CustomKeys_Entry", sql)
    add_journey(pkg, j, event)
    return export(pkg)


# 10 --------------------------------------------------------------------------------------------
ODD_VALUES = [("path_a", " Gold", "space Gold"), ("path_b", "Gold", "Gold"), ("path_c", "O'Brien", "apostrophe"),
              ("path_d", 'say "hi", ok', "quotes and comma"), ("path_e", "Silver ", "Silver space")]


def build_odd_condition_values() -> dict:
    pkg = Package("odd_condition_values", "EX odd condition values")
    setup_contact_only(pkg, [text("Customer Tier", 30)])
    m = "DE_Master"
    j = Journey(pkg, "EX_OddConditionValues")
    outs = []
    for i, (okey, v, label) in enumerate(ODD_VALUES, start=1):
        outs.append((okey, label, criteria(pkg.cond(m, "Customer Tier", "Equal", v)), "UPDATE-%d" % i,
                     "Customer Tier equal %s" % v))
    outs.append(("remainder_path", "Remainder", None, "UPDATE-6", None))
    j.decision("SPLIT-1", "Customer tier", outs)
    for i in range(1, 7):
        log_update(j, "UPDATE-%d" % i, "Tier %d" % i, "Tier%d" % i, None)
    event = add_entry_source(pkg, j.name, "DE_Entry", "Q_EX_OddConditionValues_Entry", sql_master_only(pkg))
    add_journey(pkg, j, event)
    return export(pkg)


# 11 --------------------------------------------------------------------------------------------
def build_two_journeys() -> dict:
    pkg = Package("two_journeys", "EX two journeys")
    pkg.table("DE_Entry", [text("ContactId", 50, pk=True, nullable=False), email_field()], sendable_field="ContactId")
    pkg.table("DE_Master", [text("ContactId", 50, pk=True, nullable=False), text("FirstName"), email_field(),
                            phone(), text("Region", 10, nullable=False), boolean("Perm")], sendable_field="ContactId")
    pkg.table("DE_Other", [text("ContactId", 50, pk=True, nullable=False), boolean("OtherFlag")],
              sendable_field="ContactId")
    log_table(pkg)
    pkg.contact_model([("DE_Master", "ContactId", ""), ("DE_Entry", "ContactId", "ContactId"),
                       ("DE_Other", "ContactId", "ContactId")])
    # First journey (NOT selected): reads DE_Other, its entry query filters Region = 'NORTH'.
    j1 = Journey(pkg, "EX_FirstJourney")
    j1.decision("SPLIT-1", "Other flag", [
        ("path_a", "true", criteria(pkg.cond("DE_Other", "OtherFlag", "Is", "true")), "UPDATE-1", "OtherFlag is True"),
        ("remainder_path", "false", None, "UPDATE-2", None)])
    log_update(j1, "UPDATE-1", "First yes", "FirstYes", None)
    log_update(j1, "UPDATE-2", "First no", "FirstNo", None)
    ev1 = add_entry_source(pkg, j1.name, "DE_Entry", "Q_EX_FirstJourney_Entry",
                           sql_master_only(pkg, "M.Region = 'NORTH'"))
    add_journey(pkg, j1, ev1)
    # Second journey (selected): reads DE_Master.Perm, its entry query filters Region = 'SOUTH'.
    j2 = Journey(pkg, "EX_SecondJourney")
    j2.decision("SPLIT-A", "Permission", [
        ("path_a", "true", criteria(pkg.cond("DE_Master", "Perm", "Is", "true")), "WAIT-A", "Perm is True"),
        ("remainder_path", "false", None, "UPDATE-B", None)])
    j2.wait_duration("WAIT-A", "UPDATE-A")
    log_update(j2, "UPDATE-A", "Second yes", "SecondYes", "UPDATE-C")
    log_update(j2, "UPDATE-B", "Second no", "SecondNo", None)
    log_update(j2, "UPDATE-C", "Second done", "SecondDone", None)
    ev2 = add_entry_source(pkg, j2.name, "DE_Entry", "Q_EX_SecondJourney_Entry",
                           sql_master_only(pkg, "M.Region = 'SOUTH'"))
    add_journey(pkg, j2, ev2)          # last added = selected (export() lists pkg.journey_id)
    return export(pkg)


# 12 --------------------------------------------------------------------------------------------
def build_other_value_collision() -> dict:
    pkg = Package("other_value_collision", "EX other value collision")
    setup_with_config(pkg, [text("Lvl", 3, nullable=False)], [text("CHANNEL", 50, nullable=False)])
    j = Journey(pkg, "EX_OtherValueCollision")
    j.decision("SPLIT-1", "Channel", [
        ("path_a", "OTHER", criteria(pkg.cond("DE_Config", "CHANNEL", "Equal", "OTHER")), "UPDATE-1",
         "CHANNEL equal OTHER"),
        ("path_b", "Email", criteria(pkg.cond("DE_Config", "CHANNEL", "Equal", "Email")), "SPLIT-2",
         "CHANNEL equal Email"),
        ("remainder_path", "Remainder", None, "UPDATE-3", None)])
    j.decision("SPLIT-2", "Level", [
        ("path_a", "OTH", criteria(pkg.cond("DE_Master", "Lvl", "Equal", "OTH")), "UPDATE-4", "Lvl equal OTH"),
        ("path_b", "A", criteria(pkg.cond("DE_Master", "Lvl", "Equal", "A")), "UPDATE-5", "Lvl equal A"),
        ("remainder_path", "Remainder", None, "UPDATE-6", None)])
    log_update(j, "UPDATE-1", "Channel OTHER", "ChannelOther", None)
    log_update(j, "UPDATE-3", "Channel remainder", "ChannelRemainder", None)
    log_update(j, "UPDATE-4", "Level OTH", "LevelOTH", None)
    log_update(j, "UPDATE-5", "Level A", "LevelA", None)
    log_update(j, "UPDATE-6", "Level other", "LevelOther", None)
    event = add_entry_source(pkg, j.name, "DE_Entry", "Q_EX_OtherValueCollision_Entry", sql_master_config(pkg))
    add_journey(pkg, j, event)
    return export(pkg)


FRESH = {
    "boolean_order": build_boolean_order,
    "update_scenario_field": build_update_scenario_field,
    "two_emails_engagement": build_two_emails_engagement,
    "engagement_after_join": build_engagement_after_join,
    "random_then_contact_split": build_random_then_contact_split,
    "wait_contact_date_engagement": build_wait_contact_date_engagement,
    "short_text_field": build_short_text_field,
    "entry_left_join_literal": build_entry_left_join_literal,
    "custom_keys": build_custom_keys,
    "odd_condition_values": build_odd_condition_values,
    "two_journeys": build_two_journeys,
    "other_value_collision": build_other_value_collision,
}


def main(names=None) -> int:
    names = names or list(FRESH)
    for name in names:
        d = EXAMPLES_DIR / name
        d.mkdir(exist_ok=True)
        (d / "package.json").write_text(json.dumps(FRESH[name](), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for name in names:
        d = EXAMPLES_DIR / name
        branches = B.validate_package(d / "package.json")
        if (d / "expected.json").exists():
            B.validate_expected(d / "expected.json", branches)
        print("ok  %-30s %3d split branches %s" % (name, len(branches), branches))
    return 0



# ================================ batch 2 ======================================================
from build_examples import ref, GROUP_NAME  # noqa: E402


def build_entry_filter_vs_split() -> dict:
    pkg = Package("entry_filter_vs_split", "EX entry filter vs split")
    setup_contact_only(pkg, [text("Tier", 10)])
    m = "DE_Master"
    j = Journey(pkg, "EX_EntryFilterVsSplit")
    j.decision("SPLIT-1", "Tier", [
        ("path_a", "Silver", criteria(pkg.cond(m, "Tier", "Equal", "Silver")), "UPDATE-1", "Tier equal Silver"),
        ("path_b", "Gold", criteria(pkg.cond(m, "Tier", "Equal", "Gold")), "UPDATE-2", "Tier equal Gold"),
        ("remainder_path", "Remainder", None, "UPDATE-3", None)])
    log_update(j, "UPDATE-1", "Silver", "Silver", None)
    log_update(j, "UPDATE-2", "Gold", "Gold", None)
    log_update(j, "UPDATE-3", "Other tier", "OtherTier", None)
    event = add_entry_source(pkg, j.name, "DE_Entry", "Q_EX_EntryFilterVsSplit_Entry",
                             sql_master_only(pkg, "M.Tier = 'Gold'"))
    add_journey(pkg, j, event)
    return export(pkg)


def build_entry_column_split() -> dict:
    pkg = Package("entry_column_split", "EX entry column split")
    pkg.table("DE_Entry", [text("ContactId", 50, pk=True, nullable=False), email_field(), text("Segment", 20),
                           text("Source", 20)], sendable_field="ContactId")
    pkg.table("DE_Master", [text("ContactId", 50, pk=True, nullable=False), text("FirstName"), email_field(),
                            phone(), text("Segment", 20)], sendable_field="ContactId")
    log_table(pkg)
    pkg.contact_model([("DE_Master", "ContactId", ""), ("DE_Entry", "ContactId", "ContactId")])
    e = "DE_Entry"
    j = Journey(pkg, "EX_EntryColumnSplit")
    j.decision("SPLIT-1", "Segment", [
        ("path_a", "Gold", criteria(pkg.cond(e, "Segment", "Equal", "Gold")), "UPDATE-1", "Segment equal Gold"),
        ("remainder_path", "Remainder", None, "SPLIT-2", None)])
    j.decision("SPLIT-2", "Source", [
        ("path_a", "PARTNER", criteria(pkg.cond(e, "Source", "Equal", "PARTNER")), "UPDATE-2", "Source equal PARTNER"),
        ("remainder_path", "Remainder", None, "UPDATE-3", None)])
    log_update(j, "UPDATE-1", "Gold segment", "GoldSegment", None)
    log_update(j, "UPDATE-2", "Partner source", "PartnerSource", None)
    log_update(j, "UPDATE-3", "Other", "Other", None)
    sql = ("SELECT\n    M.ContactId,\n    M.Emailaddress,\n    M.Segment,\n    'WELCOME' AS Source\nFROM %s M"
           % table_sql(pkg.tables["DE_Master"]))
    event = add_entry_source(pkg, j.name, "DE_Entry", "Q_EX_EntryColumnSplit_Entry", sql)
    add_journey(pkg, j, event)
    return export(pkg)


def build_sql_variants() -> dict:
    pkg = Package("sql_variants", "EX sql variants")
    pkg.table("DE_Entry", [text("ContactId", 50, pk=True, nullable=False), email_field(),
                           text("CampaignName", 100, nullable=False)], sendable_field="ContactId")
    pkg.table("DE_Master", [text("ContactId", 50, pk=True, nullable=False), text("FirstName"), email_field(),
                            phone(), text("CampaignName", 100, nullable=False), boolean("Perm")],
              sendable_field="ContactId")
    pkg.table("DE_Config", [text("CampaignName", 100, pk=True, nullable=False), text("CHANNEL", 20, nullable=False),
                            date("START_DATE", nullable=False, default="GETDATE()"),
                            date("END_DATE", nullable=False, default="GETDATE()"),
                            boolean("ACTIVE", nullable=False, default="False")])
    log_table(pkg)
    pkg.contact_model([("DE_Master", "ContactId", ""), ("DE_Entry", "ContactId", "ContactId"),
                       ("DE_Config", "CampaignName", "CampaignName")])
    j = Journey(pkg, "EX_SqlVariants")
    j.decision("SPLIT-1", "Channel", [
        ("path_a", "Email", criteria(pkg.cond("DE_Config", "CHANNEL", "Equal", "Email")), "SPLIT-2", "CHANNEL equal Email"),
        ("remainder_path", "Remainder", None, "UPDATE-3", None)])
    j.decision("SPLIT-2", "Permission", [
        ("path_a", "true", criteria(pkg.cond("DE_Master", "Perm", "Is", "true")), "UPDATE-1", "Perm is True"),
        ("remainder_path", "false", None, "UPDATE-2", None)])
    log_update(j, "UPDATE-1", "Email allowed", "EmailAllowed", None)
    log_update(j, "UPDATE-2", "Email blocked", "EmailBlocked", None)
    log_update(j, "UPDATE-3", "Other channel", "OtherChannel", None)
    sql = ("select m.ContactId, m.Emailaddress, c.CampaignName\n"
           "from ENT.[DE_Master] as m\n"
           "inner join ENT.[DE_Config] as c on c.CampaignName = m.CampaignName\n"
           "where c.ACTIVE = 1\n"
           "and GETDATE() BETWEEN c.START_DATE AND c.END_DATE")
    event = add_entry_source(pkg, j.name, "DE_Entry", "Q_EX_SqlVariants_Entry", sql)
    add_journey(pkg, j, event)
    return export(pkg)


def _contact_model_named(pkg, chain, set_names):
    """Like Package.contact_model, but each attribute set gets the name set_names[table] (not the table name)."""
    pkg.group_id = pkg.gid("group", GROUP_NAME)
    pkg.add("attributeGroups", pkg.group_id, {
        "attributeGroupIconKey": "et-icon-databas", "attributeGroupType": "Standard",
        "definitionName": {"value": GROUP_NAME}, "name": GROUP_NAME, "isSystemDefined": False})
    for table, _, _ in chain:
        pkg.sets[table] = pkg.gid("set", table)
    previous = None
    for table, left_field, right_field in chain:
        de_id = pkg.tables[table]; set_id = pkg.sets[table]
        if previous is None:
            rel_name = "%s <- %s" % (GROUP_NAME, set_names[table]); rel_id = pkg.gid("rel", rel_name)
            pkg.add("attributeRelationships", rel_id, {
                "relationshipAttributes": [{"rightAttributeName": left_field,
                                            "rightDataExtensionID": ref("dataExtensions", de_id, "id"),
                                            "rightAttributeID": ref("dataExtensions", de_id, "fields/name:%s/id" % left_field)}],
                "leftRelationshipIDs": [{"type": "int16", "value": "3"}], "leftRelationshipReferenceType": "CustomerData",
                "isGroupToSetRelationship": True,
                "leftItem": {"relationshipType": "AttributeGroup", "cardinality": "One",
                             "name": ref("attributeGroups", pkg.group_id, "name"),
                             "identifier": ref("attributeGroups", pkg.group_id, "id"),
                             "connectingID": {"identifierType": "FullyQualifiedName"}},
                "rightItem": {"relationshipType": "AttributeSet", "cardinality": "One",
                              "name": ref("attributeSets", set_id, "name")}, "name": rel_name})
        else:
            rel_name = "%s -> %s" % (set_names[previous], set_names[table]); rel_id = pkg.gid("rel", rel_name)
            pkg.add("attributeRelationships", rel_id, {
                "relationshipAttributes": [{"leftAttributeName": left_field, "rightAttributeName": right_field,
                                            "rightDataExtensionID": ref("dataExtensions", de_id, "id"),
                                            "rightAttributeID": ref("dataExtensions", de_id, "fields/name:%s/id" % right_field)}],
                "isGroupToSetRelationship": False,
                "leftItem": {"relationshipType": "AttributeSet", "cardinality": "One",
                             "identifier": ref("attributeSets", pkg.sets[previous], "id"),
                             "connectingID": {"identifierType": "FullyQualifiedName"}},
                "rightItem": {"relationshipType": "AttributeSet", "cardinality": "One",
                              "name": ref("attributeSets", set_id, "name")}, "name": rel_name})
        pkg.rels[table] = rel_id
        pkg.add("attributeSets", set_id, {
            "storageLogicalType": "DataExtension", "isRoot": False,
            "storageName": ref("dataExtensions", de_id, "name"),
            "storageReferenceID": {"type": "guid", "value": ref("dataExtensions", de_id, "id")},
            "groupId": ref("attributeGroups", pkg.group_id, "id"), "name": set_names[table],
            "leftRelationships": ["#/entities/attributeRelationships/%s/data" % rel_id], "isSystemDefined": False})
        previous = table
    pkg.chain = [t for t, _, _ in chain]


def build_set_name_differs() -> dict:
    pkg = Package("set_name_differs", "EX set name differs")
    pkg.table("DE_Entry", [text("ContactId", 50, pk=True, nullable=False), email_field(),
                           text("CampaignName", 100, nullable=False)], sendable_field="ContactId")
    pkg.table("DE_Master", [text("ContactId", 50, pk=True, nullable=False), text("FirstName"), email_field(),
                            phone(), text("CampaignName", 100, nullable=False), boolean("Perm")],
              sendable_field="ContactId")
    pkg.table("DE_Config", [text("CampaignName", 100, pk=True, nullable=False), text("CHANNEL", 20, nullable=False),
                            date("WAIT1", nullable=False, default="GETDATE()")])
    log_table(pkg)
    names = {"DE_Master": "Customers", "DE_Entry": "Entries", "DE_Config": "Campaigns"}
    _contact_model_named(pkg, [("DE_Master", "ContactId", ""), ("DE_Entry", "ContactId", "ContactId"),
                               ("DE_Config", "CampaignName", "CampaignName")], names)
    j = Journey(pkg, "EX_SetNameDiffers")
    j.decision("SPLIT-1", "Channel", [
        ("path_a", "Email", criteria(pkg.cond("DE_Config", "CHANNEL", "Equal", "Email")), "WAITATTR-1", "CHANNEL equal Email"),
        ("remainder_path", "Remainder", None, "UPDATE-3", None)])
    j.wait_attribute("WAITATTR-1", "DE_Config", "WAIT1", "SPLIT-2")
    # the wait expression must name the attribute sets, not the tables
    a = j.activities[-1]
    expr = '{{Contact.Attribute.Contacts.Customers.Entries.Campaigns."WAIT1"}}'
    a["configurationArguments"]["waitEndDateAttributeExpression"] = expr
    a["arguments"]["waitEndDateAttributeDataBound"] = expr
    for item in a["metaData"]["attribute"]["attributePath"]:
        if item["displayName"] in names:
            item["displayName"] = names[item["displayName"]]
    j.decision("SPLIT-2", "Permission", [
        ("path_a", "true", criteria(pkg.cond("DE_Master", "Perm", "Is", "true")), "UPDATE-1", "Perm is True"),
        ("remainder_path", "false", None, "UPDATE-2", None)])
    log_update(j, "UPDATE-1", "Email allowed", "EmailAllowed", None)
    log_update(j, "UPDATE-2", "Email blocked", "EmailBlocked", None)
    log_update(j, "UPDATE-3", "Other channel", "OtherChannel", None)
    event = add_entry_source(pkg, j.name, "DE_Entry", "Q_EX_SetNameDiffers_Entry", sql_master_config(pkg))
    add_journey(pkg, j, event)
    return export(pkg)


def build_join_after_updates() -> dict:
    pkg = Package("join_after_updates", "EX join after updates")
    setup_contact_only(pkg, [boolean("Perm"), text("Seg", 10)])
    m = "DE_Master"
    j = Journey(pkg, "EX_JoinAfterUpdates")
    j.decision("SPLIT-1", "Permission", [
        ("path_a", "true", criteria(pkg.cond(m, "Perm", "Is", "true")), "UPDATE-1", "Perm is True"),
        ("remainder_path", "false", None, "UPDATE-2", None)])
    j.update("UPDATE-1", "Segment X", m, [("Seg", "X")], "WAIT-1")
    j.update("UPDATE-2", "Segment Y", m, [("Seg", "Y")], "WAIT-1")
    j.wait_duration("WAIT-1", "SPLIT-2")
    j.decision("SPLIT-2", "Segment", [
        ("path_a", "X", criteria(pkg.cond(m, "Seg", "Equal", "X")), "UPDATE-3", "Seg equal X"),
        ("path_b", "Y", criteria(pkg.cond(m, "Seg", "Equal", "Y")), "UPDATE-4", "Seg equal Y"),
        ("remainder_path", "Remainder", None, "UPDATE-5", None)])
    log_update(j, "UPDATE-3", "Was X", "WasX", None)
    log_update(j, "UPDATE-4", "Was Y", "WasY", None)
    log_update(j, "UPDATE-5", "Neither", "Neither", None)
    event = add_entry_source(pkg, j.name, "DE_Entry", "Q_EX_JoinAfterUpdates_Entry", sql_master_only(pkg))
    add_journey(pkg, j, event)
    return export(pkg)


def build_boolean_written_as_number() -> dict:
    pkg = Package("boolean_written_as_number", "EX boolean written as number")
    setup_contact_only(pkg, [boolean("Gate"), boolean("Flag"), boolean("Other")])
    m = "DE_Master"
    j = Journey(pkg, "EX_BooleanWrittenAsNumber")
    j.decision("SPLIT-1", "Gate", [
        ("path_a", "true", criteria(pkg.cond(m, "Gate", "Is", "true")), "UPDATE-1", "Gate is True"),
        ("remainder_path", "false", None, "UPDATE-9", None)])
    j.update("UPDATE-1", "Set flags", m, [("Flag", 1), ("Other", "false")], "SPLIT-2")
    j.decision("SPLIT-2", "Flag", [
        ("path_a", "true", criteria(pkg.cond(m, "Flag", "Is", "true")), "SPLIT-3", "Flag is True"),
        ("remainder_path", "false", None, "UPDATE-2", None)])
    j.decision("SPLIT-3", "Other", [
        ("path_a", "false", criteria(pkg.cond(m, "Other", "Is", "false")), "UPDATE-3", "Other is False"),
        ("remainder_path", "true", None, "UPDATE-4", None)])
    log_update(j, "UPDATE-2", "Flag not set", "FlagNotSet", None)
    log_update(j, "UPDATE-3", "Flags as written", "FlagsAsWritten", None)
    log_update(j, "UPDATE-4", "Other not false", "OtherNotFalse", None)
    log_update(j, "UPDATE-9", "Gate closed", "GateClosed", None)
    event = add_entry_source(pkg, j.name, "DE_Entry", "Q_EX_BooleanWrittenAsNumber_Entry", sql_master_only(pkg))
    add_journey(pkg, j, event)
    return export(pkg)


def build_email_field_split() -> dict:
    pkg = Package("email_field_split", "EX email field split")
    setup_with_config(pkg, [], [date("WAIT1", nullable=False, default="GETDATE()")])
    add_email_asset(pkg, "900901", "Welcome", "WELCOME", with_link=False)
    m = "DE_Master"
    j = Journey(pkg, "EX_EmailFieldSplit")
    j.decision("SPLIT-1", "Email known?", [
        ("path_a", "no email", criteria(pkg.cond(m, "Emailaddress", "IsNull", "")), "UPDATE-1", "Emailaddress is null"),
        ("path_b", "vip", criteria(pkg.cond(m, "Emailaddress", "Equal", "vip@example.com")), "EMAIL-1",
         "Emailaddress equal vip@example.com"),
        ("remainder_path", "Remainder", None, "EMAIL-2", None)])
    j.email("EMAIL-1", "900901", "WAITATTR-1")
    j.wait_attribute("WAITATTR-1", "DE_Config", "WAIT1", "ENGAGE-1")
    j.engagement("ENGAGE-1", "Open Welcome VIP", "open", "EMAIL-1", "Welcome", yes_next="UPDATE-2", no_next="UPDATE-3")
    j.email("EMAIL-2", "900901", "UPDATE-4")
    log_update(j, "UPDATE-1", "No email", "NoEmail", None)
    log_update(j, "UPDATE-2", "VIP opened", "VipOpened", None)
    log_update(j, "UPDATE-3", "VIP not opened", "VipNotOpened", None)
    log_update(j, "UPDATE-4", "Welcome sent", "WelcomeSent", None)
    event = add_entry_source(pkg, j.name, "DE_Entry", "Q_EX_EmailFieldSplit_Entry", sql_master_config(pkg))
    add_journey(pkg, j, event)
    return export(pkg)


def build_field_name_case() -> dict:
    pkg = Package("field_name_case", "EX field name case")
    setup_with_config(pkg, [boolean("Perm")], [text("Channel", 20, nullable=False)])
    j = Journey(pkg, "EX_FieldNameCase")
    j.decision("SPLIT-1", "Channel", [
        ("path_a", "Email", criteria(pkg.cond("DE_Config", "CHANNEL", "Equal", "Email")), "SPLIT-2", "CHANNEL equal Email"),
        ("remainder_path", "Remainder", None, "UPDATE-3", None)])
    j.decision("SPLIT-2", "Permission", [
        ("path_a", "true", criteria(pkg.cond("DE_Master", "PERM", "Is", "true")), "UPDATE-1", "PERM is True"),
        ("remainder_path", "false", None, "UPDATE-2", None)])
    log_update(j, "UPDATE-1", "Allowed", "Allowed", None)
    log_update(j, "UPDATE-2", "Blocked", "Blocked", None)
    log_update(j, "UPDATE-3", "Other channel", "OtherChannel", None)
    event = add_entry_source(pkg, j.name, "DE_Entry", "Q_EX_FieldNameCase_Entry", sql_master_config(pkg))
    add_journey(pkg, j, event)
    return export(pkg)


def build_nested_random() -> dict:
    pkg = Package("nested_random", "EX nested random")
    setup_with_config(pkg, [boolean("Flag")], [boolean("Test Group", nullable=False, default="False")])
    j = Journey(pkg, "EX_NestedRandom")
    j.decision("SPLIT-1", "Test group", [
        ("path_a", "true", criteria(pkg.cond("DE_Config", "Test Group", "Is", "true")), "RANDOM-1", "Test Group is True"),
        ("remainder_path", "false", None, "UPDATE-5", None)])
    j.random_split("RANDOM-1", [("branchResult-1", 50, "RANDOM-2"), ("branchResult-2", 50, "UPDATE-1")])
    j.random_split("RANDOM-2", [("branchResult-1", 90, "UPDATE-2"), ("branchResult-2", 10, "UPDATE-3")])
    log_update(j, "UPDATE-1", "Half B", "HalfB", None)
    log_update(j, "UPDATE-2", "Half A main", "HalfAMain", None)
    log_update(j, "UPDATE-3", "Half A small", "HalfASmall", None)
    log_update(j, "UPDATE-5", "No test", "NoTest", None)
    event = add_entry_source(pkg, j.name, "DE_Entry", "Q_EX_NestedRandom_Entry", sql_master_config(pkg))
    add_journey(pkg, j, event)
    return export(pkg)


FRESH.update({
    "entry_filter_vs_split": build_entry_filter_vs_split,
    "entry_column_split": build_entry_column_split,
    "sql_variants": build_sql_variants,
    "set_name_differs": build_set_name_differs,
    "join_after_updates": build_join_after_updates,
    "boolean_written_as_number": build_boolean_written_as_number,
    "email_field_split": build_email_field_split,
    "field_name_case": build_field_name_case,
    "nested_random": build_nested_random,
})


def build_email_null_split() -> dict:
    pkg = Package("email_null_split", "EX email null split")
    setup_contact_only(pkg, [boolean("Perm")])
    m = "DE_Master"
    j = Journey(pkg, "EX_EmailNullSplit")
    j.decision("SPLIT-1", "Has email?", [
        ("path_a", "no email", criteria(pkg.cond(m, "Emailaddress", "IsNull", "")), "UPDATE-1", "Emailaddress is null"),
        ("remainder_path", "has email", None, "UPDATE-2", None)])
    log_update(j, "UPDATE-1", "SMS instead", "SmsInstead", None)
    log_update(j, "UPDATE-2", "Email ok", "EmailOk", None)
    event = add_entry_source(pkg, j.name, "DE_Entry", "Q_EX_EmailNullSplit_Entry", sql_master_only(pkg))
    add_journey(pkg, j, event)
    return export(pkg)


FRESH["email_null_split"] = build_email_null_split


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
