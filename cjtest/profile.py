"""Test profile: how test data must be shaped for a journey.

The profile is inferred from the package and saved as JSON so the user can
review and correct it. Keys of per-field maps are "DE name.Field name".
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import criteria
from .model import Package

DEFAULT_SETTINGS = {
    "records_per_case": 3,
    "control_group_sample_size": 50,
    "case_insensitive_text": True,
    "fictitious_email_domain": "example.invalid",
    "fictitious_phone": "333333333333",
    "engagement_mailbox": "",
    "mailbox_plus_addressing": True,
    "id_prefix": "CJT",
    "other_value": "TST_OTHER",
    "date_format": "%Y-%m-%d",
    "datetime_format": "%Y-%m-%d %H:%M",
    "engagement_wait_hours": 24,
    "candidates_per_round": 200,
    "max_exhaustive_scenarios": 200000,
    "greedy_restarts": 40,
    "seed": 42,
}

SQL_KEYWORDS = {"on", "where", "join", "left", "right", "inner", "outer", "full", "cross",
                "group", "order", "union", "and", "or", "select", "having"}


def fkey(de: str, field: str) -> str:
    return f"{de}.{field}"


def split_fkey(key: str, pkg: Package) -> tuple[str, str]:
    for de in sorted(pkg.des, key=len, reverse=True):
        if key.startswith(de + "."):
            return de, key[len(de) + 1:]
    raise KeyError(f"Unknown DE in '{key}'")


def load(path: str | Path) -> dict:
    prof = json.loads(Path(path).read_text(encoding="utf-8"))
    prof["settings"] = {**DEFAULT_SETTINGS, **prof.get("settings", {})}
    return prof


def save(prof: dict, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(prof, indent=2, ensure_ascii=False), encoding="utf-8")


def infer(pkg: Package) -> dict:
    notes: list[str] = []
    levels, scenario_keys = _levels(pkg, notes)
    entry = pkg.entry_de
    query = next((q for q in pkg.queries if entry and q.target_de == entry), None)
    automation = None
    if query:
        automation = next((a.name for a in pkg.automations if query.name in a.activity_names), None)

    fixed: dict[str, str] = {}
    date_rules: dict[str, str] = {}
    equalities: list[tuple[tuple[str, str], tuple[str, str]]] = []
    if query:
        tables, aliases = _sql_tables(query.sql, pkg)
        injection = list(dict.fromkeys(tables))
        _sql_rules(query.sql, aliases, injection, pkg, fixed, date_rules, equalities)
    else:
        cond_des = {c.var[0] for a in pkg.journey.activities.values() for o in a.outcomes
                    for c in criteria.conditions(o.criteria)}
        injection = [d for d in [entry, *sorted(cond_des)] if d and d in pkg.des]
        injection = list(dict.fromkeys(injection))
        notes.append("Entry DE is not populated by a query: test data goes straight into the entry DE.")

    # Contact Builder relationships are also key equalities
    for r in pkg.relationships:
        if r.left_de and r.left_field:
            equalities.append(((r.left_de, r.left_field), (r.right_de, r.right_field)))

    links = _links(pkg, injection, scenario_keys, equalities)
    for de in injection:
        if levels.get(de) is None:
            levels[de] = "scenario" if any(k.startswith(de + ".") and v == "scenario_key" for k, v in links.items()) \
                and not any(k.startswith(de + ".") and v == "contact_key" for k, v in links.items()) else "contact"
        if levels[de] == "contact" and not any(k.startswith(de + ".") and v == "contact_key" for k, v in links.items()):
            notes.append(f"{de}: no field linked to the contact key; check 'field_links'.")

    for a in pkg.journey.activities.values():
        expr = a.config.get("waitEndDateAttributeExpression") or ""
        m = re.search(r'Contacts\.(.+)\."([^"]+)"\}\}', expr)
        if m:
            de = m.group(1).split(".")[-1]
            date_rules[fkey(de, m.group(2))] = "yesterday"

    return {
        "journey": pkg.journey.name,
        "contact_de": pkg.contact_root_de,
        "contact_key": pkg.contact_key_field,
        "entry": {"de": entry, "automation": automation, "query": query.name if query else None},
        "de_levels": {de: levels.get(de, "contact") for de in sorted(set(levels) | set(injection))},
        "injection_des": injection,
        "field_links": links,
        "fixed_values": fixed,
        "date_rules": date_rules,
        "notes": notes,
        "settings": dict(DEFAULT_SETTINGS),
    }


def _levels(pkg: Package, notes: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    """Contact-level DEs join on the contact key; anything joined on another key is scenario-level."""
    levels: dict[str, str] = {}
    scenario_keys: dict[str, str] = {}
    if pkg.contact_root_de:
        levels[pkg.contact_root_de] = "contact"
    ck = (pkg.contact_key_field or "").lower()
    changed = True
    while changed:
        changed = False
        for r in pkg.relationships:
            if r.left_de is None or r.left_de not in levels or r.right_de in levels:
                continue
            same_key = (r.left_field or "").lower() == ck and r.right_field.lower() == ck
            if levels[r.left_de] == "contact" and same_key:
                levels[r.right_de] = "contact"
            else:
                levels[r.right_de] = "scenario"
                scenario_keys[r.right_de] = r.right_field
            changed = True
    if not pkg.contact_root_de:
        notes.append("No Contact Builder root found: all DEs treated as contact-level.")
    return levels, scenario_keys


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return re.sub(r"--[^\n]*", " ", sql)


def _canon_field(pkg: Package, de: str, name: str) -> str | None:
    d = pkg.des.get(de)
    f = d.field(name.strip("[]")) if d else None
    return f.name if f else None


def _sql_tables(sql: str, pkg: Package) -> tuple[list[str], dict[str, str]]:
    sql = _strip_comments(sql)
    tables, aliases = [], {}
    for m in re.finditer(r"\b(?:FROM|JOIN)\s+(?:ENT\.)?(?:\[([^\]]+)\]|([\w.]+))(?:\s+(?:AS\s+)?(\w+))?", sql, re.I):
        name = (m.group(1) or m.group(2)).strip()
        de = next((d for d in pkg.des if d.lower() == name.lower()), None)
        if not de:
            continue
        tables.append(de)
        alias = m.group(3)
        if alias and alias.lower() not in SQL_KEYWORDS:
            aliases[alias.lower()] = de
        aliases[de.lower()] = de
    return tables, aliases


def _sql_rules(sql, aliases, injection, pkg, fixed, date_rules, equalities) -> None:
    sql = _strip_comments(sql)
    col = r"(\w+)\.(\[[^\]]+\]|\w+)"
    for m in re.finditer(col + r"\s*=\s*" + col, sql):
        a, b = aliases.get(m.group(1).lower()), aliases.get(m.group(3).lower())
        fa = a and _canon_field(pkg, a, m.group(2))
        fb = b and _canon_field(pkg, b, m.group(4))
        if fa and fb:
            equalities.append(((a, fa), (b, fb)))
    for m in re.finditer(col + r"\s*=\s*'([^']*)'", sql):
        de = aliases.get(m.group(1).lower())
        f = de and _canon_field(pkg, de, m.group(2))
        if f:
            fixed[fkey(de, f)] = m.group(3)
    date_cmp = r"(?:CAST\(\s*)?GET(?:UTC)?DATE\(\)(?:\s+AS\s+DATE\s*\))?\s*(>=|<=|>|<)\s*(?:CAST\(\s*)?(?:(\w+)\.)?(\w+)"
    for m in re.finditer(date_cmp, sql, re.I):
        op, alias, name = m.groups()
        candidates = [aliases.get(alias.lower())] if alias else injection
        for de in candidates:
            f = de and _canon_field(pkg, de, name)
            if f:
                date_rules[fkey(de, f)] = "yesterday" if op in (">=", ">") else "tomorrow"
                break


def _links(pkg, injection, scenario_keys, equalities) -> dict[str, str]:
    parent: dict[tuple, tuple] = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in equalities:
        parent[find(a)] = find(b)
    seeds = {}
    if pkg.contact_root_de and pkg.contact_key_field:
        seeds[find((pkg.contact_root_de, pkg.contact_key_field))] = "contact_key"
    for de, f in scenario_keys.items():
        seeds.setdefault(find((de, f)), "scenario_key")
    links = {}
    for de in injection:
        for f in pkg.des[de].fields:
            role = seeds.get(find((de, f.name)))
            if role:
                links[fkey(de, f.name)] = role
    return links
