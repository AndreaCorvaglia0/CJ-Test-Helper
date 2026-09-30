"""Test-case derivation.

Split variables are divided into scenario-level (shared by every contact of one
run, e.g. campaign configuration) and contact-level. The engine:

1. groups contact assignments into classes that evaluate every contact
   criterion the same way (same class => same path);
2. picks a small set of scenarios that covers every decision/engagement outcome
   (greedy set cover over sampled scenario assignments), avoiding random splits;
3. walks the journey for each scenario x contact class, branching on engagement
   splits, and turns every distinct path into a test case;
4. builds one statistical scenario per random split.

Assumption (to verify on the platform): decision-split outcomes are evaluated in
the order they appear, the first match wins, the remainder is taken otherwise.
"""
from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field

from . import criteria
from .criteria import Var
from .model import Package

DECISION = "MULTICRITERIADECISION"
ENGAGEMENT = "ENGAGEMENTDECISION"
RANDOM = "RANDOMSPLIT"
OTHER = "__OTHER__"
MAX_CONTACT_COMBOS = 20000

Step = tuple[str, str]  # (activity key, outcome key)


@dataclass
class Leaf:
    steps: tuple[Step, ...]
    engagement: tuple[tuple[str, bool], ...]
    random: tuple[Step, ...]


@dataclass
class Case:
    id: str
    scenario_id: str
    steps: tuple[Step, ...]
    engagement: dict[str, bool]
    contact: dict[Var, str | None]
    classes: int = 1


@dataclass
class Scenario:
    id: str
    kind: str  # path | statistical
    assignment: dict[Var, str | None]
    cases: list[Case] = field(default_factory=list)
    contacts: int = 0  # statistical scenarios only
    random_expectation: list[dict] = field(default_factory=list)


@dataclass
class Result:
    scenarios: list[Scenario]
    goals: list[Step]
    covered: set[Step]
    covered_statistical: set[Step]
    unreachable_engagement: set[Step]
    blocked_by_engagement: set[Step]
    scenario_vars: list[Var]
    contact_vars: list[Var]
    domains: dict[Var, list]
    warnings: list[str]

    @property
    def uncovered(self) -> list[Step]:
        done = self.covered | self.covered_statistical
        return [g for g in self.goals if g not in done]


class Engine:
    def __init__(self, pkg: Package, prof: dict):
        self.pkg = pkg
        self.acts = pkg.journey.activities
        self.settings = prof["settings"]
        self.ci = bool(self.settings["case_insensitive_text"])
        self.rng = random.Random(self.settings["seed"])
        self.warnings: list[str] = []
        levels = prof["de_levels"]

        self.formulas: list[tuple[str, int, object]] = []  # (activity, outcome index, criteria)
        all_vars: set[Var] = set()
        for a in self.acts.values():
            if a.type == DECISION:
                for i, o in enumerate(a.outcomes):
                    if o.criteria is not None:
                        self.formulas.append((a.key, i, o.criteria))
                        all_vars |= criteria.variables(o.criteria)
        for v in sorted(all_vars):
            if v[0] not in levels:
                self.warnings.append(f"DE '{v[0]}' has no level in the profile: treated as contact-level")
        self.scenario_vars = sorted(v for v in all_vars if levels.get(v[0]) == "scenario")
        self.contact_vars = sorted(v for v in all_vars if levels.get(v[0]) != "scenario")
        self.domains = {v: self._domain(v) for v in all_vars}

        self.goals: list[Step] = [(a.key, o.key) for a in self.acts.values()
                                  if a.type in (DECISION, ENGAGEMENT) for o in a.outcomes]
        self.random_acts = [a.key for a in self.acts.values() if a.type == RANDOM]
        self._class_cache: list | None = None
        self._cover_cache: dict[tuple, tuple[frozenset, bool]] = {}

    # -- domains ----------------------------------------------------------------
    def _domain(self, var: Var) -> list:
        de = self.pkg.des.get(var[0])
        f = de.field(var[1]) if de else None
        nullable = f.is_nullable if f else True
        ftype = (f.type if f else "Text").lower()
        if not f:
            self.warnings.append(f"Field {var[0]}.{var[1]} not found in the package")
        if ftype == "boolean":
            values: list = ["true", "false"]
        else:
            literals: dict[str, str] = {}
            numeric = ftype in ("number", "decimal")
            for _, _, crit in self.formulas:
                for c in criteria.conditions(crit):
                    if c.var != var:
                        continue
                    for lit in c.values:
                        literals.setdefault(lit.lower() if self.ci else lit, lit)
                        if numeric and c.op.lower() in criteria.NUMERIC:
                            try:
                                n = float(lit)
                                for x in (n - 1, n + 1):
                                    s = str(int(x)) if x.is_integer() else str(x)
                                    literals.setdefault(s, s)
                            except ValueError:
                                pass
            values = list(literals.values()) + [OTHER]
        if nullable:
            values.append(None)
        return values

    # -- journey walk -------------------------------------------------------------
    def _decide(self, act, assign) -> int:
        for i, o in enumerate(act.outcomes):
            if o.criteria is None:
                return i
            try:
                if criteria.evaluate(o.criteria, lambda v: _value(assign.get(v)), self.ci):
                    return i
            except criteria.UnsupportedOperator as e:
                msg = f"{act.key}: {e}"
                if msg not in self.warnings:
                    self.warnings.append(msg)
        return len(act.outcomes) - 1

    def walk(self, assign: dict, engagement_all_no: bool = False) -> list[Leaf]:
        leaves: list[Leaf] = []

        def go(key, steps, eng, rnd, seen):
            while key:
                if key in seen:
                    self.warnings.append(f"Loop detected at {key}")
                    break
                seen = seen | {key}
                act = self.acts.get(key)
                if act is None or not act.outcomes:
                    break
                if act.type == DECISION:
                    o = act.outcomes[self._decide(act, assign)]
                    steps = steps + ((key, o.key),)
                    key = o.next
                    continue
                if act.type == ENGAGEMENT:
                    ref = act.config.get("refActivityCustomerKey")
                    sent = ref is None or any(s[0] == ref for s in steps)
                    for o in act.outcomes:
                        when = bool(o.arguments.get("when"))
                        if when and (not sent or engagement_all_no):
                            continue
                        go(o.next, steps + ((key, o.key),), eng + ((key, when),), rnd, seen)
                    return
                if act.type == RANDOM or len(act.outcomes) > 1:
                    for o in act.outcomes:
                        go(o.next, steps + ((key, o.key),), eng, rnd + ((key, o.key),), seen)
                    return
                o = act.outcomes[0]
                steps = steps + ((key, o.key),)
                key = o.next
            leaves.append(Leaf(steps, eng, rnd))

        go(self.pkg.journey.root, (), (), (), frozenset())
        return leaves

    # -- contact classes ------------------------------------------------------------
    def _contact_combos(self):
        doms = [self.domains[v] for v in self.contact_vars]
        total = 1
        for d in doms:
            total *= len(d)
        if total <= MAX_CONTACT_COMBOS:
            for combo in itertools.product(*doms):
                yield dict(zip(self.contact_vars, combo))
        else:
            self.warnings.append(f"{total} contact combinations: sampled {MAX_CONTACT_COMBOS}")
            for _ in range(MAX_CONTACT_COMBOS):
                yield {v: self.rng.choice(d) for v, d in zip(self.contact_vars, doms)}

    def contact_classes(self, scenario: dict) -> list[dict]:
        cvars = set(self.contact_vars)
        relevant = [(a, i, f) for a, i, f in self.formulas if criteria.variables(f) & cvars]
        mixed = any(criteria.variables(f) - cvars for _, _, f in relevant)
        if not mixed and self._class_cache is not None:
            return self._class_cache
        classes: dict[tuple, dict] = {}
        for combo in self._contact_combos():
            assign = {**scenario, **combo}
            vec = tuple(_safe_eval(f, assign, self.ci) for _, _, f in relevant)
            if vec not in classes:
                classes[vec] = combo
        result = list(classes.values())
        if not mixed:
            self._class_cache = result
        return result

    # -- coverage -----------------------------------------------------------------
    def coverage(self, scenario: dict) -> tuple[frozenset, bool]:
        key = tuple(scenario.get(v) for v in self.scenario_vars)
        if key not in self._cover_cache:
            hit: set[Step] = set()
            deterministic = True
            for combo in self.contact_classes(scenario):
                for leaf in self.walk({**scenario, **combo}):
                    hit.update(leaf.steps)
                    if leaf.random:
                        deterministic = False
            self._cover_cache[key] = (frozenset(hit), deterministic)
        return self._cover_cache[key]

    def _random_scenario(self) -> dict:
        return {v: self.rng.choice(self.domains[v]) for v in self.scenario_vars}

    def _targeted_scenario(self, goal: Step) -> dict:
        """Random scenario whose scenario-level variables select `goal` at its decision."""
        scen = self._random_scenario()
        act = self.acts[goal[0]]
        if act.type != DECISION:
            return scen
        idx = next(i for i, o in enumerate(act.outcomes) if o.key == goal[1])
        svars = set(self.scenario_vars)
        involved = sorted({v for o in act.outcomes for v in criteria.variables(o.criteria)})
        if not involved or any(v not in svars for v in involved):
            return scen
        options = [dict(zip(involved, c)) for c in itertools.product(*(self.domains[v] for v in involved))
                   if self._decide(act, {**scen, **dict(zip(involved, c))}) == idx]
        if options:
            scen.update(self.rng.choice(options))
        return scen

    def select_scenarios(self) -> list[dict]:
        total = 1
        for v in self.scenario_vars:
            total *= len(self.domains[v])
        if total <= self.settings["max_exhaustive_scenarios"]:
            chosen = self._select_exhaustive()
        else:
            self.warnings.append(f"{total} scenario combinations: sampled, coverage may be incomplete")
            chosen = self._select_sampled()
        # drop scenarios made redundant by later picks
        for scen in list(chosen):
            others = set().union(*(self.coverage(s)[0] for s in chosen if s is not scen)) if len(chosen) > 1 else set()
            if self.coverage(scen)[0] <= others:
                chosen.remove(scen)
        return chosen

    def _select_exhaustive(self) -> list[dict]:
        """Greedy set cover over every deterministic scenario, using bitmasks."""
        bit = {g: 1 << i for i, g in enumerate(self.goals)}
        pool: dict[int, dict] = {}
        for combo in itertools.product(*(self.domains[v] for v in self.scenario_vars)):
            scen = dict(zip(self.scenario_vars, combo))
            hit, det = self.coverage(scen)
            if not det:
                continue
            mask = sum(bit[g] for g in hit if g in bit)
            pool.setdefault(mask, scen)  # equivalent scenarios collapse on the same mask
        self._cover_cache.clear()
        # drop masks strictly contained in another one: they can never be a better pick
        masks = sorted(pool, key=int.bit_count, reverse=True)
        kept: list[int] = []
        for m in masks:
            if not any(m | k == k for k in kept):
                kept.append(m)
        best: list[int] | None = None
        for attempt in range(self.settings["greedy_restarts"]):
            chosen = self._greedy(kept, sum(bit.values()), randomize=attempt > 0)
            if best is None or len(chosen) < len(best):
                best = chosen
        return [pool[m] for m in best or []]

    def _greedy(self, masks: list[int], target: int, randomize: bool) -> list[int]:
        chosen: list[int] = []
        uncovered = target
        while uncovered:
            gains = [(m & uncovered).bit_count() for m in masks]
            top = max(gains)
            if top == 0:
                break
            ties = [m for m, g in zip(masks, gains) if g == top]
            m = self.rng.choice(ties) if randomize else ties[0]
            chosen.append(m)
            uncovered &= ~m
        # reverse-delete redundant picks
        for m in list(reversed(chosen)):
            rest = 0
            for o in chosen:
                if o != m:
                    rest |= o
            if (m & target) | rest == rest:
                chosen.remove(m)
        return chosen

    def _select_sampled(self) -> list[dict]:
        uncovered = set(self.goals)
        chosen: list[dict] = []
        idle = 0
        while uncovered and idle < 4:
            targets = sorted(uncovered)
            pool = [self._targeted_scenario(self.rng.choice(targets)) if i % 2 == 0 else self._random_scenario()
                    for i in range(self.settings["candidates_per_round"])]
            best, best_gain = None, 0
            for scen in pool:
                hit, det = self.coverage(scen)
                gain = len(hit & uncovered)
                if det and gain > best_gain:
                    best, best_gain = scen, gain
            if best is None:
                idle += 1
                continue
            idle = 0
            chosen.append(best)
            uncovered -= self.coverage(best)[0]
        return chosen

    # -- cases ----------------------------------------------------------------------
    def derive(self) -> Result:
        scenarios: list[Scenario] = []
        covered: set[Step] = set()
        for n, scen in enumerate(self.select_scenarios(), start=1):
            s = Scenario(f"S{n:02d}", "path", scen)
            by_path: dict[tuple, Case] = {}
            for combo in self.contact_classes(scen):
                for leaf in self.walk({**scen, **combo}):
                    if leaf.steps in by_path:
                        by_path[leaf.steps].classes += 1
                        continue
                    by_path[leaf.steps] = Case(f"{s.id}-C{len(by_path) + 1:03d}", s.id, leaf.steps,
                                               dict(leaf.engagement), combo)
                    covered.update(leaf.steps)
            s.cases = list(by_path.values())
            scenarios.append(s)

        covered_stat: set[Step] = set()
        for rkey in self.random_acts:
            stat = self._statistical(rkey, len(scenarios) + 1)
            if stat:
                scenarios.append(stat)
                for exp in stat.random_expectation:
                    covered_stat.update(exp["steps"])
            else:
                self.warnings.append(f"No scenario found that reaches random split {rkey}")

        unreachable = set()
        for g in self.goals:
            act = self.acts[g[0]]
            if act.type == ENGAGEMENT and g not in covered and g not in covered_stat:
                o = next(o for o in act.outcomes if o.key == g[1])
                if o.arguments.get("when"):
                    unreachable.add(g)
        blocked = self._downstream_only(unreachable) - covered - covered_stat - unreachable
        return Result(scenarios, self.goals, covered, covered_stat - covered, unreachable, blocked,
                      self.scenario_vars, self.contact_vars, self.domains, self.warnings)

    def _downstream_only(self, cut: set[Step]) -> set[Step]:
        """Goals structurally reachable only through the `cut` outcomes."""
        seen, stack = set(), [self.pkg.journey.root]
        while stack:
            k = stack.pop()
            if k in seen or k not in self.acts:
                continue
            seen.add(k)
            for o in self.acts[k].outcomes:
                if o.next and (k, o.key) not in cut:
                    stack.append(o.next)
        return {g for g in self.goals if g[0] not in seen}

    def _statistical(self, rkey: str, number: int) -> Scenario | None:
        for _ in range(self.settings["candidates_per_round"] * 5):
            scen = self._random_scenario()
            for combo in self.contact_classes(scen):
                leaves = [l for l in self.walk({**scen, **combo}, engagement_all_no=True)
                          if any(r[0] == rkey for r in l.random)]
                if not leaves:
                    continue
                act = self.acts[rkey]
                expectation = []
                for o in act.outcomes:
                    leaf = next((l for l in leaves if (rkey, o.key) in l.random), None)
                    expectation.append({"outcome": o.key, "label": o.label,
                                        "percentage": o.arguments.get("percentage"),
                                        "steps": leaf.steps if leaf else ()})
                s = Scenario(f"S{number:02d}", "statistical", scen,
                             contacts=int(self.settings["control_group_sample_size"]),
                             random_expectation=expectation)
                s.cases = [Case(f"{s.id}-C001", s.id, leaves[0].steps, {}, combo)]
                return s
        return None


def _value(v):
    return "__other__value__" if v == OTHER else v


def _safe_eval(f, assign, ci) -> bool:
    try:
        return criteria.evaluate(f, lambda v: _value(assign.get(v)), ci)
    except criteria.UnsupportedOperator:
        return False
