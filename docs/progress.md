# Progress

Resume from this file. Spec: `docs/spec.md`. Contract: `docs/plan.md`.

## Done

- Repository set up: spec copied to `docs/spec.md`, pilot export to `fixtures/`, old tool kept only in git history (commit 83f0f65) as reference.
- `cjhelper/model.py`: the shared data model and module contract.
- `docs/plan.md`: module responsibilities and function signatures. `docs/export-format.md`: export shape for hand-made examples.

- `loader.py` + `criteria.py` (195 tests), `sqlparse_lite.py` (143 tests), `tables.py` (27 tests): delivered and reviewed.
- `graph.py`, `coverage.py`, `checks.py`, `pipeline.py`, `__main__.py` (lead): first integrated run on the pilot passes all 7 trust checks.
  `python -m cjhelper "fixtures/CJ template complesso-v1.json" --out output --inbox tester@example.com` takes about 30 s.

## In progress (priority 1, core)

- datagen.py + outputs.py: delivered on disk, developer's report pending.
- examples/: test engineer writes small journeys with hand-derived expected answers (pending).
- Salesforce review (docs/assumptions.md): pending.
- Then: the example loop on priority 1.

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

- Run the example loop on priority 1; fix root causes; every bug becomes an example.
- Priority 2: scenarios.csv and report.md wording. Priority 3: engagement and random splits end to end on the pilot. Priority 4: testbook. Priority 5: Streamlit page.

## Open questions

- Pilot under the default case-sensitive comparison: 137 of 259 split branches are unreachable because `CHANNEL2 Equal 'EMAIL'` /
  `CHANNEL3 Equal 'EMAIL'` can never be true on paths that passed `CHANNEL2 Equal 'Email'` earlier. The spec's acceptance line says the
  four engagement Yes branches after channels 2 and 3 are unreachable "because all six engagement splits reference the first email";
  that is the reason only when text comparisons ignore case (then 91 branches stay unreachable). Both readings give the same status.
- `RUN_TIME` (nullable Date, no condition, no filter) is filled with the generation time per the spec rule "other date fields";
  the config-update query filters `WHERE RUN_TIME IS NULL`, so null may be more realistic. Spec rule kept.

## Facts checked on the pilot export

- 178 activities: 106 decision splits, 34 update contact, 13 waits (3 by attribute on Config.WAIT1-3, 10 by duration of 1 minute), 11 emails (all the same asset "Demo Sky", no link), 7 send-time waits, 6 engagement splits (all reference EMAILV2-1), 1 random split 90/10.
- Start activity: `MULTICRITERIADECISIONV2-1` (Control Group Required). All 178 activities are structurally reachable.
- Entry query joins Master -> Target on `ContactId = SalesforceId`, Target -> Config on `Description = CampaignName`; filters `C.active = 'True'`, `HAS_RUN = 'False'`, date range on `START_DATE`/`END_DATE`.
- With the default case-sensitive comparison, `CHANNEL2 Equal 'EMAIL'` (channel-2 email check) can never be true on a path that reached it through `CHANNEL2 Equal 'Email'`, so the channel-2 and channel-3 engagement splits are unreachable entirely; their Yes branches are unreachable anyway because EMAILV2-1 is only sent when CHANNEL1 is Email, which routes to the channel-1 engagement split instead.
