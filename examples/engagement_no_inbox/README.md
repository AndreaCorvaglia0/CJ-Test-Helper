# engagement_no_inbox

Same `package.json` as `engagement_sent` (built by the same function), run **without** a real inbox
(`settings.real_inbox` is empty, which is the spec default).

## Expected answer, step by step

Everything about tables, values and paths is as in `engagement_sent/README.md`. What changes:

1. **Spec, Behaviour at the edges:** "If the real inbox is empty, generation still works. The open and click
   contacts get undeliverable addresses, and those branches are reported as not covered."
2. **ENGAGE-1 Yes: not covered**, and the reason should name the missing real inbox (`reason_contains:
   "inbox"`, the word the spec uses for the setting: "Real inbox for open and click tests").
3. **ENGAGE-2 Yes: not covered.** Two reasons apply (no link, no inbox); which one the report gives is not
   fixed by the spec, so no `reason_contains`.
4. **ENGAGE-2 No: not covered.** It is only reachable through ENGAGE-1 Yes, i.e. only by a contact who
   opens; without a real inbox no contact can open, so this branch is one of "those branches" whose
   contacts get undeliverable addresses.
5. **ENGAGE-1 No and both SPLIT-1 branches: covered**, as in `engagement_sent`.
6. **Cases: still 3, 9 contacts.** The sentence above says the open contacts still exist ("get undeliverable
   addresses"), so the open case is generated as in `engagement_sent`; only its addresses and its branch
   status change. Its `manual_actions` is not pinned (the case was built for an open that cannot happen).

## Ambiguity

A generator could also drop the open case when no inbox is set (2 cases, 6 contacts); the quoted sentence
says the contacts are generated, so this example expects 3 cases. If the lead decides otherwise, record
the decision here with the spec sentence that supports it.
