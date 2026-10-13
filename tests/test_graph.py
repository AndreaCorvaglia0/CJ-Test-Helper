from datetime import datetime

from cjhelper import graph
from cjhelper.model import KIND_UPDATE, Step
from tests.helpers import (
    AND, OR, cond, decision, email, email_asset, engagement, field, journey, package, table, unsupported, update,
)

MASTER = table("DE_Master", [field("ContactId", pk=True, nullable=False), field("Perm", "Boolean"),
                             field("Flag", "Boolean"), field("Channel", "Text", length=10)], sendable_field="ContactId")
ENTRY = table("DE_Entry", [field("ContactId", pk=True, nullable=False)], sendable_field="ContactId")


def schema():
    return graph.Schema({t.name: t for t in (MASTER, ENTRY)})


def lookup_from(values):
    def lookup(ref):
        return values.get(ref, graph.UNKNOWN)
    return lookup


def test_evaluate_three_valued_logic():
    s = schema()
    f = AND(cond("DE_Master", "Perm", "Is", "true"), OR(cond("DE_Master", "Flag", "Is", "false"), cond("DE_Master", "Flag", "IsNull")))
    assert graph.evaluate(f, lookup_from({("DE_Master", "Perm"): "False"}), s, False) is False  # AND short-circuits
    assert graph.evaluate(f, lookup_from({("DE_Master", "Perm"): "True"}), s, False) is graph.UNKNOWN
    assert graph.evaluate(f, lookup_from({("DE_Master", "Perm"): "True", ("DE_Master", "Flag"): None}), s, False) is True
    assert graph.evaluate(f, lookup_from({("DE_Master", "Perm"): "True", ("DE_Master", "Flag"): "True"}), s, False) is False
    assert graph.first_unknown_field(f, lookup_from({("DE_Master", "Perm"): "True"}), s) == ("DE_Master", "Flag")


def test_canonical_spelling_is_case_insensitive():
    s = schema()
    assert s.canonical(("de_master", "PERM")) == ("DE_Master", "Perm")
    assert s.field_type(("DE_MASTER", "perm")) == "Boolean"


def build_walker(acts, emails=None, case_insensitive=False):
    j = journey(acts)
    pkg = package(j, [MASTER, ENTRY], emails)
    return graph.Walker(j, schema(), pkg.emails, case_insensitive, datetime(2026, 10, 11, 12, 0)), j


def test_decision_first_match_wins_and_remainder():
    acts = [
        decision("SPLIT-1", "s", [("a", "A", "UPD-A", cond("DE_Master", "Channel", "Equal", "X")),
                                  ("b", "B", "UPD-B", cond("DE_Master", "Channel", "Equal", "X"))], remainder_next="UPD-R"),
        update("UPD-A", "A", [], None), update("UPD-B", "B", [], None), update("UPD-R", "R", [], None),
    ]
    w, j = build_walker(acts)
    st = w.run(w.start(), lookup_from({("DE_Master", "Channel"): "X"}))
    assert st.stop == graph.STOP_EXIT
    assert st.steps == [Step("SPLIT-1", "a"), Step("UPD-A", "UPD-A-out")]
    st = w.run(w.start(), lookup_from({("DE_Master", "Channel"): "Y"}))
    assert st.steps[0] == Step("SPLIT-1", "remainder_path")
    assert st.branches() == [("SPLIT-1", "remainder_path"), ("UPD-R", "UPD-R-out")]


def test_undetermined_value_stops_the_walk_and_names_the_field():
    acts = [decision("SPLIT-1", "s", [("a", "A", None, cond("DE_Master", "Channel", "Equal", "X"))], remainder_next=None)]
    w, j = build_walker(acts)
    st = w.run(w.start(), lookup_from({}))
    assert st.stop == graph.STOP_UNDETERMINED
    assert st.pending_field == ("DE_Master", "Channel")
    assert st.current == "SPLIT-1" and "SPLIT-1" not in st.visited


def test_update_write_is_seen_by_a_later_split():
    acts = [
        update("UPD-1", "set", [("DE_Master", "Channel", "X")], "SPLIT-1"),
        decision("SPLIT-1", "s", [("a", "A", None, cond("DE_Master", "Channel", "Equal", "X"))], remainder_next=None),
    ]
    w, j = build_walker(acts)
    st = w.run(w.start(), lookup_from({("DE_Master", "Channel"): "Y"}))
    assert st.steps == [Step("UPD-1", "UPD-1-out"), Step("SPLIT-1", "a")]
    assert st.writes[0].value == "X"


def test_datetime_now_write_uses_generation_time():
    acts = [update("UPD-1", "set", [("DE_Master", "Channel", "{{DateTime.Now}}")], None)]
    w, j = build_walker(acts)
    st = w.run(w.start(), lookup_from({}))
    assert st.overrides[("DE_Master", "Channel")] == "2026-10-11 12:00"


def test_engagement_verdicts():
    emails = {"A1": email_asset("A1", "Demo", has_link=False)}
    acts = [email("EMAIL-1", "Demo", "A1", "ENG-1"),
            engagement("ENG-1", "open", "open", "EMAIL-1", None, None),
            engagement("ENG-2", "click", "click", "EMAIL-1", None, None),
            engagement("ENG-3", "open", "open", "EMAIL-9", None, None)]
    w, j = build_walker(acts, emails)
    st = w.run(w.start(), lookup_from({}))
    assert st.stop == graph.STOP_CHOICE and st.current == "ENG-1"
    assert graph.engagement_verdict(j.activities["ENG-1"], st, emails, j).possible
    v = graph.engagement_verdict(j.activities["ENG-2"], st, emails, j)
    assert not v.possible and "non contiene link" in v.reason
    v = graph.engagement_verdict(j.activities["ENG-3"], st, emails, j)
    assert not v.possible and "non viene inviata" in v.reason
    # taking an outcome after a choice continues the walk
    w.take(st, j.activities["ENG-1"], j.activities["ENG-1"].outcomes[1])
    assert st.stop == graph.STOP_EXIT and st.steps[-1] == Step("ENG-1", "branchResult-2")


def test_loop_and_dangling_are_reported():
    acts = [update("U-1", "a", [], "U-2"), update("U-2", "b", [], "U-1")]
    j = journey(acts)
    j.start_key = "U-1"
    w = graph.Walker(j, schema(), {}, False)
    st = w.run(w.start(), lookup_from({}))
    assert st.stop == graph.STOP_LOOP
    acts = [update("U-1", "a", [], "MISSING")]
    w, j = build_walker(acts)
    st = w.run(w.start(), lookup_from({}))
    assert st.stop == graph.STOP_DANGLING
    assert any("attività mancante" in p for p in graph.structural_problems(j))


def test_unsupported_activity_stops_the_path():
    acts = [unsupported("X-1", "SMSSYNC", "U-1"), update("U-1", "a", [], None)]
    w, j = build_walker(acts)
    st = w.run(w.start(), lookup_from({}))
    assert st.stop == graph.STOP_UNSUPPORTED
    assert graph.activities_behind(j, {"X-1"}) == {"U-1"}


def test_observer_receives_values_of_the_split_fields():
    seen = []
    acts = [decision("SPLIT-1", "s", [("a", "A", None, cond("DE_Master", "Channel", "Equal", "X"))], remainder_next=None)]
    w, j = build_walker(acts)
    w.on_decision = lambda activity, values: seen.append((activity.key, values))
    w.run(w.start(), lookup_from({("DE_Master", "Channel"): "Y"}))
    assert seen == [("SPLIT-1", {("DE_Master", "Channel"): "Y"})]


def test_remainder_is_evaluated_last_whatever_its_position():
    from cjhelper.model import Outcome
    remainder = Outcome(key="remainder_path", label="Remainder", next="UPD-R", formula=None, is_remainder=True)
    yes = Outcome(key="yes", label="yes", next="UPD-Y", formula=cond("DE_Master", "Perm", "Is", "true"))
    split = decision("SPLIT-1", "s", [], remainder_next=None)
    split.outcomes = [remainder, yes]
    acts = [split, update("UPD-Y", "Y", [], None), update("UPD-R", "R", [], None)]
    w, j = build_walker(acts)
    st = w.run(w.start(), lookup_from({("DE_Master", "Perm"): "True"}))
    assert st.steps[0] == Step("SPLIT-1", "yes")
    st = w.run(w.start(), lookup_from({("DE_Master", "Perm"): "False"}))
    assert st.steps[0] == Step("SPLIT-1", "remainder_path")


def test_unsupported_outcome_stops_the_walk_only_when_it_is_reached():
    acts = [decision("SPLIT-1", "s", [("a", "A", "UPD-A", cond("DE_Master", "Perm", "Is", "true")),
                                      ("b", "B", "UPD-B", cond("DE_Master", "Channel", "Between", "x"))], remainder_next="UPD-R"),
            update("UPD-A", "A", [], None), update("UPD-B", "B", [], None), update("UPD-R", "R", [], None)]
    acts[0].outcomes[1].unsupported_reason = "uses the operator 'Between'"
    w, j = build_walker(acts)
    st = w.run(w.start(), lookup_from({("DE_Master", "Perm"): "True"}))
    assert st.steps == [Step("SPLIT-1", "a"), Step("UPD-A", "UPD-A-out")]
    st = w.run(w.start(), lookup_from({("DE_Master", "Perm"): "False"}))
    assert st.stop == graph.STOP_UNSUPPORTED and st.steps == [Step("SPLIT-1", None)]
    assert "Between" in st.stop_detail


def test_between_and_row_present_conditions_are_evaluated():
    """Spec, "Extensions beyond the pilot": Between includes both bounds; the supported attribute comparison
    reads "the contact has a row", true when the linked key field holds a value."""
    from cjhelper.model import Condition

    row_present = Condition("DE_Master", "ContactId", "Equal", None, value_attribute="Event.EV.ContactId")
    acts = [decision("SPLIT-1", "s", [("a", "A", "UPD-A", cond("DE_Master", "Channel", "Between", "b|d")),
                                      ("b", "B", "UPD-B", row_present)], remainder_next="UPD-R"),
            update("UPD-A", "A", [], None), update("UPD-B", "B", [], None), update("UPD-R", "R", [], None)]
    w, j = build_walker(acts)
    st = w.run(w.start(), lookup_from({("DE_Master", "Channel"): "d", ("DE_Master", "ContactId"): "TST_C1"}))
    assert st.steps[0] == Step("SPLIT-1", "a")
    st = w.run(w.start(), lookup_from({("DE_Master", "Channel"): "e", ("DE_Master", "ContactId"): "TST_C1"}))
    assert st.steps[0] == Step("SPLIT-1", "b")
    st = w.run(w.start(), lookup_from({("DE_Master", "Channel"): "a", ("DE_Master", "ContactId"): None}))
    assert st.steps[0] == Step("SPLIT-1", "remainder_path")
    st = w.run(w.start(), lookup_from({("DE_Master", "Channel"): "e"}))
    assert st.stop == graph.STOP_UNDETERMINED and st.pending_field == ("DE_Master", "ContactId")


# ---------------------------------------------------------------------------
# Spec, "Extensions beyond the pilot": Journey Data snapshot, row present or absent, waits
# ---------------------------------------------------------------------------

FORM = table("DE_Form", [field("ContactId", pk=True, nullable=False), field("Consent", "Boolean"),
                         field("Source", "Text", length=20)], sendable_field="ContactId")


def row_walker(acts):
    """A walker that knows DE_Form has the "row present / row absent" variable on ContactId."""
    j = journey(acts)
    tables = {t.name: t for t in (MASTER, ENTRY, FORM)}
    return graph.Walker(j, graph.Schema(tables), {}, False, datetime(2026, 10, 11, 12, 0),
                        row_fields={"DE_Form": ("DE_Form", "ContactId")}), j


def test_journey_data_reads_the_snapshot_taken_at_entry_and_contact_data_the_written_value():
    """Spec: Journey Data "is the snapshot taken at entry: later Update contact writes do not change it";
    "a later split that reads the same field sees the updated value" applies to Contact Data only."""
    from cjhelper.model import SOURCE_JOURNEY, Condition

    journey_tier = Condition("DE_Master", "Channel", "Equal", "Gold", source=SOURCE_JOURNEY)
    acts = [
        update("UPD-1", "set", [("DE_Master", "Channel", "Silver")], "SPLIT-1"),
        decision("SPLIT-1", "journey data", [("a", "A", "SPLIT-2", journey_tier)], remainder_next=None),
        decision("SPLIT-2", "contact data", [("a", "A", None, cond("DE_Master", "Channel", "Equal", "Silver"))],
                 remainder_next=None),
    ]
    w, j = build_walker(acts)
    st = w.run(w.start(), lookup_from({("DE_Master", "Channel"): "Gold"}))
    assert st.steps == [Step("UPD-1", "UPD-1-out"), Step("SPLIT-1", "a"), Step("SPLIT-2", "a")]
    # the snapshot is used by evaluate only when it is given
    snapshot = lookup_from({("DE_Master", "Channel"): "Gold"})
    live = lookup_from({("DE_Master", "Channel"): "Silver"})
    assert graph.evaluate(journey_tier, live, schema(), False, snapshot) is True
    assert graph.evaluate(journey_tier, live, schema(), False) is False


def test_absent_row_reads_null_in_every_field():
    """Spec: "On an absent row, IsNull on any of its fields is true and every other operator is false"."""
    acts = [decision("SPLIT-1", "s", [("null", "N", "UPD-N", cond("DE_Form", "Source", "IsNull")),
                                      ("consent", "C", "UPD-C", cond("DE_Form", "Consent", "Is", "true"))],
                     remainder_next="UPD-R"),
            update("UPD-N", "N", [], None), update("UPD-C", "C", [], None), update("UPD-R", "R", [], None)]
    w, j = row_walker(acts)
    absent = lookup_from({("DE_Form", "ContactId"): None, ("DE_Form", "Source"): "Web", ("DE_Form", "Consent"): "True"})
    assert w.run(w.start(), absent).steps[0] == Step("SPLIT-1", "null")
    present = lookup_from({("DE_Form", "ContactId"): "TST_C1", ("DE_Form", "Source"): "Web",
                           ("DE_Form", "Consent"): "True"})
    assert w.run(w.start(), present).steps[0] == Step("SPLIT-1", "consent")
    # the same masking as a plain lookup, for callers that evaluate formulas themselves
    masked = graph.row_lookup(absent, {"de_form": ("DE_Form", "ContactId")})
    assert masked(("DE_Form", "Consent")) is None and masked(("DE_Master", "Perm")) is graph.UNKNOWN


def test_update_contact_inserts_an_absent_row():
    """Spec: "An Update contact on that table inserts the row: later reads see it present"; the fields it does
    not write read their default value, null when they have none (docs/assumptions.md, rows 20, 29 and 46)."""
    acts = [
        update("UPD-1", "record", [("DE_Form", "Source", "Journey")], "SPLIT-1"),
        decision("SPLIT-1", "still absent?", [("a", "A", None, cond("DE_Form", "ContactId", "IsNull"))],
                 remainder_next="SPLIT-2"),
        decision("SPLIT-2", "consent", [("a", "A", None, cond("DE_Form", "Consent", "IsNull"))], remainder_next=None),
    ]
    w, j = row_walker(acts)
    st = w.run(w.start(), lookup_from({("DE_Form", "ContactId"): None, ("DE_Form", "Consent"): "True"}))
    assert st.steps[1:] == [Step("SPLIT-1", "remainder_path"), Step("SPLIT-2", "a")]
    assert st.inserted == {"de_form"}
    # a row that was there keeps its other values
    st = w.run(w.start(), lookup_from({("DE_Form", "ContactId"): "TST_C1", ("DE_Form", "Consent"): "True"}))
    assert st.steps[1:] == [Step("SPLIT-1", "remainder_path"), Step("SPLIT-2", "remainder_path")]


def test_inserted_row_gives_unwritten_fields_their_default_and_may_fail_on_a_required_field():
    """The spec says only that the insert makes the row present. For the other fields the walker follows the
    assumptions listed for inserts (docs/assumptions.md, rows 19, 20, 29 and 46): an unwritten field reads its
    default value; an insert that leaves a non-nullable field without a default empty may fail, so the path is
    unknown from that Update contact on (spec, "Honest outcomes")."""
    form = table("DE_Form", [field("ContactId", pk=True, nullable=False), field("Welcomed", "Boolean", default="True"),
                             field("Seen", "Date", default="GETDATE()"), field("Source", "Text", length=20)],
                 sendable_field="ContactId")
    acts = [
        update("UPD-1", "record", [("DE_Form", "Source", "Journey")], "SPLIT-1"),
        decision("SPLIT-1", "welcomed?", [("a", "A", "SPLIT-2", cond("DE_Form", "Welcomed", "Is", "true"))],
                 remainder_next=None),
        decision("SPLIT-2", "seen?", [("a", "A", None, cond("DE_Form", "Seen", "IsNotNull"))], remainder_next=None),
    ]
    j = journey(acts)

    def walker(form_table):
        tables = {t.name: t for t in (MASTER, ENTRY, form_table)}
        return graph.Walker(j, graph.Schema(tables), {}, False, datetime(2026, 10, 11, 12, 0),
                            row_fields={"DE_Form": ("DE_Form", "ContactId")})

    absent = lookup_from({("DE_Form", "ContactId"): None, ("DE_Form", "Welcomed"): None, ("DE_Form", "Seen"): None})
    w = walker(form)
    st = w.run(w.start(), absent)
    assert st.stop == graph.STOP_EXIT and st.steps[1:] == [Step("SPLIT-1", "a"), Step("SPLIT-2", "a")]
    assert w.inserted_default(("DE_Form", "Seen")) == "2026-10-11 12:00"
    # A required field the update does not write: the insert may fail, the path is unknown from UPD-1 on.
    strict = table("DE_Form", [field("ContactId", pk=True, nullable=False), field("Welcomed", "Boolean", default="True"),
                               field("Seen", "Date", default="GETDATE()"), field("Source", "Text", length=20),
                               field("Channel", "Text", nullable=False)], sendable_field="ContactId")
    w = walker(strict)
    st = w.run(w.start(), absent)
    assert st.stop == graph.STOP_UNSUPPORTED and st.steps == [Step("UPD-1", None)] and st.current == "UPD-1"
    assert "Channel" in st.stop_detail and "può fallire" in st.stop_detail and not st.writes
    # A row that is there is updated, not inserted: nothing can fail.
    st = w.run(w.start(), lookup_from({("DE_Form", "ContactId"): "TST_C1", ("DE_Form", "Welcomed"): "False",
                                       ("DE_Form", "Seen"): None}))
    assert st.stop == graph.STOP_EXIT and st.steps[1:] == [Step("SPLIT-1", "remainder_path")]


def test_fixed_wait_minutes_and_case_paths():
    from tests.helpers import wait_attr, wait_dur
    from cjhelper.model import KIND_WAIT_STO, Activity, Case, RandomBranch, RandomInfo

    assert graph.fixed_wait_minutes(wait_dur("W-1", 5, "MINUTES", None)) == 5
    assert graph.fixed_wait_minutes(wait_dur("W-2", 2, "DAYS", None)) == 2 * 24 * 60
    assert graph.fixed_wait_minutes(wait_dur("W-3", 1, "Hour", None)) == 60
    assert graph.fixed_wait_minutes(wait_dur("W-4", 1, "MONTHS", None)) == 28 * 24 * 60   # the shortest month
    assert graph.fixed_wait_minutes(wait_dur("W-5", 3, "FORTNIGHTS", None)) is None
    assert graph.fixed_wait_minutes(wait_attr("W-6", "DE_Master", "Channel", None)) == 0
    assert graph.fixed_wait_minutes(Activity("STO-1", "STOWAIT", KIND_WAIT_STO, "", [], wait_amount=24)) == 0
    branch = RandomBranch("b", 50, (Step("U-2", None),), (), (), "U-2")
    case = Case("S01-C01", "S01", 1, {}, [Step("U-1", "o"), Step("R-1", None)], [], [], [], [], "R-1", 50,
                random=RandomInfo("R-1", [branch], 1, 9))
    assert graph.case_paths(case) == [["U-1", "R-1", "U-2"]]
