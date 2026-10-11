# and_or_null

A nested AND/OR condition on nullable Boolean contact fields, written exactly like the pilot's "Phone
consent" split, followed by a second split on the nullable field alone, so that null and `False` must be
told apart. It checks the criteria parser (nested `ConditionSet`, `IsNull` with an empty CDATA value), the
contact classes, the minimal cases, and that the remainder is covered too.

## Journey

```
SPLIT-1 "Phone consent"
  path_a          IsMailOffers Is true AND (IsDunning Is false OR IsDunning IsNull) AND PhoneConsent Is true
                  -> UPDATE-1 "Phone allowed" -> SPLIT-2
  remainder_path  -> UPDATE-2 "Phone not allowed" -> exit

SPLIT-2 "Dunning unknown?"
  path_a          IsDunning IsNull -> UPDATE-3 "Dunning unknown" -> exit
  remainder_path                   -> UPDATE-4 "Not dunning"     -> exit
```

All three fields are nullable Booleans of `DE_Master` (contact-level). The entry query also filters
`WHERE M.IsActive = 'True'` (a contact-level field no split reads).

## Expected answer, step by step

Write X = `IsMailOffers`, Y = `IsDunning`, Z = `PhoneConsent`.

1. **Tables and levels.** `DE_Entry` (entry) and `DE_Master` (split and source) get a CSV, both
   contact-level (joined on the contact key `ContactId`); `DE_Log` is written only. Same rules as
   `one_split`.
2. **Values.** Spec step 4: "Each field takes the values named in conditions, one extra "other" value, and
   null when the schema allows it." X and Z: `True` (named), `False` (other), null. Y: `False` (named),
   `True` (other), null. 27 combinations.
3. **The formula of SPLIT-1.** F1 = X Is true AND (Y Is false OR Y IsNull) AND Z Is true. F1 is true only
   for X = `True`, Z = `True` and Y in {`False`, null}. (Y = null makes `Y IsNull` true, so the OR is true
   whatever `Y Is false` means for null; nothing here depends on how `Is false` treats null.)
4. **The formula of SPLIT-2.** F2 = Y IsNull: true for null, false for `False` and `True`.
5. **Contact classes.** Spec step 4: "a class groups the contact-level combinations that satisfy the same
   conditions". By the truth of (F1, F2): (T, T), (T, F), (F, T), (F, F): 4 classes.
6. **Paths** (spec step 2, first true outcome wins):
   - (T, T) = X `True`, Y null, Z `True`: SPLIT-1 `path_a` -> SPLIT-2 `path_a` -> UPDATE-3.
   - (T, F) = X `True`, Y `False`, Z `True`: SPLIT-1 `path_a` -> SPLIT-2 remainder -> UPDATE-4.
   - (F, *): SPLIT-1 remainder -> UPDATE-2.
   Every branch is reachable without manual action: all four are **covered**.
7. **Minimal cases.** Every path ends after exactly one of `SPLIT-2/path_a`, `SPLIT-2/remainder_path`,
   `SPLIT-1/remainder_path` (the outcomes that lead to an exit with no further split), so at least 3 paths
   are needed, and the 3 paths above suffice. Spec, Journey model: "test design becomes a search for the
   smallest set of paths that crosses every branch." -> **3 cases**, 1 scenario (no scenario-level field),
   **9 contacts**.
8. **Case values.** The two `path_a` cases are fully determined: (`True`, null, `True`) and
   (`True`, `False`, `True`); null is an empty cell in the CSV and `None` in the case. The remainder case can
   be any combination failing F1 (for example X = `False`), so it is not pinned.

## Not asserted

- Which failing combination represents the remainder class.
- That `IsActive` is `True` on every Master row (spec Data generation rules, priority 3: "A value that
  passes the filter, so the contact really enters the journey"). It is not expressible in expected.json;
  `checks_pass` covers it through "every Entry row matches what the entry query would return".
