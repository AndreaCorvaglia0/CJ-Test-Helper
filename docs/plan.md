# Build plan and module contract

This document is the working contract between the modules of `cjhelper/`.
`docs/spec.md` is the source of truth; this file only fixes *how* the spec is
split into code. If the two disagree, the spec wins and this file is wrong.

## Package layout

```
cjhelper/
  model.py          shared dataclasses: the only file every module imports (frozen contract)
  loader.py         export JSON -> Package           (resolves {{mcpm#...}}, builds Journey, Tables, Queries)
  criteria.py       FilterDefinition XML -> Formula; operator lookup table and condition evaluation
  sqlparse_lite.py  Query -> ParsedQuery              (sqlglot, T-SQL)
  tables.py         Package -> TableModel             (table selection rule, field levels, key groups)
  graph.py          journey graph walk and simulation (lead)
  coverage.py       value enumeration, set cover, scenarios and cases (lead)
  datagen.py        CoverageResult -> GeneratedData   (data generation rules)
  checks.py         trust checks on the written files (lead)
  outputs.py        CSV, scenarios.csv, report.md, testbook.xlsx, zip
  pipeline.py       generate(source, settings) -> GenerationResult (lead)
  __main__.py       command line: python -m cjhelper export.json --out dir
  app.py            Streamlit page (priority 5, later)
tests/              pytest, one file per module, plus test_examples.py and test_pilot.py
examples/           small hand-made journeys with expected answers (see "Examples")
fixtures/           the pilot export
```

Rules for everyone:

- Python 3.11+, standard library plus `sqlglot`, `openpyxl`, later `streamlit`. Nothing else.
- Plain, readable code. Short functions, explicit names, no cleverness. Docstrings say *what the spec rule is*.
- `model.py` is frozen for you. If you need a change there, say so in your final report; do not edit it.
- Only create or edit your own module and its test file. Never touch another module.
- Never invent Salesforce behaviour. When the spec does not say, pick the simplest reading, make it visible (a `warnings` entry or a report line) and list it under "Assumptions" in your final report.
- Nothing is hard-coded to the pilot journey. Table and field names come from the export.
- Every value is a `str` in CSV form, or `None` for null. Booleans `"True"`/`"False"`. Dates in `Settings.date_format`.
- Field lookups are case-insensitive (`Table.field(name)`); the schema spelling is what gets written.
- Run `python -m pytest tests/test_<yourmodule>.py -q` before you finish.

## Module contracts

### loader.py

```python
class LoadError(Exception): ...          # invalid JSON, no journey, missing entry table
def load_package(source) -> Package      # source: bytes, str (JSON text or path), dict, or pathlib.Path
```

- Resolve every `{{mcpm#/entities/<kind>/<id>/data/<path>}}` reference first, everywhere (strings inside
  strings included, e.g. inside criteria XML and SQL). Rules: `.../data/name` -> the entity name;
  `.../data/id` -> the entity id (the export key); `.../data/fields/name:<F>/id` -> the field name `<F>`;
  `.../data/namePrefix` -> the value if present else `""`; `.../data/eventDefinitionKey` and other
  existing paths -> the value; a missing path -> the entity id plus a warning. `{{mcpm:...}}` placeholders
  (sender profile, delivery profile) stay as they are. SQL `prefix[name]` becomes `[name]`.
- Journey choice: `selectedEntities.journeys[0]` when present, else the only journey, else the first with a warning.
  No journey at all -> `LoadError`.
- Activities: map `type` through `model.ACTIVITY_KINDS`; `WAIT` with `metaData.uiType == "WAITBYATTRIBUTE"`
  is `KIND_WAIT_ATTRIBUTE` (field from `configurationArguments.waitEndDateAttributeExpression`, last quoted
  segment = field, segment before it = attribute set -> table; `metaData.attribute.id` is the fallback).
  Unknown types -> `KIND_UNSUPPORTED` and the key goes to `Package.unsupported_activities`.
- Decision splits: for each outcome, `configurationArguments.criteria[outcome.key]` is parsed with
  `criteria.parse_criteria`; the outcome without criteria is the remainder (`is_remainder=True`, formula None).
  Condition `table` is the attribute-set name; map it to the Data Extension name through
  `attributeSets[*].storageName` (fall back to the name itself when no set matches, with a warning).
  Keep the outcomes in export order (it is the evaluation order).
- Engagement splits: `configurationArguments.refActivityCustomerKey` -> `engagement_ref`;
  `statsTypeId` through a lookup `ENGAGEMENT_KINDS = {2: "open", 3: "click"}`; anything else ->
  `engagement_kind = None` and a warning (the branch will be reported as not covered).
  Outcomes carry `when` from `arguments.when`.
- Random splits: `percentage` from `outcomes[*].arguments.percentage`.
- Emails: `configurationArguments.triggeredSend.emailId` resolves to the asset id; `email_name` from the asset
  name, else the activity name. `EmailAsset.has_link` = an `href=` or `<a ` appears in `views.html.content`
  or `views.text.content`.
- Update contact: `arguments.activityData.updateContactFields[*]` -> `Write(table, field, value)`; value kept
  as written (`str(value)` for numbers), `{{DateTime.Now}}` kept literally.
- Start activity: the one no outcome points to (one expected; several -> first in export order plus a warning).
- Entry: the trigger's `metaData.eventDefinitionId` -> eventDefinition -> `dataExtensionId` -> table;
  `arguments.automationId` -> automation name. `Journey.default_email_event_key` = the event key inside
  `defaults.email[0]` (for the anomaly check "default reads a different entry event").
- Tables: all `dataExtensions` (and `sharedDataExtensions`), fields in `ordinal` order.
- Relationships: `attributeRelationships` -> one `Relationship` per `relationshipAttributes` entry, tables
  resolved through the attribute sets (`leftItem.identifier` / `rightItem.name`) to Data Extension names.
  `isGroupToSetRelationship` -> `left_table=None`.
- Queries: every `queryActivities` entry; `Package.automation_queries[automation name]` lists the query names
  in step order (`steps[*].activities[*]` with `objectTypeId == 300`).

### criteria.py

```python
class CriteriaError(Exception): ...
def parse_criteria(xml: str) -> Formula
OPERATORS: dict[str, Callable]            # the one lookup table for operators
def evaluate_condition(cond: Condition, value: Value, field_type: str, case_insensitive: bool) -> bool
class UnsupportedOperator(Exception): ...
```

- XML: `<FilterDefinition><ConditionSet Operator="AND|OR">` nesting `<Condition Key="Set.Field" Operator="..">`
  with the value in `<Value>` (CDATA, possibly empty), sometimes wrapped in one or more `<AttributePath>`.
  `Key` splits on the first `.` into set and field (field names may contain spaces). A set with one item
  collapses to that item. An empty set or an unknown element -> `CriteriaError`.
- Operators, all from the spec: `Is`, `Equal`, `IsNull` (pilot) plus `NotEqual`, `IsNotNull`, `GreaterThan`,
  `LessThan`, `GreaterThanOrEqual`, `LessThanOrEqual`, `Contains`, `BeginsWith`, `EndsWith` (carried over).
  Semantics in `evaluate_condition` (the value is always the CSV string or None):
  - Boolean: compare after lower-casing, accepting `true/false/1/0`.
  - Text, EmailAddress, Phone, Locale: exact match; case-insensitive when the setting says so.
  - Number/Decimal: numeric compare. Date: parse both sides (`YYYY-MM-DD[ HH:MM[:SS]]`, ISO); date-only
    condition values compare on the date part.
  - `IsNull`: None or `""`. `IsNotNull`: the opposite. Any other operator on None -> False (assumption, list it).
  - Unknown operator -> `UnsupportedOperator`.

### sqlparse_lite.py

```python
def parse_query(query: Query, tables: dict[str, Table]) -> ParsedQuery
```

- `sqlglot` with `read="tsql"`. Table names arrive as `[Name]` or `ENT.[Name]`; aliases are common.
- `sources`: FROM and every JOIN table. `joins`: equalities from ON clauses (AND-chained); anything else -> warning.
- `filters`: WHERE split on top-level AND. `col = 'lit'` -> `EqualityFilter`; `col IS [NOT] NULL` -> `IsNullFilter`;
  a comparison between the current date (`GETDATE()`, `GETUTCDATE()`, `SYSDATETIME()`, with or without `CAST(... AS DATE)`)
  and a column -> `DateBoundFilter` with `bound="start"` when the filter means *now >= column* and `"end"` when
  *now <= column*, whichever side the column is on. Everything else, including any OR group -> `UnsupportedFilter(text)`.
- `select`: column -> `SelectColumn`; string/number literal -> `SelectLiteral`; `FORMAT(GETUTCDATE(), 'fmt')` ->
  `SelectCurrentDate(fmt)`; a bare current-date call, also wrapped in `AT TIME ZONE` -> `SelectCurrentDate(None)`;
  `CONCAT(...)` -> `SelectConcat`; anything else -> `SelectUnsupported(text)`. `target_column` = alias, else column name.
  `SELECT *` -> `select_all=True`, select empty.
- Column resolution: alias -> table name; unqualified -> the unique source table having that column
  (case-insensitive, via `Table.field`); otherwise `ColumnRef("", col)` plus a warning.
- Never raise on odd SQL: return what was understood and put the rest in `warnings`.

### tables.py

```python
def build_table_model(package: Package) -> TableModel
```

Calls `sqlparse_lite.parse_query` itself. Rules (spec "Table selection" and "Classify fields by level"):

- Entry table: `journey.entry_table`. Entry query: the query in the entry automation whose target is the entry
  table (last one in step order if several, with a warning); none -> `entry_query=None` and a warning.
- Split tables: tables named in any decision condition or wait-by-attribute field.
- Source tables: FROM/JOIN of the entry query, then for each source any query whose target is that source
  (entry automation first, then the rest of the package), recursively, with a visited set. Record the parsed
  queries in `source_queries`.
- Written-only: targets of update-contact writes or of queries that are not entry, split or source -> not selected.
  Tables with no role at all -> not selected, reason "not read or written by this journey".
- Contact key: `(entry table, entry table's sendable_field)`; fall back to the group-to-set relationship's
  right field on the entry table, then to a single-field primary key; otherwise a warning and the first PK field.
- Key groups: union-find over every join equality (query joins and relationships); the group holding the contact
  key field is `kind="contact"`; a group holding a field of a scenario-level table is `kind="scenario"`; others `"other"`.
- Levels: breadth-first from the entry table along join edges between selected tables. A table reached through a
  contact-group field is contact-level; reached through any other field it is scenario-level; a scenario-level
  table's neighbours stay scenario-level. Field levels follow their table, except fields of a contact-level
  table that belong to a scenario key group (they hold the scenario key).
- `activation_field`: from the entry query filters, the first `EqualityFilter` on a Boolean field of a
  scenario-level table with value `True`/`true`; else None.
- Every decision goes into `TableRole.reason` or `warnings` in plain words.

### graph.py and coverage.py (lead)

Produce `CoverageResult`. What the consumers can rely on:

- `Scenario.values` has every field in `CoverageResult.scenario_fields`; `Case.contact_values` every field in
  `contact_fields`. Values are CSV strings or None. "Other" text values look like `OTHER`.
- `Case.steps` is the full deterministic path; for the statistical case it stops at the random split and
  `Case.random.branches` holds the continuation per outcome.
- `Scenario.run_order` starts at 1; scenarios with manual actions come first. `Case.id` is `S01-C01`.
- `Case.contact_count` is 3 or the random-case count. `Case.waits` lists wait activity keys crossed, in order.
- `ManualAction` tells datagen which contacts need the real inbox.

### datagen.py

```python
def generate_data(package: Package, model: TableModel, coverage: CoverageResult,
                  settings: Settings, generation_time: datetime) -> GeneratedData
```

Implements the spec's "Data generation rules" exactly, in priority order. Also fills `Scenario.key` and
`Case.contact_keys` in place, and `Contact` records.

- Rows: one contact row per contact in every contact-level selected table; one row per scenario in every
  scenario-level table; the entry table rows are computed from the entry query's `select` expressions over the
  source rows (`SelectColumn` -> value of the joined source row; `SelectLiteral`; `SelectCurrentDate` ->
  generation time in the .NET format converted to strftime, `None` format -> `Settings.date_format`;
  `SelectConcat`; `SelectUnsupported` -> placeholder and an entry in `placeholders`). Entry columns not in the
  select get the schema default (Boolean `False` when default says so), else None; a non-nullable one gets a
  placeholder and a `placeholders` entry. `select_all` copies same-named columns.
- Key groups: contact group -> `settings.contact_key(n)`, scenario group -> `settings.scenario_key(run_order)`,
  other groups -> `TST_<run>_K<n>` shared across the group.
- Fields read by splits: the case's/scenario's value, exactly as given. Null -> None.
- Entry query filters: `EqualityFilter` -> that value (Boolean written `True`/`False`); `DateBoundFilter`
  start -> window start, end -> window end; `IsNullFilter` -> None. The activation field under
  "one active scenario" is `True` only for `run_order == 1`.
- Wait-by-attribute fields: generation time + `wait_offset_hours`, or + `wait_offset_before_engagement_hours`
  when a case of that scenario crosses the wait and later has a manual action (per scenario for scenario-level
  fields, per contact for contact-level ones).
- Email fields (`EmailAddress` type, or named like `Email*`): real inbox with plus addressing
  `local+<contact key>@domain` for contacts of a case with a manual action when `settings.real_inbox` is set,
  else `<contact key>@example.invalid`. Phone fields: `fake_phone` (real phone hook: no supported activity sends
  to a phone, so keep `uses_real_phone=False` and say so in the module docstring).
- Other fields: Text `TST_<field>_<n>` cut to length (`n` = row number in that table), Boolean default or
  `False`, Date generation time, Number/Decimal `str(n)`, Locale `en-US`.
- `scenarios_rows`: one per scenario: `scenario_key, run_order, has_manual_action, is_statistical, case_count,
  contact_count, first_contact_key, last_contact_key, activate` plus one column per scenario field `Table.Field`.

### outputs.py

```python
def write_table_csv(data: TableData, table: Table) -> bytes      # UTF-8, comma, header in schema order, \n
def write_scenarios_csv(rows: list[dict]) -> bytes
def write_report(result: GenerationResult) -> str                # markdown, see spec "Outputs"
def write_testbook(result: GenerationResult) -> bytes            # openpyxl, spec columns; priority 4
def build_zip(files: dict[str, bytes]) -> bytes
```

CSV: `csv.writer` with default quoting, `lineterminator="\n"`, None -> empty cell. Report sections, in order:
summary (scenarios, cases, contacts; branches covered / covered with manual action / not covered), trust checks
(each with pass/fail and details), tables (name, role, level, CSV yes/no, reason), scenarios (key, values, cases),
branches not covered (activity, outcome, reason), unsupported elements, warnings and suspicious patterns,
assumptions, settings used.

### checks.py (lead)

Reads the written CSV bytes back and runs the five trust checks of the spec. Returns `list[CheckResult]`.

## Examples

`examples/<name>/package.json` is a package export in the same shape as the pilot (see
`docs/export-format.md`), small enough to reason about by hand. `examples/<name>/expected.json` is the
answer derived by hand from the spec. `examples/<name>/README.md` says what the example tests and how the
expected answer was derived, step by step, quoting the spec rule used.

`expected.json` keys (all optional except `branches`):

```json
{
  "journey_name": "...",
  "activity_count": 5,
  "csv_tables": ["DE_Entry", "DE_Master"],
  "table_levels": {"DE_Master": "contact", "DE_Config": "scenario"},
  "branches": {
    "SPLIT-1/path_a": {"status": "covered"},
    "SPLIT-1/remainder_path": {"status": "not covered", "reason_contains": "unreachable"}
  },
  "scenario_count": {"min": 1, "max": 2},
  "case_count": {"min": 2, "max": 2},
  "contact_count": 6,
  "cases": [
    {"scenario_values": {"DE_Config.CHANNEL": "Email"},
     "contact_values": {"DE_Master.Perm": "True"},
     "end_activity": "EMAIL-1",
     "manual_actions": ["open"],
     "contact_count": 3}
  ],
  "unsupported": ["SOMETHING-1"],
  "warnings_contain": ["Email", "EMAIL"],
  "checks_pass": true,
  "settings": {"real_inbox": "tester@example.com", "case_insensitive_text": false}
}
```

`branches` must list every outcome of every decision, engagement and random split (`"<activity key>/<outcome key>"`).
A listed case must exist (values compared as CSV strings; `end_activity` is the last activity key;
`manual_actions` is the ordered list of kinds). `tests/test_examples.py` runs every example through the
pipeline and compares. The pilot is `examples/pilot/` with `"package": "../../fixtures/CJ template complesso-v1.json"`.
