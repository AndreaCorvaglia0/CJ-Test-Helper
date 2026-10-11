# random_then_contact_split

A 70/30 random split at the very start (no path avoids it), followed on the 70% side by a decision split on
a contact-level Boolean. Builder: `examples/build_fresh_examples.py`, `build_random_then_contact_split`.

## Journey

```
RANDOM-1 (start)  branchResult-1 70% -> SPLIT-2
                  branchResult-2 30% -> UPDATE-3 "Holdout" -> exit
SPLIT-2 "Flag"    (DE_Master.Flag, Boolean, nullable)
  path_a          Flag Is true -> UPDATE-1 "Flag set"     -> exit
  remainder_path               -> UPDATE-2 "Flag not set" -> exit
```

## Expected answer, step by step

1. Spec, Special activities: "Random split | Cannot be forced. The cover prefers paths that avoid it;
   branches reachable only through it get a statistical case of 50 contacts (configurable)." Here every
   branch is reachable only through RANDOM-1: all four are **covered, statistical**.
2. SPLIT-2's two outcomes need different contact-level values (Flag `True` vs not `True`). Step 6: "each
   distinct combination of contact-level values and manual actions is one case", so one statistical case
   cannot hold both: **two statistical cases**, Flag `True` and Flag not `True`, 50 contacts each.
3. **1 scenario, 2 cases, 100 contacts.**

## Ambiguity found while deriving (not asserted)

The accepted range on the 30% side. The spec only gives the 90/10 case ("1 to 9 contacts on the 10% side,
which holds in about 97% of runs") and no rule for other percentages. For 50 contacts at p = 0.3 the mean is
15 (sd 3.24); a ~97% central range would be about 8 to 22, but the spec does not say how the range is built,
so `expected_low` / `expected_high` are not asserted.
