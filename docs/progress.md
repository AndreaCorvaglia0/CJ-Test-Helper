# Progress

Resume from this file. Spec: `docs/spec.md`. Contract: `docs/plan.md`.

## Done

- Repository set up: spec copied to `docs/spec.md`, pilot export to `fixtures/`, old tool kept only in git history (commit 83f0f65) as reference.
- `cjhelper/model.py`: the shared data model and module contract.
- `docs/plan.md`: module responsibilities and function signatures. `docs/export-format.md`: export shape for hand-made examples.

## In progress (priority 1, core)

- loader.py + criteria.py, sqlparse_lite.py, tables.py, datagen.py + outputs.py (CSV part): delegated, one developer each.
- graph.py, coverage.py, checks.py, pipeline.py: lead.
- examples/: test engineer writes small journeys with hand-derived expected answers.
- Salesforce review of the model and data rules: expert lists assumptions to verify.

## Next

- Run the example loop on priority 1; fix root causes; every bug becomes an example.
- Priority 2: scenarios.csv and report.md wording. Priority 3: engagement and random splits end to end on the pilot. Priority 4: testbook. Priority 5: Streamlit page.

## Open questions

- None yet.

## Facts checked on the pilot export

- 178 activities: 106 decision splits, 34 update contact, 13 waits (3 by attribute on Config.WAIT1-3, 10 by duration of 1 minute), 11 emails (all the same asset "Demo Sky", no link), 7 send-time waits, 6 engagement splits (all reference EMAILV2-1), 1 random split 90/10.
- Start activity: `MULTICRITERIADECISIONV2-1` (Control Group Required). All 178 activities are structurally reachable.
- Entry query joins Master -> Target on `ContactId = SalesforceId`, Target -> Config on `Description = CampaignName`; filters `C.active = 'True'`, `HAS_RUN = 'False'`, date range on `START_DATE`/`END_DATE`.
- With the default case-sensitive comparison, `CHANNEL2 Equal 'EMAIL'` (channel-2 email check) can never be true on a path that reached it through `CHANNEL2 Equal 'Email'`, so the channel-2 and channel-3 engagement splits are unreachable entirely; their Yes branches are unreachable anyway because EMAILV2-1 is only sent when CHANNEL1 is Email, which routes to the channel-1 engagement split instead.
