"""Write the generated files: one CSV per table, scenarios.csv, report.md, testbook.xlsx and the zip.

Spec, "Data generation rules", file format: "UTF-8, comma-separated, header row with the exact field
names in schema order, True/False for Booleans, empty cell for null."

Spec, "Outputs": "The app returns one zip file with the data CSVs plus three supporting files":
``<TableName>.csv`` (one per selected table), ``scenarios.csv``, ``testbook.xlsx`` and ``report.md``.

Every function here is pure: the same input gives the same bytes ("The output is reproducible").
For that reason the timestamps that Excel files and zip archives normally carry are fixed.
"""

from __future__ import annotations

import csv
import dataclasses
import io
import math
import re
import zipfile
from datetime import datetime, timezone
from typing import Iterable, Optional

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill

from .datagen import (
    SCENARIO_COLUMNS,
    UNDELIVERABLE_DOMAIN,
    activation_setting,
    boolean_text,
    case_paths,
    wait_precedes_manual_action,
)
from .model import (
    KIND_DECISION,
    KIND_EMAIL,
    KIND_ENGAGEMENT,
    KIND_RANDOM,
    KIND_UNSUPPORTED,
    KIND_UPDATE,
    KIND_WAIT_ATTRIBUTE,
    KIND_WAIT_DURATION,
    KIND_WAIT_STO,
    LEVEL_SCENARIO,
    STATUS_COVERED,
    STATUS_MANUAL,
    STATUS_NOT_COVERED,
    Activity,
    BranchStatus,
    Case,
    EqualityFilter,
    FieldRef,
    GenerationResult,
    Journey,
    Outcome,
    Package,
    Scenario,
    Settings,
    Step,
    Table,
    TableData,
    UnsupportedFilter,
    Value,
    Write,
    formula_conditions,
    formula_text,
)

CSV_LINE_END = "\n"
SCENARIOS_FILE = "scenarios.csv"
REPORT_FILE = "report.md"
TESTBOOK_FILE = "testbook.xlsx"

# Spec, "Columns of testbook.xlsx".
TESTBOOK_COLUMNS = ["ID", "Owner system", "Test name", "Description", "Pre conditions",
                    "Detailed steps", "Expected result", "Status", "Note"]
OWNER_SYSTEM = "SFMC"
STATUS_TO_START = "TO START"
TESTBOOK_SHEET = "Testbook"
_TESTBOOK_WIDTHS = [6, 12, 40, 60, 60, 70, 70, 12, 40]

ZIP_DATE_TIME = (1980, 1, 1, 0, 0, 0)    # fixed, so the same files always give the same zip bytes
_CORE_TIMESTAMP = re.compile(r"(<dcterms:(?:created|modified)\b[^>]*>)[^<]*(</dcterms:(?:created|modified)>)")
_CURRENT_TIME_VALUE = "{{DateTime.Now}}"
_REPORT_DETAIL_LIMIT = 50
SUSPICIOUS_PREFIX = "suspicious pattern:"   # how other modules mark a suspicious pattern


def table_file_name(table_name: str) -> str:
    """Spec, "Outputs": one ``<TableName>.csv`` per selected table."""
    return f"{table_name}.csv"


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def schema_field_names(table: Table) -> list[str]:
    """The exact field names in schema order."""
    return [f.name for f in sorted(table.fields, key=lambda f: f.ordinal)]


def _csv_bytes(header: list[str], rows: Iterable[list[Value]]) -> bytes:
    """UTF-8 without byte order mark, comma separated, minimal quoting, "\\n" line ends, None -> empty cell."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator=CSV_LINE_END)
    writer.writerow(header)
    for values in rows:
        writer.writerow(["" if value is None else value for value in values])
    return buffer.getvalue().encode("utf-8")


def _row_value(row: dict[str, Value], column: str) -> Value:
    if column in row:
        return row[column]
    low = column.lower()
    for key, value in row.items():
        if key.lower() == low:
            return value
    return None


def write_table_csv(data: TableData, table: Table) -> bytes:
    """One data CSV: the header is the table's schema, in schema order, whatever the rows hold."""
    header = schema_field_names(table)
    return _csv_bytes(header, ([_row_value(row, column) for column in header] for row in data.rows))


def write_scenarios_csv(rows: list[dict[str, Value]]) -> bytes:
    """scenarios.csv: one row per scenario; the columns are those of the rows, in first-seen order."""
    header: list[str] = []
    for row in rows:
        header.extend(column for column in row if column not in header)
    if not header:
        header = list(SCENARIO_COLUMNS)
    return _csv_bytes(header, ([row.get(column) for column in header] for row in rows))


def read_csv(data: bytes) -> tuple[list[str], list[dict[str, Value]]]:
    """Read a CSV written here back: (header, rows). An empty cell reads as None.

    Strict UTF-8, so a byte order mark would show up in the first column name. Blank lines are
    skipped, cells beyond the header are dropped and missing cells read as None.
    """
    reader = csv.reader(io.StringIO(data.decode("utf-8"), newline=""))
    lines = list(reader)
    if not lines:
        return [], []
    header = lines[0]
    rows = [{column: (line[i] if i < len(line) and line[i] != "" else None) for i, column in enumerate(header)}
            for line in lines[1:] if line]
    return header, rows


# ---------------------------------------------------------------------------
# Zip
# ---------------------------------------------------------------------------

def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=ZIP_DATE_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    return info


def build_zip(files: dict[str, bytes]) -> bytes:
    """Spec, "Outputs": "one zip file with the data CSVs plus three supporting files". Files keep the
    given order; every entry has the same fixed timestamp."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(_zip_info(name), content)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Shared wording helpers
# ---------------------------------------------------------------------------

_NAME_LIMIT = 90         # a test name stays within this length (spec example: "S07-C02 - Email sent on channel 1, ...")
_LABEL_LIMIT = 24        # an outcome label longer than this is shortened inside a test name
_FORMULA_LIMIT = 120     # a condition longer than this is not quoted in a reason
_PLAIN_FIRST_WORD = re.compile(r"[a-z]+(?=[\s,:;]|$)")

# Activity kinds in words, for the expected result.
_KIND_WORDS = {
    KIND_DECISION: "decision split",
    KIND_ENGAGEMENT: "engagement split",
    KIND_RANDOM: "random split",
    KIND_WAIT_DURATION: "wait",
    KIND_WAIT_ATTRIBUTE: "wait",
    KIND_WAIT_STO: "send-time wait",
    KIND_EMAIL: "email",
    KIND_UPDATE: "update contact step",
}


def _show(value: Value) -> str:
    return "(empty)" if value is None or value == "" else str(value)


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _verb(count: int) -> str:
    return "is" if count == 1 else "are"


def _join_words(items: Iterable[str]) -> str:
    """'a', 'a and b', 'a, b and c'."""
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _sentence(text: str) -> str:
    """A message as a sentence: a plain first word gets a capital letter and the text ends with a full
    stop. A name or key at the start is left as it is."""
    text = str(text).strip()
    if not text:
        return text
    if _PLAIN_FIRST_WORD.match(text):
        text = text[0].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else text + "."


def _table_of(package: Package, table_name: str) -> Optional[Table]:
    return next((t for t in package.tables.values() if t.name.lower() == table_name.lower()), None)


def _field_type(package: Package, table_name: str, field_name: str) -> str:
    table = _table_of(package, table_name)
    field = table.field(field_name) if table is not None else None
    return field.type.lower() if field is not None and field.type else ""


def _show_value(package: Package, table_name: str, field_name: str, value: Value) -> str:
    """A value as the CSV holds it: Booleans as True/False."""
    if _field_type(package, table_name, field_name) == "boolean":
        value = boolean_text(value) or value
    return _show(value)


def _ordered_refs(package: Package, refs: Iterable[FieldRef]) -> list[FieldRef]:
    """Fields grouped by table, tables in first-seen order, fields in schema order: the CSV column order."""
    refs = list(refs)
    tables: list[str] = []
    for table, _ in refs:
        if table.lower() not in tables:
            tables.append(table.lower())

    def position(ref: FieldRef) -> tuple[int, int]:
        table = _table_of(package, ref[0])
        field = table.field(ref[1]) if table is not None else None
        return tables.index(ref[0].lower()), (field.ordinal if field is not None else 10 ** 6)

    return sorted(refs, key=position)


def _values_parts(package: Package, values: dict, order: list) -> tuple[Optional[str], list[str]]:
    """``Field = value`` items in CSV column order. When the fields are several and all in one table,
    that table is returned and named once by the caller; otherwise each item reads ``Table.Field = value``."""
    refs = [ref for ref in order if ref in values] + [ref for ref in values if ref not in order]
    refs = _ordered_refs(package, refs)
    one_table = refs[0][0] if len(refs) > 1 and len({table.lower() for table, _ in refs}) == 1 else None
    items = []
    for table, field in refs:
        name = field if one_table else f"{table}.{field}"
        items.append(f"{name} = {_show_value(package, table, field, values[(table, field)])}")
    return one_table, items


def _duration_text(amount, unit: Optional[str]) -> str:
    unit_text = (unit or "").lower()
    if amount == 1 and unit_text.endswith("s"):
        unit_text = unit_text[:-1]
    return f"{amount if amount is not None else '?'} {unit_text}".strip()


def _date(moment: datetime, settings: Settings) -> str:
    return moment.strftime(settings.date_format)


def _human_date_format(date_format: str) -> str:
    """``%Y-%m-%d %H:%M`` as the spec writes it: ``YYYY-MM-DD HH:MM``. Other formats are shown as they are."""
    text = date_format
    for code, shown in (("%Y", "YYYY"), ("%m", "MM"), ("%d", "DD"), ("%H", "HH"), ("%M", "MM"), ("%S", "SS")):
        text = text.replace(code, shown)
    return date_format if "%" in text else text


def _activity_name(journey: Journey, key: Optional[str]) -> str:
    """An activity by its name, or its key when it has none."""
    if key is None:
        return "(none)"
    activity = journey.activities.get(key)
    return activity.name if activity is not None and activity.name else key


def _activity_label(journey: Journey, key: Optional[str]) -> str:
    """``Name (KEY)``, or the key alone when the activity has no name."""
    name = _activity_name(journey, key)
    return name if name == key else f"{name} ({key})"


def _quoted_label(journey: Journey, key: Optional[str]) -> str:
    """An activity named inside a sentence: ``'Name' (KEY)``, or the key alone when it has no name."""
    name = _activity_name(journey, key)
    return name if name == key else f"'{name}' ({key})"


def _step_text(journey: Journey, step: Step) -> str:
    """An activity of the path; for an activity with several outcomes, the outcome taken."""
    text = _activity_name(journey, step.activity_key)
    activity = journey.activities.get(step.activity_key)
    if activity is not None and len(activity.outcomes) > 1 and step.outcome_key is not None:
        outcome = activity.outcome(step.outcome_key)
        text += f" [{outcome.label if outcome is not None and outcome.label else step.outcome_key}]"
    return text


def _path_text(journey: Journey, steps: Iterable[Step]) -> str:
    texts = [_step_text(journey, step) for step in steps]
    return " > ".join(texts) if texts else "(no activity)"


def _times(count: int) -> str:
    return "once" if count == 1 else f"{count} times"


def _emails_text(journey: Journey, keys: Iterable[str]) -> str:
    """The emails received, by name, with a count when one is received more than once: "Demo Sky, 2 times"."""
    counts: dict[str, int] = {}
    for key in keys:
        activity = journey.activities.get(key)
        name = (activity.email_name or activity.name or key) if activity is not None else key
        counts[name] = counts.get(name, 0) + 1
    if not counts:
        return "none"
    if len(counts) == 1:
        name, count = next(iter(counts.items()))
        return name if count == 1 else f"{name}, {count} times"
    return _join_words(f"{name} {_times(count)}" for name, count in counts.items())


def _current_time_fields(journey: Journey, keys: Iterable[str]) -> set[tuple[str, str]]:
    """Fields that an update contact step among these activities sets to ``{{DateTime.Now}}``."""
    fields: set[tuple[str, str]] = set()
    for key in keys:
        activity = journey.activities.get(key)
        for write in (activity.writes if activity is not None else []):
            if write.value == _CURRENT_TIME_VALUE:
                fields.add((write.table.lower(), write.field.lower()))
    return fields


def _writes_text(writes: Iterable[Write], current_time: set[tuple[str, str]] = frozenset(), now_text: str = "") -> str:
    """The final value of each field written by the journey, grouped by table in the order first written.
    A field set to ``{{DateTime.Now}}`` gets the time its step runs, not the generation time."""
    final: dict[tuple[str, str], Value] = {}
    for write in writes:
        final[(write.table, write.field)] = write.value
    groups: dict[str, list[str]] = {}
    for (table, field), value in final.items():
        if value == _CURRENT_TIME_VALUE or (now_text and value == now_text
                                            and (table.lower(), field.lower()) in current_time):
            shown = "the date and time when the step runs"
        else:
            shown = _show(value)
        groups.setdefault(table, []).append(f"{field} = {shown}")
    parts = [f"{table}.{items[0]}" if len(items) == 1 else f"{table}: {', '.join(items)}"
             for table, items in groups.items()]
    return "; ".join(parts) if parts else "none"


def _ordered_scenarios(result: GenerationResult) -> list[Scenario]:
    return sorted(result.coverage.scenarios, key=lambda s: (s.run_order, s.id))


def _key_range(keys: list[str]) -> str:
    if not keys:
        return "none"
    if len(keys) <= 3:
        return ", ".join(keys)
    return f"{keys[0]} to {keys[-1]}"


def _smallest_branch(case: Case):
    branches = case.random.branches if case.random is not None else []
    return min(branches, key=lambda b: b.percentage) if branches else None


def _outcome_label(journey: Journey, activity_key: str, outcome_key: str) -> str:
    activity = journey.activities.get(activity_key)
    outcome = activity.outcome(outcome_key) if activity is not None else None
    return outcome.label if outcome is not None and outcome.label else outcome_key


def _branch_label(journey: Journey, random_key: str, branch) -> str:
    """A random split branch by its label, with its percentage when the label does not show it."""
    label = _outcome_label(journey, random_key, branch.outcome_key)
    return label if f"{branch.percentage}%" in label else f"{label} ({branch.percentage}%)"


def _range_chance(contacts: int, percentage: Optional[int], low: int, high: int) -> Optional[int]:
    """In how many runs out of 100 the smallest side of a random split gets low to high contacts, when each
    contact takes it with the split's percentage (spec: 1 to 9 of 50 on the 10% side, "about 97% of runs")."""
    if contacts <= 0 or not percentage or not 0 < percentage < 100 or high < low:
        return None
    p = percentage / 100
    chance = sum(math.comb(contacts, k) * p ** k * (1 - p) ** (contacts - k)
                 for k in range(max(low, 0), min(high, contacts) + 1))
    return round(chance * 100)


def _path_keys(case: Case) -> list[str]:
    """Every activity a case can cross, in path order: the deterministic part, then the random branches."""
    keys: list[str] = []
    for path in case_paths(case):
        for key in path:
            if key not in keys:
                keys.append(key)
    return keys


def _end_sentence(journey: Journey, last: Optional[Step]) -> str:
    """The end of a path in words, when the last activity leads out of the journey."""
    activity = journey.activities.get(last.activity_key) if last is not None else None
    if activity is None or activity.kind == KIND_UNSUPPORTED:
        return ""
    if last.outcome_key is not None:
        outcome = activity.outcome(last.outcome_key)
    else:
        outcome = activity.outcomes[0] if len(activity.outcomes) == 1 else None
    if outcome is None or outcome.next is not None:
        return ""
    if len(activity.outcomes) > 1:
        return f"The contacts leave the journey there, on its {outcome.label or outcome.key} path."
    return f"The contacts leave the journey after this {_KIND_WORDS.get(activity.kind, 'activity')}."


# ---------------------------------------------------------------------------
# Test names: a short summary of what makes a case different
# ---------------------------------------------------------------------------

def _short_label(activity: Activity, outcome: Outcome) -> str:
    """An outcome label short enough for a test name. In a two-way split whose condition has a long
    label, the outcomes read "yes" and "no"; any other long label is cut at a word."""
    conditions = [o for o in activity.outcomes if not o.is_remainder]
    remainders = [o for o in activity.outcomes if o.is_remainder]
    if (len(conditions) == 1 and len(remainders) == 1
            and len(conditions[0].label or conditions[0].key) > _LABEL_LIMIT):
        return "yes" if outcome is conditions[0] else "no"
    label = outcome.label or outcome.key
    if len(label) > _LABEL_LIMIT:
        return label[:_LABEL_LIMIT - 3].rsplit(" ", 1)[0] + "..."
    return label


def _name_part(journey: Journey, contact_fields: set[tuple[str, str]], step: Step) -> Optional[tuple[str, int]]:
    """One part of a test name, from a decision or engagement outcome, with its weight: when a name is too
    long, the parts of lowest weight go first. Engagement outcomes and splits on contact fields are what
    make cases of one scenario differ (3); then splits with several values (2); then yes/no switches (1)."""
    activity = journey.activities.get(step.activity_key)
    outcome = activity.outcome(step.outcome_key) if activity is not None and step.outcome_key else None
    if outcome is None:
        return None
    if activity.kind == KIND_ENGAGEMENT:
        if activity.engagement_kind in ("open", "click") and outcome.when is not None:
            email = journey.activities.get(activity.engagement_ref or "")
            name = (email.email_name or email.name) if email is not None else (activity.name or activity.key)
            verb = "opened" if activity.engagement_kind == "open" else "clicked"
            return (f"{name} {verb}" if outcome.when else f"{name} not {verb}"), 3
        return f"{activity.name or activity.key}: {outcome.label or outcome.key}", 3
    if activity.kind != KIND_DECISION:
        return None
    text = f"{activity.name or activity.key}: {_short_label(activity, outcome)}"
    if any((c.table.lower(), c.field.lower()) in contact_fields
           for o in activity.outcomes for c in formula_conditions(o.formula)):
        return text, 3
    return text, (2 if len(activity.outcomes) > 2 else 1)


def _name_parts(journey: Journey, contact_fields: set[tuple[str, str]], case: Case) -> list[tuple[str, int]]:
    parts: dict[str, int] = {}
    for step in case.steps:
        part = _name_part(journey, contact_fields, step)
        if part is not None and part[0] not in parts:
            parts[part[0]] = part[1]
    items = list(parts.items())
    if case.random is not None and case.random.branches:
        items.append(("random split " + "/".join(str(b.percentage) for b in case.random.branches), 4))
    return items


def _name_counts(journey: Journey, contact_fields: set[tuple[str, str]], cases: Iterable[Case]) -> dict[str, int]:
    """How many cases use each part of a test name: a part shared by many cases says little."""
    counts: dict[str, int] = {}
    for case in cases:
        for text, _ in _name_parts(journey, contact_fields, case):
            counts[text] = counts.get(text, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Testbook
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class _TestbookContext:
    result: GenerationResult
    journey: Journey
    settings: Settings
    csv_names: list[str]
    one_active: bool
    activation_ref: Optional[tuple[str, str]]
    first_scenario: Optional[Scenario]
    emails: dict[str, str]           # contact key -> address
    contact_fields: set = dataclasses.field(default_factory=set)    # (table, field) in lower case
    name_counts: dict = dataclasses.field(default_factory=dict)     # test-name part -> number of cases


def _testbook_context(result: GenerationResult) -> _TestbookContext:
    on, ref, _ = activation_setting(result.package, result.table_model, result.settings)
    scenarios = _ordered_scenarios(result)
    journey = result.package.journey
    contact_fields = {(table.lower(), field.lower()) for table, field in result.coverage.contact_fields}
    return _TestbookContext(
        result=result,
        journey=journey,
        settings=result.settings,
        csv_names=[table_file_name(name) for name in result.data.tables],
        one_active=on,
        activation_ref=ref,
        first_scenario=scenarios[0] if scenarios else None,
        emails={contact.key: contact.email for contact in result.data.contacts},
        contact_fields=contact_fields,
        name_counts=_name_counts(journey, contact_fields, result.coverage.cases),
    )


def build_testbook_rows(result: GenerationResult) -> list[list]:
    """Spec, "Columns of testbook.xlsx": one row per case, scenarios in run order."""
    context = _testbook_context(result)
    rows: list[list] = []
    for scenario in _ordered_scenarios(result):
        for case in scenario.cases:
            rows.append([
                len(rows) + 1,
                OWNER_SYSTEM,
                _test_name(context, case),
                _description(context, scenario, case),
                _preconditions(context, scenario, case),
                _detailed_steps(context, scenario, case),
                _expected_result(context, case),
                STATUS_TO_START,
                _note(context, scenario, case),
            ])
    return rows


def _case_summary(context: _TestbookContext, case: Case) -> str:
    """Spec: "a short summary of the path", for example "Email sent on channel 1, no phone consent".

    A short summary given with the case is kept. A summary that lists every split ("a: b > c: d > ...")
    is rebuilt from the decision and engagement outcomes of the path: when they do not fit, the parts
    that tell least about this case are dropped first (lowest weight, then the part most cases share)."""
    given = (case.summary or "").strip()
    if not given:
        return f"Path ending at {_activity_name(context.journey, case.end_activity_key)}"
    room = _NAME_LIMIT - len(case.id) - len(" - ")
    if " > " not in given and len(given) <= room:
        return given
    parts = _name_parts(context.journey, context.contact_fields, case)
    while len(parts) > 1 and len(", ".join(text for text, _ in parts)) > room:
        drop = min(range(len(parts)), key=lambda i: (parts[i][1], -context.name_counts.get(parts[i][0], 0), i))
        parts.pop(drop)
    text = ", ".join(t for t, _ in parts) if parts else given
    return text if len(text) <= room else text[:room - 3].rstrip() + "..."


def _test_name(context: _TestbookContext, case: Case) -> str:
    """Spec: "Case identifier and a short summary of the path"."""
    return f"{case.id} - {_case_summary(context, case)}"


def _description(context: _TestbookContext, scenario: Scenario, case: Case) -> str:
    """Spec: "Scenario values, contact profile values, and the expected path as activity names in order"."""
    coverage = context.result.coverage
    package = context.result.package
    table, items = _values_parts(package, scenario.values, coverage.scenario_fields)
    if not items:
        scenario_line = f"Scenario {scenario.key}: no scenario-level value."
    elif table:
        scenario_line = f"Scenario {scenario.key}, values in {table}: {'; '.join(items)}."
    else:
        scenario_line = f"Scenario {scenario.key}: {'; '.join(items)}."
    table, items = _values_parts(package, case.contact_values, coverage.contact_fields)
    if not items:
        contact_line = "Contact profile: no contact-level value."
    elif table:
        contact_line = f"Contact profile in {table}: {'; '.join(items)}."
    else:
        contact_line = f"Contact profile: {'; '.join(items)}."
    lines = [scenario_line, contact_line, f"Expected path: {_path_text(context.journey, case.steps)}."]
    if case.random is not None:
        random_key = case.random.activity_key
        lines.append(f"At the random split {_activity_label(context.journey, random_key)}, each contact takes "
                     "one branch.")
        for branch in case.random.branches:
            path = _path_text(context.journey, branch.steps) if branch.steps else "the contact leaves the journey"
            lines.append(f"Branch {_branch_label(context.journey, random_key, branch)}: {path}.")
    return "\n".join(lines)


def _scenario_key_column(context: _TestbookContext, table_name: str) -> Optional[str]:
    """The field of a table that holds the scenario key."""
    for group in context.result.table_model.key_groups:
        if group.kind != "scenario":
            continue
        for table, field in group.fields:
            if table.lower() == table_name.lower():
                return field
    return None


def _activation_text(context: _TestbookContext, scenario: Scenario) -> str:
    """Spec: "When on, only the first scenario is active in the CSV, and the testbook tells the tester
    which row to switch before each run"; "To move to the next scenario, the tester edits only its
    activation field"."""
    table, field = context.activation_ref
    key_column = _scenario_key_column(context, table)
    row_text = f"the row with {key_column} {scenario.key}" if key_column else f"the row of scenario {scenario.key}"
    if scenario is context.first_scenario:
        return (f"Check that scenario {scenario.key} is the active one: in {table}, {field} is True on {row_text} "
                "and False on every other row, as generated.")
    return (f"When the contacts of the previous scenario have left the journey, activate scenario {scenario.key}: "
            f"in {table}, set {field} to True on {row_text} and to False on every other row. Change nothing else.")


def _entry_procedures(result: GenerationResult) -> Optional[str]:
    """The automation that fills the entry table, when the entry can also be run through it."""
    entry = result.package.entry_event
    automation = entry.automation_name if entry is not None else None
    return automation if automation and result.table_model.entry_query is not None else None


def _preconditions(context: _TestbookContext, scenario: Scenario, case: Case) -> str:
    """Spec: "Which CSVs must be imported, which scenario must be active, and the keys of the test
    contacts"; "The 50 contacts of a random split case are given as a key range"."""
    entry_csv = table_file_name(context.result.table_model.entry_table)
    first = f"Import these CSV files: {', '.join(context.csv_names)}."
    if len(context.csv_names) > 1 and entry_csv in context.csv_names:
        if _entry_procedures(context.result):
            first += (f" Import {entry_csv} last, or leave it out if you run the entry through the automation: "
                      "see How to run in report.md.")
        else:
            first += f" Import {entry_csv} last."
    lines = [first]
    if context.one_active:
        table, field = context.activation_ref
        lines.append(f"Active scenario: {scenario.key}. In {table}, {field} is True on its row only.")
    else:
        lines.append(f"Scenario: {scenario.key}. Every scenario is active at the same time.")
    keys = case.contact_keys
    if case.random is not None and len(keys) > 3:
        lines.append(f"Test contacts ({len(keys)}): {keys[0]} to {keys[-1]}.")
    else:
        lines.append(f"Test contacts ({len(keys)}): {', '.join(keys) if keys else 'none'}.")
    return "\n".join(lines)


def _wait_descriptions(context: _TestbookContext, scenario: Scenario, case: Case) -> list[str]:
    """Spec: "Wait by duration, send-time wait: The expected delay is noted in the testbook"."""
    texts = []
    for key in _path_keys(case):
        activity = context.journey.activities.get(key)
        if activity is None:
            continue
        name = _activity_name(context.journey, activity.key)
        if activity.kind == KIND_WAIT_DURATION:
            duration = _duration_text(activity.wait_amount, activity.wait_unit)
            texts.append(name if name.lower() == duration.lower() else f"{name} ({duration})")
        elif activity.kind == KIND_WAIT_STO:
            if activity.wait_amount:
                texts.append(f"{name}, a send-time wait of up to "
                             f"{_duration_text(activity.wait_amount, activity.wait_unit)}")
            else:
                texts.append(f"{name}, a send-time wait whose delay is not known in advance")
        elif activity.kind == KIND_WAIT_ATTRIBUTE and activity.wait_field is not None:
            table, field = activity.wait_field
            value = _written_value(context, table, field, scenario, case)
            until = f"until {value}, the date in {table}.{field}" if value else f"until the date in {table}.{field}"
            texts.append(f"{name}, {until}")
    return texts


def _written_value(context: _TestbookContext, table_name: str, field_name: str,
                   scenario: Scenario, case: Case) -> Value:
    """The value written in the CSV for this scenario's or this case's row of a table."""
    data = next((d for name, d in context.result.data.tables.items() if name.lower() == table_name.lower()), None)
    if data is None or not data.rows:
        return None
    role = next((r for r in context.result.table_model.tables.values() if r.name.lower() == table_name.lower()), None)
    kind = "scenario" if role is not None and role.level == LEVEL_SCENARIO else "contact"
    owner = scenario.key if kind == "scenario" else (case.contact_keys[0] if case.contact_keys else None)
    key_columns = [field for group in context.result.table_model.key_groups if group.kind == kind
                   for table, field in group.fields if table.lower() == table_name.lower()]
    for row in data.rows:
        if any(_row_value(row, column) == owner for column in key_columns):
            return _row_value(row, field_name)
    return None


def _deadline_wait(context: _TestbookContext, scenario: Scenario, case: Case,
                   action) -> tuple[Optional[Activity], Optional[str]]:
    """The last wait by attribute between the email and the engagement split, and its date."""
    for keys in case_paths(case):
        if action.activity_key not in keys:
            continue
        end = keys.index(action.activity_key)
        start = keys.index(action.email_activity_key) if action.email_activity_key in keys[:end] else -1
        for key in reversed(keys[start + 1:end]):
            activity = context.journey.activities.get(key)
            if (activity is not None and activity.kind == KIND_WAIT_ATTRIBUTE and activity.wait_field is not None
                    and wait_precedes_manual_action(key, case)):
                return activity, _written_value(context, activity.wait_field[0], activity.wait_field[1], scenario, case)
    return None, None


def _deadline(context: _TestbookContext, scenario: Scenario, case: Case, action) -> Optional[str]:
    """Spec: "the testbook gives the deadline as a date and time". The deadline is the date of the last
    wait by attribute between the email and the engagement split: when it passes, the split is evaluated."""
    return _deadline_wait(context, scenario, case, action)[1]


def _manual_steps(context: _TestbookContext, scenario: Scenario, case: Case) -> list[str]:
    """Spec: "any manual action with its deadline"; "Contacts that must open or click get the tester's
    real inbox with plus-addressing"."""
    steps = []
    inbox = context.settings.real_inbox.strip()
    addresses = _join_words(context.emails.get(key, key) for key in case.contact_keys)
    for action in case.manual_actions:
        verb = "open the email" if action.kind == "open" else "click a link in the email"
        split = _quoted_label(context.journey, action.activity_key)
        if not inbox:
            steps.append(f"The split {split} needs the contacts to {verb} '{action.email_name}', but no real inbox "
                         "was set, so the emails cannot be received. This test cannot reach its expected result until "
                         "the data is generated again with a real inbox.")
            continue
        wait, deadline = _deadline_wait(context, scenario, case, action)
        when = f"Before {deadline}" if deadline else "As soon as the email arrives"
        text = f"{when}, {verb} '{action.email_name}' sent to each contact of this test: {addresses}."
        if deadline and wait is not None:
            text += (f" At that time the wait {_quoted_label(context.journey, wait.key)} ends, and the contacts go "
                     f"on towards the split {split}.")
        steps.append(text + f" The emails arrive in the inbox {inbox}. Do not open or click the emails of other tests.")
    return steps


def _detailed_steps(context: _TestbookContext, scenario: Scenario, case: Case) -> str:
    """Spec: "Numbered steps: activate the scenario, start the entry, wait (with expected delays), any
    manual action with its deadline, collect evidence"."""
    steps = []
    if context.one_active:
        steps.append(_activation_text(context, scenario))
    else:
        steps.append(f"Check that the rows of scenario {scenario.key} are imported.")
    entry_csv = table_file_name(context.result.table_model.entry_table)
    automation = _entry_procedures(context.result)
    if automation:
        steps.append(f"Start the entry of scenario {scenario.key} with the procedure chosen in report.md, How to run: "
                     f"the direct import of {entry_csv}, or one run of the automation {automation}. "
                     "All the tests of this scenario start together.")
    else:
        steps.append(f"Start the entry of journey {context.journey.name} from the imported rows of {entry_csv}. "
                     "All the tests of this scenario start together.")
    waits = _wait_descriptions(context, scenario, case)
    steps.append("Wait for the contacts to pass the waits on their path: " + "; ".join(waits) + "." if waits else
                 "There is no wait on the path.")
    steps.extend(_manual_steps(context, scenario, case))
    steps.append("Collect the evidence for each contact: the emails received, the values written by the journey "
                 "and the last activity reached.")
    return "\n".join(f"{number}. {text}" for number, text in enumerate(steps, 1))


def _expected_result(context: _TestbookContext, case: Case) -> str:
    """Spec: "For each contact: the emails or messages received, the values written by the journey, and
    the last activity reached". The contacts of a case share one expected result."""
    journey = context.journey
    keys = case.contact_keys
    now_text = _date(context.result.generation_time, context.settings)
    base_keys = [step.activity_key for step in case.steps]
    if case.random is None:
        last = f"- Last activity reached: {_activity_label(journey, case.end_activity_key)}."
        end = _end_sentence(journey, case.steps[-1] if case.steps else None)
        return "\n".join([
            f"For each of these contacts: {_join_words(keys) if keys else 'none'}.",
            f"- Emails received: {_emails_text(journey, case.emails_sent)}.",
            f"- Values written by the journey: "
            f"{_writes_text(case.writes, _current_time_fields(journey, base_keys), now_text)}.",
            f"{last} {end}" if end else last,
        ])
    random_key = case.random.activity_key
    lines = [
        f"For each of the {len(keys)} contacts {_key_range(keys)}, up to the random split "
        f"{_activity_label(journey, random_key)}:",
        f"- Emails received: {_emails_text(journey, case.emails_sent)}.",
        f"- Values written by the journey: "
        f"{_writes_text(case.writes, _current_time_fields(journey, base_keys), now_text)}.",
        "Then each contact takes one branch of the random split:",
    ]
    for branch in case.random.branches:
        branch_keys = base_keys + [step.activity_key for step in branch.steps]
        lines.append(f"- {_branch_label(journey, random_key, branch)}: emails received: "
                     f"{_emails_text(journey, branch.emails_sent)}; "
                     f"values written: {_writes_text(branch.writes, _current_time_fields(journey, branch_keys), now_text)}; "
                     f"last activity reached: {_activity_label(journey, branch.end_activity_key)}.")
    smallest = _smallest_branch(case)
    if smallest is not None:
        lines.append(f"Accepted range: {case.random.expected_low} to {case.random.expected_high} contacts on the "
                     f"{_branch_label(journey, random_key, smallest)} side.")
    return "\n".join(lines)


def _note(context: _TestbookContext, scenario: Scenario, case: Case) -> str:
    """Spec: "Manual engagement required, or the accepted range for a random split case"."""
    notes = []
    for action in case.manual_actions:
        verb = "open" if action.kind == "open" else "click"
        if not context.settings.real_inbox.strip():
            notes.append(f"Manual engagement required: {verb} the email '{action.email_name}'. No real inbox was "
                         "given, so this test cannot reach its expected result.")
            continue
        wait, deadline = _deadline_wait(context, scenario, case, action)
        text = f"Manual engagement required: {verb} the email '{action.email_name}'"
        notes.append(text + (f" before {deadline}." if deadline else " as soon as it arrives."))
        if deadline:
            notes.append("If that time has passed before the email arrives, generate the data again.")
        zone = wait.wait_timezone if deadline and wait is not None else None
        if zone:
            notes.append(f"The wait {_quoted_label(context.journey, wait.key)} is set to {zone}. How Salesforce "
                         "applies this time zone to the date is an assumption to verify, so the deadline could shift "
                         "by some hours.")
    if case.random is not None:
        smallest = _smallest_branch(case)
        label = _branch_label(context.journey, case.random.activity_key, smallest) if smallest else "smaller"
        contacts = len(case.contact_keys)
        notes.append(f"Random split: the contacts cannot be forced down one branch. Between {case.random.expected_low} "
                     f"and {case.random.expected_high} of the {contacts} contacts are expected on the "
                     f"{label} side.")
        chance = _range_chance(contacts, smallest.percentage if smallest else None,
                               case.random.expected_low, case.random.expected_high)
        if chance is not None:
            notes.append(f"With a {smallest.percentage}% chance for each contact, this range holds in about "
                         f"{chance}% of runs.")
    return " ".join(notes)


def _excel_text(value):
    if isinstance(value, str):
        return ILLEGAL_CHARACTERS_RE.sub("", value)
    return value


def _utc_text(moment: datetime) -> str:
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _stable_xlsx(content: bytes, moment: datetime) -> bytes:
    """openpyxl stamps the save time into docProps/core.xml and the zip entries: replace both, so the
    same input always gives the same bytes."""
    stamp = _utc_text(moment)
    source = zipfile.ZipFile(io.BytesIO(content))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == "docProps/core.xml":
                text = _CORE_TIMESTAMP.sub(lambda m: m.group(1) + stamp + m.group(2), data.decode("utf-8"))
                data = text.encode("utf-8")
            archive.writestr(_zip_info(info.filename), data)
    return buffer.getvalue()


def write_testbook(result: GenerationResult) -> bytes:
    """Spec, "Outputs": "testbook.xlsx: One test per case with the expected result, in the team's
    testbook layout"; "The testbook has one row per case, not per contact"."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = TESTBOOK_SHEET
    sheet.append(TESTBOOK_COLUMNS)
    for row in build_testbook_rows(result):
        sheet.append([_excel_text(value) for value in row])
    header_fill = PatternFill("solid", fgColor="1F3864")
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for position, width in enumerate(_TESTBOOK_WIDTHS, 1):
        sheet.column_dimensions[sheet.cell(1, position).column_letter].width = width
    sheet.freeze_panes = "A2"
    workbook.properties.creator = "CJ Test Helper"
    buffer = io.BytesIO()
    workbook.save(buffer)
    return _stable_xlsx(buffer.getvalue(), result.generation_time)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _md_cell(value) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _md_table(header: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(_md_cell(h) for h in header) + " |",
             "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(_md_cell(value) for value in row) + " |" for row in rows]
    return "\n".join(lines)


def _bullets(items: Iterable[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _numbered(items: Iterable[str]) -> str:
    return "\n".join(f"{number}. {item}" for number, item in enumerate(items, 1))


def _unique(items: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


def _split_suspicious(warnings: Iterable[str]) -> tuple[list[str], list[str]]:
    """Spec, "Outputs": the report "lists suspicious patterns found while parsing, such as the same value
    written in two letter cases". Other modules mark them with the prefix ``suspicious pattern:``."""
    patterns, others = [], []
    for warning in warnings:
        if warning.lower().startswith(SUSPICIOUS_PREFIX):
            pattern = warning[len(SUSPICIOUS_PREFIX):].strip()
            patterns.append(pattern[:1].upper() + pattern[1:])
        else:
            others.append(warning)
    return patterns, others


# Texts written by other modules that the report rewords. A text that no longer matches is shown as it is.
_CASE_PATTERN = re.compile(r"^(?P<table>[^.]+)\.(?P<field>.+?) is compared with (?P<values>.+?)"
                           r"(?:; (?P<tail>.+?))?\.?$")
_SAME_NAME_PATTERN = re.compile(r"^(?P<count>\d+) different conditions share the split name '(?P<name>.*)' "
                                r"\((?P<keys>.*)\)\.?$")
_CONSTANT_KEY_PATTERN = re.compile(r"^(?P<count>\d+) update contact step\(s\) write the constant (?P<value>.+?) "
                                   r"into the primary-key field (?P<table>[^.]+)\.(?P<field>.+?), so every contact "
                                   r"gets the same key value there \((?P<keys>.*)\)\.?$")
_ONE_TO_ONE_PATTERN = re.compile(r"^The one-to-one relationship '(?P<name>.*)' joins (?P<table>.+?) on (?P<fields>.+?), "
                                 r"but its primary key also has (?P<extra>.+?): several rows can match one contact\.?$")
_CASE_TAILS = {
    "they are different values because text comparisons are case-sensitive (setting)":
        "With the current setting, text comparisons are case-sensitive, so these are different values.",
    "treated as the same value because text comparisons ignore letter case":
        "With the current setting, text comparisons ignore letter case, so these count as one value.",
}
_IGNORED_COLUMNS = re.compile(r"^The entry query selects columns that (?P<table>.+?) does not have, so they are "
                              r"ignored: (?P<columns>.+?)\.?$")
_QUOTED = re.compile(r"'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"|\b(null)\b")
_REASON_NEVER_MATCHES = re.compile(r"^unreachable: the split is reached but '(?P<label>.*)' never matches on those "
                                   r"paths \((?P<detail>.*)\)$")
_REASON_ALWAYS_ONE_OF = re.compile(r"^(?P<field>.+?) is always one of (?P<values>.+)$")
_REASON_FOLLOWS = re.compile(r"^unreachable: no combination of field values reaches this activity "
                             r"\(it follows (?P<keys>.*)\)$")
_REASON_BEHIND_UNSUPPORTED = re.compile(r"^unreachable: lies behind the unsupported activit(?:y|ies) (?P<keys>.+)$")
_REASON_UNSUPPORTED = re.compile(r"^unsupported activity: (?P<detail>.+)$")
_REASON_BEHIND_BRANCH = re.compile(r"^unreachable: lies behind the branch .*?, which is (?P<reason>.+)$")
_REASON_FIXED = {
    "unreachable: the split is reached but an earlier outcome always matches":
        ("unreachable", "an earlier outcome of the split always matches first"),
    "unreachable: the split is reached but this branch is never taken":
        ("unreachable", "no simulated path takes this branch, although the split is reached"),
    "unreachable: no simulated path crosses this branch":
        ("unreachable", "no simulated path crosses it"),
    "unreachable: no path from the start reaches this activity":
        ("unreachable", "no path from the start of the journey reaches the split"),
    "needs an open or click but no real inbox is configured; the cases exist with undeliverable addresses":
        ("not covered", "it needs an open or a click, but no real inbox was given. Its cases exist, with "
                        "undeliverable addresses"),
}


def _quoted_values(text: str) -> list[str]:
    """The values of a list such as ``'DM', 'Email', null``, as they should be shown."""
    shown = []
    for single, double, null in _QUOTED.findall(text):
        shown.append("empty" if null else (f"'{single}'" if single or not double else f'"{double}"'))
    return shown


def _or_values(text: str) -> str:
    """``'DM', 'Email', 'OB'`` as ``'DM', 'Email' or 'OB'``."""
    values = _quoted_values(text)
    if not values:
        return "one of " + text
    return values[0] if len(values) == 1 else ", ".join(values[:-1]) + " or " + values[-1]


def _quoted_labels(journey: Journey, text: str) -> list[str]:
    """Activity keys written as ``'A', 'B'``, by name and key."""
    keys = [single or double for single, double, _ in _QUOTED.findall(text) if single or double]
    return [_activity_label(journey, key) for key in keys] or [text]


def _drop_table(detail: str, condition: str) -> str:
    """``T.F is always ...`` as ``F is always ...`` when the quoted condition already names ``T.F``."""
    field = detail.split(" is always ", 1)[0]
    if "." in field and field in condition:
        return field.split(".", 1)[1] + detail[len(field):]
    return detail


def _natural_key(text: str) -> list:
    """Sort key that puts MULTICRITERIADECISIONV2-42 before MULTICRITERIADECISIONV2-116."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


def _condition_text(journey: Journey, activity_key: str, outcome_key: str) -> Optional[str]:
    activity = journey.activities.get(activity_key)
    outcome = activity.outcome(outcome_key) if activity is not None else None
    if outcome is None or outcome.formula is None:
        return None
    text = formula_text(outcome.formula)
    return f"`{text}`" if len(text) <= _FORMULA_LIMIT else None


def _explain_reason(reason: str, journey: Journey, activity_key: str,
                    outcome_key: str) -> tuple[Optional[str], str]:
    """A not-covered reason from the coverage module as (state, clause), where state is "unreachable",
    "not covered", or None when the reason is not one the report knows (it is then shown as it is)."""
    reason = (reason or "").strip()
    if reason in _REASON_FIXED:
        return _REASON_FIXED[reason]
    match = _REASON_NEVER_MATCHES.match(reason)
    if match:
        details = []
        for part in match.group("detail").split("; "):
            seen = _REASON_ALWAYS_ONE_OF.match(part)
            if seen:
                details.append(f"{seen.group('field')} is always {_or_values(seen.group('values'))}")
            elif part != "the condition is never true":
                details.append(part)
        condition = _condition_text(journey, activity_key, outcome_key)
        if condition:
            details = [_drop_table(detail, condition) for detail in details]
        head = (f"its condition {condition} never matches" if condition
                else f"'{match.group('label')}' never matches")
        if details:
            return "unreachable", f"{head}: where the split is reached, {_join_words(details)}"
        return "unreachable", f"{head} where the split is reached"
    match = _REASON_FOLLOWS.match(reason)
    if match:
        parents = _join_words(_quoted_labels(journey, match.group("keys")))
        return "unreachable", f"no combination of field values reaches the split, which follows {parents}"
    match = _REASON_BEHIND_UNSUPPORTED.match(reason)
    if match:
        blockers = _join_words(_quoted_labels(journey, match.group("keys")))
        return "unreachable", f"it lies behind the unsupported activity {blockers}"
    match = _REASON_UNSUPPORTED.match(reason)
    if match:
        return "not covered", f"the split itself is not supported: {match.group('detail').rstrip('.')}"
    if reason.startswith("unreachable: "):
        return "unreachable", reason[len("unreachable: "):]
    return None, reason


def _reason_sentence(reason: str, journey: Journey, activity_key: str, outcome_key: str) -> str:
    state, clause = _explain_reason(reason, journey, activity_key, outcome_key)
    if state == "unreachable":
        return _sentence(f"Unreachable because {clause.rstrip('.')}")
    if state == "not covered":
        return _sentence(f"Not covered because {clause.rstrip('.')}")
    return _sentence(reason) if reason else "No reason given."


def _section_title(result: GenerationResult) -> str:
    settings = result.settings
    journey = result.package.journey.name
    intro = "This report says what the test data covers, how to run it, and what it cannot cover."
    if TESTBOOK_FILE in result.files:
        intro += f" The steps and the expected result of each test are in {TESTBOOK_FILE}."
    return "\n\n".join([
        f"# Test data report: {journey}",
        f"Journey {journey}, from the package {result.package.name}. Generated on "
        f"{_date(result.generation_time, settings)} with the run identifier {settings.run_id}.",
        intro,
    ])


def _section_summary(result: GenerationResult) -> str:
    coverage, data = result.coverage, result.data
    cases = coverage.cases
    statuses = [b.status for b in coverage.branches]
    covered = statuses.count(STATUS_COVERED)
    manual = statuses.count(STATUS_MANUAL)
    not_covered = statuses.count(STATUS_NOT_COVERED)
    statistical = sum(1 for b in coverage.branches if b.statistical and b.status != STATUS_NOT_COVERED)
    rows = [
        ["Scenarios", len(coverage.scenarios)],
        ["Statistical scenarios", sum(1 for s in coverage.scenarios if s.is_statistical)],
        ["Cases", len(cases)],
        ["Cases with a manual action", sum(1 for c in cases if c.manual_actions)],
        ["Statistical cases, for a random split", sum(1 for c in cases if c.random is not None)],
        ["Contacts", len(data.contacts)],
        ["Contacts using the real inbox", sum(1 for c in data.contacts if c.uses_real_inbox)],
        ["Branches", len(coverage.branches)],
        ["Branches covered", covered],
        ["Branches covered with manual action", manual],
        ["Branches not covered", not_covered],
        ["Branches covered only through a random split", statistical],
    ]
    text = (f"The test data has {_plural(len(coverage.scenarios), 'scenario', 'scenarios')}, "
            f"{_plural(len(cases), 'case', 'cases')} and {_plural(len(data.contacts), 'contact', 'contacts')}. "
            f"Of {_plural(len(coverage.branches), 'branch', 'branches')}, {covered} {_verb(covered)} covered, "
            f"{manual} {_verb(manual)} covered with a manual action and {not_covered} {_verb(not_covered)} not covered.")
    tables = list(result.table_model.scenario_tables)
    if len(tables) == 1:
        terms = f"A scenario is one row of {tables[0]}, shared by all its contacts."
    elif tables:
        terms = f"A scenario is one row in each of {_join_words(tables)}, shared by all its contacts."
    else:
        terms = "A scenario groups the cases that run together."
    terms += (" A case groups contacts with the same contact values and the same manual actions, so they take the "
              "same path up to any random split.")
    if TESTBOOK_FILE in result.files:
        terms += f" Each case is one test in {TESTBOOK_FILE}."
    return "\n\n".join(["## Summary", text, terms, _md_table(["Item", "Count"], rows)])


def _section_checks(result: GenerationResult) -> str:
    if not result.checks:
        return "## Trust checks\n\nNo trust check was run on these files."
    failed = [check for check in result.checks if not check.passed]
    total = len(result.checks)
    if failed:
        text = f"{total - len(failed)} of the {total} trust checks passed. {len(failed)} failed: the details are below."
    else:
        text = "The trust check passed." if total == 1 else f"All {total} trust checks passed."
    meaning = ("After writing the files, the generator reads them back and checks them. A failed check means that "
               "the files may not do what this report and the testbook say. Do not import them until the failure "
               "is explained.")
    rows = [[check.name, "passed" if check.passed else "FAILED", len(check.details)] for check in result.checks]
    parts = ["## Trust checks", text, meaning, _md_table(["Check", "Result", "Details"], rows)]
    for check in result.checks:
        if not check.details:
            continue
        shown = check.details[:_REPORT_DETAIL_LIMIT]
        lines = [f"### {check.name}", _bullets(_sentence(detail) for detail in shown)]
        if len(check.details) > len(shown):
            lines.append(f"There are {len(check.details) - len(shown)} more.")
        parts.append("\n\n".join(lines))
    return "\n\n".join(parts)


def _section_tables(result: GenerationResult) -> str:
    rows = []
    for role in result.table_model.tables.values():
        data = result.data.tables.get(role.name)
        rows.append([role.name, ", ".join(sorted(role.roles)) or "none", role.level or "-",
                     table_file_name(role.name) if role.selected else "no",
                     len(data.rows) if data is not None else "-", role.reason])
    selected = [table_file_name(name) for name in result.data.tables]
    text = f"{_plural(len(selected), 'table gets', 'tables get')} a CSV: {_join_words(selected) if selected else 'none'}."
    meaning = ("A table gets a CSV when the journey or the entry query reads it. A contact-level table has one row "
               "per contact. A scenario-level table has one row per scenario, shared by its contacts.")
    return "\n\n".join(["## Tables", text, meaning,
                        _md_table(["Table", "Role", "Level", "CSV", "Rows", "Reason"], rows)])


def _activation_is_entry_filter(result: GenerationResult, ref: FieldRef) -> bool:
    """True when the activation field is a filter of the entry query and no split or wait reads it."""
    query = result.table_model.entry_query
    wanted = (ref[0].lower(), ref[1].lower())
    filters = query.filters if query is not None else []
    if not any(isinstance(f, EqualityFilter) and (f.column.table.lower(), f.column.column.lower()) == wanted
               for f in filters):
        return False
    read = {(t.lower(), f.lower()) for t, f in result.coverage.scenario_fields + result.coverage.contact_fields}
    read |= {(a.wait_field[0].lower(), a.wait_field[1].lower()) for a in result.package.journey.activities.values()
             if a.wait_field is not None}
    return wanted not in read


def _how_to_run(result: GenerationResult, context: _TestbookContext) -> str:
    """Spec: "The tester imports the entry CSV directly, together with the CSVs of the linked tables ...
    Importing the sources and running the automation is the alternative. The two ways are not combined";
    "One scenario at a time"; "Data is read live"."""
    model = result.table_model
    entry_csv = table_file_name(model.entry_table)
    others = [name for name in context.csv_names if name != entry_csv]
    automation = _entry_procedures(result)
    runs = "once for each scenario, with only that scenario active" if context.one_active else "once"
    parts = ["### How to run"]
    if automation and others:
        parts.append("Choose one entry procedure before the first run and keep it for every scenario. Do not "
                     "combine them: doing both would duplicate the entry rows.")
        parts.append(_bullets([
            f"Direct import, the normal way in the spec. Import {_join_words(others)} first, then {entry_csv}, so "
            f"that every row a contact needs is in place before it enters. Do not run the automation {automation}.",
            f"Through the automation. Import {_join_words(others)}, but not {entry_csv}. Run the automation "
            f"{automation} {runs}. Its entry query {model.entry_query.name} builds the entry rows from the "
            "imported rows.",
        ]))
        parts.append(f"Assumption to verify before the first run: importing {entry_csv} alone may admit nobody, "
                     f"because the automation {automation} runs the entry of this journey. The direct import may then "
                     "also need a Run Once of that automation with only its journey-entry activity selected. The "
                     "Salesforce review in docs/assumptions.md explains this in rows 23 to 27.")
    elif others:
        parts.append(f"Import {_join_words(others)} first, then {entry_csv}, so that every row a contact needs is in "
                     "place before it enters.")
    else:
        parts.append(f"Import {entry_csv}.")
    if context.one_active and context.first_scenario is not None:
        table, field = context.activation_ref
        key_column = _scenario_key_column(context, table)
        row = f" The row of a scenario is the one whose {key_column} is the scenario key." if key_column else ""
        parts.append("Run one scenario at a time, in run order. Scenarios with a manual action come first, because "
                     f"their deadline is a fixed date and time. To make a scenario the active one, set {field} in "
                     f"{table} to True on the row of the scenario and to False on every other row.{row}")
        parts.append(_numbered([
            f"The CSVs start with {context.first_scenario.key} as the active scenario, so the first run needs no "
            "change.",
            "Wait until the contacts of a scenario have left the journey.",
            "Then make the next scenario the active one. Change nothing else and import nothing again, because the "
            "journey reads these rows while contacts are in it.",
        ]))
        if automation and _activation_is_entry_filter(result, context.activation_ref):
            parts.append(f"{field} is a filter of the entry query, and no split reads it: it holds a scenario back "
                         "only when the automation runs that query.")
    elif result.coverage.scenarios:
        parts.append("Every scenario is active in the CSVs, so the scenarios run together.")
    parts.extend(_contact_address_text(result))
    for case in result.coverage.cases:
        smallest = _smallest_branch(case)
        if case.random is None or smallest is None:
            continue
        journey = result.package.journey
        parts.append(f"The statistical case {case.id} has {len(case.contact_keys)} contacts for the random split "
                     f"{_activity_label(journey, case.random.activity_key)}. Each contact takes a branch at random. "
                     f"The accepted range is {case.random.expected_low} to {case.random.expected_high} contacts on "
                     f"the {_branch_label(journey, case.random.activity_key, smallest)} side.")
    return "\n\n".join(parts)


def _contact_address_text(result: GenerationResult) -> list[str]:
    """Spec, "Email": the real inbox with plus-addressing for contacts that must open or click; an
    undeliverable address for all others."""
    kinds = _unique(action.kind for case in result.coverage.cases for action in case.manual_actions)
    actions = _join_words(kinds).replace(" and ", " or ") if kinds else ""
    inbox = result.settings.real_inbox.strip()
    real = [contact for contact in result.data.contacts if contact.uses_real_inbox]
    undeliverable = f"an undeliverable address ending in @{UNDELIVERABLE_DOMAIN}"
    if kinds and inbox and real:
        return [f"Contacts that must {actions} an email get the real inbox {inbox} with plus-addressing, for "
                f"example {real[0].email}. Every other contact gets {undeliverable}."]
    if kinds:
        return [f"No real inbox was given. The contacts that must {actions} an email get {undeliverable}, so "
                "those branches are not covered."]
    if result.data.contacts:
        return [f"No contact needs to open or click an email, so every contact gets {undeliverable}."]
    return []


def _section_scenarios(result: GenerationResult) -> str:
    journey = result.package.journey
    package = result.package
    context = _testbook_context(result)
    one_table = None
    scenario_rows = []
    for scenario in _ordered_scenarios(result):
        table, items = _values_parts(package, scenario.values, result.coverage.scenario_fields)
        one_table = one_table or table
        keys = [key for case in scenario.cases for key in case.contact_keys]
        active = not context.one_active or scenario is context.first_scenario
        scenario_rows.append([scenario.key, scenario.run_order, "yes" if active else "no",
                              str(bool(scenario.has_manual_action)), str(bool(scenario.is_statistical)),
                              len(scenario.cases), len(keys),
                              f"{keys[0] if keys else '-'} to {keys[-1] if keys else '-'}",
                              "; ".join(items) or "none"])
    list_intro = "The scenarios in run order, as in scenarios.csv."
    if one_table:
        list_intro += f" The values are fields of {one_table}."
    case_rows = []
    for scenario in _ordered_scenarios(result):
        for case in scenario.cases:
            if case.random is not None:
                smallest = _smallest_branch(case)
                label = _branch_label(journey, case.random.activity_key, smallest) if smallest else "?"
                special = (f"random split {_activity_label(journey, case.random.activity_key)}: "
                           f"{case.random.expected_low} to {case.random.expected_high} contacts expected on the "
                           f"{label} side")
            else:
                actions = []
                for action in case.manual_actions:
                    deadline = _deadline(context, scenario, case, action)
                    when = f"before {deadline}" if deadline else "as soon as it arrives"
                    actions.append(f"{action.kind} '{action.email_name}' {when}")
                special = "; ".join(actions)
            case_rows.append([case.id, scenario.key, len(case.contact_keys), _key_range(case.contact_keys),
                              special or "none", _activity_label(journey, case.end_activity_key),
                              _case_summary(context, case)])
    cases_intro = "A case is a group of contacts that share one expected result."
    if TESTBOOK_FILE in result.files:
        cases_intro += f" Each case is one test in {TESTBOOK_FILE}, under the same name."
    return "\n\n".join([
        "## Scenarios",
        _how_to_run(result, context),
        "### Scenario list",
        list_intro,
        _md_table(["Scenario", "Run order", "Active at start", "Manual action", "Statistical", "Cases", "Contacts",
                   "Contact keys", "Values"], scenario_rows),
        "### Cases",
        cases_intro,
        _md_table(["Case", "Scenario", "Contacts", "Contact keys", "Manual action or random split",
                   "Last activity", "Summary"], case_rows),
    ])


def _root_text(journey: Journey, root: tuple[str, str], branches: list[BranchStatus],
               by_ref: dict) -> str:
    """One line per root cause: "N branches lie behind 'split: outcome' (KEY), which is unreachable because ..."."""
    activity = journey.activities.get(root[0])
    name = (activity.name or root[0]) if activity is not None else root[0]
    label = _outcome_label(journey, root[0], root[1])
    status = by_ref.get(root)
    reason = status.reason if status is not None and status.reason else ""
    if not reason:
        inherited = _REASON_BEHIND_BRANCH.match(branches[0].reason or "")
        reason = inherited.group("reason") if inherited else ""
    state, clause = _explain_reason(reason, journey, root[0], root[1])
    count = _plural(len(branches), "branch lies", "branches lie")
    if state is None:
        tail = f"which is not covered: {clause}" if clause else "which is not covered"
    else:
        tail = f"which is {state} because {clause}"
    return f"{count} behind '{name}: {label}' ({root[0]}), {tail.rstrip('.')}."


def _behind_list(journey: Journey, branches: list[BranchStatus]) -> str:
    """The branches behind one root cause, in a compact form: the splits they belong to, by name."""
    outcomes: dict[str, list[str]] = {}
    for branch in branches:
        outcomes.setdefault(branch.activity_key, []).append(branch.outcome_key)
    by_name: dict[str, list[str]] = {}
    complete = True
    for key, keys in outcomes.items():
        activity = journey.activities.get(key)
        entry = key
        if activity is not None and set(keys) != {o.key for o in activity.outcomes}:
            complete = False
            entry = f"{key} for {_join_words(repr(_outcome_label(journey, key, o)) for o in keys)}"
        name = (activity.name or key) if activity is not None else key
        by_name.setdefault(name, []).append(entry)
    count = len(outcomes)
    which = "this split" if count == 1 else f"these {count} splits"
    lead = f"They are all the outcomes of {which}:" if complete else f"They are outcomes of {which}:"
    items = []
    for name, keys in by_name.items():
        keys = sorted(keys, key=_natural_key)
        items.append(", ".join(keys) if name in keys else f"{name}: {', '.join(keys)}")
    return lead + "\n\n" + _bullets(items)


def _section_not_covered(result: GenerationResult) -> str:
    journey = result.package.journey
    missing = [b for b in result.coverage.branches if b.status == STATUS_NOT_COVERED]
    if not missing:
        return "## Branches not covered\n\nEvery branch is covered."
    by_ref = {(b.activity_key, b.outcome_key): b for b in result.coverage.branches}
    behind_branch: dict[tuple[str, str], list[BranchStatus]] = {}
    behind_unsupported: dict[str, list[BranchStatus]] = {}
    own: list[BranchStatus] = []
    for branch in missing:
        if branch.behind is not None:
            behind_branch.setdefault(tuple(branch.behind), []).append(branch)
        elif _REASON_BEHIND_UNSUPPORTED.match(branch.reason or ""):
            behind_unsupported.setdefault(branch.reason, []).append(branch)
        else:
            own.append(branch)
    grouped = sum(len(v) for v in behind_branch.values()) + sum(len(v) for v in behind_unsupported.values())
    causes = []
    if behind_branch:
        causes.append(_plural(len(behind_branch), "branch that no contact can reach",
                              "branches that no contact can reach"))
    if behind_unsupported:
        causes.append(_plural(len(behind_unsupported), "unsupported activity", "unsupported activities"))
    intro = f"{_plural(len(missing), 'branch is', 'branches are')} not covered."
    if grouped and own:
        intro += (f" {grouped} of them lie behind {' or '.join(causes)}, explained first. The other {len(own)} "
                  f"{'has a reason of its own' if len(own) == 1 else 'have reasons of their own'}, in the table at "
                  "the end.")
    elif grouped:
        intro += f" {'It lies' if grouped == 1 else 'They all lie'} behind {' or '.join(causes)}, explained below."
    parts = ["## Branches not covered", intro]
    if grouped:
        parts.append("### Root causes")
        for root, branches in sorted(behind_branch.items(),
                                     key=lambda item: (-len(item[1]), _natural_key(item[0][0]), item[0][1])):
            parts.append(_root_text(journey, root, branches, by_ref))
            parts.append(_behind_list(journey, branches))
        for reason, branches in behind_unsupported.items():
            blockers = _join_words(_quoted_labels(journey, _REASON_BEHIND_UNSUPPORTED.match(reason).group("keys")))
            parts.append(f"{_plural(len(branches), 'branch lies', 'branches lie')} behind the unsupported activity "
                         f"{blockers}. See Unsupported elements.")
            parts.append(_behind_list(journey, branches))
    if own:
        rows = []
        for b in own:
            activity = f"{b.activity_name} ({b.activity_key})" if b.activity_name else b.activity_key
            outcome = b.outcome_label if b.outcome_label == b.outcome_key else f"{b.outcome_label} ({b.outcome_key})"
            text = _reason_sentence(b.reason, journey, b.activity_key, b.outcome_key)
            behind = behind_branch.get((b.activity_key, b.outcome_key))
            if behind:
                text += f" {_plural(len(behind), 'branch lies', 'branches lie')} behind it."
            rows.append([activity, outcome, text])
        if grouped:
            parts.append("### Branches with a reason of their own")
        parts.append(_md_table(["Activity", "Outcome", "Reason"], rows))
    return "\n\n".join(parts)


def _section_special_branches(result: GenerationResult) -> str:
    """Spec, "Outputs": every branch ends in one of three states, each with its reason. The
    branches covered with a manual action, and those crossed only through a random split, are
    listed here by name, with the cases that cover them."""
    journey = result.package.journey
    manual = [b for b in result.coverage.branches if b.status == STATUS_MANUAL]
    statistical = [b for b in result.coverage.branches if b.statistical and b.status != STATUS_NOT_COVERED]
    if not manual and not statistical:
        return ""
    parts = ["## Branches covered with a manual action or through a random split"]
    if manual:
        rows = [[f"{_activity_name(journey, b.activity_key)} ({b.activity_key})", b.outcome_label,
                 ", ".join(b.covered_by)] for b in manual]
        parts.append(f"{len(manual)} branches are covered only by contacts that must open or click an email. "
                     "The testbook names the action and its deadline.")
        parts.append(_md_table(["Activity", "Outcome", "Cases"], rows))
    if statistical:
        rows = [[f"{_activity_name(journey, b.activity_key)} ({b.activity_key})", b.outcome_label,
                 ", ".join(b.covered_by)] for b in statistical]
        parts.append(f"{len(statistical)} branches are crossed only after a random split, by the contacts of a "
                     "statistical case. The testbook gives the accepted range.")
        parts.append(_md_table(["Activity", "Outcome", "Cases"], rows))
    return "\n\n".join(parts)


def _section_unsupported(result: GenerationResult) -> str:
    journey = result.package.journey
    items = []
    for key in _unique(list(result.package.unsupported_activities) + list(result.coverage.unsupported)):
        activity = journey.activities.get(key)
        label = _activity_label(journey, key)
        reason = getattr(activity, "unsupported_reason", None) if activity is not None else None
        if reason:
            items.append(f"{label} is not supported: {reason.rstrip('.')}. Its branches and the branches behind it "
                         "are not covered.")
        elif activity is not None:
            items.append(f"{label} has the type {activity.raw_type}, which the generator does not support. Its "
                         "branches and the branches behind it are not covered.")
        else:
            items.append(f"Activity {key} is not supported. The branches behind it are not covered.")
    query = result.table_model.entry_query
    if query is not None:
        for flt in query.filters:
            if isinstance(flt, UnsupportedFilter):
                items.append(f"The entry query filter `{flt.text}` is not supported, so the generated rows may not "
                             "pass it.")
    items.extend(f"Placeholder: {_sentence(text)}" for text in result.data.placeholders)
    if not items:
        return "## Unsupported elements\n\nNo unsupported element was found."
    return "\n\n".join(["## Unsupported elements", _bullets(items)])


def _key_list(text: str) -> list[str]:
    """Activity keys written as ``A, B, C``, in natural order."""
    return sorted((key.strip() for key in text.split(",") if key.strip()), key=_natural_key)


def _case_line(matches: list[re.Match], tail: str, package: Package) -> str:
    """Fields compared with one value written in several letter cases."""
    values = matches[0].group("values")
    refs = _ordered_refs(package, [(m.group("table"), m.group("field")) for m in matches])
    if len(refs) == 1:
        text = f"{refs[0][0]}.{refs[0][1]} is compared with {values}."
    elif len({table.lower() for table, _ in refs}) == 1:
        text = f"{_join_words(field for _, field in refs)} of {refs[0][0]} are each compared with {values}."
    else:
        text = f"{_join_words(f'{table}.{field}' for table, field in refs)} are each compared with {values}."
    if tail:
        text += f" {_CASE_TAILS.get(tail, _sentence(tail))} How Salesforce compares them is an assumption to verify."
    return text


def _same_name_line(matches: list[re.Match]) -> str:
    """Splits that share a name but test different conditions."""
    groups = [f"'{m.group('name')}' in {m.group('count')} versions, first seen in "
              f"{_join_words(_key_list(m.group('keys')))}" for m in matches]
    return "Splits with the same name test different conditions: " + "; ".join(groups) + "."


def _constant_key_line(matches: list[re.Match]) -> str:
    """Update contact steps that write a constant into a primary-key field."""
    steps = [_key_list(m.group("keys")) for m in matches]
    tables = {m.group("table") for m in matches}
    if all(keys == steps[0] for keys in steps) and len(tables) == 1:
        first = matches[0]
        if len(matches) == 1:
            what = (f"the constant {first.group('value')} into the primary-key field "
                    f"{first.group('table')}.{first.group('field')}")
        else:
            writes = _join_words(f"{m.group('value')} into {m.group('field')}" for m in matches)
            what = f"constants into primary-key fields of {first.group('table')}: {writes}"
        count = _plural(len(steps[0]), "update contact step writes", "update contact steps write")
        return (f"{count} {what}. Every contact therefore gets the same key "
                f"{'value' if len(matches) == 1 else 'values'} there. "
                f"{'The step is' if len(steps[0]) == 1 else 'The steps are'} {_join_words(steps[0])}.")
    parts = [f"{m.group('value')} into {m.group('table')}.{m.group('field')}, by {_join_words(keys)}"
             for m, keys in zip(matches, steps)]
    return ("Update contact steps write constants into primary-key fields, so every contact gets the same key "
            "value there: " + "; ".join(parts) + ".")


def _one_to_one_line(matches: list[re.Match]) -> str:
    """One-to-one relationships that join on part of a primary key."""
    parts = [f"'{m.group('name')}' joins {m.group('table')} on {m.group('fields')}, and the key of {m.group('table')} "
             f"also has {_join_words(k.strip() for k in m.group('extra').split(','))}" for m in matches]
    lead = "A one-to-one relationship" if len(parts) == 1 else "One-to-one relationships"
    return f"{lead} joins on part of a primary key, so several rows can match one contact: " + "; ".join(parts) + "."


def _merge_patterns(patterns: list[str], package: Package) -> list[str]:
    """One line per kind of suspicious pattern, in the order first met. Patterns of a kind the report does
    not know are kept as they are."""
    kinds = [("case", _CASE_PATTERN), ("names", _SAME_NAME_PATTERN), ("constants", _CONSTANT_KEY_PATTERN),
             ("one_to_one", _ONE_TO_ONE_PATTERN)]
    order: list = []
    groups: dict = {}
    for pattern in patterns:
        for kind, regex in kinds:
            match = regex.match(pattern)
            if match is None:
                continue
            group = ((kind, frozenset(_quoted_values(match.group("values"))), match.group("tail") or "")
                     if kind == "case" else (kind,))
            if group not in groups:
                groups[group] = []
                order.append(group)
            groups[group].append(match)
            break
        else:
            order.append(pattern)
    lines = []
    for item in order:
        if isinstance(item, str):
            lines.append(item)
        elif item[0] == "case":
            lines.append(_case_line(groups[item], item[2], package))
        elif item[0] == "names":
            lines.append(_same_name_line(groups[item]))
        elif item[0] == "constants":
            lines.append(_constant_key_line(groups[item]))
        else:
            lines.append(_one_to_one_line(groups[item]))
    return lines


def _reword_warning(warning: str, result: GenerationResult) -> str:
    """The extra columns of the entry query: what the generator does is a fact, what Salesforce does is an
    assumption (docs/assumptions.md, row 28)."""
    match = _IGNORED_COLUMNS.match(warning.strip())
    if not match:
        return warning
    columns = [column.strip() for column in match.group("columns").split(",") if column.strip()]
    return (f"The entry query selects {_plural(len(columns), 'column', 'columns')} that {match.group('table')} does "
            f"not have: {_join_words(columns)}. The generator ignores {'it' if len(columns) == 1 else 'them'}. What "
            "Salesforce does with such a query is an assumption to verify, listed under Assumptions.")


def _section_warnings(result: GenerationResult) -> str:
    query = result.table_model.entry_query
    sources = [
        ("While reading the export", result.package.warnings),
        ("Table selection and SQL", list(result.table_model.warnings) + (list(query.warnings) if query else [])),
        ("Coverage", result.coverage.warnings),
        ("Data generation", result.data.warnings),
    ]
    patterns: list[str] = []
    groups: list[tuple[str, list[str]]] = []
    for title, warnings in sources:
        found, others = _split_suspicious(warnings)
        patterns.extend(found)
        groups.append((title, [_reword_warning(warning, result) for warning in others]))
    patterns = _merge_patterns(_unique(patterns), result.package)
    parts = ["## Warnings and suspicious patterns"]
    for title, items in [("Suspicious patterns", patterns)] + groups:
        items = _unique(_sentence(item) for item in items)
        if items:
            parts.append(f"### {title}\n\n{_bullets(items)}")
    if len(parts) == 1:
        parts.append("No warning.")
    return "\n\n".join(parts)


def _ignored_entry_columns(result: GenerationResult) -> list[str]:
    """Columns that the entry query selects but the entry table does not have."""
    query = result.table_model.entry_query
    entry = _table_of(result.package, result.table_model.entry_table)
    if query is None or entry is None or query.select_all:
        return []
    return [item.target_column for item in query.select if entry.field(item.target_column) is None]


def _section_assumptions(result: GenerationResult) -> str:
    """Spec, "Assumptions to verify and known limits": the six assumptions the generator encodes, plus
    the ones of the Salesforce review that this export triggers."""
    settings = result.settings
    if settings.case_insensitive_text:
        case_text = ("Text comparisons ignore letter case, so `Email` and `EMAIL` are the same value. The setting "
                     "that ignores letter case is on.")
    else:
        case_text = ("Text comparisons are case-sensitive, so `Email` and `EMAIL` are different values. The setting "
                     "that ignores letter case is off.")
    zones = sorted({a.wait_timezone for a in result.package.journey.activities.values()
                    if a.kind == KIND_WAIT_ATTRIBUTE and a.wait_timezone})
    zone_text = f" The waits by attribute of this journey are set to {_join_words(zones)}." if zones else ""
    items = [
        "Decision split outcomes are evaluated in order, and the first outcome that matches wins.",
        case_text,
        "A wait by attribute whose date is already past ends at once.",
        f"The import accepts dates written like {_date(result.generation_time, settings)}, in the format "
        f"{_human_date_format(settings.date_format)}, and `True` and `False` for Booleans.",
        "An engagement split is evaluated when the contact reaches it, not when the email is sent.",
        "The time zone applied to a wait date is not known, so the deadlines in the testbook could shift by some "
        f"hours.{zone_text}",
    ]
    automation = _entry_procedures(result)
    if automation:
        items.append(f"Importing {table_file_name(result.table_model.entry_table)} admits its contacts. The "
                     f"automation {automation} runs the entry of this journey, and the Salesforce review says that an "
                     "import alone may admit nobody. See How to run.")
    ignored = _ignored_entry_columns(result)
    if ignored and result.table_model.entry_query is not None:
        items.append(f"The entry query {result.table_model.entry_query.name} runs although it selects "
                     f"{_plural(len(ignored), 'column', 'columns')} that {result.table_model.entry_table} does not "
                     f"have. The generator ignores {'that column' if len(ignored) == 1 else 'those columns'}.")
    return "\n\n".join([
        "## Assumptions",
        "The expected results depend on these assumptions about how Salesforce behaves. Check each one once with a "
        "small real run. The file docs/assumptions.md of the CJ Test Helper repository lists them all, with how to "
        "verify each one and which to check first.",
        _bullets(items),
    ])


_SETTING_LABELS = {
    "contacts_per_case": "Contacts per case",
    "contacts_per_random_case": "Contacts per random-split case",
    "real_inbox": "Real inbox for open and click tests",
    "real_phone": "Real phone number",
    "fake_phone": "Fake phone number",
    "window_start_days": "Validity window start",
    "window_end_days": "Validity window end",
    "wait_offset_hours": "Wait date offset",
    "wait_offset_before_engagement_hours": "Wait date offset before an engagement split",
    "date_format": "Date format in the CSVs",
    "one_active_scenario": "One active scenario at a time",
    "activation_field": "Activation field",
    "run_id": "Run identifier in keys",
    "case_insensitive_text": "Text comparisons ignore letter case",
    "seed": "Seed of the set cover",
    "generation_time": "Generation time",
}


def _days_text(days: int) -> str:
    if days == 0:
        return "the generation time"
    side = "before" if days < 0 else "after"
    return f"{_plural(abs(days), 'day', 'days')} {side} the generation time"


def _setting_text(name: str, value, result: GenerationResult) -> str:
    if name == "generation_time":
        return _date(result.generation_time, result.settings)
    if name == "one_active_scenario" and value is None:
        return "on when an activation field is detected"
    if name == "activation_field" and value is None:
        return "suggested from the entry query filters"
    if name in ("window_start_days", "window_end_days") and isinstance(value, int):
        return _days_text(value)
    if name in ("wait_offset_hours", "wait_offset_before_engagement_hours") and isinstance(value, int):
        return _plural(value, "hour", "hours")
    if name == "date_format" and isinstance(value, str):
        return _human_date_format(value)
    if value is None or value == "":
        return "none"
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, tuple):
        return ".".join(str(part) for part in value)
    return str(value)


def _section_settings(result: GenerationResult) -> str:
    rows = [[_SETTING_LABELS.get(f.name, f.name), _setting_text(f.name, getattr(result.settings, f.name), result)]
            for f in dataclasses.fields(result.settings)]
    on, ref, _ = activation_setting(result.package, result.table_model, result.settings)
    rows.append(["One active scenario at a time, as applied",
                 f"on, activation field {ref[0]}.{ref[1]}" if on else "off"])
    return "\n\n".join(["## Settings used", _md_table(["Setting", "Value"], rows)])


def write_report(result: GenerationResult) -> str:
    """Spec, "Outputs": "report.md: Coverage, unreachable branches, unsupported elements, warnings,
    settings used". It "opens with a summary: number of scenarios, cases and contacts, and branches
    covered, covered with manual action, and not covered". Every number is computed from ``result``."""
    sections = [
        _section_title(result),
        _section_summary(result),
        _section_checks(result),
        _section_tables(result),
        _section_scenarios(result),
        _section_not_covered(result),
        _section_special_branches(result),
        _section_unsupported(result),
        _section_warnings(result),
        _section_assumptions(result),
        _section_settings(result),
    ]
    return "\n\n".join(sec for sec in sections if sec) + "\n"
