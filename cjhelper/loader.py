"""Read a Salesforce Marketing Cloud package export into a ``Package``.

Spec, "Input: the package export": "The only input is the JSON file exported from
Package Manager, which already contains everything the generator needs." This module
reads, from ``entities``: ``journeys``, ``eventDefinitions``, ``dataExtensions`` (and
``sharedDataExtensions``), ``attributeSets``, ``attributeRelationships``,
``automations``, ``queryActivities`` and ``assets`` (docs/export-format.md).

Spec rules applied here:

- "References written as {{mcpm#/entities/...}} are resolved to the real names before
  anything else." -> ``resolve_references`` runs on the whole export first.
- "If the export holds more than one journey, the app uses the one listed in
  selectedEntities.journeys." -> ``_choose_journey``.
- "Split criteria are XML (FilterDefinition) with nested AND/OR groups." ->
  ``criteria.parse_criteria``; condition tables are attribute-set names, mapped to
  table names through the attribute sets.
- "New activity types and operators are added by extending one lookup table each." ->
  ``model.ACTIVITY_KINDS`` maps the export type to a kind; ``WAIT_UI_TYPES`` tells the
  two supported waits apart; ``ENGAGEMENT_KINDS`` maps engagement statistics types.
- "Anything else is not an error: it is listed in the report, and the branches behind
  it are marked as not covered." -> an activity the generator does not understand gets
  ``KIND_UNSUPPORTED`` and its key goes to ``Package.unsupported_activities``.
- "A file that is not valid JSON, or holds no journey, gives a plain error message and
  nothing else." -> ``LoadError``; also raised when the entry table cannot be found.

Everything odd met while reading, and every reading the spec does not fix, goes to
``Package.warnings`` in plain words. Nothing here knows the pilot: every name is read
from the export. Field names are written with the schema's spelling (docs/plan.md:
"Field lookups are case-insensitive; the schema spelling is what gets written").
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterator, Optional

from .criteria import OPERATORS, CriteriaError, parse_criteria
from .model import (
    ACTIVITY_KINDS,
    FIELD_TYPES,
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
    Condition,
    ConditionGroup,
    EmailAsset,
    EntryEvent,
    Field,
    Formula,
    Journey,
    Outcome,
    Package,
    Query,
    Relationship,
    Table,
    Value,
    Write,
    formula_conditions,
)


class LoadError(Exception):
    """The export cannot be used: not valid JSON, no journey, or no entry table. The message is plain words."""


# Engagement split statsTypeId -> the action the tester must take (docs/export-format.md:
# "statsTypeId 2 = open, 3 = click"). Any other value is reported, never guessed.
ENGAGEMENT_KINDS: dict[int, str] = {2: "open", 3: "click"}

# model.ACTIVITY_KINDS maps the export type WAIT to a wait by duration; the export tells
# the kinds of wait apart by metaData.uiType. Spec, "Supported in the PoC": wait by
# duration and wait by attribute. Any other uiType is unsupported (reported, not guessed).
WAIT_UI_TYPES: dict[str, str] = {
    "WAITBYDURATION": KIND_WAIT_DURATION,
    "WAITBYATTRIBUTE": KIND_WAIT_ATTRIBUTE,
}

QUERY_OBJECT_TYPE = 300     # automation step activity that runs a query (1000 = data verification)

REFERENCE = re.compile(r"\{\{mcpm#/entities/([^/{}]+)/([^/{}]+)/data/([^{}]*)\}\}")
FIELD_ID_PATH = re.compile(r"^fields/name:(.+)/id$")
LINK = re.compile(r"href\s*=|<a\s", re.IGNORECASE)
MAX_REFERENCE_ROUNDS = 10   # a value that holds a reference is resolved again, this many times at most


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def load_package(source: Any) -> Package:
    """Read a package export and return its journey, tables, relationships and queries.

    ``source`` is the export as bytes, as JSON text, as a path (``str`` or
    ``pathlib.Path``) or as an already parsed dict (left unchanged). Raises LoadError
    with a plain message when it is not valid JSON, holds no journey, or the journey's
    entry table cannot be found.
    """
    export = _read_export(source)
    entities = export.get("entities")
    if not isinstance(entities, dict):
        raise LoadError("The file is not a package export: it has no 'entities' section, so it holds no journey.")
    warnings: list[str] = []
    journey_id = _choose_journey(export, entities, warnings)
    # Every reference is resolved before anything is read; journeys other than the chosen one
    # are left out, so that their oddities do not reach the warnings.
    wanted = {**entities, "journeys": {journey_id: entities["journeys"][journey_id]}}
    resolved = resolve_references(wanted, entities, warnings)
    return _ExportReader(resolved, warnings).read_package(str(export.get("name") or ""), journey_id)


def resolve_references(value: Any, entities: dict, warnings: Optional[list[str]] = None) -> Any:
    """Return a copy of ``value`` with every ``{{mcpm#/entities/<kind>/<id>/data/<path>}}`` replaced.

    Spec: "References written as {{mcpm#/entities/...}} are resolved to the real names
    before anything else." Works on strings, wherever the reference sits inside them
    (criteria XML, SQL, ``{{Event.{{mcpm#...}}."Field"}}``), and recursively on dict
    values and list items; other values come back unchanged. ``entities`` is the export's
    ``entities`` map. Rules (docs/plan.md, "loader.py"):

    - ``.../data/id`` -> the entity id (its key in ``entities``): the export carries no real ids;
    - ``.../data/fields/name:<F>/id`` -> the field name ``<F>``;
    - ``.../data/namePrefix`` -> the value when present, else ``""`` (so SQL ``prefix[name]`` becomes ``[name]``);
    - any other path (``name``, ``eventDefinitionKey``, ...) -> the value found at that path;
    - a path or an entity missing from the export -> the entity id, plus a warning.

    A value that itself holds a reference (an attribute set's ``storageName``) is
    resolved in turn. ``{{mcpm:...}}`` placeholders (sender profile, delivery profile)
    and personalisation strings stay as they are. Warnings go to ``warnings`` when a
    list is given.
    """
    if isinstance(value, str):
        return _resolve_text(value, entities, warnings)
    if isinstance(value, dict):
        return {key: resolve_references(item, entities, warnings) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_references(item, entities, warnings) for item in value]
    return value


# ---------------------------------------------------------------------------
# Reading the source
# ---------------------------------------------------------------------------

def _read_export(source: Any) -> dict:
    if isinstance(source, dict):
        export = source
    elif isinstance(source, (bytes, bytearray)):
        export = _parse_json(_decode(bytes(source)))
    elif isinstance(source, Path):
        export = _parse_json(_decode(_read_file(source)))
    elif isinstance(source, str):
        text = source.lstrip("﻿ \t\r\n")
        if not text or text[0] in "{[":
            export = _parse_json(text)
        else:
            export = _parse_json(_decode(_read_file(Path(source))))
    else:
        raise LoadError(f"A package export cannot be read from a {type(source).__name__}.")
    if not isinstance(export, dict):
        raise LoadError("The file is valid JSON but not a package export: a JSON object is expected.")
    return export


def _read_file(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise LoadError(f"The file {path} cannot be read ({error.strerror or error}).") from None


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise LoadError("The file is not UTF-8 text, so it is not a valid JSON package export.") from None


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise LoadError(
            f"The file is not valid JSON ({error.msg} at line {error.lineno}, column {error.colno})."
        ) from None


def _choose_journey(export: dict, entities: dict, warnings: list[str]) -> str:
    """Plan: "selectedEntities.journeys[0] when present, else the only journey, else the first with a warning."

    Spec: "If the export holds more than one journey, the app uses the one listed in
    selectedEntities.journeys." No journey at all -> LoadError.
    """
    journeys = [journey_id for journey_id, _ in _entity_items(entities, "journeys")]
    if not journeys:
        raise LoadError("The export holds no journey.")
    selection = export.get("selectedEntities")
    selected = selection.get("journeys") if isinstance(selection, dict) else None
    selected = [journey_id for journey_id in selected or [] if isinstance(journey_id, str)]
    if selected:
        if len(selected) > 1:
            _warn(warnings, f"The export selects {len(selected)} journeys; only the first one, {selected[0]}, is read.")
        if selected[0] in journeys:
            return selected[0]
        _warn(warnings, f"The selected journey {selected[0]} is not in the export.")
    if len(journeys) == 1:
        return journeys[0]
    first_name = _entity_data(entities, "journeys", journeys[0]).get("name") or journeys[0]
    _warn(warnings, f"The export holds {len(journeys)} journeys and none of them is selected; the first one, "
                    f"{first_name}, is read.")
    return journeys[0]


# ---------------------------------------------------------------------------
# Reference resolution
# ---------------------------------------------------------------------------

def _resolve_text(text: str, entities: dict, warnings: Optional[list[str]]) -> str:
    if "{{mcpm#" not in text:
        return text
    for _ in range(MAX_REFERENCE_ROUNDS):
        resolved = REFERENCE.sub(lambda match: _reference_value(match, entities, warnings), text)
        if resolved == text:
            break
        text = resolved
    if "{{mcpm#" in text:
        _warn(warnings, f"A reference could not be resolved and is kept as written: {text[:160]}")
    return text


def _reference_value(match: re.Match, entities: dict, warnings: Optional[list[str]]) -> str:
    kind, entity_id, path = match.groups()
    if path == "id":
        return entity_id
    field_name = FIELD_ID_PATH.match(path)
    if field_name:
        return field_name.group(1)
    data = _entity_data(entities, kind, entity_id)
    found = _value_at(data, path)
    if path == "namePrefix":
        return "" if found is None else str(found)
    if isinstance(found, (str, int, float, bool)):
        return str(found)
    if not data:
        _warn(warnings, f"The export does not hold {kind}/{entity_id}; a reference to it is replaced by the id {entity_id}.")
    else:
        _warn(warnings, f"{kind}/{entity_id} has no value at '{path}'; a reference to it is replaced by the id {entity_id}.")
    return entity_id


def _value_at(data: Any, path: str) -> Any:
    """The value at a ``/``-separated path inside an entity's data, or None when the path is missing."""
    current = data
    for part in path.split("/"):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _warn(warnings: Optional[list[str]], text: str) -> None:
    """Add a warning once; the same fact met many times is reported once."""
    if warnings is not None and text not in warnings:
        warnings.append(text)


def _entity_items(entities: dict, kind: str) -> list[tuple[str, dict]]:
    """(entity id, data) of every entity of one kind, in export order."""
    group = entities.get(kind)
    if not isinstance(group, dict):
        return []
    return [(entity_id, entity["data"]) for entity_id, entity in group.items()
            if isinstance(entity, dict) and isinstance(entity.get("data"), dict)]


def _entity_data(entities: dict, kind: str, entity_id: str) -> dict:
    """The ``data`` of one entity, or an empty dict when the export does not hold it."""
    group = entities.get(kind)
    entity = group.get(entity_id) if isinstance(group, dict) else None
    data = entity.get("data") if isinstance(entity, dict) else None
    return data if isinstance(data, dict) else {}


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _int_or_none(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _text_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


def _written_value(value: Any) -> Value:
    """Plan: an update-contact value is "kept as written (str(value) for numbers)"; null stays None."""
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


def _strings(value: Any) -> Iterator[str]:
    """Every string inside a nested dict / list."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _has_link(view: Any) -> bool:
    """Plan: has_link = an ``href=`` or ``<a `` appears in the HTML or text view.

    The whole view is searched: its ``content`` and, for template-based emails, the
    content of its slots and blocks.
    """
    return any(LINK.search(text) for text in _strings(view))


def _dotted_segments(text: str) -> list[str]:
    """Split ``A.B."C D"`` on the dots outside double quotes and drop the quotes: ``[A, B, C D]``."""
    segments: list[str] = []
    current: list[str] = []
    quoted = False
    for char in text:
        if char == '"':
            quoted = not quoted
        elif char == "." and not quoted:
            segments.append("".join(current))
            current = []
        else:
            current.append(char)
    segments.append("".join(current))
    return segments


def _personalisation_segments(expression: Any) -> list[str]:
    """Segments of a ``{{A.B."C"}}`` personalisation string; empty when it is not one."""
    if not isinstance(expression, str) or not expression.strip():
        return []
    text = expression.strip()
    if text.startswith("{{") and text.endswith("}}"):
        text = text[2:-2]
    return _dotted_segments(text)


def _expression_field(expression: Any) -> Optional[tuple[str, str]]:
    """(attribute set, field) of a wait-by-attribute expression.

    Plan: "last quoted segment = field, segment before it = attribute set", e.g.
    ``{{Contact.Attribute.Contacts.Master.Entry.Config."WAIT1"}}`` -> ``(Config, WAIT1)``.
    """
    segments = _personalisation_segments(expression)
    if len(segments) < 2 or not segments[-1] or not segments[-2]:
        return None
    return segments[-2], segments[-1]


def _key_field(key: Any) -> Optional[tuple[str, str]]:
    """(attribute set, field) of a key written ``Set.Field`` (split on the first dot, as criteria keys are)."""
    if not isinstance(key, str):
        return None
    set_name, dot, field_name = key.partition(".")
    if not dot or not set_name or not field_name:
        return None
    return set_name, field_name


def _event_field(text: str) -> Optional[str]:
    """The field name in ``{{Event.<key>."Field"}}``: the entry table field the journey sends to."""
    match = re.search(r'\."([^"]+)"\s*\}\}', str(text))
    return match.group(1) if match else None


def _event_key(expression: Any) -> Optional[str]:
    """The event key of ``{{Event.<key>."Field"}}``, or None when the expression reads no entry event."""
    segments = _personalisation_segments(expression)
    if len(segments) >= 3 and segments[0] == "Event" and segments[1]:
        return segments[1]
    return None


def _named(activity: Activity) -> str:
    """An activity as named in warnings: its key, and its name when it has one."""
    return f"{activity.key} ({activity.name})" if activity.name else activity.key


def _outcome(raw: dict) -> Outcome:
    """One outcome: key, label, next activity. The label falls back to the criteria description, then the key."""
    meta = _dict(raw.get("metaData"))
    key = str(raw.get("key") or "")
    description = str(meta.get("criteriaDescription") or "")
    next_key = raw.get("next")
    return Outcome(
        key=key,
        label=str(meta.get("label") or description or key),
        next=str(next_key) if next_key else None,
        description=description,
    )


# ---------------------------------------------------------------------------
# Building the package
# ---------------------------------------------------------------------------

class _ExportReader:
    """Builds the Package from the resolved ``entities`` of one export, collecting warnings."""

    def __init__(self, entities: dict, warnings: list[str]):
        self.entities = entities
        self.warnings = warnings
        self.tables: dict[str, Table] = {}
        self.table_aliases: dict[str, str] = {}     # entity id or customer key -> table name
        self.set_tables: dict[str, str] = {}        # attribute set id or name -> table name
        self.queries_by_id: dict[str, Query] = {}
        self.automation_names: dict[str, str] = {}  # automation entity id -> automation name
        self.emails: dict[str, EmailAsset] = {}
        self.legacy_email_ids: dict[str, str] = {}  # email legacyId -> asset id

    def warn(self, text: str) -> None:
        _warn(self.warnings, text)

    def items(self, kind: str) -> list[tuple[str, dict]]:
        return _entity_items(self.entities, kind)

    def read_package(self, package_name: str, journey_id: str) -> Package:
        self.read_tables()
        self.read_attribute_sets()
        relationships = self.read_relationships()
        queries = self.read_queries()
        automation_queries = self.read_automations()
        self.read_emails()
        journey_data = _entity_data(self.entities, "journeys", journey_id)
        entry_event = self.read_entry_event(journey_data)
        journey = self.read_journey(journey_id, journey_data, entry_event)
        self.check_constant_writes_into_keys(journey)
        self.check_one_to_one_joins(relationships)
        return Package(
            name=package_name,
            journey=journey,
            tables=self.tables,
            relationships=relationships,
            queries=queries,
            entry_event=entry_event,
            emails=self.emails,
            automation_queries=automation_queries,
            warnings=self.warnings,
            unsupported_activities=[a.key for a in journey.activities.values() if a.kind == KIND_UNSUPPORTED],
        )

    # -- checks carried over from the earlier tool (spec, "Outputs") ----------

    def check_constant_writes_into_keys(self, journey: Journey) -> None:
        """Spec check: "An update contact step that writes a constant into a primary-key field"."""
        found: dict[tuple[str, str, str], list[str]] = {}
        for activity in journey.activities.values():
            for write in activity.writes:
                table = self.tables.get(write.table)
                field = table.field(write.field) if table is not None else None
                if field is None or not field.is_primary_key or write.value is None:
                    continue
                if "{{" in write.value:
                    continue   # a placeholder such as {{DateTime.Now}} is not a constant
                found.setdefault((table.name, field.name, write.value), []).append(activity.key)
        for (table, field, value), keys in found.items():
            self.warn(f"suspicious pattern: {len(keys)} update contact step(s) write the constant {value!r} into the "
                      f"primary-key field {table}.{field}, so every contact gets the same key value there "
                      f"({', '.join(keys)}).")

    def check_one_to_one_joins(self, relationships: list[Relationship]) -> None:
        """Spec check: "A one-to-one relationship to a table whose primary key is wider than the join"."""
        by_name: dict[str, list[Relationship]] = {}
        for rel in relationships:
            if rel.left_table is not None:
                by_name.setdefault(rel.name, []).append(rel)
        for name, rels in by_name.items():
            first = rels[0]
            if first.left_cardinality != "One" or first.right_cardinality != "One":
                continue
            table = self.tables.get(first.right_table)
            if table is None:
                continue
            join_fields = {r.right_field.lower() for r in rels}
            pk = [f.name for f in table.fields if f.is_primary_key]
            extra = [f for f in pk if f.lower() not in join_fields]
            if extra:
                self.warn(f"suspicious pattern: the one-to-one relationship '{name}' joins {table.name} on "
                          f"{', '.join(sorted(r.right_field for r in rels))}, but its primary key also has "
                          f"{', '.join(extra)}: several rows can match one contact.")

    # -- tables -------------------------------------------------------------

    def read_tables(self) -> None:
        """Plan: "Tables: all dataExtensions (and sharedDataExtensions), fields in ordinal order"."""
        for kind in ("dataExtensions", "sharedDataExtensions"):
            for entity_id, data in self.items(kind):
                table = self.table_from(entity_id, data)
                if table.name in self.tables:
                    self.warn(f"Two tables are named {table.name}; the first one in the export is used.")
                else:
                    self.tables[table.name] = table
                self.table_aliases[entity_id] = table.name
                if table.customer_key:
                    self.table_aliases.setdefault(table.customer_key, table.name)

    def table_from(self, entity_id: str, data: dict) -> Table:
        name = str(data.get("name") or entity_id)
        raw_fields = [raw for raw in _list(data.get("fields")) if isinstance(raw, dict) and raw.get("name")]
        fields = [self.field_from(name, raw, position) for position, raw in enumerate(raw_fields)]
        fields.sort(key=lambda f: f.ordinal)
        table = Table(
            id=entity_id,
            name=name,
            customer_key=_text_or_none(data.get("customerKey")),
            fields=fields,
            is_sendable=bool(data.get("isSendable")),
        )
        sendable_field = data.get("sendableCustomObjectField")
        if sendable_field:
            table.sendable_field = self.field_spelling(table, str(sendable_field))
        return table

    def field_from(self, table_name: str, raw: dict, position: int) -> Field:
        name = str(raw["name"])
        field_type = str(raw.get("type") or "")
        if field_type not in FIELD_TYPES:
            self.warn(f"Field {table_name}.{name} has type {field_type!r}, which the generator does not know.")
        is_primary_key = bool(raw.get("isPrimaryKey"))
        nullable = raw.get("isNullable")
        if nullable is None:
            nullable = not is_primary_key
            self.warn(f"Field {table_name}.{name} does not say whether it accepts null; it is taken as "
                      f"{'nullable' if nullable else 'not nullable'} because it is "
                      f"{'not ' if nullable else ''}part of the primary key.")
        ordinal = _int_or_none(raw.get("ordinal"))
        return Field(
            name=name,
            type=field_type,
            length=_int_or_none(raw.get("length")),
            is_primary_key=is_primary_key,
            is_nullable=bool(nullable),
            default=_text_or_none(raw.get("defaultValue")),
            ordinal=position if ordinal is None else ordinal,
        )

    def known_table(self, value: Any) -> Optional[str]:
        """The table a resolved reference names (a table name, entity id or customer key), or None."""
        if not isinstance(value, str) or not value:
            return None
        if value in self.tables:
            return value
        return self.table_aliases.get(value)

    def table_ref(self, value: Any, what: str) -> str:
        """The table named by a resolved reference; an unknown one is kept as written, with a warning."""
        table = self.known_table(value)
        if table is None:
            table = "" if value is None else str(value)
            self.warn(f"{what} names the table {table!r}, which is not in the export.")
        return table

    def field_spelling(self, table: Table, field_name: str) -> str:
        """The field's spelling in the table schema; a field missing from the schema is kept, with a warning."""
        field = table.field(field_name)
        if field is None:
            self.warn(f"Field {field_name!r} is not in the schema of table {table.name}.")
            return field_name
        if field.name != field_name:
            self.warn(f"Field {table.name}.{field_name} is spelled {field.name} in the table schema; "
                      f"the schema spelling is used.")
        return field.name

    def schema_field(self, table_name: str, field_name: str) -> str:
        table = self.tables.get(table_name)
        if table is None:       # the unknown table has already been reported
            return field_name
        return self.field_spelling(table, field_name)

    # -- attribute sets and relationships -----------------------------------

    def read_attribute_sets(self) -> None:
        """Each attribute set names a table through ``storageName`` (fallback: ``storageReferenceID``)."""
        for set_id, data in self.items("attributeSets"):
            name = str(data.get("name") or set_id)
            storage = data.get("storageName")
            table = self.known_table(storage) or self.known_table(_dict(data.get("storageReferenceID")).get("value"))
            if table is None:
                table = str(storage or name)
                self.warn(f"Attribute set {name} stores its data in {table}, which is not a table in the export.")
            self.set_tables[set_id] = table
            self.set_tables.setdefault(name, table)

    def table_for_set(self, set_name: str) -> str:
        """Plan: map the attribute-set name to the table through ``attributeSets[*].storageName``.

        "Fall back to the name itself when no set matches, with a warning."
        """
        table = self.set_tables.get(set_name)
        if table is None:
            table = set_name
            known = "" if set_name in self.tables else ", and no table has that name either"
            self.warn(f"No attribute set is named {set_name}; the name is taken as a table name{known}.")
        return table

    def item_table(self, item: dict, relationship_name: str) -> str:
        """The table of one side of a relationship (``leftItem.identifier`` / ``rightItem.name``)."""
        for ref in (item.get("identifier"), item.get("name")):
            if isinstance(ref, str) and ref in self.set_tables:
                return self.set_tables[ref]
        fallback = str(item.get("name") or item.get("identifier") or "")
        self.warn(f"Relationship {relationship_name} links {fallback!r}, which is not an attribute set of the "
                  f"export; it is taken as a table name.")
        return fallback

    def read_relationships(self) -> list[Relationship]:
        """Plan: one Relationship per ``relationshipAttributes`` entry; group-to-set links have no left table."""
        relationships: list[Relationship] = []
        for relationship_id, data in self.items("attributeRelationships"):
            name = str(data.get("name") or relationship_id)
            left_item, right_item = _dict(data.get("leftItem")), _dict(data.get("rightItem"))
            group_to_set = bool(data.get("isGroupToSetRelationship"))
            left_table = None if group_to_set else self.item_table(left_item, name)
            right_table = self.item_table(right_item, name)
            pairs = [pair for pair in _list(data.get("relationshipAttributes")) if isinstance(pair, dict)]
            if not pairs:
                self.warn(f"Relationship {name} names no fields, so it links nothing.")
            for pair in pairs:
                left_field = _text_or_none(pair.get("leftAttributeName")) or None
                if left_field and left_table is not None:
                    left_field = self.schema_field(left_table, left_field)
                right_field = str(pair.get("rightAttributeName") or pair.get("rightAttributeID") or "")
                relationships.append(Relationship(
                    name=name,
                    left_table=left_table,
                    left_field=left_field,
                    right_table=right_table,
                    right_field=self.schema_field(right_table, right_field),
                    left_cardinality=str(left_item.get("cardinality") or ""),
                    right_cardinality=str(right_item.get("cardinality") or ""),
                ))
        return relationships

    # -- queries, automations, emails ---------------------------------------

    def read_queries(self) -> list[Query]:
        """Plan: "Queries: every queryActivities entry" (SQL with references already resolved)."""
        queries: list[Query] = []
        for query_id, data in self.items("queryActivities"):
            name = str(data.get("name") or query_id)
            target = data.get("targetId") or data.get("targetKey") or data.get("targetName")
            query = Query(
                id=query_id,
                name=name,
                target_table=self.table_ref(target, f"Query {name}"),
                sql=str(data.get("queryText") or ""),
                update_type=str(data.get("targetUpdateTypeName") or ""),
            )
            queries.append(query)
            self.queries_by_id[query_id] = query
        return queries

    def read_automations(self) -> dict[str, list[str]]:
        """Plan: automation name -> query names in step order (``steps[*].activities[*]`` with objectTypeId 300)."""
        automation_queries: dict[str, list[str]] = {}
        for automation_id, data in self.items("automations"):
            name = str(data.get("name") or automation_id)
            self.automation_names[automation_id] = name
            names: list[str] = []
            for step in _list(data.get("steps")):
                for step_activity in _list(_dict(step).get("activities")):
                    if _int_or_none(_dict(step_activity).get("objectTypeId")) == QUERY_OBJECT_TYPE:
                        names.append(self.step_query_name(step_activity, name))
            if name in automation_queries:
                self.warn(f"Two automations are named {name}; the queries of the last one are kept.")
            automation_queries[name] = names
        return automation_queries

    def step_query_name(self, step_activity: dict, automation_name: str) -> str:
        query = self.queries_by_id.get(str(step_activity.get("activityObjectId") or ""))
        if query is not None:
            return query.name
        name = str(step_activity.get("name") or step_activity.get("activityObjectId") or "")
        self.warn(f"Automation {automation_name} runs the query {name}, which is not in the export.")
        return name

    def read_emails(self) -> None:
        """Every asset of the export, by asset id. Plan: has_link = ``href=`` or ``<a `` in the HTML or text view."""
        for asset_id, data in self.items("assets"):
            views = _dict(data.get("views"))
            self.emails[asset_id] = EmailAsset(
                id=asset_id,
                name=str(data.get("name") or asset_id),
                subject=str(_dict(views.get("subjectline")).get("content") or ""),
                has_link=_has_link(views.get("html")) or _has_link(views.get("text")),
            )
            legacy_id = _value_at(data, "data/email/legacy/legacyId")
            if legacy_id is not None:
                self.legacy_email_ids[str(legacy_id)] = asset_id

    # -- entry ----------------------------------------------------------------

    def read_entry_event(self, journey_data: dict) -> EntryEvent:
        """Plan: the trigger's ``metaData.eventDefinitionId`` -> eventDefinition -> ``dataExtensionId`` -> table;
        ``arguments.automationId`` -> automation name.

        Spec, "Table selection": the entry table is "the table bound to the journey's
        entry trigger". Without it nothing can be generated, so it is a LoadError.
        """
        triggers = [trigger for trigger in _list(journey_data.get("triggers")) if isinstance(trigger, dict)]
        if not triggers:
            raise LoadError("The journey has no entry trigger, so its entry table cannot be found.")
        if len(triggers) > 1:
            self.warn(f"The journey has {len(triggers)} entry triggers; only the first one is read.")
        meta = _dict(triggers[0].get("metaData"))
        event_id, event = self.find_event(meta)
        if event is None:
            raise LoadError("The journey's entry event is not in the export, so its entry table cannot be found.")
        event_name = str(event.get("name") or event_id)
        arguments = _dict(event.get("arguments"))
        table_ref = event.get("dataExtensionId") or arguments.get("dataExtensionId")
        table = self.known_table(table_ref)
        if table is None:
            raise LoadError(f"The entry table of the event {event_name} ({table_ref}) is not in the export.")
        automation_ref = arguments.get("automationId")
        automation_name = self.automation_names.get(str(automation_ref)) if automation_ref else None
        if automation_ref and automation_name is None:
            self.warn(f"The entry event {event_name} is fed by the automation {automation_ref}, "
                      f"which is not in the export.")
        return EntryEvent(
            key=str(event.get("eventDefinitionKey") or meta.get("eventDefinitionKey") or ""),
            name=event_name,
            table=table,
            automation_name=automation_name,
        )

    def find_event(self, trigger_meta: dict) -> tuple[str, Optional[dict]]:
        events = dict(self.items("eventDefinitions"))
        event_id = str(trigger_meta.get("eventDefinitionId") or "")
        if event_id in events:
            return event_id, events[event_id]
        event_key = trigger_meta.get("eventDefinitionKey")
        for other_id, data in events.items():
            if event_key and data.get("eventDefinitionKey") == event_key:
                return other_id, data
        return event_id, None

    def event_name(self, event_key: str) -> Optional[str]:
        for _, data in self.items("eventDefinitions"):
            if data.get("eventDefinitionKey") == event_key:
                return str(data.get("name") or "")
        return None

    def check_defaults(self, defaults: dict, entry: EntryEvent) -> None:
        """Spec, "Outputs" checks: "A journey default that reads from a different entry event"."""
        for default_name, expressions in defaults.items():
            for expression in _list(expressions):
                event_key = _event_key(expression)
                if event_key is None or event_key == entry.key:
                    continue
                other_name = self.event_name(event_key)
                other = f"{event_key} ({other_name})" if other_name else event_key
                self.warn(f"The journey default {default_name} reads {expression} from the entry event {other}, "
                          f"not from the journey's entry event {entry.key} ({entry.name}).")

    # -- journey ----------------------------------------------------------------

    def read_journey(self, journey_id: str, data: dict, entry: EntryEvent) -> Journey:
        activities: dict[str, Activity] = {}
        for raw in _list(data.get("activities")):
            if not isinstance(raw, dict):
                continue
            activity = self.read_activity(raw)
            if not activity.key:
                self.warn(f"An activity named {activity.name!r} has no key, so nothing can lead to it; it is ignored.")
            elif activity.key in activities:
                self.warn(f"Two activities have the key {activity.key}; the first one is used.")
            else:
                activities[activity.key] = activity
        self.check_links(activities)
        defaults = _dict(data.get("defaults"))
        self.check_defaults(defaults, entry)
        email_defaults = _list(defaults.get("email"))
        return Journey(
            name=str(data.get("name") or journey_id),
            key=str(data.get("key") or ""),
            activities=activities,
            start_key=self.start_key(activities),
            entry_event_key=entry.key or None,
            entry_table=entry.table,
            default_email_event_key=_event_key(email_defaults[0]) if email_defaults else None,
            default_email_field=_event_field(email_defaults[0]) if email_defaults else None,
            activity_count=len(activities),
        )

    def start_key(self, activities: dict[str, Activity]) -> Optional[str]:
        """Spec: "The start is the activity no other activity points to." Several -> the first, with a warning."""
        targets = {outcome.next for activity in activities.values() for outcome in activity.outcomes if outcome.next}
        starts = [key for key in activities if key not in targets]
        if not starts:
            self.warn("Every activity of the journey is the target of another one, so the start activity cannot be "
                      "found." if activities else "The journey has no activities.")
            return None
        if len(starts) > 1:
            self.warn(f"{len(starts)} activities have no incoming link ({', '.join(starts)}); the first one, "
                      f"{starts[0]}, is taken as the start.")
        return starts[0]

    def check_links(self, activities: dict[str, Activity]) -> None:
        for activity in activities.values():
            for outcome in activity.outcomes:
                if outcome.next and outcome.next not in activities:
                    self.warn(f"Activity {activity.key}, outcome {outcome.label!r}, leads to {outcome.next}, "
                              f"which is not in the journey.")
            if activity.kind == KIND_ENGAGEMENT and activity.engagement_ref:
                referenced = activities.get(activity.engagement_ref)
                if referenced is None or referenced.kind != KIND_EMAIL:
                    self.warn(f"Engagement split {_named(activity)} refers to "
                              f"{activity.engagement_ref}, which is not an email activity of the journey.")

    # -- activities -------------------------------------------------------------

    def read_activity(self, raw: dict) -> Activity:
        raw_outcomes = [outcome for outcome in _list(raw.get("outcomes")) if isinstance(outcome, dict)]
        activity = Activity(
            key=str(raw.get("key") or ""),
            raw_type=str(raw.get("type") or ""),
            kind=KIND_UNSUPPORTED,
            name=str(raw.get("name") or ""),
            outcomes=[_outcome(outcome) for outcome in raw_outcomes],
        )
        activity.kind = self.activity_kind(activity, raw)
        if activity.kind == KIND_DECISION:
            self.read_decision(activity, raw)
        elif activity.kind == KIND_ENGAGEMENT:
            self.read_engagement(activity, raw, raw_outcomes)
        elif activity.kind == KIND_RANDOM:
            self.read_random(activity, raw_outcomes)
        elif activity.kind == KIND_WAIT_DURATION:
            self.read_wait_duration(activity, raw)
        elif activity.kind == KIND_WAIT_ATTRIBUTE:
            self.read_wait_attribute(activity, raw)
        elif activity.kind == KIND_WAIT_STO:
            self.read_wait_sto(activity, raw)
        elif activity.kind == KIND_EMAIL:
            self.read_email(activity, raw)
        elif activity.kind == KIND_UPDATE:
            self.read_update(activity, raw)
        return activity

    def activity_kind(self, activity: Activity, raw: dict) -> str:
        """Plan: map ``type`` through ``model.ACTIVITY_KINDS``; unknown types are unsupported.

        A WAIT is refined by ``metaData.uiType`` through WAIT_UI_TYPES.
        """
        kind = ACTIVITY_KINDS.get(activity.raw_type, KIND_UNSUPPORTED)
        if activity.raw_type == "WAIT":
            ui_type = _dict(raw.get("metaData")).get("uiType")
            kind = WAIT_UI_TYPES.get(str(ui_type), KIND_UNSUPPORTED)
            if kind == KIND_UNSUPPORTED:
                self.warn(f"Activity {_named(activity)} is a wait of kind {ui_type!r}; only waits by "
                          f"duration and by attribute are supported, so it is reported as unsupported.")
        return kind

    def make_unsupported(self, activity: Activity, reason: str) -> None:
        """Spec: "Anything else is not an error: it is listed in the report, and the branches behind it
        are marked as not covered." The activity keeps its outcomes, so the graph stays whole."""
        activity.kind = KIND_UNSUPPORTED
        activity.unsupported_reason = reason
        for outcome in activity.outcomes:
            outcome.formula = None
            outcome.is_remainder = False
        self.warn(f"Activity {_named(activity)} is reported as unsupported: {reason}.")

    def read_decision(self, activity: Activity, raw: dict) -> None:
        """Plan: ``configurationArguments.criteria[outcome.key]`` is parsed; the outcome without criteria is the
        remainder. Spec: "Outcomes are tried in order, the first true one wins, and the remainder branch means
        none matched" -> the outcomes keep their export order.
        """
        criteria = _dict(_dict(raw.get("configurationArguments")).get("criteria"))
        for outcome in activity.outcomes:
            xml = criteria.get(outcome.key)
            if not xml:
                outcome.is_remainder = True
                continue
            try:
                formula = parse_criteria(xml)
            except CriteriaError as error:
                self.make_unsupported(activity, f"the criteria of its outcome {outcome.label!r} cannot be read "
                                                f"({error})")
                return
            outcome.formula = self.map_formula(formula)
            problem = self.unsupported_condition(outcome)
            if problem is not None:
                # Spec: outcomes are tried in order, so the outcomes before this one can still be
                # covered; this one and the ones after it are reported as not covered.
                outcome.unsupported_reason = problem
                self.warn(f"Decision split {_named(activity)}: {problem}; this outcome and the ones after it "
                          "are reported as not covered.")
        remainders = [position for position, outcome in enumerate(activity.outcomes, 1) if outcome.is_remainder]
        if remainders != [len(activity.outcomes)]:
            self.warn(f"Decision split {_named(activity)} should have one outcome without criteria "
                      f"(the remainder), in last position; outcomes without criteria: "
                      f"{remainders or 'none'} of {len(activity.outcomes)}.")

    def map_formula(self, formula: Formula) -> Formula:
        """Condition tables: attribute-set name -> table name; fields in the schema's spelling."""
        if isinstance(formula, Condition):
            table = self.table_for_set(formula.table)
            return replace(formula, table=table, field=self.schema_field(table, formula.field))
        return ConditionGroup(formula.operator, tuple(self.map_formula(item) for item in formula.items))

    def unsupported_condition(self, outcome: Outcome) -> Optional[str]:
        """Why a mapped outcome formula cannot be evaluated, or None.

        Spec, operators: only the listed ones are understood, "the rest is reported, not guessed".
        A condition on a table or field that is not in the export's schemas cannot be given a type,
        a length or a nullability, so its split is reported as unsupported rather than guessed.
        """
        for condition in formula_conditions(outcome.formula):
            if condition.operator not in OPERATORS:
                return (f"outcome {outcome.label!r} uses the operator {condition.operator!r}, which the PoC does "
                        f"not support")
            table = self.tables.get(condition.table)
            if table is None:
                return (f"outcome {outcome.label!r} reads {condition.table}.{condition.field}, and the table "
                        f"{condition.table!r} is not in the export")
            if table.field(condition.field) is None:
                return (f"outcome {outcome.label!r} reads {condition.table}.{condition.field}, and the field "
                        f"{condition.field!r} is not in the schema of {table.name}")
        return None

    def read_engagement(self, activity: Activity, raw: dict, raw_outcomes: list[dict]) -> None:
        """Plan: ``refActivityCustomerKey`` -> engagement_ref; ``statsTypeId`` through ENGAGEMENT_KINDS;
        outcomes carry ``when`` from ``arguments.when``."""
        config = _dict(raw.get("configurationArguments"))
        activity.engagement_ref = _text_or_none(config.get("refActivityCustomerKey")) or None
        activity.engagement_kind = ENGAGEMENT_KINDS.get(_int_or_none(config.get("statsTypeId")))
        if activity.engagement_kind is None:
            self.warn(f"Engagement split {_named(activity)} measures the statistics type "
                      f"{config.get('statsTypeId')!r}, which is neither an open (2) nor a click (3); its branches "
                      f"will be reported as not covered.")
        for outcome, raw_outcome in zip(activity.outcomes, raw_outcomes):
            when = _dict(raw_outcome.get("arguments")).get("when")
            outcome.when = when if isinstance(when, bool) else None
        if activity.outcomes and all(o.when is None for o in activity.outcomes):
            self.make_unsupported(activity, "its outcomes do not say which one is the Yes branch and which the No branch")
            return
        for outcome in activity.outcomes:
            if outcome.when is None:
                self.warn(f"Engagement split {_named(activity)}, outcome {outcome.label!r}, does not "
                          f"say whether it is the Yes or the No branch.")
        urls = _list(_dict(config.get("engagementUrls")).get("urls"))
        if urls:
            self.warn(f"Engagement split {_named(activity)} counts only clicks on these links: "
                      f"{', '.join(str(url) for url in urls)}.")

    def read_random(self, activity: Activity, raw_outcomes: list[dict]) -> None:
        """Plan: ``percentage`` from ``outcomes[*].arguments.percentage``."""
        for outcome, raw_outcome in zip(activity.outcomes, raw_outcomes):
            outcome.percentage = _int_or_none(_dict(raw_outcome.get("arguments")).get("percentage"))
        percentages = [outcome.percentage for outcome in activity.outcomes]
        if None in percentages or sum(p for p in percentages if p is not None) != 100:
            self.warn(f"Random split {_named(activity)} has the percentages {percentages}, "
                      f"which do not add up to 100.")

    def read_wait_duration(self, activity: Activity, raw: dict) -> None:
        config = _dict(raw.get("configurationArguments"))
        activity.wait_amount = _int_or_none(config.get("waitDuration"))
        activity.wait_unit = _text_or_none(config.get("waitUnit")) or None
        activity.wait_timezone = _text_or_none(config.get("timeZone")) or None

    def read_wait_attribute(self, activity: Activity, raw: dict) -> None:
        """Plan: the field comes from ``configurationArguments.waitEndDateAttributeExpression`` (last quoted
        segment = field, segment before it = attribute set -> table); ``metaData.attribute.id`` is the fallback.
        """
        config = _dict(raw.get("configurationArguments"))
        activity.wait_timezone = _text_or_none(config.get("timeZone")) or None
        found = _expression_field(config.get("waitEndDateAttributeExpression"))
        if found is None:
            found = _key_field(_dict(_dict(raw.get("metaData")).get("attribute")).get("id"))
        if found is None:
            self.warn(f"Wait {_named(activity)} waits on a date attribute that cannot be identified.")
            return
        set_name, field_name = found
        table = self.table_for_set(set_name)
        activity.wait_field = (table, self.schema_field(table, field_name))
        offset = _int_or_none(config.get("waitDuration"))
        if offset:
            self.warn(f"Wait {_named(activity)} has a waitDuration of {offset} {config.get('waitUnit')} "
                      f"on top of the date in {table}.{activity.wait_field[1]}; this offset is not modelled.")

    def read_wait_sto(self, activity: Activity, raw: dict) -> None:
        """Send-time wait: the email goes out within ``params.slidingWindowHours``.

        Recorded as ``wait_amount`` hours (the longest delay), because the spec notes the
        expected delay of a send-time wait in the testbook.
        """
        params = _dict(_dict(raw.get("configurationArguments")).get("params"))
        hours = _int_or_none(params.get("slidingWindowHours"))
        if hours is not None:
            activity.wait_amount = hours
            activity.wait_unit = "HOURS"

    def read_email(self, activity: Activity, raw: dict) -> None:
        """Plan: ``triggeredSend.emailId`` resolves to the asset id; ``email_name`` is the asset name, else the
        activity name. An emailId holding the asset's legacy id is matched to that asset too."""
        send = _dict(_dict(raw.get("configurationArguments")).get("triggeredSend"))
        email_ref = send.get("emailId")
        asset_id = None if email_ref is None else str(email_ref)
        if asset_id is not None and asset_id not in self.emails:
            asset_id = self.legacy_email_ids.get(asset_id, asset_id)
        activity.email_asset_id = asset_id
        asset = self.emails.get(asset_id) if asset_id else None
        activity.email_name = asset.name if asset else activity.name
        if asset is None:
            self.warn(f"Email activity {_named(activity)} sends the email {asset_id!r}, which is not "
                      f"in the export; whether it holds a link is unknown.")

    def read_update(self, activity: Activity, raw: dict) -> None:
        """Plan: ``arguments.activityData.updateContactFields[*]`` -> Write(table, field, value); the value is
        kept as written (``str(value)`` for numbers), ``{{DateTime.Now}}`` literally."""
        activity_data = _dict(_dict(raw.get("arguments")).get("activityData"))
        for item in _list(activity_data.get("updateContactFields")):
            if not isinstance(item, dict):
                continue
            table = self.table_ref(item.get("dataExtensionId"), f"Update contact {_named(activity)}")
            field_name = self.schema_field(table, str(item.get("field") or ""))
            activity.writes.append(Write(table=table, field=field_name, value=_written_value(item.get("value"))))
        if not activity.writes:
            self.warn(f"Update contact {_named(activity)} writes no field.")
