"""Data generation: turn the scenarios and cases of the coverage into rows, one table at a time.

Spec, "Data generation rules": every generated value comes from one of five sources, applied in
this priority order:

    1. Key or join field               -> generated key, identical in every table that joins on it
    2. Field read by a split           -> the value the case requires, written exactly as in the condition
    3. Field filtered by the entry query -> a value that passes the filter, so the contact really enters
    4. Email, phone, date              -> the email, phone and date rules
    5. Any other field                 -> placeholder by type: text ``TST_<field>_<n>`` cut to the field
                                          length, Boolean set to its default or false

Spec, "Table selection": "The entry CSV is kept consistent with the source CSVs: its rows are what
the entry query would produce from them." So the entry table is not filled by the five rules
directly. Its rows are computed from the entry query's select expressions over the source rows of
each contact, and a requirement on an entry column (a key, a split value, a wait date) is pushed
back onto the source column that the select copies into it.

Phone numbers. The spec gives one contact per case the tester's real number "in each case whose
path sends a message to a phone". None of the activity types supported by the PoC sends to a phone
(the pilot's SMS steps are update-contact placeholders), so every phone field gets
``Settings.fake_phone`` and ``Contact.uses_real_phone`` is always False. ``_uses_real_phone`` is
the hook to change when an SMS activity type is supported.

Nothing here reads the clock or draws random numbers: the generation time is passed in, so the same
inputs always give the same rows ("The output is reproducible").
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from .model import (
    KIND_DECISION,
    KIND_WAIT_ATTRIBUTE,
    LEVEL_CONTACT,
    LEVEL_SCENARIO,
    Case,
    ColumnRef,
    Contact,
    CoverageResult,
    DateBoundFilter,
    EqualityFilter,
    Field,
    FieldRef,
    GeneratedData,
    IsNullFilter,
    ManualAction,
    Package,
    Scenario,
    SelectColumn,
    SelectConcat,
    SelectCurrentDate,
    SelectLiteral,
    SelectUnsupported,
    Settings,
    Table,
    TableData,
    TableModel,
    UnsupportedFilter,
    Value,
    formula_conditions,
)

# Columns of scenarios.csv that come before the scenario-level fields (plan.md, "datagen.py").
SCENARIO_COLUMNS = [
    "scenario_key",
    "run_order",
    "has_manual_action",
    "is_statistical",
    "case_count",
    "contact_count",
    "first_contact_key",
    "last_contact_key",
    "activate",
]

UNDELIVERABLE_DOMAIN = "example.invalid"   # spec: "<contact key>@example.invalid"
LOCALE_PLACEHOLDER = "en-US"

# Rule kinds with their place in the spec's priority order: (priority 1..5, order inside it).
# Inside priority 3 the one-active-scenario activation value refines the equality filter on the
# same field; inside priority 4 a wait date is more specific than the plain date rule.
_PRIORITY = {
    "key": (1, 0),
    "split": (2, 0),
    "activation": (3, 0),
    "filter": (3, 1),
    "wait": (4, 0),
    "email": (4, 1),
    "phone": (4, 2),
    "date": (4, 3),
    "placeholder": (5, 0),
}

_RULE_NAMES = {
    "key": "generated key",
    "split": "value required by a split",
    "activation": "activation value of the one-active-scenario setting",
    "filter": "value required by the entry query filter",
    "wait": "wait date",
    "email": "email address",
    "phone": "phone number",
    "date": "generation date",
    "placeholder": "placeholder",
}

# Requirements an entry column passes back to the source column the select copies into it.
_PUSHED_BACK_KINDS = ("key", "split", "activation", "wait", "email", "phone", "date")

# Rules whose value is a requirement: when a higher rule wins over one of them, a warning says so.
_REQUIREMENT_KINDS = ("key", "split", "activation", "filter", "wait")

# Defaults that mean "the current date" in a Data Extension schema (the export writes GETDATE()).
_CURRENT_DATE_DEFAULTS = ("getdate()", "getutcdate()", "sysdatetime()")

_SKIP = object()   # a rule that does not apply to this row: try the next rule


def generate_data(
    package: Package,
    model: TableModel,
    coverage: CoverageResult,
    settings: Settings,
    generation_time: datetime,
) -> GeneratedData:
    """Turn the coverage into rows per selected table, following the spec's data generation rules.

    Also fills ``Scenario.key`` and ``Case.contact_keys`` in place (scenarios in run order, cases in
    the order coverage lists them), and returns one ``Contact`` record per generated contact.
    """
    return _Generator(package, model, coverage, settings, generation_time).run()


def activation_setting(
    package: Package, model: TableModel, settings: Settings
) -> tuple[bool, Optional[FieldRef], list[str]]:
    """Resolve the "one active scenario at a time" setting: (on, activation field, warnings).

    Spec: "The app therefore has an optional 'one active scenario' setting with an activation field,
    suggested from the entry query filters (ACTIVE in the pilot). When on, only the first scenario is
    active in the CSV." Settings table: "One active scenario at a time: On when an activation field
    is detected"; "Activation field: Suggested from the entry query filters".

    The field comes from ``settings.activation_field``, else ``model.activation_field``. The mode
    needs a Boolean field of a table that gets a CSV; otherwise it is switched off with a warning.
    The returned field uses the schema spelling.
    """
    warnings: list[str] = []
    ref = settings.activation_field or model.activation_field
    on = settings.one_active_scenario if settings.one_active_scenario is not None else ref is not None
    if not on:
        return False, None, warnings
    if ref is None:
        warnings.append(
            "One active scenario at a time is switched on, but no activation field was given or "
            "detected, so every scenario is active in the CSV."
        )
        return False, None, warnings
    table = _find_table(package.tables, ref[0])
    field = table.field(ref[1]) if table is not None else None
    if table is None or field is None:
        warnings.append(
            f"The activation field {ref[0]}.{ref[1]} does not exist in the export, so one active "
            "scenario at a time is switched off and every scenario is active in the CSV."
        )
        return False, None, warnings
    if table.name.lower() not in {name.lower() for name in model.selected_tables}:
        warnings.append(
            f"The activation field {table.name}.{field.name} is in a table that gets no CSV, so one "
            "active scenario at a time is switched off and every scenario is active in the CSV."
        )
        return False, None, warnings
    if _field_type(field) != "boolean":
        warnings.append(
            f"The activation field {table.name}.{field.name} is of type {field.type}, not Boolean, so "
            "one active scenario at a time is switched off and every scenario is active in the CSV."
        )
        return False, None, warnings
    return True, (table.name, field.name), warnings


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _norm(ref: FieldRef) -> tuple[str, str]:
    """Field lookups are case-insensitive (plan.md, "Rules for everyone")."""
    return (ref[0].lower(), ref[1].lower())


def _find_table(tables: dict[str, Table], name: str) -> Optional[Table]:
    if name in tables:
        return tables[name]
    low = name.lower()
    for table in tables.values():
        if table.name.lower() == low:
            return table
    return None


def _field_type(field: Field) -> str:
    return (field.type or "").strip().lower()


def _schema_fields(table: Table) -> list[Field]:
    """Fields in schema order (spec: "header row with the exact field names in schema order")."""
    return sorted(table.fields, key=lambda f: f.ordinal)


def boolean_text(value: Optional[str]) -> Optional[str]:
    """Spec file format: "True/False for Booleans". Returns None when the value is not a Boolean."""
    if value is None:
        return None
    low = str(value).strip().lower()
    if low in ("true", "1"):
        return "True"
    if low in ("false", "0"):
        return "False"
    return None


def _bool_text(flag: bool) -> str:
    return "True" if flag else "False"


def _lookup(values: dict[FieldRef, Value], ref: FieldRef) -> tuple[bool, Value]:
    """Case-insensitive lookup of a field in a values dict: (found, value)."""
    if ref in values:
        return True, values[ref]
    wanted = _norm(ref)
    for key, value in values.items():
        if _norm(key) == wanted:
            return True, value
    return False, None


def _as_text(value) -> Value:
    """Every value is a str in CSV form, or None for null (plan.md, "Rules for everyone")."""
    if value is None or isinstance(value, str):
        return value
    return str(value)


_DOTNET_TOKENS = {"yyyy": "%Y", "MM": "%m", "dd": "%d", "HH": "%H", "mm": "%M", "ss": "%S"}
_DOTNET_PATTERN = re.compile("yyyy|MM|dd|HH|mm|ss")


def _local_dotnet_to_strftime(dotnet_format: str) -> str:
    """Fallback converter for the .NET tokens yyyy MM dd HH mm ss; anything else is kept literally."""
    out: list[str] = []
    position = 0
    for match in _DOTNET_PATTERN.finditer(dotnet_format):
        out.append(dotnet_format[position:match.start()].replace("%", "%%"))
        out.append(_DOTNET_TOKENS[match.group()])
        position = match.end()
    out.append(dotnet_format[position:].replace("%", "%%"))
    return "".join(out)


def _dotnet_to_strftime(dotnet_format: str) -> str:
    """Convert a .NET date format (``FORMAT(GETUTCDATE(), 'yyyyMMdd_HHmm')``) to strftime.

    Uses ``sqlparse_lite.dotnet_to_strftime``; falls back to a tiny local converter while that
    module is not available.
    """
    try:
        from .sqlparse_lite import dotnet_to_strftime
    except ImportError:
        return _local_dotnet_to_strftime(dotnet_format)
    return dotnet_to_strftime(dotnet_format)


def case_paths(case: Case) -> list[list[str]]:
    """Activity keys of every full path of a case.

    A statistical case's ``steps`` stop at the random split; each random branch continues it.
    """
    base = [step.activity_key for step in case.steps]
    if case.random is not None and case.random.branches:
        return [base + [step.activity_key for step in branch.steps] for branch in case.random.branches]
    return [base]


def wait_precedes_manual_action(wait_key: str, case: Case) -> bool:
    """True when the case crosses the wait and later needs a manual action.

    Spec, "Dates": "Wait date before an engagement split | Wait-by-attribute on the path to an
    engagement split | Generation time plus 24 hours, leaving time to open the email". Read as: the
    case crosses the wait, and an engagement split where the case needs a manual action (open or
    click) comes after the wait on its path.
    """
    if not case.manual_actions:
        return False
    for keys in case_paths(case):
        if wait_key not in keys:
            continue
        after = keys[keys.index(wait_key) + 1:]
        if any(action.activity_key in after for action in case.manual_actions):
            return True
    return False


# ---------------------------------------------------------------------------
# The generator
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Rule:
    """One source of value for a field. ``via`` names the entry column a pushed-back rule comes from."""
    kind: str
    detail: object = None
    via: Optional[str] = None

    @property
    def priority(self) -> tuple[int, int]:
        return _PRIORITY[self.kind]

    def describe(self) -> str:
        name = _RULE_NAMES[self.kind]
        return f"{name} of entry column {self.via}" if self.via else name


@dataclass
class _Row:
    """Where a row stands: its number in its table, its scenario and, for contact rows, its contact."""
    number: int
    scenario: Scenario
    case: Optional[Case] = None
    contact_key: Optional[str] = None


class _Generator:
    def __init__(self, package: Package, model: TableModel, coverage: CoverageResult,
                 settings: Settings, generation_time: datetime):
        self.package = package
        self.model = model
        self.coverage = coverage
        self.settings = settings
        self.generation_time = generation_time
        self.warnings: list[str] = []
        self.placeholders: list[str] = []
        self._seen_messages: set[str] = set()
        self._placeholder_columns: set[tuple[str, str]] = set()
        self._rule_cache: dict[tuple[str, str], list[_Rule]] = {}
        self._row_index: dict[str, dict[str, dict[str, Value]]] = {}
        self._other_keys: dict[tuple[int, str], str] = {}
        self._contact_email: dict[str, str] = {}
        self._active_scenario: Optional[Scenario] = None

        self._entry = _find_table(package.tables, model.entry_table)
        if self._entry is None:
            self._warn(f"The entry table {model.entry_table} is not in the export, so it gets no rows.")
        self._check_settings()
        self._tables_plan = self._plan_tables()
        self._levels = {table.name.lower(): level for table, level in self._tables_plan}
        self._key_group_index = self._index_key_groups()
        self._group_owner = self._key_group_owners()
        self._wait_fields = self._index_wait_fields()
        self._split_sources = self._index_split_fields()
        self._filters = self._index_filters()
        self._one_active, self._activation_ref = self._resolve_activation()
        self._entry_plan: dict[str, object] = {}
        self._feeds: dict[tuple[str, str], list[str]] = {}
        self._build_entry_plan()

    # -- bookkeeping ------------------------------------------------------------------------

    def _warn(self, message: str) -> None:
        """Every judgement call becomes a warning, listed once."""
        if message not in self._seen_messages:
            self._seen_messages.add(message)
            self.warnings.append(message)

    def _note_placeholder(self, table: Table, field: Field, reason: str) -> None:
        """GeneratedData.placeholders: entry columns that got a placeholder, with the reason."""
        key = (table.name, field.name)
        if key not in self._placeholder_columns:
            self._placeholder_columns.add(key)
            self.placeholders.append(f"{table.name}.{field.name}: {reason}, so a placeholder is written.")

    def _table(self, name: str) -> Optional[Table]:
        return _find_table(self.package.tables, name)

    def _format_date(self, moment: datetime) -> str:
        """Dates in the CSVs follow ``Settings.date_format`` (spec settings: "Date format in the CSVs")."""
        return moment.strftime(self.settings.date_format)

    # -- setup ------------------------------------------------------------------------------

    def _check_settings(self) -> None:
        if "%" not in self.settings.date_format:
            self._warn(
                f"The date format {self.settings.date_format!r} has no strftime directive (such as %Y), "
                "so every date is written as that literal text."
            )

    def _plan_tables(self) -> list[tuple[Table, str]]:
        """The selected tables, in the order of the table model, with their level."""
        plan: list[tuple[Table, str]] = []
        for name in self.model.selected_tables:
            table = self._table(name)
            if table is None:
                self._warn(f"The selected table {name} is not in the export, so it gets no CSV.")
                continue
            plan.append((table, self._table_level(table)))
        if self._entry is not None and all(table is not self._entry for table, _ in plan):
            self._warn(f"The entry table {self._entry.name} is not among the selected tables, so it gets no CSV.")
        return plan

    def _table_level(self, table: Table) -> str:
        """Spec, "Classify fields by level": one row per contact, or one row shared by many contacts."""
        if table is self._entry:
            return LEVEL_CONTACT
        role = next((r for r in self.model.tables.values() if r.name.lower() == table.name.lower()), None)
        if role is not None and role.level in (LEVEL_CONTACT, LEVEL_SCENARIO):
            return role.level
        if table.name.lower() in {name.lower() for name in self.model.scenario_tables}:
            return LEVEL_SCENARIO
        if table.name.lower() not in {name.lower() for name in self.model.contact_tables}:
            self._warn(f"The level of table {table.name} is not known, so it gets one row per contact.")
        return LEVEL_CONTACT

    def _index_key_groups(self) -> dict[tuple[str, str], int]:
        index: dict[tuple[str, str], int] = {}
        for number, group in enumerate(self.model.key_groups):
            for ref in group.fields:
                index.setdefault(_norm(ref), number)
        return index

    def _key_group_owners(self) -> dict[int, str]:
        """An "other" key group holds one key per scenario when one of its tables is scenario-level,
        else one key per contact, so that the tables it links join row by row."""
        owners: dict[int, str] = {}
        for number, group in enumerate(self.model.key_groups):
            scenario_level = any(self._levels.get(ref[0].lower()) == LEVEL_SCENARIO for ref in group.fields)
            owners[number] = LEVEL_SCENARIO if scenario_level else LEVEL_CONTACT
        return owners

    def _index_wait_fields(self) -> dict[tuple[str, str], list[str]]:
        """Spec, "Dates": "Wait date | Field used by a wait-by-attribute"."""
        waits: dict[tuple[str, str], list[str]] = {}
        for activity in self.package.journey.activities.values():
            if activity.kind != KIND_WAIT_ATTRIBUTE:
                continue
            if activity.wait_field is None:
                self._warn(f"The wait by attribute {activity.key} names no date field, so no field is filled for it.")
                continue
            waits.setdefault(_norm(activity.wait_field), []).append(activity.key)
        return waits

    def _index_split_fields(self) -> dict[tuple[str, str], tuple[str, FieldRef]]:
        """Fields read by a split: the coverage's scenario-level and contact-level fields.

        A field that only a wait by attribute reads (no decision condition names it) follows the wait
        rule even when the coverage lists it, because the spec says that field "is filled according
        to the date settings".
        """
        condition_fields = {
            _norm((condition.table, condition.field))
            for activity in self.package.journey.activities.values()
            if activity.kind == KIND_DECISION
            for outcome in activity.outcomes
            for condition in formula_conditions(outcome.formula)
        }
        sources: dict[tuple[str, str], tuple[str, FieldRef]] = {}
        for level, refs in ((LEVEL_SCENARIO, self.coverage.scenario_fields),
                            (LEVEL_CONTACT, self.coverage.contact_fields)):
            for ref in refs:
                key = _norm(ref)
                if key in self._wait_fields and key not in condition_fields:
                    self._warn(
                        f"{ref[0]}.{ref[1]} is listed by the coverage but only a wait by attribute reads it, "
                        "so it is filled as a wait date."
                    )
                    continue
                sources.setdefault(key, (level, ref))
        return sources

    def _index_filters(self) -> dict[tuple[str, str], list[object]]:
        """Spec priority 3: "Field filtered by the entry query: a value that passes the filter"."""
        filters: dict[tuple[str, str], list[object]] = {}
        query = self.model.entry_query
        if query is None:
            return filters
        for flt in query.filters:
            if isinstance(flt, UnsupportedFilter):
                self._warn(
                    f"The entry query filter {flt.text!r} is not supported, so the generated rows may not "
                    "pass it and the contacts may not enter the journey."
                )
                continue
            resolved = self._resolve_column(flt.column)
            if resolved is None:
                self._warn(
                    f"The entry query filters on {flt.column.table or '?'}.{flt.column.column}, which matches "
                    "no field of a source table, so the filter is not applied to the generated rows."
                )
                continue
            table, field = resolved
            if table is self._entry:
                self._warn(
                    f"The entry query filters on the entry table itself ({table.name}.{field.name}); the generated "
                    "contacts are new, so the filter is not applied to the generated rows."
                )
                continue
            if table.name.lower() not in self._levels:
                self._warn(
                    f"The entry query filters on {table.name}.{field.name}, but {table.name} gets no CSV, "
                    "so the filter is not applied to the generated rows."
                )
                continue
            same_field = filters.setdefault(_norm((table.name, field.name)), [])
            if same_field and same_field[0] != flt:
                self._warn(
                    f"The entry query has several filters on {table.name}.{field.name}; only the first one "
                    "is used to choose its value."
                )
            same_field.append(flt)
        return filters

    def _resolve_activation(self) -> tuple[bool, Optional[FieldRef]]:
        on, ref, warnings = activation_setting(self.package, self.model, self.settings)
        for message in warnings:
            self._warn(message)
        return on, ref

    def _resolve_column(self, column: ColumnRef) -> Optional[tuple[Table, Field]]:
        """A query column as (table, field) with the schema spelling; unqualified columns are looked
        up in the entry query's source tables and must match exactly one of them."""
        if column.table:
            table = self._table(column.table)
            field = table.field(column.column) if table is not None else None
            return (table, field) if field is not None else None
        query = self.model.entry_query
        matches: list[tuple[Table, Field]] = []
        for source in (query.sources if query is not None else []):
            table = self._table(source.table)
            field = table.field(column.column) if table is not None else None
            if field is not None and all(t is not table for t, _ in matches):
                matches.append((table, field))
        return matches[0] if len(matches) == 1 else None

    def _build_entry_plan(self) -> None:
        """Map each entry column to the select expression that fills it (spec, "Table selection")."""
        query = self.model.entry_query
        entry = self._entry
        if query is None or entry is None:
            return
        if query.select_all:
            for field in _schema_fields(entry):
                for source in query.sources:
                    table = self._table(source.table)
                    source_field = table.field(field.name) if table is not None and table is not entry else None
                    if source_field is not None:
                        self._entry_plan[field.name] = SelectColumn(ColumnRef(table.name, source_field.name))
                        break
        else:
            ignored: list[str] = []
            for item in query.select:
                field = entry.field(item.target_column)
                if field is None:
                    ignored.append(item.target_column)
                    continue
                if field.name in self._entry_plan:
                    self._warn(
                        f"The entry query fills {entry.name}.{field.name} twice; the first expression is used."
                    )
                    continue
                self._entry_plan[field.name] = item.expr
            if ignored:
                self._warn(
                    f"The entry query selects columns that {entry.name} does not have, so they are ignored: "
                    + ", ".join(ignored) + "."
                )
        for column, expr in self._entry_plan.items():
            if not isinstance(expr, SelectColumn):
                continue
            resolved = self._resolve_column(expr.source)
            if resolved is not None and resolved[0] is not entry:
                source_table, source_field = resolved
                self._feeds.setdefault(_norm((source_table.name, source_field.name)), []).append(column)

    # -- rules ------------------------------------------------------------------------------

    def _own_rules(self, table: Table, field: Field) -> list[_Rule]:
        """The rules that apply to a field by itself, in the spec's priority order."""
        ref = _norm((table.name, field.name))
        rules: list[_Rule] = []
        if ref in self._key_group_index:
            rules.append(_Rule("key", self._key_group_index[ref]))
        if ref in self._split_sources:
            rules.append(_Rule("split", self._split_sources[ref]))
        if self._activation_ref is not None and ref == _norm(self._activation_ref):
            rules.append(_Rule("activation"))
        if ref in self._filters:
            rules.append(_Rule("filter", self._filters[ref][0]))
        if ref in self._wait_fields:
            rules.append(_Rule("wait", tuple(self._wait_fields[ref])))
        field_type = _field_type(field)
        if field_type == "emailaddress":
            rules.append(_Rule("email"))
        elif field_type == "phone":
            rules.append(_Rule("phone"))
        elif field_type == "date":
            rules.append(_Rule("date"))
        rules.append(_Rule("placeholder"))
        return sorted(rules, key=lambda rule: rule.priority)

    def _rules(self, table: Table, field: Field) -> list[_Rule]:
        """Own rules plus the requirements of the entry columns this field is selected into."""
        cache_key = (table.name, field.name)
        if cache_key in self._rule_cache:
            return self._rule_cache[cache_key]
        rules = self._own_rules(table, field)
        if table is not self._entry and self._entry is not None:
            for column in self._feeds.get(_norm(cache_key), []):
                entry_field = self._entry.field(column)
                for rule in self._own_rules(self._entry, entry_field):
                    if rule.kind in _PUSHED_BACK_KINDS:
                        rules.append(_Rule(rule.kind, rule.detail, via=column))
        rules = sorted(rules, key=lambda rule: rule.priority)   # stable: own rules first on ties
        self._rule_cache[cache_key] = rules
        return rules

    def _field_value(self, table: Table, field: Field, row: _Row) -> Value:
        """The value of one field: the first rule, in priority order, that applies to this row."""
        rules = self._rules(table, field)
        for position, rule in enumerate(rules):
            value = self._rule_value(rule, table, field, row)
            if value is _SKIP:
                continue
            value = self._normalise(_as_text(value), table, field)
            if rule.kind == "key" and field.length and value and len(value) > field.length:
                self._warn(
                    f"The key {value} is longer than {table.name}.{field.name} ({field.length} characters); "
                    "it is not cut, so that the tables still join."
                )
            self._report_overridden(table, field, row, rule, value, rules[position + 1:])
            return value
        raise AssertionError("the placeholder rule always applies")

    def _report_overridden(self, table: Table, field: Field, row: _Row, chosen: _Rule,
                           value: Value, lower_rules: list[_Rule]) -> None:
        """Spec priority order: a higher rule wins; say so when a lower requirement is lost."""
        for rule in lower_rules:
            if rule.kind not in _REQUIREMENT_KINDS:
                continue
            if chosen.kind == "activation" and rule.kind == "filter":
                continue   # the activation value is the filter value of the active scenario
            if isinstance(rule.detail, IsNullFilter) and rule.detail.negated:
                if value is None or value == "":
                    self._warn(
                        f"{table.name}.{field.name} gets the {chosen.describe()} (empty on row {row.number}), so the "
                        "entry query filter IS NOT NULL on it is not met, following the spec's priority order."
                    )
                continue
            other = self._rule_value(rule, table, field, row)
            if other is _SKIP:
                continue
            other = self._normalise(_as_text(other), table, field)
            if other != value:
                self._warn(
                    f"{table.name}.{field.name} gets the {chosen.describe()} ({value!r} on row {row.number}) "
                    f"instead of the {rule.describe()} ({other!r}), following the spec's priority order."
                )

    def _rule_value(self, rule: _Rule, table: Table, field: Field, row: _Row) -> object:
        """The value a rule gives on this row, or _SKIP when the rule does not apply to it."""
        kind = rule.kind
        if kind == "key":
            return self._key_value(rule.detail, table, field, row)
        if kind == "split":
            return self._split_value(rule.detail, row)
        if kind == "activation":
            return "True" if row.scenario is self._active_scenario else "False"
        if kind == "filter":
            return self._filter_value(rule.detail)
        if kind == "wait":
            return self._wait_value(rule.detail, row)
        if kind == "email":
            return self._email_value(table, field, row)
        if kind == "phone":
            return self.settings.fake_phone
        if kind == "date":
            return self._format_date(self.generation_time)
        return self._placeholder(table, field, row.number)

    def _fallback_value(self, table: Table, field: Field, row: _Row) -> Value:
        """Placeholder by type for a field whose own value cannot be computed (rules 4 and 5)."""
        for rule in self._own_rules(table, field):
            if rule.kind in ("wait", "email", "phone", "date", "placeholder"):
                value = self._rule_value(rule, table, field, row)
                if value is not _SKIP:
                    return self._normalise(_as_text(value), table, field)
        return self._placeholder(table, field, row.number)

    # -- rule 1: keys -----------------------------------------------------------------------

    def _key_value(self, group_number: int, table: Table, field: Field, row: _Row) -> object:
        """Spec: "Key or join field: generated key, identical in every table that joins on it".

        Contact keys go into the contact key group, scenario keys into the field that joins contacts
        to the scenario-level table, and any other join group gets ``TST_<run>_K<n>``.
        """
        group = self.model.key_groups[group_number]
        if group.kind == "contact":
            if row.contact_key is None:
                self._warn(
                    f"{table.name}.{field.name} should hold the contact key, but {table.name} has one row per "
                    "scenario, so it is filled by the lower-priority rules."
                )
                return _SKIP
            return row.contact_key
        if group.kind == "scenario":
            return row.scenario.key
        if self._group_owner[group_number] == LEVEL_SCENARIO or row.contact_key is None:
            return self._other_key(group_number, row.scenario.key)
        return self._other_key(group_number, row.contact_key)

    def _other_key(self, group_number: int, owner: str) -> str:
        """``TST_<run>_K<n>``: one key per scenario or per contact, shared by every field of the group."""
        slot = (group_number, owner)
        if slot not in self._other_keys:
            self._other_keys[slot] = f"TST_{self.settings.run_id}_K{len(self._other_keys) + 1:04d}"
        return self._other_keys[slot]

    # -- rule 2: split values ---------------------------------------------------------------

    def _split_value(self, source: tuple[str, FieldRef], row: _Row) -> object:
        """Spec: "Field read by a split: the value the case requires, written exactly as in the
        condition (same letter case)". Scenario-level fields come from ``Scenario.values``,
        contact-level ones from ``Case.contact_values``; None means an empty cell."""
        level, ref = source
        if level == LEVEL_SCENARIO:
            found, value = _lookup(row.scenario.values, ref)
            if not found:
                self._warn(f"The coverage gives no value for {ref[0]}.{ref[1]} in scenario {row.scenario.id}, "
                           "so the lower-priority rules fill it.")
                return _SKIP
            return value
        if row.case is not None:
            found, value = _lookup(row.case.contact_values, ref)
            if not found:
                self._warn(f"The coverage gives no value for {ref[0]}.{ref[1]} in case {row.case.id}, "
                           "so the lower-priority rules fill it.")
                return _SKIP
            return value
        # A row shared by the whole scenario holds a contact-level field: its cases must agree.
        values = [value for case in row.scenario.cases for found, value in [_lookup(case.contact_values, ref)] if found]
        if not values:
            return _SKIP
        if len(set(values)) > 1:
            self._warn(
                f"{ref[0]}.{ref[1]} is read per contact, but its row is shared by scenario {row.scenario.id}, "
                f"whose cases need different values; the value of the first case ({values[0]!r}) is written."
            )
        return values[0]

    # -- rule 3: entry query filters --------------------------------------------------------

    def _filter_value(self, flt: object) -> object:
        """Spec priority 3 and "Dates": an equality filter gets its literal; a date-range filter gets
        the validity window ("Starts yesterday, ends in 7 days" by default); IS NULL gets an empty cell."""
        if isinstance(flt, EqualityFilter):
            return flt.value
        if isinstance(flt, DateBoundFilter):
            days = self.settings.window_start_days if flt.bound == "start" else self.settings.window_end_days
            return self._format_date(self.generation_time + timedelta(days=days))
        if isinstance(flt, IsNullFilter):
            return _SKIP if flt.negated else None   # IS NOT NULL: any value of the lower rules passes
        return _SKIP

    # -- rule 4: wait dates, email, phone ---------------------------------------------------

    def _wait_value(self, wait_keys: tuple[str, ...], row: _Row) -> str:
        """Spec, "Dates": a wait date is the generation time plus the wait offset (default 0 hours, "so
        the wait ends at once"), or plus the offset before an engagement split (default 24 hours)
        when a case crosses the wait and later needs a manual action. A scenario-level field is decided
        over all the cases of its scenario, a contact-level field for the contact's own case."""
        cases = [row.case] if row.case is not None else list(row.scenario.cases)
        before_engagement = any(wait_precedes_manual_action(key, case) for case in cases for key in wait_keys)
        hours = (self.settings.wait_offset_before_engagement_hours if before_engagement
                 else self.settings.wait_offset_hours)
        return self._format_date(self.generation_time + timedelta(hours=hours))

    def _email_value(self, table: Table, field: Field, row: _Row) -> str:
        """Spec, "Email": the contact's address (see ``_build_contacts``)."""
        if row.contact_key is not None:
            return self._contact_email[row.contact_key]
        self._warn(
            f"{table.name}.{field.name} is an email field in a table with one row per scenario, so it gets the "
            f"undeliverable address <scenario key>@{UNDELIVERABLE_DOMAIN}."
        )
        return f"{row.scenario.key}@{UNDELIVERABLE_DOMAIN}"

    # -- rule 5: placeholders ---------------------------------------------------------------

    def _placeholder(self, table: Table, field: Field, number: int) -> str:
        """Spec: "Placeholder by type: text TST_<field>_<n> cut to the field length, Boolean set to its
        default or false"; plan.md adds Date -> generation time, Number/Decimal -> n, Locale -> en-US.
        ``n`` is the row number in the table, starting at 1."""
        field_type = _field_type(field)
        if field_type == "boolean":
            return boolean_text(field.default) or "False"
        if field_type in ("number", "decimal"):
            return str(number)
        if field_type == "locale":
            return LOCALE_PLACEHOLDER
        if field_type == "date":
            return self._format_date(self.generation_time)
        if field_type not in ("text", "emailaddress", "phone"):
            self._warn(f"{table.name}.{field.name} has the unknown type {field.type!r}, so it gets a text placeholder.")
        if field_type == "text" and field.name.lower().startswith("email"):
            self._warn(
                f"{table.name}.{field.name} is a Text field named like an email address; only EmailAddress fields get "
                "addresses, so it gets a text placeholder."
            )
        text = f"TST_{field.name}_{number}"
        return text[:field.length] if field.length else text

    def _normalise(self, value: Value, table: Table, field: Field) -> Value:
        """Spec file format: "True/False for Booleans"."""
        if value is None or _field_type(field) != "boolean":
            return value
        boolean = boolean_text(value)
        if boolean is None:
            self._warn(f"{table.name}.{field.name} is Boolean but gets the value {value!r}, written as given.")
            return value
        return boolean

    # -- keys and contacts ------------------------------------------------------------------

    def _assign_keys(self, scenarios: list[Scenario]) -> None:
        """Spec, "Keys": scenario keys TST_<run>_S01..., contact keys TST_<run>_C0001... The contact number
        counts up over the whole run, scenarios in run order and cases in the order given."""
        number = 0
        for scenario in scenarios:
            scenario.key = self.settings.scenario_key(scenario.run_order)
            for case in scenario.cases:
                if case.contact_count <= 0:
                    self._warn(f"Case {case.id} asks for {case.contact_count} contacts, so it gets none.")
                keys = []
                for _ in range(max(case.contact_count, 0)):
                    number += 1
                    keys.append(self.settings.contact_key(number))
                case.contact_keys = keys
        scenario_keys = [scenario.key for scenario in scenarios]
        if len(set(scenario_keys)) != len(scenario_keys):
            self._warn("Two scenarios have the same run order, so they share a scenario key.")
        self._allocate_other_keys(scenarios)

    def _allocate_other_keys(self, scenarios: list[Scenario]) -> None:
        """Number the "other" group keys in a predictable order: group by group, then by owner."""
        for number, group in enumerate(self.model.key_groups):
            if group.kind in ("contact", "scenario"):
                continue
            if not any(ref[0].lower() in self._levels for ref in group.fields):
                continue
            for scenario in scenarios:
                if self._group_owner[number] == LEVEL_SCENARIO:
                    self._other_key(number, scenario.key)
                    continue
                for case in scenario.cases:
                    for key in case.contact_keys:
                        self._other_key(number, key)

    def _real_inbox(self) -> Optional[tuple[str, str]]:
        """The tester's real inbox as (local part, domain), or None when it is empty or unusable."""
        inbox = (self.settings.real_inbox or "").strip()
        if not inbox:
            return None
        local, at, domain = inbox.rpartition("@")
        if not at or not local or not domain or " " in inbox:
            self._warn(
                f"The real inbox {inbox!r} is not an address of the form name@domain, so it is not used and "
                "every contact gets an undeliverable address."
            )
            return None
        return local, domain

    def _uses_real_phone(self, case: Case) -> bool:
        """Hook for the spec's real phone rule ("In each case whose path sends a message to a phone, one
        of the 3 contacts gets the tester's real number"). No supported activity type sends to a phone,
        so no contact uses the real number."""
        return False

    def _build_contacts(self, scenarios: list[Scenario]) -> list[Contact]:
        """Spec, "Email": "Contacts that must open or click get the tester's real inbox with
        plus-addressing, for example name+TST_C0042@domain. All other contacts get an undeliverable
        address, <contact key>@example.invalid." A contact must open or click when its case has a
        manual action; with no real inbox, it gets the undeliverable address too."""
        inbox = self._real_inbox()
        contacts: list[Contact] = []
        manual_without_inbox = 0
        for scenario in scenarios:
            for case in scenario.cases:
                real = bool(case.manual_actions) and inbox is not None
                if case.manual_actions and inbox is None:
                    manual_without_inbox += 1
                for key in case.contact_keys:
                    email = f"{inbox[0]}+{key}@{inbox[1]}" if real else f"{key}@{UNDELIVERABLE_DOMAIN}"
                    self._contact_email[key] = email
                    contacts.append(Contact(key=key, case_id=case.id, scenario_id=scenario.id,
                                            uses_real_inbox=real, uses_real_phone=self._uses_real_phone(case),
                                            email=email))
        if manual_without_inbox:
            self._warn(
                f"No real inbox is set, so the contacts of the {manual_without_inbox} case(s) that need an open "
                f"or a click get undeliverable addresses (@{UNDELIVERABLE_DOMAIN})."
            )
        return contacts

    def _check_engagement_waits(self, scenarios: list[Scenario]) -> None:
        """Spec, "Dates": the wait before an engagement split leaves the tester time to open the email.
        Warn when no wait by attribute lies between the email and the split on a case's path."""
        activities = self.package.journey.activities
        for scenario in scenarios:
            for case in scenario.cases:
                for action in case.manual_actions:
                    if not self._has_wait_before(case, action, activities):
                        self._warn(
                            f"Case {case.id}: no wait by attribute lies between the email {action.email_name!r} "
                            f"and the engagement split {action.activity_key}, so the tester may not have time to "
                            f"{action.kind} the email before the split is evaluated."
                        )

    @staticmethod
    def _has_wait_before(case: Case, action: ManualAction, activities: dict) -> bool:
        for keys in case_paths(case):
            if action.activity_key not in keys:
                continue
            end = keys.index(action.activity_key)
            start = keys.index(action.email_activity_key) if action.email_activity_key in keys[:end] else -1
            if any(activities.get(key) is not None and activities[key].kind == KIND_WAIT_ATTRIBUTE
                   for key in keys[start + 1:end]):
                return True
        return False

    # -- rows -------------------------------------------------------------------------------

    def run(self) -> GeneratedData:
        scenarios = sorted(self.coverage.scenarios, key=lambda s: (s.run_order, s.id))
        self._assign_keys(scenarios)
        contacts = self._build_contacts(scenarios)
        self._active_scenario = scenarios[0] if (self._one_active and scenarios) else None
        self._check_engagement_waits(scenarios)

        contact_rows = self._contact_contexts(scenarios)
        scenario_rows = [_Row(number, scenario) for number, scenario in enumerate(scenarios, 1)]
        rows_by_table: dict[str, list[dict[str, Value]]] = {}
        for table, level in self._tables_plan:
            if table is self._entry:
                continue
            contexts = scenario_rows if level == LEVEL_SCENARIO else contact_rows
            rows = [self._generic_row(table, context) for context in contexts]
            rows_by_table[table.name] = rows
            self._index_rows(table, level, contexts, rows)
        if self._entry is not None and any(table is self._entry for table, _ in self._tables_plan):
            rows_by_table[self._entry.name] = self._entry_rows(contact_rows)

        tables = {
            table.name: TableData(table=table.name, columns=[f.name for f in _schema_fields(table)],
                                  rows=rows_by_table[table.name])
            for table, _ in self._tables_plan
        }
        return GeneratedData(tables=tables, contacts=contacts, scenarios_rows=self._scenario_rows(scenarios),
                             placeholders=self.placeholders, warnings=self.warnings)

    @staticmethod
    def _contact_contexts(scenarios: list[Scenario]) -> list[_Row]:
        """Spec, "Table selection" and plan.md: one row per contact, contacts in key order."""
        contexts: list[_Row] = []
        for scenario in scenarios:
            for case in scenario.cases:
                for key in case.contact_keys:
                    contexts.append(_Row(len(contexts) + 1, scenario, case, key))
        return contexts

    def _generic_row(self, table: Table, row: _Row) -> dict[str, Value]:
        return {field.name: self._field_value(table, field, row) for field in _schema_fields(table)}

    def _index_rows(self, table: Table, level: str, contexts: list[_Row], rows: list[dict[str, Value]]) -> None:
        index = self._row_index.setdefault(table.name.lower(), {})
        for context, row in zip(contexts, rows):
            owner = context.scenario.key if level == LEVEL_SCENARIO else context.contact_key
            index[owner] = row

    def _joined_rows(self, row: _Row) -> dict[str, dict[str, Value]]:
        """The source rows that join for one contact: its own row in each contact-level table and its
        scenario's row in each scenario-level table."""
        joined: dict[str, dict[str, Value]] = {}
        for table_name, index in self._row_index.items():
            owner = row.scenario.key if self._levels.get(table_name) == LEVEL_SCENARIO else row.contact_key
            if owner in index:
                joined[table_name] = index[owner]
        return joined

    # -- the entry table --------------------------------------------------------------------

    def _entry_rows(self, contexts: list[_Row]) -> list[dict[str, Value]]:
        """Spec, "Table selection": "The entry CSV is kept consistent with the source CSVs: its rows are
        what the entry query would produce from them." Without an entry query, the entry table is
        filled by the general rules like any contact-level table."""
        entry = self._entry
        if self.model.entry_query is None:
            self._warn(
                f"No entry query fills {entry.name}, so its rows are generated by the general rules, like any "
                "contact-level table, and nothing guarantees that they match the source tables."
            )
            return [self._generic_row(entry, context) for context in contexts]
        rows: list[dict[str, Value]] = []
        for context in contexts:
            sources = self._joined_rows(context)
            rows.append({field.name: self._entry_value(entry, field, context, sources)
                         for field in _schema_fields(entry)})
        return rows

    def _entry_value(self, entry: Table, field: Field, row: _Row, sources: dict[str, dict[str, Value]]) -> Value:
        expr = self._entry_plan.get(field.name)
        if expr is None:
            return self._entry_absent_value(entry, field, row)
        value, problem = self._evaluate(expr, sources)
        if problem is not None:
            self._note_placeholder(entry, field, problem)
            return self._fallback_value(entry, field, row)
        value = self._normalise(_as_text(value), entry, field)
        self._check_entry_requirements(entry, field, row, value)
        return value

    def _evaluate(self, expr: object, sources: dict[str, dict[str, Value]]) -> tuple[Value, Optional[str]]:
        """Spec, "Table selection": "simple select expressions (column, literal, CONCAT, current date)";
        "Anything more complex is reported, and the affected entry column gets a placeholder".
        Returns (value, problem); a problem means the column gets a placeholder."""
        if isinstance(expr, SelectColumn):
            return self._column_value(expr.source, sources)
        if isinstance(expr, SelectLiteral):
            return expr.value, None
        if isinstance(expr, SelectCurrentDate):
            return self._current_date(expr.format)
        if isinstance(expr, SelectConcat):
            parts: list[str] = []
            for part in expr.parts:
                value, problem = self._evaluate(part, sources)
                if problem is not None:
                    return None, problem
                parts.append(value or "")   # T-SQL CONCAT turns NULL into an empty string
            return "".join(parts), None
        if isinstance(expr, SelectUnsupported):
            return None, f"the entry query fills it with the unsupported expression {expr.text!r}"
        return None, f"the entry query fills it with an expression the generator does not know ({expr!r})"

    def _column_value(self, column: ColumnRef, sources: dict[str, dict[str, Value]]) -> tuple[Value, Optional[str]]:
        resolved = self._resolve_column(column)
        if resolved is None:
            return None, (f"the entry query copies {column.table or '?'}.{column.column}, which matches no field "
                          "of a source table")
        table, field = resolved
        if table is self._entry:
            return None, f"the entry query reads the entry table itself ({table.name}.{field.name})"
        source_row = sources.get(table.name.lower())
        if source_row is None:
            return None, f"the entry query copies {table.name}.{field.name}, but {table.name} has no generated row"
        return source_row.get(field.name), None

    def _current_date(self, dotnet_format: Optional[str]) -> tuple[Value, Optional[str]]:
        """``GETDATE()`` and friends: the generation time, in ``Settings.date_format`` for a plain date
        or in the query's own format for ``FORMAT(GETUTCDATE(), '...')``."""
        if dotnet_format is None:
            return self._format_date(self.generation_time), None
        try:
            pattern = _dotnet_to_strftime(dotnet_format)
        except (ValueError, KeyError) as error:
            return None, f"the date format {dotnet_format!r} of the entry query cannot be converted ({error})"
        return self.generation_time.strftime(pattern), None

    def _entry_absent_value(self, entry: Table, field: Field, row: _Row) -> Value:
        """Entry columns the query does not fill get what the query would produce: the schema default,
        else an empty cell when nullable, else a placeholder (listed in ``placeholders``). A key column
        is the exception: priority 1 says it holds the generated key, so that the tables join."""
        rules = self._own_rules(entry, field)
        if rules[0].kind == "key":
            value = self._rule_value(rules[0], entry, field, row)
            if value is not _SKIP:
                self._warn(
                    f"{entry.name}.{field.name} is a key field but the entry query does not fill it; the generated "
                    "key is written so that the tables join."
                )
                return _as_text(value)
        if any(rule.kind == "split" for rule in rules):
            self._warn(
                f"{entry.name}.{field.name} is read by a split but the entry query does not fill it, so the entry "
                "row gets what the query would produce (its default or an empty cell), not the case's value."
            )
        default = self._default_value(entry, field)
        if default is not None:
            return default
        if field.is_nullable:
            return None
        self._note_placeholder(entry, field, "the entry query does not fill it, it is not nullable and has no default")
        return self._fallback_value(entry, field, row)

    def _default_value(self, table: Table, field: Field) -> Value:
        """The schema default as a CSV value: Booleans as True/False, GETDATE() as the generation time."""
        default = field.default
        if default is None or not default.strip():
            return None
        if default.strip().lower().replace(" ", "") in _CURRENT_DATE_DEFAULTS:
            return self._format_date(self.generation_time)
        return self._normalise(default, table, field)

    def _check_entry_requirements(self, entry: Table, field: Field, row: _Row, value: Value) -> None:
        """Warn when the value the entry query produces differs from what the entry column needs."""
        for rule in self._own_rules(entry, field):
            if rule.kind not in ("key", "split", "activation", "wait"):
                continue
            required = self._rule_value(rule, entry, field, row)
            if required is _SKIP:
                continue
            required = self._normalise(_as_text(required), entry, field)
            if required != value:
                self._warn(
                    f"The entry query fills {entry.name}.{field.name} with {value!r} (row {row.number}) but the "
                    f"{rule.describe()} is {required!r}; the entry row keeps what the query produces."
                )
            return   # only the highest requirement counts

    # -- scenarios.csv ----------------------------------------------------------------------

    def _scenario_rows(self, scenarios: list[Scenario]) -> list[dict[str, Value]]:
        """Spec, "Outputs": "scenarios.csv: One row per scenario: its key, its scenario-level values, run
        order, what to activate". Under one active scenario at a time, only the first is "yes"."""
        rows: list[dict[str, Value]] = []
        for scenario in scenarios:
            keys = [key for case in scenario.cases for key in case.contact_keys]
            active = not self._one_active or scenario is self._active_scenario
            row: dict[str, Value] = {
                "scenario_key": scenario.key,
                "run_order": str(scenario.run_order),
                "has_manual_action": _bool_text(scenario.has_manual_action),
                "is_statistical": _bool_text(scenario.is_statistical),
                "case_count": str(len(scenario.cases)),
                "contact_count": str(len(keys)),
                "first_contact_key": keys[0] if keys else None,
                "last_contact_key": keys[-1] if keys else None,
                "activate": "yes" if active else "no",
            }
            for ref in self.coverage.scenario_fields:
                column, value = self._scenario_field(ref, scenario)
                row[column] = value
            rows.append(row)
        return rows

    def _scenario_field(self, ref: FieldRef, scenario: Scenario) -> tuple[str, Value]:
        """A scenario-level value for scenarios.csv, named ``Table.Field`` in the schema spelling."""
        found, value = _lookup(scenario.values, ref)
        value = _as_text(value) if found else None
        table = self._table(ref[0])
        field = table.field(ref[1]) if table is not None else None
        if field is None:
            return f"{ref[0]}.{ref[1]}", value
        return f"{table.name}.{field.name}", self._normalise(value, table, field)
