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

Spec, "Extensions beyond the pilot":

- Row present or absent. Each table of ``TableModel.existence_tested`` gets a contact-level
  variable: its field linked to the contact key takes GENERATED_KEY (row present) or None
  (row absent), and every other field of an absent row reads null (graph.py).
- Values strictly inside the ranges. Number, Decimal and Date fields compared with an
  ordering operator or ``Between`` take one value inside each range the condition values cut,
  never a bound, plus the values named by the other operators (``build_domain``).
- Preference. Among values that cover the same branches, the generator prefers those whose
  path rests on no unverified assumption: not null, row present, then values inside the
  ranges rather than on a named value (``_preference``). It decides the representative of
  each contact class, the scenario kept for each signature and, among different scenarios
  crossing the same branches, the one the cover can choose (``_preferred_per_mask``).
- Honest outcomes. A path that stops at an element the PoC cannot evaluate is marked
  ``Case.unknown_from``; each manual action gets its window (``Case.action_windows``) and
  each case its minimum duration, from the waits on its path.

The simulation itself lives in graph.py so that checks.py re-simulates with the same code.
"""

from __future__ import annotations

import itertools
import math
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation
from typing import Optional

from . import criteria, graph
from .model import (
    GENERATED_KEY,
    KIND_WAIT_ATTRIBUTE,
    SOURCE_JOURNEY,
    ActionWindow,
    EqualityFilter,
    KIND_EMAIL,
    IsNullFilter,
    SelectCurrentDate,
    SelectLiteral,
    SelectNull,
    KIND_DECISION,
    KIND_ENGAGEMENT,
    KIND_RANDOM,
    KIND_UNSUPPORTED,
    KIND_UPDATE,
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
MAX_CONTACT_COMBINATIONS = 1_000_000
MAX_SCENARIO_COMBINATIONS = 2_000_000
MAX_PATHS = 400_000

OTHER_TEXT_CANDIDATES = ("OTHER", "OTHER_2", "OTHER_3", "OTHER_4", "X", "Y", "Z", "W", "XX", "YY", "ZZ", "XY", "XZ", "YZ")
OTHER_EMAIL = "other@example.invalid"
OTHER_PHONE = "000000000000"
KEY_MARKER = GENERATED_KEY         # stands for the generated key in the domain of a key field
TEXT_TYPES = ("Text", "EmailAddress", "Phone", "Locale")
ORDER_OPERATORS_UP = ("GreaterThan", "GreaterThanOrEqual")
ORDER_OPERATORS_DOWN = ("LessThan", "LessThanOrEqual")
RANGE_OPERATORS = ORDER_OPERATORS_UP + ORDER_OPERATORS_DOWN + ("Between",)
RANGE_TYPES = ("Number", "Decimal", "Date")    # the field types whose ranges build_domain fills


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


def _clashes(candidate: str, values: list[str]) -> bool:
    """A text 'other' value must not equal, contain or be contained in any condition value,
    so that Equal, Contains, BeginsWith and EndsWith conditions all stay false for it."""
    low = candidate.lower()
    for v in values:
        vl = v.lower()
        if vl and (low == vl or vl in low or low in vl):
            return True
    return False


def _other_text(values: list[str], length: Optional[int]) -> Optional[str]:
    """An 'other' text value that fits the field length; None when no such value exists."""
    for candidate in OTHER_TEXT_CANDIDATES:
        if length is not None and len(candidate) > length:
            continue
        if not _clashes(candidate, values):
            return candidate
    n = 1
    while n < 1000:
        candidate = f"O{n}"
        if length is None or len(candidate) <= length:
            if not _clashes(candidate, values):
                return candidate
        elif length is not None and length < 2:
            break
        n += 1
    return None


def _parse_date(value: str, date_format: str) -> Optional[datetime]:
    for fmt in (date_format, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _shift_date(value: str, days: int, date_format: str) -> Optional[str]:
    parsed = _parse_date(value, date_format)
    return (parsed + timedelta(days=days)).strftime(date_format) if parsed else None


def _shift_number(value: str, delta: int) -> Optional[str]:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    n += delta
    return str(int(n)) if n == int(n) else str(n)


def build_domain(field_type: str, conditions: list[Condition], nullable: bool, case_insensitive: bool,
                 date_format: str, length: Optional[int] = None,
                 scale: Optional[int] = None) -> tuple[list[Value], Optional[Value], list[str]]:
    """Spec step 4: the values named in conditions, one extra 'other' value, null when allowed.

    Returns (domain, the 'other' value, warnings). Booleans always take both True and False.
    Text values keep the letter case written in the condition (data rule 2); when text
    comparisons ignore case, spellings that differ only by case are one value. A condition
    value longer than the field can never be stored, so it is left out with a warning.

    Spec, "Extensions beyond the pilot": "Coverage values are chosen strictly inside the ranges
    the conditions define, never on a bound." On a Number, Decimal or Date field compared with an
    ordering operator or Between, the bounds and the values named by the other operators cut the
    values into ranges, and the domain takes one value inside each range (``_range_values``), then
    the named values; a bound itself is never tried. Without such a condition the domain is the
    named values plus one 'other' value above them. A text field gets no value from an ordering
    operator or Between: no value inside a text range is chosen, and a warning says so.
    """
    warnings: list[str] = []
    values: list[Value] = []
    other: Optional[Value] = None
    if field_type == "Boolean":
        for cond in conditions:
            v = _normalise_boolean(cond.value)
            if v in ("True", "False") and v not in values:
                values.append(v)
        for v in ("True", "False"):
            if v not in values:
                values.append(v)
    elif field_type in ("Number", "Decimal", "Date"):
        is_date = field_type == "Date"
        named: list[str] = []
        bounds: list[str] = []
        for cond in conditions:
            if cond.value is None:
                continue
            if cond.operator in RANGE_OPERATORS:
                bounds.extend(_range_bounds(cond))
            elif cond.value not in named:
                named.append(cond.value)
        if bounds:
            values = _range_values(named + bounds, is_date, date_format, scale if field_type == "Decimal" else 0)
            other = values[-1] if values else None
            values.extend(v for v in named if v not in values)
        else:
            values = list(named)
            if is_date:
                other = _shift_date(named[0], 1, date_format) if named else datetime(2000, 1, 1).strftime(date_format)
                while other in values:
                    other = _shift_date(other, 1, date_format)
            else:
                nums = [float(v) for v in named if _shift_number(v, 0) is not None]
                top = max(nums) + 1 if nums else 0
                other = str(int(top)) if top == int(top) else str(top)
            values.append(other)
    else:
        seen: set[str] = set()
        ranges: list[str] = []
        for cond in conditions:
            v = cond.value
            if v is None:
                continue
            if cond.operator in RANGE_OPERATORS:
                if cond.operator not in ranges:
                    ranges.append(cond.operator)
                continue
            if length is not None and len(v) > length:
                warnings.append(f"il valore {v!r} della condizione è più lungo del campo ({length} caratteri), "
                                "quindi quella condizione non può mai essere vera")
                continue
            key = v.lower() if case_insensitive else v
            if key not in seen:
                seen.add(key)
                values.append(v)
        if ranges:
            warnings.append(f"è confrontato con {', '.join(ranges)} su un campo di tipo {field_type}: il generatore non "
                            "sceglie valori dentro gli intervalli di testo, quindi i branch che li richiedono possono "
                            "risultare non coperti")
        named = [v for v in values if v is not None]
        if field_type == "EmailAddress":
            other = OTHER_EMAIL if not _clashes(OTHER_EMAIL, named) else _other_text(named, length)
        elif field_type == "Phone":
            other = OTHER_PHONE if not _clashes(OTHER_PHONE, named) else _other_text(named, length)
        else:
            other = _other_text(named, length)
        if other is None:
            warnings.append(f"nel campo ({length} caratteri) non entra nessun valore diverso da quelli delle condizioni")
        else:
            values.append(other)
    if nullable:
        values.append(None)
    return values, other, warnings


def _range_bounds(cond: Condition) -> list[str]:
    """The bounds, as written, at which an ordering or Between condition cuts the values."""
    if cond.value is None or cond.value_attribute is not None:
        return []
    if cond.operator == "Between":
        bounds = criteria.between_bounds(cond.value)
        return list(bounds) if bounds is not None else []
    return [cond.value] if cond.operator in RANGE_OPERATORS else []


_DATE_ONLY = re.compile(r"\d{4}-?\d{2}-?\d{2}")


def _range_values(points: list[str], is_date: bool, date_format: str, scale: Optional[int]) -> list[str]:
    """One value strictly inside each range the points cut: below the lowest, between two neighbours, above
    the highest, in ascending order. A range with no storable value inside (two neighbouring integers, two
    dates a day apart compared on the date) gets none. Points that cannot be read are ignored."""
    if is_date:
        cuts = sorted({d for d in (_parse_date(p.strip(), date_format) for p in points) if d is not None})
        if not cuts:
            return []
        # A condition date written without a time is compared on the date part (criteria.py), so the
        # values must then fall on other days.
        whole_days = any(_DATE_ONLY.fullmatch(p.strip()) for p in points)
        candidates = [cuts[0] - timedelta(days=1)]
        for a, b in zip(cuts, cuts[1:]):
            if whole_days:
                days = (b.date() - a.date()).days
                if days >= 2:
                    candidates.append(datetime.combine(a.date() + timedelta(days=days // 2), time()))
            else:
                candidates.append((a + (b - a) / 2).replace(second=0, microsecond=0))
        candidates.append(cuts[-1] + timedelta(days=1))
        out: list[str] = []
        for c in candidates:
            text = c.strftime(date_format)
            back = _parse_date(text, date_format)
            if back is None or text in out:
                continue
            key = back.date() if whole_days else back
            if all((key < (k.date() if whole_days else k)) or (key > (k.date() if whole_days else k)) for k in cuts):
                out.append(text)
        return out
    cuts = sorted({n for n in (_decimal(p) for p in points) if n is not None})
    if not cuts:
        return []
    numbers: list[Decimal] = []
    below = cuts[0].to_integral_value(rounding=ROUND_FLOOR)
    numbers.append(below if below < cuts[0] else cuts[0] - 1)
    for a, b in zip(cuts, cuts[1:]):
        middle = (a + b) / 2
        for candidate in (middle.to_integral_value(rounding=ROUND_FLOOR),
                          middle.to_integral_value(rounding=ROUND_CEILING), _at_scale(middle, scale)):
            if candidate is not None and a < candidate < b:
                numbers.append(candidate)
                break
    above = cuts[-1].to_integral_value(rounding=ROUND_CEILING)
    numbers.append(above if above > cuts[-1] else cuts[-1] + 1)
    return [_number_text(n) for n in numbers]


def _decimal(text: str) -> Optional[Decimal]:
    try:
        number = Decimal(text.strip())
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _at_scale(number: Decimal, scale: Optional[int]) -> Optional[Decimal]:
    """A number cut to the digits a Decimal field keeps; None for a Number field (no decimals)."""
    if scale is None:
        return number
    if scale <= 0:
        return None
    return number.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_FLOOR)


def _number_text(number: Decimal) -> str:
    """CSV form of a number: no exponent, no trailing zeros, no decimal point for a whole number."""
    if number == number.to_integral_value():
        return str(int(number))
    return format(number.normalize(), "f")

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
    unknown_from: Optional[str] = None         # the walk stopped here without reaching an exit

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
    """The leaves a full scenario assignment reaches in one class's tree (several through choice nodes)."""
    out: list[Leaf] = []
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, LeafNode):
            out.append(n.leaf)
        elif isinstance(n, BranchNode):
            child = n.children.get(assignment.get(n.field))
            if child is not None:
                stack.append(child)
        else:
            stack.extend(n.children)
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
        # Spec, "Row present or absent": lower-case table -> its field linked to the contact key (canonical).
        self.row_fields: dict[str, FieldRef] = {}
        for ref in table_model.existence_tested.values():
            linked = self.schema.canonical(ref)
            self.row_fields[linked[0].lower()] = linked
        self.walker = graph.Walker(self.journey, self.schema, package.emails,
                                   settings.case_insensitive_text, self.now, settings.date_format,
                                   row_fields=self.row_fields)
        self.walker.on_decision = self._observe_decision
        # filled by run()
        self.fields: list[FieldRef] = []
        self.conditions_by_field: dict[FieldRef, list[Condition]] = {}
        self.levels: dict[FieldRef, str] = {}
        self.domains: dict[FieldRef, list[Value]] = {}
        self.other_values: dict[FieldRef, Value] = {}
        self.named_points: dict[FieldRef, set[Value]] = {}   # range fields: domain values that are condition values
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
        self.exploration_truncated = False
        self.classes_incomplete = False
        # Elements of a supported type the generator cannot handle for some contacts: an activity where some paths
        # stop (an Update contact whose insert may fail), or a branch "<split>/<outcome>" whose range on a text
        # field gets no value (CoverageResult.unsupported_reasons): key -> why.
        self.stopped_at: dict[str, str] = {}

    # -- step 3 and 4: fields, levels, domains ------------------------------------------

    def collect_fields(self) -> None:
        """Every field read by a decision split, in order of first appearance."""
        for activity in self.journey.activities.values():
            if activity.kind != KIND_DECISION:
                continue
            for outcome in activity.outcomes:
                if outcome.unsupported_reason:
                    continue   # never evaluated: the walk stops there
                for cond in formula_conditions(outcome.formula):
                    ref = self.schema.canonical((cond.table, cond.field))
                    if ref not in self.conditions_by_field:
                        self.fields.append(ref)
                        self.conditions_by_field[ref] = []
                    self.conditions_by_field[ref].append(cond)
        journey_data = {self.schema.canonical((c.table, c.field)) for conds in self.conditions_by_field.values()
                        for c in conds if c.source == SOURCE_JOURNEY}
        for ref in self.fields:
            level = self.table_model.field_levels.get(ref)
            if level is None and ref in journey_data:
                # Spec, "Data sources of a condition": Journey Data is a column of the entry row, one per contact.
                level = LEVEL_CONTACT
            elif level is None:
                level = LEVEL_CONTACT
                self.warnings.append(
                    f"il campo {ref[0]}.{ref[1]} è letto da uno split, ma la sua tabella non è collegata alla tabella di ingresso: "
                    "è trattato come campo a livello di contatto (assunzione)")
            self.levels[ref] = level
            if self.schema.table(ref[0]) is None or self.schema.table(ref[0]).field(ref[1]) is None:
                self.warnings.append(f"il campo {ref[0]}.{ref[1]} è letto da uno split, ma non è negli schemi dell'export: è trattato come testo che ammette null")
        self.contact_fields = [f for f in self.fields if self.levels[f] == LEVEL_CONTACT]
        self.scenario_fields = [f for f in self.fields if self.levels[f] == LEVEL_SCENARIO]

    def build_domains(self) -> None:
        fixed, not_null = self._entry_pins()
        key_fields = {ref for g in self.table_model.key_groups if g.kind in ("contact", "scenario") for ref in g.fields}
        for ref in self.fields:
            conds = self.conditions_by_field[ref]
            values = [c.value for c in conds if c.value is not None]
            ftype = self.schema.field_type(ref)
            table = self.schema.table(ref[0])
            field = table.field(ref[1]) if table is not None else None
            length = field.length if field is not None else None
            self._flag_case_variants(ref, ftype, values)
            if ref in self.row_fields.values():
                # Spec, "Row present or absent": the contact has a row (its linked field holds the generated
                # key) or has none (the field reads null).
                self.domains[ref] = [KEY_MARKER, None]
                self.other_values[ref] = KEY_MARKER
                continue
            if ref in key_fields:
                # Data rule 1 wins over rule 2: a key field always holds the generated key, so a split
                # comparing it with a value can never match; IsNotNull stays true.
                self.domains[ref] = [KEY_MARKER]
                self.other_values[ref] = KEY_MARKER
                if values:
                    self.warnings.append(
                        f"{ref[0]}.{ref[1]} è letto da uno split, ma è un campo chiave: contiene la chiave generata, "
                        "quindi una condizione che lo confronta con un valore non può mai essere vera")
                continue
            scale = field.scale if field is not None else None
            domain, other, warnings = build_domain(ftype, conds, self.schema.is_nullable(ref),
                                                   self.settings.case_insensitive_text, self.settings.date_format, length,
                                                   scale)
            if ftype in ("Number", "Decimal", "Date") and any(c.operator in RANGE_OPERATORS for c in conds):
                self.named_points[ref] = {c.value for c in conds if c.operator not in RANGE_OPERATORS}
            for w in warnings:
                self.warnings.append(f"{ref[0]}.{ref[1]}: {w}")
            self.other_values[ref] = other
            if ref in fixed:
                # Data rule 3: a field filtered by the entry query holds a value that passes the filter, so a
                # contact that enters the journey can only show that value to the splits reading it.
                value = _normalise_boolean(fixed[ref]) if ftype == "Boolean" else fixed[ref]
                domain = [value]
                shown = "null" if value is None else repr(value)
                self.warnings.append(
                    f"{ref[0]}.{ref[1]} è letto da uno split ed è fissato dalla entry query: i contatti che entrano "
                    f"nel journey hanno sempre {shown}, quindi si prova solo quel valore")
            elif ref in not_null and None in domain:
                domain = [v for v in domain if v is not None]
                self.warnings.append(
                    f"{ref[0]}.{ref[1]} è letto da uno split e la entry query lo filtra con IS NOT NULL, quindi null non si prova")
            self.domains[ref] = domain

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
                shown = " e ".join(repr(s) for s in spellings)
                if self.settings.case_insensitive_text:
                    self.warnings.append(
                        f"pattern sospetto: {ref[0]}.{ref[1]} è confrontato con {shown}; "
                        "sono trattati come un solo valore perché i confronti di testo non distinguono maiuscole e minuscole")
                else:
                    self.warnings.append(
                        f"pattern sospetto: {ref[0]}.{ref[1]} è confrontato con {shown}; "
                        "sono valori diversi perché i confronti di testo distinguono maiuscole e minuscole (impostazione)")

    def _entry_pins(self) -> tuple[dict[FieldRef, Value], set[FieldRef]]:
        """Fields pinned by the entry query: equality and IS NULL filters, literal and current-date
        select expressions (every entry row gets that value), and the fields filtered IS NOT NULL."""
        query = self.table_model.entry_query
        pinned: dict[FieldRef, Value] = {}
        not_null: set[FieldRef] = set()
        if query is None:
            return pinned, not_null
        for flt in query.filters:
            if isinstance(flt, EqualityFilter):
                ref = self._filter_ref(flt.column, query)
                if ref is not None and ref not in pinned:
                    pinned[ref] = flt.value
            elif isinstance(flt, IsNullFilter):
                ref = self._filter_ref(flt.column, query)
                if ref is None:
                    continue
                if flt.negated:
                    not_null.add(ref)
                elif ref not in pinned:
                    pinned[ref] = None
        entry = self.schema.table(self.table_model.entry_table)
        if entry is not None:
            for item in query.select:
                field = entry.field(item.target_column)
                if field is None:
                    continue
                ref = (entry.name, field.name)
                if isinstance(item.expr, SelectLiteral) and ref not in pinned:
                    pinned[ref] = item.expr.value
                elif isinstance(item.expr, SelectNull) and ref not in pinned:
                    pinned[ref] = None
                elif isinstance(item.expr, SelectCurrentDate) and ref not in pinned:
                    pinned[ref] = self.now.strftime(self.settings.date_format)
        return pinned, not_null

    def _filter_ref(self, column, query) -> Optional[FieldRef]:
        if column.table:
            return self.schema.canonical((column.table, column.column))
        matches = []
        for source in query.sources:
            table = self.schema.table(source.table)
            if table is not None and table.field(column.column) is not None and table.name not in [m[0] for m in matches]:
                matches.append((table.name, table.field(column.column).name))
        return matches[0] if len(matches) == 1 else None

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

        # A field rewritten by an update-contact step can change the truth of a formula along the
        # path, so such formulas are split into their conditions: classes then stay exact. Journey Data
        # never changes (the snapshot taken at entry); a write into a table with the row present / row
        # absent variable can change every field of that table (it inserts the row).
        written = {self.schema.canonical((w.table, w.field))
                   for a in self.journey.activities.values() for w in a.writes}
        inserting = {ref[0].lower() for ref in written if ref[0].lower() in self.row_fields}

        def may_change(c: Condition, ref: FieldRef) -> bool:
            return c.source != SOURCE_JOURNEY and (ref in written or ref[0].lower() in inserting)

        for activity in self.journey.activities.values():
            if activity.kind != KIND_DECISION:
                continue
            for outcome in activity.outcomes:
                if outcome.formula is None or outcome.unsupported_reason:
                    continue
                conds = formula_conditions(outcome.formula)
                refs = [self.schema.canonical((c.table, c.field)) for c in conds]
                levels = {self.levels[r] for r in refs}
                if levels == {LEVEL_CONTACT} and not any(may_change(c, r) for c, r in zip(conds, refs)):
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
            self.classes_incomplete = True
            self.warnings.append(
                f"{total} combinazioni di valori a livello di contatto: sono state esaminate solo le prime {MAX_CONTACT_COMBINATIONS}, "
                "quindi mancano alcune classi di contatti e alcuni branch raggiungibili possono risultare non coperti")
            combos = itertools.islice(combos, MAX_CONTACT_COMBINATIONS)
        by_truth: dict[tuple[bool, ...], ContactClass] = {}
        best: dict[tuple[bool, ...], tuple[int, ...]] = {}
        for combo in combos:
            values = self._mask_absent_rows(dict(zip(self.contact_fields, combo)))

            def lookup(ref: FieldRef, _values=values):
                return _values.get(ref, graph.UNKNOWN)

            truth = tuple(bool(graph.evaluate(p, lookup, self.schema, self.settings.case_insensitive_text))
                          for p in preds)
            cls = by_truth.get(truth)
            preference = self._preference(values)
            if cls is None:
                by_truth[truth] = ContactClass(id=len(by_truth) + 1, values=values, predicate_truth=truth, member_count=1)
                best[truth] = preference
            else:
                cls.member_count += 1
                if preference < best[truth]:
                    # Spec: among values that cover the same branches, prefer those whose path rests on no
                    # unverified assumption. Every member of a class takes the same paths.
                    cls.values = values
                    best[truth] = preference
        self.classes = list(by_truth.values())

    def _mask_absent_rows(self, values: dict[FieldRef, Value]) -> dict[FieldRef, Value]:
        """Spec, "Row present or absent": every field of an absent row reads null, so a contact without the
        row has no other value in that table."""
        if not self.row_fields:
            return values
        for table, linked in self.row_fields.items():
            if linked in values and values[linked] is None:
                for ref in values:
                    if ref != linked and ref[0].lower() == table:
                        values[ref] = None
        return values

    def _preference(self, values: dict[FieldRef, Value]) -> tuple[int, int, int]:
        """Spec, "Operators, types and values": "Among values that cover the same branches, the generator
        prefers those whose path rests on no unverified assumption: not null, row present." Lower is
        better: the null values and absent rows, then the absent rows alone, then the values of a range
        field that sit on a value named by a condition rather than strictly inside a range."""
        absent = {table for table, linked in self.row_fields.items() if linked in values and values[linked] is None}
        nulls = 0
        on_points = 0
        for ref, value in values.items():
            if absent and ref[0].lower() in absent:
                continue
            if value is None:
                nulls += 1
            elif value in self.named_points.get(ref, ()):
                on_points += 1
        return (nulls + len(absent), len(absent), on_points)

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
        if len(self.leaves) >= MAX_PATHS:
            if not self.exploration_truncated:
                self.exploration_truncated = True
                self.warnings.append(
                    f"il journey ha più di {MAX_PATHS} percorsi distinti: l'esplorazione si è fermata a quel limite, quindi "
                    "alcuni branch raggiungibili possono risultare non coperti")
            state.stop = graph.STOP_ERROR
            state.stop_detail = "limite di esplorazione raggiunto"
            return LeafNode(self._leaf(cls, state, assigned, manual, randoms))
        state = self.walker.run(state, self._lookup(cls, assigned), choose=None)
        self.reached_activities.update(s.activity_key for s in state.steps)
        if state.current is not None:
            self.reached_activities.add(state.current)

        if state.stop == graph.STOP_UNDETERMINED:
            ref = state.pending_field
            if ref is None or ref not in self.domains:
                self.warnings.append(f"lo split '{state.current}' legge un campo di cui il generatore non sa elencare i valori: "
                                     "il percorso si ferma lì")
                state.stop = graph.STOP_ERROR
                state.stop_detail = f"lo split '{state.current}' legge un campo di cui il generatore non sa elencare i valori"
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
            self.warnings.append(f"percorso interrotto: {state.stop_detail}")
        stop = state.stop or graph.STOP_EXIT
        # Spec, "Honest outcomes": past an element the walk cannot evaluate, the path is unknown from there on.
        unknown_from = None if stop == graph.STOP_EXIT else (state.current or state.end_activity_key)
        stopped = self.journey.activities.get(state.current or "")
        if stop == graph.STOP_UNSUPPORTED and stopped is not None and stopped.kind == KIND_UPDATE:
            self.stopped_at.setdefault(stopped.key, state.stop_detail)
        leaf = Leaf(id=len(self.leaves), class_id=cls.id, assigned=dict(assigned), manual=manual, randoms=randoms,
                    steps=list(state.steps), emails_sent=list(state.emails_sent), writes=list(state.writes),
                    waits=list(state.waits), stop=stop, stop_detail=state.stop_detail, unknown_from=unknown_from)
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
        """Signature (the leaves a full scenario produces across all classes) -> the preferred scenario with
        it (``_preference``; the first one enumerated on a tie)."""
        domains = [self.domains[f] for f in self.scenario_fields]
        total = math.prod(len(d) for d in domains) if domains else 1
        signatures: dict[tuple[int, ...], dict[FieldRef, Value]] = {}
        if total > MAX_SCENARIO_COMBINATIONS:
            self.warnings.append(
                f"{total} combinazioni di valori a livello di scenario superano il limite del generatore "
                f"({MAX_SCENARIO_COMBINATIONS}): gli scenari sono stati costruiti solo dai valori da cui dipendono i percorsi esplorati")
            for leaf in self.leaves:
                assignment = {f: d[0] for f, d in zip(self.scenario_fields, domains)}
                assignment.update(leaf.assigned)
                sig = self._signature(assignment)
                signatures.setdefault(sig, assignment)
            return signatures
        preferences: dict[tuple[int, ...], tuple[int, int, int]] = {}
        for combo in itertools.product(*domains):
            assignment = dict(zip(self.scenario_fields, combo))
            sig = self._signature(assignment)
            preference = self._preference(assignment)
            if sig not in signatures or preference < preferences[sig]:
                signatures[sig] = assignment
                preferences[sig] = preference
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
        candidates = self._preferred_per_mask(candidates)
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
        # Cases without a manual action first, so a branch reachable without opening an email is
        # reported as plainly covered; cases with a manual action only for what remains.
        for with_manual in (False, True):
            pool = [c for c in case_candidates if bool(c[1].manual) == with_manual]
            while covered != universe:
                best = None
                best_key = None
                for cand in pool:
                    gain = bin(cand[1].mask & ~covered).count("1")
                    if gain == 0:
                        continue
                    key = (-gain, cand[0], cand[1].class_id, cand[1].id)
                    if best_key is None or key < best_key:
                        best, best_key = cand, key
                if best is None:
                    break
                selected.setdefault(best[0], []).append(best[1])
                covered |= best[1].mask
                pool.remove(best)
        if not selected:
            # A journey without any split still gets one case, so the CSVs hold data.
            for sig, assignment in signatures.items():
                leaf = next((self.leaves[i] for i in sig if self.leaves[i].deterministic), None)
                if leaf is not None:
                    chosen.append((sig, assignment))
                    selected[len(chosen) - 1] = [leaf]
                    break
        scenarios = [(chosen[i][1], leaves) for i, leaves in sorted(selected.items())]
        return scenarios, universe

    def _preferred_per_mask(self, candidates: list) -> list:
        """Spec: "Among values that cover the same branches, the generator prefers those whose path rests on
        no unverified assumption". Scenarios crossing the same branches have the same mask; the greedy cover
        can only ever choose the first of them in the shuffled order (the others never gain more), so that
        place goes to the preferred one, and the others are dropped. Ties keep the shuffled order.

        The full preference applies (not null, then values inside ranges; scenario-level fields have no row
        present / row absent variable). The team accepted on 13 October 2026 the one pilot difference this
        makes: S18 gets CHANNEL2 = OTHER instead of empty."""
        best: dict[int, tuple] = {}
        for cand in candidates:
            held = best.get(cand[2])
            if held is None or self._preference(cand[1]) < self._preference(held[1]):
                best[cand[2]] = cand
        out = []
        for cand in candidates:
            chosen = best.pop(cand[2], None)
            if chosen is not None:
                out.append(chosen)
        return out

    # -- random splits: statistical cases -----------------------------------------------

    def choose_statistical(self, signatures: dict[tuple[int, ...], dict[FieldRef, Value]], det_universe: int):
        """Branches crossed only on paths through a random split get a statistical case.

        Random leaves are grouped by scenario, contact class and manual actions: a group is one
        statistical case (its contacts share the values and the actions asked of the tester).
        Groups without a manual action are preferred."""
        random_universe = 0
        for leaf in self.leaves:
            if not leaf.deterministic:
                random_universe |= leaf.mask
        random_universe &= ~det_universe
        if not random_universe:
            return []
        groups: list[tuple[dict[FieldRef, Value], int, tuple[ManualAction, ...], list[Leaf], int]] = []
        for sig, assignment in signatures.items():
            by_group: dict[tuple[int, tuple[ManualAction, ...]], list[Leaf]] = {}
            for leaf_id in sig:
                leaf = self.leaves[leaf_id]
                if not leaf.deterministic:
                    by_group.setdefault((leaf.class_id, leaf.manual), []).append(leaf)
            for (class_id, manual), leaves in by_group.items():
                mask = 0
                for leaf in leaves:
                    mask |= leaf.mask
                groups.append((assignment, class_id, manual, leaves, mask & random_universe))
        rng = random.Random(self.settings.seed + 1)
        rng.shuffle(groups)
        covered = 0
        chosen = []
        while covered != random_universe:
            best = None
            best_key = None
            for g in groups:
                gain = bin(g[4] & ~covered).count("1")
                if gain == 0:
                    continue
                key = (-gain, len(g[2]), len(g[3]), g[1])
                if best_key is None or key < best_key:
                    best, best_key = g, key
            if best is None:
                break
            chosen.append(best)
            covered |= best[4]
            groups.remove(best)
        return chosen

    def _random_info(self, leaves: list[Leaf]) -> tuple[list[Step], RandomInfo]:
        """Cut the leaves at their first random split: the common prefix and one branch per leaf.

        A leaf that crosses several random splits is one branch whose percentage is the product
        of the percentages it took; its steps show every random split crossed."""
        first_key = leaves[0].randoms[0][0]
        activity = self.journey.activities[first_key]
        prefix: list[Step] = []
        for step in leaves[0].steps:
            if step.activity_key == first_key:
                break
            prefix.append(step)
        prefix.append(Step(first_key, None))
        order = {o.key: i for i, o in enumerate(activity.outcomes)}

        def sort_key(leaf: Leaf):
            return [order.get(leaf.randoms[0][1], 99)] + [k for pair in leaf.randoms for k in pair]

        branches: list[RandomBranch] = []
        for leaf in sorted(leaves, key=sort_key):
            share = 1.0
            for key, outcome_key in leaf.randoms:
                split = self.journey.activities.get(key)
                outcome = split.outcome(outcome_key) if split is not None else None
                share *= (outcome.percentage or 0) / 100.0 if outcome is not None else 0
            idx = next(i for i, st in enumerate(leaf.steps) if st.activity_key == first_key)
            branches.append(RandomBranch(
                outcome_key=leaf.randoms[0][1], percentage=int(round(share * 100)),
                steps=tuple(leaf.steps[idx + 1:]), emails_sent=tuple(leaf.emails_sent),
                writes=tuple(leaf.writes), end_activity_key=leaf.end_activity_key,
                unknown_from=leaf.unknown_from, unknown_reason=leaf.stop_detail if leaf.unknown_from else ""))
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
        self.warnings.extend(self._engagement_refers_to_an_earlier_email())
        signatures = self.enumerate_scenarios()
        det_scenarios, det_universe = self.choose_cover(signatures)
        stat_groups = self.choose_statistical(signatures, det_universe)

        # Spec step 6: paths sharing the same scenario-level values form one scenario, so a
        # statistical group joins the scenario with its values when there is one.
        def key_of(assignment: dict[FieldRef, Value]):
            return tuple(sorted(assignment.items(), key=lambda kv: (kv[0], str(kv[1]))))

        pending: dict[tuple, dict] = {}
        for assignment, leaves in det_scenarios:
            entry = pending.setdefault(key_of(assignment), {"values": assignment, "det": [], "stat": []})
            entry["det"].extend(leaves)
        for assignment, class_id, manual, leaves, _mask in stat_groups:
            entry = pending.setdefault(key_of(assignment), {"values": assignment, "det": [], "stat": []})
            entry["stat"].append((class_id, manual, leaves))

        def has_manual(entry: dict) -> bool:
            return any(l.manual for l in entry["det"]) or any(m for _, m, _ in entry["stat"])

        # Spec: scenarios with a manual action come first in the run order; statistical-only last.
        ordered = sorted(pending.values(), key=lambda e: (not e["det"], not has_manual(e)))
        scenarios: list[Scenario] = []
        for order, entry in enumerate(ordered, start=1):
            sid = f"S{order:02d}"
            cases: list[Case] = []
            for leaf in sorted(entry["det"], key=lambda l: (l.class_id, len(l.manual), l.id)):
                cls = self.classes[leaf.class_id - 1]
                case = Case(id=f"{sid}-C{len(cases) + 1:02d}", scenario_id=sid, class_id=cls.id,
                            contact_values=dict(cls.values), steps=list(leaf.steps), emails_sent=list(leaf.emails_sent),
                            writes=list(leaf.writes), waits=list(leaf.waits), manual_actions=list(leaf.manual),
                            end_activity_key=leaf.end_activity_key, contact_count=self.settings.contacts_per_case)
                case.summary = self._summary(case.steps)
                if case.manual_actions:
                    case.inbox_blocked_reason = self._inbox_block_reason(cls.values, entry["values"])
                if leaf.unknown_from is not None:
                    case.unknown_from, case.unknown_reason = leaf.unknown_from, leaf.stop_detail
                self._timing(case)
                cases.append(case)
            for class_id, manual, leaves in sorted(entry["stat"], key=lambda g: (len(g[1]), g[0])):
                prefix, info = self._random_info(leaves)
                cls = self.classes[class_id - 1]
                prefix_keys = [st.activity_key for st in prefix]
                case = Case(id=f"{sid}-C{len(cases) + 1:02d}", scenario_id=sid, class_id=cls.id,
                            contact_values=dict(cls.values), steps=prefix,
                            emails_sent=[k for k in prefix_keys if self.journey.activities[k].kind == KIND_EMAIL],
                            writes=[], waits=[k for k in prefix_keys if self.journey.activities[k].kind in graph.WAIT_KINDS],
                            manual_actions=list(manual), end_activity_key=info.activity_key,
                            contact_count=self.settings.contacts_per_random_case, random=info)
                prefix_summary = self._summary(case.steps)
                case.summary = (prefix_summary + " > random split") if prefix_summary else "random split"
                if case.manual_actions:
                    case.inbox_blocked_reason = self._inbox_block_reason(cls.values, entry["values"])
                self._timing(case)
                cases.append(case)
            scenarios.append(Scenario(id=sid, key="", values=dict(entry["values"]), cases=cases, run_order=order,
                                      has_manual_action=any(c.manual_actions for c in cases),
                                      is_statistical=not entry["det"]))

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
            "classes_incomplete": int(self.classes_incomplete),
            "exploration_truncated": int(self.exploration_truncated),
            "paths_explored": len(self.leaves),
            "scenario_signatures": len(signatures),
        }
        return CoverageResult(
            scenarios=scenarios, branches=branches, classes=self.classes,
            scenario_fields=list(self.scenario_fields), contact_fields=list(self.contact_fields),
            domains=dict(self.domains), other_values=dict(self.other_values),
            unsupported=list(self.package.unsupported_activities) + [
                f"{a.key}/{o.key}" for a in self.journey.activities.values() for o in a.outcomes if o.unsupported_reason]
            + [key for key in self.stopped_at if key.partition("/")[0] in self.journey.activities],
            warnings=list(dict.fromkeys(self.warnings)), stats=stats,
            row_fields={linked[0]: linked for linked in self.row_fields.values()},
            unsupported_reasons=dict(self.stopped_at))

    # -- honest outcomes: windows of the manual actions and minimum durations -------------

    def _timing(self, case: Case) -> None:
        """Spec, "Honest outcomes": "The deadline of a manual open or click is computed from the waits
        between the email and the engagement split ... The testbook gives each case's minimum duration."

        Fills ``case.action_windows`` (one per manual action: the waits between its email and its split,
        their fixed duration, the last wait by attribute among them, whose date datagen.py turns into
        the deadline, and the waits before the email, which delay its arrival and so the start of the
        window) and ``case.min_duration_minutes`` (the fixed waits of the longest path of the case)."""
        activities = self.journey.activities
        paths = graph.case_paths(case)
        durations = [self._fixed_minutes(keys, need_dates=False) for keys in paths]
        case.min_duration_minutes = None if any(d is None for d in durations) else max(durations, default=0)
        windows: list[ActionWindow] = []
        for action in case.manual_actions:
            keys = next((p for p in paths if action.activity_key in p), [])
            end = keys.index(action.activity_key) if keys else 0
            start = keys.index(action.email_activity_key) if action.email_activity_key in keys[:end] else -1
            waits = [k for k in keys[start + 1:end] if activities[k].kind in graph.WAIT_KINDS]
            attribute = [k for k in waits if activities[k].kind == KIND_WAIT_ATTRIBUTE]
            after = waits[waits.index(attribute[-1]) + 1:] if attribute else []
            before = [k for k in keys[:max(start, 0)] if activities[k].kind in graph.WAIT_KINDS]
            windows.append(ActionWindow(
                activity_key=action.activity_key, email_activity_key=action.email_activity_key, wait_keys=waits,
                minutes=self._fixed_minutes(waits), attribute_wait_key=attribute[-1] if attribute else None,
                minutes_after_attribute_wait=self._fixed_minutes(after), wait_keys_before=before))
        case.action_windows = windows

    def _fixed_minutes(self, keys: list[str], need_dates: bool = True) -> Optional[int]:
        """Fixed duration of the waits among ``keys``, in minutes (graph.fixed_wait_minutes); None when one
        is unknown, or, with ``need_dates``, when a wait by attribute has no date field (a window that ends
        at an unknown date is unknown)."""
        total = 0
        for key in keys:
            activity = self.journey.activities.get(key)
            if activity is None or activity.kind not in graph.WAIT_KINDS:
                continue
            if need_dates and activity.kind == KIND_WAIT_ATTRIBUTE and activity.wait_field is None:
                return None
            minutes = graph.fixed_wait_minutes(activity)
            if minutes is None:
                return None
            total += minutes
        return total

    def _inbox_block_reason(self, contact_values: dict[FieldRef, Value],
                            scenario_values: dict[FieldRef, Value]) -> Optional[str]:
        """Data rule 2 wins over rule 4: when a split fixes the address field the journey sends to,
        the contacts of that case cannot use the tester's inbox, so their open or click cannot be done."""
        entry = self.table_model.entry_table
        default_email = (self.journey.default_email_field or "").lower()
        absent = {table for table, linked in self.row_fields.items()
                  if linked in contact_values and contact_values[linked] is None}
        for values in (contact_values, scenario_values):
            for ref, value in values.items():
                if ref[0].lower() in absent:
                    continue   # the contact has no row there: no address of that table is written
                is_address = (self.schema.field_type(ref) == "EmailAddress"
                              or (ref[0].lower() == entry.lower() and ref[1].lower() == default_email))
                if not is_address:
                    continue
                if value is None:
                    return f"il percorso richiede che {ref[0]}.{ref[1]} sia vuoto, quindi nessuna email può essere ricevuta"
                if value != self.other_values.get(ref):
                    return (f"il percorso richiede {ref[0]}.{ref[1]} = {value!r}, un indirizzo che il tester non possiede, "
                            "quindi l'email non può essere aperta né cliccata")
        return None

    def _summary(self, steps: list[Step]) -> str:
        parts: list[str] = []
        for step in steps:
            activity = self.journey.activities.get(step.activity_key)
            if activity is None or step.outcome_key is None:
                continue
            if activity.kind in (KIND_DECISION, KIND_ENGAGEMENT):
                outcome = activity.outcome(step.outcome_key)
                label = outcome.label if outcome is not None and outcome.label else "condizione vera"
                parts.append(f"{activity.name or activity.key}: {label}")
        text = " > ".join(parts)
        return text if len(text) <= 160 else text[:157] + "..."

    def _engagement_refers_to_an_earlier_email(self) -> list[str]:
        """Spec check carried over: an engagement split that references an email never sent on the
        paths reaching it. Read structurally: when another email is the last one sent before the
        split on some path, the split measures an older email than the one just sent."""
        preds = graph.predecessors(self.journey)
        out: list[str] = []
        for activity in self.journey.activities.values():
            if activity.kind != KIND_ENGAGEMENT or not activity.engagement_ref:
                continue
            nearest: set[str] = set()
            seen: set[str] = set()
            stack = list(preds.get(activity.key, ()))
            while stack:
                k = stack.pop()
                if k in seen:
                    continue
                seen.add(k)
                a = self.journey.activities.get(k)
                if a is None:
                    continue
                if a.kind == KIND_EMAIL:
                    nearest.add(k)
                    continue
                stack.extend(preds.get(k, ()))
            others = sorted(k for k in nearest if k != activity.engagement_ref)
            if others:
                ref = self.journey.activities.get(activity.engagement_ref)
                ref_name = ref.email_name if ref is not None and ref.email_name else activity.engagement_ref
                names = [f"'{self.journey.activities[k].email_name or k}' ({k})" for k in others]
                shown = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " oppure " + names[-1]
                out.append(f"pattern sospetto: l'engagement split '{activity.name or activity.key}' ({activity.key}) "
                           f"misura l'email '{ref_name}' ({activity.engagement_ref}), ma su alcuni percorsi l'ultima "
                           f"email inviata prima dello split è {shown}")
        return out

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
                out.append(f"pattern sospetto: {len(variants)} split con condizioni diverse hanno lo stesso nome '{name}' ({keys})")
        return out

    def _branch_statuses(self, scenarios: list[Scenario]) -> list[BranchStatus]:
        """Each split branch: covered (a case without manual action crosses it), covered with
        manual action, or not covered with a reason. A branch crossed only after a random split
        is flagged statistical; the branches before the random split are crossed with certainty."""
        plain: dict[BranchRef, list[str]] = {}
        manual: dict[BranchRef, list[str]] = {}
        stat_plain: dict[BranchRef, list[str]] = {}
        stat_manual: dict[BranchRef, list[str]] = {}
        blocked: dict[BranchRef, list[tuple[str, str]]] = {}   # manual cases whose action cannot be done
        for scenario in scenarios:
            for case in scenario.cases:
                if case.manual_actions and case.inbox_blocked_reason:
                    refs = [(s.activity_key, s.outcome_key) for s in case.steps if s.outcome_key is not None]
                    if case.random is not None:
                        for rb in case.random.branches:
                            refs.append((case.random.activity_key, rb.outcome_key))
                            refs.extend((s.activity_key, s.outcome_key) for s in rb.steps if s.outcome_key is not None)
                    for ref in refs:
                        blocked.setdefault(ref, []).append((case.id, case.inbox_blocked_reason))
                    continue
                before = [(s.activity_key, s.outcome_key) for s in case.steps if s.outcome_key is not None]
                after: list[BranchRef] = []
                if case.random is not None:
                    for rb in case.random.branches:
                        after.append((case.random.activity_key, rb.outcome_key))
                        after.extend((s.activity_key, s.outcome_key) for s in rb.steps if s.outcome_key is not None)
                sure = manual if case.manual_actions else plain
                random_bucket = stat_manual if case.manual_actions else stat_plain
                for ref in before:
                    sure.setdefault(ref, []).append(case.id)
                for ref in after:
                    random_bucket.setdefault(ref, []).append(case.id)
        statistical: dict[BranchRef, list[str]] = {}
        for ref, ids in stat_plain.items():
            statistical.setdefault(ref, []).extend(ids)
        for ref, ids in stat_manual.items():
            if ref not in plain and ref not in stat_plain:
                manual.setdefault(ref, []).extend(ids)
                statistical.setdefault(ref, []).extend(ids)
            else:
                statistical.setdefault(ref, []).extend(ids)

        unsupported = set(self.package.unsupported_activities)
        preds = graph.predecessors(self.journey)
        statuses: list[BranchStatus] = []
        root_reasons: dict[BranchRef, str] = {}
        for activity, outcome in self.branch_list:
            ref = (activity.key, outcome.key)
            label = outcome.label or outcome.key
            stat_note = f"raggiunto solo attraverso un random split; caso statistico di {self.settings.contacts_per_random_case} contatti"
            if _unknown_engagement(activity):
                # Triage RB-5: the split measures neither an open nor a click, so no branch can be claimed,
                # whatever path crosses it; the loader warns that both branches are not covered.
                reason = self._not_covered_reason(activity, outcome, preds)
                root_reasons[ref] = reason
                statuses.append(BranchStatus(activity.key, activity.name, activity.kind, outcome.key, label,
                                             STATUS_NOT_COVERED, reason, []))
            elif ref in plain:
                statuses.append(BranchStatus(activity.key, activity.name, activity.kind, outcome.key, label,
                                             STATUS_COVERED, "", sorted(set(plain[ref]))))
            elif ref in manual:
                is_stat = ref in statistical and ref not in plain
                reason = "un contatto deve aprire o cliccare l'email" + ("; " + stat_note if is_stat else "")
                if self.settings.real_inbox:
                    statuses.append(BranchStatus(activity.key, activity.name, activity.kind, outcome.key, label,
                                                 STATUS_MANUAL, reason, sorted(set(manual[ref])), statistical=is_stat))
                else:
                    statuses.append(BranchStatus(activity.key, activity.name, activity.kind, outcome.key, label,
                                                 STATUS_NOT_COVERED,
                                                 "richiede un open o un click, ma non è configurata un'inbox reale; i casi esistono, con indirizzi non recapitabili",
                                                 sorted(set(manual[ref])), statistical=is_stat))
            elif ref in statistical:
                statuses.append(BranchStatus(activity.key, activity.name, activity.kind, outcome.key, label,
                                             STATUS_COVERED, stat_note, sorted(set(statistical[ref])), statistical=True))
            elif ref in blocked:
                ids = sorted({cid for cid, _ in blocked[ref]})
                reason = blocked[ref][0][1]
                statuses.append(BranchStatus(activity.key, activity.name, activity.kind, outcome.key, label,
                                             STATUS_NOT_COVERED,
                                             f"richiede un open o un click che non si può fare: {reason}; i casi esistono",
                                             ids))
            else:
                behind = None
                if activity.key in self.reached_activities or activity.key in unsupported:
                    reason = self._not_covered_reason(activity, outcome, preds)
                    root_reasons[ref] = reason
                else:
                    roots = self._root_branches(activity.key, preds)
                    if roots:
                        behind = roots[0]
                        root_activity = self.journey.activities[behind[0]]
                        root_outcome = root_activity.outcome(behind[1])
                        root_reason = root_reasons.get(behind)
                        if root_reason is None:
                            root_reason = self._not_covered_reason(root_activity, root_outcome, preds)
                            root_reasons[behind] = root_reason
                        prefix = ("a valle di un elemento non supportato"
                                  if root_reason.startswith(("attività non supportata", "branch non supportato",
                                                             "a valle di un elemento non supportato"))
                                  else "non raggiungibile")
                        reason = (f"{prefix}: si trova a valle del branch '{root_activity.name or behind[0]}: {label_of(root_outcome)}' "
                                  f"({behind[0]}), che non è coperto per questo motivo: {root_reason}")
                    else:
                        reason = self._not_covered_reason(activity, outcome, preds)
                statuses.append(BranchStatus(activity.key, activity.name, activity.kind, outcome.key, label,
                                             STATUS_NOT_COVERED, reason, [], behind=behind))
        return statuses

    def _seen_text(self, ref: FieldRef, values: set[Value]) -> str:
        """The values a split saw in a field, for the reason of a branch that never matched."""
        if ref in self.row_fields.values():
            if all(not graph.is_null(v) for v in values):
                return f"il contatto ha sempre una riga in {ref[0]}"
            if all(graph.is_null(v) for v in values):
                return f"il contatto non ha mai una riga in {ref[0]}"
        elif ref[0].lower() in self.row_fields and all(graph.is_null(v) for v in values):
            return (f"{ref[0]}.{ref[1]} è sempre null, perché il contatto non ha una riga in {ref[0]} oppure il campo "
                    "è vuoto")
        if values == {KEY_MARKER}:
            return f"{ref[0]}.{ref[1]} contiene sempre la chiave generata"
        shown = ", ".join("la chiave generata" if v == KEY_MARKER else "null" if v is None else repr(v)
                          for v in sorted(values, key=lambda x: (x is None, str(x))))
        return f"{ref[0]}.{ref[1]} vale sempre uno tra {shown}"

    def _root_branches(self, key: str, preds: dict[str, set[str]]) -> list[BranchRef]:
        """For an activity no path reaches: the branches of reached activities that lead into the
        unreached region around it. Those branches are the root cause; everything behind them inherits it."""
        region: set[str] = set()
        stack = [key]
        while stack:
            k = stack.pop()
            if k in region:
                continue
            region.add(k)
            for p in preds.get(k, ()):
                if p not in self.reached_activities:
                    stack.append(p)
        roots: set[BranchRef] = set()
        for k in region:
            for p in preds.get(k, ()):
                if p in self.reached_activities:
                    for o in self.journey.activities[p].outcomes:
                        if o.next == k:
                            roots.add((p, o.key))
        return sorted(roots)

    def _not_covered_reason(self, activity: Activity, outcome: Outcome, preds: dict[str, set[str]]) -> str:
        key = activity.key
        if key in self.stopped_at:
            return f"attività non supportata: {self.stopped_at[key]}"
        if key in self.package.unsupported_activities:
            if activity.unsupported_reason:
                return f"attività non supportata: {activity.unsupported_reason}"
            return f"attività non supportata: il PoC non gestisce il tipo {activity.raw_type}"
        if outcome.unsupported_reason:
            return f"branch non supportato: {outcome.unsupported_reason}"
        if _unknown_engagement(activity):
            return ("branch non supportato: lo split misura un tipo di statistica che non è né un open né un click, "
                    "quindi nessuno dei suoi branch può essere considerato coperto")
        if activity.kind == KIND_DECISION:
            remainder = [o for o in activity.outcomes if o.is_remainder or o.formula is None]
            ordered = [o for o in activity.outcomes if o not in remainder] + remainder
            for earlier in ordered:
                if earlier is outcome:
                    break
                if earlier.unsupported_reason:
                    return (f"a valle di un elemento non supportato: questo branch viene dopo il branch non supportato "
                            f"'{label_of(earlier)}' dello stesso split, quindi non viene mai valutato")
        blocked = self.engagement_blocked.get((key, outcome.key))
        if blocked:
            return "non raggiungibile: " + blocked
        if key not in self.reached_activities:
            parent = sorted(preds.get(key, ()))
            if not parent:
                return "non raggiungibile: nessun percorso dall'inizio del journey raggiunge questa attività"
            return ("non raggiungibile: nessuna combinazione di valori dei campi raggiunge questa attività "
                    f"(segue {', '.join(repr(p) for p in parent)})")
        # The split was reached but this outcome never matched.
        seen = self.reached_values.get(key, {})
        if activity.kind == KIND_DECISION and outcome.formula is not None:
            for cond in formula_conditions(outcome.formula):
                ref = self.schema.canonical((cond.table, cond.field))
                ftype = self.schema.field_type(ref)
                if cond.operator in RANGE_OPERATORS and ftype not in RANGE_TYPES and cond.value_attribute is None:
                    # build_domain picks no value inside a range of such a field, so the branch may well be
                    # reachable in Salesforce: an element the generator does not support, not an unreachable branch.
                    why = (f"la condizione confronta {ref[0]}.{ref[1]}, un campo di tipo {ftype}, con {cond.operator}: il "
                           "generatore sceglie valori dentro un intervallo solo per i campi Number, Decimal e Date, quindi "
                           "nei dati di test nessun contatto la soddisfa, anche se in Salesforce un contatto potrebbe")
                    self.stopped_at[f"{key}/{outcome.key}"] = why
                    return f"branch non supportato: {why}"
            for cond in formula_conditions(outcome.formula):
                ref = self.schema.canonical((cond.table, cond.field))
                table = self.schema.table(ref[0])
                field = table.field(ref[1]) if table is not None else None
                if (cond.value is not None and field is not None and field.length
                        and field.type in TEXT_TYPES and len(cond.value) > field.length):
                    return (f"non raggiungibile: il valore {cond.value!r} della condizione è più lungo di {ref[0]}.{ref[1]} "
                            f"({field.length} caratteri), quindi il campo non può mai contenerlo")
            fields = []
            for cond in formula_conditions(outcome.formula):
                ref = self.schema.canonical((cond.table, cond.field))
                values = seen.get(ref)
                if values:
                    fields.append(self._seen_text(ref, values))
            detail = "; ".join(fields) if fields else "la condizione non è mai vera"
            return (f"non raggiungibile: lo split è raggiunto, ma su quei percorsi la condizione di '{label_of(outcome)}' "
                    f"non è mai vera ({detail})")
        if activity.kind == KIND_DECISION and outcome.is_remainder:
            return "non raggiungibile: lo split è raggiunto, ma la condizione di un branch precedente è sempre vera"
        if activity.kind == KIND_ENGAGEMENT:
            return "non raggiungibile: lo split è raggiunto, ma nessun contatto prende questo branch"
        return "non raggiungibile: nessun percorso simulato attraversa questo branch"


def _unknown_engagement(activity: Activity) -> bool:
    """An engagement split whose statsTypeId is neither an open nor a click (triage RB-5)."""
    return activity.kind == KIND_ENGAGEMENT and activity.engagement_kind not in ("open", "click")


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
