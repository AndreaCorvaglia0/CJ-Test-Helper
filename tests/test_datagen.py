"""Unit tests for cjhelper.datagen on a small hand-made world (spec, "Data generation rules").

The world: an entry table filled by an entry query from a contact-level Master table and a
scenario-level Config table (joined on CampaignName), plus a written-only Log table. Two scenarios,
three cases: one needing a manual open, one plain, and one statistical case of 50 contacts.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from cjhelper.datagen import (
    SCENARIO_COLUMNS,
    _local_dotnet_to_strftime,
    activation_setting,
    generate_data,
    wait_precedes_manual_action,
)
from cjhelper.model import (
    KIND_DECISION,
    KIND_EMAIL,
    KIND_ENGAGEMENT,
    KIND_RANDOM,
    KIND_UPDATE,
    KIND_WAIT_ATTRIBUTE,
    KIND_WAIT_DURATION,
    LEVEL_CONTACT,
    LEVEL_SCENARIO,
    ROLE_ENTRY,
    ROLE_SOURCE,
    ROLE_SPLIT,
    ROLE_WRITTEN,
    STATUS_COVERED,
    STATUS_MANUAL,
    STATUS_NOT_COVERED,
    Activity,
    BranchStatus,
    Case,
    ColumnRef,
    Condition,
    ConditionGroup,
    CoverageResult,
    DateBoundFilter,
    EmailAsset,
    EntryEvent,
    EqualityFilter,
    Field,
    GeneratedData,
    IsNullFilter,
    Journey,
    KeyGroup,
    ManualAction,
    Outcome,
    Package,
    ParsedQuery,
    RandomBranch,
    RandomInfo,
    Relationship,
    Scenario,
    SelectColumn,
    SelectConcat,
    SelectCurrentDate,
    SelectItem,
    SelectLiteral,
    SelectUnsupported,
    Settings,
    Step,
    Table,
    TableModel,
    TableRef,
    TableRole,
    UnsupportedFilter,
    Write,
)

GEN_TIME = datetime(2026, 10, 11, 9, 30)
NOW = "2026-10-11 09:30"
PLUS_24H = "2026-10-12 09:30"
YESTERDAY = "2026-10-10 09:30"
IN_7_DAYS = "2026-10-18 09:30"

ENTRY = "DE_Entry"
MASTER = "DE_Master"
CONFIG = "DE_Config"
LOG = "DE_Log"


# ---------------------------------------------------------------------------
# The hand-made world
# ---------------------------------------------------------------------------

@dataclass
class World:
    package: Package
    model: TableModel
    coverage: CoverageResult
    settings: Settings
    generation_time: datetime


def _fields(*specs) -> list[Field]:
    """specs: (name, type, length, pk, nullable, default)."""
    return [Field(name=n, type=t, length=ln, is_primary_key=pk, is_nullable=nl, default=d, ordinal=i)
            for i, (n, t, ln, pk, nl, d) in enumerate(specs)]


def build_tables() -> dict[str, Table]:
    entry = Table(id="de-entry", name=ENTRY, customer_key="KEY-ENTRY", is_sendable=True, sendable_field="ContactId",
                  fields=_fields(
                      ("ContactId", "Text", 50, True, False, None),
                      ("Email", "EmailAddress", 254, False, True, None),
                      ("AccountId", "Text", 50, False, True, None),
                      ("CampaignName", "Text", 50, True, False, None),
                      ("ActionId", "Text", 100, True, False, None),
                      ("Source", "Text", 20, False, True, None),
                      ("LoadDate", "Date", None, False, True, None),
                      ("Weird", "Text", 30, False, False, None),
                      ("Flag", "Boolean", None, False, True, "false"),
                      ("Note", "Text", 10, False, True, None),
                      ("Mandatory", "Text", 8, False, False, None),
                      ("Mobile", "Phone", 50, False, True, None),
                  ))
    master = Table(id="de-master", name=MASTER, customer_key="KEY-MASTER", is_sendable=True, sendable_field="ContactId",
                   fields=_fields(
                       ("ContactId", "Text", 50, True, False, None),
                       ("CampaignName", "Text", 50, False, False, None),
                       ("AccountId", "Text", 50, False, True, None),
                       ("FirstName", "Text", 8, False, True, None),
                       ("Email", "EmailAddress", 254, False, True, None),
                       ("Mobile", "Phone", 50, False, True, None),
                       ("Perm", "Boolean", None, False, True, None),
                       ("Optin", "Boolean", None, False, True, "true"),
                       ("Locked", "Boolean", None, False, True, None),
                       ("BirthDate", "Date", None, False, True, None),
                       ("Score", "Number", None, False, True, None),
                       ("Lang", "Locale", None, False, True, None),
                       ("ReminderDate", "Date", None, False, True, None),
                   ))
    config = Table(id="de-config", name=CONFIG, customer_key="KEY-CONFIG",
                   fields=_fields(
                       ("CampaignName", "Text", 50, True, False, None),
                       ("CHANNEL", "Text", 20, False, True, None),
                       ("ACTIVE", "Boolean", None, False, False, "False"),
                       ("HAS_RUN", "Boolean", None, False, False, "False"),
                       ("START_DATE", "Date", None, False, False, "GETDATE()"),
                       ("END_DATE", "Date", None, False, False, "GETDATE()"),
                       ("RUN_TIME", "Date", None, False, True, None),
                       ("Region", "Text", 10, False, True, None),
                       ("WAIT1", "Date", None, False, False, "GETDATE()"),
                       ("Label", "Text", 6, False, True, None),
                   ))
    log = Table(id="de-log", name=LOG, customer_key="KEY-LOG",
                fields=_fields(("ContactId", "Text", 50, True, False, None),
                               ("Status", "Text", 50, False, True, None)))
    return {t.name: t for t in (entry, master, config, log)}


def build_journey() -> Journey:
    def activity(key, raw, kind, name, outcomes, **details):
        return Activity(key=key, raw_type=raw, kind=kind, name=name, outcomes=outcomes, **details)

    perm_true = ConditionGroup("AND", (Condition(MASTER, "Perm", "Is", "true"),))
    activities = [
        activity("DEC-1", "MULTICRITERIADECISION", KIND_DECISION, "Channel", [
            Outcome("email", "Email", "EMAIL-1", formula=Condition(CONFIG, "CHANNEL", "Equal", "Email")),
            Outcome("remainder_path", "Remainder", "DEC-2", is_remainder=True)]),
        activity("EMAIL-1", "EMAILV2", KIND_EMAIL, "Welcome", [Outcome("e1", "", "WAIT-1")],
                 email_asset_id="A1", email_name="Welcome"),
        activity("WAIT-1", "WAIT", KIND_WAIT_ATTRIBUTE, "Wait campaign date", [Outcome("w1", "", "WAIT-2")],
                 wait_field=(CONFIG, "WAIT1"), wait_timezone="W. Europe Standard Time"),
        activity("WAIT-2", "WAIT", KIND_WAIT_ATTRIBUTE, "Wait reminder date", [Outcome("w2", "", "ENG-1")],
                 wait_field=(MASTER, "ReminderDate")),
        activity("ENG-1", "ENGAGEMENTDECISION", KIND_ENGAGEMENT, "Opened Welcome", [
            Outcome("yes", "Yes", "UPD-1", when=True), Outcome("no", "No", "DEC-2", when=False)],
            engagement_kind="open", engagement_ref="EMAIL-1"),
        activity("UPD-1", "UPDATECONTACTDATA", KIND_UPDATE, "Log open", [Outcome("u1", "", None)],
                 writes=[Write(LOG, "Status", "Opened")]),
        activity("DEC-2", "MULTICRITERIADECISION", KIND_DECISION, "Permission", [
            Outcome("perm", "Has permission", "WAIT-3", formula=perm_true),
            Outcome("remainder_path", "Remainder", "RAND-1", is_remainder=True)]),
        activity("WAIT-3", "WAIT", KIND_WAIT_DURATION, "Wait one minute", [Outcome("w3", "", None)],
                 wait_amount=1, wait_unit="MINUTES"),
        activity("RAND-1", "RANDOMSPLIT", KIND_RANDOM, "", [
            Outcome("b1", "90%", None, percentage=90), Outcome("b2", "10%", "EMAIL-2", percentage=10)]),
        activity("EMAIL-2", "EMAILV2", KIND_EMAIL, "Promo", [Outcome("e2", "", "ENG-2")],
                 email_asset_id="A2", email_name="Promo"),
        activity("ENG-2", "ENGAGEMENTDECISION", KIND_ENGAGEMENT, "Clicked Promo", [
            Outcome("yes", "Yes", None, when=True), Outcome("no", "No", None, when=False)],
            engagement_kind="click", engagement_ref="EMAIL-2"),
    ]
    return Journey(name="Test journey", key="J-1", activities={a.key: a for a in activities}, start_key="DEC-1",
                   entry_event_key="EV-KEY", entry_table=ENTRY, activity_count=len(activities))


def build_package() -> Package:
    tables = build_tables()
    return Package(
        name="Test package",
        journey=build_journey(),
        tables=tables,
        relationships=[Relationship("Entry -> Config", ENTRY, "CampaignName", CONFIG, "CampaignName", "Many", "One")],
        queries=[],
        entry_event=EntryEvent(key="EV-KEY", name="Test entry", table=ENTRY, automation_name="A_Entry"),
        emails={"A1": EmailAsset("A1", "Welcome", "Hello", True), "A2": EmailAsset("A2", "Promo", "Offer", False)},
        warnings=["Reading warning from the loader."],
    )


def build_entry_query() -> ParsedQuery:
    m = lambda column: ColumnRef(MASTER, column)  # noqa: E731
    c = lambda column: ColumnRef(CONFIG, column)  # noqa: E731
    return ParsedQuery(
        name="Q_Entry",
        target_table=ENTRY,
        sources=[TableRef(MASTER, "M"), TableRef(CONFIG, "C")],
        joins=[],
        filters=[
            EqualityFilter(c("ACTIVE"), "True"),
            EqualityFilter(c("HAS_RUN"), "false"),
            EqualityFilter(c("Region"), "North"),
            DateBoundFilter(c("START_DATE"), "start"),
            DateBoundFilter(c("END_DATE"), "end"),
            IsNullFilter(c("RUN_TIME")),
            UnsupportedFilter("C.Region LIKE 'N%' OR C.Region IS NULL"),
        ],
        select=[
            SelectItem("ContactId", SelectColumn(m("ContactId"))),
            SelectItem("Email", SelectColumn(m("Email"))),
            SelectItem("AccountId", SelectColumn(m("AccountId"))),
            SelectItem("CampaignName", SelectColumn(c("CampaignName"))),
            SelectItem("ActionId", SelectConcat((SelectColumn(m("ContactId")), SelectLiteral("_"),
                                                 SelectColumn(c("CampaignName")), SelectLiteral("_"),
                                                 SelectCurrentDate("yyyyMMdd_HHmm")))),
            SelectItem("Source", SelectLiteral("JOURNEY")),
            SelectItem("LoadDate", SelectCurrentDate(None)),
            SelectItem("Weird", SelectUnsupported("LEFT(M.FirstName, 2)")),
            SelectItem("Mobile", SelectColumn(ColumnRef("", "Mobile"))),       # unqualified: only Master has it
            SelectItem("FirstName", SelectColumn(m("FirstName"))),            # not an entry column: ignored
        ],
        warnings=["Parser warning about the entry query."],
    )


def build_model(package: Package) -> TableModel:
    roles = {
        ENTRY: TableRole(ENTRY, {ROLE_ENTRY}, True, LEVEL_CONTACT, "Bound to the entry trigger."),
        MASTER: TableRole(MASTER, {ROLE_SPLIT, ROLE_SOURCE}, True, LEVEL_CONTACT, "Read by a split and by the entry query."),
        CONFIG: TableRole(CONFIG, {ROLE_SPLIT, ROLE_SOURCE}, True, LEVEL_SCENARIO, "Read by a split, joined on CampaignName."),
        LOG: TableRole(LOG, {ROLE_WRITTEN}, False, None, "Only written by the journey."),
    }
    levels = {}
    for name in (ENTRY, MASTER):
        for f in package.tables[name].fields:
            levels[(name, f.name)] = LEVEL_SCENARIO if f.name == "CampaignName" else LEVEL_CONTACT
    for f in package.tables[CONFIG].fields:
        levels[(CONFIG, f.name)] = LEVEL_SCENARIO
    entry_query = build_entry_query()
    return TableModel(
        entry_table=ENTRY,
        contact_key_field=(ENTRY, "ContactId"),
        tables=roles,
        key_groups=[
            KeyGroup("contact", [(ENTRY, "ContactId"), (MASTER, "ContactId")]),
            KeyGroup("scenario", [(ENTRY, "CampaignName"), (MASTER, "CampaignName"), (CONFIG, "CampaignName")]),
            KeyGroup("other", [(ENTRY, "AccountId"), (MASTER, "AccountId")]),
        ],
        field_levels=levels,
        entry_query=entry_query,
        source_queries=[entry_query],
        scenario_tables=[CONFIG],
        contact_tables=[ENTRY, MASTER],
        activation_field=(CONFIG, "ACTIVE"),
        warnings=["Table selection warning."],
    )


def build_coverage() -> CoverageResult:
    open_welcome = ManualAction("ENG-1", "open", "EMAIL-1", "Welcome")
    case_open = Case(
        id="S01-C01", scenario_id="S01", class_id=1, contact_values={(MASTER, "Perm"): "True"},
        steps=[Step("DEC-1", "email"), Step("EMAIL-1", "e1"), Step("WAIT-1", "w1"), Step("WAIT-2", "w2"),
               Step("ENG-1", "yes"), Step("UPD-1", None)],
        emails_sent=["EMAIL-1"], writes=[Write(LOG, "Status", "Opened")], waits=["WAIT-1", "WAIT-2"],
        manual_actions=[open_welcome], end_activity_key="UPD-1", contact_count=3, summary="Welcome opened")
    case_plain = Case(
        id="S01-C02", scenario_id="S01", class_id=1, contact_values={(MASTER, "Perm"): "true"},
        steps=[Step("DEC-1", "email"), Step("EMAIL-1", "e1"), Step("WAIT-1", "w1"), Step("WAIT-2", "w2"),
               Step("ENG-1", "no"), Step("DEC-2", "perm"), Step("WAIT-3", None)],
        emails_sent=["EMAIL-1"], writes=[], waits=["WAIT-1", "WAIT-2", "WAIT-3"], manual_actions=[],
        end_activity_key="WAIT-3", contact_count=3, summary="")
    case_random = Case(
        id="S02-C01", scenario_id="S02", class_id=2, contact_values={(MASTER, "Perm"): None},
        steps=[Step("DEC-1", "remainder_path"), Step("DEC-2", "remainder_path"), Step("RAND-1", None)],
        emails_sent=[], writes=[], waits=[], manual_actions=[], end_activity_key="RAND-1", contact_count=50,
        random=RandomInfo("RAND-1", [
            RandomBranch("b1", 90, (), (), (), "RAND-1"),
            RandomBranch("b2", 10, (Step("EMAIL-2", "e2"), Step("ENG-2", "no")), ("EMAIL-2",), (), "ENG-2"),
        ], expected_low=1, expected_high=9),
        summary="Random split 90/10")
    s01 = Scenario(id="S01", key="", values={(CONFIG, "CHANNEL"): "Email"}, cases=[case_open, case_plain],
                   run_order=1, has_manual_action=True)
    s02 = Scenario(id="S02", key="", values={(CONFIG, "CHANNEL"): "OTHER"}, cases=[case_random],
                   run_order=2, has_manual_action=False, is_statistical=True)

    def branch(activity, name, kind, outcome, label, status, covered_by, reason="", statistical=False):
        return BranchStatus(activity, name, kind, outcome, label, status, reason, covered_by, statistical)

    branches = [
        branch("DEC-1", "Channel", KIND_DECISION, "email", "Email", STATUS_COVERED, ["S01-C01", "S01-C02"]),
        branch("DEC-1", "Channel", KIND_DECISION, "remainder_path", "Remainder", STATUS_COVERED, ["S02-C01"]),
        branch("ENG-1", "Opened Welcome", KIND_ENGAGEMENT, "yes", "Yes", STATUS_MANUAL, ["S01-C01"]),
        branch("ENG-1", "Opened Welcome", KIND_ENGAGEMENT, "no", "No", STATUS_COVERED, ["S01-C02"]),
        branch("DEC-2", "Permission", KIND_DECISION, "perm", "Has permission", STATUS_COVERED, ["S01-C02"]),
        branch("DEC-2", "Permission", KIND_DECISION, "remainder_path", "Remainder", STATUS_COVERED, ["S02-C01"]),
        branch("RAND-1", "", KIND_RANDOM, "b1", "90%", STATUS_COVERED, ["S02-C01"], statistical=True),
        branch("RAND-1", "", KIND_RANDOM, "b2", "10%", STATUS_COVERED, ["S02-C01"], statistical=True),
        branch("ENG-2", "Clicked Promo", KIND_ENGAGEMENT, "yes", "Yes", STATUS_NOT_COVERED, [],
               reason="The email Promo has no link, so a click cannot be asked."),
        branch("ENG-2", "Clicked Promo", KIND_ENGAGEMENT, "no", "No", STATUS_COVERED, ["S02-C01"], statistical=True),
    ]
    # Scenarios listed out of run order on purpose: the output must follow run_order.
    return CoverageResult(scenarios=[s02, s01], branches=branches, classes=[],
                          scenario_fields=[(CONFIG, "CHANNEL")], contact_fields=[(MASTER, "Perm")],
                          domains={}, unsupported=[], warnings=["Coverage warning."], stats={})


def build_world(**settings) -> World:
    package = build_package()
    options = {"real_inbox": "tester@example.com"}
    options.update(settings)
    return World(package, build_model(package), build_coverage(), Settings(**options), GEN_TIME)


def run(world: World) -> GeneratedData:
    return generate_data(world.package, world.model, world.coverage, world.settings, world.generation_time)


def rows_of(data: GeneratedData, table: str) -> list[dict]:
    return data.tables[table].rows


def by_key(rows: list[dict], column: str) -> dict:
    return {row[column]: row for row in rows}


def scenario(world: World, scenario_id: str) -> Scenario:
    return next(s for s in world.coverage.scenarios if s.id == scenario_id)


def case_keys(world: World, case_id: str) -> list[str]:
    return next(c for c in world.coverage.cases if c.id == case_id).contact_keys


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------

def test_keys_follow_run_order_then_case_order():
    world = build_world()
    data = run(world)
    assert scenario(world, "S01").key == "TST_R01_S01"
    assert scenario(world, "S02").key == "TST_R01_S02"
    assert case_keys(world, "S01-C01") == ["TST_R01_C0001", "TST_R01_C0002", "TST_R01_C0003"]
    assert case_keys(world, "S01-C02") == ["TST_R01_C0004", "TST_R01_C0005", "TST_R01_C0006"]
    random_keys = case_keys(world, "S02-C01")
    assert len(random_keys) == 50
    assert random_keys[0] == "TST_R01_C0007" and random_keys[-1] == "TST_R01_C0056"
    assert [c.key for c in data.contacts] == [f"TST_R01_C{n:04d}" for n in range(1, 57)]


def test_run_identifier_is_in_every_key():
    world = build_world(run_id="R07")
    data = run(world)
    assert scenario(world, "S01").key == "TST_R07_S01"
    assert data.contacts[0].key == "TST_R07_C0001"
    assert all(row["AccountId"].startswith("TST_R07_K") for row in rows_of(data, MASTER))


def test_one_row_per_contact_and_per_scenario_in_order():
    data = run(build_world())
    assert set(data.tables) == {ENTRY, MASTER, CONFIG}       # the written-only table gets no CSV
    assert [r["ContactId"] for r in rows_of(data, MASTER)] == [f"TST_R01_C{n:04d}" for n in range(1, 57)]
    assert [r["ContactId"] for r in rows_of(data, ENTRY)] == [f"TST_R01_C{n:04d}" for n in range(1, 57)]
    assert [r["CampaignName"] for r in rows_of(data, CONFIG)] == ["TST_R01_S01", "TST_R01_S02"]


def test_keys_are_consistent_across_tables():
    data = run(build_world())
    masters = by_key(rows_of(data, MASTER), "ContactId")
    configs = by_key(rows_of(data, CONFIG), "CampaignName")
    for entry_row in rows_of(data, ENTRY):
        master_row = masters[entry_row["ContactId"]]
        assert master_row["CampaignName"] == entry_row["CampaignName"]
        assert master_row["AccountId"] == entry_row["AccountId"]
        assert entry_row["CampaignName"] in configs
    contact_to_scenario = {c.key: c.scenario_id for c in data.contacts}
    for key, row in masters.items():
        assert row["CampaignName"] == f"TST_R01_{contact_to_scenario[key]}"


def test_other_key_group_is_shared_by_its_fields_and_unique_per_contact():
    data = run(build_world())
    account_ids = [r["AccountId"] for r in rows_of(data, MASTER)]
    assert account_ids[0] == "TST_R01_K0001"
    assert len(set(account_ids)) == 56
    assert [r["AccountId"] for r in rows_of(data, ENTRY)] == account_ids


def test_primary_keys_are_unique_in_every_table():
    world = build_world()
    data = run(world)
    for name, table_data in data.tables.items():
        pk = world.package.tables[name].primary_key
        values = [tuple(row[f] for f in pk) for row in table_data.rows]
        assert all(all(v for v in key) for key in values), name
        assert len(set(values)) == len(values), name


def test_columns_follow_the_schema_order():
    world = build_world()
    data = run(world)
    for name, table_data in data.tables.items():
        assert table_data.columns == world.package.tables[name].field_names
        assert all(list(row) == table_data.columns for row in table_data.rows)


# ---------------------------------------------------------------------------
# Split values and entry query filters
# ---------------------------------------------------------------------------

def test_split_values_are_written_exactly_as_given():
    world = build_world()
    data = run(world)
    configs = by_key(rows_of(data, CONFIG), "CampaignName")
    assert configs["TST_R01_S01"]["CHANNEL"] == "Email"          # same letter case as the condition
    assert configs["TST_R01_S02"]["CHANNEL"] == "OTHER"
    masters = by_key(rows_of(data, MASTER), "ContactId")
    assert [masters[k]["Perm"] for k in case_keys(world, "S01-C01")] == ["True"] * 3
    assert [masters[k]["Perm"] for k in case_keys(world, "S01-C02")] == ["True"] * 3   # "true" -> True/False format
    assert {masters[k]["Perm"] for k in case_keys(world, "S02-C01")} == {None}        # null -> empty cell


def test_entry_query_filters_give_passing_values():
    data = run(build_world(one_active_scenario=False))
    for row in rows_of(data, CONFIG):
        assert row["ACTIVE"] == "True"
        assert row["HAS_RUN"] == "False"          # Boolean literal 'false' normalised
        assert row["Region"] == "North"           # text literal as written
        assert row["START_DATE"] == YESTERDAY     # validity window starts yesterday
        assert row["END_DATE"] == IN_7_DAYS       # and ends in 7 days
        assert row["RUN_TIME"] is None            # IS NULL


def test_validity_window_follows_the_settings():
    data = run(build_world(window_start_days=-3, window_end_days=30))
    row = rows_of(data, CONFIG)[0]
    assert row["START_DATE"] == "2026-10-08 09:30"
    assert row["END_DATE"] == "2026-11-10 09:30"


def test_unsupported_filter_and_ignored_select_columns_are_warned():
    data = run(build_world())
    assert any("C.Region LIKE 'N%' OR C.Region IS NULL" in w and "not supported" in w for w in data.warnings)
    assert any("FirstName" in w and "ignored" in w for w in data.warnings)


def test_one_active_scenario_activates_only_the_first_in_run_order():
    world = build_world()
    data = run(world)
    configs = by_key(rows_of(data, CONFIG), "CampaignName")
    assert configs["TST_R01_S01"]["ACTIVE"] == "True"
    assert configs["TST_R01_S02"]["ACTIVE"] == "False"
    assert [r["activate"] for r in data.scenarios_rows] == ["yes", "no"]
    assert not any("ACTIVE" in w and "instead of" in w for w in data.warnings)


def test_one_active_scenario_off_activates_every_scenario():
    data = run(build_world(one_active_scenario=False))
    assert [r["ACTIVE"] for r in rows_of(data, CONFIG)] == ["True", "True"]
    assert [r["activate"] for r in data.scenarios_rows] == ["yes", "yes"]


def test_activation_field_from_settings_must_be_boolean():
    world = build_world(activation_field=(CONFIG, "Region"))
    on, field, warnings = activation_setting(world.package, world.model, world.settings)
    assert (on, field) == (False, None)
    assert any("not Boolean" in w for w in warnings)
    data = run(world)
    assert [r["activate"] for r in data.scenarios_rows] == ["yes", "yes"]
    assert any("Region" in w and "not Boolean" in w for w in data.warnings)


def test_activation_setting_resolves_the_schema_spelling():
    world = build_world(activation_field=(CONFIG.lower(), "active"))
    assert activation_setting(world.package, world.model, world.settings) == (True, (CONFIG, "ACTIVE"), [])


def test_key_wins_over_a_split_value_with_a_warning():
    world = build_world()
    world.coverage.scenario_fields.append((CONFIG, "CampaignName"))
    for s in world.coverage.scenarios:
        s.values[(CONFIG, "CampaignName")] = "DemoCampaign"
    data = run(world)
    assert [r["CampaignName"] for r in rows_of(data, CONFIG)] == ["TST_R01_S01", "TST_R01_S02"]
    assert any("CampaignName" in w and "generated key" in w and "DemoCampaign" in w for w in data.warnings)


def test_split_value_wins_over_a_filter_value_with_a_warning():
    world = build_world(one_active_scenario=False)
    world.coverage.scenario_fields.append((CONFIG, "Region"))
    for s in world.coverage.scenarios:
        s.values[(CONFIG, "Region")] = "South"
    data = run(world)
    assert [r["Region"] for r in rows_of(data, CONFIG)] == ["South", "South"]
    assert any("Region" in w and "split" in w and "North" in w for w in data.warnings)


# ---------------------------------------------------------------------------
# Dates, waits, email, phone
# ---------------------------------------------------------------------------

def test_wait_dates_use_the_24_hour_rule_only_before_a_manual_action():
    world = build_world()
    data = run(world)
    configs = by_key(rows_of(data, CONFIG), "CampaignName")
    assert configs["TST_R01_S01"]["WAIT1"] == PLUS_24H        # a case of S01 opens the email after WAIT-1
    assert configs["TST_R01_S02"]["WAIT1"] == NOW             # no manual action in S02
    masters = by_key(rows_of(data, MASTER), "ContactId")
    assert {masters[k]["ReminderDate"] for k in case_keys(world, "S01-C01")} == {PLUS_24H}
    assert {masters[k]["ReminderDate"] for k in case_keys(world, "S01-C02")} == {NOW}   # crosses, no manual action
    assert {masters[k]["ReminderDate"] for k in case_keys(world, "S02-C01")} == {NOW}   # does not cross


def test_wait_after_the_manual_action_gets_no_extra_offset():
    world = build_world()
    case_open = next(c for c in world.coverage.cases if c.id == "S01-C01")
    case_open.steps = [Step("DEC-1", "email"), Step("EMAIL-1", "e1"), Step("WAIT-1", "w1"), Step("ENG-1", "yes"),
                       Step("WAIT-2", "w2"), Step("UPD-1", None)]
    assert wait_precedes_manual_action("WAIT-1", case_open)
    assert not wait_precedes_manual_action("WAIT-2", case_open)
    data = run(world)
    masters = by_key(rows_of(data, MASTER), "ContactId")
    assert {masters[k]["ReminderDate"] for k in case_keys(world, "S01-C01")} == {NOW}


def test_wait_offsets_follow_the_settings():
    data = run(build_world(wait_offset_hours=2, wait_offset_before_engagement_hours=48))
    assert [r["WAIT1"] for r in rows_of(data, CONFIG)] == ["2026-10-13 09:30", "2026-10-11 11:30"]


def test_missing_wait_between_email_and_engagement_is_warned():
    world = build_world()
    case_open = next(c for c in world.coverage.cases if c.id == "S01-C01")
    case_open.steps = [Step("DEC-1", "email"), Step("WAIT-1", "w1"), Step("EMAIL-1", "e1"), Step("ENG-1", "yes"),
                       Step("UPD-1", None)]
    data = run(world)
    assert any("S01-C01" in w and "ENG-1" in w and "may not have time" in w for w in data.warnings)
    assert not any("S01-C01" in w for w in run(build_world()).warnings)


def test_wait_field_listed_by_coverage_still_gets_the_wait_date():
    world = build_world()
    world.coverage.scenario_fields.append((CONFIG, "WAIT1"))
    for s in world.coverage.scenarios:
        s.values[(CONFIG, "WAIT1")] = None
    data = run(world)
    assert [r["WAIT1"] for r in rows_of(data, CONFIG)] == [PLUS_24H, NOW]
    assert any("WAIT1" in w and "wait date" in w for w in data.warnings)


def test_real_inbox_with_plus_addressing_only_for_manual_action_contacts():
    world = build_world()
    data = run(world)
    contacts = {c.key: c for c in data.contacts}
    masters = by_key(rows_of(data, MASTER), "ContactId")
    entries = by_key(rows_of(data, ENTRY), "ContactId")
    for key in case_keys(world, "S01-C01"):
        assert contacts[key].uses_real_inbox
        assert contacts[key].email == f"tester+{key}@example.com"
        assert masters[key]["Email"] == entries[key]["Email"] == f"tester+{key}@example.com"
    for key in case_keys(world, "S01-C02") + case_keys(world, "S02-C01"):
        assert not contacts[key].uses_real_inbox
        assert masters[key]["Email"] == entries[key]["Email"] == f"{key}@example.invalid"


def test_without_real_inbox_every_contact_is_undeliverable():
    data = run(build_world(real_inbox=""))
    assert not any(c.uses_real_inbox for c in data.contacts)
    assert all(c.email == f"{c.key}@example.invalid" for c in data.contacts)
    assert any("No real inbox" in w for w in data.warnings)


def test_malformed_real_inbox_is_not_used():
    data = run(build_world(real_inbox="tester"))
    assert not any(c.uses_real_inbox for c in data.contacts)
    assert any("'tester'" in w and "name@domain" in w for w in data.warnings)


def test_phone_fields_get_the_fake_number_and_never_the_real_one():
    data = run(build_world(real_phone="+39 333 1234567", fake_phone="000111"))
    assert {r["Mobile"] for r in rows_of(data, MASTER)} == {"000111"}
    assert {r["Mobile"] for r in rows_of(data, ENTRY)} == {"000111"}
    assert not any(c.uses_real_phone for c in data.contacts)


# ---------------------------------------------------------------------------
# Placeholders
# ---------------------------------------------------------------------------

def test_placeholders_by_type_and_cut_to_length():
    data = run(build_world())
    masters = rows_of(data, MASTER)
    assert masters[0]["FirstName"] == "TST_Firs"                 # TST_FirstName_1 cut to 8
    assert masters[0]["Score"] == "1" and masters[55]["Score"] == "56"
    assert masters[0]["Lang"] == "en-US"
    assert masters[0]["BirthDate"] == NOW
    assert [r["Label"] for r in rows_of(data, CONFIG)] == ["TST_La", "TST_La"]   # TST_Label_<n> cut to 6


def test_boolean_placeholders_use_the_default_or_false():
    data = run(build_world())
    assert {r["Optin"] for r in rows_of(data, MASTER)} == {"True"}     # default "true"
    assert {r["Locked"] for r in rows_of(data, MASTER)} == {"False"}   # no default


def test_text_placeholder_without_length_is_not_cut():
    world = build_world()
    world.package.tables[MASTER].fields.append(
        Field("Nickname", "Text", None, False, True, None, 13))
    data = run(world)
    assert rows_of(data, MASTER)[2]["Nickname"] == "TST_Nickname_3"


# ---------------------------------------------------------------------------
# The entry table
# ---------------------------------------------------------------------------

def test_entry_rows_are_derived_from_the_select_expressions():
    data = run(build_world())
    first = rows_of(data, ENTRY)[0]
    assert first["ContactId"] == "TST_R01_C0001"
    assert first["CampaignName"] == "TST_R01_S01"
    assert first["ActionId"] == "TST_R01_C0001_TST_R01_S01_20261011_0930"   # CONCAT + FORMAT(GETUTCDATE())
    assert first["Source"] == "JOURNEY"                                      # literal
    assert first["LoadDate"] == NOW                                          # plain current date
    assert first["Mobile"] == "333333333333"                                 # unqualified column from Master
    assert first["Weird"] == "TST_Weird_1"                                   # unsupported -> placeholder
    assert any(p.startswith(f"{ENTRY}.Weird:") and "LEFT(M.FirstName, 2)" in p for p in data.placeholders)


def test_entry_columns_not_in_the_select():
    data = run(build_world())
    rows = rows_of(data, ENTRY)
    assert {r["Flag"] for r in rows} == {"False"}            # schema default "false", normalised
    assert {r["Note"] for r in rows} == {None}               # nullable, no default
    assert rows[0]["Mandatory"] == "TST_Mand"                # not nullable, no default: placeholder
    assert any(p.startswith(f"{ENTRY}.Mandatory:") for p in data.placeholders)
    assert len(data.placeholders) == 2


def test_entry_key_column_missing_from_the_select_still_gets_the_key():
    world = build_world()
    world.model.entry_query.select = [i for i in world.model.entry_query.select if i.target_column != "ContactId"]
    data = run(world)
    assert [r["ContactId"] for r in rows_of(data, ENTRY)][:2] == ["TST_R01_C0001", "TST_R01_C0002"]
    assert any(f"{ENTRY}.ContactId" in w and "does not fill it" in w for w in data.warnings)


def test_split_on_an_entry_column_is_pushed_back_to_its_source():
    world = build_world()
    master = world.package.tables[MASTER]
    master.fields.append(Field("Segment", "Text", 20, False, True, None, 13))
    world.package.tables[ENTRY].fields.append(Field("Segment", "Text", 20, False, True, None, 12))
    world.model.entry_query.select.append(SelectItem("Segment", SelectColumn(ColumnRef(MASTER, "Segment"))))
    world.coverage.contact_fields.append((ENTRY, "Segment"))
    for c in world.coverage.cases:
        c.contact_values[(ENTRY, "Segment")] = "Gold" if c.id == "S01-C01" else "Silver"
    data = run(world)
    masters = by_key(rows_of(data, MASTER), "ContactId")
    entries = by_key(rows_of(data, ENTRY), "ContactId")
    for key in case_keys(world, "S01-C01"):
        assert masters[key]["Segment"] == entries[key]["Segment"] == "Gold"
    for key in case_keys(world, "S02-C01"):
        assert masters[key]["Segment"] == entries[key]["Segment"] == "Silver"


def test_select_all_copies_same_named_columns():
    world = build_world()
    world.model.entry_query.select = []
    world.model.entry_query.select_all = True
    data = run(world)
    masters = by_key(rows_of(data, MASTER), "ContactId")
    for row in rows_of(data, ENTRY):
        master_row = masters[row["ContactId"]]
        for column in ("Email", "AccountId", "CampaignName", "Mobile"):
            assert row[column] == master_row[column]
        assert row["Source"] is None                            # no source column of that name


def test_without_entry_query_the_entry_table_uses_the_general_rules():
    world = build_world()
    world.model.entry_query = None
    data = run(world)
    rows = rows_of(data, ENTRY)
    assert len(rows) == 56
    assert rows[0]["ContactId"] == "TST_R01_C0001"
    assert rows[0]["CampaignName"] == "TST_R01_S01"
    assert rows[0]["ActionId"] == "TST_ActionId_1"
    assert rows[0]["Email"] == "tester+TST_R01_C0001@example.com"
    assert any("No entry query" in w for w in data.warnings)
    assert data.placeholders == []


def test_dotnet_format_fallback_converter():
    assert _local_dotnet_to_strftime("yyyyMMdd_HHmm") == "%Y%m%d_%H%M"
    assert _local_dotnet_to_strftime("dd/MM/yyyy HH:mm:ss 100%") == "%d/%m/%Y %H:%M:%S 100%%"


# ---------------------------------------------------------------------------
# scenarios.csv rows, statistical case, determinism
# ---------------------------------------------------------------------------

def test_scenarios_rows_content():
    data = run(build_world())
    assert list(data.scenarios_rows[0]) == SCENARIO_COLUMNS + [f"{CONFIG}.CHANNEL"]
    first, second = data.scenarios_rows
    assert first == {
        "scenario_key": "TST_R01_S01", "run_order": "1", "has_manual_action": "True", "is_statistical": "False",
        "case_count": "2", "contact_count": "6", "first_contact_key": "TST_R01_C0001",
        "last_contact_key": "TST_R01_C0006", "activate": "yes", f"{CONFIG}.CHANNEL": "Email",
    }
    assert second["scenario_key"] == "TST_R01_S02"
    assert second["is_statistical"] == "True"
    assert second["contact_count"] == "50"
    assert (second["first_contact_key"], second["last_contact_key"]) == ("TST_R01_C0007", "TST_R01_C0056")
    assert second[f"{CONFIG}.CHANNEL"] == "OTHER"


def test_statistical_case_gets_its_contact_count():
    world = build_world()
    data = run(world)
    random_contacts = [c for c in data.contacts if c.case_id == "S02-C01"]
    assert len(random_contacts) == 50
    assert len(rows_of(data, MASTER)) == len(rows_of(data, ENTRY)) == 56


def test_contacts_records():
    data = run(build_world())
    counts = Counter(c.case_id for c in data.contacts)
    assert counts == {"S01-C01": 3, "S01-C02": 3, "S02-C01": 50}
    assert {c.scenario_id for c in data.contacts if c.case_id.startswith("S01")} == {"S01"}


def test_same_inputs_give_the_same_data():
    first, second = run(build_world()), run(build_world())
    assert first == second


def test_nothing_reads_the_clock():
    later = build_world()
    later.generation_time = datetime(2027, 1, 2, 3, 4)
    data = run(later)
    assert rows_of(data, CONFIG)[1]["WAIT1"] == "2027-01-02 03:04"
    assert rows_of(data, ENTRY)[0]["ActionId"].endswith("_20270102_0304")


# ---------------------------------------------------------------------------
# Edge cases: every judgement call is a warning
# ---------------------------------------------------------------------------

def test_split_value_breaking_an_is_not_null_filter_is_warned():
    world = build_world()
    world.model.entry_query.filters.append(IsNullFilter(ColumnRef(MASTER, "Perm"), negated=True))
    data = run(world)
    masters = by_key(rows_of(data, MASTER), "ContactId")
    assert masters["TST_R01_C0007"]["Perm"] is None                       # the split value still wins
    assert any("DE_Master.Perm" in w and "IS NOT NULL" in w for w in data.warnings)


def test_is_not_null_filter_lets_the_lower_rules_fill_a_value():
    world = build_world()
    world.model.entry_query.filters.append(IsNullFilter(ColumnRef(CONFIG, "Label"), negated=True))
    data = run(world)
    assert [r["Label"] for r in rows_of(data, CONFIG)] == ["TST_La", "TST_La"]


def test_filter_on_the_entry_table_itself_is_not_applied():
    world = build_world()
    world.model.entry_query.filters.append(IsNullFilter(ColumnRef(ENTRY, "ContactId")))
    data = run(world)
    assert rows_of(data, ENTRY)[0]["ContactId"] == "TST_R01_C0001"
    assert any("filters on the entry table itself" in w for w in data.warnings)


def test_several_filters_on_one_field_and_unknown_filter_columns_are_warned():
    world = build_world(one_active_scenario=False)
    world.model.entry_query.filters += [EqualityFilter(ColumnRef(CONFIG, "Region"), "South"),
                                        EqualityFilter(ColumnRef("", "NoSuchColumn"), "x")]
    data = run(world)
    assert {r["Region"] for r in rows_of(data, CONFIG)} == {"North"}     # the first filter is used
    assert any("several filters on DE_Config.Region" in w for w in data.warnings)
    assert any("NoSuchColumn" in w and "matches no field" in w for w in data.warnings)


def test_text_field_named_like_an_email_gets_a_placeholder_and_a_warning():
    world = build_world()
    world.package.tables[MASTER].fields.append(Field("EmailStatus", "Text", 20, False, True, None, 13))
    data = run(world)
    assert rows_of(data, MASTER)[0]["EmailStatus"] == "TST_EmailStatus_1"
    assert any("DE_Master.EmailStatus" in w and "named like an email" in w for w in data.warnings)


def test_email_field_in_a_scenario_level_table():
    world = build_world()
    world.package.tables[CONFIG].fields.append(Field("Sender", "EmailAddress", 254, False, True, None, 10))
    data = run(world)
    assert [r["Sender"] for r in rows_of(data, CONFIG)] == ["TST_R01_S01@example.invalid", "TST_R01_S02@example.invalid"]
    assert any("DE_Config.Sender" in w for w in data.warnings)


def test_unknown_field_type_gets_a_text_placeholder():
    world = build_world()
    world.package.tables[MASTER].fields.append(Field("Blob", "Binary", 5, False, True, None, 13))
    data = run(world)
    assert rows_of(data, MASTER)[0]["Blob"] == "TST_B"
    assert any("Binary" in w for w in data.warnings)


def test_other_key_groups_without_a_csv_table_take_no_key_numbers():
    world = build_world()
    world.model.key_groups.insert(2, KeyGroup("other", [(LOG, "Status"), ("DE_Elsewhere", "Code")]))
    data = run(world)
    assert rows_of(data, MASTER)[0]["AccountId"] == "TST_R01_K0001"


def test_case_without_contacts_is_warned():
    world = build_world()
    next(c for c in world.coverage.cases if c.id == "S01-C02").contact_count = 0
    data = run(world)
    assert len(data.contacts) == 53
    assert case_keys(world, "S02-C01")[0] == "TST_R01_C0004"
    assert any("S01-C02" in w and "0 contacts" in w for w in data.warnings)


def test_date_format_without_directives_is_warned():
    data = run(build_world(date_format="YYYY-MM-DD HH:MM"))
    assert rows_of(data, MASTER)[0]["BirthDate"] == "YYYY-MM-DD HH:MM"
    assert any("no strftime directive" in w for w in data.warnings)


def test_entry_dates_use_the_local_converter_when_sqlparse_lite_is_missing(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "cjhelper.sqlparse_lite", None)   # any import of it now fails
    data = run(build_world())
    assert rows_of(data, ENTRY)[0]["ActionId"] == "TST_R01_C0001_TST_R01_S01_20261011_0930"
