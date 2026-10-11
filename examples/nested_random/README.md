# nested_random

A 90/10 random split reachable only through the 50% side of another random split. Builder:
`examples/build_fresh_examples.py`, `build_nested_random`.

```
SPLIT-1 "Test group"  (DE_Config."Test Group", Boolean, not nullable)  Is true -> RANDOM-1 ; remainder -> UPDATE-5
RANDOM-1  50% -> RANDOM-2 ; 50% -> UPDATE-1
RANDOM-2  90% -> UPDATE-2 ; 10% -> UPDATE-3
```

## Expected answer, step by step

1. Spec, Special activities: "Random split | Cannot be forced. ... branches reachable only through it get a
   statistical case of 50 contacts". The four random outcomes are reachable only through RANDOM-1: **covered,
   statistical**. A contact cannot be steered to RANDOM-2, so one statistical case serves both random
   splits: Test Group `True`, 50 contacts.
2. SPLIT-1 remainder: Test Group `False` -> UPDATE-5, a deterministic case of 3.
3. **2 scenarios** (Test Group is scenario-level), **2 cases, 53 contacts.**

## Ambiguity found while deriving (not asserted)

The spec's figures ("50 contacts reach the 10% side at least once with about 99.5% probability"; "1 to 9
contacts on the 10% side") hold for one 90/10 split met by all 50 contacts. Behind a 50/50 split only about
25 contacts reach RANDOM-2: P(at least one on its 10% side) = 1 - 0.95^50 = 92.3%, and the count on that side
follows Binomial(50, 0.05), not Binomial(50, 0.1). The spec does not say how the accepted range is stated for
a nested random split.
