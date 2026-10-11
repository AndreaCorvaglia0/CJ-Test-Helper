# odd_condition_values

Condition values with a leading space, a trailing space, an apostrophe, double quotes and a comma, on a
contact-level Text field whose name has a space (`Customer Tier`). ` Gold` and `Gold` are both present, so a
generator that trims values would merge two outcomes. Builder: `examples/build_fresh_examples.py`,
`build_odd_condition_values`.

## Journey

```
SPLIT-1 "Customer tier"   (DE_Master."Customer Tier", Text(30), nullable)
  path_a  Equal ' Gold'          -> UPDATE-1
  path_b  Equal 'Gold'           -> UPDATE-2
  path_c  Equal 'O'Brien'        -> UPDATE-3     (value O'Brien)
  path_d  Equal 'say "hi", ok'   -> UPDATE-4
  path_e  Equal 'Silver '        -> UPDATE-5
  remainder_path                 -> UPDATE-6
```

The values are inside `<![CDATA[...]]>` exactly as above (spaces included).

## Expected answer, step by step

1. **Values** (rule 2): "The value the case requires, written exactly as in the condition (same letter
   case)". The value of each outcome is the CDATA content, spaces and quotes included.
2. **First match, case-sensitive exact comparison** (default setting "Text comparisons ignore letter case |
   Off"): the five values are pairwise different (` Gold` differs from `Gold`), so each selects its own
   outcome; null or an other value takes the remainder. **All 6 covered.**
3. **Cases**: one per outcome: **1 scenario, 6 cases, 18 contacts**, with `Customer Tier` equal to
   ` Gold`, `Gold`, `O'Brien`, `say "hi", ok`, `Silver `.
4. **CSV** (spec, File format: "UTF-8, comma-separated"): the value with a comma and quotes must be quoted
   so that it reads back as one cell (`checks_pass` reads the files back).

## Assumption to verify (not decided by the spec)

Whether the Salesforce import keeps leading and trailing spaces. If it trims them, ` Gold` arrives as `Gold`
and the contacts of the first case take `path_b`. The spec does not say; the expected answer follows rule 2
literally.
