# field_name_case

The conditions spell field names in a different letter case from the schema: `DE_Config.CHANNEL` for the
field `Channel`, `DE_Master.PERM` for the field `Perm`. Builder: `examples/build_fresh_examples.py`,
`build_field_name_case`.

```
SPLIT-1 "Channel"     CHANNEL Equal 'Email' -> SPLIT-2 ; remainder -> UPDATE-3     (schema field: Channel)
SPLIT-2 "Permission"  PERM Is true -> UPDATE-1 ; remainder -> UPDATE-2              (schema field: Perm)
```

## Expected answer, step by step

1. **Assumption** (the spec does not say): Salesforce field names are not case-sensitive, so `CHANNEL` is the
   field `Channel` and `PERM` the field `Perm`. The CSV header keeps the schema spelling ("header row with
   the exact field names in schema order").
2. Scenarios: Channel `Email` / other: 2. Cases: (`Email`, Perm `True`) -> UPDATE-1, (`Email`, not `True`)
   -> UPDATE-2, (other) -> UPDATE-3: **3 cases, 9 contacts**, all 4 branches covered. `checks_pass` makes
   the re-simulation from the files confirm that the values land in the schema columns.
3. Values are not asserted because the key spelling inside the coverage result is the tool's choice.

## Possible alternative

A tool that treats the field names as case-sensitive would not find `CHANNEL` and `PERM` in the schema and
would have to report the conditions as unsupported. The spec's parsing rules say nothing on letter case of
field names.
