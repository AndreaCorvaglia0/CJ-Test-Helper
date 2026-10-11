"""Coverage: which field values send a contact down each branch, and the smallest set of
scenarios and cases that crosses every reachable branch.

Spec, "Journey model and coverage", steps 3 to 6:

3. Fields are contact-level or scenario-level (tables.py decides; here we read the result).
4. Values are enumerated, not paths. Each field read by a split takes the values named in
   conditions, one extra "other" value, and null when the schema allows it. Contact-level
   combinations are grouped into classes that satisfy the same conditions. The journey is
   simulated for each scenario-level combination and each class.
5. A greedy set cover with a fixed random seed picks the fewest scenarios crossing every
   reachable branch.
6. Paths sharing scenario-level values form a scenario; inside it, each distinct combination
   of contact-level values and manual actions is a case of 3 contacts.

Special activities (spec table): engagement splits get both branches, the Yes branch only
when the referenced email was sent earlier on the path and (for a click) the email has a
link; random splits cannot be forced, the cover prefers paths avoiding them, and branches
reachable only through them get one statistical case of 50 contacts.

The simulation itself lives in graph.py so that checks.py re-simulates with the same code.
"""

from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from . import graph
from .model import (
    KIND_DECISION,
    KIND_ENGAGEMENT,
    KIND_RANDOM,
    KIND_UNSUPPORTED,
    KIND_WAIT_ATTRIBUTE,
    LEVEL_CONTACT,
    LEVEL_SCENARIO,
    STATUS_COVERED,
    STATUS_MANUAL,
    STATUS_NOT_COVERED,
    Activity,
    BranchRef,
    BranchStatus,
    Case,
    Condition,
    ContactClass,
    CoverageResult,
    FieldRef,
    Formula,
    ManualAction,
    Outcome,
    Package,
    RandomBranch,
    RandomInfo,
    Scenario,
    Settings,
    Step,
    TableModel,
    Value,
    Write,
    formula_conditions,
    formula_text,
)

# Safety limits so a strange export cannot hang the generator. Both are reported when hit.
MAX_CONTACT_COMBINATIONS = 200_000
MAX_SCENARIO_COMBINATIONS = 2_000_000

OTHER_TEXT_CANDIDATES = ("OTHER", "OTHER_2", "OTHER_3", "OTHER_4")


# ---------------------------------------------------------------------------
# Domains
# ---------------------------------------------------------------------------

def _normalise_boolean(value: Value) -> Value:
    if value is None:
        return None
    low = value.strip().lower()
    if low in ("true", "1"):
        return "True"
    if low in ("false", "0"):
        return "False"
    return value


def _other_text(values: list[Value]) -> str:
    taken = {v.lower() for v in values if v is not None}
    for candidate in OTHER_TEXT_CANDIDATES:
        if candidate.lower() not in taken:
            return candidate
    n = 5
    while f"OTHER_{n}".lower() in taken:
        n += 1
    return f"OTHER_{n}"


def _other_date(values: list[Value], date_format: str) -> str:
    for v in values:
        if v is None:
            continue
        for fmt in (date_format, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
            try:
                return (datetime.strptime(v, fmt) + timedelta(days=1)).strftime(date_format)
            except ValueError:
                continue
    return datetime(2000, 1, 1).strftime(date_format)


def _other_number(values: list[Value]) -> str:
    nums = []
    for v in values:
        try:
            nums.append(float(v))
        except (TypeError, ValueError):
            continue
    if not nums:
        return "0"
    top = max(nums) + 1
    return str(int(top)) if top == int(top) else str(top)


def build_domain(field_type: str, condition_values: list[Value], nullable: bool,
                 case_insensitive: bool, date_format: str) -> list[Value]:
    """Spec step 4: the values named in conditions, one extra 'other' value, null when allowed.

    Booleans always take both True and False (the 'other' of one is the other).
    Text values keep the letter case written in the condition (data rule 2). When text
    comparisons ignore case, spellings that differ only by case are one value.
    """
    values: list[Value] = []
    if field_type == "Boolean":
        for v in condition_values:
            v = _normalise_boolean(v)
            if v in ("True", "False") and v not in values:
                values.append(v)
        for v in ("True", "False"):
            if v not in values:
                values.append(v)
    else:
        seen: set[str] = set()
        for v in condition_values:
            if v is None:
                continue
            key = v.lower() if (case_insensitive and field_type not in ("Date", "Number", "Decimal")) else v
            if key not in seen:
                seen.add(key)
                values.append(v)
        if field_type == "Date":
            values.append(_other_date(values, date_format))
        elif field_type in ("Number", "Decimal"):
            values.append(_other_number(values))
        else:
            values.append(_other_text(values))
    if nullable:
        values.append(None)
    return values


# ---------------------------------------------------------------------------
# Exploration results
# ---------------------------------------------------------------------------

@dataclass
class Leaf:
    """One complete simulated path for one contact class and one partial scenario assignment."""
    id: int
    class_id: int
    assigned: dict[FieldRef, Value]            # scenario-level values the path depended on
    manual: tuple[ManualAction, ...]
    randoms: tuple[tuple[str, str], ...]       # (random split key, outcome key) choices made
    steps: list[Step]
    emails_sent: list[str]
    writes: list[Write]
    waits: list[str]
    stop: str
    stop_detail: str
    mask: int = 0                              # bitmask over split branches crossed

    @property
    def deterministic(self) -> bool:
        return not self.randoms

    @property
    def end_activity_key(self) -> Optional[str]:
        return self.steps[-1].activity_key if self.steps else None


@dataclass
class BranchNode:
    field: FieldRef
    children: dict[Value, "Node"]


@dataclass
class ChoiceNode:
    children: list["Node"]


@dataclass
class LeafNode:
    leaf: Leaf


Node = BranchNode | ChoiceNode | LeafNode


def lookup_leaves(node: Node, assignment: dict[FieldRef, Value]) -> list[Leaf]:
    if isinstance(node, LeafNode):
        return [node.leaf]
    if isinstance(node, BranchNode):
        child = node.children.get(assignment.get(node.field))
        return lookup_leaves(child, assignment) if child is not None else []
    out: list[Leaf] = []
    for child in node.children:
        out.extend(lookup_leaves(child, assignment))
    return out


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------

class CoverageEngine:
    def __init__(self, package: Package, table_model: TableModel, settings: Settings,
                 generation_time: Optional[datetime] = None):
        self.package = package
        self.journey = package.journey
        self.table_model = table_model
        self.settings = settings
        self.now = generation_time or settings.generation_time or datetime.now()
        self.schema = graph.Schema(package.tables)
        self.warnings: list[str] = []
        self.walker = graph.Walker(self.journey, self.schema, package.emails,
                                   settings.case_insensitive_text, self.now, settings.date_format)
        self.walker.on_decision = self._observe_decision
        # filled by run()
        self.fields: list[FieldRef] = []
        self.conditions_by_field: dict[FieldRef, list[Condition]] = {}
        self.levels: dict[FieldRef, str] = {}
        self.domains: dict[FieldRef, list[Value]] = {}
        self.contact_fields: list[FieldRef] = []
        self.scenario_fields: list[FieldRef] = []
        self.classes: list[ContactClass] = []
        self.leaves: list[Leaf] = []
        self.trees: dict[int, Node] = {}
        self.branch_index: dict[BranchRef, int] = {}
        self.branch_list: list[tuple[Activity, Outcome]] = []
        self.engagement_blocked: dict[BranchRef, str] = {}
        self.reached_values: dict[str, dict[FieldRef, set[Value]]] = {}
        self.reached_activities: set[str] = set()

    # -- step 3 and 4: fields, levels, domains ------------------------------------------

    def collect_fields(self) -> None:
        """Every field read by a decision split, in order of first appearance."""
        for activity in self.journey.activities.values():
            if activity.kind != KIND_DECISION:
                continue
            for outcome in activity.outcomes:
                for cond in formula_conditions(outcome.formula):
                    ref = self.schema.canonical((cond.table, cond.field))
                    if ref not in self.conditions_by_field:
                        self.fields.append(ref)
                        self.conditions_by_field[ref] = []
                    self.conditions_by_field[ref].append(cond)
        for ref in self.fields:
            level = self.table_model.field_levels.get(ref)
            if level is None:
                level = LEVEL_CONTACT
                self.warnings.append(
                    f"field {ref[0]}.{ref[1]} is read by a split but its table is not linked to the entry; "
                    "treated as a contact-level field (assumption)")
            self.levels[ref] = level
            if self.schema.table(ref[0]) is None or self.schema.table(ref[0]).field(ref[1]) is None:
                self.warnings.append(f"field {ref[0]}.{ref[1]} is read by a split but is not in the export's schemas; treated as nullable text")
        self.contact_fields = [f for f in self.fields if self.levels[f] == LEVEL_CONTACT]
        self.scenario_fields = [f for f in self.fields if self.levels[f] == LEVEL_SCENARIO]

    def build_domains(self) -> None:
        for ref in self.fields:
            conds = self.conditions_by_field[ref]
            values = [c.value for c in conds if c.value is not None]
            ftype = self.schema.field_type(ref)
            self.domains[ref] = build_domain(ftype, values, self.schema.is_nullable(ref),
                                             self.settings.case_insensitive_text, self.settings.date_format)
            self._flag_case_variants(ref, ftype, values)

    def _flag_case_variants(self, ref: FieldRef, ftype: str, values: list[str]) -> None:
        """Spec, report: 'the same value written in two letter cases (Email and EMAIL in the pilot)'."""
        if ftype in ("Boolean", "Date", "Number", "Decimal"):
            return
        by_lower: dict[str, list[str]] = {}
        for v in values:
            by_lower.setdefault(v.lower(), [])
            if v not in by_lower[v.lower()]:
                by_lower[v.lower()].append(v)
        for spellings in by_lower.values():
            if len(spellings) > 1:
                shown = " and ".join(repr(s) for s in spellings)
                if self.settings.case_insensitive_text:
                    self.warnings.append(
                        f"suspicious pattern: {ref[0]}.{ref[1]} is compared with {shown}; "
                        "treated as the same value because text comparisons ignore letter case")
                else:
                    self.warnings.append(
                        f"suspicious pattern: {ref[0]}.{ref[1]} is compared with {shown}; "
                        "they are different values because text comparisons are case-sensitive (setting)")

    # -- contact classes ----------------------------------------------------------------

    def contact_predicates(self) -> list[Formula]:
        """A pure contact-level outcome formula is one predicate; of a mixed formula, each
        contact-level condition is one predicate. Classes are the distinct truth vectors."""
        preds: list[Formula] = []
        seen: set[str] = set()

        def add(f: Formula) -> None:
            key = formula_text(f)
            if key not in seen:
                seen.add(key)
                preds.append(f)

        for activity in self.journey.activities.values():
            if activity.kind != KIND_DECISION:
                continue
            for outcome in activity.outcomes:
                if outcome.formula is None:
                    continue
                conds = formula_conditions(outcome.formula)
                levels = {self.levels[self.schema.canonical((c.table, c.field))] for c in conds}
                if levels == {LEVEL_CONTACT}:
                    add(outcome.formula)
                elif LEVEL_CONTACT in levels:
                    for c in conds:
                        if self.levels[self.schema.canonical((c.table, c.field))] == LEVEL_CONTACT:
                            add(c)
        return preds

    def build_classes(self) -> None:
        preds = self.contact_predicates()
        domains = [self.domains[f] for f in self.contact_fields]
        total = math.prod(len(d) for d in domains) if domains else 1
        combos = itertools.product(*domains)
        if total > MAX_CONTACT_COMBINATIONS:
            self.warnings.append(
                f"{total} contact-level value combinations; only the first {MAX_CONTACT_COMBINATIONS} were examined")
            combos = itertools.islice(combos, MAX_CONTACT_COMBINATIONS)
        by_truth: dict[tuple[bool, ...], ContactClass] = {}
        for combo in combos:
            values = dict(zip(self.contact_fields, combo))

            def lookup(ref: FieldRef, _values=values):
                return _values.get(ref, graph.UNKNOWN)

            truth = tuple(bool(graph.evaluate(p, lookup, self.schema, self.settings.case_insensitive_text))
                          for p in preds)
            cls = by_truth.get(truth)
            if cls is None:
                by_truth[truth] = ContactClass(id=len(by_truth) + 1, values=values, predicate_truth=truth, member_count=1)
            else:
                cls.member_count += 1
        self.classes = list(by_truth.values())

    # -- symbolic exploration -----------------------------------------------------------

    def _observe_decision(self, activity: Activity, values: dict[FieldRef, Value]) -> None:
        store = self.reached_values.setdefault(activity.key, {})
        for ref, v in values.items():
            store.setdefault(ref, set()).add(v)

    def explore(self) -> None:
        """One decision tree per contact class: branch on scenario-level values when a split
        needs one, on both outcomes of engagement and random splits, and stop at a leaf."""
        for cls in self.classes:
            state = self.walker.start()
            self.trees[cls.id] = self._explore_from(cls, state, {}, (), ())

    def _lookup(self, cls: ContactClass, assigned: dict[FieldRef, Value]):
        def lookup(ref: FieldRef):
            if ref in cls.values:
                return cls.values[ref]
            if ref in assigned:
                return assigned[ref]
            if ref in self.domains:
                return graph.UNKNOWN
            # A field no split reads (only reachable through a tracked write): unknown.
            return graph.UNKNOWN
        return lookup

    def _explore_from(self, cls: ContactClass, state: graph.WalkState, assigned: dict[FieldRef, Value],
                      manual: tuple[ManualAction, ...], randoms: tuple[tuple[str, str], ...]) -> Node:
        state = self.walker.run(state, self._lookup(cls, assigned), choose=None)
        self.reached_activities.update(s.activity_key for s in state.steps)
        if state.current is not None:
            self.reached_activities.add(state.current)

        if state.stop == graph.STOP_UNDETERMINED:
            ref = state.pending_field
            if ref is None or ref not in self.domains:
                self.warnings.append(f"split '{state.current}' reads a field the generator cannot enumerate; path stopped there")
                state.stop = graph.STOP_ERROR
                state.stop_detail = f"split '{state.current}' reads a field the generator cannot enumerate"
                return LeafNode(self._leaf(cls, state, assigned, manual, randoms))
            children: dict[Value, Node] = {}
            for value in self.domains[ref]:
                child_state = state.clone()
                child_assigned = dict(assigned)
                child_assigned[ref] = value
                children[value] = self._explore_from(cls, child_state, child_assigned, manual, randoms)
            return BranchNode(ref, children)

        if state.stop == graph.STOP_CHOICE:
            activity = self.journey.activities[state.current]
            children: list[Node] = []
            if activity.kind == KIND_ENGAGEMENT:
                verdict = graph.engagement_verdict(activity, state, self.package.emails, self.journey)
                for outcome in activity.outcomes:
                    if outcome.when is True and not verdict.possible:
                        self.engagement_blocked.setdefault((activity.key, outcome.key), verdict.reason)
                        continue
                    child_state = state.clone()
                    self.walker.take(child_state, activity, outcome)
                    child_manual = manual
                    if outcome.when is True:
                        email = self.journey.activities.get(activity.engagement_ref or "")
                        child_manual = manual + (ManualAction(
                            activity_key=activity.key, kind=activity.engagement_kind or "",
                            email_activity_key=activity.engagement_ref or "",
                            email_name=(email.email_name if email is not None and email.email_name else activity.engagement_ref or "")),)
                    children.append(self._explore_from(cls, child_state, assigned, child_manual, randoms))
            else:  # random split
                for outcome in activity.outcomes:
                    child_state = state.clone()
                    self.walker.take(child_state, activity, outcome)
                    children.append(self._explore_from(cls, child_state, assigned, manual, randoms + ((activity.key, outcome.key),)))
            return ChoiceNode(children)

        return LeafNode(self._leaf(cls, state, assigned, manual, randoms))

    def _leaf(self, cls: ContactClass, state: graph.WalkState, assigned: dict[FieldRef, Value],
              manual: tuple[ManualAction, ...], randoms: tuple[tuple[str, str], ...]) -> Leaf:
        if state.stop in (graph.STOP_LOOP, graph.STOP_DANGLING, graph.STOP_ERROR):
            self.warnings.append(f"path stopped: {state.stop_detail}")
        leaf = Leaf(id=len(self.leaves), class_id=cls.id, assigned=dict(assigned), manual=manual, randoms=randoms,
                    steps=list(state.steps), emails_sent=list(state.emails_sent), writes=list(state.writes),
                    waits=list(state.waits), stop=state.stop or graph.STOP_EXIT, stop_detail=state.stop_detail)
        mask = 0
        for ref in state.branches():
            idx = self.branch_index.get(ref)
            if idx is not None:
                mask |= 1 << idx
        leaf.mask = mask
        self.leaves.append(leaf)
        return leaf

    # -- step 4 continued: every scenario-level combination ------------------------------

    def enumerate_scenarios(self) -> dict[tuple[int, ...], dict[FieldRef, Value]]:
        """Signature (the leaves a full scenario produces across all classes) -> first scenario with it."""
        domains = [self.domains[f] for f in self.scenario_fields]
        total = math.prod(len(d) for d in domains) if domains else 1
        signatures: dict[tuple[int, ...], dict[FieldRef, Value]] = {}
        if total > MAX_SCENARIO_COMBINATIONS:
            self.warnings.append(
                f"{total} scenario-level value combinations is more than the generator enumerates "
                f"({MAX_SCENARIO_COMBINATIONS}); scenarios were built from the paths' own values instead")
            for leaf in self.leaves:
                assignment = {f: d[0] for f, d in zip(self.scenario_fields, domains)}
                assignment.update(leaf.assigned)
                sig = self._signature(assignment)
                signatures.setdefault(sig, assignment)
            return signatures
        for combo in itertools.product(*domains):
            assignment = dict(zip(self.scenario_fields, combo))
            sig = self._signature(assignment)
            if sig not in signatures:
                signatures[sig] = assignment
        return signatures

    def _signature(self, assignment: dict[FieldRef, Value]) -> tuple[int, ...]:
        ids: list[int] = []
        for cls in self.classes:
            ids.extend(leaf.id for leaf in lookup_leaves(self.trees[cls.id], assignment))
        return tuple(sorted(ids))

    # -- step 5: the cover --------------------------------------------------------------

    def choose_cover(self, signatures: dict[tuple[int, ...], dict[FieldRef, Value]]):
        """Greedy set cover over scenarios, then over the cases inside the chosen scenarios.

        Only deterministic leaves (no random split on the path) count here: the cover prefers
        paths that avoid random splits. Ties are broken by a fixed random seed."""
        rng = random.Random(self.settings.seed)
        universe = 0
        for leaf in self.leaves:
            if leaf.deterministic:
                universe |= leaf.mask
        candidates = []
        for sig, assignment in signatures.items():
            mask = 0
            for leaf_id in sig:
                leaf = self.leaves[leaf_id]
                if leaf.deterministic:
                    mask |= leaf.mask
            if mask:
                candidates.append((sig, assignment, mask))
        rng.shuffle(candidates)
        covered = 0
        chosen: list[tuple[tuple[int, ...], dict[FieldRef, Value]]] = []
        while covered != universe:
            best = None
            best_gain = 0
            for cand in candidates:
                gain = bin(cand[2] & ~covered).count("1")
                if gain > best_gain:
                    best, best_gain = cand, gain
            if best is None:
                break
            chosen.append((best[0], best[1]))
            covered |= best[2]
            candidates.remove(best)

        # Cases: the fewest leaves of the chosen scenarios that still cover everything.
        case_candidates: list[tuple[int, Leaf]] = []
        for i, (sig, _) in enumerate(chosen):
            for leaf_id in sig:
                leaf = self.leaves[leaf_id]
                if leaf.deterministic and leaf.mask:
                    case_candidates.append((i, leaf))
        covered = 0
        selected: dict[int, list[Leaf]] = {}
        while covered != universe:
            best = None
            best_key = None
            for cand in case_candidates:
                gain = bin(cand[1].mask & ~covered).count("1")
                if gain == 0:
                    continue
                key = (-gain, len(cand[1].manual), cand[0], cand[1].class_id, cand[1].id)
                if best_key is None or key < best_key:
                    best, best_key = cand, key
            if best is None:
                break
            selected.setdefault(best[0], []).append(best[1])
            covered |= best[1].mask
            case_candidates.remove(best)
        scenarios = [(chosen[i][1], leaves) for i, leaves in sorted(selected.items())]
        return scenarios, universe

    # -- random splits: statistical cases -----------------------------------------------

    def choose_statistical(self, signatures: dict[tuple[int, ...], dict[FieldRef, Value]], det_universe: int):
        """Branches crossed only on paths through a random split get a statistical case."""
        random_universe = 0
        for leaf in self.leaves:
            if not leaf.deterministic:
                random_universe |= leaf.mask
        random_universe &= ~det_universe
        if not random_universe:
            return []
        # Group random leaves by (scenario signature, class); engagement Yes choices are not
        # asked of the tester in a statistical case, so leaves with manual actions are left out.
        groups: list[tuple[dict[FieldRef, Value], int, list[Leaf], int]] = []
        for sig, assignment in signatures.items():
            by_class: dict[int, list[Leaf]] = {}
            for leaf_id in sig:
                leaf = self.leaves[leaf_id]
                if not leaf.deterministic and not leaf.manual:
                    by_class.setdefault(leaf.class_id, []).append(leaf)
            for class_id, leaves in by_class.items():
                mask = 0
                for leaf in leaves:
                    mask |= leaf.mask
                groups.append((assignment, class_id, leaves, mask & random_universe))
        rng = random.Random(self.settings.seed + 1)
        rng.shuffle(groups)
        covered = 0
        chosen = []
        while covered != random_universe:
            best = None
            best_key = None
            for g in groups:
                gain = bin(g[3] & ~covered).count("1")
                if gain == 0:
                    continue
                key = (-gain, len(g[2]), g[1])
                if best_key is None or key < best_key:
                    best, best_key = g, key
            if best is None:
                break
            chosen.append(best)
            covered |= best[3]
            groups.remove(best)
        return chosen

    def _random_info(self, leaves: list[Leaf]) -> tuple[list[Step], RandomInfo]:
        """Cut the leaves at their first random split: the common prefix and one branch per outcome."""
        first_key = leaves[0].randoms[0][0]
        activity = self.journey.activities[first_key]
        prefix: list[Step] = []
        for step in leaves[0].steps:
            if step.activity_key == first_key:
                break
            prefix.append(step)
        prefix.append(Step(first_key, None))
        branches: list[RandomBranch] = []
        seen_outcomes: set[str] = set()
        for outcome in activity.outcomes:
            for leaf in leaves:
                if leaf.randoms[0] != (first_key, outcome.key) or outcome.key in seen_outcomes:
                    continue
                if len(leaf.randoms) > 1:
                    self.warnings.append(
                        f"random split '{first_key}' leads to another random split; only the first continuation is described")
                idx = next(i for i, s in enumerate(leaf.steps) if s.activity_key == first_key)
                branches.append(RandomBranch(
                    outcome_key=outcome.key, percentage=outcome.percentage or 0,
                    steps=tuple(leaf.steps[idx + 1:]), emails_sent=tuple(leaf.emails_sent),
                    writes=tuple(leaf.writes), end_activity_key=leaf.end_activity_key))
                seen_outcomes.add(outcome.key)
        n = self.settings.contacts_per_random_case
        smallest = min((b.percentage for b in branches if b.percentage), default=0) / 100.0
        low, high = expected_range(n, smallest)
        return prefix, RandomInfo(activity_key=first_key, branches=branches, expected_low=low, expected_high=high)

    # -- assembling scenarios, cases and statuses --------------------------------------

    def run(self) -> CoverageResult:
        self.branch_list = graph.split_branches(self.journey)
        self.branch_index = {(a.key, o.key): i for i, (a, o) in enumerate(self.branch_list)}
        self.warnings.extend(graph.structural_problems(self.journey))
        self.collect_fields()
        self.build_domains()
        self.build_classes()
        self.explore()
        self.warnings.extend(self._same_name_different_conditions())
        signatures = self.enumerate_scenarios()
        det_scenarios, det_universe = self.choose_cover(signatures)
        stat_groups = self.choose_statistical(signatures, det_universe)

        scenarios: list[Scenario] = []
        pending: list[tuple[dict[FieldRef, Value], list[Leaf], bool]] = []
        for assignment, leaves in det_scenarios:
            pending.append((assignment, leaves, False))
        for assignment, _class_id, leaves, _mask in stat_groups:
            pending.append((assignment, leaves, True))
        # Spec: scenarios with a manual action come first in the run order; statistical ones last.
        pending.sort(key=lambda p: (p[2], not any(l.manual for l in p[1])))
        case_lookup: dict[str, Case] = {}
        for order, (assignment, leaves, is_stat) in enumerate(pending, start=1):
            sid = f"S{order:02d}"
            cases: list[Case] = []
            if is_stat:
                prefix, info = self._random_info(leaves)
                leaf = leaves[0]
                cls = self.classes[leaf.class_id - 1]
                case = Case(id=f"{sid}-C01", scenario_id=sid, class_id=cls.id, contact_values=dict(cls.values),
                            steps=prefix, emails_sent=[], writes=[], waits=[s.activity_key for s in prefix
                                                                               if self.journey.activities[s.activity_key].kind in graph.WAIT_KINDS],
                            manual_actions=[], end_activity_key=info.activity_key,
                            contact_count=self.settings.contacts_per_random_case, random=info)
                case.summary = self._summary(case.steps) + " > random split"
                cases.append(case)
            else:
                leaves_sorted = sorted(leaves, key=lambda l: (l.class_id, len(l.manual), l.id))
                for n, leaf in enumerate(leaves_sorted, start=1):
                    cls = self.classes[leaf.class_id - 1]
                    case = Case(id=f"{sid}-C{n:02d}", scenario_id=sid, class_id=cls.id, contact_values=dict(cls.values),
                                steps=list(leaf.steps), emails_sent=list(leaf.emails_sent), writes=list(leaf.writes),
                                waits=list(leaf.waits), manual_actions=list(leaf.manual),
                                end_activity_key=leaf.end_activity_key, contact_count=self.settings.contacts_per_case)
                    case.summary = self._summary(case.steps)
                    cases.append(case)
            for c in cases:
                case_lookup[c.id] = c
            scenarios.append(Scenario(id=sid, key="", values=dict(assignment), cases=cases, run_order=order,
                                      has_manual_action=any(c.manual_actions for c in cases), is_statistical=is_stat))

        branches = self._branch_statuses(scenarios)
        stats = {
            "scenarios": len(scenarios),
            "cases": sum(len(s.cases) for s in scenarios),
            "contacts": sum(c.contact_count for s in scenarios for c in s.cases),
            "branches": len(branches),
            "covered": sum(1 for b in branches if b.status == STATUS_COVERED),
            "covered_manual": sum(1 for b in branches if b.status == STATUS_MANUAL),
            "not_covered": sum(1 for b in branches if b.status == STATUS_NOT_COVERED),
            "contact_classes": len(self.classes),
            "paths_explored": len(self.leaves),
            "scenario_signatures": len(signatures),
        }
        return CoverageResult(
            scenarios=scenarios, branches=branches, classes=self.classes,
            scenario_fields=list(self.scenario_fields), contact_fields=list(self.contact_fields),
            domains=dict(self.domains), unsupported=list(self.package.unsupported_activities),
            warnings=list(dict.fromkeys(self.warnings)), stats=stats)

    def _summary(self, steps: list[Step]) -> str:
        parts: list[str] = []
        for step in steps:
            activity = self.journey.activities.get(step.activity_key)
            if activity is None or step.outcome_key is None:
                continue
            if activity.kind in (KIND_DECISION, KIND_ENGAGEMENT):
                outcome = activity.outcome(step.outcome_key)
                label = outcome.label if outcome is not None and outcome.label else "match"
                parts.append(f"{activity.name or activity.key}: {label}")
        text = " > ".join(parts)
        return text if len(text) <= 160 else text[:157] + "..."

    def _same_name_different_conditions(self) -> list[str]:
        """Spec check carried over: splits with the same name but different conditions."""
        by_name: dict[str, dict[str, str]] = {}
        for activity in self.journey.activities.values():
            if activity.kind != KIND_DECISION or not activity.name:
                continue
            text = " | ".join(formula_text(o.formula) for o in activity.outcomes)
            by_name.setdefault(activity.name, {}).setdefault(text, activity.key)
        out: list[str] = []
        for name, variants in by_name.items():
            if len(variants) > 1:
                keys = ", ".join(variants.values())
                out.append(f"suspicious pattern: {len(variants)} different conditions share the split name '{name}' ({keys})")
        return out

    def _branch_statuses(self, scenarios: list[Scenario]) -> list[BranchStatus]:
        plain: dict[BranchRef, list[str]] = {}
        manual: dict[BranchRef, list[str]] = {}
        statistical: dict[BranchRef, list[str]] = {}
        for scenario in scenarios:
            for case in scenario.cases:
                refs = [(s.activity_key, s.outcome_key) for s in case.steps if s.outcome_key is not None]
                if case.random is not None:
                    for rb in case.random.branches:
                        refs.append((case.random.activity_key, rb.outcome_key))
                        refs.extend((s.activity_key, s.outcome_key) for s in rb.steps if s.outcome_key is not None)
                    bucket = statistical
                elif case.manual_actions:
                    bucket = manual
                else:
                    bucket = plain
                for ref in refs:
                    bucket.setdefault(ref, []).append(case.id)

        unsupported = set(self.package.unsupported_activities)
        behind_unsupported = graph.activities_behind(self.journey, unsupported) if unsupported else set()
        preds = graph.predecessors(self.journey)
        statuses: list[BranchStatus] = []
        for activity, outcome in self.branch_list:
            ref = (activity.key, outcome.key)
            label = outcome.label or outcome.key
            if ref in plain:
                statuses.append(BranchStatus(activity.key, activity.name, activity.kind, outcome.key, label,
                                             STATUS_COVERED, "", sorted(set(plain[ref]))))
            elif ref in manual:
                if self.settings.real_inbox:
                    statuses.append(BranchStatus(activity.key, activity.name, activity.kind, outcome.key, label,
                                                 STATUS_MANUAL, "a contact must open or click the email", sorted(set(manual[ref]))))
                else:
                    statuses.append(BranchStatus(activity.key, activity.name, activity.kind, outcome.key, label,
                                                 STATUS_NOT_COVERED,
                                                 "needs an open or click but no real inbox is configured; the cases exist with undeliverable addresses",
                                                 sorted(set(manual[ref]))))
            elif ref in statistical:
                statuses.append(BranchStatus(activity.key, activity.name, activity.kind, outcome.key, label,
                                             STATUS_COVERED,
                                             f"reached only through a random split; statistical case of {self.settings.contacts_per_random_case} contacts",
                                             sorted(set(statistical[ref])), statistical=True))
            else:
                statuses.append(BranchStatus(activity.key, activity.name, activity.kind, outcome.key, label,
                                             STATUS_NOT_COVERED,
                                             self._not_covered_reason(activity, outcome, behind_unsupported, preds), []))
        return statuses

    def _not_covered_reason(self, activity: Activity, outcome: Outcome, behind_unsupported: set[str],
                            preds: dict[str, set[str]]) -> str:
        key = activity.key
        if key in self.package.unsupported_activities:
            return f"the activity itself has the unsupported type {activity.raw_type}"
        if key in behind_unsupported:
            blockers = sorted(self.package.unsupported_activities)
            return "unreachable: lies behind the unsupported activity " + ", ".join(f"'{b}'" for b in blockers)
        blocked = self.engagement_blocked.get((key, outcome.key))
        if blocked:
            return "unreachable: " + blocked
        if key not in self.reached_activities:
            parent = sorted(preds.get(key, ()))
            if not parent:
                return "unreachable: no path from the start reaches this activity"
            return ("unreachable: no combination of field values reaches this activity "
                    f"(it follows {', '.join(repr(p) for p in parent)})")
        # The split was reached but this outcome never matched.
        seen = self.reached_values.get(key, {})
        if activity.kind == KIND_DECISION and outcome.formula is not None:
            fields = []
            for cond in formula_conditions(outcome.formula):
                ref = self.schema.canonical((cond.table, cond.field))
                values = seen.get(ref)
                if values:
                    shown = ", ".join("null" if v is None else repr(v) for v in sorted(values, key=lambda x: (x is None, str(x))))
                    fields.append(f"{ref[0]}.{ref[1]} is always one of {shown}")
            detail = "; ".join(fields) if fields else "the condition is never true"
            return f"unreachable: the split is reached but '{label_of(outcome)}' never matches on those paths ({detail})"
        if activity.kind == KIND_DECISION and outcome.is_remainder:
            return "unreachable: the split is reached but an earlier outcome always matches"
        if activity.kind == KIND_ENGAGEMENT:
            return "unreachable: the split is reached but this branch is never taken"
        return "unreachable: no simulated path crosses this branch"


def label_of(outcome: Outcome) -> str:
    return outcome.label or outcome.key


def expected_range(n: int, p: float) -> tuple[int, int]:
    """Accepted count on the smallest side of a random split, about two standard deviations
    around the mean (spec: 1 to 9 contacts on the 10% side of 50)."""
    if n <= 0 or p <= 0:
        return (0, 0)
    mean = n * p
    sd = math.sqrt(n * p * (1 - p))
    low = max(1, int(round(mean - 2 * sd)))
    high = min(n - 1, int(round(mean + 2 * sd)))
    return (low, max(low, high))


def compute_coverage(package: Package, table_model: TableModel, settings: Settings,
                     generation_time: Optional[datetime] = None) -> CoverageResult:
    """Entry point: spec steps 3 to 6 on one package."""
    return CoverageEngine(package, table_model, settings, generation_time).run()
