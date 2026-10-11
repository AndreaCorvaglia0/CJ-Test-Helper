# wait_contact_date_engagement

A wait by attribute on a **contact-level** date field, in a table that nothing else reads (`DE_Dates`:
no split, not in the entry query), followed by an open split. In the pilot and in `engagement_sent` the
wait field is scenario-level (`DE_Config.WAIT1`). Builder: `examples/build_fresh_examples.py`,
`build_wait_contact_date_engagement`. Settings: a real inbox.

## Journey

```
SPLIT-1 "Permission"  (DE_Master.Perm, Boolean, nullable)
  path_a  Perm Is true -> EMAIL-1 "Welcome" -> WAITATTR-1 (DE_Dates.NextContact) -> ENGAGE-1
  remainder_path       -> UPDATE-3 "No permission" -> exit
ENGAGE-1 "Open Welcome" (open, EMAIL-1)
  Yes -> UPDATE-1 "Opened" -> exit ;  No -> UPDATE-2 "Not opened" -> exit
```

Contact model: group -> DE_Master (ContactId) -> DE_Entry (ContactId) -> DE_Dates (ContactId = ContactId).

## Expected answer, step by step

1. **Tables.** Spec, Table selection: "Split table | Any table named in a split condition or in a
   wait-by-attribute | Yes". `DE_Dates` is named only by WAITATTR-1 and still gets a CSV: **3 CSVs**.
2. **Level.** Step 3: "A field is contact-level when its table has one row per contact (joined to the entry
   on the contact key)". `DE_Dates` joins the entry on `ContactId`, the contact key: **contact**.
3. **Branches.** EMAIL-1 is on the only path into ENGAGE-1, so Yes is reachable and needs an open:
   **covered with manual action**. No, SPLIT-1 `path_a` (crossed by the no-open case) and the remainder:
   **covered**.
4. **Cases.** Three terminal outcomes (ENGAGE-1 Yes, ENGAGE-1 No, SPLIT-1 remainder), three paths:
   (Perm `True`, open) -> UPDATE-1; (Perm `True`, no action) -> UPDATE-2; (Perm not `True`) -> UPDATE-3.
   **1 scenario, 3 cases, 9 contacts.**

## Not asserted (checked by hand in the review)

- `DE_Dates.NextContact`, per contact. Spec, Dates: "Wait date | Field used by a wait-by-attribute |
  Generation time" and "Wait date before an engagement split | Wait-by-attribute on the path to an
  engagement split | Generation time plus 24 hours". Read literally, the contacts whose path crosses
  WAITATTR-1 on the way to ENGAGE-1 (the open case **and** the no-open case) get +24 h, and the
  Perm-not-true contacts (whose path does not cross the wait) get the generation time. The tool's README
  reads the rule as "24 hours later when the contacts must open an email after that wait" (open case only).
- `DE_Dates.LastSeen` (other date field): generation time.
