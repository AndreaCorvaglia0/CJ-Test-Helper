# entry_column_split

The splits read columns of the **entry table** that the entry query fills: one copied from a source column,
one set to a string literal. Builder: `examples/build_fresh_examples.py`, `build_entry_column_split`.

```
Entry query:  SELECT M.ContactId, M.Emailaddress, M.Segment, 'WELCOME' AS Source FROM [DE_Master] M
SPLIT-1 "Segment"  (DE_Entry.Segment)  Equal 'Gold'    -> UPDATE-1 ; remainder -> SPLIT-2
SPLIT-2 "Source"   (DE_Entry.Source)   Equal 'PARTNER' -> UPDATE-2 ; remainder -> UPDATE-3
```

## Expected answer, step by step

1. Spec, Table selection: the entry rows "are what the entry query would produce from them". So
   `DE_Entry.Segment` = the contact's `DE_Master.Segment`, and `DE_Entry.Source` = `WELCOME` for every
   contact.
2. **SPLIT-1**: `Gold` is reachable (Master.Segment `Gold`, copied by the query); the remainder with any other
   value or null: both **covered**.
3. **SPLIT-2 `path_a`**: Source is always `WELCOME`, never `PARTNER`: **not covered, unreachable**. The
   remainder is **covered**.
4. **Cases**: Segment `Gold` -> UPDATE-1; Segment not `Gold` -> UPDATE-3: **1 scenario, 2 cases,
   6 contacts.** For the first case, `Gold` must be in `DE_Master.Segment` (the source) as well as in
   `DE_Entry.Segment`, or the entry rows would not match the query (`checks_pass`).

## Ambiguity found while deriving

The spec's value rules (priority 2, "Field read by a split") do not say what to do when the field read by a
split is an entry column computed by the entry query; the answer above follows the consistency rule of the
Table selection section.
