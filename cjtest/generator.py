"""Synthetic records for every injected DE, with keys kept consistent across DEs."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from .engine import OTHER, Case, Result, Scenario
from .model import DEField, Package
from .profile import fkey


class GenerationError(ValueError):
    pass


def _wait_field(expr: str) -> str | None:
    m = re.search(r'Contacts\.(.+)\."([^"]+)"\}\}', expr or "")
    return fkey(m.group(1).split(".")[-1], m.group(2)) if m else None


@dataclass
class CaseRecords:
    case: Case
    contact_keys: list[str]
    emails: list[str]


@dataclass
class Dataset:
    run_id: str
    campaigns: dict[str, str]                                   # scenario id -> campaign name
    contact_rows: dict[str, list[dict]] = field(default_factory=dict)   # DE -> rows (all scenarios)
    scenario_rows: dict[str, dict[str, list[dict]]] = field(default_factory=dict)  # DE -> scenario -> rows
    case_records: dict[str, CaseRecords] = field(default_factory=dict)  # case id -> records
    engagement_deadlines: dict[str, str] = field(default_factory=dict)  # scenario id -> open/click before
    errors: list[str] = field(default_factory=list)


class Generator:
    def __init__(self, pkg: Package, prof: dict, result: Result, run_id: str, today: dt.date | None = None):
        self.pkg, self.prof, self.result, self.run_id = pkg, prof, result, run_id
        self.s = prof["settings"]
        self.today = today or dt.date.today()
        self.levels = prof["de_levels"]
        self.links = prof["field_links"]
        self.fixed = prof["fixed_values"]
        self.date_rules = prof["date_rules"]
        self.now = dt.datetime.combine(self.today, dt.datetime.now().time()).replace(second=0, microsecond=0)
        self._future_waits: set[str] = set()

    def build(self) -> Dataset:
        prefix = self.s["id_prefix"]
        ds = Dataset(self.run_id, {s.id: f"{prefix}_{self.run_id}_{s.id}" for s in self.result.scenarios})
        injection = self.prof["injection_des"]
        contact_des = [d for d in injection if self.levels.get(d) != "scenario"]
        scenario_des = [d for d in injection if self.levels.get(d) == "scenario"]
        self._check_variables(injection, ds)

        for de in contact_des:
            ds.contact_rows[de] = []
        for de in scenario_des:
            ds.scenario_rows[de] = {}

        for scen in self.result.scenarios:
            campaign = ds.campaigns[scen.id]
            self._future_waits = self._engagement_waits(scen)
            if self._future_waits:
                ds.engagement_deadlines[scen.id] = self._deadline()
            for de in scenario_des:
                ds.scenario_rows[de][scen.id] = [self._row(de, scen.assignment, None, campaign, "", ds)]
            for case, keys in self._contacts(scen):
                mails = [self._email(case, key) for key in keys]
                ds.case_records[case.id] = CaseRecords(case, keys, mails)
                for key, mail in zip(keys, mails):
                    for de in contact_des:
                        ds.contact_rows[de].append(self._row(de, case.contact, key, campaign, mail, ds))

        for de, rows in ds.contact_rows.items():
            self._check_pk(de, rows, ds)
        for de, by_scen in ds.scenario_rows.items():
            self._check_pk(de, [r for rows in by_scen.values() for r in rows], ds)
        return ds

    # -- contacts -------------------------------------------------------------------
    def _contacts(self, scen: Scenario):
        prefix = self.s["id_prefix"]
        if scen.kind == "statistical":
            case = scen.cases[0]
            keys = [f"{prefix}{self.run_id}{scen.id}N{n:03d}" for n in range(1, scen.contacts + 1)]
            yield case, keys
            return
        for n, case in enumerate(scen.cases, start=1):
            keys = [f"{prefix}{self.run_id}{scen.id}C{n:03d}R{r}" for r in range(1, self.s["records_per_case"] + 1)]
            yield case, keys

    def _email(self, case: Case, key: str) -> str:
        """Engagement 'Yes' needs a real mailbox; every other contact gets an undeliverable address.

        With plus-addressing the tester can tell which contact each email belongs to.
        """
        if not any(case.engagement.values()):
            return f"{key.lower()}@{self.s['fictitious_email_domain']}"
        box = self.s.get("engagement_mailbox") or ""
        if not box:
            raise GenerationError(f"Case {case.id} needs a real mailbox for engagement: set "
                                  f"settings.engagement_mailbox in the profile")
        if self.s.get("mailbox_plus_addressing", True) and "@" in box:
            local, domain = box.split("@", 1)
            return f"{local}+{key.lower()}@{domain}"
        return box

    def _engagement_waits(self, scen: Scenario) -> set[str]:
        """Wait-by-attribute fields that precede an engagement split the tester must trigger.

        The split evaluates engagement when the contact reaches it, so the wait before
        it must leave the tester time to open/click.
        """
        acts = self.pkg.journey.activities
        fields: set[str] = set()
        for case in scen.cases:
            for i, (key, _) in enumerate(case.steps):
                if not case.engagement.get(key):
                    continue
                for prev, _ in reversed(case.steps[:i]):
                    expr = acts[prev].config.get("waitEndDateAttributeExpression") or ""
                    k = _wait_field(expr)
                    if k:
                        fields.add(k)
                        break
                    if acts[prev].type == "EMAILV2":
                        self.result.warnings.append(
                            f"{case.id}: no wait-by-attribute between the email and {key}; the tester may not "
                            f"have time to engage before the split is evaluated")
                        break
        return fields

    def _deadline(self) -> str:
        return (self.now + dt.timedelta(hours=self.s["engagement_wait_hours"])).strftime(self.s["datetime_format"])

    # -- rows -------------------------------------------------------------------------
    def _row(self, de: str, assignment: dict, contact_key: str | None, campaign: str, email: str, ds: Dataset) -> dict:
        row = {}
        for f in self.pkg.des[de].fields:
            value = self._value(de, f, assignment, contact_key, campaign, email)
            self._validate(de, f, value, ds)
            row[f.name] = value
        return row

    def _value(self, de: str, f: DEField, assignment: dict, contact_key, campaign, email) -> str:
        k = fkey(de, f.name)
        link = self.links.get(k)
        if link == "contact_key":
            return contact_key or ""
        if link == "scenario_key":
            return campaign
        var = (de, f.name)
        if var in assignment:
            return self._fmt(assignment[var], f)
        if k in self.fixed:
            return self.fixed[k]
        if k in self._future_waits:
            return self._deadline()
        if k in self.date_rules:
            return self._date(self.date_rules[k])
        t = f.type.lower()
        if t == "emailaddress":
            return email
        if t == "phone":
            return self.s["fictitious_phone"]
        if f.is_nullable:
            if t in ("boolean", "date", "number", "decimal"):
                return ""
            return f"TST_{f.name}".replace(" ", "_")[: f.length or 50]
        if f.default:
            return self._date("today") if f.default.lower().startswith("getdate") else f.default
        return {"boolean": "False", "date": self._date("today"), "number": "0", "decimal": "0"}.get(
            t, f"TST_{f.name}".replace(" ", "_")[: f.length or 50])

    def _fmt(self, value, f: DEField) -> str:
        if value is None:
            return ""
        if value == OTHER:
            return self.s["other_value"]
        if f.type.lower() == "boolean":
            return "True" if str(value).lower() == "true" else "False"
        return str(value)

    def _date(self, rule: str) -> str:
        delta = {"yesterday": -1, "today": 0, "tomorrow": 1}.get(rule)
        if delta is None:
            raise GenerationError(f"Unknown date rule '{rule}'")
        return (self.today + dt.timedelta(days=delta)).strftime(self.s["date_format"])

    # -- validation ---------------------------------------------------------------------
    def _validate(self, de: str, f: DEField, value: str, ds: Dataset) -> None:
        if not f.is_nullable and value == "":
            ds.errors.append(f"{de}.{f.name}: empty value in a non-nullable field")
        if f.length and len(value) > f.length and f.type.lower() not in ("boolean", "date"):
            ds.errors.append(f"{de}.{f.name}: '{value}' exceeds length {f.length}")

    def _check_pk(self, de: str, rows: list[dict], ds: Dataset) -> None:
        pk = self.pkg.des[de].primary_key
        if not pk:
            return
        seen = set()
        for r in rows:
            key = tuple(r[p] for p in pk)
            if key in seen:
                ds.errors.append(f"{de}: duplicate primary key {key}")
            seen.add(key)

    def _check_variables(self, injection: list[str], ds: Dataset) -> None:
        for v in self.result.scenario_vars + self.result.contact_vars:
            if v[0] not in injection:
                ds.errors.append(f"Split variable {v[0]}.{v[1]} lives in a DE that is not loaded by the test "
                                 f"data: its value cannot be controlled")
