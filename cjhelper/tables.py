"""Table selection and field levels: ``build_table_model(package) -> TableModel``.

Spec rules implemented here (docs/spec.md):

- "Table selection": "A table gets a CSV when something reads it; tables that are only
  written to are skipped." The roles, as the spec defines them:

  - entry table: "The table bound to the journey's entry trigger";
  - split table: "Any table named in a split condition or in a wait-by-attribute";
  - source table: "Any table in the FROM or JOIN of a query that fills the entry table,
    followed back until no query writes it";
  - written-only table: "Target of an update contact step or of a query, never read by a
    split or by the entry query": no CSV.

- "Journey model and coverage", step 3: "A field is contact-level when its table has one row
  per contact (joined to the entry on the contact key). It is scenario-level when many contacts
  share one row (joined on any other field)."

- "Data generation rules", "Keys": a key is "identical in every table that joins on it", and
  scenario keys are "written into the field that joins contacts to the scenario-level table".
  The fields that must hold the same key are grouped in ``KeyGroup`` objects.

- "One scenario at a time": the activation field is "suggested from the entry query filters".

The SQL is read through ``sqlparse_lite.parse_query``; this module only looks at the parsed form.
Every decision is explained in ``TableRole.reason`` or in ``TableModel.warnings``, in plain words.
The parser warnings of the queries followed are repeated in ``TableModel.warnings``, prefixed
with the query name.

Readings of the spec that are not spelled out there (each is visible in a reason or a warning):

- ``ROLE_WRITTEN`` is the spec's "written-only" role: a table that is read keeps only its
  reading roles, and its reason says it is also written.
- A selected table that is not joined to the entry is scenario-level: one row shared by all
  contacts (warning).
- A table joined to the entry on the contact key is contact-level even when it is also joined to
  a scenario-level table: the contact key link wins.
- A group-to-set relationship (the contact model pointing at a table) links a field that holds
  the contact key (``model.Relationship``), so that field joins the contact key's group.
- A plain column copied by a followed query (``SELECT M.ContactId`` into the entry table) holds the
  same value as its source on every row, so it carries the source's key, and the other way round.
- Contact key: when the entry table has no sendable field, no contact link and no primary key,
  its first field is used (warning).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from . import sqlparse_lite
from .model import (
    KIND_WAIT_ATTRIBUTE,
    LEVEL_CONTACT,
    LEVEL_SCENARIO,
    ROLE_ENTRY,
    ROLE_SOURCE,
    ROLE_SPLIT,
    ROLE_WRITTEN,
    ColumnRef,
    EqualityFilter,
    FieldRef,
    KeyGroup,
    Package,
    ParsedQuery,
    Query,
    SelectColumn,
    Table,
    TableModel,
    TableRole,
    formula_conditions,
)

# KeyGroup.kind values.
GROUP_CONTACT = "contact"
GROUP_SCENARIO = "scenario"
GROUP_OTHER = "other"

# A table with one of these roles is read by the journey, so it gets a CSV.
READING_ROLES = frozenset({ROLE_ENTRY, ROLE_SPLIT, ROLE_SOURCE})

NO_ROLE_REASON = "Not read or written by this journey."


def build_table_model(package: Package) -> TableModel:
    """Apply the table selection rule, group the key fields and classify tables and fields by level.

    Steps, in order:

    1. the entry table and the query that fills it (the entry query);
    2. who reads each table (splits, waits by attribute, the queries followed back from the entry
       query) and who writes it (update contact steps, queries);
    3. roles and selection: the entry, split and source tables get a CSV, the others do not;
    4. the contact key field, then the key groups;
    5. the level of each selected table, then the kind of each key group, then the level of each field;
    6. the activation field suggested from the entry query filters.
    """
    warnings: list[str] = []
    names = _Names(package.tables)
    entry = _entry_table(package, names)

    automation_queries = _entry_automation_queries(package, warnings)
    parse = _Parser(package, warnings)
    entry_queries = _find_entry_queries(package, entry, automation_queries, names, warnings)
    entry_query = _choose_entry_query(entry_queries, entry, parse, names, warnings)
    entry_parsed = parse(entry_query) if entry_query else None

    uses = {name: _Use() for name in package.tables}
    _record_split_reads(package, names, uses, warnings)
    source_queries = _follow_sources(package, entry, entry_query, entry_queries, parse, automation_queries,
                                     names, uses, warnings)
    _record_writes(package, names, uses)

    order = _table_order(package.tables, entry)
    roles = {name: _roles(name, entry, uses[name]) for name in order}
    selected = [name for name in order if roles[name] & READING_ROLES]

    contact_key = _contact_key_field(package, entry, names, warnings)
    keys = _link_keys(contact_key, package, source_queries, names, warnings)
    levels, level_reasons = _table_levels(entry, selected, package.tables, keys, contact_key, warnings)
    key_groups = _key_groups(keys, contact_key, levels, entry, selected, package.tables)
    field_levels = _field_levels(selected, package.tables, levels, key_groups, entry, entry_parsed, names)
    activation, activation_note = _activation_field(entry_parsed, levels, names, warnings)

    entry_query_name = entry_query.name if entry_query else None
    table_roles: dict[str, TableRole] = {}
    for name in order:
        is_selected = name in selected
        if is_selected:
            note = activation_note if activation and activation[0] == name else ""
            reason = _selected_reason(roles[name], uses[name], entry_query_name,
                                      levels[name], level_reasons[name], note)
        elif ROLE_WRITTEN in roles[name]:
            reason = f"Written by {_writers_text(uses[name])}, never read by a split or by the entry query: no CSV."
        else:
            reason = NO_ROLE_REASON
        table_roles[name] = TableRole(name=name, roles=roles[name], selected=is_selected,
                                      level=levels.get(name), reason=reason)

    return TableModel(
        entry_table=entry,
        contact_key_field=contact_key,
        tables=table_roles,
        key_groups=key_groups,
        field_levels=field_levels,
        entry_query=entry_parsed,
        source_queries=source_queries,
        scenario_tables=[name for name in selected if levels[name] == LEVEL_SCENARIO],
        contact_tables=[name for name in selected if levels[name] == LEVEL_CONTACT],
        activation_field=activation,
        warnings=list(dict.fromkeys(warnings)),
    )


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------

class _Names:
    """Case-insensitive lookup of tables and fields.

    SQL, split criteria and schemas do not always agree on letter case (the pilot's entry query
    writes ``C.active`` for the schema's ``ACTIVE``). The model keeps the schema spelling.
    """

    def __init__(self, tables: dict[str, Table]):
        self.tables = tables
        self._by_lower = {name.lower(): name for name in tables}

    def table(self, name: Optional[str]) -> Optional[str]:
        """The schema spelling of a table name, or None when the export has no such table."""
        if not name:
            return None
        return self._by_lower.get(name.lower())

    def field_ref(self, table: Optional[str], field_name: Optional[str]) -> Optional[FieldRef]:
        """``(table, field)`` in the schema spelling, or None when either is unknown."""
        table_name = self.table(table)
        if table_name is None or not field_name:
            return None
        found = self.tables[table_name].field(field_name)
        return (table_name, found.name) if found else None

    def why_unknown(self, table: Optional[str], field_name: Optional[str]) -> str:
        """Plain words saying why ``field_ref`` found nothing."""
        if not table:
            return f"the table of column {field_name} is not known"
        if self.table(table) is None:
            return f"table {table} is not in the export"
        return f"{self.table(table)} has no field {field_name}"


def _table_order(tables: dict[str, Table], entry: str) -> list[str]:
    """Entry table first, then the others by name: a stable order for the report and the CSVs."""
    others = sorted((name for name in tables if name != entry), key=lambda name: (name.lower(), name))
    return [entry] + others


# ---------------------------------------------------------------------------
# Entry table and entry query
# ---------------------------------------------------------------------------

def _entry_table(package: Package, names: _Names) -> str:
    """Spec, entry table: "The table bound to the journey's entry trigger" (``Journey.entry_table``).

    loader.py refuses an export without one, so a missing entry table here is a programming error.
    """
    entry = names.table(package.journey.entry_table)
    if entry is None:
        raise ValueError(f"the journey's entry table {package.journey.entry_table!r} "
                         "is not among the tables of the export")
    return entry


def _entry_automation_queries(package: Package, warnings: list[str]) -> list[Query]:
    """The queries run by the automation that feeds the entry event, in step order."""
    automation = package.entry_event.automation_name if package.entry_event else None
    if not automation:
        return []
    by_name: dict[str, Query] = {}
    for query in package.queries:
        by_name.setdefault(query.name, query)
    out: list[Query] = []
    for name in package.automation_queries.get(automation, []):
        query = by_name.get(name)
        if query is None:
            warnings.append(f"The entry automation {automation} runs query {name}, which is not in the export")
        elif query not in out:
            out.append(query)
    return out


def _find_entry_queries(package: Package, entry: str, automation_queries: list[Query], names: _Names,
                        warnings: list[str]) -> list[Query]:
    """Every query that fills the entry table (contract in docs/plan.md, "tables.py").

    Spec, source table: "Any table in the FROM or JOIN of a query that fills the entry table", so
    all of them count, not only the last. They are the queries of the entry automation whose target
    is the entry table, in step order. When the automation has none, every query of the export that
    fills the entry table is taken (warning). When no query fills the entry table there is no entry
    query (warning), and the entry table alone is the source side.
    """
    in_automation = [q for q in automation_queries if names.table(q.target_table) == entry]
    if in_automation:
        return in_automation

    if package.entry_event is None:
        why = "The journey has no entry event"
    elif not package.entry_event.automation_name:
        why = f"The entry event {package.entry_event.name} is not fed by an automation"
    else:
        why = f"No query of the entry automation {package.entry_event.automation_name} fills the entry table {entry}"
    elsewhere = [q for q in package.queries if names.table(q.target_table) == entry]
    if not elsewhere:
        warnings.append(f"{why}, and no other query of the export fills {entry}: there is no entry query, "
                        "so the entry table alone is the source side")
    elif len(elsewhere) == 1:
        warnings.append(f"{why}; query {elsewhere[0].name} fills {entry} and is taken as the entry query")
    else:
        warnings.append(f"{why}; the queries of the export that fill {entry} are taken as entry queries")
    return elsewhere


def _choose_entry_query(entry_queries: list[Query], entry: str, parse: "_Parser", names: _Names,
                        warnings: list[str]) -> Optional[Query]:
    """The one entry query that builds the entry rows: the last query in step order.

    When several queries fill the entry table (warning), the tables read by all of them are source
    tables, but the entry rows come from one query. A last query that reads only the entry table
    (a post-processing update of the entry rows) is not the one that builds them: the last query that
    reads some other table is taken instead.
    """
    if not entry_queries:
        return None
    chosen = entry_queries[-1]
    if len(entry_queries) == 1:
        return chosen
    reading_others = [q for q in entry_queries if any(names.table(ref.table) != entry for ref in parse(q).sources)]
    if reading_others:
        chosen = reading_others[-1]
    how = "the last one in step order" if chosen is entry_queries[-1] else \
        f"the last one that reads a table other than {entry}"
    warnings.append(f"Several queries fill the entry table {entry} ({_join_words([q.name for q in entry_queries])}): "
                    f"the tables they read are all source tables, and the entry rows are built from "
                    f"{chosen.name}, {how}")
    return chosen


class _Parser:
    """Parse each query once; its parser warnings are repeated in the table model, prefixed with the
    query name."""

    def __init__(self, package: Package, warnings: list[str]):
        self.package = package
        self.warnings = warnings
        self._done: dict[str, ParsedQuery] = {}

    def __call__(self, query: Query) -> ParsedQuery:
        if query.name not in self._done:
            self._done[query.name] = _parse(query, self.package, self.warnings)
        return self._done[query.name]


def _parse(query: Query, package: Package, warnings: list[str]) -> ParsedQuery:
    """Parse one query; its parser warnings are repeated here, prefixed with the query name."""
    parsed = sqlparse_lite.parse_query(query, package.tables)
    warnings.extend(f"Query {query.name}: {warning}" for warning in parsed.warnings)
    return parsed


# ---------------------------------------------------------------------------
# Who reads and who writes each table
# ---------------------------------------------------------------------------

@dataclass
class _Use:
    """Who reads and who writes one table: the facts behind its roles and its reason."""
    splits: list[str] = field(default_factory=list)              # decision splits naming it in a condition
    waits: list[str] = field(default_factory=list)               # waits by attribute on one of its fields
    read_by_query: Optional[str] = None                          # the followed query that first read it
    query_fills: Optional[str] = None                            # the table that query fills
    update_steps: list[str] = field(default_factory=list)        # update contact steps writing it
    written_by_queries: list[str] = field(default_factory=list)  # queries whose target it is


def _record_split_reads(package: Package, names: _Names, uses: dict[str, _Use], warnings: list[str]) -> None:
    """Spec, split table: "Any table named in a split condition or in a wait-by-attribute".

    The tables come from every condition of every decision outcome formula and from the date
    field of every wait-by-attribute. A table or field that is not in the export is reported.
    """
    reads: list[tuple[str, bool, str, str]] = []   # (activity key, is a wait, table, field) as written
    for activity in package.journey.activities.values():
        for outcome in activity.outcomes:
            for condition in formula_conditions(outcome.formula):
                reads.append((activity.key, False, condition.table, condition.field))
        if activity.kind == KIND_WAIT_ATTRIBUTE and activity.wait_field:
            reads.append((activity.key, True, activity.wait_field[0], activity.wait_field[1]))

    unknown_tables: dict[str, list[str]] = {}
    unknown_fields: dict[str, list[str]] = {}
    for activity_key, is_wait, table_name, field_name in reads:
        table = names.table(table_name)
        if table is None:
            _add_once(unknown_tables.setdefault(table_name, []), activity_key)
            continue
        _add_once(uses[table].waits if is_wait else uses[table].splits, activity_key)
        if names.field_ref(table, field_name) is None:
            _add_once(unknown_fields.setdefault(f"{table}.{field_name}", []), activity_key)
    for table_name, keys in unknown_tables.items():
        warnings.append(f"Table {table_name} is read by {_short_list(keys)} but is not in the export: "
                        "no CSV can be made for it")
    for ref_text, keys in unknown_fields.items():
        warnings.append(f"{ref_text} is read by {_short_list(keys)} but is not a field of the export")


def _follow_sources(package: Package, entry: str, entry_query: Optional[Query], entry_queries: list[Query],
                    parse: _Parser, automation_queries: list[Query], names: _Names, uses: dict[str, _Use],
                    warnings: list[str]) -> list[ParsedQuery]:
    """Spec, source table: "Any table in the FROM or JOIN of a query that fills the entry table,
    followed back until no query writes it".

    Breadth-first from the FROM/JOIN tables of every query that fills the entry table (the entry
    query first, then the others in step order). For each new source table, every query whose
    target it is gets parsed and its own FROM/JOIN tables are followed in turn: the queries of the
    entry automation first (step order), then the other queries of the export.
    Each table and each query is followed once, and the walk starts at the entry table, which is
    therefore never a source: cycles stop (the pilot has a query that writes its Config table from
    Config and the entry table).

    Returns the parsed queries followed, the entry query first.
    """
    if entry_query is None:
        return []
    search_order = automation_queries + [q for q in package.queries if q not in automation_queries]
    starting = [entry_query] + [q for q in entry_queries if q is not entry_query]
    followed = [parse(q) for q in starting]
    done_queries = {q.name for q in starting}
    done_tables = {entry}
    pending = deque((ref.table, parsed) for parsed in followed for ref in parsed.sources)
    while pending:
        table_name, reader = pending.popleft()
        table = names.table(table_name)
        if table is None:
            warnings.append(f"Query {reader.name} reads table {table_name}, which is not in the export: "
                            "no CSV can be made for it")
            continue
        if table in done_tables:
            continue
        done_tables.add(table)
        uses[table].read_by_query = reader.name
        uses[table].query_fills = names.table(reader.target_table) or reader.target_table
        for query in search_order:
            if query.name in done_queries or names.table(query.target_table) != table:
                continue
            done_queries.add(query.name)
            parsed = parse(query)
            followed.append(parsed)
            pending.extend((ref.table, parsed) for ref in parsed.sources)
    return followed


def _record_writes(package: Package, names: _Names, uses: dict[str, _Use]) -> None:
    """Who writes each table: update contact steps (``Activity.writes``) and queries (their target).

    A write to a table that is not in the export is left out: loader.py already reports the
    unresolved reference, and a table that is only written gets no CSV anyway.
    """
    for activity in package.journey.activities.values():
        for write in activity.writes:
            table = names.table(write.table)
            if table is not None:
                _add_once(uses[table].update_steps, activity.key)
    for query in package.queries:
        table = names.table(query.target_table)
        if table is not None:
            _add_once(uses[table].written_by_queries, query.name)


def _roles(name: str, entry: str, use: _Use) -> set[str]:
    """Spec "Table selection": entry, split and source tables are read; a table that is only
    written is the spec's "written-only table" (``ROLE_WRITTEN``). A table that is read and also
    written keeps its reading roles only; its reason says it is also written."""
    roles: set[str] = set()
    if name == entry:
        roles.add(ROLE_ENTRY)
    if use.splits or use.waits:
        roles.add(ROLE_SPLIT)
    if use.read_by_query:
        roles.add(ROLE_SOURCE)
    if not roles and (use.update_steps or use.written_by_queries):
        roles.add(ROLE_WRITTEN)
    return roles


# ---------------------------------------------------------------------------
# Contact key and key groups
# ---------------------------------------------------------------------------

def _contact_key_field(package: Package, entry: str, names: _Names, warnings: list[str]) -> FieldRef:
    """The entry table's field that holds the contact key (spec "Keys": contact keys TST_C0001...).

    In this order (contract in docs/plan.md): the entry table's sendable field
    (``sendableCustomObjectField``); the field a group-to-set relationship links to the contact on
    the entry table; a single-field primary key; the first primary key field. Every fallback is
    reported. With no primary key at all the first field is used (assumption, reported).
    """
    table = package.tables[entry]
    if table.sendable_field:
        found = table.field(table.sendable_field)
        if found:
            return (entry, found.name)
        warnings.append(f"The sendable field {table.sendable_field} of the entry table {entry} is not in its schema")
    for rel in package.relationships:
        if rel.left_table is None and names.table(rel.right_table) == entry:
            found = table.field(rel.right_field)
            if found:
                warnings.append(f"The entry table {entry} has no usable sendable field: the contact key is "
                                f"{found.name}, the field relationship {rel.name} links to the contact")
                return (entry, found.name)
    primary_key = table.primary_key
    if len(primary_key) == 1:
        warnings.append(f"The entry table {entry} has no usable sendable field and no contact link: "
                        f"the contact key is its primary key {primary_key[0]}")
        return (entry, primary_key[0])
    if primary_key:
        warnings.append(f"The entry table {entry} has no usable sendable field and no contact link, and its "
                        f"primary key has several fields ({_join_words(primary_key)}): the contact key is "
                        f"taken to be the first one, {primary_key[0]}")
        return (entry, primary_key[0])
    if table.fields:
        warnings.append(f"The entry table {entry} has no usable sendable field, no contact link and no primary "
                        f"key: the contact key is taken to be its first field, {table.fields[0].name} (assumption)")
        return (entry, table.fields[0].name)
    raise ValueError(f"the entry table {entry} has no fields")


class _KeyUnion:
    """Union-find over fields: fields linked by an equality end in the same group."""

    def __init__(self) -> None:
        self._parent: dict[FieldRef, FieldRef] = {}

    def __contains__(self, ref: FieldRef) -> bool:
        return ref in self._parent

    def add(self, ref: FieldRef) -> None:
        self._parent.setdefault(ref, ref)

    def find(self, ref: FieldRef) -> FieldRef:
        while self._parent[ref] != ref:
            ref = self._parent[ref]
        return ref

    def union(self, a: FieldRef, b: FieldRef) -> None:
        self.add(a)
        self.add(b)
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self._parent[root_b] = root_a

    def same(self, a: FieldRef, b: FieldRef) -> bool:
        return a in self and b in self and self.find(a) == self.find(b)

    def groups(self) -> list[list[FieldRef]]:
        """Every group, its members in the order they were first linked."""
        by_root: dict[FieldRef, list[FieldRef]] = {}
        for ref in self._parent:
            by_root.setdefault(self.find(ref), []).append(ref)
        return list(by_root.values())


def _link_keys(contact_key: FieldRef, package: Package, source_queries: list[ParsedQuery], names: _Names,
               warnings: list[str]) -> _KeyUnion:
    """Group the fields that must hold the same generated key (spec "Keys": a key is "identical in
    every table that joins on it").

    Links, in this order:

    1. the join equalities of the followed queries (``JOIN ... ON a = b``) and the relationships
       between two tables (contract in docs/plan.md);
    2. the contact model's own links (group-to-set relationships): ``model.Relationship`` says their
       field holds the contact key, so it joins the contact key's group;
    3. the plain columns the followed queries copy (``SELECT M.ContactId`` into the entry table): the
       copy holds the same value as its source on every row, so it joins the source's key group, or
       the source joins the copy's. A copy where neither side is a key is left out, so ordinary
       copied columns (email, phone) never become keys.

    The contact key field is always in a group, even when nothing joins on it.
    """
    keys = _KeyUnion()
    keys.add(contact_key)
    for left, right in _join_links(package, source_queries, names, warnings):
        if left != right:   # a field equal to itself links nothing
            keys.union(left, right)
    for ref in _contact_links(package, names, warnings):
        keys.union(contact_key, ref)
    copies = _select_copies(source_queries, names)
    changed = True
    while changed:   # repeated so that keys also flow through a chain of queries
        changed = False
        for source, target in copies:
            if (source in keys or target in keys) and not keys.same(source, target):
                keys.union(source, target)
                changed = True
    return keys


def _join_links(package: Package, source_queries: list[ParsedQuery], names: _Names,
                warnings: list[str]) -> list[tuple[FieldRef, FieldRef]]:
    """Join equalities of the followed queries, then relationships between two tables, both sides in
    the schema spelling. A side that cannot be resolved skips that link, with a warning."""
    links: list[tuple[FieldRef, FieldRef]] = []
    for parsed in source_queries:
        for join in parsed.joins:
            what = f"Query {parsed.name}: join {_column_text(join.left)} = {_column_text(join.right)}"
            link = _resolve_link(names, (join.left.table, join.left.column),
                                 (join.right.table, join.right.column), what, warnings)
            if link:
                links.append(link)
    for rel in package.relationships:
        if rel.left_table is None:
            continue   # group-to-set: see _contact_links
        link = _resolve_link(names, (rel.left_table, rel.left_field), (rel.right_table, rel.right_field),
                             f"Relationship {rel.name}", warnings)
        if link:
            links.append(link)
    return links


def _resolve_link(names: _Names, left: tuple[Optional[str], Optional[str]], right: tuple[Optional[str], Optional[str]],
                  what: str, warnings: list[str]) -> Optional[tuple[FieldRef, FieldRef]]:
    left_ref = names.field_ref(*left)
    right_ref = names.field_ref(*right)
    if left_ref is None or right_ref is None:
        problem = names.why_unknown(*left) if left_ref is None else names.why_unknown(*right)
        warnings.append(f"{what} is skipped: {problem}")
        return None
    return left_ref, right_ref


def _contact_links(package: Package, names: _Names, warnings: list[str]) -> list[FieldRef]:
    """Fields the contact model links to the contact (group-to-set relationships, ``left_table`` None)."""
    out: list[FieldRef] = []
    for rel in package.relationships:
        if rel.left_table is not None:
            continue
        ref = names.field_ref(rel.right_table, rel.right_field)
        if ref is None:
            problem = names.why_unknown(rel.right_table, rel.right_field)
            warnings.append(f"Relationship {rel.name} is skipped: {problem}")
            continue
        out.append(ref)
    return out


def _select_copies(source_queries: list[ParsedQuery], names: _Names) -> list[tuple[FieldRef, FieldRef]]:
    """``(source column, target column)`` for every plain column in the SELECT of the followed queries.

    Columns the target table does not have (the pilot's entry query selects ``FirstName``, which the
    entry table lacks) and columns that cannot be resolved are left out.
    """
    out: list[tuple[FieldRef, FieldRef]] = []
    for parsed in source_queries:
        for item in parsed.select:
            if not isinstance(item.expr, SelectColumn):
                continue
            source = names.field_ref(item.expr.source.table, item.expr.source.column)
            target = names.field_ref(parsed.target_table, item.target_column)
            if source is not None and target is not None and source != target:
                out.append((source, target))
    return out


# ---------------------------------------------------------------------------
# Levels
# ---------------------------------------------------------------------------

def _table_levels(entry: str, selected: list[str], tables: dict[str, Table], keys: _KeyUnion,
                  contact_key: FieldRef, warnings: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    """Spec step 3: "A field is contact-level when its table has one row per contact (joined to the
    entry on the contact key). It is scenario-level when many contacts share one row (joined on any
    other field)."

    - The entry table is contact-level.
    - A selected table holding a field of the contact key's group is joined to the entry on the
      contact key: contact-level. This link wins over any other, so a table joined on the contact key
      stays contact-level even when it is also joined to a scenario-level table (the pilot's Target is
      joined to Master on the contact key and to Config on the campaign name).
    - Breadth-first from the contact-level tables over the other key groups (two tables are neighbours
      when they hold fields of the same group): a table first reached this way is joined on another
      field, so it is scenario-level; the neighbours of a scenario-level table are scenario-level too.
    - A selected table never reached is not joined to the entry at all: scenario-level, with a warning
      (assumption: one row shared by all contacts).

    Only selected tables get a level, but the groups were built over every table, so a link that
    passes through a table without a CSV still counts.

    Returns the level of each selected table and the plain-words reason for it.
    """
    members = _group_members(keys, selected, tables)
    contact_root = keys.find(contact_key)
    levels = {entry: LEVEL_CONTACT}
    reasons = {entry: "it is the entry table, one row per contact"}
    for table, field_name in members.get(contact_root, {}).items():
        if table not in levels:
            levels[table] = LEVEL_CONTACT
            reasons[table] = f"joined to the entry on the contact key ({table}.{field_name})"

    queue = deque(name for name in selected if name in levels)
    while queue:
        current = queue.popleft()
        for root, tables_in_group in members.items():
            if root == contact_root or current not in tables_in_group:
                continue
            for other, other_field in tables_in_group.items():
                if other in levels:
                    continue
                levels[other] = LEVEL_SCENARIO
                reasons[other] = (f"joined on {current}.{tables_in_group[current]} = {other}.{other_field}, "
                                  "not on the contact key, so many contacts share one row")
                queue.append(other)

    for name in selected:
        if name not in levels:
            levels[name] = LEVEL_SCENARIO
            reasons[name] = "not joined to the entry: treated as one row shared by all contacts (assumption)"
            warnings.append(f"Table {name} is not joined to the entry: treated as one row shared by all contacts "
                            "(scenario-level). This is an assumption: check how the journey links this table")
    return levels, reasons


def _group_members(keys: _KeyUnion, selected: list[str], tables: dict[str, Table]) -> dict[FieldRef, dict[str, str]]:
    """For each key group (by its root): the selected tables holding one of its fields, each with the
    first such field in schema order."""
    members: dict[FieldRef, dict[str, str]] = {}
    for name in selected:
        for f in tables[name].fields:
            ref = (name, f.name)
            if ref in keys:
                members.setdefault(keys.find(ref), {}).setdefault(name, f.name)
    return members


def _key_groups(keys: _KeyUnion, contact_key: FieldRef, levels: dict[str, str], entry: str, selected: list[str],
                tables: dict[str, Table]) -> list[KeyGroup]:
    """Spec "Keys". The contact key's group is kind "contact" (contact keys TST_C0001...). A group
    holding a field of a scenario-level table is kind "scenario": it is the field that joins contacts
    to the scenario-level table (scenario keys TST_S01...). The other groups are kind "other".

    Fields of tables without a CSV stay in their group; a group with no field of a selected table is
    left out, since no CSV holds it. Order: contact group, scenario groups, other groups; inside a
    group, the entry table first (its contact key field before its other fields), then tables with a
    CSV, then the others, by name and schema order. So the first field of a table in a group is the
    one that holds that group's key for the table.
    """
    contact_root = keys.find(contact_key)
    selected_set = set(selected)

    def sort_key(ref: FieldRef) -> tuple:
        table, field_name = ref
        return (table != entry, ref != contact_key, table not in selected_set, table.lower(), table,
                tables[table].field_names.index(field_name))

    groups: list[KeyGroup] = []
    for refs in keys.groups():
        if not any(table in selected_set for table, _ in refs):
            continue
        if keys.find(refs[0]) == contact_root:
            kind = GROUP_CONTACT
        elif any(levels.get(table) == LEVEL_SCENARIO for table, _ in refs):
            kind = GROUP_SCENARIO
        else:
            kind = GROUP_OTHER
        groups.append(KeyGroup(kind=kind, fields=sorted(refs, key=sort_key)))
    kind_order = {GROUP_CONTACT: 0, GROUP_SCENARIO: 1, GROUP_OTHER: 2}
    groups.sort(key=lambda group: (kind_order[group.kind], sort_key(group.fields[0])))
    return groups


def _field_levels(selected: list[str], tables: dict[str, Table], levels: dict[str, str],
                  key_groups: list[KeyGroup], entry: Optional[str] = None,
                  entry_parsed: Optional[ParsedQuery] = None, names=None) -> dict[FieldRef, str]:
    """Every field of every selected table takes its table's level, except the fields of a
    contact-level table that belong to a scenario key group: they hold the scenario key (the pilot's
    Target.Description and the entry table's CampaignName), so they are scenario-level. An entry
    column that the entry query copies from a scenario-level column is scenario-level too: every
    contact of the scenario gets the same value."""
    scenario_key_fields = {ref for group in key_groups if group.kind == GROUP_SCENARIO for ref in group.fields}
    out: dict[FieldRef, str] = {}
    for name in selected:
        for f in tables[name].fields:
            ref = (name, f.name)
            level = levels[name]
            if level == LEVEL_CONTACT and ref in scenario_key_fields:
                level = LEVEL_SCENARIO
            out[ref] = level
    if entry is not None and entry_parsed is not None and names is not None and entry in tables:
        for item in entry_parsed.select:
            if not isinstance(item.expr, SelectColumn):
                continue
            target = tables[entry].field(item.target_column)
            source = names.field_ref(item.expr.source.table, item.expr.source.column)
            if target is None or source is None:
                continue
            if levels.get(source[0]) == LEVEL_SCENARIO:
                out[(entry, target.name)] = LEVEL_SCENARIO
    return out


# ---------------------------------------------------------------------------
# Activation field
# ---------------------------------------------------------------------------

def _activation_field(entry_parsed: Optional[ParsedQuery], levels: dict[str, str], names: _Names,
                      warnings: list[str]) -> tuple[Optional[FieldRef], str]:
    """Spec "One scenario at a time": the activation field is "suggested from the entry query filters
    (ACTIVE in the pilot)".

    The suggestion is the first equality filter of the entry query on a Boolean field (per schema) of
    a scenario-level table whose value is true, e.g. ``C.active = 'True'``. Returns the field in the
    schema spelling, or None, and a sentence for the table's reason.
    """
    if entry_parsed is None:
        return None, ""
    candidates: list[tuple[FieldRef, str]] = []
    for flt in entry_parsed.filters:
        if not isinstance(flt, EqualityFilter):
            continue
        ref = names.field_ref(flt.column.table, flt.column.column)
        if ref is None or levels.get(ref[0]) != LEVEL_SCENARIO:
            continue
        if names.tables[ref[0]].field(ref[1]).type.lower() != "boolean":
            continue
        if flt.value.strip().lower() not in ("true", "1"):
            continue
        candidates.append((ref, f"{flt.column.column} = '{flt.value}'"))
    if not candidates:
        return None, ""
    ref, filter_text = candidates[0]
    if len(candidates) > 1:
        others = [f"{table}.{field_name}" for (table, field_name), _ in candidates[1:]]
        warnings.append(f"Several entry query filters could be the activation field: {ref[0]}.{ref[1]} is "
                        f"suggested (the first one), not {_join_words(others)}")
    return ref, f"Its field {ref[1]} is suggested as the activation field (entry query filter {filter_text})."


# ---------------------------------------------------------------------------
# Reasons and small text helpers
# ---------------------------------------------------------------------------

def _selected_reason(roles: set[str], use: _Use, entry_query_name: Optional[str], level: str,
                     level_reason: str, activation_note: str) -> str:
    """Plain words for a table that gets a CSV: who reads it, who else writes it, and its level."""
    reads = _reads_text(use, entry_query_name)
    if ROLE_ENTRY in roles:
        if entry_query_name:
            text = f"Entry table of the journey, filled by the entry query {entry_query_name}"
        else:
            text = "Entry table of the journey, filled by no query of the export"
        if reads:
            text += f"; also read by {_join_words(reads)}"
        writers = _writers_text(use, skip_query=entry_query_name)
    else:
        text = f"Read by {_join_words(reads)}"
        writers = _writers_text(use)
    if writers:
        text += f"; also written by {writers}"
    level_name = "Contact-level" if level == LEVEL_CONTACT else "Scenario-level"
    parts = [f"{text}.", f"{level_name}: {level_reason}."]
    if activation_note:
        parts.append(activation_note)
    return " ".join(parts)


def _reads_text(use: _Use, entry_query_name: Optional[str]) -> list[str]:
    phrases: list[str] = []
    if use.splits:
        phrases.append(_count(len(use.splits), "split"))
    if use.waits:
        phrases.append(_count(len(use.waits), "wait by attribute", "waits by attribute"))
    if use.read_by_query:
        if use.read_by_query == entry_query_name:
            phrases.append(f"the entry query {use.read_by_query}")
        else:
            phrases.append(f"query {use.read_by_query}, which fills {use.query_fills}")
    return phrases


def _writers_text(use: _Use, skip_query: Optional[str] = None) -> str:
    phrases: list[str] = []
    if use.update_steps:
        phrases.append(_count(len(use.update_steps), "update contact step"))
    queries = [name for name in use.written_by_queries if name != skip_query]
    if queries:
        phrases.append(("query " if len(queries) == 1 else "queries ") + _join_words(queries))
    return _join_words(phrases)


def _add_once(items: list[str], item: str) -> None:
    if item not in items:
        items.append(item)


def _join_words(items: list[str]) -> str:
    """``a``, ``a and b``, ``a, b and c``."""
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _short_list(items: list[str], limit: int = 5) -> str:
    if len(items) <= limit:
        return _join_words(items)
    return ", ".join(items[:limit]) + f" and {len(items) - limit} more"


def _count(n: int, singular: str, plural: Optional[str] = None) -> str:
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


def _column_text(ref: ColumnRef) -> str:
    return f"{ref.table}.{ref.column}" if ref.table else ref.column
