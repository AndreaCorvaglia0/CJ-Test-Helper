# Examples: small journeys with hand-derived answers

Each directory holds a journey and the answer the generator must give, worked out by hand from
`docs/spec.md` before looking at any generator output. `tests/test_examples.py` runs every example through
the pipeline and compares (format: `docs/plan.md`, section "Examples").

```
examples/<name>/package.json    package export in the pilot's shape (docs/export-format.md)
examples/<name>/expected.json   the expected answer
examples/<name>/README.md       what it tests, and the derivation step by step, quoting the spec rule used
examples/build_examples.py      builds every package.json and validates all examples
```

## The rule

**An expected answer is never edited to make a failure pass without a written proof from the spec in the
example's README.** When the generator and an example disagree, either the generator is fixed, or the
example's README gains a paragraph that quotes the spec sentence proving the expected answer wrong, and
only then is `expected.json` changed (in the same commit). A failing example is a finding, not noise.

## The examples

| Example | What it tests | Key expected numbers |
| --- | --- | --- |
| `one_split` | One Boolean contact split, two updates, exits; table selection and levels | 1 scenario, 2 cases, 6 contacts; both branches covered |
| `repeated_splits` | The same scenario-level text field tested three times; contradictions, a remainder made unreachable by an earlier outcome | 3 / 3 / 9; 3 of 8 branches unreachable |
| `and_or_null` | `X AND (Y Is false OR Y IsNull) AND Z` on nullable Booleans, then a split on `Y IsNull` alone; classes and the remainder | 1 / 3 / 9; all 4 covered; null and `False` told apart |
| `two_levels` | Scenario-level Config + contact-level Master, pilot table layout (Master -> Target -> Config, `ACTIVE`/`HAS_RUN`/date filters, `CONCAT`) | 4 / 6 / 18; 4 CSVs incl. source-only Target |
| `engagement_sent` | Email -> wait by attribute -> open split -> click split, email without link, real inbox | 1 / 3 / 9; open Yes manual, click Yes not covered ("link"), click No manual |
| `engagement_no_inbox` | Same package, no real inbox | 1 / 3 / 9; open Yes not covered ("inbox"), click No not covered |
| `engagement_click` | Same journey, email with a link | 1 / 4 / 12; click Yes covered with manual action (`open`, `click`) |
| `engagement_not_sent` | Open split referencing an email sent only on another branch | 1 / 2 / 6; open Yes not covered ("unreachable") |
| `random_split` | 90/10 random split behind a scenario-level flag; statistical case | 2 / 3 / 56; random branches statistical, range 1..9 |
| `unsupported_element` | Unknown activity type `SMSSYNC` in the middle of a path | 1 / 2 / 6; `SMSSYNC-1` unsupported; split behind it not covered ("unsupported") |
| `update_then_split` | Update contact writes a constant a later split reads | 1 / 2 / 6; the generated `Gold` contact ends on the `Silver` branch |
| `case_mismatch` | `'Email'` then `'EMAIL'` on the same field, case-sensitive (default) | 3 / 3 / 9; `EMAIL` outcome unreachable; warning Email/EMAIL |
| `case_mismatch_insensitive` | Same package, `case_insensitive_text: true` | 3 / 3 / 9; reachability flips (remainder unreachable instead) |
| `unsupported_operator` | Condition the generator cannot evaluate: `Between` with a value not written `low\|high` (until the extension section, `Between` was outside the spec's list); found by trying to break the generator (it raised instead of reporting) | 1 / 2 / 6; both outcomes of the split not covered ("unsupported") |
| `boolean_exhaustive` | `Is true` / `Is false` / remainder on a non-nullable and on a nullable Boolean | 1 / 3 / 9; remainder unreachable only for the non-nullable field (relies on null not matching `Is false`, assumptions row 7) |
| `journey_data_split` | Journey Data conditions (`Event.<key>.<field>`, `IsEphemeralAttribute`) on the entry table, DE entry with no Contact Builder model; `IsNull` on the contact key, `Is`, `Equal`, `GreaterThan` on a Decimal | 1 / 4 / 12; key `IsNull` unreachable; numbers strictly inside the ranges, not-null representatives |
| `journey_data_snapshot` | Update contact rewrites an entry field: a later Journey Data split sees the entry value, a Contact Data split on the same field the written one | 1 / 2 / 6; both later remainders unreachable |
| `between_inclusive` | `Between` `10\|20` (bounds included) with `GreaterThan 20` and `Equal 20` on a Number | 1 / 3 / 9; `Equal 20` unreachable; values > 20, in (10, 20), < 10 and not null |
| `row_absent_isnull` | Existence test via `IsNull` on the key of a group-to-set table | 1 / 3 / 9; absent contacts have no row in that CSV; no space-only cells |
| `row_absent_attribute_comparison` | Existence test written as key `Equal` `ValueParameterName="Event.<key>.SubscriberKey"` | 1 / 3 / 9; read as "the contact has a row" |
| `attribute_comparison_unsupported` | `ValueParameterName` comparing two ordinary fields | 1 / 2 / 6; that split not covered ("non supportat"); report opens with the warning |
| `missing_relationship` | Attribute set with no relationship in the export; Package Manager issues (WARNING listed, INFO not) | 1 / 2 / 6; reason names the relationship |
| `run_once_entry` | EmailAudience entry with `scheduleFlowMode` `runOnce` | 1 / 2 / 6; report: Run Once, new version; testbook: new version and run identifier |
| `cloudpages_entry` | CloudPages Smart Capture entry, `JOURNEY_UNSUPPORTED_ENTRY` issue | 1 / 2 / 6; report: test a copy with a DE entry; issue listed |
| `engagement_short_window` | Open split 5 minutes after its email, another 2 days after | 1 / 4 / 12; warning for the short window only; testbook gives a minimum duration |
| `update_inserts_row` | Update contact on an existence-tested table inserts the row | 1 / 2 / 6; the later existence test sees the row |
| `journey_data_other_event` | Journey Data key naming an event definition other than the trigger's | 1 / 2 / 6; that split not covered ("non supportat") |
| `row_absent_other_fields` | `IsNotNull` existence test, then `IsNull` / `Equal` on another field of the absent row | 1 / 2 / 6; `IsNull` true, `Equal` false on an absent row |
| `once_and_done_entry`, `single_entry_all_versions` | `entryMode` OnceAndDone / SingleEntryAcrossAllVersions with an automation entry | 1 / 2 / 6; testbook names the run identifier |
| `default_missing_column` | `defaults.mobileNumber` naming a column the entry table lacks | 1 / 2 / 6; report names the column |
| `unused_asset` | An image and an email no activity uses, with an unresolvable `publishedURL` reference | 1 / 2 / 6; no warning and no report line about them |
| `pilot` | The spec's acceptance criteria on the real export (default settings + real inbox) | >= 23 scenarios, >= 33 cases, >= 146 contacts (proven minima); 137 of 259 branches unreachable |
| `pilot_case_insensitive` | The pilot with case-insensitive text (what the earlier tool assumed) | >= 41 / 59 / 224 (41 is the earlier tool's "40 + 1"); 91 unreachable |

`engagement_no_inbox` and `engagement_sent` share the same package (built by the same function), as do
`case_mismatch` and `case_mismatch_insensitive`; only `settings` in `expected.json` differ.

## Conventions used in the expected answers

- **Status of a branch.** "covered": at least one case crosses it with no manual action. "covered with
  manual action": every case that crosses it needs an open or click first (engagement Yes branches, and
  branches only reachable behind them, such as the No of a click split placed on an open split's Yes).
  "not covered": with a reason; `reason_contains` uses the spec's own word: "unreachable" (spec: "Otherwise
  it is reported as unreachable"), "unsupported" ("behind an unsupported element"), "link" ("A click needs a
  link"), "inbox" (the "Real inbox" setting). In the small examples the status never depends on which cover
  the generator picks; in the pilot, the three branches where it could are in `branches_any_of`.
- **Counts** are exact when two bounds meet: a lower bound (every path ends after exactly one "terminal"
  outcome, i.e. an outcome followed by an exit with no further split, so cases >= reachable terminal
  outcomes; scenarios forced by scenario-level outcomes that one scenario cannot cross together) and the
  result of a greedy cover, which reaches that bound whatever the tie-break. The pilot uses ranges.
- **Values** are CSV strings: Booleans `"True"`/`"False"`, null is JSON `null`. Values the spec leaves
  free (the "other" value, the representative of a "not true" class, an irrelevant scenario field) are not
  listed in `cases`; listed values are compared, unlisted ones are not.
- **`end_activity`** is the last activity the contact is in. A contact leaving through an outcome without
  `next` ends at that split (docs/export-format.md: "An outcome without `next` is a journey exit").
- **Statistical case**: counted in `case_count` and in `contact_count` (50 contacts).

## Extensions to the expected.json format (proposed)

Used where the documented keys could not say what the spec requires. A runner that does not know them
yet can ignore them, but they are part of the expected answer.

| Key | Where | Meaning |
| --- | --- | --- |
| `branches[b].statistical` | `random_split`, pilots | equals `BranchStatus.statistical` |
| `cases[i].random` | `random_split`, pilots | `{activity_key, expected_low, expected_high}` equals `Case.random` (1..9 for 50 contacts at 10%) |
| `contact_count: {min, max}` | pilots | a range, like `scenario_count` and `case_count` |
| `branches_any_of` | pilots | `{branch: [allowed statuses]}` for the three branches whose status depends on the generator's cover; together with `branches` it lists every split outcome |
| `cases[i].contact_constraints`, `cases[i].has_row`, `report_contains`, `report_not_contains`, `report_head_contains`, `testbook_contains`, `warnings_not_contain`, `csv_no_space_cells`, lists of alternatives | extension examples | see `docs/plan.md`, section "Esempi" |

## What expected.json cannot express yet

- CSV cell values: real inbox with plus-addressing for open/click contacts and `@example.invalid` for the
  others; wait dates (+24 h before an engagement split); values passing the entry filters (`ACTIVE`,
  `HAS_RUN`, the validity window); the activation field set only on the first scenario ("one active
  scenario"); placeholders; key formats (`TST_R01_C0001`). Only `checks_pass` covers part of this.
- Determinism ("Running twice with the same settings gives the same scenarios, cases and keys"):
  a `"deterministic": true` key could ask the runner to generate twice and compare.
- Number of contact classes (4 in `and_or_null`, 8 in the pilot), scenario flags (`is_statistical`,
  `has_manual_action`) and run order (manual-action scenarios first).
- The relation between counts (contacts = 3 x deterministic cases + 50).
- More than one substring per reason, and warnings whose wording the spec does not fix (the anomaly checks,
  e.g. "An engagement split that references an email never sent on the paths reaching it").
- Testbook rows (priority 4).

## Regenerating and validating

```
python examples/build_examples.py
python examples/build_fresh_examples.py
python examples/build_extension_examples.py
```

rewrites every `package.json` and checks, for every example: valid JSON, one selected journey, every
`next` points to an existing activity key, one start activity, no dangling `{{mcpm#/entities/...}}`
reference, every criteria XML parses, and `expected.json` lists every split outcome exactly once. Change
the builder, never a `package.json` by hand.
