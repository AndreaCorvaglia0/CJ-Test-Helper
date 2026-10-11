# other_value_collision

Condition values equal to the generator's "other" placeholder: `OTHER` on a scenario-level Text(50)
field, and `OTH` (what `OTHER` becomes when cut to 3 characters) on a contact-level Text(3) field. Both
fields are **not nullable**, so the remainder cannot be reached with null and needs a genuine extra value.
Builder: `examples/build_fresh_examples.py`, `build_other_value_collision`.

## Journey

```
SPLIT-1 "Channel"   (DE_Config.CHANNEL, Text(50), not nullable, scenario-level)
  path_a  CHANNEL Equal 'OTHER' -> UPDATE-1 -> exit
  path_b  CHANNEL Equal 'Email' -> SPLIT-2
  remainder_path                -> UPDATE-3 -> exit
SPLIT-2 "Level"     (DE_Master.Lvl, Text(3), not nullable, contact-level)
  path_a  Lvl Equal 'OTH'  -> UPDATE-4 -> exit
  path_b  Lvl Equal 'A'    -> UPDATE-5 -> exit
  remainder_path           -> UPDATE-6 -> exit
```

## Expected answer, step by step

1. **Values** (step 4): "Each field takes the values named in conditions, one extra 'other' value, and null
   when the schema allows it." The extra value must be *extra*: different from every named value, or it
   would select a named outcome. CHANNEL: `OTHER`, `Email`, an extra value (no null). Lvl: `OTH`, `A`, an
   extra value of at most 3 characters (no null).
2. **Reachability**: every outcome has a value that selects it first: **all 6 covered**.
3. **Scenarios**: SPLIT-1's 3 outcomes need 3 CHANNEL values: **3 scenarios**. **Cases**: `OTHER` ->
   UPDATE-1; `Email` x {`OTH`, `A`, extra} -> UPDATE-4/5/6; extra channel -> UPDATE-3: **5 cases,
   15 contacts.**
