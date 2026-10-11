# join_after_updates

Two paths write **different** constants into the same field and then join before a split that reads it.
The written value must be tracked per path, not per activity. Builder: `examples/build_fresh_examples.py`,
`build_join_after_updates`.

```
SPLIT-1 "Permission" (DE_Master.Perm Is true)
  path_a    -> UPDATE-1 "Segment X" (DE_Master.Seg = 'X') -> WAIT-1
  remainder -> UPDATE-2 "Segment Y" (DE_Master.Seg = 'Y') -> WAIT-1
WAIT-1 (1 minute, the join) -> SPLIT-2 "Segment" (DE_Master.Seg)
  path_a 'X' -> UPDATE-3 ;  path_b 'Y' -> UPDATE-4 ;  remainder -> UPDATE-5
```

## Expected answer, step by step

1. Spec, Special activities: "Update contact | The written values are tracked, so a later split that reads
   the same field sees the updated value."
2. Perm `True`: Seg becomes `X` -> SPLIT-2 `path_a` -> UPDATE-3. Perm not `True`: Seg becomes `Y` ->
   `path_b` -> UPDATE-4. Whatever the generated Seg, it is overwritten before SPLIT-2.
3. SPLIT-2 remainder: every contact reaching SPLIT-2 has `X` or `Y`: **not covered, unreachable**.
4. **1 scenario, 2 cases, 6 contacts.**
