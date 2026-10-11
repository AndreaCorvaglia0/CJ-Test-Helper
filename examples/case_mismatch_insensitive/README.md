# case_mismatch_insensitive

Same `package.json` as `case_mismatch` (built by the same function), run with
`settings.case_insensitive_text: true` ("Text comparisons ignore letter case | On"). Reachability changes:
the branch that was unreachable becomes covered, and the branch that was covered becomes unreachable.

## Expected answer, step by step

1. **Setting.** Spec, assumptions: "Text comparisons: whether `Email` and `EMAIL` are treated as equal. The
   PoC assumes they are different by default; the earlier tool assumed they are equal, so this is a
   setting." Here they are equal.
2. **Simulation** (journey drawn in `case_mismatch/README.md`):
   - `Email` or `EMAIL` (now the same value): SPLIT-1 `path_a` -> SPLIT-2: equal to `'EMAIL'` -> `path_a`
     -> UPDATE-3.
   - `DM`: SPLIT-1 `path_b` -> UPDATE-2.
   - other, null: SPLIT-1 remainder -> WAIT-1.
3. **`SPLIT-2/path_a`: covered. `SPLIT-2/remainder_path`: not covered, unreachable**: SPLIT-2 is only
   reached when CHANNEL matches `'Email'`, and then it always matches `'EMAIL'` first. Spec step 2: "the
   first true one wins, and the remainder branch means none matched."
4. **3 scenarios, 3 cases, 9 contacts**, as in `case_mismatch`.
5. **Warning still expected**: the suspicious pattern is "found while parsing", independently of how the
   comparison is then made, and the result depends on an assumption still to verify.

## Not asserted

- Whether the Email scenario writes `Email` or `EMAIL`: both satisfy both splits once case is ignored.
