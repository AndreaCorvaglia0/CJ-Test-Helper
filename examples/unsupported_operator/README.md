# unsupported_operator

A decision split whose condition the generator cannot evaluate. Found while trying to break the generator: on
11 October 2026 the pipeline raised `UnsupportedOperator` on this package instead of reporting it.

**Correction, 12 October 2026.** When this example was written, `Between` was outside the spec's operator list.
The section "Extensions beyond the pilot" added it: "Supported operators: ... `Between` ... `Between` takes the
value `low|high`". The condition here is `PostalCode Between '10000'`, a value not written `low|high`, so it is
still not evaluable and the expected answer does not change; only its reason does (step 1). An operator outside
the list (`NotContains`) is now covered by the unit tests in `tests/test_loader.py`
(`test_unsupported_operator_is_reported`) and `tests/test_criteria.py`.

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

1. **This `Between` is unsupported.** Spec, "Operators, types and values": "`Between` takes the value
   `low|high`". `'10000'` has no `|`, so the bounds cannot be read and the branch is reported as unsupported,
   never guessed. (Before the extension section the reason was that `Between` was outside the operator list of
   "Supported in the PoC".)
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
