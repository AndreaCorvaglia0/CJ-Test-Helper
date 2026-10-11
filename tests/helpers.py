"""Builders for small hand-made journeys used by the lead's unit tests (graph, coverage, checks)."""

from __future__ import annotations

from typing import Optional

from cjhelper.model import (
    KIND_DECISION, KIND_EMAIL, KIND_ENGAGEMENT, KIND_RANDOM, KIND_UNSUPPORTED, KIND_UPDATE,
    KIND_WAIT_ATTRIBUTE, KIND_WAIT_DURATION, LEVEL_CONTACT, LEVEL_SCENARIO, ROLE_ENTRY, ROLE_SOURCE, ROLE_SPLIT,
    Activity, Condition, ConditionGroup, EmailAsset, EntryEvent, Field, Journey, KeyGroup, Outcome, Package,
    Relationship, Table, TableModel, TableRole, Write,
)


def field(name, type_="Text", pk=False, nullable=True, length=50, default=None, ordinal=0):
    return Field(name=name, type=type_, length=None if type_ in ("Boolean", "Date") else length,
                 is_primary_key=pk, is_nullable=nullable, default=default, ordinal=ordinal)


def table(name, fields, sendable_field=None):
    fs = [Field(f.name, f.type, f.length, f.is_primary_key, f.is_nullable, f.default, i) for i, f in enumerate(fields)]
    return Table(id=name.lower(), name=name, customer_key=name, fields=fs,
                 is_sendable=sendable_field is not None, sendable_field=sendable_field)


def cond(table_name, field_name, operator="Is", value=None):
    return Condition(table=table_name, field=field_name, operator=operator, value=value)


def AND(*items):
    return ConditionGroup("AND", tuple(items))


def OR(*items):
    return ConditionGroup("OR", tuple(items))


def decision(key, name, outcomes, remainder_next="__none__"):
    """outcomes: list of (outcome_key, label, next, formula). A remainder is added unless remainder_next is None."""
    outs = [Outcome(key=k, label=lbl, next=nxt, formula=f, is_remainder=False) for (k, lbl, nxt, f) in outcomes]
    if remainder_next != "__none__":
        outs.append(Outcome(key="remainder_path", label="Remainder", next=remainder_next, formula=None, is_remainder=True))
    return Activity(key=key, raw_type="MULTICRITERIADECISION", kind=KIND_DECISION, name=name, outcomes=outs)


def engagement(key, name, kind, ref, yes_next, no_next):
    outs = [Outcome(key="branchResult-1", label="Yes", next=yes_next, when=True),
            Outcome(key="branchResult-2", label="No", next=no_next, when=False)]
    return Activity(key=key, raw_type="ENGAGEMENTDECISION", kind=KIND_ENGAGEMENT, name=name, outcomes=outs,
                    engagement_kind=kind, engagement_ref=ref)


def random_split(key, branches):
    outs = [Outcome(key=k, label=f"{pct}%", next=nxt, percentage=pct) for (k, pct, nxt) in branches]
    return Activity(key=key, raw_type="RANDOMSPLIT", kind=KIND_RANDOM, name="", outcomes=outs)


def email(key, name, asset_id, next_key):
    return Activity(key=key, raw_type="EMAILV2", kind=KIND_EMAIL, name=name,
                    outcomes=[Outcome(key=key + "-out", label="", next=next_key)],
                    email_asset_id=asset_id, email_name=name)


def update(key, name, writes, next_key):
    return Activity(key=key, raw_type="UPDATECONTACTDATA", kind=KIND_UPDATE, name=name,
                    outcomes=[Outcome(key=key + "-out", label="", next=next_key)],
                    writes=[Write(t, f, v) for (t, f, v) in writes])


def wait_attr(key, table_name, field_name, next_key):
    return Activity(key=key, raw_type="WAIT", kind=KIND_WAIT_ATTRIBUTE, name=f"on {field_name}",
                    outcomes=[Outcome(key=key + "-out", label="", next=next_key)], wait_field=(table_name, field_name))


def wait_dur(key, amount, unit, next_key):
    return Activity(key=key, raw_type="WAIT", kind=KIND_WAIT_DURATION, name=f"{amount} {unit}",
                    outcomes=[Outcome(key=key + "-out", label="", next=next_key)], wait_amount=amount, wait_unit=unit)


def unsupported(key, raw_type, next_key):
    return Activity(key=key, raw_type=raw_type, kind=KIND_UNSUPPORTED, name=key,
                    outcomes=[Outcome(key=key + "-out", label="", next=next_key)])


def journey(activities, entry_table="DE_Entry", name="J"):
    acts = {a.key: a for a in activities}
    targets = {o.next for a in activities for o in a.outcomes if o.next}
    starts = [a.key for a in activities if a.key not in targets]
    return Journey(name=name, key="k", activities=acts, start_key=starts[0] if starts else None,
                   entry_event_key="EV", entry_table=entry_table, activity_count=len(acts))


def package(jny, tables, emails=None, unsupported_keys=()):
    return Package(name="pkg", journey=jny, tables={t.name: t for t in tables}, relationships=[], queries=[],
                   entry_event=EntryEvent(key="EV", name="EV", table=jny.entry_table, automation_name=None),
                   emails=emails or {}, unsupported_activities=list(unsupported_keys))


def table_model(entry, contact_key, levels, key_groups, tables, entry_query=None):
    """levels: {table name: LEVEL_*}; key_groups: list of (kind, [(table, field), ...])."""
    roles = {}
    for t in tables:
        lvl = levels.get(t.name)
        roles[t.name] = TableRole(name=t.name, roles={ROLE_ENTRY} if t.name == entry else {ROLE_SPLIT},
                                  selected=lvl is not None, level=lvl, reason="test")
    field_levels = {}
    for t in tables:
        lvl = levels.get(t.name)
        if lvl is None:
            continue
        for f in t.fields:
            field_levels[(t.name, f.name)] = lvl
    groups = [KeyGroup(kind, list(fields)) for kind, fields in key_groups]
    for g in groups:
        if g.kind == "scenario":
            for ref in g.fields:
                if ref in field_levels:
                    field_levels[ref] = LEVEL_SCENARIO
    return TableModel(entry_table=entry, contact_key_field=(entry, contact_key), tables=roles, key_groups=groups,
                      field_levels=field_levels, entry_query=entry_query, source_queries=[entry_query] if entry_query else [],
                      scenario_tables=[n for n, l in levels.items() if l == LEVEL_SCENARIO],
                      contact_tables=[n for n, l in levels.items() if l == LEVEL_CONTACT],
                      activation_field=None)


def email_asset(asset_id="A1", name="Demo", has_link=False):
    return EmailAsset(id=asset_id, name=name, subject=name, has_link=has_link)
