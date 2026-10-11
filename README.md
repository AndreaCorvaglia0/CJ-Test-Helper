# CJ Test Helper

CJ Test Helper reads a Salesforce Marketing Cloud package export, the JSON file that Package Manager produces, and writes test data that sends contacts down every branch of the customer journey. It writes one CSV per table that the journey reads, a list of scenarios, a coverage report and a testbook with the expected result of each test. It never connects to Salesforce: it only generates files, and it checks them before you use them.

`docs/spec.md` is the source of truth for what the tool does. This file explains how to run it and how to use what it writes.

## Requirements and install

- Python 3.11 or later.
- The packages listed in `requirements.txt`:

```
pip install -r requirements.txt
```

## Run it

From the repository folder:

```
python -m cjhelper "fixtures/CJ template complesso-v1.json" --out output --inbox name@example.com
```

The command prints a summary and the result of each trust check. It writes every file into the output folder, together with `test_data.zip`, which holds them all. On the pilot export it takes about 30 seconds.

| Option | What it does |
| --- | --- |
| `export` | The package export JSON. Required. |
| `--out FOLDER` | Where to write the files. Default `output`. |
| `--run-id R01` | Run identifier added to every key, as in `TST_R01_C0001`. Default `R01`. |
| `--inbox ADDRESS` | Real inbox for the contacts that must open or click an email. Default empty. |
| `--phone NUMBER` | Real phone number. No supported activity sends to a phone yet, so it is not used today. Default empty. |
| `--contacts N` | Contacts per case. Default 3. |
| `--random-contacts N` | Contacts in the statistical case of a random split. Default 50. |
| `--case-insensitive` | Text comparisons ignore letter case, so `Email` matches `EMAIL`. Default off. |
| `--no-single-active` | Makes every scenario active in the CSVs at once. By default only the first one is. |
| `--time "YYYY-MM-DD HH:MM"` | Generation time. Default now. Give the same time to get the same files again. |
| `--no-testbook` | Skips `testbook.xlsx`. |

The command ends with code 0 when every trust check passes, and with code 2 when a check fails. On an error, such as a file that is not valid JSON or holds no journey, it prints one plain message, writes nothing and ends with code 1.

## What you get

| File | What it holds |
| --- | --- |
| `<TableName>.csv` | One file per table that the journey or the entry query reads, with all scenarios together, ready to import. UTF-8, comma-separated, the exact field names of the schema as header, `True` and `False` for Booleans, an empty cell for null. |
| `scenarios.csv` | One row per scenario: its key, its run order, which scenario is active at the start, its cases and contacts, and its scenario-level values. |
| `report.md` | Read it first. Summary, trust checks, tables, how to run, scenarios and cases, branches not covered and why, unsupported elements, warnings and suspicious patterns, assumptions, settings used. |
| `testbook.xlsx` | One test per case in the team's layout: ID, Owner system, Test name, Description, Pre conditions, Detailed steps, Expected result, Status, Note. |
| `test_data.zip` | All the files above in one archive. |

Words used in these files:

- A **branch** is one outcome of a split: a decision split, an engagement split or a random split.
- A **scenario** is one set of scenario-level values, such as one row of a campaign configuration table. All its contacts share it.
- A **case** is a group of contacts with the same contact values and the same manual actions, so they take the same path. Each case is one test in the testbook. It has 3 contacts by default.
- A **statistical case** covers the branches behind a random split. Its contacts cannot be sent down one branch, so it has 50 contacts by default.

## How a tester uses the files

1. Open `report.md`. Check that every trust check passed, then read its "How to run" section.
2. Choose one entry procedure and keep it for the whole test. The two are alternatives: doing both would duplicate the entry rows.
   - Direct import, the normal way in the spec. Import the CSVs of the linked tables first and the entry CSV last. Do not run the automation that fills the entry table.
   - Through the automation. Import every CSV except the entry CSV. Run the automation once per scenario: its entry query builds the entry rows from the imported rows.
3. Run one scenario at a time, in run order. The CSVs start with the first scenario active. To make a scenario the active one, set the activation field to True on the row of the scenario and to False on every other row. The report names the field: `ACTIVE` of `DE_NCRM_AD_HOC_CONFIG` in the pilot.
4. Wait until the contacts of a scenario have left the journey before you switch to the next one. Change nothing else and import nothing again, because the journey reads the split data when a contact reaches a split.
5. Follow the testbook, one row per case. The steps give the waits, any manual action with its deadline, and the evidence to collect. Compare what you see with the Expected result.
6. For a new generation, use a new run identifier. Keys of an earlier run are already in the tables, and a test contact is never reused.

Assumption to verify before the first real run: when an automation fills the entry table, as in the pilot, importing the entry CSV alone may admit nobody. The direct import may then also need a Run Once of that automation with only its journey-entry activity selected. Rows 23 to 27 of `docs/assumptions.md` explain why.

### The real inbox

Contacts that must open or click an email get your real inbox with plus-addressing. With `--inbox name@example.com`, the contact `TST_R01_C0004` gets `name+TST_R01_C0004@example.com`, and its emails arrive in `name@example.com`. Every other contact gets an undeliverable address, `<contact key>@example.invalid`.

- Open or click only the emails that the testbook names, and only for the contacts of that test.
- Do it before the deadline in the testbook. The deadline is the end of the wait before the engagement split, 24 hours after the generation time by default. Scenarios with a manual action come first in the run order for this reason.
- If a run starts too late to meet a deadline, generate the data again.
- Without `--inbox`, generation still works. Those contacts get undeliverable addresses, and the branches that need an open or a click are reported as not covered.

A click can be asked only when the email has a link. In the pilot the email has none, so the click branches are reported as not covered.

### The random split case

A random split cannot be forced. Its branches get one statistical case, with 50 contacts by default, and the testbook gives the accepted range for the smaller side. For a 90/10 split, 1 to 9 of the 50 contacts should take the 10% side. That holds in about 97% of runs, so a count outside the range can happen by chance.

## Trust checks

After writing the files, the generator reads them back and checks them. The report gives the result of each check and its details.

| Check | A failure means |
| --- | --- |
| Values respect type, length, nullability and primary key | The import could reject rows or cut values. |
| Every key joins across tables | Some contacts would miss their scenario row or their rows in a linked table, so their splits would not see the intended values. |
| Entry rows match the entry query | The entry CSV does not hold what the entry query would build from the other CSVs, so the two entry procedures would give different data. |
| Every contact re-simulated from the files takes its intended path | The expected result in the testbook may be wrong for some contacts. |
| Every reachable branch is covered and every uncovered branch has a reason | The coverage given in the report cannot be trusted. |
| Only contacts with a manual action use the real inbox; all others are undeliverable | Emails could reach the real inbox when they should not. |
| Two runs with the same input give the same files | The same export and settings would not give the same data. |

When a check fails, the command ends with code 2 and the report lists the failures. Do not import the files until the failure is explained.

## Settings and defaults

These are the settings of the spec. The command line uses the defaults, and the options above change some of them. The report ends with the settings used for the run.

| Setting | Default | Option |
| --- | --- | --- |
| Contacts per case | 3 | `--contacts` |
| Contacts per random-split case | 50 | `--random-contacts` |
| Real inbox for open and click tests | Empty | `--inbox` |
| Real phone number | Empty | `--phone` |
| Fake phone number | `333333333333` | none |
| Validity window length | From yesterday to 7 days ahead | none |
| Wait date offset | 0 hours | none |
| Wait date offset before an engagement split | 24 hours | none |
| Date format in the CSVs | `YYYY-MM-DD HH:MM` | none |
| One active scenario at a time | On when an activation field is detected | `--no-single-active` turns it off |
| Activation field | Suggested from the entry query filters | none |
| Run identifier in keys | R01 | `--run-id` |
| Text comparisons ignore letter case | Off | `--case-insensitive` |

## How the values are chosen

Each value comes from the first of these rules that applies:

1. A key or join field gets a generated key, the same in every table that joins on it: `TST_R01_C0001` for contacts, `TST_R01_S01` for scenarios.
2. A field read by a split gets the value the case needs, written exactly as in the condition, with the same letter case.
3. A field filtered by the entry query gets a value that passes the filter, so the contact really enters the journey.
4. An email address gets the real inbox or `@example.invalid`, as above. A phone gets the fake number. The validity window runs from yesterday to 7 days ahead. A wait date is the generation time, meant to end the wait at once, or 24 hours later when the contacts must open an email after that wait.
5. Any other field gets a placeholder: text `TST_<field>_<n>` cut to the field length, Booleans their default or False.

## Known limits

- Branch coverage, not path coverage: every branch is crossed at least once, but not every combination of branches.
- Random splits are covered statistically, never with certainty.
- Only the supported activity types, operators and SQL patterns are understood. Anything else is listed in the report, and the branches behind it are marked as not covered. Nothing is guessed.
- Entry criteria defined outside the JSON, such as contact filters set in the interface and not exported, are not seen.
- Email content and personalisation are not tested. The tool tests the routing of contacts.

Supported in the PoC:

- Activities: decision split, engagement split, random split, wait by duration, wait by attribute, send-time wait, email, update contact.
- Condition operators: `Is`, `Equal` and `IsNull`, plus `NotEqual`, `IsNotNull`, `GreaterThan`, `GreaterThanOrEqual`, `LessThan`, `LessThanOrEqual`, `Contains`, `BeginsWith` and `EndsWith`, carried over from the earlier tool.
- SQL in the entry queries: table names, join equalities, simple WHERE filters on equality, null and date range, and simple select expressions. A more complex filter or expression is reported, and an entry column that depends on it gets a placeholder.

## Assumptions to verify

In a few places the expected results depend on Salesforce behaviour that the spec does not settle: letter case in text comparisons, how a wait date without a time zone is read, how contacts enter through an entry automation, and more. Each one is an assumption to verify once with a small real run, never a fact.

- `docs/assumptions.md` lists them all, with the documentation found and how to verify each one, and it plans a one-day verification run. Start with its "Check these first" section.
- The "Assumptions" section of `report.md` lists the ones that apply to the export you ran.

## The one-page app

The one-page app is a later step, priority 5 in the spec: upload the export, review what was detected, adjust the settings, generate and download the zip. A first version is in `cjhelper/app.py` and starts with `streamlit run cjhelper/app.py`. Until it is confirmed, use the command line.

## For developers

| Path | What it holds |
| --- | --- |
| `docs/spec.md` | The specification, the source of truth |
| `docs/plan.md` | How the spec is split into modules |
| `docs/progress.md` | State of the work and open questions |
| `docs/assumptions.md` | The Salesforce review: assumptions to verify and suspicious patterns |
| `cjhelper/` | The generator, one module per step of the spec |
| `tests/` | Unit tests per module, the examples and the end-to-end pilot test |
| `examples/` | Small hand-made journeys with their expected answers |
| `fixtures/` | The pilot export |

Run the tests with `python -m pytest`. The pilot tests take about a minute.
