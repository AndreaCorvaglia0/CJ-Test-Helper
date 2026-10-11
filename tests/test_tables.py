"""Tests for cjhelper.tables: table selection, key groups and levels (spec "Table selection",
"Journey model and coverage" step 3, "Data generation rules" / "Keys").

The packages are built by hand and ``sqlparse_lite.parse_query`` is replaced by a stub that
returns hand-made ParsedQuery objects, so these tests do not depend on the SQL parser.
"""

import importlib.util
import sys
import types
from dataclasses import replace
from pathlib import Path

import pytest

import cjhelper

SQLPARSE_WRITTEN = importlib.util.find_spec("cjhelper.sqlparse_lite") is not None
if not SQLPARSE_WRITTEN:
    # sqlparse_lite.py is written in parallel. Until it exists, a placeholder lets cjhelper.tables
    # import; every unit test below replaces parse_query anyway, and the pilot test is skipped.
    _placeholder = types.ModuleType("cjhelper.sqlparse_lite")

    def _not_written_yet(query, schema):
        raise NotImplementedError("cjhelper.sqlparse_lite is not written yet")

    _placeholder.parse_query = _not_written_yet
    sys.modules["cjhelper.sqlparse_lite"] = _placeholder
    cjhelper.sqlparse_lite = _placeholder

from cjhelper import tables  # noqa: E402
from cjhelper.model import (  # noqa: E402
    KIND_DECISION,
    KIND_UPDATE,
    KIND_WAIT_ATTRIBUTE,
    LEVEL_CONTACT,
    LEVEL_SCENARIO,
    ROLE_ENTRY,
    ROLE_SOURCE,
    ROLE_SPLIT,
    ROLE_WRITTEN,
    Activity,
    ColumnRef,
    Condition,
    EntryEvent,
    EqualityFilter,
    Field,
    JoinEquality,
    Journey,
    Outcome,
    Package,
    ParsedQuery,
    Query,
    Relationship,
    SelectColumn,
    SelectItem,
    Table,
    TableRef,
    Write,
)

PILOT = Path(__file__).resolve().parent.parent / "fixtures" / "CJ template complesso-v1.json"

ENTRY = "DE_Entry"
MASTER = "DE_Master"
TARGET = "DE_Target"
CONFIG = "DE_Config"


# ---------------------------------------------------------------------------
# Hand-made packages
# ---------------------------------------------------------------------------

def text(name, pk=False):
    return Field(name=name, type="Text", length=50, is_primary_key=pk, is_nullable=not pk, default=None, ordinal=0)


def boolean(name):
    return Field(name=name, type="Boolean", length=None, is_primary_key=False, is_nullable=False,
                 default="False", ordinal=0)


def date(name):
    return Field(name=name, type="Date", length=None, is_primary_key=False, is_nullable=True, default=None, ordinal=0)


def make_table(name, *fields, sendable_field=None):
    numbered = [replace(f, ordinal=i) for i, f in enumerate(fields)]
    return Table(id=f"id-{name}", name=name, customer_key=name, fields=numbered,
                 is_sendable=sendable_field is not None, sendable_field=sendable_field)


def cond(table, field, value="true", operator="Is"):
    return Condition(table=table, field=field, operator=operator, value=value)


def decision(key, *conditions):
    """A decision split with one outcome per condition, plus the remainder."""
    outcomes = [Outcome(key=f"{key}-path{i}", label=f"path {i}", next=None, formula=c)
                for i, c in enumerate(conditions, 1)]
    outcomes.append(Outcome(key="remainder_path", label="Remainder", next=None, is_remainder=True))
    return Activity(key=key, raw_type="MULTICRITERIADECISION", kind=KIND_DECISION, name=key, outcomes=outcomes)


def wait_on(key, table, field):
    return Activity(key=key, raw_type="WAIT", kind=KIND_WAIT_ATTRIBUTE, name=key,
                    outcomes=[Outcome(key=f"{key}-out", label="", next=None)], wait_field=(table, field))


def update(key, table, field, value="x"):
    return Activity(key=key, raw_type="UPDATECONTACTDATA", kind=KIND_UPDATE, name=key,
                    outcomes=[Outcome(key=f"{key}-out", label="", next=None)],
                    writes=[Write(table=table, field=field, value=value)])


def query(name, target):
    return Query(id=f"id-{name}", name=name, target_table=target, sql=f"-- {name}: parsed by the stub",
                 update_type="Update")


def relation(left_table, left_field, right_table, right_field):
    """A relationship; ``left_table`` None is a group-to-set link (the contact model pointing at a table)."""
    return Relationship(name=f"{left_table or 'Contact'} -> {right_table}", left_table=left_table,
                        left_field=left_field, right_table=right_table, right_field=right_field,
                        left_cardinality="One", right_cardinality="One")


def make_package(table_list, activities=(), entry=ENTRY, queries=(), automation=(), relationships=()):
    """A package whose entry event is fed by automation A_Entry running ``automation`` (query names)."""
    activities = list(activities)
    journey = Journey(name="J", key="J", activities={a.key: a for a in activities},
                      start_key=activities[0].key if activities else None, entry_event_key="EV",
                      entry_table=entry, activity_count=len(activities))
    return Package(name="P", journey=journey, tables={t.name: t for t in table_list},
                   relationships=list(relationships), queries=list(queries),
                   entry_event=EntryEvent(key="EV", name="EV", table=entry, automation_name="A_Entry"),
                   emails={}, automation_queries={"A_Entry": list(automation)})


def col(ref):
    """``"Table.Column"`` -> ColumnRef; ``".Column"`` is a column the parser could not tie to a table."""
    table, _, column = ref.partition(".")
    return ColumnRef(table=table, column=column)


def parsed(name, target, sources, joins=(), filters=(), select=(), warnings=()):
    """A ParsedQuery: joins are (left, right) pairs, filters (column, value) equalities,
    select (target column, source column) plain copies."""
    return ParsedQuery(
        name=name, target_table=target,
        sources=[TableRef(table=t, alias=None) for t in sources],
        joins=[JoinEquality(left=col(a), right=col(b)) for a, b in joins],
        filters=[EqualityFilter(column=col(c), value=v) for c, v in filters],
        select=[SelectItem(target_column=t, expr=SelectColumn(source=col(s))) for t, s in select],
        warnings=list(warnings))


class ParserStub:
    """Stands in for sqlparse_lite.parse_query: answers by query name and records the calls."""

    def __init__(self):
        self.answers = {}
        self.calls = []

    def add(self, parsed_query):
        self.answers[parsed_query.name] = parsed_query

    def __call__(self, query, schema):
        self.calls.append(query.name)
        return self.answers[query.name]


@pytest.fixture
def sql(monkeypatch):
    stub = ParserStub()
    monkeypatch.setattr(tables.sqlparse_lite, "parse_query", stub)
    return stub


def summary(model):
    return {name: (role.roles, role.selected, role.level) for name, role in model.tables.items()}


def groups(model):
    return [(group.kind, group.fields) for group in model.key_groups]


def fields_of(package, name):
    return [f.name for f in package.tables[name].fields]


def pilot_like(sql):
    """The pilot's shape in miniature (docs/progress.md, "Facts checked on the pilot export")."""
    table_list = [
        make_table(ENTRY, text("ContactId", pk=True), text("CampaignName", pk=True), text("Emailaddress"),
                   boolean("Control Group"), sendable_field="ContactId"),
        make_table(MASTER, text("ContactId", pk=True), text("Emailaddress"), boolean("IsMailOffers"),
                   sendable_field="ContactId"),
        make_table(TARGET, text("SalesforceId", pk=True), text("Description", pk=True), date("CreatedDate"),
                   sendable_field="SalesforceId"),
        make_table(CONFIG, text("CampaignName", pk=True), text("CHANNEL1"), date("WAIT1"), boolean("ACTIVE"),
                   boolean("HAS_RUN")),
        make_table("DE_Log", text("ContactId", pk=True), text("CampaignName", pk=True), sendable_field="ContactId"),
        make_table("DE_Entry_Backup", text("ContactId", pk=True), sendable_field="ContactId"),
        make_table("DE_Check", text("CampaignName"), boolean("Active")),
        make_table("DE_Unused", text("Id", pk=True)),
    ]
    activities = [
        decision("SPLIT-1", cond(CONFIG, "CHANNEL1", "Email", "Equal")),
        decision("SPLIT-2", cond(MASTER, "IsMailOffers"), cond(CONFIG, "CHANNEL1", "DM", "Equal")),
        wait_on("WAIT-1", CONFIG, "WAIT1"),
        update("UPDATE-1", "DE_Log", "CampaignName", "Demo"),
        update("UPDATE-2", ENTRY, "Control Group", "true"),
    ]
    queries = [query("Q_Check", "DE_Check"), query("Q_Entry", ENTRY), query("Q_ConfigUpdate", CONFIG),
               query("Q_Backup", "DE_Entry_Backup")]
    sql.add(parsed("Q_Entry", ENTRY, [MASTER, TARGET, CONFIG],
                   joins=[("DE_Master.ContactId", "DE_Target.SalesforceId"),
                          ("DE_Target.Description", "DE_Config.CampaignName")],
                   filters=[("DE_Config.active", "True"), ("DE_Config.HAS_RUN", "False")],
                   select=[("ContactId", "DE_Master.ContactId"), ("CampaignName", "DE_Config.CampaignName"),
                           ("Emailaddress", "DE_Master.Emailaddress"), ("FirstName", "DE_Master.FirstName")]))
    sql.add(parsed("Q_ConfigUpdate", CONFIG, [CONFIG, ENTRY],
                   joins=[("DE_Config.CampaignName", "DE_Entry.CampaignName")],
                   select=[("CampaignName", "DE_Config.CampaignName")]))
    relationships = [
        relation(None, None, MASTER, "ContactId"),
        relation(MASTER, "ContactId", ENTRY, "ContactId"),
        relation(ENTRY, "CampaignName", CONFIG, "CampaignName"),
    ]
    return make_package(table_list, activities, ENTRY, queries,
                        automation=["Q_Check", "Q_Entry", "Q_ConfigUpdate", "Q_Backup"], relationships=relationships)


# ---------------------------------------------------------------------------
# The pilot's shape
# ---------------------------------------------------------------------------

def test_pilot_shape_roles_levels_and_keys(sql):
    package = pilot_like(sql)
    model = tables.build_table_model(package)

    assert summary(model) == {
        ENTRY: ({ROLE_ENTRY}, True, LEVEL_CONTACT),
        "DE_Check": ({ROLE_WRITTEN}, False, None),
        CONFIG: ({ROLE_SPLIT, ROLE_SOURCE}, True, LEVEL_SCENARIO),
        "DE_Entry_Backup": ({ROLE_WRITTEN}, False, None),
        "DE_Log": ({ROLE_WRITTEN}, False, None),
        MASTER: ({ROLE_SPLIT, ROLE_SOURCE}, True, LEVEL_CONTACT),
        TARGET: ({ROLE_SOURCE}, True, LEVEL_CONTACT),
        "DE_Unused": (set(), False, None),
    }
    assert list(model.tables) == [ENTRY, "DE_Check", CONFIG, "DE_Entry_Backup", "DE_Log", MASTER, TARGET, "DE_Unused"]
    assert model.selected_tables == [ENTRY, CONFIG, MASTER, TARGET]
    assert model.contact_tables == [ENTRY, MASTER, TARGET]
    assert model.scenario_tables == [CONFIG]

    # The query writing Config from Config and the entry table is followed once, then the walk stops.
    assert model.entry_query.name == "Q_Entry"
    assert [q.name for q in model.source_queries] == ["Q_Entry", "Q_ConfigUpdate"]
    assert sql.calls == ["Q_Entry", "Q_ConfigUpdate"]

    assert model.contact_key_field == (ENTRY, "ContactId")
    assert groups(model) == [
        ("contact", [(ENTRY, "ContactId"), (MASTER, "ContactId"), (TARGET, "SalesforceId")]),
        ("scenario", [(ENTRY, "CampaignName"), (CONFIG, "CampaignName"), (TARGET, "Description")]),
    ]

    selected_fields = {(name, f) for name in model.selected_tables for f in fields_of(package, name)}
    assert set(model.field_levels) == selected_fields
    assert model.field_levels[(TARGET, "Description")] == LEVEL_SCENARIO
    assert model.field_levels[(TARGET, "SalesforceId")] == LEVEL_CONTACT
    assert model.field_levels[(TARGET, "CreatedDate")] == LEVEL_CONTACT
    assert model.field_levels[(ENTRY, "CampaignName")] == LEVEL_SCENARIO
    assert model.field_levels[(ENTRY, "Control Group")] == LEVEL_CONTACT
    assert {model.field_levels[(CONFIG, f)] for f in fields_of(package, CONFIG)} == {LEVEL_SCENARIO}
    assert {model.field_levels[(MASTER, f)] for f in fields_of(package, MASTER)} == {LEVEL_CONTACT}

    assert model.activation_field == (CONFIG, "ACTIVE")
    assert model.warnings == []


def test_pilot_shape_reasons_are_plain_words(sql):
    model = tables.build_table_model(pilot_like(sql))
    reasons = {name: role.reason for name, role in model.tables.items()}

    assert reasons[ENTRY] == ("Entry table of the journey, filled by the entry query Q_Entry; also written by "
                              "1 update contact step. Contact-level: it is the entry table, one row per contact.")
    assert reasons[MASTER] == ("Read by 1 split and the entry query Q_Entry. Contact-level: joined to the entry "
                               "on the contact key (DE_Master.ContactId).")
    assert reasons[TARGET] == ("Read by the entry query Q_Entry. Contact-level: joined to the entry on the "
                               "contact key (DE_Target.SalesforceId).")
    assert reasons[CONFIG] == (
        "Read by 2 splits, 1 wait by attribute and the entry query Q_Entry; also written by query "
        "Q_ConfigUpdate. Scenario-level: joined on DE_Entry.CampaignName = DE_Config.CampaignName, not on "
        "the contact key, so many contacts share one row. Its field ACTIVE is suggested as the activation "
        "field (entry query filter active = 'True').")
    assert reasons["DE_Log"] == "Written by 1 update contact step, never read by a split or by the entry query: no CSV."
    assert reasons["DE_Check"] == "Written by query Q_Check, never read by a split or by the entry query: no CSV."
    assert reasons["DE_Entry_Backup"] == ("Written by query Q_Backup, never read by a split or by the entry query: "
                                          "no CSV.")
    assert reasons["DE_Unused"] == "Not read or written by this journey."


# ---------------------------------------------------------------------------
# Entry query
# ---------------------------------------------------------------------------

def test_no_entry_query_leaves_the_entry_table_alone(sql):
    package = make_package(
        [make_table(ENTRY, text("ContactId", pk=True), text("Segment"), sendable_field="ContactId"),
         make_table(CONFIG, text("CampaignName", pk=True), boolean("ACTIVE"))],
        [decision("SPLIT-1", cond(CONFIG, "ACTIVE")), decision("SPLIT-2", cond(ENTRY, "Segment", "A", "Equal"))])
    model = tables.build_table_model(package)

    assert model.entry_query is None
    assert model.source_queries == []
    assert sql.calls == []
    assert summary(model) == {
        ENTRY: ({ROLE_ENTRY, ROLE_SPLIT}, True, LEVEL_CONTACT),
        CONFIG: ({ROLE_SPLIT}, True, LEVEL_SCENARIO),
    }
    assert groups(model) == [("contact", [(ENTRY, "ContactId")])]
    assert model.field_levels == {
        (ENTRY, "ContactId"): LEVEL_CONTACT, (ENTRY, "Segment"): LEVEL_CONTACT,
        (CONFIG, "CampaignName"): LEVEL_SCENARIO, (CONFIG, "ACTIVE"): LEVEL_SCENARIO,
    }
    assert model.activation_field is None
    assert model.warnings == [
        "No query of the entry automation A_Entry fills the entry table DE_Entry, and no other query of the "
        "export fills DE_Entry: there is no entry query, so the entry table alone is the source side",
        "Table DE_Config is not joined to the entry: treated as one row shared by all contacts "
        "(scenario-level). This is an assumption: check how the journey links this table",
    ]
    assert "filled by no query of the export" in model.tables[ENTRY].reason
    assert "Scenario-level: not joined to the entry" in model.tables[CONFIG].reason


def test_entry_query_is_the_last_of_the_entry_automation(sql):
    package = make_package(
        [make_table(ENTRY, text("ContactId", pk=True), sendable_field="ContactId"),
         make_table(MASTER, text("ContactId", pk=True))],
        queries=[query("Q_First", ENTRY), query("Q_Second", ENTRY)], automation=["Q_First", "Q_Second"])
    sql.add(parsed("Q_Second", ENTRY, [MASTER], select=[("ContactId", "DE_Master.ContactId")],
                   warnings=["an OR group in WHERE is not understood"]))
    model = tables.build_table_model(package)

    assert model.entry_query.name == "Q_Second"
    assert sql.calls == ["Q_Second"]
    assert model.warnings == [
        "Several queries of the entry automation fill the entry table DE_Entry (Q_First and Q_Second): "
        "the last one in step order, Q_Second, is taken as the entry query",
        "Query Q_Second: an OR group in WHERE is not understood",
    ]
    assert "also written by query Q_First" in model.tables[ENTRY].reason
    assert model.tables[MASTER].level == LEVEL_CONTACT


def test_entry_query_found_outside_the_entry_automation(sql):
    package = make_package(
        [make_table(ENTRY, text("ContactId", pk=True), sendable_field="ContactId"),
         make_table(MASTER, text("ContactId", pk=True))],
        queries=[query("Q_Unrelated", MASTER), query("Q_Elsewhere", ENTRY)],
        automation=["Q_Unrelated", "Q_Missing"])
    sql.add(parsed("Q_Elsewhere", ENTRY, [MASTER], select=[("ContactId", "DE_Master.ContactId")]))
    sql.add(parsed("Q_Unrelated", MASTER, []))
    model = tables.build_table_model(package)

    assert model.entry_query.name == "Q_Elsewhere"
    # Master is a source, so the query writing it is followed too.
    assert [q.name for q in model.source_queries] == ["Q_Elsewhere", "Q_Unrelated"]
    assert model.warnings == [
        "The entry automation A_Entry runs query Q_Missing, which is not in the export",
        "No query of the entry automation A_Entry fills the entry table DE_Entry; query Q_Elsewhere fills "
        "DE_Entry and is taken as the entry query",
    ]


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def test_table_both_written_and_read_is_selected(sql):
    package = make_package(
        [make_table(ENTRY, text("ContactId", pk=True), sendable_field="ContactId"),
         make_table(MASTER, text("ContactId", pk=True), boolean("Flag")),
         make_table(CONFIG, text("CampaignName", pk=True), text("Channel")),
         make_table("DE_Log", text("ContactId", pk=True))],
        [decision("SPLIT-1", cond(MASTER, "Flag"), cond(CONFIG, "Channel", "Email", "Equal")),
         update("UPDATE-1", MASTER, "Flag", "false"),
         update("UPDATE-2", "DE_Log", "ContactId")],
        queries=[query("Q_Config", CONFIG)],
        relationships=[relation(MASTER, "ContactId", ENTRY, "ContactId")])
    model = tables.build_table_model(package)

    master, config, log = model.tables[MASTER], model.tables[CONFIG], model.tables["DE_Log"]
    assert (master.roles, master.selected, master.level) == ({ROLE_SPLIT}, True, LEVEL_CONTACT)
    assert master.reason.startswith("Read by 1 split; also written by 1 update contact step.")
    assert (config.roles, config.selected) == ({ROLE_SPLIT}, True)
    assert config.reason.startswith("Read by 1 split; also written by query Q_Config.")
    assert (log.roles, log.selected, log.level) == ({ROLE_WRITTEN}, False, None)
    assert sql.calls == []   # Q_Config feeds no source table: it is never parsed


def test_split_on_a_table_or_field_missing_from_the_export(sql):
    package = make_package(
        [make_table(ENTRY, text("ContactId", pk=True), sendable_field="ContactId")],
        [decision("SPLIT-1", cond("DE_Ghost", "X")), decision("SPLIT-2", cond(ENTRY, "Nope")),
         decision("SPLIT-3", cond("DE_Ghost", "Y"))])
    model = tables.build_table_model(package)

    assert list(model.tables) == [ENTRY]
    assert "Table DE_Ghost is read by SPLIT-1 and SPLIT-3 but is not in the export: no CSV can be made for it" \
        in model.warnings
    assert "DE_Entry.Nope is read by SPLIT-2 but is not a field of the export" in model.warnings


# ---------------------------------------------------------------------------
# Following the sources back
# ---------------------------------------------------------------------------

def test_source_chain_of_two_queries(sql):
    """Entry <- Q1 FROM DE_A; DE_A <- Q2 FROM DE_B, in another automation: both tables are sources."""
    package = make_package(
        [make_table(ENTRY, text("ContactId", pk=True), text("Email"), sendable_field="ContactId"),
         make_table("DE_A", text("Id", pk=True), text("Email")),
         make_table("DE_B", text("Key", pk=True), text("Mail"))],
        queries=[query("Q2", "DE_A"), query("Q1", ENTRY)], automation=["Q1"])
    sql.add(parsed("Q1", ENTRY, ["DE_A"], select=[("ContactId", "DE_A.Id"), ("Email", "DE_A.Email")]))
    sql.add(parsed("Q2", "DE_A", ["DE_B"], select=[("Id", "DE_B.Key"), ("Email", "DE_B.Mail")]))
    model = tables.build_table_model(package)

    assert [q.name for q in model.source_queries] == ["Q1", "Q2"]
    assert summary(model) == {
        ENTRY: ({ROLE_ENTRY}, True, LEVEL_CONTACT),
        "DE_A": ({ROLE_SOURCE}, True, LEVEL_CONTACT),
        "DE_B": ({ROLE_SOURCE}, True, LEVEL_CONTACT),
    }
    assert model.tables["DE_A"].reason.startswith("Read by the entry query Q1; also written by query Q2.")
    assert model.tables["DE_B"].reason.startswith("Read by query Q2, which fills DE_A.")
    # The copied contact key links the three tables; the copied e-mail columns do not become keys.
    assert groups(model) == [("contact", [(ENTRY, "ContactId"), ("DE_A", "Id"), ("DE_B", "Key")])]
    assert model.warnings == []


def test_writers_of_a_source_are_followed_entry_automation_first(sql):
    package = make_package(
        [make_table(ENTRY, text("ContactId", pk=True), sendable_field="ContactId"),
         make_table("DE_A", text("ContactId", pk=True)),
         make_table("DE_B", text("ContactId", pk=True)),
         make_table("DE_C", text("ContactId", pk=True))],
        queries=[query("Q_Nightly", "DE_A"), query("Q_Entry", ENTRY), query("Q_Refresh", "DE_A")],
        automation=["Q_Refresh", "Q_Entry"])
    sql.add(parsed("Q_Entry", ENTRY, ["DE_A"], select=[("ContactId", "DE_A.ContactId")]))
    sql.add(parsed("Q_Refresh", "DE_A", ["DE_B"], select=[("ContactId", "DE_B.ContactId")]))
    sql.add(parsed("Q_Nightly", "DE_A", ["DE_C"], select=[("ContactId", "DE_C.ContactId")]))
    model = tables.build_table_model(package)

    assert [q.name for q in model.source_queries] == ["Q_Entry", "Q_Refresh", "Q_Nightly"]
    assert {name: role.roles for name, role in model.tables.items()} == {
        ENTRY: {ROLE_ENTRY}, "DE_A": {ROLE_SOURCE}, "DE_B": {ROLE_SOURCE}, "DE_C": {ROLE_SOURCE}}
    assert model.contact_tables == [ENTRY, "DE_A", "DE_B", "DE_C"]


def test_cycles_stop(sql):
    """Config is written from Config and the entry table (as in the pilot); DE_A and DE_B fill each other."""
    package = make_package(
        [make_table(ENTRY, text("ContactId", pk=True), text("CampaignName"), sendable_field="ContactId"),
         make_table(CONFIG, text("CampaignName", pk=True)),
         make_table("DE_A", text("ContactId", pk=True), text("Campaign")),
         make_table("DE_B", text("ContactId", pk=True), text("Campaign"))],
        queries=[query("Q_Entry", ENTRY), query("Q_Config", CONFIG), query("Q_A", "DE_A"), query("Q_B", "DE_B")],
        automation=["Q_Entry", "Q_Config"])
    sql.add(parsed("Q_Entry", ENTRY, ["DE_A", CONFIG], joins=[("DE_A.Campaign", "DE_Config.CampaignName")],
                   select=[("ContactId", "DE_A.ContactId"), ("CampaignName", "DE_Config.CampaignName")]))
    sql.add(parsed("Q_Config", CONFIG, [CONFIG, ENTRY], joins=[("DE_Config.CampaignName", "DE_Entry.CampaignName")]))
    sql.add(parsed("Q_A", "DE_A", ["DE_B"], select=[("ContactId", "DE_B.ContactId"), ("Campaign", "DE_B.Campaign")]))
    sql.add(parsed("Q_B", "DE_B", ["DE_A"], select=[("ContactId", "DE_A.ContactId")]))
    model = tables.build_table_model(package)

    assert sql.calls == ["Q_Entry", "Q_A", "Q_Config", "Q_B"]
    assert [q.name for q in model.source_queries] == sql.calls
    assert summary(model) == {
        ENTRY: ({ROLE_ENTRY}, True, LEVEL_CONTACT),
        "DE_A": ({ROLE_SOURCE}, True, LEVEL_CONTACT),
        "DE_B": ({ROLE_SOURCE}, True, LEVEL_CONTACT),
        CONFIG: ({ROLE_SOURCE}, True, LEVEL_SCENARIO),
    }
    assert groups(model) == [
        ("contact", [(ENTRY, "ContactId"), ("DE_A", "ContactId"), ("DE_B", "ContactId")]),
        ("scenario", [(ENTRY, "CampaignName"), ("DE_A", "Campaign"), ("DE_B", "Campaign"), (CONFIG, "CampaignName")]),
    ]
    assert model.warnings == []


# ---------------------------------------------------------------------------
# Contact key
# ---------------------------------------------------------------------------

def test_contact_key_is_the_sendable_field_in_schema_spelling(sql):
    package = make_package([make_table(ENTRY, text("Id", pk=True), text("ContactId"), sendable_field="contactid")])
    model = tables.build_table_model(package)

    assert model.contact_key_field == (ENTRY, "ContactId")
    assert not any("contact key" in w for w in model.warnings)


def test_contact_key_falls_back_to_the_contact_link_of_the_entry_table(sql):
    package = make_package([make_table(ENTRY, text("Id", pk=True), text("SubscriberKey"))],
                           relationships=[relation(None, None, "de_entry", "subscriberkey")])
    model = tables.build_table_model(package)

    assert model.contact_key_field == (ENTRY, "SubscriberKey")
    assert ("The entry table DE_Entry has no usable sendable field: the contact key is SubscriberKey, the field "
            "relationship Contact -> de_entry links to the contact") in model.warnings


def test_contact_key_falls_back_to_a_single_field_primary_key(sql):
    package = make_package(
        [make_table(ENTRY, text("Email"), text("Id", pk=True)), make_table(MASTER, text("ContactId", pk=True))],
        relationships=[relation(None, None, MASTER, "ContactId")])   # links another table, not the entry
    model = tables.build_table_model(package)

    assert model.contact_key_field == (ENTRY, "Id")
    assert ("The entry table DE_Entry has no usable sendable field and no contact link: the contact key is its "
            "primary key Id") in model.warnings


def test_contact_key_falls_back_to_the_first_of_several_primary_key_fields(sql):
    package = make_package(
        [make_table(ENTRY, text("Email"), text("ContactId", pk=True), text("CampaignName", pk=True))])
    model = tables.build_table_model(package)

    assert model.contact_key_field == (ENTRY, "ContactId")
    assert any("several fields (ContactId and CampaignName)" in w and "the first one, ContactId" in w
               for w in model.warnings)


def test_sendable_field_missing_from_the_schema_falls_back(sql):
    package = make_package([make_table(ENTRY, text("Id", pk=True), sendable_field="ContactId")])
    model = tables.build_table_model(package)

    assert model.contact_key_field == (ENTRY, "Id")
    assert "The sendable field ContactId of the entry table DE_Entry is not in its schema" in model.warnings


# ---------------------------------------------------------------------------
# Levels and key groups
# ---------------------------------------------------------------------------

def test_contact_key_link_wins_over_a_scenario_neighbour(sql):
    """Target is joined to Master on the contact key and to Config on the campaign. The relationships list
    the Config links first, so a walk taking the first link it meets would reach Target from Config."""
    package = make_package(
        [make_table(ENTRY, text("ContactId", pk=True), text("CampaignName"), sendable_field="ContactId"),
         make_table(MASTER, text("ContactId", pk=True), boolean("Flag")),
         make_table(TARGET, text("SalesforceId", pk=True), text("Description")),
         make_table(CONFIG, text("CampaignName", pk=True), text("Channel"))],
        [decision("SPLIT-1", cond(MASTER, "Flag"), cond(CONFIG, "Channel", "SMS", "Equal"),
                  cond(TARGET, "Description", "X"))],
        relationships=[relation(ENTRY, "CampaignName", CONFIG, "CampaignName"),
                       relation(CONFIG, "CampaignName", TARGET, "Description"),
                       relation(ENTRY, "ContactId", MASTER, "ContactId"),
                       relation(MASTER, "ContactId", TARGET, "SalesforceId")])
    model = tables.build_table_model(package)

    assert {name: role.level for name, role in model.tables.items()} == {
        ENTRY: LEVEL_CONTACT, CONFIG: LEVEL_SCENARIO, MASTER: LEVEL_CONTACT, TARGET: LEVEL_CONTACT}
    assert model.field_levels[(TARGET, "Description")] == LEVEL_SCENARIO
    assert model.field_levels[(TARGET, "SalesforceId")] == LEVEL_CONTACT


def test_neighbour_of_a_scenario_table_is_scenario_level(sql):
    package = make_package(
        [make_table(ENTRY, text("ContactId", pk=True), text("CampaignName"), sendable_field="ContactId"),
         make_table(CONFIG, text("CampaignName", pk=True), text("PromoCode")),
         make_table("DE_Promo", text("PromoCode", pk=True), text("Discount"))],
        [decision("SPLIT-1", cond(CONFIG, "PromoCode", "P1", "Equal"), cond("DE_Promo", "Discount", "10", "Equal"))],
        relationships=[relation(ENTRY, "CampaignName", CONFIG, "CampaignName"),
                       relation(CONFIG, "PromoCode", "DE_Promo", "PromoCode")])
    model = tables.build_table_model(package)

    assert model.scenario_tables == [CONFIG, "DE_Promo"]
    assert groups(model) == [
        ("contact", [(ENTRY, "ContactId")]),
        ("scenario", [(ENTRY, "CampaignName"), (CONFIG, "CampaignName")]),
        ("scenario", [(CONFIG, "PromoCode"), ("DE_Promo", "PromoCode")]),
    ]
    assert ("Scenario-level: joined on DE_Config.PromoCode = DE_Promo.PromoCode, not on the contact key, so many "
            "contacts share one row.") in model.tables["DE_Promo"].reason
    assert not any("not joined to the entry" in w for w in model.warnings)


def test_link_through_a_table_without_csv_still_counts(sql):
    """Entry -> Log -> Foo on the contact key: Log is only written, Foo is read by a split."""
    package = make_package(
        [make_table(ENTRY, text("ContactId", pk=True), sendable_field="ContactId"),
         make_table("DE_Log", text("ContactId", pk=True)),
         make_table("DE_Foo", text("ContactId", pk=True), boolean("Flag"))],
        [decision("SPLIT-1", cond("DE_Foo", "Flag")), update("UPDATE-1", "DE_Log", "ContactId")],
        relationships=[relation(ENTRY, "ContactId", "DE_Log", "ContactId"),
                       relation("DE_Log", "ContactId", "DE_Foo", "ContactId")])
    model = tables.build_table_model(package)

    assert model.tables["DE_Foo"].level == LEVEL_CONTACT
    # Members without a CSV stay in the group.
    assert groups(model) == [("contact", [(ENTRY, "ContactId"), ("DE_Foo", "ContactId"), ("DE_Log", "ContactId")])]


def test_contact_model_link_holds_the_contact_key(sql):
    """The entry table is not in the contact model; Master is linked to the contact itself (group-to-set)."""
    package = make_package(
        [make_table(ENTRY, text("ContactId", pk=True), sendable_field="ContactId"),
         make_table(MASTER, text("ContactId", pk=True), text("Segment"), boolean("Flag")),
         make_table(CONFIG, text("Segment", pk=True), text("Channel"))],
        [decision("SPLIT-1", cond(MASTER, "Flag"), cond(CONFIG, "Channel", "Email", "Equal"))],
        relationships=[relation(None, None, MASTER, "ContactId"), relation(MASTER, "Segment", CONFIG, "Segment")])
    model = tables.build_table_model(package)

    assert model.contact_tables == [ENTRY, MASTER]
    assert model.scenario_tables == [CONFIG]
    assert groups(model) == [
        ("contact", [(ENTRY, "ContactId"), (MASTER, "ContactId")]),
        ("scenario", [(CONFIG, "Segment"), (MASTER, "Segment")]),
    ]
    assert model.field_levels[(MASTER, "Segment")] == LEVEL_SCENARIO
    assert model.field_levels[(MASTER, "Flag")] == LEVEL_CONTACT


def test_contact_key_field_comes_first_in_its_group(sql):
    """Two entry fields hold the contact key: the sendable one is listed first, so a consumer taking the
    first entry field of the group gets the contact key field."""
    package = make_package(
        [make_table(ENTRY, text("ContactId", pk=True), text("SubscriberKey"), sendable_field="SubscriberKey")],
        relationships=[relation(None, None, ENTRY, "ContactId")])
    model = tables.build_table_model(package)

    assert model.contact_key_field == (ENTRY, "SubscriberKey")
    assert groups(model) == [("contact", [(ENTRY, "SubscriberKey"), (ENTRY, "ContactId")])]


def test_entry_query_copy_carries_the_contact_key_without_relationships(sql):
    package = make_package(
        [make_table(ENTRY, text("ContactId", pk=True), text("Email"), text("CampaignName"), sendable_field="ContactId"),
         make_table(MASTER, text("ContactId", pk=True), text("Email"), text("Segment")),
         make_table(CONFIG, text("Segment", pk=True), text("CampaignName"))],
        queries=[query("Q_Entry", ENTRY)], automation=["Q_Entry"])
    sql.add(parsed("Q_Entry", ENTRY, [MASTER, CONFIG], joins=[("DE_Master.Segment", "DE_Config.Segment")],
                   select=[("ContactId", "DE_Master.ContactId"), ("Email", "DE_Master.Email"),
                           ("CampaignName", "DE_Config.CampaignName")]))
    model = tables.build_table_model(package)

    assert model.contact_tables == [ENTRY, MASTER]
    assert model.scenario_tables == [CONFIG]
    assert groups(model) == [
        ("contact", [(ENTRY, "ContactId"), (MASTER, "ContactId")]),
        ("scenario", [(CONFIG, "Segment"), (MASTER, "Segment")]),
    ]
    assert model.warnings == []


def test_unresolvable_join_sides_are_skipped_with_a_warning(sql):
    package = make_package(
        [make_table(ENTRY, text("ContactId", pk=True), sendable_field="ContactId"),
         make_table(MASTER, text("ContactId", pk=True), text("CampaignName")),
         make_table(CONFIG, text("CampaignName", pk=True))],
        queries=[query("Q_Entry", ENTRY)], automation=["Q_Entry"],
        relationships=[relation(MASTER, "ContactId", "DE_Gone", "ContactId")])
    sql.add(parsed("Q_Entry", ENTRY, [MASTER, CONFIG, "DE_Missing"],
                   joins=[(".CampaignName", "DE_Config.CampaignName"),
                          ("DE_Master.Nope", "DE_Config.CampaignName"),
                          ("DE_Missing.X", "DE_Config.CampaignName")],
                   select=[("ContactId", "DE_Master.ContactId")]))
    model = tables.build_table_model(package)

    assert model.warnings == [
        "Query Q_Entry reads table DE_Missing, which is not in the export: no CSV can be made for it",
        "Query Q_Entry: join CampaignName = DE_Config.CampaignName is skipped: the table of column CampaignName "
        "is not known",
        "Query Q_Entry: join DE_Master.Nope = DE_Config.CampaignName is skipped: DE_Master has no field Nope",
        "Query Q_Entry: join DE_Missing.X = DE_Config.CampaignName is skipped: table DE_Missing is not in the export",
        "Relationship DE_Master -> DE_Gone is skipped: table DE_Gone is not in the export",
        "Table DE_Config is not joined to the entry: treated as one row shared by all contacts (scenario-level). "
        "This is an assumption: check how the journey links this table",
    ]
    assert model.tables[MASTER].level == LEVEL_CONTACT
    assert model.tables[CONFIG].level == LEVEL_SCENARIO


def test_a_field_equal_to_itself_makes_no_key_group(sql):
    package = make_package(
        [make_table(ENTRY, text("ContactId", pk=True), text("Segment"), sendable_field="ContactId")],
        [decision("SPLIT-1", cond(ENTRY, "Segment", "A", "Equal"))],
        relationships=[relation(ENTRY, "Segment", ENTRY, "segment")])
    model = tables.build_table_model(package)

    assert groups(model) == [("contact", [(ENTRY, "ContactId")])]
    assert model.field_levels[(ENTRY, "Segment")] == LEVEL_CONTACT


# ---------------------------------------------------------------------------
# Activation field and letter case
# ---------------------------------------------------------------------------

def _activation_package(sql, filters):
    package = make_package(
        [make_table(ENTRY, text("ContactId", pk=True), sendable_field="ContactId"),
         make_table(MASTER, text("ContactId", pk=True), text("CampaignName"), boolean("Vip")),
         make_table(CONFIG, text("CampaignName", pk=True), boolean("ACTIVE"), text("Label"))],
        queries=[query("Q_Entry", ENTRY)], automation=["Q_Entry"])
    sql.add(parsed("Q_Entry", ENTRY, [MASTER, CONFIG], joins=[("DE_Master.CampaignName", "DE_Config.CampaignName")],
                   filters=filters, select=[("ContactId", "DE_Master.ContactId")]))
    return package


def test_boolean_filter_on_false_is_not_an_activation_field(sql):
    package = _activation_package(sql, [
        ("DE_Config.ACTIVE", "False"),   # false
        ("DE_Master.Vip", "True"),       # contact-level table
        ("DE_Config.Label", "True"),     # not a Boolean field
    ])
    model = tables.build_table_model(package)

    assert model.tables[CONFIG].level == LEVEL_SCENARIO
    assert model.activation_field is None
    assert "activation field" not in model.tables[CONFIG].reason


def test_first_true_boolean_filter_is_the_activation_field(sql):
    package = _activation_package(sql, [("DE_Config.Label", "x"), ("de_config.active", "TRUE"),
                                        ("DE_CONFIG.Active", "true")])
    model = tables.build_table_model(package)

    assert model.activation_field == (CONFIG, "ACTIVE")
    assert any(w.startswith("Several entry query filters could be the activation field") for w in model.warnings)


def test_sql_and_criteria_spelling_is_normalised_to_the_schema(sql):
    package = make_package(
        [make_table(ENTRY, text("ContactId", pk=True), text("CampaignName"), sendable_field="ContactId"),
         make_table(MASTER, text("ContactId", pk=True), text("CampaignName"), boolean("Optin")),
         make_table(CONFIG, text("CampaignName", pk=True), text("CHANNEL1"), date("WAIT1"), boolean("ACTIVE"))],
        [decision("SPLIT-1", cond("de_config", "channel1", "Email", "Equal")),
         decision("SPLIT-2", cond("DE_MASTER", "OPTIN")),
         wait_on("WAIT-1", "de_config", "wait1")],
        queries=[query("Q_Entry", "de_entry")], automation=["Q_Entry"],
        relationships=[relation("de_master", "contactid", "DE_ENTRY", "CONTACTID")])
    sql.add(parsed("Q_Entry", "de_entry", ["de_master", "DE_CONFIG"],
                   joins=[("de_master.CAMPAIGNNAME", "de_config.campaignname")],
                   filters=[("DE_CONFIG.active", "true")],
                   select=[("contactid", "de_master.contactid"), ("campaignname", "de_config.CampaignName")]))
    model = tables.build_table_model(package)

    assert model.entry_query.name == "Q_Entry"
    assert summary(model) == {
        ENTRY: ({ROLE_ENTRY}, True, LEVEL_CONTACT),
        CONFIG: ({ROLE_SPLIT, ROLE_SOURCE}, True, LEVEL_SCENARIO),
        MASTER: ({ROLE_SPLIT, ROLE_SOURCE}, True, LEVEL_CONTACT),
    }
    assert groups(model) == [
        ("contact", [(ENTRY, "ContactId"), (MASTER, "ContactId")]),
        ("scenario", [(ENTRY, "CampaignName"), (CONFIG, "CampaignName"), (MASTER, "CampaignName")]),
    ]
    assert model.activation_field == (CONFIG, "ACTIVE")
    assert model.field_levels[(MASTER, "Optin")] == LEVEL_CONTACT
    assert model.field_levels[(CONFIG, "CHANNEL1")] == LEVEL_SCENARIO
    assert model.warnings == []


# ---------------------------------------------------------------------------
# The pilot export, end to end (needs loader.py and sqlparse_lite.py)
# ---------------------------------------------------------------------------

def test_pilot_export():
    if not SQLPARSE_WRITTEN:
        pytest.skip("cjhelper.sqlparse_lite is not written yet")
    loader = pytest.importorskip("cjhelper.loader")
    package = loader.load_package(PILOT)
    model = tables.build_table_model(package)

    entry, master = "DE_NCM_AdHoc_Entry", "SF_Master_DataExtension_DE"
    target, config = "DE_NCRM_AdHoc_Target", "DE_NCRM_AD_HOC_CONFIG"
    assert summary(model) == {
        entry: ({ROLE_ENTRY}, True, LEVEL_CONTACT),
        master: ({ROLE_SPLIT, ROLE_SOURCE}, True, LEVEL_CONTACT),
        target: ({ROLE_SOURCE}, True, LEVEL_CONTACT),
        config: ({ROLE_SPLIT, ROLE_SOURCE}, True, LEVEL_SCENARIO),
        "DE_SkyDE_AdHoc_Log_partial": ({ROLE_WRITTEN}, False, None),
        "DE_NCRM_AdHoc_Entry_Backup": ({ROLE_WRITTEN}, False, None),
        "DE_Check_Active_Campaigns": ({ROLE_WRITTEN}, False, None),
    }
    assert model.entry_query.name == "Q_SKYDE_AdHoc_Target"
    assert [q.name for q in model.source_queries] == [
        "Q_SKYDE_AdHoc_Target", "Q_SKYDE_NCRM_AD_HOC_CONFIGURATION_UPDATE"]
    assert model.contact_key_field == (entry, "ContactId")
    assert groups(model) == [
        ("contact", [(entry, "ContactId"), (target, "SalesforceId"), (master, "ContactId")]),
        ("scenario", [(entry, "CampaignName"), (config, "CampaignName"), (target, "Description")]),
    ]
    assert model.field_levels[(target, "Description")] == LEVEL_SCENARIO
    assert model.field_levels[(target, "SalesforceId")] == LEVEL_CONTACT
    assert {model.field_levels[(config, f)] for f in fields_of(package, config)} == {LEVEL_SCENARIO}
    assert {model.field_levels[(master, f)] for f in fields_of(package, master)} == {LEVEL_CONTACT}
    assert model.activation_field == (config, "ACTIVE")
    assert model.contact_tables == [entry, target, master]
    assert model.scenario_tables == [config]
    assert not any("not joined to the entry" in w for w in model.warnings)
