# entry_filter_vs_split

The entry query filters the same field that the first split reads: only `Tier = 'Gold'` contacts enter, and
the split then tests `Silver`, `Gold`, remainder. Builder: `examples/build_fresh_examples.py`,
`build_entry_filter_vs_split`.

```
Entry query:  SELECT M.ContactId, M.Emailaddress FROM [DE_Master] M WHERE M.Tier = 'Gold'
SPLIT-1 "Tier"  (DE_Master.Tier, Text(10), nullable)
  path_a  Tier Equal 'Silver' -> UPDATE-1 ;  path_b  Tier Equal 'Gold' -> UPDATE-2 ;  remainder -> UPDATE-3
```

## Expected answer, step by step

1. Spec, Table selection: "The entry CSV is kept consistent with the source CSVs: its rows are what the
   entry query would produce from them." So every contact that has an entry row has `Tier = 'Gold'` in
   Master. Spec, Data generation rule 3: "Field filtered by the entry query | A value that passes the
   filter, so the contact really enters the journey."
2. Spec, Salesforce rules: "Data is read live": SPLIT-1 reads the Master row, unchanged since entry, so
   every contact at SPLIT-1 has `Gold`: **path_b covered**; `path_a` and the remainder can never be taken by
   a contact that entered: **not covered, unreachable**.
3. **1 scenario, 1 case, 3 contacts** (Tier `Gold` -> UPDATE-2).

## Ambiguity found while deriving

Rule 2 ("Field read by a split | The value the case requires") is listed before rule 3 ("Field filtered by
the entry query"). Read alone, the priority order would write `Silver` for a Silver case. But such a contact
gets no row from the entry query, so it cannot enter, and its entry row (if written anyway) would not be
"what the entry query would produce". The spec does not say which rule wins when the same field is both read
by a split and filtered by the entry query; this example takes the only reading under which the files stay
consistent and the contacts really take their path.
