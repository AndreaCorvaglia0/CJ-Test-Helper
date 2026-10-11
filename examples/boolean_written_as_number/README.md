# boolean_written_as_number

An update contact step writes a Boolean as the **number** `1` (JSON `"value": 1`, exactly like the pilot's
`DE_NCM_AdHoc_Entry."Control Group" = 1`) and another as the string `"false"`; later splits read both. In the
pilot nothing reads the written Boolean, so this conversion is never exercised there. Builder:
`examples/build_fresh_examples.py`, `build_boolean_written_as_number`.

```
SPLIT-1 "Gate" (DE_Master.Gate Is true) -> UPDATE-1 "Set flags" (Flag = 1, Other = "false") -> SPLIT-2 ;
        remainder -> UPDATE-9
SPLIT-2 "Flag"  (Flag Is true)   -> SPLIT-3 ; remainder -> UPDATE-2
SPLIT-3 "Other" (Other Is false) -> UPDATE-3 ; remainder -> UPDATE-4
```

## Expected answer, step by step

1. Spec, Special activities: "Update contact | The written values are tracked". docs/export-format.md:
   "Values may be strings or numbers (`"value": 1`)".
2. **Assumption** (the spec does not say how a Boolean field stores the number 1): 1 is `True`, as Salesforce
   imports `1` into a Boolean field as true. With it: after UPDATE-1, Flag is true and Other is false, so
   SPLIT-2 takes `path_a` and SPLIT-3 takes `path_a`. Their remainders: **not covered, unreachable**.
3. Gate not `True` -> UPDATE-9. **1 scenario, 2 cases, 6 contacts.**
