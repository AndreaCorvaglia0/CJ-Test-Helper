# repeated_splits

The same scenario-level text field is tested by three splits in sequence. Some outcomes contradict what an
earlier split already decided, so they are unreachable; one remainder is unreachable because an earlier
outcome always matches first. It checks that reachability is computed from values, not from the graph shape.

## Journey

```
SPLIT-1 "Channel first check"
  path_a          CHANNEL Equal 'A' -> UPDATE-1 "Mark A" -> SPLIT-2
  remainder_path                    -> SPLIT-3

SPLIT-2 "Channel check after A"          (only reached with CHANNEL = 'A')
  path_a          CHANNEL Equal 'B' -> UPDATE-2 "Mark B after A" -> exit
  path_b          CHANNEL Equal 'A' -> UPDATE-3 "Confirm A"      -> exit
  remainder_path                    -> exit

SPLIT-3 "Channel check after not A"      (only reached with CHANNEL <> 'A')
  path_a          CHANNEL Equal 'B' -> UPDATE-4 "Mark B"      -> exit
  path_b          CHANNEL Equal 'A' -> UPDATE-5 "Mark A late" -> exit
  remainder_path                    -> WAIT-1 (1 minute)      -> exit
```

`CHANNEL` is a nullable Text field of `DE_Config`. Contact model as in the pilot: group -> `DE_Master`
(`ContactId`) -> `DE_Entry` (`ContactId`) -> `DE_Config` (`CampaignName`). Entry query:
`SELECT M.ContactId, M.Emailaddress, C.CampaignName FROM [DE_Master] M JOIN [DE_Config] C ON M.CampaignName = C.CampaignName`.

## Expected answer, step by step

1. **Tables and levels.** `DE_Config` is a split table and a source; `DE_Master` is a source (FROM of the
   entry query); `DE_Log` is written only. Spec, Table selection: "A table gets a CSV when something reads
   it; tables that are only written to are skipped." Levels, spec step 3: `DE_Master` is joined on the
   contact key -> contact; `DE_Config` is joined on `CampaignName` -> "scenario-level when many contacts
   share one row (joined on any other field)". Same as the pilot: "Config is scenario-level because it is
   joined on `CampaignName`."
2. **Values of CHANNEL.** Spec step 4: values named in conditions (`A`, `B`), one other value, null
   (nullable): 4 values.
3. **Simulate each value** (spec step 2, first true outcome wins, remainder if none):
   - `A`: SPLIT-1 `path_a` -> SPLIT-2: `B`? no; `A`? yes -> `path_b` -> UPDATE-3.
   - `B`: SPLIT-1 remainder -> SPLIT-3: `B`? yes -> `path_a` -> UPDATE-4.
   - other or null: SPLIT-1 remainder -> SPLIT-3: no match -> remainder -> WAIT-1.
4. **Unreachable branches** (status "not covered", reason: unreachable; spec "Every branch ends in one of
   three states ... not covered (unreachable, or behind an unsupported element)"):
   - `SPLIT-2/path_a`: SPLIT-2 is only reached with `CHANNEL = 'A'`, which is never equal to `'B'`.
   - `SPLIT-2/remainder_path`: with `CHANNEL = 'A'` the earlier outcome `path_b` always matches first.
   - `SPLIT-3/path_b`: SPLIT-3 is only reached when `CHANNEL Equal 'A'` was false.
   All other branches are covered by one of the three values above.
5. **Scenarios.** Spec step 6: "Paths sharing the same scenario-level values form one scenario." The three
   value groups (`A`, `B`, other/null) each cover branches no other value covers (`SPLIT-2/path_b`,
   `SPLIT-3/path_a`, `SPLIT-3/remainder_path`), so the fewest scenarios is **3** (spec step 5: "picks the
   fewest scenarios that cross every reachable branch"). A greedy cover finds 3 with any tie-break.
6. **Cases and contacts.** No contact-level field is read, so each scenario has one contact class and one
   case: **3 cases, 9 contacts** (3 per case).
7. **Case values.** Spec, Data generation rules: "Field read by a split | The value the case requires,
   written exactly as in the condition (same letter case)" -> `A` and `B`. The third scenario's value is
   any value other than `A`/`B`, or null: not pinned.

## Not asserted

- Which "other" value (or null) the third scenario uses.
- Scenario keys and run order.
