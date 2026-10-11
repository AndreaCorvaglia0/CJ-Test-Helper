# case_mismatch

Two splits compare the same scenario-level text field with `'Email'` and later with `'EMAIL'`, as the pilot
does (`Channel1` ... `CHANNEL1 equal Email`, then `channel 2 email?` ... `CHANNEL2 equal EMAIL`). Run with the
default setting: text comparisons are case-sensitive. The same package runs case-insensitively in
`case_mismatch_insensitive`.

## Journey

```
SPLIT-1 "Channel"                       (DE_Config.CHANNEL, Text, nullable)
  path_a          CHANNEL Equal 'Email' -> UPDATE-1 "Email channel" -> SPLIT-2
  path_b          CHANNEL Equal 'DM'    -> UPDATE-2 "DM channel"    -> exit
  remainder_path                        -> WAIT-1 (1 minute)        -> exit

SPLIT-2 "channel email?"
  path_a          CHANNEL Equal 'EMAIL' -> UPDATE-3 "Email confirmed"     -> exit
  remainder_path                        -> UPDATE-4 "Email not confirmed" -> exit
```

## Expected answer, step by step

1. **Setting.** Spec, settings table: "Text comparisons ignore letter case | Off"; and "Text comparisons:
   whether `Email` and `EMAIL` are treated as equal. The PoC assumes they are different by default".
2. **Values of CHANNEL** (spec step 4): `Email`, `DM`, `EMAIL` (all named in conditions; different strings
   when the comparison is case-sensitive), one other value, null.
3. **Simulation:**
   - `Email`: SPLIT-1 `path_a` -> SPLIT-2: `'Email'` is not `'EMAIL'` -> remainder -> UPDATE-4.
   - `DM`: SPLIT-1 `path_b` -> UPDATE-2.
   - `EMAIL`, other, null: SPLIT-1 remainder -> WAIT-1.
4. **`SPLIT-2/path_a`: not covered, unreachable.** SPLIT-2 is only reached with `CHANNEL = 'Email'`, which
   never equals `'EMAIL'` case-sensitively. All other branches are covered.
5. **Scenarios and cases**: three value groups, each covering a branch the others do not (`SPLIT-1/path_a`
   + `SPLIT-2/remainder_path`, `SPLIT-1/path_b`, `SPLIT-1/remainder_path`). No contact-level field is read.
   **3 scenarios, 3 cases, 9 contacts.** The Email scenario holds exactly `Email` (spec: "written exactly as
   in the condition (same letter case)").
6. **Warning.** Spec, Outputs: the report "lists suspicious patterns found while parsing, such as the same
   value written in two letter cases (`Email` and `EMAIL` in the pilot)." -> `warnings_contain: ["Email",
   "EMAIL"]`. No activity key or field name of this example contains `EMAIL` in capitals, so the second
   string can only come from that warning.

## Not asserted

- Which value the remainder scenario uses (`EMAIL`, another value, or null are all correct).
