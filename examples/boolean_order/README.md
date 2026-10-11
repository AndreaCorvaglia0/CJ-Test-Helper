# boolean_order

Three non-remainder outcomes on the same Boolean field, in the "wrong" order: a broad outcome first, a
narrower one shadowed by it, then the opposite value. The same shape follows on a non-nullable Boolean
whose first outcome tests `IsNull`. Written by the fresh test engineer (builder:
`examples/build_fresh_examples.py`, function `build_boolean_order`).

## Journey

```
SPLIT-1 "Opt-in"                         (DE_Master.OptIn, Boolean, nullable)
  path_a   OptIn Is false OR OptIn IsNull   -> UPDATE-1 "Not opted in" -> SPLIT-2
  path_b   OptIn Is false                   -> UPDATE-2 "Opted out"    -> exit
  path_c   OptIn Is true                    -> UPDATE-3 "Opted in"     -> SPLIT-2
  remainder_path                            -> UPDATE-4 "Opt-in other" -> exit

SPLIT-2 "Strict"                         (DE_Master.Strict, Boolean, NOT nullable, default False)
  path_a   Strict IsNull    -> UPDATE-5 -> exit
  path_b   Strict Is false  -> UPDATE-6 -> exit
  path_c   Strict Is true   -> UPDATE-7 -> exit
  remainder_path            -> UPDATE-8 -> exit
```

## Expected answer, step by step

1. **Values** (spec, Journey model step 4): "Each field takes the values named in conditions, one extra
   'other' value, and null when the schema allows it." A Boolean has only `True` and `False`, so
   OptIn takes {`True`, `False`, null} and Strict takes {`True`, `False`} (its schema does not allow null).
2. **SPLIT-1, first match** (step 2: "Outcomes are tried in order, the first true one wins, and the
   remainder branch means none matched"):
   - `False` -> `path_a` (its first condition); null -> `path_a` (its `IsNull` condition);
   - `True` -> not `path_a`, not `path_b`, so `path_c`.
   - `path_b` can never win: every value that makes it true (`False`) already made `path_a` true.
     **Unreachable.**
   - The remainder: all three values are caught. **Unreachable.**
3. **SPLIT-2**: `False` -> `path_b`, `True` -> `path_c`. `path_a` needs a null that the schema forbids, and
   the remainder needs a value that is neither true nor false nor null. **Both unreachable.**
4. **Status words**: spec, "not covered (unreachable, or behind an unsupported element), each with its
   reason"; the four branches above are not behind an unsupported element, so their reason says
   unreachable.
5. **Cases** (step 6). One scenario (no scenario-level table). Both SPLIT-1 survivors lead to SPLIT-2, so
   every path is (path_a or path_c) then (path_b or path_c of SPLIT-2): 4 possible paths, each crossing
   2 of the 4 reachable branches. Two cases are needed (two terminal outcomes, UPDATE-6 and UPDATE-7) and
   two suffice. A greedy cover reaches 2 whatever it picks first: after any first path (x, y), only the
   complementary path (x', y') still adds 2 new branches. **1 scenario, 2 cases, 6 contacts.**
6. **Asserted values**: the case ending at UPDATE-6 has Strict `False`; the one ending at UPDATE-7 has
   Strict `True`. Which OptIn value goes with which is the generator's choice (not asserted).

## Not asserted

- OptIn of each case (`True` in one case, `False` or null in the other).
