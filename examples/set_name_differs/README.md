# set_name_differs

The Contact Builder attribute sets have names different from their data extensions: `Customers` stores
`DE_Master`, `Entries` stores `DE_Entry`, `Campaigns` stores `DE_Config`. Conditions and the wait expression
use the set names (`Campaigns.CHANNEL`, `Customers.Perm`,
`{{Contact.Attribute.Contacts.Customers.Entries.Campaigns."WAIT1"}}`). In the pilot every set has the name of
its table, so this mapping is never exercised there. Builder: `examples/build_fresh_examples.py`,
`build_set_name_differs`.

```
SPLIT-1 "Channel"     Campaigns.CHANNEL Equal 'Email' -> WAITATTR-1 (Campaigns.WAIT1) -> SPLIT-2 ; remainder -> UPDATE-3
SPLIT-2 "Permission"  Customers.Perm Is true -> UPDATE-1 ; remainder -> UPDATE-2
```

## Expected answer, step by step

1. Spec, Input: `attributeSets` give "How tables are linked"; docs/export-format.md: "An attribute set names a
   table" through `storageName`. A condition "names a table" (spec, Parsing rules): the set `Campaigns` is the
   table `DE_Config`, `Customers` is `DE_Master`.
2. **Tables**: `DE_Config` (split, wait and source), `DE_Master` (split and source), `DE_Entry`: 3 CSVs, named
   after the data extensions. Levels: Config scenario (joined on `CampaignName`).
3. **Scenarios** 2 (`Email`, other); **cases** 3 (`Email` x Perm `True` / not `True`, other): **9
   contacts**. All 4 branches covered.
