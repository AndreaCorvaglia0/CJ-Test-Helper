# entry_left_join_literal

The entry query uses a `LEFT JOIN`, a string literal column and a bare current-date column. Builder:
`examples/build_fresh_examples.py`, `build_entry_left_join_literal`.

## Entry query

```sql
SELECT M.ContactId, M.Emailaddress, 'WELCOME' AS Source, X.Segment, GETDATE() AS LoadedOn
FROM [DE_Master] M
LEFT JOIN [DE_Extra] X ON M.ContactId = X.ContactId
WHERE M.Active = 'True'
```

Journey: `SPLIT-1 "Permission"` (DE_Master.Perm Is true -> UPDATE-1, remainder -> UPDATE-2).

## Expected answer, step by step

1. **Tables.** Spec, Table selection: "Source table | Any table in the FROM or JOIN of a query that fills the
   entry table ... | Yes". A LEFT JOIN is a JOIN: `DE_Extra` gets a CSV although no split reads it.
   **3 CSVs** (`DE_Log` is written only).
2. **Levels.** `DE_Extra` joins Master on `ContactId`, the contact key: contact-level.
3. **Branches, cases**: Perm `True` -> UPDATE-1, not `True` -> UPDATE-2: **1 scenario, 2 cases,
   6 contacts.**

## Not asserted (checked by hand in the review)

- Entry rows (spec: "its rows are what the entry query would produce from them"; "simple select expressions
  (column, literal, CONCAT, current date)"): `Source` = `WELCOME`, `Segment` = the contact's
  `DE_Extra.Segment`, `LoadedOn` = the generation time, `Emailaddress` = Master's.
- `DE_Master.Active` = `True` for every contact (rule 3: "Field filtered by the entry query | A value that
  passes the filter").
