# engagement_sent

An email, a send-time wait before it, a wait by attribute after it, then an open split and a click split
that both reference that email, as in the pilot (`ENGAGEMENTSPLITV2-1` open -> `ENGAGEMENTSPLITV2-2` click,
both on `EMAILV2-1`). The email has no link. Settings give a real inbox.

## Journey

```
SPLIT-1 "MP email"                      (DE_Master.MarketingPermission, Boolean, nullable)
  path_a          MarketingPermission Is true -> STO-1 (send-time wait) -> EMAIL-1 "Welcome"
                                              -> WAITATTR-1 (on DE_Config.WAIT1) -> ENGAGE-1
  remainder_path                              -> UPDATE-4 "No permission" -> exit

ENGAGE-1 "Open Welcome"   (open, refActivityCustomerKey EMAIL-1)
  branchResult-1 Yes -> ENGAGE-2
  branchResult-2 No  -> UPDATE-1 "Not opened" -> exit

ENGAGE-2 "Click Welcome"  (click, refActivityCustomerKey EMAIL-1)
  branchResult-1 Yes -> UPDATE-2 "Clicked"            -> exit
  branchResult-2 No  -> UPDATE-3 "Opened not clicked" -> exit
```

The asset "Welcome" has neither `href=` nor `<a ` in its HTML or text view: it has no link.

## Expected answer, step by step

1. **Tables.** `DE_Config` gets a CSV because of the wait: "Split table | Any table named in a split
   condition or in a wait-by-attribute | Yes" (it is also a source of the entry query). With `DE_Entry` and
   `DE_Master`: 3 CSVs. Levels as in the pilot: Config scenario, the others contact.
2. **Waits do not branch.** Spec, Special activities: "Wait by duration, send-time wait | No branching" and
   "Wait by attribute | No branching. The date field is filled according to the date settings."
3. **SPLIT-1.** `True` -> `path_a`, `False`/null -> remainder. Both covered without manual action
   (`path_a` is also crossed by the no-open case below).
4. **ENGAGE-1 Yes: covered with manual action.** Every path reaching ENGAGE-1 goes through EMAIL-1, so
   spec "The Yes branch counts as reachable only if the path sent the referenced email earlier" holds; spec
   "Engagement split | Both branches get contacts. The Yes branch needs a manual action (open or click),
   recorded in the testbook, and uses the real inbox." The settings give a real inbox.
5. **ENGAGE-1 No: covered.** Contacts that do nothing (undeliverable `@example.invalid` address, spec
   "All other contacts get an undeliverable address") take No.
6. **ENGAGE-2 Yes: not covered, reason about the link.** Spec: "A click needs a link. When the email
   referenced by a click split has no link, as in the pilot, the Yes branch is reported as not covered
   instead of asking the tester for a click."
7. **ENGAGE-2 No: covered with manual action.** ENGAGE-2 is only reached through ENGAGE-1 Yes, so every
   contact crossing it must first open the email (a manual action). The branch itself needs no click, but its
   coverage depends on the tester's open; see "Status convention" in `examples/README.md`.
8. **Cases.** Spec step 6: "each distinct combination of contact-level values and manual actions is one
   case". Three paths are needed (each ends after one of `SPLIT-1/remainder_path`, `ENGAGE-1/branchResult-2`,
   `ENGAGE-2/branchResult-2`; `ENGAGE-2/branchResult-1` cannot be covered):
   - MarketingPermission `True`, no action -> ENGAGE-1 No -> UPDATE-1;
   - MarketingPermission `True`, open -> ENGAGE-1 Yes -> ENGAGE-2 No -> UPDATE-3, `manual_actions: ["open"]`;
   - MarketingPermission not `True` -> UPDATE-4.
   No split reads a scenario-level field (`WAIT1` is read by a wait, not by a condition), so there is
   **1 scenario, 3 cases, 9 contacts**.

## Not asserted

- The open case's contacts use `cj.tester+<contact key>@example.com` (spec: "Contacts that must open or
  click get the tester's real inbox with plus-addressing"); others use `<contact key>@example.invalid`.
- `WAIT1` = generation time + 24 hours (spec, Dates: "Wait date before an engagement split | Wait-by-attribute
  on the path to an engagement split | Generation time plus 24 hours").
- The testbook deadline for the open. The format cannot express these; see `examples/README.md`.
