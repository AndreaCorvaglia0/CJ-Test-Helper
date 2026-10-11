# two_levels

Splits on a scenario-level config table and on a contact-level master table, with the pilot's table layout
(Master -> Target -> Config in the entry query, Config filtered on `ACTIVE`, `HAS_RUN` and a date window).
It checks that scenarios and cases differ: scenario values decide the macro path, contact classes split it
inside a scenario.

## Journey

```
SPLIT-1 "Channel"                        (DE_Config.CHANNEL, Text, not nullable)
  path_a          CHANNEL Equal 'Email' -> SPLIT-2
  path_b          CHANNEL Equal 'DM'    -> SPLIT-4
  remainder_path                        -> exit (no next)

SPLIT-2 "Ignore permission"              (DE_Config.IGNOREPERM, Boolean, not nullable)
  path_a          IGNOREPERM Is false   -> SPLIT-3
  remainder_path                        -> UPDATE-1 "Email forced"  -> exit

SPLIT-3 "Marketing permission"           (DE_Master.MarketingPermission, Boolean, nullable)
  path_a          MarketingPermission Is true -> UPDATE-2 "Email allowed" -> exit
  remainder_path                              -> UPDATE-3 "Email blocked" -> exit

SPLIT-4 "Mail offers"                    (DE_Master.IsMailOffers, Boolean, nullable)
  path_a          IsMailOffers Is true  -> UPDATE-4 "DM sent"    -> exit
  remainder_path                        -> UPDATE-5 "DM skipped" -> exit
```

Entry query (same shape as the pilot's `Q_SKYDE_AdHoc_Target`):

```sql
SELECT M.ContactId, M.Emailaddress, C.CampaignName,
       CONCAT(M.ContactId, '_', C.CampaignName, '_', FORMAT(GETUTCDATE(), 'yyyyMMdd_HHmm')) AS ActionId
FROM [DE_Master] M
JOIN [DE_Target] T ON M.ContactId = T.SubscriberId
JOIN [DE_Config] C on T.CampaignName = C.CampaignName
where C.ACTIVE = 'True'
and (CAST(GETUTCDATE() AS DATE) >= CAST(START_DATE AS DATE) AND CAST(GETUTCDATE() AS DATE) <= CAST(END_DATE AS DATE))
AND C.HAS_RUN = 'False'
```

## Expected answer, step by step

1. **Tables.** `DE_Entry` (entry), `DE_Master` (split + source), `DE_Config` (split + source) and
   `DE_Target` (source only: no split reads it, but the entry query joins it). Spec, Table selection:
   "Source table | Any table in the FROM or JOIN of a query that fills the entry table ... | Yes". This is
   the pilot's `DE_NCRM_AdHoc_Target` case ("`DE_NCRM_AdHoc_Target` | Source | Yes"). `DE_Log` is
   written only -> no CSV. **4 CSVs.**
2. **Levels.** Spec step 3. `DE_Master` joins the entry on the contact key; `DE_Target` joins Master on
   `ContactId = SubscriberId`, the contact key again -> both **contact**. `DE_Config` is joined on
   `CampaignName` (any other field) -> **scenario**.
3. **Values.** Spec step 4. Scenario level: `CHANNEL` in {`Email`, `DM`, other} (not nullable), `IGNOREPERM`
   in {`False` (named), `True`} (not nullable): 6 scenario combinations. Contact level:
   `MarketingPermission` and `IsMailOffers` in {`True`, `False`, null}.
4. **Reachability.** Every branch is reachable (each outcome has a value that selects it on a path that
   reaches the split) and none needs a manual action: all 9 **covered**.
5. **Fewest scenarios = 4.** Spec step 5: "picks the fewest scenarios that cross every reachable branch".
   `SPLIT-1` has 3 outcomes and one scenario crosses exactly one of them; `SPLIT-2`'s two outcomes both
   need `CHANNEL = 'Email'` with different `IGNOREPERM` values. So at least 2 scenarios with `Email`, 1 with
   `DM`, 1 with another value: **4**. Four suffice: (Email, False), (Email, True), (DM, any), (other, any).
   A greedy cover over scenarios reaches 4 whatever the tie-break: (Email, False) covers 4 new branches,
   then a DM scenario 3, then the last two 1 each.
6. **Cases = 6.** Spec step 6: "Inside a scenario, each distinct combination of contact-level values and
   manual actions is one case". Each path ends after exactly one of the 6 outcomes that lead to an exit
   with no further split (`SPLIT-1/remainder_path`, `SPLIT-2/remainder_path`, both outcomes of `SPLIT-3`,
   both outcomes of `SPLIT-4`), so at least 6 cases, and the 4 scenarios give exactly 6:
   (Email, False) x {MarketingPermission True, not True}; (Email, True) x 1; (DM) x {IsMailOffers True,
   not True}; (other) x 1. **18 contacts.**
7. **End activities.** The remainder of `SPLIT-1` has no `next`, so that case exits at `SPLIT-1`
   (docs/export-format.md: "An outcome without `next` is a journey exit"); its last activity is `SPLIT-1`.

## Not asserted

- `IGNOREPERM` of the DM and "other" scenarios (not read on their paths), the "other" channel value, and
  the representatives of the "not True" classes.
- The entry filters' effect on the data: `ACTIVE`, `HAS_RUN` and the date window (spec priority 3 and the
  "Validity window" date rule), and the "one active scenario" setting that `ACTIVE` switches on by default
  ("One active scenario at a time | On when an activation field is detected"). Only `checks_pass` covers
  them; see the format gaps in `examples/README.md`.
