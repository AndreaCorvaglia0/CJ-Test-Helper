# managed_source_table

A source table of the entry query is a data extension synchronized from the CRM, which Package Manager marks as
managed (`NO_DEPLOY`, `ManagedDataExtension`). It cannot be filled by an import. Builder:
`examples/build_step3_structure_examples.py`, `build_managed_source_table`.

## Journey and tables

```
SPLIT-1 "Permission"   DE_Master.Perm Is true -> UPDATE-1 "Allowed"
                       remainder              -> UPDATE-2 "Not allowed"
```

```sql
SELECT M.ContactId, M.Emailaddress
FROM [DE_Master] M
JOIN [CampaignMember_Salesforce_3] CM ON M.ContactId = CM.ContactId
WHERE CM.Status = 'Responded'
```

Tables: `DE_Entry` (`ContactId` PK, `Emailaddress`), `DE_Master` (`ContactId` PK, `FirstName`, `Emailaddress`,
`MobilePhone`, `Perm` Boolean nullable), `CampaignMember_Salesforce_3` (`Id` Text(18) PK, `ContactId` Text(18),
`Status` Text(40)), `DE_Log` (written only). Automation entry. The managed table's entity carries

```json
"issues": [{"type": "UNSUPPORTED_FUNCTIONALITY", "level": "WARNING", "sourceJobType": "PACKAGE",
            "functionality": "NO_DEPLOY", "objectType": "ManagedDataExtension"}]
```

## Expected answer, step by step

1. **Selected, with a CSV.** Spec, step 3, "Synchronized data extensions": "A source table that Package Manager marks
   as a managed data extension (`NO_DEPLOY`, `ManagedDataExtension` ...) cannot be filled by an import. Its CSV is
   still produced, so the tester sees the rows the entry query would need, but the report and the testbook leave it
   out of the files to import and say that with the direct import of the entry CSV it is not needed (assumption: the
   team confirms the procedure)." **3 CSVs**; the managed table has the role source and is **contact**-level (joined
   on `ContactId`, the contact key).
2. **Its rows.** The rows the entry query would need: one per contact, `ContactId` = the contact key (data rule 1),
   `Status` = **`Responded`** (data rule 3, "A value that passes the filter"). `Id` is its primary key, unique in
   the table ("Primary keys are unique within each table"; value not asserted). 6 rows.
3. **The issue is listed.** Spec, "Data sources of a condition": "Package Manager `issues` of level warning or error
   are listed in the report." The issue is level `WARNING`.
4. **Coverage.** `Perm` `True` -> UPDATE-1; `False` (preferred over null) -> UPDATE-2. **1 / 2 / 6**, both branches
   **covered**. The managed table changes nothing in the coverage; the trust checks run on all three CSVs as usual
   and pass.

## What report.md must say

- The table, and that its CSV is not among the files to import, because a synchronized (managed) data extension
  cannot be filled by an import and, with the direct import of the entry CSV, it is not needed
  (`report_contains`: the table name and one of the wordings of "synchronized / cannot be imported").
- The Package Manager issue (`NO_DEPLOY`, `ManagedDataExtension` or its type `UNSUPPORTED_FUNCTIONALITY`, as accepted
  in `cloudpages_entry`).
- The same in the testbook's Pre conditions.

## Format notes

`table_roles`, `csv_rows`, `csv_values` are proposed keys (see `examples/link_table_path/README.md`).

## Not asserted

- That the import list of report.md and the Pre conditions of testbook.xlsx leave out
  `CampaignMember_Salesforce_3.csv`. Both texts also name the table when they say it is not needed, so a substring
  test cannot tell "listed to import" from "listed as not needed"; checked by hand until the format has a key for
  the list of files to import.
- Whether the report lists "the team confirms the procedure" as an assumption.
