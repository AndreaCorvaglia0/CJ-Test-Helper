# email_null_split

The common "has the contact an email address?" split: `Emailaddress IsNull`, nothing else. No email is sent
and no manual action exists. Builder: `examples/build_fresh_examples.py`, `build_email_null_split`.

```
SPLIT-1 "Has email?"  (DE_Master.Emailaddress, EmailAddress, nullable)
  path_a     Emailaddress IsNull -> UPDATE-1 "SMS instead" -> exit
  remainder                      -> UPDATE-2 "Email ok"    -> exit
```

## Expected answer, step by step

1. **Values.** Spec, Data generation rules, applied "in this priority order": "2 | Field read by a split |
   The value the case requires" before "4 | Email, phone, date". The `path_a` case requires null, so its
   contacts have an empty address. The remainder contacts get `<contact key>@example.invalid` (rule 4: "All
   other contacts get an undeliverable address"), which is not null.
2. **Branches**: both covered. **1 scenario, 2 cases, 6 contacts.**
3. **Trust checks** (`checks_pass: true`): an empty address is undeliverable, and no contact uses the real
   inbox, so "Only contacts with a manual action use the real inbox; all others are undeliverable" holds.

## Spec sentence that pulls the other way

Acceptance criterion: "Contacts needing an open or click use the real inbox; all others use
`@example.invalid`." Read literally it forbids the empty address that rule 2 requires. The criterion is
written for the pilot, where no split reads the address; the priority order of the data generation rules
decides the value, and an empty address is as undeliverable as `@example.invalid`.
