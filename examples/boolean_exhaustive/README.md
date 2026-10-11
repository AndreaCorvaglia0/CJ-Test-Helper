# boolean_exhaustive

Two splits that each test a Boolean for `true` and for `false`, then keep a remainder. The first field is
not nullable, so its remainder can never be taken; the second is nullable, so its remainder is the null
case. It checks the spec's rule "null when the schema allows it" in both directions.

## Journey

```
SPLIT-1 "Strict flag"                   (DE_Master.StrictFlag, Boolean, NOT nullable, default False)
  path_a          StrictFlag Is true  -> SPLIT-2
  path_b          StrictFlag Is false -> SPLIT-2
  remainder_path                      -> UPDATE-1 "Strict flag empty" -> exit

SPLIT-2 "Loose flag"                    (DE_Master.LooseFlag, Boolean, nullable)
  path_a          LooseFlag Is true   -> UPDATE-2 "Loose true"  -> exit
  path_b          LooseFlag Is false  -> UPDATE-3 "Loose false" -> exit
  remainder_path                      -> UPDATE-4 "Loose empty" -> exit
```

## Expected answer, step by step

1. **Values.** Spec step 4: "Each field takes the values named in conditions, one extra "other" value, and
   null when the schema allows it." StrictFlag: `True`, `False`, no null (not nullable). LooseFlag: `True`,
   `False`, null.
2. **SPLIT-1** (spec step 2, first true outcome wins): `True` -> `path_a`, `False` -> `path_b`. No value is
   left for the remainder: **`SPLIT-1/remainder_path` not covered, unreachable.**
3. **SPLIT-2**: `True` -> `path_a`, `False` -> `path_b`, null -> remainder. All three **covered**.
   This step relies on null not matching `Is false`. The spec does not say it; it is the plan's rule
   ("Any other operator on None -> False") and `docs/assumptions.md` row 7 ("An empty (null) Boolean does
   not match `Is false`; only `IsNull` matches it"), still to be verified on a real run. If that run shows
   the opposite, this remainder becomes unreachable too and this file must be updated with the evidence.
4. **Cases.** Each path ends after exactly one outcome of SPLIT-2 (the reachable terminal outcomes), so at
   least 3 cases; 3 suffice, because the two outcomes of SPLIT-1 can be spread over them. **1 scenario,
   3 cases, 9 contacts**, with LooseFlag `True`, `False` and null. StrictFlag is `True` in at least one case
   and `False` in another, but which case gets which is not fixed.
