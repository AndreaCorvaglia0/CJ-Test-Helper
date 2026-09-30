"""Turn an engine path into expected, checkable outcomes."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .model import Package

ACTION_TYPES = {"EMAILV2", "UPDATECONTACTDATA", "STOWAIT", "SMSSYNC", "SMS", "PUSHNOTIFICATION"}


@dataclass
class Expectation:
    trail: list[str] = field(default_factory=list)       # decisions taken, readable
    actions: list[dict] = field(default_factory=list)    # checkable actions, in order
    tester_actions: list[str] = field(default_factory=list)
    exit_activity: str = ""
    summary: str = ""


def describe(pkg: Package, steps, engagement: dict) -> Expectation:
    acts = pkg.journey.activities
    exp = Expectation()
    labels = []
    for key, outcome in steps:
        a = acts[key]
        o = next((x for x in a.outcomes if x.key == outcome), None)
        if a.type in ("MULTICRITERIADECISION", "RANDOMSPLIT"):
            exp.trail.append(f"{a.name or a.key}: {o.label if o else outcome}")
        elif a.type == "ENGAGEMENTDECISION":
            yes = engagement.get(key, False)
            ref = a.config.get("refActivityCustomerKey", "")
            exp.trail.append(f"{a.name or a.key}: {'Yes' if yes else 'No'}")
            if yes:
                verb = "click a link in" if "click" in a.name.lower() else "open"
                exp.tester_actions.append(f"{verb} the email '{acts[ref].name if ref in acts else ref}' ({ref})")
        elif a.type == "EMAILV2":
            exp.actions.append({"type": "email", "activity": key, "name": a.name})
            labels.append(f"Email '{a.name}'")
        elif a.type == "UPDATECONTACTDATA":
            fields = (a.arguments.get("activityData") or {}).get("updateContactFields", [])
            values = {f.get("field", ""): _clean(f.get("value")) for f in fields}
            de = fields[0].get("dataExtensionId", "") if fields else ""
            exp.actions.append({"type": "update", "activity": key, "name": a.name, "de": de, "values": values})
            labels.append(a.name or "Update")
        elif a.type == "STOWAIT":
            exp.actions.append({"type": "sto_wait", "activity": key})
        elif a.type == "WAIT":
            expr = a.config.get("waitEndDateAttributeExpression")
            if expr:
                exp.actions.append({"type": "wait_attribute", "activity": key, "name": a.name})
    if steps:
        last = acts[steps[-1][0]]
        exp.exit_activity = f"{last.key} '{last.name}'" if last.name else last.key
    exp.summary = " > ".join(labels) if labels else "no action"
    return exp


def _clean(v) -> str:
    s = str(v)
    return "<execution time>" if "DateTime.Now" in s else s


def action_text(a: dict) -> str:
    if a["type"] == "email":
        return f"Email '{a['name']}' ({a['activity']}) sent"
    if a["type"] == "update":
        vals = ", ".join(f"{k}={v}" for k, v in a["values"].items())
        return f"{a['de']} updated by '{a['name']}' ({a['activity']}): {vals}"
    if a["type"] == "sto_wait":
        return f"Send-time-optimization wait ({a['activity']}): up to 24h delay"
    if a["type"] == "wait_attribute":
        return f"Wait by attribute '{a['name']}' ({a['activity']}) until the date set in the campaign configuration"
    return str(a)


def binomial_interval(n: int, p: float, level: float = 0.95) -> tuple[int, int]:
    """Central interval [lo, hi] holding at least `level` of the Binomial(n, p) mass."""
    pmf = [math.comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(n + 1)]
    tail = (1 - level) / 2
    acc, lo = 0.0, 0
    for k in range(n + 1):
        if acc + pmf[k] > tail:
            lo = k
            break
        acc += pmf[k]
    acc, hi = 0.0, n
    for k in range(n, -1, -1):
        if acc + pmf[k] > tail:
            hi = k
            break
        acc += pmf[k]
    return lo, hi
