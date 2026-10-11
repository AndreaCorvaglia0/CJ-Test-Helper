# short_text_field

A Text(3) field compared with `'A'`, `'B'`, `'ABC'` and `'ABCD'` (one character too long for the field),
plus unread Text(3), Text(2) and non-nullable Text(1) fields whose placeholders must be cut. Builder:
`examples/build_fresh_examples.py`, `build_short_text_field`.

## Journey

```
SPLIT-1 "Code"   (DE_Master.Code, Text(3), nullable)
  path_a  Code Equal 'A'    -> UPDATE-1 -> exit
  path_b  Code Equal 'B'    -> UPDATE-2 -> exit
  path_c  Code Equal 'ABC'  -> UPDATE-3 -> exit
  path_d  Code Equal 'ABCD' -> UPDATE-4 -> exit
  remainder_path            -> UPDATE-5 -> exit
DE_Master also has Tag Text(3), Two Text(2) (nullable) and One Text(1) (not nullable), read by nothing.
```

## Expected answer, step by step

1. **Values** (step 4): Code takes `A`, `B`, `ABC`, `ABCD`, one other value, and null.
2. **`ABCD` cannot be written.** Spec, Development priorities: "Every value respects the type, length,
   nullability and primary key of its schema." A Text(3) field can never hold `ABCD`, so no contact can
   match `path_d`: **not covered**. Its reason must say why (spec: "every branch not covered is listed with
   its reason"); by the spec's classification ("not covered (unreachable, or behind an unsupported
   element)") it is unreachable, but the wording is not asserted.
3. **First match** (step 2): `A` -> `path_a`, `B` -> `path_b`, `ABC` -> `path_c`. The remainder takes null
   or an "other" value; that value must fit in 3 characters and differ from `A`, `B`, `ABC` (a literal
   `OTHER` does not fit). **4 covered outcomes.**
4. **Cases**: one per terminal outcome reached: **1 scenario, 4 cases, 12 contacts.**

## Not asserted (checked by hand in the review)

- Placeholders (rule 5: "text `TST_<field>_<n>` cut to the field length"): Tag = `TST`, Two = `TS`,
  One = `T`.
- The remainder case's Code value: null or a value of at most 3 characters other than `A`, `B`, `ABC`.
