"""Journey graph: walk a contact through the activities and record what happens.

Spec, "Journey model and coverage", step 1: each activity is a node, each outcome a
branch pointing to the next activity, the start is the activity no other activity
points to. Step 2: decision split outcomes are tried in order, the first true one
wins, the remainder means none matched. Update-contact writes are tracked so a
later split sees the written value.

Spec, "Extensions beyond the pilot":

- Data sources. A Journey Data condition (``Condition.source == SOURCE_JOURNEY``) reads the
  entry row as it was at entry: "later Update contact writes do not change it". Contact Data
  is read live, so it sees the writes ("applies to Contact Data only").
- Row present or absent. For the tables given in ``row_fields`` (table -> its field linked
  to the contact key) a contact may have no row: the row is absent when that field reads
  null. "On an absent row, IsNull on any of its fields is true and every other operator is
  false": every field of an absent row reads null. "An Update contact on that table inserts
  the row: later reads see it present": the linked field then reads GENERATED_KEY, the
  written fields their written value, the other fields null (assumption: a row inserted by
  an Update contact has no value in the fields it does not write).

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
    ACTIVITY_KINDS,
    KIND_DECISION,
    KIND_EMAIL,
    KIND_ENGAGEMENT,
    KIND_RANDOM,
    KIND_UNSUPPORTED,
    KIND_UPDATE,
    KIND_WAIT_ATTRIBUTE,
    KIND_WAIT_DURATION,
    KIND_WAIT_STO,
    GENERATED_KEY,
    SOURCE_JOURNEY,
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
        self._canonical: dict[FieldRef, FieldRef] = {}
        self._types: dict[FieldRef, str] = {}

    def table(self, name: str) -> Optional[Table]:
        return self._tables.get(name.lower())

    def canonical(self, ref: FieldRef) -> FieldRef:
        """``(table, field)`` spelled as in the schema; unknown names are returned unchanged."""
        hit = self._canonical.get(ref)
        if hit is not None:
            return hit
        table = self.table(ref[0])
        if table is None:
            out = ref
        else:
            f = table.field(ref[1])
            out = (table.name, ref[1]) if f is None else (table.name, f.name)
        self._canonical[ref] = out
        return out

    def field_type(self, ref: FieldRef) -> str:
        hit = self._types.get(ref)
        if hit is not None:
            return hit
        table = self.table(ref[0])
        f = table.field(ref[1]) if table is not None else None
        out = f.type if f is not None else "Text"
        self._types[ref] = out
        return out

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
             case_insensitive: bool, snapshot: Optional[ValueLookup] = None) -> "bool | Unknown":
    """Evaluate a split formula. UNKNOWN propagates only when it could still change the answer.

    AND: any False -> False; else any UNKNOWN -> UNKNOWN; else True.
    OR:  any True -> True;   else any UNKNOWN -> UNKNOWN; else False.
    The remainder outcome has no formula and is handled by the caller.
    ``lookup`` answers Contact Data conditions; ``snapshot``, when given, answers Journey Data
    conditions (the entry row as it was at entry), otherwise ``lookup`` answers them too.
    """
    if formula is None:
        return True
    if isinstance(formula, Condition):
        ref = schema.canonical((formula.table, formula.field))
        value = _reader(formula, lookup, snapshot)(ref)
        if isinstance(value, Unknown):
            return UNKNOWN
        return criteria.evaluate_condition(formula, value, schema.field_type(ref), case_insensitive)
    assert isinstance(formula, ConditionGroup)
    saw_unknown = False
    for item in formula.items:
        r = evaluate(item, lookup, schema, case_insensitive, snapshot)
        if isinstance(r, Unknown):
            saw_unknown = True
        elif formula.operator == "AND" and r is False:
            return False
        elif formula.operator == "OR" and r is True:
            return True
    if saw_unknown:
        return UNKNOWN
    return formula.operator == "AND"


def first_unknown_field(formula: Optional[Formula], lookup: ValueLookup, schema: Schema,
                        snapshot: Optional[ValueLookup] = None) -> Optional[FieldRef]:
    """The first field, in document order, whose value is not decided yet."""
    for cond in formula_conditions(formula):
        ref = schema.canonical((cond.table, cond.field))
        if isinstance(_reader(cond, lookup, snapshot)(ref), Unknown):
            return ref
    return None


def _reader(cond: Condition, lookup: ValueLookup, snapshot: Optional[ValueLookup]) -> ValueLookup:
    """Journey Data conditions read the snapshot taken at entry, Contact Data conditions the live value."""
    if snapshot is not None and cond.source == SOURCE_JOURNEY:
        return snapshot
    return lookup


def is_null(value: "Value | Unknown") -> bool:
    """Null as the criteria read it: None or an empty string (criteria.evaluate_condition)."""
    return value is None or value == ""


def row_lookup(lookup: ValueLookup, row_fields: dict[str, FieldRef]) -> ValueLookup:
    """Spec, "Row present or absent": "On an absent row, IsNull on any of its fields is true and every other
    operator is false (confirmed: a contact with no row reads its key as null)".

    ``row_fields`` maps a lower-case table name to its field linked to the contact key (canonical); the
    row is absent when that field reads null, and every field of an absent row then reads null.
    """
    if not row_fields:
        return lookup

    def read(ref: FieldRef):
        linked = row_fields.get(ref[0].lower())
        if linked is None or linked == ref:
            return lookup(ref)
        present = lookup(linked)
        if isinstance(present, Unknown):
            return UNKNOWN
        return None if is_null(present) else lookup(ref)
    return read


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
    inserted: set[str] = field(default_factory=set)           # lower-case tables an update contact wrote into
    visited: set[str] = field(default_factory=set)
    current: Optional[str] = None                             # activity key to execute next
    stop: Optional[str] = None                                # STOP_* once the walk ended
    stop_detail: str = ""                                     # plain words
    pending_field: Optional[FieldRef] = None                  # STOP_UNDETERMINED: the field to decide
    pending_outcomes: list[Outcome] = field(default_factory=list)  # STOP_CHOICE: the outcomes to choose from

    def clone(self) -> "WalkState":
        return WalkState(
            steps=list(self.steps), emails_sent=list(self.emails_sent), writes=list(self.writes),
            waits=list(self.waits), overrides=dict(self.overrides), inserted=set(self.inserted),
            visited=set(self.visited),
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
        return EngagementVerdict(False, "non è stato possibile leggere dall'export il tipo di engagement "
                                        "(open o click)")
    if not ref:
        return EngagementVerdict(False, "lo split non indica l'email a cui si riferisce")
    if ref not in state.emails_sent:
        email = journey.activities.get(ref)
        name = email.email_name if email is not None and email.email_name else ref
        return EngagementVerdict(False, f"l'email di riferimento '{name}' ({ref}) non viene inviata sui percorsi "
                                        f"che raggiungono questo split")
    if activity.engagement_kind == "click":
        email = journey.activities.get(ref)
        asset = emails.get(email.email_asset_id) if email is not None and email.email_asset_id else None
        if asset is None or not asset.has_link:
            name = email.email_name if email is not None and email.email_name else ref
            return EngagementVerdict(False, f"l'email di riferimento '{name}' non contiene link da cliccare")
    return EngagementVerdict(True)


class Walker:
    """Executes activities one at a time against a value lookup.

    ``lookup(ref)`` returns the contact's value for a canonical field ref, as it is at entry, or UNKNOWN.
    For Contact Data, update-contact writes recorded in ``state.overrides`` take precedence over the
    lookup; Journey Data always reads the lookup (the snapshot taken at entry).
    ``row_fields`` lists the tables with the "row present / row absent" variable (table -> its field
    linked to the contact key, as in TableModel.existence_tested); see the module docstring.
    """

    def __init__(self, journey: Journey, schema: Schema, emails: dict[str, EmailAsset],
                 case_insensitive: bool, now: Optional[datetime] = None, date_format: str = "%Y-%m-%d %H:%M",
                 row_fields: Optional[dict[str, FieldRef]] = None):
        self.journey = journey
        self.schema = schema
        self.emails = emails
        self.case_insensitive = case_insensitive
        self.now = now or datetime.now()
        self.date_format = date_format
        self.row_fields: dict[str, FieldRef] = {}
        for ref in (row_fields or {}).values():
            linked = schema.canonical(ref)
            self.row_fields[linked[0].lower()] = linked
        # Optional observer called when a decision split is taken, with the values of the fields
        # its outcomes read at that moment (coverage.py uses it to explain unreachable branches).
        self.on_decision: Optional[Callable[[Activity, dict[FieldRef, Value]], None]] = None

    def start(self) -> WalkState:
        state = WalkState()
        state.current = self.journey.start_key
        if state.current is None:
            state.stop = STOP_ERROR
            state.stop_detail = "il journey non ha un'attività iniziale"
        return state

    def value_of(self, state: WalkState, ref: FieldRef, lookup: ValueLookup) -> "Value | Unknown":
        """Contact Data, read live: the value written by an update contact, else the contact's row."""
        if ref in state.overrides:
            return state.overrides[ref]
        linked = self.row_fields.get(ref[0].lower())
        if linked is not None and ref[0].lower() in state.inserted:
            present = lookup(linked)
            if not isinstance(present, Unknown) and is_null(present):
                # The row was absent and an update contact inserted it.
                return GENERATED_KEY if ref == linked else None
        return row_lookup(lookup, self.row_fields)(ref)

    def snapshot_of(self, ref: FieldRef, lookup: ValueLookup) -> "Value | Unknown":
        """Journey Data: the entry row as it was at entry, whatever the update contacts wrote."""
        return row_lookup(lookup, self.row_fields)(ref)

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
            state.stop_detail = f"un branch porta a un'attività mancante, '{key}'"
            return
        if key in state.visited:
            state.stop = STOP_LOOP
            state.stop_detail = f"l'attività '{key}' è raggiunta due volte sullo stesso percorso"
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
            state.stop_detail = f"l'attività '{key}' è di un tipo non supportato, {activity.raw_type}"
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

        def snapshot(ref: FieldRef):
            return self.snapshot_of(ref, lookup)

        def observe() -> None:
            if self.on_decision is None:
                return
            seen: dict[FieldRef, Value] = {}
            for o in activity.outcomes:
                for cond in formula_conditions(o.formula):
                    ref = self.schema.canonical((cond.table, cond.field))
                    v = _reader(cond, value, snapshot)(ref)
                    if not isinstance(v, Unknown):
                        seen[ref] = v
            self.on_decision(activity, seen)

        # Spec: outcomes are tried in order and the remainder means none matched, so the remainder
        # is evaluated last whatever its position in the export.
        remainder = [o for o in activity.outcomes if o.is_remainder or o.formula is None]
        ordered = [o for o in activity.outcomes if o not in remainder] + remainder
        for outcome in ordered:
            if outcome.is_remainder or outcome.formula is None:
                observe()
                self._take(activity, outcome, state)
                return
            if outcome.unsupported_reason:
                observe()
                state.steps.append(Step(activity.key, None))
                state.stop = STOP_UNSUPPORTED
                state.stop_detail = (f"il branch '{outcome.label or outcome.key}' dello split '{activity.key}' "
                                     f"non è supportato: {outcome.unsupported_reason}")
                return
            try:
                result = evaluate(outcome.formula, value, self.schema, self.case_insensitive, snapshot)
            except criteria.UnsupportedOperator as exc:
                state.steps.append(Step(activity.key, None))
                state.stop = STOP_ERROR
                state.stop_detail = f"lo split '{activity.key}' usa un operatore che il PoC non supporta: {exc}"
                return
            if isinstance(result, Unknown):
                state.stop = STOP_UNDETERMINED
                state.pending_field = first_unknown_field(outcome.formula, value, self.schema, snapshot)
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
        state.stop_detail = f"lo split '{activity.key}' non trova alcun branch corrispondente e non ha un remainder"

    def _update(self, activity: Activity, state: WalkState) -> None:
        """Spec: written values are tracked so a later split reads the updated value (Contact Data only);
        a write into a table with the "row present / row absent" variable inserts the contact's row."""
        for w in activity.writes:
            ref = self.schema.canonical((w.table, w.field))
            value = w.value
            if value == DATETIME_NOW:
                value = self.now.strftime(self.date_format)
            state.overrides[ref] = value
            state.writes.append(Write(ref[0], ref[1], value))
            if ref[0].lower() in self.row_fields:
                state.inserted.add(ref[0].lower())


# ---------------------------------------------------------------------------
# Paths and waits
# ---------------------------------------------------------------------------

def case_paths(case) -> list[list[str]]:
    """Activity keys of every full path of a case (model.Case).

    A statistical case's ``steps`` stop at the random split; each random branch continues it.
    """
    base = [step.activity_key for step in case.steps]
    if case.random is not None and case.random.branches:
        return [base + [step.activity_key for step in branch.steps] for branch in case.random.branches]
    return [base]


# Minutes per wait unit as written in the export (waitUnit). A month and a year count their shortest
# length, 28 and 365 days, because the durations computed here are minimum durations.
WAIT_UNIT_MINUTES = {
    "MINUTE": 1, "HOUR": 60, "DAY": 24 * 60, "WEEK": 7 * 24 * 60, "MONTH": 28 * 24 * 60, "YEAR": 365 * 24 * 60,
}


def fixed_wait_minutes(activity: Activity) -> Optional[int]:
    """The shortest time a wait by duration or a send-time wait holds a contact, in minutes.

    Spec, "Honest outcomes": the window of a manual action and the minimum duration of a case come from
    the waits on the path. A wait by duration lasts its amount (``specifiedTime``, a time of day the wait
    ends at, can only make it longer). A send-time wait may send at once, so it counts 0. A wait by attribute
    counts 0 here: it ends at a date, which is a value of the data (datagen.py). None when the amount or the
    unit cannot be read.
    """
    if activity.kind == KIND_WAIT_DURATION:
        unit = (activity.wait_unit or "").strip().upper()
        per_unit = WAIT_UNIT_MINUTES.get(unit[:-1] if unit.endswith("S") else unit)
        if per_unit is None or activity.wait_amount is None or activity.wait_amount < 0:
            return None
        return activity.wait_amount * per_unit
    return 0


# ---------------------------------------------------------------------------
# Structural helpers
# ---------------------------------------------------------------------------

def is_split(activity: Activity) -> bool:
    """A decision, engagement or random split, including one reported as unsupported (its outcomes are
    still branches of the journey, all of them not covered)."""
    if activity.kind in SPLIT_KINDS:
        return True
    return activity.kind == KIND_UNSUPPORTED and ACTIVITY_KINDS.get(activity.raw_type) in SPLIT_KINDS


def split_branches(journey: Journey) -> list[tuple[Activity, Outcome]]:
    """Every outcome of every decision, engagement and random split, in export order."""
    return [(a, o) for a in journey.activities.values() if is_split(a) for o in a.outcomes]


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
                problems.append(f"il branch '{o.key}' dell'attività '{a.key}' porta a un'attività mancante, "
                                f"'{o.next}'")
    preds = predecessors(journey)
    starts = [k for k, p in preds.items() if not p]
    if len(starts) > 1:
        problems.append("più attività non hanno collegamenti in entrata: " + ", ".join(starts)
                        + f"; il journey inizia da '{journey.start_key}'")
    unreachable = activities_behind(journey, set())
    if unreachable:
        problems.append("attività non raggiungibili dall'inizio: " + ", ".join(sorted(unreachable)))
    return problems
