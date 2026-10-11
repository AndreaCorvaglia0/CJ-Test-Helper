"""Journey graph: walk a contact through the activities and record what happens.

Spec, "Journey model and coverage", step 1: each activity is a node, each outcome a
branch pointing to the next activity, the start is the activity no other activity
points to. Step 2: decision split outcomes are tried in order, the first true one
wins, the remainder means none matched. Update-contact writes are tracked so a
later split sees the written value.

The walker here serves two callers:

- coverage.py explores the journey symbolically: some field values are not yet
  decided, so a formula can evaluate to UNKNOWN and the caller branches on the
  possible values of the field. ``walk`` stops and reports where it got stuck.
- checks.py re-simulates a written contact with every value known, to prove the
  contact takes the path it was created for.

Both use the same code, so the check cannot drift from the generator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from . import criteria
from .model import (
    KIND_DECISION,
    KIND_EMAIL,
    KIND_ENGAGEMENT,
    KIND_RANDOM,
    KIND_UNSUPPORTED,
    KIND_UPDATE,
    KIND_WAIT_ATTRIBUTE,
    KIND_WAIT_DURATION,
    KIND_WAIT_STO,
    Activity,
    BranchRef,
    Condition,
    ConditionGroup,
    EmailAsset,
    FieldRef,
    Formula,
    Journey,
    Outcome,
    Step,
    Table,
    Value,
    Write,
    formula_conditions,
)

SPLIT_KINDS = (KIND_DECISION, KIND_ENGAGEMENT, KIND_RANDOM)
WAIT_KINDS = (KIND_WAIT_DURATION, KIND_WAIT_ATTRIBUTE, KIND_WAIT_STO)

DATETIME_NOW = "{{DateTime.Now}}"


class Unknown:
    """Sentinel for a value that is not decided yet (three-valued logic)."""

    def __repr__(self) -> str:
        return "UNKNOWN"


UNKNOWN = Unknown()


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

class Schema:
    """Case-insensitive access to field types, with canonical (schema) spelling of field refs."""

    def __init__(self, tables: dict[str, Table]):
        self._tables = {name.lower(): t for name, t in tables.items()}

    def table(self, name: str) -> Optional[Table]:
        return self._tables.get(name.lower())

    def canonical(self, ref: FieldRef) -> FieldRef:
        """``(table, field)`` spelled as in the schema; unknown names are returned unchanged."""
        table = self.table(ref[0])
        if table is None:
            return ref
        f = table.field(ref[1])
        if f is None:
            return (table.name, ref[1])
        return (table.name, f.name)

    def field_type(self, ref: FieldRef) -> str:
        table = self.table(ref[0])
        if table is None:
            return "Text"
        f = table.field(ref[1])
        return f.type if f is not None else "Text"

    def is_nullable(self, ref: FieldRef) -> bool:
        table = self.table(ref[0])
        if table is None:
            return True
        f = table.field(ref[1])
        return f.is_nullable if f is not None else True


# ---------------------------------------------------------------------------
# Three-valued formula evaluation
# ---------------------------------------------------------------------------

ValueLookup = Callable[[FieldRef], "Value | Unknown"]


def evaluate(formula: Optional[Formula], lookup: ValueLookup, schema: Schema,
             case_insensitive: bool) -> "bool | Unknown":
    """Evaluate a split formula. UNKNOWN propagates only when it could still change the answer.

    AND: any False -> False; else any UNKNOWN -> UNKNOWN; else True.
    OR:  any True -> True;   else any UNKNOWN -> UNKNOWN; else False.
    The remainder outcome has no formula and is handled by the caller.
    """
    if formula is None:
        return True
    if isinstance(formula, Condition):
        ref = schema.canonical((formula.table, formula.field))
        value = lookup(ref)
        if isinstance(value, Unknown):
            return UNKNOWN
        return criteria.evaluate_condition(formula, value, schema.field_type(ref), case_insensitive)
    assert isinstance(formula, ConditionGroup)
    saw_unknown = False
    for item in formula.items:
        r = evaluate(item, lookup, schema, case_insensitive)
        if isinstance(r, Unknown):
            saw_unknown = True
        elif formula.operator == "AND" and r is False:
            return False
        elif formula.operator == "OR" and r is True:
            return True
    if saw_unknown:
        return UNKNOWN
    return formula.operator == "AND"


def first_unknown_field(formula: Optional[Formula], lookup: ValueLookup, schema: Schema) -> Optional[FieldRef]:
    """The first field, in document order, whose value is not decided yet."""
    for cond in formula_conditions(formula):
        ref = schema.canonical((cond.table, cond.field))
        if isinstance(lookup(ref), Unknown):
            return ref
    return None


# ---------------------------------------------------------------------------
# Walking
# ---------------------------------------------------------------------------

STOP_EXIT = "exit"                    # the journey ended
STOP_UNDETERMINED = "undetermined"    # a decision split needs a value the caller has not decided
STOP_CHOICE = "choice"                # an engagement or random split needs the caller's choice
STOP_UNSUPPORTED = "unsupported"      # an activity type the PoC does not understand
STOP_LOOP = "loop"                    # an activity was reached twice on the same path
STOP_DANGLING = "dangling"            # an outcome points to a missing activity
STOP_ERROR = "error"                  # an operator or value the PoC cannot evaluate


@dataclass
class WalkState:
    """Everything that happened to one contact so far. Copy with ``clone`` before branching."""
    steps: list[Step] = field(default_factory=list)
    emails_sent: list[str] = field(default_factory=list)      # email activity keys
    writes: list[Write] = field(default_factory=list)
    waits: list[str] = field(default_factory=list)            # wait activity keys
    overrides: dict[FieldRef, Value] = field(default_factory=dict)   # update-contact writes, canonical refs
    visited: set[str] = field(default_factory=set)
    current: Optional[str] = None                             # activity key to execute next
    stop: Optional[str] = None                                # STOP_* once the walk ended
    stop_detail: str = ""                                     # plain words
    pending_field: Optional[FieldRef] = None                  # STOP_UNDETERMINED: the field to decide
    pending_outcomes: list[Outcome] = field(default_factory=list)  # STOP_CHOICE: the outcomes to choose from

    def clone(self) -> "WalkState":
        return WalkState(
            steps=list(self.steps), emails_sent=list(self.emails_sent), writes=list(self.writes),
            waits=list(self.waits), overrides=dict(self.overrides), visited=set(self.visited),
            current=self.current, stop=None, stop_detail="", pending_field=None, pending_outcomes=[],
        )

    @property
    def end_activity_key(self) -> Optional[str]:
        return self.steps[-1].activity_key if self.steps else None

    def branches(self) -> list[BranchRef]:
        return [(s.activity_key, s.outcome_key) for s in self.steps if s.outcome_key is not None]


@dataclass
class EngagementVerdict:
    """Whether the Yes branch of an engagement split can be taken on this path, and why not."""
    possible: bool
    reason: str = ""


def engagement_verdict(activity: Activity, state: WalkState, emails: dict[str, EmailAsset],
                       journey: Journey) -> EngagementVerdict:
    """Spec: the Yes branch is reachable only if the path sent the referenced email earlier;
    a click needs a link in that email."""
    ref = activity.engagement_ref
    if activity.engagement_kind not in ("open", "click"):
        return EngagementVerdict(False, "the kind of engagement (open or click) could not be read from the export")
    if not ref:
        return EngagementVerdict(False, "the split does not name the email it refers to")
    if ref not in state.emails_sent:
        email = journey.activities.get(ref)
        name = email.email_name if email is not None and email.email_name else ref
        return EngagementVerdict(False, f"the referenced email '{name}' ({ref}) is not sent on the paths reaching this split")
    if activity.engagement_kind == "click":
        email = journey.activities.get(ref)
        asset = emails.get(email.email_asset_id) if email is not None and email.email_asset_id else None
        if asset is None or not asset.has_link:
            name = email.email_name if email is not None and email.email_name else ref
            return EngagementVerdict(False, f"the referenced email '{name}' has no link to click")
    return EngagementVerdict(True)


class Walker:
    """Executes activities one at a time against a value lookup.

    ``lookup(ref)`` returns the contact's value for a canonical field ref, or UNKNOWN.
    Update-contact writes recorded in ``state.overrides`` take precedence over the lookup.
    """

    def __init__(self, journey: Journey, schema: Schema, emails: dict[str, EmailAsset],
                 case_insensitive: bool, now: Optional[datetime] = None, date_format: str = "%Y-%m-%d %H:%M"):
        self.journey = journey
        self.schema = schema
        self.emails = emails
        self.case_insensitive = case_insensitive
        self.now = now or datetime.now()
        self.date_format = date_format
        # Optional observer called when a decision split is taken, with the values of the fields
        # its outcomes read at that moment (coverage.py uses it to explain unreachable branches).
        self.on_decision: Optional[Callable[[Activity, dict[FieldRef, Value]], None]] = None

    def start(self) -> WalkState:
        state = WalkState()
        state.current = self.journey.start_key
        if state.current is None:
            state.stop = STOP_ERROR
            state.stop_detail = "the journey has no start activity"
        return state

    def value_of(self, state: WalkState, ref: FieldRef, lookup: ValueLookup) -> "Value | Unknown":
        if ref in state.overrides:
            return state.overrides[ref]
        return lookup(ref)

    def run(self, state: WalkState, lookup: ValueLookup,
            choose: Optional[Callable[[Activity, WalkState], Optional[Outcome]]] = None) -> WalkState:
        """Advance until the journey exits or the walk needs the caller (see STOP_*).

        ``choose(activity, state)`` answers engagement and random splits with an outcome;
        returning None means the caller wants to branch itself (STOP_CHOICE).
        """
        while state.stop is None:
            self.step(state, lookup, choose)
        return state

    def step(self, state: WalkState, lookup: ValueLookup,
             choose: Optional[Callable[[Activity, WalkState], Optional[Outcome]]] = None) -> None:
        key = state.current
        if key is None:
            state.stop = STOP_EXIT
            return
        activity = self.journey.activities.get(key)
        if activity is None:
            state.stop = STOP_DANGLING
            state.stop_detail = f"outcome points to a missing activity '{key}'"
            return
        if key in state.visited:
            state.stop = STOP_LOOP
            state.stop_detail = f"activity '{key}' reached twice on the same path"
            return
        state.visited.add(key)

        kind = activity.kind
        if kind == KIND_DECISION:
            self._decision(activity, state, lookup)
        elif kind in (KIND_ENGAGEMENT, KIND_RANDOM):
            outcome = choose(activity, state) if choose is not None else None
            if outcome is None:
                state.stop = STOP_CHOICE
                state.pending_outcomes = list(activity.outcomes)
                return
            self._take(activity, outcome, state)
        elif kind == KIND_UNSUPPORTED:
            state.steps.append(Step(key, None))
            state.stop = STOP_UNSUPPORTED
            state.stop_detail = f"activity '{key}' has the unsupported type {activity.raw_type}"
        else:
            if kind == KIND_EMAIL:
                state.emails_sent.append(key)
            elif kind == KIND_UPDATE:
                self._update(activity, state)
            elif kind in WAIT_KINDS:
                state.waits.append(key)
            self._take(activity, activity.outcomes[0] if activity.outcomes else None, state)

    def take(self, state: WalkState, activity: Activity, outcome: Optional[Outcome]) -> None:
        """Record that ``outcome`` of ``activity`` was taken and move on. Public for callers
        that answer engagement and random splits themselves after STOP_CHOICE."""
        state.stop = None
        state.stop_detail = ""
        state.pending_outcomes = []
        self._take(activity, outcome, state)

    def _take(self, activity: Activity, outcome: Optional[Outcome], state: WalkState) -> None:
        if outcome is None:
            state.steps.append(Step(activity.key, None))
            state.current = None
            state.stop = STOP_EXIT
            return
        state.steps.append(Step(activity.key, outcome.key))
        state.current = outcome.next
        if outcome.next is None:
            state.stop = STOP_EXIT

    def _decision(self, activity: Activity, state: WalkState, lookup: ValueLookup) -> None:
        """Outcomes in order, first true wins; the remainder when none matched."""
        def value(ref: FieldRef):
            return self.value_of(state, ref, lookup)

        def observe() -> None:
            if self.on_decision is None:
                return
            seen: dict[FieldRef, Value] = {}
            for o in activity.outcomes:
                for cond in formula_conditions(o.formula):
                    ref = self.schema.canonical((cond.table, cond.field))
                    v = value(ref)
                    if not isinstance(v, Unknown):
                        seen[ref] = v
            self.on_decision(activity, seen)

        for outcome in activity.outcomes:
            if outcome.is_remainder or outcome.formula is None:
                observe()
                self._take(activity, outcome, state)
                return
            try:
                result = evaluate(outcome.formula, value, self.schema, self.case_insensitive)
            except criteria.UnsupportedOperator as exc:
                state.steps.append(Step(activity.key, None))
                state.stop = STOP_ERROR
                state.stop_detail = f"split '{activity.key}' uses an operator the PoC does not support: {exc}"
                return
            if isinstance(result, Unknown):
                state.stop = STOP_UNDETERMINED
                state.pending_field = first_unknown_field(outcome.formula, value, self.schema)
                state.visited.discard(activity.key)   # the caller will re-run this activity
                return
            if result:
                observe()
                self._take(activity, outcome, state)
                return
        # No remainder outcome and nothing matched: the contact leaves the journey here.
        observe()
        state.steps.append(Step(activity.key, None))
        state.current = None
        state.stop = STOP_EXIT
        state.stop_detail = f"split '{activity.key}' matched no outcome and has no remainder"

    def _update(self, activity: Activity, state: WalkState) -> None:
        """Spec: written values are tracked so a later split reads the updated value."""
        for w in activity.writes:
            ref = self.schema.canonical((w.table, w.field))
            value = w.value
            if value == DATETIME_NOW:
                value = self.now.strftime(self.date_format)
            state.overrides[ref] = value
            state.writes.append(Write(ref[0], ref[1], value))


# ---------------------------------------------------------------------------
# Structural helpers
# ---------------------------------------------------------------------------

def split_branches(journey: Journey) -> list[tuple[Activity, Outcome]]:
    """Every outcome of every decision, engagement and random split, in export order."""
    return [(a, o) for a in journey.activities.values() if a.kind in SPLIT_KINDS for o in a.outcomes]


def predecessors(journey: Journey) -> dict[str, set[str]]:
    preds: dict[str, set[str]] = {k: set() for k in journey.activities}
    for a in journey.activities.values():
        for o in a.outcomes:
            if o.next is not None and o.next in preds:
                preds[o.next].add(a.key)
    return preds


def activities_behind(journey: Journey, blockers: set[str]) -> set[str]:
    """Activities reachable from the start only through one of the ``blockers``."""
    if journey.start_key is None:
        return set(journey.activities)
    reachable: set[str] = set()
    stack = [journey.start_key]
    while stack:
        k = stack.pop()
        if k in reachable or k in blockers or k not in journey.activities:
            continue
        reachable.add(k)
        for o in journey.activities[k].outcomes:
            if o.next is not None:
                stack.append(o.next)
    return {k for k in journey.activities if k not in reachable and k not in blockers}


def structural_problems(journey: Journey) -> list[str]:
    """Plain-words findings about the graph itself: dangling links, several starts, unreachable activities."""
    problems: list[str] = []
    for a in journey.activities.values():
        for o in a.outcomes:
            if o.next is not None and o.next not in journey.activities:
                problems.append(f"outcome '{o.key}' of activity '{a.key}' points to a missing activity '{o.next}'")
    preds = predecessors(journey)
    starts = [k for k, p in preds.items() if not p]
    if len(starts) > 1:
        problems.append("several activities have no incoming link: " + ", ".join(starts)
                        + f"; the journey starts at '{journey.start_key}'")
    unreachable = activities_behind(journey, set())
    if unreachable:
        problems.append("activities not reachable from the start: " + ", ".join(sorted(unreachable)))
    return problems
