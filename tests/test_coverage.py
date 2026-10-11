from datetime import datetime

from cjhelper import coverage
from cjhelper.model import (
    LEVEL_CONTACT, LEVEL_SCENARIO, STATUS_COVERED, STATUS_MANUAL, STATUS_NOT_COVERED, Settings,
)
from tests.helpers import (
    AND, OR, cond, decision, email, email_asset, engagement, field, journey, package, random_split, table,
    table_model, unsupported, update, wait_attr,
)

NOW = datetime(2026, 10, 11, 12, 0)

ENTRY = table("DE_Entry", [field("ContactId", pk=True, nullable=False), field("CampaignName", pk=True, nullable=False)],
              sendable_field="ContactId")
MASTER = table("DE_Master", [field("ContactId", pk=True, nullable=False), field("Perm", "Boolean"),
                             field("Dunning", "Boolean"), field("Consent", "Boolean"), field("Email", "EmailAddress")],
               sendable_field="ContactId")
CONFIG = table("DE_Config", [field("CampaignName", pk=True, nullable=False), field("Channel", "Text", nullable=False),
                             field("Channel2", "Text"), field("CG", "Boolean", nullable=False), field("WAIT1", "Date", nullable=False)])


def model_for(tables, scenario=False):
    levels = {"DE_Entry": LEVEL_CONTACT, "DE_Master": LEVEL_CONTACT}
    groups = [("contact", [("DE_Entry", "ContactId"), ("DE_Master", "ContactId")])]
    if scenario:
        levels["DE_Config"] = LEVEL_SCENARIO
        groups.append(("scenario", [("DE_Entry", "CampaignName"), ("DE_Config", "CampaignName")]))
    return table_model("DE_Entry", "ContactId", levels, groups, tables)


def run(acts, tables, scenario=False, settings=None, emails=None, unsupported_keys=()):
    j = journey(acts)
    pkg = package(j, tables, emails, unsupported_keys)
    tm = model_for(tables, scenario)
    return coverage.compute_coverage(pkg, tm, settings or Settings(), NOW)


def status(result, activity, outcome):
    for b in result.branches:
        if b.activity_key == activity and b.outcome_key == outcome:
            return b
    raise AssertionError(f"no branch {activity}/{outcome}")


def test_one_boolean_split_gives_two_cases_in_one_scenario():
    acts = [decision("SPLIT-1", "perm", [("yes", "true", "UPD-Y", cond("DE_Master", "Perm", "Is", "true"))], remainder_next="UPD-N"),
            update("UPD-Y", "Y", [], None), update("UPD-N", "N", [], None)]
    r = run(acts, [ENTRY, MASTER])
    assert r.stats["scenarios"] == 1 and r.stats["cases"] == 2 and r.stats["contacts"] == 6
    assert status(r, "SPLIT-1", "yes").status == STATUS_COVERED
    assert status(r, "SPLIT-1", "remainder_path").status == STATUS_COVERED
    values = sorted(c.contact_values[("DE_Master", "Perm")] for c in r.cases)
    assert values == ["False", "True"]
    assert r.scenario_fields == [] and r.contact_fields == [("DE_Master", "Perm")]
    assert all(c.id.startswith("S01-C") for c in r.cases)


def test_contact_classes_group_combinations_by_predicate_truth():
    f = AND(cond("DE_Master", "Perm", "Is", "true"), OR(cond("DE_Master", "Dunning", "Is", "false"), cond("DE_Master", "Dunning", "IsNull")),
            cond("DE_Master", "Consent", "Is", "true"))
    acts = [decision("SPLIT-1", "phone", [("yes", "ok", None, f)], remainder_next=None)]
    r = run(acts, [ENTRY, MASTER])
    # 3 nullable booleans = 27 combinations, one predicate = 2 classes
    assert len(r.classes) == 2
    assert sum(c.member_count for c in r.classes) == 27
    assert r.stats["cases"] == 2
    # the representative of the true class prefers the condition values and non-null
    true_case = next(c for c in r.cases if c.end_activity_key == "SPLIT-1" and c.steps[-1].outcome_key == "yes")
    assert true_case.contact_values == {("DE_Master", "Perm"): "True", ("DE_Master", "Dunning"): "False", ("DE_Master", "Consent"): "True"}


def test_scenario_level_and_contact_level_fields():
    acts = [
        decision("SPLIT-1", "Channel", [("email", "Email", "SPLIT-2", cond("DE_Config", "Channel", "Equal", "Email")),
                                        ("dm", "DM", "UPD-DM", cond("DE_Config", "Channel", "Equal", "DM"))], remainder_next=None),
        decision("SPLIT-2", "perm", [("ok", "ok", "UPD-E", cond("DE_Master", "Perm", "Is", "true"))], remainder_next="UPD-X"),
        update("UPD-DM", "DM", [], None), update("UPD-E", "E", [], None), update("UPD-X", "X", [], None),
    ]
    r = run(acts, [ENTRY, MASTER, CONFIG], scenario=True)
    assert r.scenario_fields == [("DE_Config", "Channel")]
    assert r.domains[("DE_Config", "Channel")] == ["Email", "DM", "OTHER"]   # not nullable: no null
    assert r.stats["scenarios"] == 3 and r.stats["cases"] == 4
    assert all(b.status == STATUS_COVERED for b in r.branches)
    chans = sorted(s.values[("DE_Config", "Channel")] for s in r.scenarios)
    assert chans == ["DM", "Email", "OTHER"]
    assert [s.run_order for s in r.scenarios] == [1, 2, 3]


def test_repeated_split_on_same_field_marks_contradiction_unreachable():
    acts = [
        decision("SPLIT-1", "c1", [("a", "A", "SPLIT-2", cond("DE_Config", "Channel", "Equal", "A"))], remainder_next="UPD-R"),
        decision("SPLIT-2", "c2", [("b", "B", "UPD-B", cond("DE_Config", "Channel", "Equal", "B"))], remainder_next="UPD-R2"),
        update("UPD-R", "R", [], None), update("UPD-B", "B", [], None), update("UPD-R2", "R2", [], None),
    ]
    r = run(acts, [ENTRY, MASTER, CONFIG], scenario=True)
    b = status(r, "SPLIT-2", "b")
    assert b.status == STATUS_NOT_COVERED
    assert "non è mai vera" in b.reason and "'A'" in b.reason
    assert status(r, "SPLIT-2", "remainder_path").status == STATUS_COVERED
    assert r.stats["scenarios"] == 2


def test_case_mismatch_is_flagged_and_setting_changes_reachability():
    acts = [
        decision("SPLIT-1", "c1", [("a", "Email", "SPLIT-2", cond("DE_Config", "Channel", "Equal", "Email"))], remainder_next=None),
        decision("SPLIT-2", "c2", [("b", "EMAIL", "UPD-B", cond("DE_Config", "Channel", "Equal", "EMAIL"))], remainder_next="UPD-R"),
        update("UPD-B", "B", [], None), update("UPD-R", "R", [], None),
    ]
    r = run(acts, [ENTRY, MASTER, CONFIG], scenario=True)
    assert status(r, "SPLIT-2", "b").status == STATUS_NOT_COVERED
    assert any("'Email' e 'EMAIL'" in w and "perché i confronti di testo distinguono maiuscole e minuscole" in w
               for w in r.warnings)
    r2 = run(acts, [ENTRY, MASTER, CONFIG], scenario=True, settings=Settings(case_insensitive_text=True))
    assert status(r2, "SPLIT-2", "b").status == STATUS_COVERED
    assert status(r2, "SPLIT-2", "remainder_path").status == STATUS_NOT_COVERED
    assert r2.domains[("DE_Config", "Channel")] == ["Email", "OTHER"]


def engagement_journey(email_always_sent: bool, has_link=False):
    emails = {"A1": email_asset("A1", "Demo", has_link=has_link)}
    if email_always_sent:
        first = email("EMAIL-1", "Demo", "A1", "WAIT-1")
    else:
        first = decision("SPLIT-0", "send?", [("s", "send", "EMAIL-1", cond("DE_Master", "Perm", "Is", "true"))], remainder_next="WAIT-1")
    acts = [first,
            email("EMAIL-1", "Demo", "A1", "UPD-Z") if not email_always_sent else wait_attr("WAIT-1", "DE_Config", "WAIT1", "ENG-1"),
            wait_attr("WAIT-1", "DE_Config", "WAIT1", "ENG-1") if not email_always_sent else None,
            engagement("ENG-1", "Open Demo", "open", "EMAIL-1", "ENG-2", "UPD-N"),
            engagement("ENG-2", "Click Demo", "click", "EMAIL-1", "UPD-C", "UPD-NC"),
            update("UPD-N", "N", [], None), update("UPD-C", "C", [], None), update("UPD-NC", "NC", [], None),
            update("UPD-Z", "Z", [], None)]
    acts = [a for a in acts if a is not None]
    return [a for a in acts if a is not None], emails


def test_engagement_split_with_email_sent():
    acts, emails = engagement_journey(True)
    r = run(acts, [ENTRY, MASTER, CONFIG], scenario=True, emails=emails, settings=Settings(real_inbox="t@example.com"))
    assert status(r, "ENG-1", "branchResult-1").status == STATUS_MANUAL
    assert status(r, "ENG-1", "branchResult-2").status == STATUS_COVERED
    click_yes = status(r, "ENG-2", "branchResult-1")
    assert click_yes.status == STATUS_NOT_COVERED and "non contiene link" in click_yes.reason
    assert status(r, "ENG-2", "branchResult-2").status == STATUS_MANUAL
    manual_cases = [c for c in r.cases if c.manual_actions]
    assert len(manual_cases) == 1 and manual_cases[0].manual_actions[0].kind == "open"
    assert manual_cases[0].waits == ["WAIT-1"]
    assert r.scenarios[0].has_manual_action   # manual scenarios come first
    # without an inbox the same cases exist but the branches are not covered
    r2 = run(acts, [ENTRY, MASTER, CONFIG], scenario=True, emails=emails)
    assert status(r2, "ENG-1", "branchResult-1").status == STATUS_NOT_COVERED
    assert "inbox" in status(r2, "ENG-1", "branchResult-1").reason
    assert len([c for c in r2.cases if c.manual_actions]) == 1


def test_engagement_split_with_email_never_sent_on_its_paths():
    acts, emails = engagement_journey(False)
    r = run(acts, [ENTRY, MASTER, CONFIG], scenario=True, emails=emails, settings=Settings(real_inbox="t@example.com"))
    yes = status(r, "ENG-1", "branchResult-1")
    assert yes.status == STATUS_NOT_COVERED and "non viene inviata" in yes.reason and "Demo" in yes.reason
    assert status(r, "ENG-1", "branchResult-2").status == STATUS_COVERED
    assert status(r, "ENG-2", "branchResult-1").status == STATUS_NOT_COVERED
    assert status(r, "ENG-2", "branchResult-2").status == STATUS_NOT_COVERED
    assert "non raggiungibile" in status(r, "ENG-2", "branchResult-2").reason


def test_random_split_gets_a_statistical_case():
    acts = [
        decision("SPLIT-1", "cg", [("cg", "true", "RANDOM-1", cond("DE_Config", "CG", "Is", "true"))], remainder_next="SPLIT-2"),
        random_split("RANDOM-1", [("branchResult-1", 90, "SPLIT-2"), ("branchResult-2", 10, "UPD-CG")]),
        decision("SPLIT-2", "perm", [("ok", "ok", "UPD-Y", cond("DE_Master", "Perm", "Is", "true"))], remainder_next="UPD-N"),
        update("UPD-CG", "CG", [], None), update("UPD-Y", "Y", [], None), update("UPD-N", "N", [], None),
    ]
    r = run(acts, [ENTRY, MASTER, CONFIG], scenario=True)
    stat = [s for s in r.scenarios if s.is_statistical]
    assert len(stat) == 1 and stat[0].values[("DE_Config", "CG")] == "True"
    case = stat[0].cases[0]
    assert case.contact_count == 50 and case.random is not None
    assert case.random.expected_low == 1 and case.random.expected_high == 9
    assert [b.outcome_key for b in case.random.branches] == ["branchResult-1", "branchResult-2"]
    assert case.steps[-1].activity_key == "RANDOM-1"
    assert stat[0].run_order == len(r.scenarios)   # last in the run order
    for key in ("branchResult-1", "branchResult-2"):
        b = status(r, "RANDOM-1", key)
        assert b.status == STATUS_COVERED and b.statistical
    # the branch before the random split is crossed by all 50 contacts: covered, not statistical
    cg = status(r, "SPLIT-1", "cg")
    assert cg.status == STATUS_COVERED and not cg.statistical and cg.covered_by == [stat[0].cases[0].id]
    assert not status(r, "SPLIT-2", "ok").statistical
    det = [s for s in r.scenarios if not s.is_statistical]
    assert len(det) == 1 and det[0].values[("DE_Config", "CG")] == "False"
    assert r.stats["contacts"] == 6 + 50


def test_unsupported_activity_blocks_what_is_behind_it():
    acts = [
        decision("SPLIT-1", "perm", [("ok", "ok", "X-1", cond("DE_Master", "Perm", "Is", "true"))], remainder_next="UPD-N"),
        unsupported("X-1", "SMSSYNC", "SPLIT-2"),
        decision("SPLIT-2", "later", [("a", "A", None, cond("DE_Master", "Consent", "Is", "true"))], remainder_next=None),
        update("UPD-N", "N", [], None),
    ]
    r = run(acts, [ENTRY, MASTER], unsupported_keys=["X-1"])
    assert status(r, "SPLIT-1", "ok").status == STATUS_COVERED
    b = status(r, "SPLIT-2", "a")
    assert b.status == STATUS_NOT_COVERED and "non supportat" in b.reason and "X-1" in b.reason
    assert r.unsupported == ["X-1"]


def test_update_before_split_is_tracked():
    acts = [
        update("UPD-1", "set", [("DE_Master", "Perm", "True")], "SPLIT-1"),
        decision("SPLIT-1", "perm", [("ok", "ok", "UPD-Y", cond("DE_Master", "Perm", "Is", "true"))], remainder_next="UPD-N"),
        update("UPD-Y", "Y", [], None), update("UPD-N", "N", [], None),
    ]
    r = run(acts, [ENTRY, MASTER])
    assert status(r, "SPLIT-1", "ok").status == STATUS_COVERED
    b = status(r, "SPLIT-1", "remainder_path")
    assert b.status == STATUS_NOT_COVERED and "mai" in b.reason.lower() or "sempre" in b.reason
    assert r.stats["cases"] == 1 and r.cases[0].writes[0].value == "True"


def test_same_input_gives_same_result():
    acts = [
        decision("SPLIT-1", "Channel", [("email", "Email", "SPLIT-2", cond("DE_Config", "Channel", "Equal", "Email")),
                                        ("dm", "DM", "UPD-DM", cond("DE_Config", "Channel", "Equal", "DM"))], remainder_next=None),
        decision("SPLIT-2", "perm", [("ok", "ok", "UPD-E", cond("DE_Master", "Perm", "Is", "true"))], remainder_next="UPD-X"),
        update("UPD-DM", "DM", [], None), update("UPD-E", "E", [], None), update("UPD-X", "X", [], None),
    ]
    a = run(acts, [ENTRY, MASTER, CONFIG], scenario=True)
    b = run(acts, [ENTRY, MASTER, CONFIG], scenario=True)
    assert [(s.id, s.values, [(c.id, c.contact_values, c.steps) for c in s.cases]) for s in a.scenarios] == \
           [(s.id, s.values, [(c.id, c.contact_values, c.steps) for c in s.cases]) for s in b.scenarios]


def test_expected_range():
    assert coverage.expected_range(50, 0.10) == (1, 9)
    assert coverage.expected_range(50, 0.50) == (18, 32)
    assert coverage.expected_range(0, 0.1) == (0, 0)


def test_build_domain_rules():
    fmt = "%Y-%m-%d %H:%M"
    c = lambda op, v, t="DE_Master", f="F": cond(t, f, op, v)
    assert coverage.build_domain("Boolean", [c("Is", "false")], True, False, fmt)[0] == ["False", "True", None]
    assert coverage.build_domain("Text", [c("Equal", "A"), c("Equal", "a"), c("Equal", "B")], False, False, fmt)[0] == ["A", "a", "B", "OTHER"]
    assert coverage.build_domain("Text", [c("Equal", "A"), c("Equal", "a"), c("Equal", "B")], True, True, fmt)[0] == ["A", "B", "OTHER", None]
    assert coverage.build_domain("Text", [c("Equal", "OTHER")], False, False, fmt)[0] == ["OTHER", "X"]
    assert coverage.build_domain("Number", [c("Equal", "3")], False, False, fmt)[0] == ["3", "4"]
    assert coverage.build_domain("Date", [c("Equal", "2026-01-01 00:00")], False, False, fmt)[0] == ["2026-01-01 00:00", "2026-01-02 00:00"]
    # the 'other' value fits the field length; a condition value that does not fit is left out with a warning
    domain, other, warnings = coverage.build_domain("Text", [c("Equal", "IT"), c("Equal", "ITA")], True, False, fmt, length=2)
    assert domain == ["IT", "X", None] and other == "X" and any("'ITA'" in w for w in warnings)
    domain, other, _ = coverage.build_domain("Text", [c("Equal", "Y")], False, False, fmt, length=1)
    assert domain == ["Y", "X"]
    # ordering operators get a value on the other side of the bound
    assert coverage.build_domain("Number", [c("LessThan", "50")], False, False, fmt)[0] == ["50", "49", "51"]
    assert coverage.build_domain("Date", [c("GreaterThan", "2026-01-01 00:00")], False, False, fmt)[0] == ["2026-01-01 00:00", "2026-01-02 00:00", "2026-01-03 00:00"]
    # email and phone fields get an 'other' value of their own kind
    assert coverage.build_domain("EmailAddress", [c("IsNull", None)], True, False, fmt)[0] == ["other@example.invalid", None]
    assert coverage.build_domain("Phone", [c("IsNull", None)], True, False, fmt)[0] == ["000000000000", None]
    # a Contains condition: the other value must not contain the text
    domain, other, _ = coverage.build_domain("Text", [c("Contains", "OTH")], False, False, fmt)
    assert other == "X"


def test_unsupported_outcome_keeps_the_earlier_outcomes_coverable():
    acts = [decision("SPLIT-1", "s", [("a", "A", "UPD-A", cond("DE_Master", "Perm", "Is", "true")),
                                      ("b", "B", "UPD-B", cond("DE_Master", "Consent", "Between", "x"))], remainder_next="UPD-R"),
            update("UPD-A", "A", [], None), update("UPD-B", "B", [], None), update("UPD-R", "R", [], None)]
    acts[0].outcomes[1].unsupported_reason = "outcome 'B' uses the operator 'Between', which the PoC does not support"
    r = run(acts, [ENTRY, MASTER])
    assert status(r, "SPLIT-1", "a").status == STATUS_COVERED
    b = status(r, "SPLIT-1", "b")
    assert b.status == STATUS_NOT_COVERED and b.reason.startswith("branch non supportato") and "Between" in b.reason
    rem = status(r, "SPLIT-1", "remainder_path")
    assert rem.status == STATUS_NOT_COVERED and rem.reason.startswith("a valle di un elemento non supportato")
    assert "SPLIT-1/b" in r.unsupported
    assert r.stats["cases"] == 1   # only the A case: the path stopped at the unsupported outcome covers nothing


def test_branches_behind_an_unsupported_activity_name_it():
    acts = [
        decision("SPLIT-1", "perm", [("ok", "ok", "X-1", cond("DE_Master", "Perm", "Is", "true"))], remainder_next="X-2"),
        unsupported("X-1", "SMSSYNC", "SPLIT-2"), unsupported("X-2", "WHATSAPP", "SPLIT-3"),
        decision("SPLIT-2", "later", [("a", "A", None, cond("DE_Master", "Consent", "Is", "true"))], remainder_next=None),
        decision("SPLIT-3", "later2", [("a", "A", None, cond("DE_Master", "Consent", "Is", "true"))], remainder_next=None),
    ]
    r = run(acts, [ENTRY, MASTER], unsupported_keys=["X-1", "X-2"])
    b2 = status(r, "SPLIT-2", "a")
    assert b2.status == STATUS_NOT_COVERED and b2.reason.startswith("a valle di un elemento non supportato") and "X-1" in b2.reason and "X-2" not in b2.reason
    b3 = status(r, "SPLIT-3", "a")
    assert "X-2" in b3.reason and "X-1" not in b3.reason


def test_manual_action_cannot_be_done_when_a_split_fixes_the_address():
    """Data rule 2 (split value) wins over rule 4 (real inbox): the open contacts must carry the
    address the split requires, which the tester does not own, so the Yes branch is not covered."""
    emails = {"A1": email_asset("A1", "Demo")}
    acts = [decision("SPLIT-1", "vip?", [("vip", "vip", "EMAIL-1", cond("DE_Master", "Email", "Equal", "vip@example.com"))], remainder_next="UPD-R"),
            email("EMAIL-1", "Demo", "A1", "WAIT-1"), wait_attr("WAIT-1", "DE_Config", "WAIT1", "ENG-1"),
            engagement("ENG-1", "Open Demo", "open", "EMAIL-1", "UPD-Y", "UPD-N"),
            update("UPD-Y", "Y", [], None), update("UPD-N", "N", [], None), update("UPD-R", "R", [], None)]
    r = run(acts, [ENTRY, MASTER, CONFIG], scenario=True, emails=emails, settings=Settings(real_inbox="t@example.com"))
    yes = status(r, "ENG-1", "branchResult-1")
    assert yes.status == STATUS_NOT_COVERED and "vip@example.com" in yes.reason and yes.covered_by
    assert status(r, "ENG-1", "branchResult-2").status == STATUS_COVERED
    blocked = [c for c in r.cases if c.manual_actions]
    assert len(blocked) == 1 and blocked[0].inbox_blocked_reason and "vip@example.com" in blocked[0].inbox_blocked_reason


def test_engagement_split_of_unknown_kind_reports_both_branches_not_covered():
    """Triage RB-5: a statsTypeId that is neither an open nor a click measures something unknown, so
    neither branch can be claimed, as the loader warning says; the split before it stays covered."""
    emails = {"A1": email_asset("A1", "Demo", has_link=True)}
    acts = [decision("SPLIT-1", "perm", [("ok", "ok", "EMAIL-1", cond("DE_Master", "Perm", "Is", "true"))], remainder_next="UPD-R"),
            email("EMAIL-1", "Demo", "A1", "ENG-1"),
            engagement("ENG-1", "Bounce Demo", None, "EMAIL-1", "UPD-Y", "UPD-N"),
            update("UPD-Y", "Y", [], None), update("UPD-N", "N", [], None), update("UPD-R", "R", [], None)]
    r = run(acts, [ENTRY, MASTER], emails=emails, settings=Settings(real_inbox="t@example.com"))
    for key in ("branchResult-1", "branchResult-2"):
        b = status(r, "ENG-1", key)
        assert b.status == STATUS_NOT_COVERED and b.covered_by == []
        assert b.reason.startswith("branch non supportato") and "né un open né un click" in b.reason
    assert status(r, "SPLIT-1", "ok").status == STATUS_COVERED
    assert status(r, "SPLIT-1", "remainder_path").status == STATUS_COVERED
    assert r.stats["not_covered"] == 2
