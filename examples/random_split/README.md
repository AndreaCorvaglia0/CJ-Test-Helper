# random_split

A 90/10 random split at the start of the branch selected by a scenario-level flag, as in the pilot
(`control group required` -> `RANDOMSPLITV2-1`). Both random sides reach different update-contact steps;
the rest of the journey is also reachable without the random split.

## Journey

```
SPLIT-1 "Control group required"        (DE_Config."Control Group Required", Boolean, not nullable; name with spaces)
  path_a          Control Group Required Is true -> RANDOM-1
  remainder_path                                 -> SPLIT-2

RANDOM-1 (90/10)
  branchResult-1 90% -> UPDATE-1 "Treatment group" -> SPLIT-2
  branchResult-2 10% -> UPDATE-2 "Control group"   -> WAIT-1 (1 minute) -> exit

SPLIT-2 "Mail offers"                   (DE_Master.IsMailOffers, Boolean, nullable)
  path_a          IsMailOffers Is true -> UPDATE-3 "Offer sent" -> exit
  remainder_path                       -> UPDATE-4 "No offer"   -> exit
```

## Expected answer, step by step

1. **Tables and levels**: `DE_Entry`, `DE_Master` (contact), `DE_Config` (scenario); `DE_Log` written only.
2. **Spec, Special activities:** "Random split | Cannot be forced. The cover prefers paths that avoid it;
   branches reachable only through it get a statistical case of 50 contacts (configurable)."
3. **Which branches are reachable only through RANDOM-1?** Only its own two outcomes. `SPLIT-2`'s branches
   are reachable deterministically through `SPLIT-1/remainder_path` (`Control Group Required` = `False`),
   so the cover takes that route: `statistical: false` for them and for `SPLIT-1/remainder_path`.
4. **`SPLIT-1/path_a`: covered.** It lies before the random split: every contact of the statistical
   scenario crosses it with certainty. Whether it is flagged statistical is not asserted (it is covered
   only by the statistical case, but not *through* the random split; the model's comment "covered only
   through a random split" leaves this open).
5. **RANDOM-1 both outcomes: covered, `statistical: true`.** Spec, priority 3 "Done when": "Both branches
   of each have contacts and are flagged".
6. **The statistical case.** It needs `Control Group Required` = `True` (a scenario-level value), while
   every deterministic case needs `False`, so it is a scenario of its own: **2 scenarios**. It has
   `contact_count` 50 (setting "Contacts per random-split case | 50").
7. **Accepted range on the 10% side: 1 to 9.** Spec: "With a 90/10 random split, 50 contacts reach the 10%
   side at least once with about 99.5% probability. The testbook states the accepted range: 1 to 9
   contacts on the 10% side, which holds in about 97% of runs." Checked: for 50 draws at p = 0.1,
   P(X >= 1) = 0.9948 and P(1 <= X <= 9) = 0.9703. So `random.expected_low` = 1, `expected_high` = 9.
8. **Deterministic cases**: `Control Group Required` = `False` with IsMailOffers `True` -> UPDATE-3, and not
   `True` -> UPDATE-4 (each ends after a different exit outcome of SPLIT-2, so both are needed).
9. **Totals**: 2 deterministic cases + 1 statistical case = **3 cases**; 2 x 3 + 50 = **56 contacts**.

## Not asserted

- The statistical case's `end_activity` (its deterministic steps stop at RANDOM-1, per `docs/plan.md`:
  "for the statistical case it stops at the random split") and its contact class.
- The testbook note with the accepted range (priority 4).

## Format extensions used

- `branches[...].statistical` (compared with `BranchStatus.statistical`).
- `cases[...].random` = `{activity_key, expected_low, expected_high}` (compared with `Case.random`).
