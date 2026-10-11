# two_journeys

The export holds two journeys on the same entry table, each with its own entry event, automation and entry
query. `selectedEntities.journeys` names the **second** one, which is also second in `entities.journeys`.
Builder: `examples/build_fresh_examples.py`, `build_two_journeys`.

## The two journeys

```
EX_FirstJourney (not selected; 3 activities)
  SPLIT-1 "Other flag" (DE_Other.OtherFlag Is true -> UPDATE-1, remainder -> UPDATE-2)
  entry query Q_EX_FirstJourney_Entry:  ... FROM [DE_Master] M WHERE M.Region = 'NORTH'

EX_SecondJourney (selected; 5 activities)
  SPLIT-A "Permission" (DE_Master.Perm Is true -> WAIT-A (1 minute) -> UPDATE-A -> UPDATE-C ;
                        remainder -> UPDATE-B)
  entry query Q_EX_SecondJourney_Entry: ... FROM [DE_Master] M WHERE M.Region = 'SOUTH'
```

## Expected answer, step by step

1. Spec, Parsing rules: "If the export holds more than one journey, the app uses the one listed in
   `selectedEntities.journeys`": **EX_SecondJourney, 5 activities**.
2. **Tables.** `DE_Other` is read only by the first journey: for the selected one it has no role, so **no
   CSV**. `DE_Entry` and `DE_Master` (split and source): 2 CSVs.
3. **Branches, cases**: Perm `True` -> UPDATE-A -> UPDATE-C; not `True` -> UPDATE-B: **1 scenario,
   2 cases, 6 contacts.**

## Not asserted (checked by hand in the review)

- The entry query is the selected journey's: `DE_Master.Region` = `SOUTH` for every contact (rule 3), not
  `NORTH`. A tool that took the first journey's automation would pass its own checks with the wrong data.
