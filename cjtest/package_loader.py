"""Input adapter (level 3): SFMC Package Manager export (JSON) -> Package."""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import criteria
from .model import (Activity, Automation, DataExtension, DEField, EventDefinition, Journey,
                    Outcome, Package, QueryActivity, Relationship)

REF = re.compile(r"\{\{mcpm#/entities/(\w+)/([^/}]+)/data/([^}]*)\}\}")


class PackageError(ValueError):
    pass


def load(path: str | Path, journey_id: str | None = None) -> Package:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    ents = raw.get("entities")
    if not isinstance(ents, dict):
        raise PackageError("Not a Package Manager export: 'entities' missing")
    return _Builder(ents).build(journey_id or _selected_journey(raw))


def _selected_journey(raw: dict) -> str | None:
    sel = (raw.get("selectedEntities") or {}).get("journeys") or []
    return sel[0] if sel else None


def _items(ents: dict, kind: str) -> dict[str, dict]:
    return {k: (v.get("data") or {}) for k, v in (ents.get(kind) or {}).items()}


class _Builder:
    def __init__(self, ents: dict):
        self.ents = ents
        self.warnings: list[str] = []
        self.des_raw = _items(ents, "dataExtensions")
        self.sets_raw = _items(ents, "attributeSets")
        self.groups_raw = _items(ents, "attributeGroups")
        self.events_raw = _items(ents, "eventDefinitions")
        self.queries_raw = _items(ents, "queryActivities")

    # -- placeholder resolution ------------------------------------------------
    def _set_de(self, set_id: str) -> str:
        data = self.sets_raw.get(set_id, {})
        ref = (data.get("storageReferenceID") or {}).get("value", "")
        m = REF.search(ref)
        if m and m.group(1) == "dataExtensions":
            return self.des_raw.get(m.group(2), {}).get("name", data.get("name", set_id))
        return data.get("name", set_id)

    def resolve(self, text):
        if not isinstance(text, str):
            return text
        return REF.sub(self._sub, text)

    def _sub(self, m: re.Match) -> str:
        kind, eid, prop = m.groups()
        if kind == "dataExtensions":
            d = self.des_raw.get(eid, {})
            if prop in ("name", "id"):
                return d.get("name", eid)
            if prop == "namePrefix":
                return ""
            if prop == "customerKey":
                return d.get("customerKey", eid)
            fm = re.match(r"fields/name:(.+)/id$", prop)
            if fm:
                return fm.group(1)
        if kind == "attributeSets" and prop in ("name", "id"):
            return self._set_de(eid)
        if kind == "attributeGroups" and prop in ("name", "id"):
            return self.groups_raw.get(eid, {}).get("name", eid)
        if kind == "eventDefinitions":
            if prop == "eventDefinitionKey":
                return self.events_raw.get(eid, {}).get("eventDefinitionKey", eid)
            if prop == "id":
                return eid
        if kind == "queryActivities" and prop == "name":
            return self.queries_raw.get(eid, {}).get("name", eid)
        if kind == "attributeRelationships" and prop == "id":
            return eid
        return m.group(0)

    # -- builders -------------------------------------------------------------
    def build(self, journey_id: str | None) -> Package:
        des = {d["name"]: self._de(d) for d in self.des_raw.values()}
        rels = [self._rel(r) for r in _items(self.ents, "attributeRelationships").values()]
        root = next((r for r in rels if r.left_de is None), None)
        events = {eid: EventDefinition(eid, e.get("name", ""), e.get("type", ""),
                                       e.get("eventDefinitionKey", ""), self.resolve(e.get("dataExtensionId")))
                  for eid, e in self.events_raw.items()}
        journeys = _items(self.ents, "journeys")
        if not journeys:
            raise PackageError("The package contains no journey")
        jid = journey_id if journey_id in journeys else next(iter(journeys))
        journey = self._journey(journeys[jid], des)
        queries = [QueryActivity(q.get("name", ""), self.resolve(q.get("queryText", "")),
                                 self.resolve(q.get("targetId")), q.get("targetUpdateTypeName", ""))
                   for q in self.queries_raw.values()]
        autos = [Automation(a.get("name", ""),
                            [self.resolve(act.get("name", "")) for s in a.get("steps", []) for act in s.get("activities", [])])
                 for a in _items(self.ents, "automations").values()]
        return Package(des=des, relationships=rels,
                       contact_root_de=root.right_de if root else None,
                       contact_key_field=root.right_field if root else None,
                       journey=journey, event_definitions=events, queries=queries,
                       automations=autos, warnings=self.warnings)

    def _de(self, d: dict) -> DataExtension:
        fields = [DEField(f.get("name", ""), f.get("type", "Text"), f.get("length"),
                          bool(f.get("isPrimaryKey")), bool(f.get("isNullable", True)),
                          f.get("defaultValue") or None)
                  for f in d.get("fields", [])]
        return DataExtension(d.get("name", ""), d.get("customerKey", ""), fields,
                             bool(d.get("isSendable")), d.get("sendableCustomObjectField") or None)

    def _rel(self, r: dict) -> Relationship:
        left, right = r.get("leftItem") or {}, r.get("rightItem") or {}
        attrs = (r.get("relationshipAttributes") or [{}])[0]
        is_group = left.get("relationshipType") == "AttributeGroup"
        return Relationship(
            name=r.get("name", ""),
            left_de=None if is_group else self.resolve(left.get("identifier")),
            right_de=self.resolve(right.get("name") or right.get("identifier")),
            left_field=attrs.get("leftAttributeName"),
            right_field=attrs.get("rightAttributeName", ""),
            left_cardinality=left.get("cardinality", ""),
            right_cardinality=right.get("cardinality", ""))

    def _resolve_key(self, key: str, entry_de: str | None) -> criteria.Var:
        m = re.match(r"^\{\{mcpm#/entities/attributeSets/([^/}]+)/data/name\}\}\.(.+)$", key)
        if m:
            return self._set_de(m.group(1)), m.group(2).strip('"')
        k = self.resolve(key)
        em = re.match(r'^Event\.[^.]+\.(.+)$', k)
        if em and entry_de:
            return entry_de, em.group(1).strip('"')
        self.warnings.append(f"Unresolved criteria key: {key}")
        return "?", k

    def _journey(self, j: dict, des: dict) -> Journey:
        trigger = (j.get("triggers") or [{}])[0]
        ev_id = self.resolve((trigger.get("metaData") or {}).get("eventDefinitionId"))
        entry_de = self.resolve(self.events_raw.get(ev_id or "", {}).get("dataExtensionId"))
        acts: dict[str, Activity] = {}
        for a in j.get("activities", []):
            crit = (a.get("configurationArguments") or {}).get("criteria")
            outcomes = []
            for o in a.get("outcomes", []):
                parsed = None
                if isinstance(crit, dict) and crit.get(o.get("key")):
                    parsed = criteria.parse(crit[o["key"]], lambda k: self._resolve_key(k, entry_de))
                label = (o.get("metaData") or {}).get("label") or (o.get("metaData") or {}).get("criteriaDescription") or o.get("key", "")
                outcomes.append(Outcome(o.get("key", ""), label, o.get("next") or None, parsed, o.get("arguments") or {}))
            acts[a["key"]] = Activity(a["key"], a.get("type", ""), a.get("name", ""), outcomes,
                                      self._resolved(a.get("configurationArguments")),
                                      self._resolved(a.get("arguments")))
        referenced = {o.next for a in acts.values() for o in a.outcomes if o.next}
        roots = [k for k in acts if k not in referenced]
        if not roots:
            raise PackageError("Cannot find the journey's first activity")
        if len(roots) > 1:
            self.warnings.append(f"Multiple root activities, using {roots[0]}: {roots}")
        return Journey(j.get("name", ""), j.get("key", ""), j.get("entryMode", ""), acts, roots[0],
                       self._resolved(j.get("defaults")), ev_id)

    def _resolved(self, obj) -> dict:
        """Deep copy of a JSON object with every mcpm placeholder resolved."""
        return json.loads(self.resolve(json.dumps(obj or {})))
