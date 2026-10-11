# Progress

Resume from this file. Spec: `docs/spec.md`. Contract: `docs/plan.md`.

## Done

- Repository set up: spec copied to `docs/spec.md`, pilot export to `fixtures/`, old tool kept only in git history (commit 83f0f65) as reference.
- `cjhelper/model.py`: the shared data model and module contract.
- `docs/plan.md`: module responsibilities and function signatures. `docs/export-format.md`: export shape for hand-made examples.

- `loader.py` + `criteria.py` (197 tests), `sqlparse_lite.py` (144 tests), `tables.py` (27 tests): delivered and reviewed.
- `graph.py`, `coverage.py`, `checks.py`, `pipeline.py`, `__main__.py` (lead): first integrated run on the pilot passes all 7 trust checks.
  `python -m cjhelper "fixtures/CJ template complesso-v1.json" --out output --inbox tester@example.com` takes about 30 s.

- `datagen.py` + `outputs.py` (88 tests): delivered. The whole suite (562 tests) passes.
- `examples/`: 17 examples with hand-derived expected answers (15 small, 2 pilot variants with hand-proven minimum counts);
  all pass through `tests/test_examples.py`. Loop findings fixed: the coverage check misread the intended "no real inbox" state;
  an unknown condition operator crashed the run (now the split is unsupported, its branches not covered); a condition on a field
  missing from the schema was guessed as text (now unsupported); a field pinned by an entry filter is no longer tried with other values.
- `docs/assumptions.md`: Salesforce review, 35 assumptions to verify, 16 suspicious patterns, a one-day verification run plan.
  Acted on: the filters of the followed automation queries are applied to the generated rows (RUN_TIME stays empty).

- Technical writer: README.md, report.md with a how-to-run section and root-cause grouping, testbook wording. Done.
- Streamlit page `cjhelper/app.py` (28 tests), screenshots judged by the lead; UX review done.
- End-of-level review loop, part 1 (coverage and data generation reviewers, 34 findings): fixed in three batches, see the
  commits "Review fixes, batch 1/2/3". Highlights: length-aware 'other' values, email and phone fields read by splits, key
  fields read by splits, unsupported outcomes instead of whole splits, remainder evaluated last, nested random splits,
  statistical cases with manual actions, branches before a random split, SELECT * with extra items, NULL in select,
  unsupported .NET date tokens, entry columns copied from scenario-level columns, waits before the email get no extra time,
  unique primary-key placeholders, email-typed contact keys, scenarios.csv `active_at_start` and `activation_field` columns.

## Remaining plan

Nothing scheduled. Possible next steps, to decide with the user: verify the Salesforce assumptions with a small real run
(docs/assumptions.md), the postponed findings below, the open design readings (docs/final-report.md).

Done in the evening of 11 October: translation of the generator's messages and output files into Italian (four Opus agents on
disjoint modules, glossary in docs/brand.md "Glossario"; patterns in outputs.py reconciled with the new texts; one shared
prefix "pattern sospetto:"), tests/test_checks.py (18 tests), RB-5, RB-15 (single query prefix). Fast suite (~700 tests),
39 examples and the pilot acceptance test pass; pilot CLI run 7/7 checks, 23/33/146 as before.

Postponed findings (not in the pilot): RB-1/RB-10 (Journey Data wait and condition mapping), RB-2 (entry-source criteria
warning), CK-9 (inbox local part not checked); all low findings of the triage.
Routing: Opus for code and Italian text, Sonnet for checks and mechanical work, Haiku for trivial tasks.

## State after the merge of PR #1 (upstream main)

- PR #1 merged; upstream added on main: Lutech brand (theme, Montserrat, logo, docs/brand.md), page in Italian with
  stepper and collapsible step cards (cjhelper/app.css), README in Italian, CLAUDE.md section on look and language.
  Only cjhelper/app.py, app.css, config.toml, README.md, tests/test_app.py, docs/brand.md and assets changed: no overlap with
  the generator. The branch was fast-forwarded onto main; the page's look is not to be changed.
- Triage fixes committed on top (4e5e01a): every query filling the entry table is followed (RB-4/CP-4), LEFT JOIN exclusion
  form in the entry check (RB-13), trust checks read the files and follow scenario links (CK-1, CK-4, CK-5, CK-6, CK-8,
  CK-11, CK-12). CK-18 (tests/test_checks.py) and RB-5 (unknown statsTypeId: both branches not covered) done with the translation.

## Working rules from the user

- Subagents on Opus at max effort for judgement-heavy work; Sonnet for simpler, possibly long, supervised tasks and for simple checks.

## Design readings taken by the lead (not Salesforce assumptions)

- Cases inside a scenario: the spec asks for "the smallest set of paths that crosses every branch" and "the fewest scenarios".
  The generator picks the fewest scenarios, then the fewest cases inside them (a second greedy pass). It does not add every
  contact class to every scenario. On the pilot this gives 23 scenarios / 33 cases / 146 contacts (case-sensitive) and
  41 / 59 / 224 (case-insensitive); the earlier tool reported 41 / 148 / 494. The scenario count matches, the case count is lower
  by design. To confirm with the user.
- Contact classes group contact-level value combinations by the truth of every pure contact-level outcome formula (and of each
  contact-level condition of a mixed formula): 8 classes on the pilot, as the spec says.
- "Other" text value is `OTHER` (or `OTHER_2`, ... when taken); Booleans always take both values; null is added when the schema allows.
- Statistical case: engagement splits downstream of the random split take the No branch (no manual action is asked in a statistical case).

## Next

- See "Remaining plan" above. After it: hand over with the final report; the assumptions in docs/assumptions.md stay to be
  verified with a small real run.

## To report to the user (spec corrections suggested by the Salesforce review, not changed in code)

- Entry procedure: the review says importing the entry CSV alone admits nobody; the automation (with its journey-entry step) must run,
  and a full run also executes the entry query (duplicating entry rows) and the verification step. The spec presents direct import as
  the normal way. The generator still writes all four CSVs, so both procedures are possible; the report lists both as alternatives.
- Wait dates: the spec default (generation time, "so the wait ends at once") is not guaranteed if Salesforce reads the CSV date in
  another time zone (CST); a negative wait offset would be safer. Setting kept at the spec default.
- Letter case moves 46 branches between covered and not covered on the pilot; the setting default (case-sensitive) is the spec's.

## Open questions

- Pilot under the default case-sensitive comparison: 137 of 259 split branches are unreachable because `CHANNEL2 Equal 'EMAIL'` /
  `CHANNEL3 Equal 'EMAIL'` can never be true on paths that passed `CHANNEL2 Equal 'Email'` earlier. The spec's acceptance line says the
  four engagement Yes branches after channels 2 and 3 are unreachable "because all six engagement splits reference the first email";
  that is the reason only when text comparisons ignore case (then 91 branches stay unreachable). Both readings give the same status.
- `RUN_TIME` (nullable Date, no condition, no entry query filter) stays empty, not the generation time of the spec rule "other date fields";
  the config-update query filters `WHERE RUN_TIME IS NULL`, so the generator keeps it empty. This differs from the spec rule.

## Facts checked on the pilot export

- 178 activities: 106 decision splits, 34 update contact, 13 waits (3 by attribute on Config.WAIT1-3, 10 by duration of 1 minute), 11 emails (all the same asset "Demo Sky", no link), 7 send-time waits, 6 engagement splits (all reference EMAILV2-1), 1 random split 90/10.
- Start activity: `MULTICRITERIADECISIONV2-1` (Control Group Required). All 178 activities are structurally reachable.
- Entry query joins Master -> Target on `ContactId = SalesforceId`, Target -> Config on `Description = CampaignName`; filters `C.active = 'True'`, `HAS_RUN = 'False'`, date range on `START_DATE`/`END_DATE`.
- With the default case-sensitive comparison, `CHANNEL2 Equal 'EMAIL'` (channel-2 email check) can never be true on a path that reached it through `CHANNEL2 Equal 'Email'`, so the channel-2 and channel-3 engagement splits are unreachable entirely; their Yes branches are unreachable anyway because EMAILV2-1 is only sent when CHANNEL1 is Email, which routes to the channel-1 engagement split instead.
