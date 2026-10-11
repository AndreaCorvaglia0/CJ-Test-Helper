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
    assert not v.possible and "no link" in v.reason
    v = graph.engagement_verdict(j.activities["ENG-3"], st, emails, j)
    assert not v.possible and "not sent" in v.reason
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
    assert any("missing activity" in p for p in graph.structural_problems(j))


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
