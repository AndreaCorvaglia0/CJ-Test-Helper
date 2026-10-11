# unsupported_operator

A decision split whose condition uses an operator outside the spec's list (`Between`). Found while trying to
break the generator: on 11 October 2026 the pipeline raised `UnsupportedOperator` on this package instead
of reporting it.

## Journey

```
SPLIT-1 "Mail offers"                   (DE_Master.IsMailOffers, Boolean, nullable)
  path_a          IsMailOffers Is true -> SPLIT-2
  remainder_path                       -> UPDATE-1 "No offers" -> exit

SPLIT-2 "Postal code range"             (DE_Master.PostalCode, Text(10))
  path_a          PostalCode Between '10000' -> UPDATE-2 "North"     -> exit
  remainder_path                             -> UPDATE-3 "Elsewhere" -> exit
```

## Expected answer, step by step

1. **`Between` is unsupported.** Spec, "Supported in the PoC": "Condition operators | `Is`, `Equal`,
   `IsNull`", and "The earlier tool's condition parser also handled not-equal, numeric comparisons,
   contains, begins-with, ends-with and is-not-null." `Between` is none of these.
2. **No crash.** Spec: "Anything else is not an error: it is listed in the report, and the branches behind
   it are marked as not covered. New activity types and operators are added by extending one lookup table
   each." Known limits: "Only the listed activity types, operators and SQL patterns are understood; the rest
   is reported, not guessed."
3. **SPLIT-2, both outcomes: not covered, reason mentioning the unsupported element.** Whether a contact
   takes `path_a` or the remainder depends on the unknown operator; the remainder means "none matched"
   (spec step 2), which cannot be decided either. Guessing either way would break "not guessed".
4. **SPLIT-1, both outcomes: covered.** They lie before the unsupported condition. The IsMailOffers `True`
   case crosses `path_a` and stops at SPLIT-2, as the `unsupported_element` example stops at its unknown
   activity.
5. **Cases**: IsMailOffers `True` (stops at SPLIT-2) and not `True` (UPDATE-1). **1 scenario, 2 cases,
   6 contacts.**

## Not asserted

- Where the report lists the unsupported operator (`CoverageResult.unsupported` "activity keys stopped as
  unsupported", or a warning): the spec only says "listed in the report".
- The first case's `end_activity` (`SPLIT-2` if the simulation stops when it meets the condition).
