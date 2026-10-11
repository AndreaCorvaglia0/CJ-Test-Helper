"""Shared data model for every module of the generator.

This file is the contract between modules. Every module imports from here and
nothing here imports from the other modules. Keep it plain: dataclasses, type
aliases and small helpers only.

Naming used throughout:

- *table*: a Data Extension, always referred to by its name (``Table.name``).
- *field*: a column of a table, referred to by ``FieldRef = (table_name, field_name)``.
- *branch*: one outcome of one activity, referred to by ``BranchRef = (activity_key, outcome_key)``.
- *value*: every generated or compared value is a ``str`` in CSV form, or ``None`` for null.
  Booleans are ``"True"`` / ``"False"``; dates follow ``Settings.date_format``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional, Union

FieldRef = tuple[str, str]
BranchRef = tuple[str, str]
Value = Optional[str]


# ---------------------------------------------------------------------------
# Tables and relationships (loader.py fills these from the export)
# ---------------------------------------------------------------------------

FIELD_TYPES = ("Text", "Boolean", "Date", "EmailAddress", "Phone", "Number", "Decimal", "Locale")


@dataclass(frozen=True)
class Field:
    name: str
    type: str                      # one of FIELD_TYPES as written in the export
    length: Optional[int]          # None when the type has no length
    is_primary_key: bool
    is_nullable: bool
    default: Optional[str]         # defaultValue as written in the export, e.g. "False", "GETDATE()"
    ordinal: int


@dataclass
class Table:
    id: str                        # entity id in the export
    name: str
    customer_key: Optional[str]
    fields: list[Field]
    is_sendable: bool = False
    sendable_field: Optional[str] = None   # sendableCustomObjectField: the field holding the contact key

    def field(self, name: str) -> Optional[Field]:
        """Case-insensitive lookup, because SQL and split criteria do not always match the schema's case."""
        low = name.lower()
        for f in self.fields:
            if f.name.lower() == low:
                return f
        return None

    @property
    def primary_key(self) -> list[str]:
        return [f.name for f in self.fields if f.is_primary_key]

    @property
    def field_names(self) -> list[str]:
        return [f.name for f in self.fields]


@dataclass(frozen=True)
class Relationship:
    """A link between two tables from attributeRelationships, on one pair of fields.

    Group-to-set links (the contact model itself pointing at a table) have
    ``left_table`` set to None and ``right_field`` naming the contact key field.
    """
    name: str
    left_table: Optional[str]
    left_field: Optional[str]
    right_table: str
    right_field: str
    left_cardinality: str          # "One" / "Many" as written
    right_cardinality: str


@dataclass
class EmailAsset:
    id: str
    name: str
    subject: str
    has_link: bool                 # True when the HTML or text view holds an href


# ---------------------------------------------------------------------------
# Split criteria (criteria.py produces these)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Condition:
    """One atomic condition: ``table.field operator value``.

    ``table`` is the attribute-set name as written in the XML; loader.py maps it
    to the table name before anything else sees it. ``value`` is None for
    operators without a value (IsNull, IsNotNull).
    """
    table: str
    field: str
    operator: str                  # as written: Is, Equal, IsNull, NotEqual, ...
    value: Value


@dataclass(frozen=True)
class ConditionGroup:
    operator: Literal["AND", "OR"]
    items: tuple["Formula", ...]


Formula = Union[Condition, ConditionGroup]


def formula_conditions(formula: Optional[Formula]) -> list[Condition]:
    """All atomic conditions of a formula, in document order."""
    if formula is None:
        return []
    if isinstance(formula, Condition):
        return [formula]
    out: list[Condition] = []
    for item in formula.items:
        out.extend(formula_conditions(item))
    return out


def formula_text(formula: Optional[Formula]) -> str:
    """Readable rendering, e.g. ``(A.x Is 'true' AND (A.y Is 'false' OR A.y IsNull))``."""
    if formula is None:
        return "<remainder>"
    if isinstance(formula, Condition):
        if formula.value is None:
            return f"{formula.table}.{formula.field} {formula.operator}"
        return f"{formula.table}.{formula.field} {formula.operator} {formula.value!r}"
    inner = f" {formula.operator} ".join(formula_text(i) for i in formula.items)
    return f"({inner})"


# ---------------------------------------------------------------------------
# Journey (loader.py builds it, graph.py walks it)
# ---------------------------------------------------------------------------

# Normalised activity kinds. The raw export type is kept in Activity.raw_type.
KIND_DECISION = "decision"           # MULTICRITERIADECISION
KIND_ENGAGEMENT = "engagement"       # ENGAGEMENTDECISION
KIND_RANDOM = "random"               # RANDOMSPLIT
KIND_WAIT_DURATION = "wait_duration" # WAIT with uiType WAITBYDURATION
KIND_WAIT_ATTRIBUTE = "wait_attribute"  # WAIT with uiType WAITBYATTRIBUTE
KIND_WAIT_STO = "wait_sto"           # STOWAIT (send-time optimisation)
KIND_EMAIL = "email"                 # EMAILV2
KIND_UPDATE = "update"               # UPDATECONTACTDATA
KIND_UNSUPPORTED = "unsupported"     # anything else: reported, never guessed

# The one lookup table to extend for new activity types (spec: "one lookup table each").
ACTIVITY_KINDS: dict[str, str] = {
    "MULTICRITERIADECISION": KIND_DECISION,
    "ENGAGEMENTDECISION": KIND_ENGAGEMENT,
    "RANDOMSPLIT": KIND_RANDOM,
    "WAIT": KIND_WAIT_DURATION,       # refined to wait_attribute by loader when uiType says so
    "STOWAIT": KIND_WAIT_STO,
    "EMAILV2": KIND_EMAIL,
    "UPDATECONTACTDATA": KIND_UPDATE,
}


@dataclass
class Outcome:
    key: str
    label: str                     # metaData.label, or a fallback such as the key
    next: Optional[str]            # key of the next activity, None = journey exit
    formula: Optional[Formula] = None   # decision split only; None for the remainder outcome
    is_remainder: bool = False     # decision split: taken when no earlier outcome matched
    percentage: Optional[int] = None    # random split only
    when: Optional[bool] = None    # engagement split only: True = Yes branch, False = No branch
    description: str = ""          # metaData.criteriaDescription when present


@dataclass
class Write:
    """One field written by an update-contact activity."""
    table: str
    field: str
    value: Value                   # literal as written; "{{DateTime.Now}}" means the current time


@dataclass
class Activity:
    key: str
    raw_type: str
    kind: str                      # one of the KIND_* constants
    name: str
    outcomes: list[Outcome]
    # kind-specific details, all optional:
    wait_amount: Optional[int] = None         # wait_duration
    wait_unit: Optional[str] = None           # wait_duration: MINUTES, HOURS, DAYS, ...
    wait_field: Optional[FieldRef] = None     # wait_attribute: (table, field) holding the date
    wait_timezone: Optional[str] = None
    email_asset_id: Optional[str] = None      # email
    email_name: Optional[str] = None          # email: asset name, or activity name as fallback
    engagement_kind: Optional[str] = None     # engagement: "open" or "click"
    engagement_ref: Optional[str] = None      # engagement: key of the referenced email activity
    writes: list[Write] = field(default_factory=list)   # update

    def outcome(self, key: str) -> Optional[Outcome]:
        for o in self.outcomes:
            if o.key == key:
                return o
        return None


@dataclass
class Journey:
    name: str
    key: str
    activities: dict[str, Activity]      # by activity key, in export order
    start_key: Optional[str]             # the activity no outcome points to
    entry_event_key: Optional[str]       # eventDefinitionKey of the trigger
    entry_table: Optional[str]           # table bound to the entry trigger
    default_email_event_key: Optional[str] = None   # event key used by defaults.email, for the anomaly check
    activity_count: int = 0

    def branches(self) -> list[tuple[Activity, Outcome]]:
        return [(a, o) for a in self.activities.values() for o in a.outcomes]


# ---------------------------------------------------------------------------
# Queries (loader.py gives the raw SQL, sqlparse_lite.py parses it)
# ---------------------------------------------------------------------------

@dataclass
class Query:
    id: str
    name: str
    target_table: str
    sql: str                       # with {{mcpm#...}} references already resolved to table names
    update_type: str               # Update, Overwrite, Append as written


@dataclass(frozen=True)
class ColumnRef:
    table: str                     # table name (alias already resolved); "" when it could not be resolved
    column: str


@dataclass(frozen=True)
class TableRef:
    table: str
    alias: Optional[str]


@dataclass(frozen=True)
class JoinEquality:
    left: ColumnRef
    right: ColumnRef


@dataclass(frozen=True)
class EqualityFilter:
    column: ColumnRef
    value: str                     # literal as written, without quotes


@dataclass(frozen=True)
class IsNullFilter:
    column: ColumnRef
    negated: bool = False


@dataclass(frozen=True)
class DateBoundFilter:
    """``now >= column`` (bound="start") or ``now <= column`` (bound="end")."""
    column: ColumnRef
    bound: Literal["start", "end"]


@dataclass(frozen=True)
class UnsupportedFilter:
    text: str


Filter = Union[EqualityFilter, IsNullFilter, DateBoundFilter, UnsupportedFilter]


@dataclass(frozen=True)
class SelectColumn:
    source: ColumnRef


@dataclass(frozen=True)
class SelectLiteral:
    value: str


@dataclass(frozen=True)
class SelectCurrentDate:
    format: Optional[str]          # .NET format string from FORMAT(GETDATE(), '...'), None for a plain date


@dataclass(frozen=True)
class SelectConcat:
    parts: tuple["SelectExpr", ...]


@dataclass(frozen=True)
class SelectUnsupported:
    text: str


SelectExpr = Union[SelectColumn, SelectLiteral, SelectCurrentDate, SelectConcat, SelectUnsupported]


@dataclass(frozen=True)
class SelectItem:
    target_column: str             # alias, or the source column name
    expr: SelectExpr


@dataclass
class ParsedQuery:
    name: str
    target_table: str
    sources: list[TableRef]        # FROM and JOIN tables
    joins: list[JoinEquality]
    filters: list[Filter]          # WHERE, split on AND; OR groups become UnsupportedFilter
    select: list[SelectItem]
    select_all: bool = False       # SELECT *
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# The whole export
# ---------------------------------------------------------------------------

@dataclass
class EntryEvent:
    key: str
    name: str
    table: str
    automation_name: Optional[str]


@dataclass
class Package:
    name: str
    journey: Journey
    tables: dict[str, Table]                 # by table name
    relationships: list[Relationship]
    queries: list[Query]
    entry_event: Optional[EntryEvent]
    emails: dict[str, EmailAsset]            # by asset id
    automation_queries: dict[str, list[str]] = field(default_factory=dict)  # automation name -> query names in step order
    warnings: list[str] = field(default_factory=list)   # anything odd met while reading, in plain words
    unsupported_activities: list[str] = field(default_factory=list)  # keys of activities with an unknown type


# ---------------------------------------------------------------------------
# Settings (defaults from the spec's settings table)
# ---------------------------------------------------------------------------

@dataclass
class Settings:
    contacts_per_case: int = 3
    contacts_per_random_case: int = 50
    real_inbox: str = ""                     # "name@domain"; empty = none
    real_phone: str = ""
    fake_phone: str = "333333333333"
    window_start_days: int = -1              # validity window starts yesterday
    window_end_days: int = 7                 # and ends in 7 days
    wait_offset_hours: int = 0
    wait_offset_before_engagement_hours: int = 24
    date_format: str = "%Y-%m-%d %H:%M"      # shown in the app as YYYY-MM-DD HH:MM
    one_active_scenario: Optional[bool] = None   # None = on when an activation field is detected
    activation_field: Optional[FieldRef] = None  # None = suggested from the entry query filters
    run_id: str = "R01"
    case_insensitive_text: bool = False
    seed: int = 20261011
    generation_time: Optional[datetime] = None   # None = now; tests pass a fixed value

    def contact_key(self, n: int) -> str:
        return f"TST_{self.run_id}_C{n:04d}"

    def scenario_key(self, n: int) -> str:
        return f"TST_{self.run_id}_S{n:02d}"


# ---------------------------------------------------------------------------
# Table selection and field levels (tables.py produces these)
# ---------------------------------------------------------------------------

ROLE_ENTRY = "entry"
ROLE_SPLIT = "split"
ROLE_SOURCE = "source"
ROLE_WRITTEN = "written"

LEVEL_CONTACT = "contact"
LEVEL_SCENARIO = "scenario"


@dataclass
class TableRole:
    name: str
    roles: set[str]                  # subset of ROLE_*
    selected: bool                   # gets a CSV
    level: Optional[str]             # LEVEL_CONTACT / LEVEL_SCENARIO for selected tables
    reason: str                      # plain words for the report


@dataclass
class KeyGroup:
    """Fields that must hold the same generated key, across tables."""
    kind: str                        # "contact", "scenario" or "other"
    fields: list[FieldRef]


@dataclass
class TableModel:
    entry_table: str
    contact_key_field: FieldRef                 # (entry table, its contact key field)
    tables: dict[str, TableRole]                # every table of the export
    key_groups: list[KeyGroup]
    field_levels: dict[FieldRef, str]           # for every field of every selected table
    entry_query: Optional[ParsedQuery]          # the query that fills the entry table, parsed
    source_queries: list[ParsedQuery]           # entry query plus the queries feeding its sources, in order
    scenario_tables: list[str]
    contact_tables: list[str]
    activation_field: Optional[FieldRef]        # suggested from the entry query filters
    warnings: list[str] = field(default_factory=list)

    @property
    def selected_tables(self) -> list[str]:
        return [t.name for t in self.tables.values() if t.selected]


# ---------------------------------------------------------------------------
# Coverage (coverage.py produces these; datagen.py and outputs.py consume them)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Step:
    activity_key: str
    outcome_key: Optional[str]       # None for the last activity when the journey exits there


@dataclass(frozen=True)
class ManualAction:
    activity_key: str                # the engagement split
    kind: str                        # "open" or "click"
    email_activity_key: str          # the email to act on
    email_name: str


@dataclass(frozen=True)
class RandomBranch:
    outcome_key: str
    percentage: int
    steps: tuple[Step, ...]          # the path taken after this outcome
    emails_sent: tuple[str, ...]
    writes: tuple[Write, ...]
    end_activity_key: Optional[str]


@dataclass
class RandomInfo:
    activity_key: str
    branches: list[RandomBranch]
    expected_low: int                # accepted range for the smallest side, inclusive
    expected_high: int


@dataclass
class ContactClass:
    id: int
    values: dict[FieldRef, Value]    # representative contact-level values
    predicate_truth: tuple[bool, ...]
    member_count: int                # how many contact-level value combinations it stands for


@dataclass
class Case:
    id: str                          # "S01-C01"
    scenario_id: str                 # "S01"
    class_id: int
    contact_values: dict[FieldRef, Value]
    steps: list[Step]                # deterministic part of the path, start to end (or to the random split)
    emails_sent: list[str]           # email activity keys, in order
    writes: list[Write]
    waits: list[str]                 # activity keys of waits crossed, in order
    manual_actions: list[ManualAction]
    end_activity_key: Optional[str]
    contact_count: int
    random: Optional[RandomInfo] = None     # set for the statistical case
    contact_keys: list[str] = field(default_factory=list)   # filled by datagen
    summary: str = ""                # short path summary for the testbook title


@dataclass
class Scenario:
    id: str                          # "S01"
    key: str                         # "TST_R01_S01", filled by datagen
    values: dict[FieldRef, Value]    # every scenario-level field
    cases: list[Case]
    run_order: int
    has_manual_action: bool
    is_statistical: bool = False


STATUS_COVERED = "covered"
STATUS_MANUAL = "covered with manual action"
STATUS_NOT_COVERED = "not covered"


@dataclass
class BranchStatus:
    activity_key: str
    activity_name: str
    activity_kind: str
    outcome_key: str
    outcome_label: str
    status: str                      # STATUS_*
    reason: str                      # why, in plain words (always set for not covered)
    covered_by: list[str]            # case ids
    statistical: bool = False        # covered only through a random split


@dataclass
class CoverageResult:
    scenarios: list[Scenario]
    branches: list[BranchStatus]
    classes: list[ContactClass]
    scenario_fields: list[FieldRef]  # scenario-level fields read by the journey, in order
    contact_fields: list[FieldRef]
    domains: dict[FieldRef, list[Value]]
    unsupported: list[str]           # activity keys stopped as unsupported
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)

    @property
    def cases(self) -> list[Case]:
        return [c for s in self.scenarios for c in s.cases]


# ---------------------------------------------------------------------------
# Generated data and checks
# ---------------------------------------------------------------------------

@dataclass
class TableData:
    table: str
    columns: list[str]               # schema order
    rows: list[dict[str, Value]]


@dataclass
class Contact:
    key: str
    case_id: str
    scenario_id: str
    uses_real_inbox: bool
    uses_real_phone: bool
    email: str


@dataclass
class GeneratedData:
    tables: dict[str, TableData]     # by table name, selected tables only
    contacts: list[Contact]
    scenarios_rows: list[dict[str, Value]]   # content of scenarios.csv
    placeholders: list[str]          # entry columns that got a placeholder, with the reason
    warnings: list[str] = field(default_factory=list)


@dataclass
class CheckResult:
    name: str
    passed: bool
    details: list[str]               # failures or notes, plain words


@dataclass
class GenerationResult:
    package: Package
    table_model: TableModel
    coverage: CoverageResult
    data: GeneratedData
    checks: list[CheckResult]
    settings: Settings
    files: dict[str, bytes]          # file name -> content, everything that goes into the zip
    generation_time: datetime
