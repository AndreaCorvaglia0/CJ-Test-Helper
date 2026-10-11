"""Trust checks: the generator reads the written files back and proves they are right.

Spec, "Development priorities", the meaning of "trusted":

1. Every value respects the type, length, nullability and primary key of its schema.
2. Every key joins: each contact row finds its scenario row and its rows in the linked tables.
3. Each generated contact, simulated again through the journey from the written values,
   takes exactly the path it was created for.
4. Every reachable branch is crossed by at least one case, and every branch not covered is
   listed with its reason.
5. The same JSON and settings give the same data.

Plus the acceptance rule on addresses: contacts needing an open or click use the real inbox,
all others use ``@example.invalid``. The files are read with the standard ``csv`` module, not
with the writer's helpers, so a writer bug cannot hide from the checks.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Optional

from . import graph
from .model import (
    KIND_ENGAGEMENT,
    KIND_RANDOM,
    STATUS_NOT_COVERED,
    Case,
    CheckResult,
    CoverageResult,
    DateBoundFilter,
    EqualityFilter,
    FieldRef,
    GeneratedData,
    IsNullFilter,
    Package,
    ParsedQuery,
    SelectColumn,
    SelectConcat,
    SelectCurrentDate,
    SelectLiteral,
    SelectUnsupported,
    Settings,
    Step,
    TableModel,
    UnsupportedFilter,
    Value,
)

MAX_DETAILS = 25


def read_csv_bytes(data: bytes) -> tuple[list[str], list[dict[str, Value]]]:
    """Header and rows; empty cells become None (the CSV convention for null)."""
    text = data.decode("utf-8")
    reader = csv.reader(io.StringIO(text, newline=""))
    rows = list(reader)
    if not rows:
        return [], []
    header = rows[0]
    out: list[dict[str, Value]] = []
    for r in rows[1:]:
        if not r:
            continue
        out.append({h: (v if v != "" else None) for h, v in zip(header, r)})
    return header, out


def _trim(details: list[str]) -> list[str]:
    if len(details) <= MAX_DETAILS:
        return details
    return details[:MAX_DETAILS] + [f"... and {len(details) - MAX_DETAILS} more"]


def _parse_date(value: str, date_format: str) -> Optional[datetime]:
    for fmt in (date_format, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


class Checker:
    def __init__(self, package: Package, table_model: TableModel, coverage: CoverageResult,
                 data: GeneratedData, files: dict[str, bytes], settings: Settings, generation_time: datetime):
        self.package = package
        self.table_model = table_model
        self.coverage = coverage
        self.data = data
        self.files = files
        self.settings = settings
        self.now = generation_time
        self.schema = graph.Schema(package.tables)
        self.csv: dict[str, tuple[list[str], list[dict[str, Value]]]] = {}
        for name in table_model.selected_tables:
            content = files.get(f"{name}.csv")
            self.csv[name] = read_csv_bytes(content) if content is not None else ([], [])

    def run_all(self) -> list[CheckResult]:
        return [
            self.check_schema(),
            self.check_joins(),
            self.check_entry_query(),
            self.check_simulation(),
            self.check_coverage(),
            self.check_addresses(),
        ]

    # 1 ---------------------------------------------------------------------------------
    def check_schema(self) -> CheckResult:
        details: list[str] = []
        for name in self.table_model.selected_tables:
            table = self.package.tables.get(name)
            header, rows = self.csv[name]
            if table is None:
                details.append(f"{name}: no schema in the export")
                continue
            if not header:
                details.append(f"{name}.csv is missing or empty")
                continue
            if header != table.field_names:
                details.append(f"{name}.csv header {header} differs from the schema {table.field_names}")
                continue
            pk_fields = table.primary_key
            seen_pk: set[tuple] = set()
            for i, row in enumerate(rows, start=2):
                for f in table.fields:
                    v = row.get(f.name)
                    if v is None:
                        if not f.is_nullable:
                            details.append(f"{name}.csv line {i}: {f.name} is empty but not nullable")
                        continue
                    if f.length is not None and f.type in ("Text", "EmailAddress", "Phone", "Locale") and len(v) > f.length:
                        details.append(f"{name}.csv line {i}: {f.name} has {len(v)} characters, schema allows {f.length}")
                    if f.type == "Boolean" and v not in ("True", "False"):
                        details.append(f"{name}.csv line {i}: {f.name} = {v!r} is not True/False")
                    elif f.type == "Date" and _parse_date(v, self.settings.date_format) is None:
                        details.append(f"{name}.csv line {i}: {f.name} = {v!r} is not a date in {self.settings.date_format}")
                    elif f.type == "Number":
                        try:
                            int(v)
                        except ValueError:
                            details.append(f"{name}.csv line {i}: {f.name} = {v!r} is not a whole number")
                    elif f.type == "Decimal":
                        try:
                            float(v)
                        except ValueError:
                            details.append(f"{name}.csv line {i}: {f.name} = {v!r} is not a number")
                    elif f.type == "EmailAddress" and ("@" not in v or " " in v):
                        details.append(f"{name}.csv line {i}: {f.name} = {v!r} is not an email address")
                    elif f.type == "Phone" and (" " in v or not v.replace("+", "").isdigit()):
                        details.append(f"{name}.csv line {i}: {f.name} = {v!r} is not a phone number")
                if pk_fields:
                    pk = tuple(row.get(f) for f in pk_fields)
                    if any(p is None for p in pk):
                        details.append(f"{name}.csv line {i}: primary key {pk_fields} has an empty part")
                    elif pk in seen_pk:
                        details.append(f"{name}.csv line {i}: duplicate primary key {pk}")
                    seen_pk.add(pk)
        return CheckResult("Values respect type, length, nullability and primary key", not details, _trim(details))

    # 2 ---------------------------------------------------------------------------------
    def _column_values(self, ref: FieldRef) -> Optional[set[Value]]:
        table, field_name = ref
        if table not in self.csv:
            return None
        header, rows = self.csv[table]
        if field_name not in header:
            return None
        return {r.get(field_name) for r in rows}

    def check_joins(self) -> CheckResult:
        details: list[str] = []
        entry = self.table_model.entry_table
        for group in self.table_model.key_groups:
            members = [f for f in group.fields if f[0] in self.csv]
            entry_members = [f for f in members if f[0] == entry]
            if not entry_members or len(members) < 2:
                continue
            entry_values = self._column_values(entry_members[0]) or set()
            for member in members:
                if member[0] == entry:
                    continue
                values = self._column_values(member)
                if values is None:
                    details.append(f"{member[0]}.{member[1]} is in a key group but not in the CSV")
                    continue
                missing = sorted(v for v in entry_values if v not in values and v is not None)
                if missing:
                    details.append(f"{len(missing)} {entry}.{entry_members[0][1]} values have no row in {member[0]}.{member[1]}: "
                                   + ", ".join(missing[:5]))
                if group.kind == "contact":
                    extra = sorted(v for v in values if v not in entry_values and v is not None)
                    if extra:
                        details.append(f"{len(extra)} {member[0]}.{member[1]} values have no entry row: " + ", ".join(extra[:5]))
        # Every contact of a case has a row in every contact-level table.
        for name in self.table_model.contact_tables:
            if name not in self.csv:
                continue
            key_field = self._contact_key_field(name)
            if key_field is None:
                continue
            values = self._column_values((name, key_field)) or set()
            for contact in self.data.contacts:
                if contact.key not in values:
                    details.append(f"contact {contact.key} has no row in {name}")
        return CheckResult("Every key joins across tables", not details, _trim(details))

    def _contact_key_field(self, table: str) -> Optional[str]:
        for group in self.table_model.key_groups:
            if group.kind == "contact":
                for t, f in group.fields:
                    if t == table:
                        return f
        return None

    def _scenario_key_field(self, table: str) -> Optional[str]:
        for group in self.table_model.key_groups:
            if group.kind == "scenario":
                for t, f in group.fields:
                    if t == table:
                        return f
        return None

    # 3 ---------------------------------------------------------------------------------
    def check_entry_query(self) -> CheckResult:
        query = self.table_model.entry_query
        entry = self.table_model.entry_table
        if query is None:
            return CheckResult("Entry rows match the entry query", True, ["no entry query in the export; nothing to compare"])
        if entry not in self.csv:
            return CheckResult("Entry rows match the entry query", False, [f"{entry}.csv is missing"])
        details: list[str] = []
        notes: list[str] = []
        joined = self._join_sources(query, details)
        if joined is None:
            return CheckResult("Entry rows match the entry query", False, _trim(details))
        activation = self.settings.activation_field or self.table_model.activation_field
        one_active = self.settings.one_active_scenario
        if one_active is None:
            one_active = activation is not None
        kept = []
        for combo in joined:
            ok = True
            for flt in query.filters:
                if isinstance(flt, UnsupportedFilter):
                    continue
                col = flt.column
                if one_active and activation is not None and col.table.lower() == activation[0].lower() \
                        and col.column.lower() == activation[1].lower():
                    continue   # only the first scenario is active; the others are activated later by the tester
                value = self._combo_value(combo, col)
                if isinstance(flt, EqualityFilter):
                    if not _sql_equal(value, flt.value):
                        ok = False
                elif isinstance(flt, IsNullFilter):
                    if (value is None) == flt.negated:
                        ok = False
                elif isinstance(flt, DateBoundFilter):
                    d = _parse_date(value, self.settings.date_format) if value else None
                    if d is None:
                        ok = False
                    elif flt.bound == "start" and not (self.now >= d):
                        ok = False
                    elif flt.bound == "end" and not (self.now <= d):
                        ok = False
            if ok:
                kept.append(combo)
        if any(isinstance(f, UnsupportedFilter) for f in query.filters):
            notes.append("some entry query filters are not understood and were not checked")
        if one_active and activation is not None:
            notes.append(f"the filter on the activation field {activation[0]}.{activation[1]} was not checked: only the first "
                         "scenario is active in the CSV and the tester activates the others one at a time")

        table = self.package.tables[entry]
        header, rows = self.csv[entry]
        pk = table.primary_key or table.field_names
        expected: dict[tuple, dict[str, Value]] = {}
        for combo in kept:
            row: dict[str, Value] = {}
            if query.select_all:
                for f in table.fields:
                    for src_table, src_row in combo.items():
                        if f.name in src_row:
                            row[f.name] = src_row[f.name]
            for item in query.select:
                f = table.field(item.target_column)
                if f is None:
                    continue
                value = self._select_value(item.expr, combo)
                if value is _SKIP:
                    continue
                row[f.name] = value
            key = tuple(row.get(p) for p in pk)
            expected[key] = row
        actual = {tuple(r.get(p) for p in pk): r for r in rows}
        for key in expected:
            if key not in actual:
                details.append(f"the entry query would produce a row with key {key} that is not in {entry}.csv")
        for key, row in actual.items():
            if key not in expected:
                details.append(f"{entry}.csv has a row with key {key} that the entry query would not produce")
                continue
            exp = expected[key]
            for col, v in exp.items():
                if row.get(col) != v:
                    details.append(f"{entry}.csv row {key}: {col} is {row.get(col)!r} but the entry query gives {v!r}")
            for f in table.fields:
                if f.name in exp:
                    continue
                v = row.get(f.name)
                allowed = {None}
                if f.default is not None:
                    allowed.add(_normalise_default(f, f.default))
                if v not in allowed and f.is_nullable:
                    details.append(f"{entry}.csv row {key}: {f.name} is {v!r} but the entry query does not fill it")
        return CheckResult("Entry rows match the entry query", not details, _trim(details) + notes)

    def _join_sources(self, query: ParsedQuery, details: list[str]) -> Optional[list[dict[str, dict[str, Value]]]]:
        """Nested-loop join of the source CSVs along the query's join equalities."""
        sources = [s.table for s in query.sources]
        for name in sources:
            if name not in self.csv:
                details.append(f"source table {name} has no CSV to join")
                return None
        combos: list[dict[str, dict[str, Value]]] = [{}]
        for name in sources:
            _, rows = self.csv[name]
            new_combos: list[dict[str, dict[str, Value]]] = []
            for combo in combos:
                for row in rows:
                    candidate = dict(combo)
                    candidate[name] = row
                    if self._joins_hold(query, candidate):
                        new_combos.append(candidate)
            combos = new_combos
        return combos

    def _joins_hold(self, query: ParsedQuery, combo: dict[str, dict[str, Value]]) -> bool:
        for join in query.joins:
            if join.left.table in combo and join.right.table in combo:
                if self._combo_value(combo, join.left) != self._combo_value(combo, join.right):
                    return False
        return True

    def _combo_value(self, combo: dict[str, dict[str, Value]], col) -> Value:
        row = combo.get(col.table)
        if row is None:
            for name, r in combo.items():
                table = self.package.tables.get(name)
                if table is not None and table.field(col.column) is not None:
                    row, col_table = r, name
                    return row.get(table.field(col.column).name)
            return None
        table = self.package.tables.get(col.table)
        f = table.field(col.column) if table is not None else None
        return row.get(f.name if f is not None else col.column)

    def _select_value(self, expr, combo):
        if isinstance(expr, SelectColumn):
            return self._combo_value(combo, expr.source)
        if isinstance(expr, SelectLiteral):
            return expr.value
        if isinstance(expr, SelectCurrentDate):
            if expr.format:
                from .sqlparse_lite import dotnet_to_strftime
                return self.now.strftime(dotnet_to_strftime(expr.format))
            return self.now.strftime(self.settings.date_format)
        if isinstance(expr, SelectConcat):
            parts = [self._select_value(p, combo) for p in expr.parts]
            if any(p is _SKIP for p in parts):
                return _SKIP
            return "".join("" if p is None else str(p) for p in parts)
        return _SKIP

    # 4 ---------------------------------------------------------------------------------
    def check_simulation(self) -> CheckResult:
        details: list[str] = []
        walker = graph.Walker(self.package.journey, self.schema, self.package.emails,
                              self.settings.case_insensitive_text, self.now, self.settings.date_format)
        cases = {c.id: c for c in self.coverage.cases}
        scenario_of = {s.id: s for s in self.coverage.scenarios}
        checked = 0
        for contact in self.data.contacts:
            case = cases.get(contact.case_id)
            scenario = scenario_of.get(contact.scenario_id)
            if case is None or scenario is None:
                details.append(f"contact {contact.key} belongs to an unknown case {contact.case_id}")
                continue
            lookup = self._contact_lookup(contact.key, scenario.key)
            if case.random is None:
                steps = self._simulate(walker, lookup, case, None)
                if steps != case.steps:
                    details.append(f"contact {contact.key} (case {case.id}) takes {_describe(steps)} instead of {_describe(case.steps)}")
                checked += 1
            else:
                for branch in case.random.branches:
                    steps = self._simulate(walker, lookup, case, branch.outcome_key)
                    expected = list(case.steps[:-1]) + [Step(case.random.activity_key, branch.outcome_key)] + list(branch.steps)
                    if steps != expected:
                        details.append(f"contact {contact.key} (case {case.id}, random outcome {branch.outcome_key}) takes "
                                       f"{_describe(steps)} instead of {_describe(expected)}")
                    checked += 1
        notes = [f"{checked} contact paths re-simulated from the written values"]
        return CheckResult("Every contact re-simulated from the files takes its intended path", not details, _trim(details) + notes)

    def _contact_lookup(self, contact_key: str, scenario_key: str):
        rows_by_ref: dict[str, dict[str, Value]] = {}
        for name in self.table_model.selected_tables:
            header, rows = self.csv[name]
            ckey = self._contact_key_field(name)
            skey = self._scenario_key_field(name)
            match = None
            for row in rows:
                if ckey is not None and row.get(ckey) != contact_key:
                    continue
                if skey is not None and row.get(skey) != scenario_key:
                    continue
                if ckey is None and skey is None:
                    continue
                match = row
                break
            if match is not None:
                rows_by_ref[name] = match

        def lookup(ref: FieldRef):
            row = rows_by_ref.get(ref[0])
            if row is None:
                return None
            return row.get(ref[1])
        return lookup

    def _simulate(self, walker: graph.Walker, lookup, case: Case, random_outcome: Optional[str]) -> list[Step]:
        manual_keys = {m.activity_key for m in case.manual_actions}

        def choose(activity, state):
            if activity.kind == KIND_ENGAGEMENT:
                want_yes = activity.key in manual_keys
                for o in activity.outcomes:
                    if o.when is want_yes:
                        return o
                return activity.outcomes[-1] if activity.outcomes else None
            if activity.kind == KIND_RANDOM:
                if case.random is not None and activity.key == case.random.activity_key and random_outcome is not None:
                    return activity.outcome(random_outcome)
                return activity.outcomes[0] if activity.outcomes else None
            return None

        state = walker.start()
        walker.run(state, lookup, choose)
        return list(state.steps)

    # 5 ---------------------------------------------------------------------------------
    def check_coverage(self) -> CheckResult:
        details: list[str] = []
        cases = {c.id: c for c in self.coverage.cases}
        crossed: set[tuple[str, str]] = set()
        for c in self.coverage.cases:
            crossed.update((s.activity_key, s.outcome_key) for s in c.steps if s.outcome_key is not None)
            if c.random is not None:
                for b in c.random.branches:
                    crossed.add((c.random.activity_key, b.outcome_key))
                    crossed.update((s.activity_key, s.outcome_key) for s in b.steps if s.outcome_key is not None)
        for b in self.coverage.branches:
            ref = (b.activity_key, b.outcome_key)
            if b.status == STATUS_NOT_COVERED:
                if not b.reason:
                    details.append(f"branch {ref} is not covered and has no reason")
                # Spec: with no real inbox the open/click cases still exist, but the branch is
                # reported as not covered; such a branch names its cases in covered_by.
                if ref in crossed and not b.covered_by:
                    details.append(f"branch {ref} is reported as not covered but a case crosses it")
            else:
                if not b.covered_by:
                    details.append(f"branch {ref} is reported as {b.status} but no case covers it")
                if ref not in crossed:
                    details.append(f"branch {ref} is reported as {b.status} but no case path crosses it")
                for cid in b.covered_by:
                    if cid not in cases:
                        details.append(f"branch {ref} names an unknown case {cid}")
        for c in self.coverage.cases:
            expected = self.settings.contacts_per_random_case if c.random is not None else self.settings.contacts_per_case
            if c.contact_count != expected:
                details.append(f"case {c.id} has {c.contact_count} contacts instead of {expected}")
            if len(c.contact_keys) != c.contact_count:
                details.append(f"case {c.id} lists {len(c.contact_keys)} contact keys for {c.contact_count} contacts")
        return CheckResult("Every reachable branch is covered and every uncovered branch has a reason", not details, _trim(details))

    # addresses -------------------------------------------------------------------------
    def check_addresses(self) -> CheckResult:
        details: list[str] = []
        real = self.settings.real_inbox.strip()
        for name in self.table_model.contact_tables:
            table = self.package.tables.get(name)
            if table is None or name not in self.csv:
                continue
            ckey = self._contact_key_field(name)
            email_fields = [f.name for f in table.fields if f.type == "EmailAddress"]
            if ckey is None or not email_fields:
                continue
            by_key = {c.key: c for c in self.data.contacts}
            _, rows = self.csv[name]
            for row in rows:
                contact = by_key.get(row.get(ckey))
                if contact is None:
                    continue
                for ef in email_fields:
                    v = row.get(ef) or ""
                    if contact.uses_real_inbox:
                        if not real or not (v.endswith("@" + real.split("@", 1)[1]) and f"+{contact.key}@" in v):
                            details.append(f"{name}: {contact.key} needs the real inbox but has {v!r}")
                    elif not v.endswith("@example.invalid"):
                        details.append(f"{name}: {contact.key} should be undeliverable but has {v!r}")
        return CheckResult("Only contacts with a manual action use the real inbox; all others are undeliverable", not details, _trim(details))


class _Skip:
    pass


_SKIP = _Skip()


def _sql_equal(value: Value, literal: str) -> bool:
    """SQL Server compares case-insensitively under the default collation; booleans accept true/1."""
    if value is None:
        return False
    a, b = value.strip().lower(), literal.strip().lower()
    truthy = {"true": "1", "false": "0"}
    return a == b or truthy.get(a, a) == truthy.get(b, b)


def _normalise_default(f, default: str) -> Value:
    if f.type == "Boolean":
        low = default.strip().lower()
        if low in ("true", "1"):
            return "True"
        if low in ("false", "0"):
            return "False"
    return default


def _describe(steps: list[Step]) -> str:
    return " > ".join(f"{s.activity_key}/{s.outcome_key}" if s.outcome_key else s.activity_key for s in steps)


def check_determinism(first: dict[str, bytes], second: dict[str, bytes]) -> CheckResult:
    """Spec: the same JSON and settings give the same data (the generation time is held fixed)."""
    details: list[str] = []
    for name in sorted(set(first) | set(second)):
        if name not in first or name not in second:
            details.append(f"{name} is produced by only one of the two runs")
        elif first[name] != second[name]:
            details.append(f"{name} differs between two runs with the same input")
    return CheckResult("Two runs with the same input give the same files", not details, details)


def run_checks(package: Package, table_model: TableModel, coverage: CoverageResult, data: GeneratedData,
               files: dict[str, bytes], settings: Settings, generation_time: datetime) -> list[CheckResult]:
    return Checker(package, table_model, coverage, data, files, settings, generation_time).run_all()
