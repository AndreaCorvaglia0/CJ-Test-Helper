# update_then_split

An update-contact step writes a constant into a contact-level field that a later split reads. The value
generated for the CSV would send the contact one way; the value written by the journey sends it another.

## Journey

```
SPLIT-1 "Gold segment?"                 (DE_Master.Segment, Text(20), nullable)
  path_a          Segment Equal 'Gold' -> UPDATE-1 "Downgrade to Silver" -> SPLIT-2
                                          (writes DE_Master.Segment = 'Silver',
                                                  DE_Master.SegmentChangedOn = {{DateTime.Now}})
  remainder_path                       -> UPDATE-2 "Not gold" -> exit

SPLIT-2 "Segment after downgrade"
  path_a          Segment Equal 'Gold'   -> UPDATE-3 "Still gold"    -> exit
  path_b          Segment Equal 'Silver' -> UPDATE-4 "Now silver"    -> exit
  remainder_path                         -> UPDATE-5 "Other segment" -> exit
```

## Expected answer, step by step

1. **Values of `Segment`** (spec step 4): `Gold`, `Silver` (named in conditions), one other value, null.
2. **Spec, Special activities:** "Update contact | The written values are tracked, so a later split that
   reads the same field sees the updated value." UPDATE-1 writes the constant `Silver` into the same
   table and field that SPLIT-2 reads (`DE_Master.Segment`).
3. **Simulation:**
   - `Gold`: SPLIT-1 `path_a` -> UPDATE-1 sets `Segment` = `Silver` -> SPLIT-2: `Gold`? no (it is now
     `Silver`); `Silver`? yes -> `path_b` -> UPDATE-4.
     Without tracking, the generated value `Gold` would have sent the contact to `path_a` (UPDATE-3): the
     example fails if the write is ignored.
   - `Silver`, other, null: SPLIT-1 remainder -> UPDATE-2.
4. **SPLIT-2:** it is only reached after UPDATE-1, where `Segment` is always `Silver`. So `path_b` is
   covered; `path_a` (`Gold`) and the remainder are **not covered, unreachable**.
5. **Cases**: `Segment` = `Gold` (the value written in the CSV, before the journey runs) -> UPDATE-4;
   any other value -> UPDATE-2. **1 scenario, 2 cases, 6 contacts.**
6. **Tables**: `DE_Master` is read by splits and also written by UPDATE-1. It still gets a CSV: the
   written-only rule applies only to tables "never read by a split or by the entry query".

## Not asserted

- The trust check "Each generated contact, simulated again through the journey from the written values,
  takes exactly the path it was created for" must apply the update during re-simulation; only
  `checks_pass` covers it.
