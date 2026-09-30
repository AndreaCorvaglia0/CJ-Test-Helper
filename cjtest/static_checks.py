"""Static checks on the journey definition, independent of test execution."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from . import criteria
from .model import Package


@dataclass
class Finding:
    severity: str  # WARNING | INFO
    code: str
    message: str


def run(pkg: Package, unreachable_engagement: set | None = None) -> list[Finding]:
    out: list[Finding] = []
    acts = pkg.journey.activities
    parents: dict[str, list[str]] = defaultdict(list)
    for a in acts.values():
        for o in a.outcomes:
            if o.next:
                parents[o.next].append(a.key)

    # 1. engagement splits referencing an email that is not the closest upstream one
    for a in acts.values():
        if a.type != "ENGAGEMENTDECISION":
            continue
        ref = a.config.get("refActivityCustomerKey")
        nearest = _nearest_upstream(a.key, parents, acts, "EMAILV2")
        if ref and nearest and nearest != {ref}:
            out.append(Finding("WARNING", "ENGAGEMENT_REF",
                               f"{a.key} '{a.name}' checks engagement on {ref}, but on some paths the most recent "
                               f"email is another one ({', '.join(sorted(nearest - {ref}))})."))
    for g in sorted(unreachable_engagement or []):
        out.append(Finding("WARNING", "ENGAGEMENT_UNREACHABLE",
                           f"{g[0]} branch 'Yes' is unreachable: the referenced email is never sent on the "
                           f"paths that reach this split. Everything below it cannot be tested."))

    # 2. decision splits with the same name but different criteria
    variants: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for a in acts.values():
        if a.type == "MULTICRITERIADECISION" and a.name:
            sig = " | ".join(o.criteria.describe() for o in a.outcomes if o.criteria is not None)
            variants[a.name.strip().lower()][sig] += 1
    for name, sigs in sorted(variants.items()):
        if len(sigs) > 1:
            detail = "; ".join(f"{n}x [{s}]" for s, n in sigs.items())
            out.append(Finding("INFO", "SAME_NAME_DIFFERENT_CRITERIA",
                               f"Splits named '{name}' use {len(sigs)} different criteria: {detail}"))

    # 3. literal values spelled with different case
    spellings: dict[str, set[str]] = defaultdict(set)
    where: dict[str, set[str]] = defaultdict(set)
    for a in acts.values():
        for o in a.outcomes:
            for c in criteria.conditions(o.criteria):
                for v in c.values:
                    if v.lower() not in ("true", "false"):
                        spellings[v.lower()].add(v)
                        where[v].add(c.var[1])
    for low, forms in sorted(spellings.items()):
        if len(forms) > 1:
            detail = ", ".join(f"'{f}' ({'/'.join(sorted(where[f]))})" for f in sorted(forms))
            out.append(Finding("INFO", "LITERAL_CASE",
                               f"Value spelled in different ways: {detail}. Harmless only if comparisons "
                               f"are case-insensitive."))

    # 4. update-contact writing constants into primary-key fields
    constant_pk: dict[tuple, set] = defaultdict(set)
    for a in acts.values():
        if a.type != "UPDATECONTACTDATA":
            continue
        for f in (a.arguments.get("activityData") or {}).get("updateContactFields", []):
            de = pkg.des.get(f.get("dataExtensionId", ""))
            fname = f.get("field", "")
            val = str(f.get("value", ""))
            if de and fname in de.primary_key and "{{" not in val:
                constant_pk[(de.name, fname, val)].add(a.key)
    for (de, fname, val), keys in sorted(constant_pk.items()):
        extra = " With re-entry enabled, later entries overwrite earlier rows." if pkg.journey.entry_mode == "MultipleEntries" else ""
        out.append(Finding("WARNING", "CONSTANT_PK",
                           f"{len(keys)} Update Contact activities write the constant '{val}' into primary-key "
                           f"field {de}.{fname}.{extra}"))

    # 5. journey defaults pointing to another entry event
    trig_ev = pkg.event_definitions.get(pkg.journey.event_definition_id or "")
    if trig_ev:
        for channel, exprs in pkg.journey.defaults.items():
            if not isinstance(exprs, list):
                continue
            for e in exprs:
                m = re.search(r"Event\.([^.]+)\.", str(e))
                if m and m.group(1) != trig_ev.event_key:
                    other = next((ev.name for ev in pkg.event_definitions.values() if ev.event_key == m.group(1)), m.group(1))
                    out.append(Finding("WARNING", "DEFAULTS_EVENT",
                                       f"Journey default '{channel}' reads from event '{other}', not from the "
                                       f"entry event '{trig_ev.name}'."))

    # 6. one-to-one relationships on DEs whose primary key is wider than the join
    for r in pkg.relationships:
        de = pkg.des.get(r.right_de)
        if de and r.right_cardinality == "One" and r.left_cardinality == "One" and len(de.primary_key) > 1:
            out.append(Finding("INFO", "CARDINALITY",
                               f"Relationship to {r.right_de} on {r.right_field} is One-to-One, but the DE primary "
                               f"key is {', '.join(de.primary_key)}: several rows per contact are possible."))
    return out


def _nearest_upstream(key, parents, acts, type_) -> set[str]:
    found, seen, stack = set(), set(), list(parents.get(key, []))
    while stack:
        k = stack.pop()
        if k in seen:
            continue
        seen.add(k)
        if acts[k].type == type_:
            found.add(k)
        else:
            stack.extend(parents.get(k, []))
    return found
