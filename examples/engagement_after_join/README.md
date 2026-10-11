# engagement_after_join

An open split whose email is sent on only **one** of the two paths that join before it. The Yes branch is
reachable through the path that sent the email, and must not be reported unreachable because the other path
did not send it. Builder: `examples/build_fresh_examples.py`, `build_engagement_after_join`. Settings: a
real inbox.

## Journey

```
SPLIT-1 "Permission"   (DE_Master.Perm, Boolean, nullable)
  path_a          Perm Is true -> EMAIL-1 "Welcome" -> WAIT-1
  remainder_path               ->                      WAIT-1
WAIT-1 (2 days, wait by duration: the join) -> ENGAGE-1 "Open Welcome" (open, EMAIL-1)
  branchResult-1 Yes -> UPDATE-1 "Opened"     -> exit
  branchResult-2 No  -> UPDATE-2 "Not opened" -> exit
```

## Expected answer, step by step

1. Spec, Special activities: "Engagement split, reachability | The Yes branch counts as reachable only if
   the path sent the referenced email earlier. Otherwise it is reported as unreachable." The rule is per
   path: the path through `path_a` sent EMAIL-1, so ENGAGE-1 Yes is reachable there, and needs an open:
   **covered with manual action** (real inbox set).
2. The path through the remainder never sent EMAIL-1: its contacts can only take No. ENGAGE-1 No:
   **covered** (no manual action needed). SPLIT-1 remainder: **covered**.
3. **Cases.** Needed: (Perm `True`, open) -> UPDATE-1, the only way to cross ENGAGE-1 Yes; and a case
   through the remainder (Perm not `True`) -> UPDATE-2. These two cover all four branches: **2 cases**
   minimum. A cover may also keep (Perm `True`, no open) -> UPDATE-2, which crosses the same branches as
   the two others together, so **2 or 3 cases** (6 or 9 contacts) depending on the generator's
   tie-break. A case with Perm not `True` and an open must not exist: its contacts never receive the email.
4. **SPLIT-1 `path_a`** is "covered" if the (Perm `True`, no open) case exists, else "covered with manual
   action" (the convention of `examples/README.md`): listed in `branches_any_of`.
5. Waits by duration do not branch ("Wait by duration, send-time wait | No branching").

## Not asserted

- No warning "An engagement split that references an email never sent on the paths reaching it" should
  appear: the email is sent on one of the paths. The format cannot assert the absence of a warning.
