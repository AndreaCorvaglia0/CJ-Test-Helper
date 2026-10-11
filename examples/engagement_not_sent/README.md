# engagement_not_sent

An open split references an email that is sent only on a branch that never leads to the split. The Yes
branch must be reported as unreachable even though a real inbox is set. This is the pilot's situation for
the channel-2 and channel-3 engagement splits, reduced to its core.

## Journey

```
SPLIT-1 "MP email"                      (DE_Master.MarketingPermission, Boolean, nullable)
  path_a          MarketingPermission Is true -> EMAIL-1 "Welcome" -> UPDATE-1 "Email sent" -> exit
  remainder_path                              -> WAITATTR-1 (on DE_Config.WAIT1) -> ENGAGE-1

ENGAGE-1 "Open Welcome"   (open, refActivityCustomerKey EMAIL-1)
  branchResult-1 Yes -> UPDATE-2 "Opened"     -> exit
  branchResult-2 No  -> UPDATE-3 "Not opened" -> exit
```

## Expected answer, step by step

1. **Tables and levels**: as in `engagement_sent` (Config gets a CSV through the wait by attribute).
2. **The only path to ENGAGE-1** is `SPLIT-1/remainder_path` -> WAITATTR-1 -> ENGAGE-1. EMAIL-1 lies on
   `SPLIT-1/path_a`, which ends at UPDATE-1 and never reaches ENGAGE-1. So no path reaching ENGAGE-1 has sent
   EMAIL-1.
3. **ENGAGE-1 Yes: not covered, unreachable.** Spec, Special activities: "Engagement split, reachability |
   The Yes branch counts as reachable only if the path sent the referenced email earlier. Otherwise it is
   reported as unreachable." The real inbox does not change this. `reason_contains: "unreachable"` is the
   spec's own word.
4. **ENGAGE-1 No: covered** (contacts with MarketingPermission not `True`, no action).
5. **SPLIT-1 both branches: covered.**
6. **Cases.** Two paths, each ending after a different exit outcome (`SPLIT-1/path_a` via UPDATE-1,
   `ENGAGE-1/branchResult-2`): MarketingPermission `True` -> UPDATE-1; not `True` -> UPDATE-3. No manual
   action anywhere. **1 scenario, 2 cases, 6 contacts.**

## Not asserted

- The anomaly check of the spec, "An engagement split that references an email never sent on the paths
  reaching it.", should also produce a warning. Its wording is not fixed by the spec, so no
  `warnings_contain` is asserted. Suggestion: the warning names the split key (`ENGAGE-1`), because the
  pilot has six engagement splits with only two distinct names.
