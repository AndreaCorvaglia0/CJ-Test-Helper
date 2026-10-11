# sql_variants

The entry query in a different but common style: lower-case keywords, `ENT.` prefixes, `AS` aliases,
`INNER JOIN` with the equality reversed, a Boolean filter written `= 1`, and the validity window written
with `BETWEEN`. Builder: `examples/build_fresh_examples.py`, `build_sql_variants`.

```sql
select m.ContactId, m.Emailaddress, c.CampaignName
from ENT.[DE_Master] as m
inner join ENT.[DE_Config] as c on c.CampaignName = m.CampaignName
where c.ACTIVE = 1
and GETDATE() BETWEEN c.START_DATE AND c.END_DATE
```

Journey: SPLIT-1 "Channel" (DE_Config.CHANNEL Equal `Email` -> SPLIT-2, remainder -> UPDATE-3); SPLIT-2
"Permission" (DE_Master.Perm Is true -> UPDATE-1, remainder -> UPDATE-2).

## Expected answer, step by step

1. **Sources** (spec: "The app reads table names, join equalities, simple WHERE filters (equality and date
   range)"): `DE_Master` and `DE_Config` (`ENT.` only says the tables are shared), joined on `CampaignName`.
   3 CSVs; Config is scenario-level (joined on `CampaignName`).
2. **Filters**: `c.ACTIVE = 1` is an equality on a Boolean (1 = True), so ACTIVE is the activation field;
   `GETDATE() BETWEEN c.START_DATE AND c.END_DATE` is a date range, the validity window ("Validity window |
   Date-range filter in the entry query | Starts yesterday, ends in 7 days").
3. **Scenarios**: CHANNEL `Email` and another value: 2. **Cases**: (`Email`, Perm `True`) -> UPDATE-1,
   (`Email`, Perm not `True`) -> UPDATE-2, (other) -> UPDATE-3: **3 cases, 9 contacts.** All covered.

## Not asserted (checked by hand in the review)

- `START_DATE` <= generation time <= `END_DATE` (yesterday / +7 days) for every scenario, and `ACTIVE` =
  `True` on the first scenario only. If `BETWEEN` were not understood, the spec requires it to be reported
  ("Anything more complex is reported").
