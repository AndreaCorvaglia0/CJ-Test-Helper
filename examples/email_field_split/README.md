# email_field_split

A split reads the email address field itself: `IsNull`, and `Equal 'vip@example.com'`; behind the second
outcome, an open split. The value a split requires collides with the address rules (real inbox for open
contacts, `@example.invalid` for the others). Builder: `examples/build_fresh_examples.py`,
`build_email_field_split`. Settings: a real inbox.

```
SPLIT-1 "Email known?"  (DE_Master.Emailaddress, EmailAddress, nullable)
  path_a  Emailaddress IsNull                   -> UPDATE-1 "No email"
  path_b  Emailaddress Equal 'vip@example.com'  -> EMAIL-1 "Welcome" -> WAITATTR-1 (DE_Config.WAIT1) -> ENGAGE-1
  remainder                                     -> EMAIL-2 "Welcome" -> UPDATE-4 "Welcome sent"
ENGAGE-1 "Open Welcome VIP" (open, EMAIL-1): Yes -> UPDATE-2 ; No -> UPDATE-3
```

## Expected answer, step by step

1. **Value priority** (spec, Data generation rules): "2 | Field read by a split | The value the case
   requires, written exactly as in the condition" comes before "4 | Email, phone, date". So the `path_a`
   contacts have no address (null) and the `path_b` contacts have `vip@example.com`; the remainder contacts
   get `<contact key>@example.invalid`, which is neither null nor `vip@example.com`. SPLIT-1: **all three
   covered.**
2. **ENGAGE-1 Yes** needs an open of an email that goes to `vip@example.com`, an address the tester does
   not own: the real inbox cannot be used for these contacts (rule 2 fixes their address). The spec's
   nearest rule is the one for a missing inbox: "The open and click contacts get undeliverable addresses,
   and those branches are reported as not covered." **Not covered** (reason not asserted). A case with the
   open may still exist, as for a missing inbox ("Its cases exist"), hence 3 or 4 cases.
3. **ENGAGE-1 No**: `vip@example.com` contacts that do nothing: **covered**.
4. **Cases**: null email -> UPDATE-1; `vip@example.com`, no open -> UPDATE-3; other address -> UPDATE-4;
   possibly `vip@example.com` with an open that cannot be done. **1 scenario, 3 or 4 cases, 9 or 12
   contacts.**

## Ambiguity found while deriving

The spec does not say what happens when a field read by a split is the email address field, nor whether
"Contacts that must open or click get the tester's real inbox" overrides rule 2. Giving the open contacts
the real inbox would send them down the remainder instead of `path_b`.
