# pilot_case_insensitive

The pilot export again, with `settings.case_insensitive_text: true` (and a real inbox). Not an acceptance
criterion of the spec: it exists to show where the earlier tool's reference numbers come from and to test
the setting on a large journey. Read `examples/pilot/README.md` first; notation is the same.

Spec, assumptions: "Text comparisons: whether `Email` and `EMAIL` are treated as equal. The PoC assumes they
are different by default; the earlier tool assumed they are equal, so this is a setting."

## What changes compared with `pilot`

1. **D42 `default_path_1` (CHANNEL2 Equal 'EMAIL') becomes reachable**: CHANNEL2 = `Email` reaches D42
   (through D13 `Email` and `Open_Click_Strategy` = true) and now equals `EMAIL`. Covered.
2. **D116 `default_path_1` (CHANNEL3 Equal 'EMAIL') becomes reachable** the same way. Covered.
3. **ENG3 and ENG5 become reachable, but only their No branches.** The argument of step 3 in the pilot
   README does not depend on letter case: the only paths into D42/D116 have CHANNEL1 not `Email`, and
   EMAILV2-1 is sent only when CHANNEL1 is `Email`. Spec: "The Yes branch counts as reachable only if the
   path sent the referenced email earlier. Otherwise it is reported as unreachable." So **ENG3 Yes and ENG5 Yes:
   not covered, `reason_contains: "unreachable"`**; **ENG3 No and ENG5 No: covered**. This is exactly the
   acceptance criterion's reason: "because all six engagement splits reference the first email".
4. **Behind ENG3 No (D106-D114) and ENG5 No (D153-D161): every outcome covered.** D153's first outcome
   (CHANNEL4 Equal 'EMAIL') is reached by CHANNEL4 = `Email` or `EMAIL`.
5. **ENG4 and ENG6 lie behind the unreachable Yes branches**: all their outcomes, and D70-D78, D97-D105,
   D117-D125, D144-D152 behind them, stay **not covered, unreachable**.
6. Everything else is as in `pilot` (ENG1, ENG2, R1, D1, the same 3 branches left out for the same reason).

Totals in `branches`: 256 listed; 91 not covered, 163 covered, 2 covered with manual action.

## Counts

**Scenarios >= 41**, by the pilot's argument with two more groups: (a) D61 needs 9 scenarios (CHANNEL1
`Email`, strategy true); (b) D106 behind ENG3 No needs 9 (strategy true, CHANNEL1 not `Email`, CHANNEL2
`Email`/`EMAIL`; they exit before D23); (c) D153 behind ENG5 No needs 9 (strategy true, CHANNEL2 in
`DM`/`OB`/`SMS`, CHANNEL3 `Email`/`EMAIL`); (d) D33 needs 9 (strategy false, or strategy true with
CHANNEL3 not `Email`); (e) the 2 leaves of D23 that reach neither D33 nor D116's first outcome; (f) D13's
remainder; (g) D2's remainder. The groups are disjoint: 9 + 9 + 9 + 9 + 2 + 1 + 1 = 40, plus the statistical
scenario = **41**, which is the earlier tool's "40 path scenarios plus 1 statistical".

**Cases >= 59**: 58 terminal outcomes are reachable without the random split (the pilot's 32 plus 13 behind
D106 and 13 behind D153), plus the statistical case. **Contacts >= 58 x 3 + 50 = 224.**

**Upper bounds 50 / 150 / 500** are a sanity margin chosen to include the earlier tool's figures: 148
deterministic cases + 1 statistical = 149 cases and 148 x 3 + 50 = 494 contacts. The earlier tool's case
count is well above the minimal 59, so it kept more cases than the smallest cover needs.

## Cross-check

The same independent exhaustive simulation as for `pilot`, run case-insensitively, gives exactly these
statuses for all 256 listed branches; a greedy scenario cover on it gives 40 deterministic scenarios.
