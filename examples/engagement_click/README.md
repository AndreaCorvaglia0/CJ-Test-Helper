# engagement_click

Same journey as `engagement_sent`, but the email **has a link** (`<a href="https://www.example.com/offer">`
in the HTML view, and the URL in the text view). Positive counterpart of the "click needs a link" rule:
the click split's Yes branch becomes coverable with a manual action. Settings give a real inbox.

## Journey

```
SPLIT-1 "MP email": path_a (MarketingPermission Is true) -> STO-1 -> EMAIL-1 -> WAITATTR-1 -> ENGAGE-1
                    remainder_path -> UPDATE-4 -> exit
ENGAGE-1 "Open Welcome"  (open,  EMAIL-1): Yes -> ENGAGE-2;            No -> UPDATE-1 -> exit
ENGAGE-2 "Click Welcome" (click, EMAIL-1): Yes -> UPDATE-2 -> exit;    No -> UPDATE-3 -> exit
```

## Expected answer, step by step

1. Tables, levels, waits and SPLIT-1: as in `engagement_sent/README.md`.
2. **ENGAGE-1 Yes: covered with manual action; ENGAGE-1 No: covered** (same reasons as `engagement_sent`).
3. **ENGAGE-2 Yes: covered with manual action.** The referenced email EMAIL-1 is sent on every path that
   reaches ENGAGE-2 ("The Yes branch counts as reachable only if the path sent the referenced email
   earlier"), the email has a link (so the spec's "A click needs a link" rule does not block it), and a real
   inbox is set. The contact must open (to pass ENGAGE-1 Yes) and then click: `manual_actions: ["open", "click"]`.
4. **ENGAGE-2 No: covered with manual action**: only reachable after an open (see `engagement_sent`, step 7).
5. **Cases.** Four paths, each ending after a different exit outcome (`SPLIT-1/remainder_path`,
   `ENGAGE-1/branchResult-2`, `ENGAGE-2/branchResult-1`, `ENGAGE-2/branchResult-2`), so at least 4 and
   exactly 4 cases: no action -> UPDATE-1; open -> UPDATE-3; open + click -> UPDATE-2; no permission ->
   UPDATE-4. Spec step 6: cases differ by "contact-level values and manual actions". **1 scenario, 4 cases,
   12 contacts.**

## Not asserted

- Plus-addressed real inbox for the two manual cases, `@example.invalid` for the others.
- The click instruction and deadline in the testbook.
