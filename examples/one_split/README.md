# one_split

The smallest useful journey: one decision split on a nullable Boolean contact field, two update-contact
steps, two exits. It checks table selection, levels, the remainder branch, and the 3-contacts-per-case rule.

## Journey

```
SPLIT-1 "Loyalty card?"
  path_a          DE_Master.HasLoyaltyCard Is true  -> UPDATE-1 "Log loyal"      -> exit
  remainder_path                                    -> UPDATE-2 "Log not loyal"  -> exit
```

Tables: `DE_Entry` (entry, sendable on `ContactId`), `DE_Master` (`ContactId` PK, `HasLoyaltyCard` Boolean
nullable, plus name, email, phone), `DE_Log` (written by both updates). Contact model: group -> `DE_Master`
on `ContactId` -> `DE_Entry` on `ContactId`. Entry query: `SELECT M.ContactId, M.Emailaddress FROM [DE_Master] M`.

## Expected answer, step by step

1. **Activities.** 3 activities; the start is `SPLIT-1`. Spec, Journey model step 1: "Each activity is a
   node; each outcome is a branch pointing to the next activity. The start is the activity no other activity
   points to."
2. **Tables with a CSV: `DE_Entry`, `DE_Master`.** Spec, Table selection: "Entry table | The table bound to
   the journey's entry trigger | Yes"; `DE_Master` is both "Split table | Any table named in a split
   condition ..." and "Source table | Any table in the FROM or JOIN of a query that fills the entry table".
   `DE_Log` is only written: "Written-only table | Target of an update contact step or of a query, never
   read by a split or by the entry query | No".
3. **Levels: both contact.** Spec, step 3: "A field is contact-level when its table has one row per contact
   (joined to the entry on the contact key)." `DE_Master` joins the entry on `ContactId`, the entry's
   sendable field (the contact key). The entry table itself is the one-row-per-contact root.
4. **Values.** Spec, step 4: "Each field takes the values named in conditions, one extra "other" value, and
   null when the schema allows it." `HasLoyaltyCard` -> `True` (named), `False` (the other Boolean value),
   null (nullable).
5. **Branches.** Spec, step 2: "Outcomes are tried in order, the first true one wins, and the remainder
   branch means none matched." `True` -> `path_a`; `False` and null -> `remainder_path`. Both reachable,
   no manual action anywhere: both **covered**.
6. **Classes, scenarios, cases.** Two contact classes (condition true / false). No scenario-level field
   is read, so every path has the same (empty) scenario values: spec step 6 "Paths sharing the same
   scenario-level values form one scenario" -> **1 scenario**. Each branch needs its own path (each path
   ends after exactly one of the two outcomes), so the smallest cover has **2 cases**; spec: "each distinct
   combination of contact-level values and manual actions is one case, with 3 contacts" -> **6 contacts**.
7. **Case values.** The `path_a` case has `HasLoyaltyCard = True` (Booleans are written `True`/`False` in
   the CSV, spec "File format"). The remainder case's value is either `False` or null; both are correct,
   so it is not pinned.

## Not asserted

- The exact value of the remainder case (`False` or null).
- CSV cell values (the format cannot express them); `checks_pass` covers types, keys and the entry query.
