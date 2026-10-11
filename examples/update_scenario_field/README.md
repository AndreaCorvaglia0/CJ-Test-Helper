# update_scenario_field

An update-contact step writes a constant into a **scenario-level** field (`DE_Config.MODE`, the table
joined on `CampaignName`) that later splits read. `update_then_split` covers the same rule on a
contact-level field; this one checks that the tracking also holds for a field that the generator
enumerates per scenario, not per contact class. Builder: `examples/build_fresh_examples.py`,
`build_update_scenario_field`.

## Journey

```
SPLIT-1 "Mode A?"            (DE_Config.MODE, Text(20), nullable, scenario-level)
  path_a          MODE Equal 'A' -> UPDATE-1 "Switch mode to B" (writes DE_Config.MODE = 'B') -> SPLIT-2
  remainder_path                 -> SPLIT-3

SPLIT-2 "Mode after switch"
  path_a          MODE Equal 'A' -> UPDATE-3 -> exit
  path_b          MODE Equal 'B' -> UPDATE-4 -> exit
  remainder_path                 -> UPDATE-5 -> exit

SPLIT-3 "Mode B?"
  path_a          MODE Equal 'B' -> UPDATE-6 -> exit
  remainder_path                 -> UPDATE-7 -> exit
```

## Expected answer, step by step

1. **Tables**: `DE_Config` is read by splits, so it gets a CSV although an update contact step also
   writes it (spec, Table selection: the written-only rule is for tables "never read by a split or by the
   entry query"). Levels as in the pilot: Config is joined on `CampaignName`, so scenario-level.
2. **Values** (step 4): MODE takes `A`, `B`, one other value, and null.
3. **Simulation with the write tracked** (spec, Special activities: "Update contact | The written values
   are tracked, so a later split that reads the same field sees the updated value"):
   - `A`: SPLIT-1 `path_a` -> UPDATE-1 sets MODE to `B` -> SPLIT-2 `path_b` -> UPDATE-4.
   - `B`: SPLIT-1 remainder -> SPLIT-3 `path_a` -> UPDATE-6.
   - other or null: SPLIT-1 remainder -> SPLIT-3 remainder -> UPDATE-7.
4. **SPLIT-2** is reached only after UPDATE-1, where MODE is always `B`: `path_a` and the remainder are
   **not covered, unreachable**. Without the tracking, `A` would wrongly reach `path_a`.
5. **Scenarios** (step 5): the three terminal outcomes UPDATE-4, UPDATE-6, UPDATE-7 need MODE = `A`, `B`
   and a third value; one scenario holds one MODE, so at least 3 scenarios, and 3 suffice. No contact-level
   split: one case per scenario. **3 scenarios, 3 cases, 9 contacts.**
6. **Values in the CSV**: the scenario of the `A` path holds `A` in `DE_Config.MODE` (the value before the
   journey runs), not `B`.

## Spec gap noted while deriving

`DE_Config` holds one row per scenario, shared by its contacts. In Salesforce the write of UPDATE-1 would
change that shared row, so a contact of the same scenario that reaches SPLIT-1 after another contact passed
UPDATE-1 would see `B` and take the remainder. The spec's rule "the written values are tracked" is per
contact and says nothing about writes into a scenario-level table (nor whether an update contact step can
target a table not keyed on the contact). This example asserts the per-contact reading only.
