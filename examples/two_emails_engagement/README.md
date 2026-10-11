# two_emails_engagement

Two engagement splits on two **different** emails on one path: an open split on "Welcome" (no link), and
on its No branch a second email "Reminder" (with a link) followed by a click split on it. The click case
must leave Welcome unopened and click Reminder. Builder: `examples/build_fresh_examples.py`,
`build_two_emails_engagement`. Settings: a real inbox.

## Journey

```
SPLIT-1 "Permission"  (DE_Master.Perm, Boolean, nullable)
  path_a  Perm Is true -> EMAIL-1 "Welcome" -> WAITATTR-1 (DE_Config.WAIT1) -> ENGAGE-1
  remainder_path       -> UPDATE-4 "No permission" -> exit

ENGAGE-1 "Open Welcome"    (open, refActivityCustomerKey EMAIL-1)
  branchResult-1 Yes -> UPDATE-1 "Opened welcome" -> exit
  branchResult-2 No  -> EMAIL-2 "Reminder" -> WAITATTR-2 (DE_Config.WAIT2) -> ENGAGE-2

ENGAGE-2 "Click Reminder"  (click, refActivityCustomerKey EMAIL-2; the Reminder asset has a link)
  branchResult-1 Yes -> UPDATE-2 "Clicked reminder" -> exit
  branchResult-2 No  -> UPDATE-3 "Ignored both"     -> exit
```

## Expected answer, step by step

1. **Tables**: `DE_Config` is read by the two waits by attribute ("Split table | Any table named in a split
   condition or in a wait-by-attribute") and is a source of the entry query: 3 CSVs, Config scenario-level.
2. **ENGAGE-1 Yes**: every path reaching ENGAGE-1 sent EMAIL-1 ("The Yes branch counts as reachable only if
   the path sent the referenced email earlier"), so it is reachable; it needs an open ("The Yes branch needs
   a manual action (open or click) ... and uses the real inbox"): **covered with manual action**.
3. **ENGAGE-2 Yes**: every path reaching ENGAGE-2 sent EMAIL-2 (EMAIL-2 is on the only way in), and
   Reminder has a link, so the spec's "A click needs a link" does not block it: **covered with manual
   action** (a click on Reminder).
4. **No branches**: a contact that does nothing takes ENGAGE-1 No, receives Reminder, and takes ENGAGE-2
   No. That case has no manual action, so both No branches are **covered**, and so is SPLIT-1 `path_a`.
5. **Cases** (step 6: "each distinct combination of contact-level values and manual actions is one case").
   The four terminal outcomes (ENGAGE-1 Yes, ENGAGE-2 Yes, ENGAGE-2 No, SPLIT-1 remainder) each need their
   own path, and these four paths cover everything:
   - Perm `True`, open Welcome -> UPDATE-1, `["open"]`;
   - Perm `True`, Welcome not opened, click Reminder -> UPDATE-2, `["click"]`;
   - Perm `True`, no action -> UPDATE-3, `[]`;
   - Perm not `True` -> UPDATE-4, `[]`.
   **1 scenario, 4 cases, 12 contacts.**

## Not asserted (checked by hand in the review)

- The open and click contacts get `cj.tester+<key>@example.com`; the others `@example.invalid`.
- Wait dates. Spec: "Wait date before an engagement split | Wait-by-attribute on the path to an engagement
  split | Generation time plus 24 hours". Both WAIT1 and WAIT2 qualify, so both get generation time + 24 h.
  **Spec gap**: WAITATTR-2 is reached only after WAITATTR-1 has ended (+24 h), when Reminder has just been
  sent; a WAIT2 of +24 h is then already past, so ENGAGE-2 is evaluated at once and the tester has no time
  to click. The rule as written cannot leave time for a second engagement split on the same path.
- The testbook must say which email to open or click: for the click case, Welcome must stay unopened.
