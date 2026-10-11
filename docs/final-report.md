# Final report: CJ Test Helper PoC

11 October 2026. Branch `claude/dazzling-ramanujan-l38jta`. Resume from `docs/progress.md`.

## What passes

On the pilot export (`fixtures/CJ template complesso-v1.json`), with the default settings plus a real inbox:

- The journey `CJ_SkYDE_NCRM_Demo_final` is read with its 178 activities. Exactly four CSVs are produced (Entry, Master, Target, Config).
- Every CSV has its schema's columns, unique primary keys and values that respect type and length. Every Target row joins a Master row and a Config row. Every Entry row is what the entry query would produce from the other three CSVs.
- Every reachable branch of the 106 decision splits is covered by a case of 3 contacts. The 90/10 random split has one statistical case of 50 contacts with the accepted range 1 to 9.
- The four engagement Yes branches after channels 2 and 3 are reported as unreachable. The three contacts that must open an email use the real inbox with plus-addressing; the other 143 use `@example.invalid`.
- `testbook.xlsx` has one test per case and names every contact; the totals of `report.md` match the files. Two runs with the same settings give identical files.
- All seven trust checks pass, including an independent re-simulation of every contact from the written files. A fresh test engineer confirmed the same by their own simulator, with no code from the package.
- 39 hand-derived examples (17 from the first test engineer, 22 from the fresh one) pass. The unit suite has about 680 tests.
- The one-page Streamlit app works end to end (upload, review, settings, generate, download); a UX review passed it with changes, which were applied.

Default run on the pilot: 23 scenarios, 33 cases, 146 contacts; 120 branches covered, 2 covered with a manual action, 137 not covered. With text comparisons ignoring letter case: 41 scenarios (the earlier tool's 40 plus 1), 59 cases, 224 contacts, 91 branches not covered.

## What does not pass, or differs from the spec text

- "The PoC should land in the same range" as the earlier tool (148 cases, 494 contacts): not met by design. The generator picks the fewest scenarios and then the fewest cases that cross every branch (33 cases). Adding every contact class to every chosen scenario would give about 180 cases; it is a one-line change in the cover if you prefer that reading.
- The spec's acceptance reason for the engagement splits after channels 2 and 3 ("because all six engagement splits reference the first email") holds only when text comparisons ignore letter case. With the default case-sensitive comparison, those splits are unreachable earlier, because `CHANNEL2 Equal 'EMAIL'` can never be true on a path that passed `CHANNEL2 Equal 'Email'`. The report states both: the root cause of each unreachable branch, and the suspicious pattern that the splits measure an older email than the last one sent.
- Journeys with very many contact-level fields read by splits (more than about a million value combinations) or with more than 400,000 distinct paths are not fully explored; the coverage check then fails and says so, instead of claiming coverage.
- `RUN_TIME` in the pilot's Config table is left empty rather than set to the generation time (the spec's rule for other dates), because the automation's own configuration-update query reads `WHERE RUN_TIME IS NULL`.
- The wait date before an engagement split gets the 24-hour offset only when a case of that scenario actually needs an open or click; the spec's wording would add it to every wait on the path to an engagement split.

## Spec corrections suggested by the Salesforce review (`docs/assumptions.md`)

- Importing the entry CSV alone may admit nobody: a Data Extension entry source scheduled by an automation admits contacts when the automation runs. The report gives both procedures as alternatives and the point is listed as an assumption to verify first.
- The wait date default (generation time, "so the wait ends at once") is not guaranteed if Salesforce reads the CSV date in another time zone; a negative wait offset is safer. The setting is kept at the spec's default.
- All seven data extensions in the export carry a retention policy; if it is active in the test business unit, the rows disappear during the run.

## Salesforce assumptions still to verify

`docs/assumptions.md` lists 35, with a one-day verification plan (3 Config rows, 7 contacts). The six from the spec first; the most consequential additions: how contacts enter (rows 23 to 27), letter case (row 2, moves 46 branches), retention (row 32), an empty Boolean against `Is false` (row 7), opens on an email with no open-tracking element (row 15), the time zone of wait dates (row 6).

## Design readings taken (not Salesforce assumptions)

- Fewest scenarios, then fewest cases inside them. Contact classes group contact-level value combinations by the truth of every pure contact-level outcome formula (8 on the pilot).
- A field read by a split and fixed by an entry-query filter, a literal select expression or the generated key takes only that value; the other outcomes are reported unreachable with the reason.
- An unknown operator or an unknown field makes only that outcome unsupported; earlier outcomes stay coverable. The remainder is evaluated last whatever its position.
- A split that reads the address field fixes the address; an open or click on such a case is reported as not covered, the case still exists.
- Two engagement splits on one path get cumulative wait offsets.

## Known limits

Branch coverage, not path coverage. Random splits are covered statistically. Only the listed activity types, operators and SQL shapes are understood; the rest is reported. Entry criteria set outside the export are not seen. Email content is not tested.

## Where things are

- Code: `cjhelper/` (model, loader, criteria, sqlparse_lite, tables, graph, coverage, datagen, checks, outputs, pipeline, app). Command line: `python -m cjhelper <export> --out <dir> --inbox <address>`. Page: `streamlit run cjhelper/app.py`.
- Documents: `README.md`, `docs/spec.md`, `docs/plan.md`, `docs/export-format.md`, `docs/assumptions.md`, `docs/ux-review.md`, `docs/progress.md`.
- Examples: `examples/<name>/` with `package.json`, `expected.json`, `README.md`; `tests/test_examples.py` runs them.
