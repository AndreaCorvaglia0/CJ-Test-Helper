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
SUSPICIOUS_PREFIX = "pattern sospetto:"    # how other modules mark a suspicious pattern


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
    KIND_DECISION: "questo decision split",
    KIND_ENGAGEMENT: "questo engagement split",
    KIND_RANDOM: "questo random split",
    KIND_WAIT_DURATION: "questo wait",
    KIND_WAIT_ATTRIBUTE: "questo wait",
    KIND_WAIT_STO: "questo send-time wait",
    KIND_EMAIL: "questa email",
    KIND_UPDATE: "questo Update contact",
}

# Duration units as the export writes them (singular, lower case) -> Italian singular and plural.
_UNIT_WORDS = {
    "second": ("secondo", "secondi"),
    "minute": ("minuto", "minuti"),
    "hour": ("ora", "ore"),
    "day": ("giorno", "giorni"),
    "week": ("settimana", "settimane"),
    "month": ("mese", "mesi"),
    "year": ("anno", "anni"),
}

# A manual action (``ManualAction.kind``) in the forms the testbook needs.
_ACTION_INFINITIVE = {"open": "aprire", "click": "cliccare"}
_ACTION_TO_DO = {"open": "aprire l'email", "click": "cliccare un link nell'email"}
_ACTION_IMPERATIVE = {"open": "apri l'email", "click": "clicca un link nell'email"}
_ACTION_SUBJUNCTIVE = {"open": "aprano l'email", "click": "clicchino un link nell'email"}

# The level of a table as the report writes it.
_LEVEL_WORDS = {"contact": "contatto", "scenario": "scenario"}

# The not-covered states of ``_explain_reason`` after "che" ("which is ...").
_STATE_WORDS = {"unreachable": "non è raggiungibile", "not covered": "non è coperto"}


def _show(value: Value) -> str:
    return "(vuoto)" if value is None or value == "" else str(value)


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _covered(count: int, words: str = "coperto") -> str:
    """"1 è coperto", "8 sono coperti", "1 non è coperto"; ``words`` is the singular adjective, with a
    leading "non " when negated."""
    negated = words.startswith("non ")
    adjective = words[4:] if negated else words
    verb = "è" if count == 1 else "sono"
    shown = adjective if count == 1 else adjective[:-1] + "i"
    return f"{count} {'non ' if negated else ''}{verb} {shown}"


def _lie_behind(count: int) -> str:
    """"1 branch si trova", "3 branch si trovano"."""
    return f"{count} branch {'si trova' if count == 1 else 'si trovano'}"


def _join_words(items: Iterable[str]) -> str:
    """'a', 'a e b', 'a, b e c'."""
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " e " + items[-1]


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


def _duration_text(amount, unit: Optional[str], english: bool = False) -> str:
    unit_text = (unit or "").lower()
    if amount == 1 and unit_text.endswith("s"):
        unit_text = unit_text[:-1]
    words = None if english else _UNIT_WORDS.get(unit_text[:-1] if unit_text.endswith("s") else unit_text)
    if words is not None:
        unit_text = words[0] if amount == 1 else words[1]
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
        return "(nessuna)"
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
    return " > ".join(texts) if texts else "(nessuna attività)"


def _times(count: int) -> str:
    return "una volta" if count == 1 else f"{count} volte"


def _emails_text(journey: Journey, keys: Iterable[str]) -> str:
    """The emails received, by name, with a count when one is received more than once: "Demo Sky, 2 volte"."""
    counts: dict[str, int] = {}
    for key in keys:
        activity = journey.activities.get(key)
        name = (activity.email_name or activity.name or key) if activity is not None else key
        counts[name] = counts.get(name, 0) + 1
    if not counts:
        return "nessuna"
    if len(counts) == 1:
        name, count = next(iter(counts.items()))
        return name if count == 1 else f"{name}, {count} volte"
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
            shown = "la data e l'ora in cui viene eseguito il passo"
        else:
            shown = _show(value)
        groups.setdefault(table, []).append(f"{field} = {shown}")
    parts = [f"{table}.{items[0]}" if len(items) == 1 else f"{table}: {', '.join(items)}"
             for table, items in groups.items()]
    return "; ".join(parts) if parts else "nessuno"


def _ordered_scenarios(result: GenerationResult) -> list[Scenario]:
    return sorted(result.coverage.scenarios, key=lambda s: (s.run_order, s.id))


def _key_range(keys: list[str]) -> str:
    if not keys:
        return "nessuno"
    if len(keys) <= 3:
        return ", ".join(keys)
    return f"da {keys[0]} a {keys[-1]}"


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
        return f"Lì i contatti escono dal journey, sul branch {outcome.label or outcome.key}."
    return f"I contatti escono dal journey dopo {_KIND_WORDS.get(activity.kind, 'questa attività')}."


# ---------------------------------------------------------------------------
# Test names: a short summary of what makes a case different
# ---------------------------------------------------------------------------

def _short_label(activity: Activity, outcome: Outcome) -> str:
    """An outcome label short enough for a test name. In a two-way split whose condition has a long
    label, the outcomes read "sì" and "no"; any other long label is cut at a word."""
    conditions = [o for o in activity.outcomes if not o.is_remainder]
    remainders = [o for o in activity.outcomes if o.is_remainder]
    if (len(conditions) == 1 and len(remainders) == 1
            and len(conditions[0].label or conditions[0].key) > _LABEL_LIMIT):
        return "sì" if outcome is conditions[0] else "no"
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
            verb = "aperta" if activity.engagement_kind == "open" else "cliccata"
            return (f"{name} {verb}" if outcome.when else f"{name} non {verb}"), 3
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
        return f"Percorso fino a {_activity_name(context.journey, case.end_activity_key)}"
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
        scenario_line = f"Scenario {scenario.key}: nessun valore a livello di scenario."
    elif table:
        scenario_line = f"Scenario {scenario.key}, valori in {table}: {'; '.join(items)}."
    else:
        scenario_line = f"Scenario {scenario.key}: {'; '.join(items)}."
    table, items = _values_parts(package, case.contact_values, coverage.contact_fields)
    if not items:
        contact_line = "Profilo del contatto: nessun valore a livello di contatto."
    elif table:
        contact_line = f"Profilo del contatto in {table}: {'; '.join(items)}."
    else:
        contact_line = f"Profilo del contatto: {'; '.join(items)}."
    lines = [scenario_line, contact_line, f"Percorso atteso: {_path_text(context.journey, case.steps)}."]
    if case.random is not None:
        random_key = case.random.activity_key
        lines.append(f"Al random split {_activity_label(context.journey, random_key)} ogni contatto prende uno dei "
                     "branch.")
        for branch in case.random.branches:
            path = _path_text(context.journey, branch.steps) if branch.steps else "il contatto esce dal journey"
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
    row_text = f"riga con {key_column} {scenario.key}" if key_column else f"riga dello scenario {scenario.key}"
    if scenario is context.first_scenario:
        return (f"Verifica che lo scenario {scenario.key} sia quello attivo: in {table}, {field} è True sulla "
                f"{row_text} e False su tutte le altre righe, come generato.")
    return (f"Quando i contatti dello scenario precedente sono usciti dal journey, attiva lo scenario {scenario.key}: "
            f"in {table}, imposta {field} a True sulla {row_text} e a False su tutte le altre righe. Non cambiare "
            "altro.")


def _entry_procedures(result: GenerationResult) -> Optional[str]:
    """The automation that schedules the entry source, when the entry table is also filled by an entry query.
    Only named in the assumption note: the test itself always uses the direct import."""
    entry = result.package.entry_event
    automation = entry.automation_name if entry is not None else None
    return automation if automation and result.table_model.entry_query is not None else None


def _preconditions(context: _TestbookContext, scenario: Scenario, case: Case) -> str:
    """Spec: "Which CSVs must be imported, which scenario must be active, and the keys of the test
    contacts"; "The 50 contacts of a random split case are given as a key range"."""
    entry_csv = table_file_name(context.result.table_model.entry_table)
    first = f"Importa questi file CSV: {', '.join(context.csv_names)}."
    if len(context.csv_names) > 1 and entry_csv in context.csv_names:
        first += f" Importa {entry_csv} per ultimo."
    lines = [first]
    if context.one_active:
        table, field = context.activation_ref
        lines.append(f"Scenario attivo: {scenario.key}. In {table}, {field} è True solo sulla sua riga.")
    else:
        lines.append(f"Scenario: {scenario.key}. Tutti gli scenari sono attivi contemporaneamente.")
    keys = case.contact_keys
    if case.random is not None and len(keys) > 3:
        lines.append(f"Contatti di test ({len(keys)}): da {keys[0]} a {keys[-1]}.")
    else:
        lines.append(f"Contatti di test ({len(keys)}): {', '.join(keys) if keys else 'nessuno'}.")
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
            english = _duration_text(activity.wait_amount, activity.wait_unit, english=True)
            texts.append(name if name.lower() in (duration.lower(), english.lower()) else f"{name} ({duration})")
        elif activity.kind == KIND_WAIT_STO:
            if activity.wait_amount:
                texts.append(f"{name}, un send-time wait di al massimo "
                             f"{_duration_text(activity.wait_amount, activity.wait_unit)}")
            else:
                texts.append(f"{name}, un send-time wait la cui attesa non è nota in anticipo")
        elif activity.kind == KIND_WAIT_ATTRIBUTE and activity.wait_field is not None:
            table, field = activity.wait_field
            value = _written_value(context, table, field, scenario, case)
            until = f"fino al {value}, la data in {table}.{field}" if value else f"fino alla data in {table}.{field}"
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
        kind = "open" if action.kind == "open" else "click"
        split = _quoted_label(context.journey, action.activity_key)
        if not inbox:
            steps.append(f"Lo split {split} richiede che i contatti {_ACTION_SUBJUNCTIVE[kind]} '{action.email_name}', "
                         "ma non è stata indicata un'inbox reale, quindi le email non possono essere ricevute. Questo "
                         "test non può raggiungere il risultato atteso finché i dati non vengono generati di nuovo con "
                         "un'inbox reale.")
            continue
        wait, deadline = _deadline_wait(context, scenario, case, action)
        when = f"Prima del {deadline}" if deadline else "Appena arriva l'email"
        text = (f"{when}, {_ACTION_IMPERATIVE[kind]} '{action.email_name}' inviata a ogni contatto di questo test: "
                f"{addresses}.")
        if deadline and wait is not None:
            text += (f" A quell'ora termina il wait {_quoted_label(context.journey, wait.key)} e i contatti "
                     f"proseguono verso lo split {split}.")
        steps.append(text + f" Le email arrivano nell'inbox {inbox}. Non aprire e non cliccare le email degli altri "
                     "test.")
    return steps


def _detailed_steps(context: _TestbookContext, scenario: Scenario, case: Case) -> str:
    """Spec: "Numbered steps: activate the scenario, start the entry, wait (with expected delays), any
    manual action with its deadline, collect evidence"."""
    steps = []
    if context.one_active:
        steps.append(_activation_text(context, scenario))
    else:
        steps.append(f"Verifica che le righe dello scenario {scenario.key} siano state importate.")
    entry_csv = table_file_name(context.result.table_model.entry_table)
    steps.append(f"Avvia l'ingresso nel journey {context.journey.name} dalle righe importate di {entry_csv}. "
                 "Tutti i test di questo scenario partono insieme.")
    waits = _wait_descriptions(context, scenario, case)
    steps.append("Attendi che i contatti superino i wait del loro percorso: " + "; ".join(waits) + "." if waits else
                 "Il percorso non ha wait.")
    steps.extend(_manual_steps(context, scenario, case))
    steps.append("Raccogli le evidenze per ogni contatto: le email ricevute, i valori scritti dal journey e l'ultima "
                 "attività raggiunta.")
    return "\n".join(f"{number}. {text}" for number, text in enumerate(steps, 1))


def _expected_result(context: _TestbookContext, case: Case) -> str:
    """Spec: "For each contact: the emails or messages received, the values written by the journey, and
    the last activity reached". The contacts of a case share one expected result."""
    journey = context.journey
    keys = case.contact_keys
    now_text = _date(context.result.generation_time, context.settings)
    base_keys = [step.activity_key for step in case.steps]
    if case.random is None:
        last = f"- Ultima attività raggiunta: {_activity_label(journey, case.end_activity_key)}."
        end = _end_sentence(journey, case.steps[-1] if case.steps else None)
        return "\n".join([
            f"Per ciascuno di questi contatti: {_join_words(keys) if keys else 'nessuno'}.",
            f"- Email ricevute: {_emails_text(journey, case.emails_sent)}.",
            f"- Valori scritti dal journey: "
            f"{_writes_text(case.writes, _current_time_fields(journey, base_keys), now_text)}.",
            f"{last} {end}" if end else last,
        ])
    random_key = case.random.activity_key
    lines = [
        f"Per ciascuno dei {len(keys)} contatti {_key_range(keys)}, fino al random split "
        f"{_activity_label(journey, random_key)}:",
        f"- Email ricevute: {_emails_text(journey, case.emails_sent)}.",
        f"- Valori scritti dal journey: "
        f"{_writes_text(case.writes, _current_time_fields(journey, base_keys), now_text)}.",
        "Poi ogni contatto prende uno dei branch del random split:",
    ]
    for branch in case.random.branches:
        branch_keys = base_keys + [step.activity_key for step in branch.steps]
        lines.append(f"- {_branch_label(journey, random_key, branch)}: email ricevute: "
                     f"{_emails_text(journey, branch.emails_sent)}; "
                     f"valori scritti: {_writes_text(branch.writes, _current_time_fields(journey, branch_keys), now_text)}; "
                     f"ultima attività raggiunta: {_activity_label(journey, branch.end_activity_key)}.")
    smallest = _smallest_branch(case)
    if smallest is not None:
        lines.append(f"Intervallo accettato: da {case.random.expected_low} a {case.random.expected_high} contatti sul "
                     f"branch {_branch_label(journey, random_key, smallest)}.")
    return "\n".join(lines)


def _note(context: _TestbookContext, scenario: Scenario, case: Case) -> str:
    """Spec: "Manual engagement required, or the accepted range for a random split case"."""
    notes = []
    for action in case.manual_actions:
        verb = _ACTION_TO_DO["open" if action.kind == "open" else "click"]
        if not context.settings.real_inbox.strip():
            notes.append(f"Azione manuale richiesta: {verb} '{action.email_name}'. Non è stata indicata un'inbox "
                         "reale, quindi questo test non può raggiungere il risultato atteso.")
            continue
        wait, deadline = _deadline_wait(context, scenario, case, action)
        text = f"Azione manuale richiesta: {verb} '{action.email_name}'"
        notes.append(text + (f" prima del {deadline}." if deadline else " appena arriva."))
        if deadline:
            notes.append("Se l'email arriva dopo quell'ora, genera di nuovo i dati.")
        zone = wait.wait_timezone if deadline and wait is not None else None
        if zone:
            notes.append(f"Il wait {_quoted_label(context.journey, wait.key)} è impostato sul fuso orario {zone}. "
                         "Come Salesforce applica questo fuso orario alla data è un'assunzione da verificare, quindi "
                         "la scadenza potrebbe spostarsi di qualche ora.")
    if case.random is not None:
        smallest = _smallest_branch(case)
        label = _branch_label(context.journey, case.random.activity_key, smallest) if smallest else "più piccolo"
        contacts = len(case.contact_keys)
        notes.append(f"Random split: non è possibile indirizzare i contatti su un branch preciso. Sul branch {label} "
                     f"sono attesi da {case.random.expected_low} a {case.random.expected_high} dei {contacts} "
                     "contatti.")
        chance = _range_chance(contacts, smallest.percentage if smallest else None,
                               case.random.expected_low, case.random.expected_high)
        if chance is not None:
            notes.append(f"Con una probabilità del {smallest.percentage}% per ogni contatto, questo intervallo si "
                         f"verifica in circa il {chance}% dei run.")
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
    written in two letter cases". Other modules mark them with the prefix ``pattern sospetto:``."""
    patterns, others = [], []
    for warning in warnings:
        if warning.lower().startswith(SUSPICIOUS_PREFIX):
            pattern = warning[len(SUSPICIOUS_PREFIX):].strip()
            patterns.append(pattern[:1].upper() + pattern[1:])
        else:
            others.append(warning)
    return patterns, others


# Texts written by other modules that the report rewords. A text that no longer matches is shown as it is.
# Suspicious patterns arrive with their first letter in upper case (``_split_suspicious``), hence ``[Ll]``.
_CASE_PATTERN = re.compile(r"^(?P<table>[^.]+)\.(?P<field>.+?) è confrontato con (?P<values>.+?)"
                           r"(?:; (?P<tail>.+?))?\.?$")
_SAME_NAME_PATTERN = re.compile(r"^(?P<count>\d+) split con condizioni diverse hanno lo stesso nome '(?P<name>.*)' "
                                r"\((?P<keys>.*)\)\.?$")
_CONSTANT_KEY_PATTERN = re.compile(r"^[Ll]a costante (?P<value>.+?) è scritta nel campo di chiave primaria "
                                   r"(?P<table>[^.]+)\.(?P<field>.+?) da (?P<count>\d+) attività Update contact, "
                                   r"quindi tutti i contatti hanno lo stesso valore di chiave in quel campo "
                                   r"\((?P<keys>.*)\)\.?$")
_ONE_TO_ONE_PATTERN = re.compile(r"^[Ll]a relazione uno a uno '(?P<name>.*)' collega (?P<table>.+?) tramite "
                                 r"(?P<fields>.+?), ma la chiave primaria della tabella comprende anche (?P<extra>.+?): "
                                 r"a un contatto possono corrispondere più righe\.?$")
_CASE_TAILS = {
    "sono valori diversi perché i confronti di testo distinguono maiuscole e minuscole (impostazione)":
        "Con l'impostazione attuale i confronti di testo distinguono maiuscole e minuscole, quindi sono valori diversi.",
    "sono trattati come un solo valore perché i confronti di testo non distinguono maiuscole e minuscole":
        "Con l'impostazione attuale i confronti di testo non distinguono maiuscole e minuscole, quindi contano come "
        "un solo valore.",
}
_IGNORED_COLUMNS = re.compile(r"^La entry query seleziona colonne che (?P<table>.+?) non ha\. Queste colonne "
                              r"vengono ignorate: (?P<columns>.+?)\.?$")
_QUOTED = re.compile(r"'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"|\b(null)\b")
_UNREACHABLE_PREFIX = "non raggiungibile: "
_REASON_NEVER_MATCHES = re.compile(r"^non raggiungibile: lo split è raggiunto, ma su quei percorsi la condizione di "
                                   r"'(?P<label>.*)' non è mai vera \((?P<detail>.*)\)$")
_REASON_ALWAYS_ONE_OF = re.compile(r"^(?P<field>.+?) vale sempre uno tra (?P<values>.+)$")
_REASON_NEVER_TRUE = "la condizione non è mai vera"
_REASON_FOLLOWS = re.compile(r"^non raggiungibile: nessuna combinazione di valori dei campi raggiunge questa attività "
                             r"\(segue (?P<keys>.*)\)$")
_REASON_BEHIND_UNSUPPORTED = re.compile(r"^a valle di un elemento non supportato: (?P<detail>.+)$")
_REASON_AFTER_UNSUPPORTED = re.compile(r"^questo branch viene dopo il branch non supportato '(?P<label>.*)' dello "
                                       r"stesso split, quindi non viene mai valutato$")
_REASON_UNSUPPORTED = re.compile(r"^(?P<what>attività non supportata|branch non supportato): (?P<detail>.+)$")
_REASON_BEHIND_BRANCH = re.compile(r"^(?:non raggiungibile|a valle di un elemento non supportato): si trova a valle "
                                   r"del branch .*?, che non è coperto per questo motivo: (?P<reason>.+)$")
_REASON_BLOCKED = re.compile(r"^richiede un open o un click che non si può fare: (?P<detail>.+); i casi esistono$")
_REASON_FIXED = {
    "non raggiungibile: lo split è raggiunto, ma la condizione di un branch precedente è sempre vera":
        ("unreachable", "la condizione di un branch precedente dello split è sempre vera"),
    "non raggiungibile: lo split è raggiunto, ma nessun contatto prende questo branch":
        ("unreachable", "nessun contatto prende questo branch, anche se lo split viene raggiunto"),
    "non raggiungibile: nessun percorso simulato attraversa questo branch":
        ("unreachable", "nessun percorso simulato lo attraversa"),
    "non raggiungibile: nessun percorso dall'inizio del journey raggiunge questa attività":
        ("unreachable", "nessun percorso dall'inizio del journey raggiunge lo split"),
    "richiede un open o un click, ma non è configurata un'inbox reale; i casi esistono, con indirizzi non recapitabili":
        ("not covered", "richiede un open o un click, ma non è stata indicata un'inbox reale. I suoi casi esistono, "
                        "con indirizzi non recapitabili"),
}


def _quoted_values(text: str) -> list[str]:
    """The values of a list such as ``'DM', 'Email', null``, as they should be shown."""
    shown = []
    for single, double, null in _QUOTED.findall(text):
        shown.append("vuoto" if null else (f"'{single}'" if single or not double else f'"{double}"'))
    return shown


def _or_values(text: str) -> str:
    """``'DM', 'Email', 'OB'`` as ``'DM', 'Email' o 'OB'``."""
    values = _quoted_values(text)
    if not values:
        return "uno tra " + text
    return values[0] if len(values) == 1 else ", ".join(values[:-1]) + " o " + values[-1]


def _quoted_labels(journey: Journey, text: str) -> list[str]:
    """Activity keys written as ``'A', 'B'``, by name and key."""
    keys = [single or double for single, double, _ in _QUOTED.findall(text) if single or double]
    return [_activity_label(journey, key) for key in keys] or [text]


def _drop_table(detail: str, condition: str) -> str:
    """``T.F vale sempre ...`` as ``F vale sempre ...`` when the quoted condition already names ``T.F``."""
    field = detail.split(" vale sempre ", 1)[0]
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
                details.append(f"{seen.group('field')} vale sempre {_or_values(seen.group('values'))}")
            elif part != _REASON_NEVER_TRUE:
                details.append(part)
        condition = _condition_text(journey, activity_key, outcome_key)
        if condition:
            details = [_drop_table(detail, condition) for detail in details]
        head = (f"la sua condizione {condition} non è mai soddisfatta" if condition
                else f"'{match.group('label')}' non è mai soddisfatto")
        if details:
            return "unreachable", f"{head}: dove lo split viene raggiunto, {_join_words(details)}"
        return "unreachable", f"{head} dove lo split viene raggiunto"
    match = _REASON_FOLLOWS.match(reason)
    if match:
        parents = _join_words(_quoted_labels(journey, match.group("keys")))
        return "unreachable", f"nessuna combinazione di valori dei campi raggiunge lo split, che segue {parents}"
    match = _REASON_BEHIND_UNSUPPORTED.match(reason)
    if match:
        return "not covered", match.group("detail")
    match = _REASON_UNSUPPORTED.match(reason)
    if match:
        what = ("lo split stesso non è supportato" if match.group("what").startswith("attività")
                else "il branch non è supportato")
        return "not covered", f"{what}: {match.group('detail').rstrip('.')}"
    match = _REASON_BLOCKED.match(reason)
    if match:
        return "not covered", (f"richiede un open o un click che non si può fare: {match.group('detail')}. I suoi "
                               "casi esistono")
    if reason.startswith(_UNREACHABLE_PREFIX):
        return "unreachable", reason[len(_UNREACHABLE_PREFIX):]
    return None, reason


def _reason_sentence(reason: str, journey: Journey, activity_key: str, outcome_key: str) -> str:
    state, clause = _explain_reason(reason, journey, activity_key, outcome_key)
    if state == "unreachable":
        return _sentence(f"Non raggiungibile perché {clause.rstrip('.')}")
    if state == "not covered":
        return _sentence(f"Non coperto perché {clause.rstrip('.')}")
    return _sentence(reason) if reason else "Nessun motivo indicato."


def _section_title(result: GenerationResult) -> str:
    settings = result.settings
    journey = result.package.journey.name
    intro = "Questo report indica cosa coprono i dati di test, come eseguire i test e cosa i dati non possono coprire."
    if TESTBOOK_FILE in result.files:
        intro += f" I passi e il risultato atteso di ogni test sono in {TESTBOOK_FILE}."
    return "\n\n".join([
        f"# Report dei dati di test: {journey}",
        f"Journey {journey}, dal package {result.package.name}. Generato il "
        f"{_date(result.generation_time, settings)} con il run identifier {settings.run_id}.",
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
        ["Scenari", len(coverage.scenarios)],
        ["Scenari statistici", sum(1 for s in coverage.scenarios if s.is_statistical)],
        ["Casi", len(cases)],
        ["Casi con un'azione manuale", sum(1 for c in cases if c.manual_actions)],
        ["Casi statistici, per un random split", sum(1 for c in cases if c.random is not None)],
        ["Contatti", len(data.contacts)],
        ["Contatti con l'inbox reale", sum(1 for c in data.contacts if c.uses_real_inbox)],
        ["Branch", len(coverage.branches)],
        ["Branch coperti", covered],
        ["Branch coperti con un'azione manuale", manual],
        ["Branch non coperti", not_covered],
        ["Branch coperti solo tramite un random split", statistical],
    ]
    text = (f"I dati di test comprendono {_plural(len(coverage.scenarios), 'scenario', 'scenari')}, "
            f"{_plural(len(cases), 'caso', 'casi')} e {_plural(len(data.contacts), 'contatto', 'contatti')}. "
            f"Su {len(coverage.branches)} branch, {_covered(covered)}, "
            f"{_covered(manual)} con un'azione manuale e {_covered(not_covered, 'non coperto')}.")
    tables = list(result.table_model.scenario_tables)
    if len(tables) == 1:
        terms = f"Uno scenario è una riga di {tables[0]}, condivisa da tutti i suoi contatti."
    elif tables:
        terms = (f"Uno scenario è una riga in ciascuna delle tabelle {_join_words(tables)}, condivisa da tutti i "
                 "suoi contatti.")
    else:
        terms = "Uno scenario raggruppa i casi che vengono eseguiti insieme."
    terms += (" Un caso raggruppa contatti con gli stessi valori di contatto e le stesse azioni manuali, che quindi "
              "seguono lo stesso percorso fino all'eventuale random split.")
    if TESTBOOK_FILE in result.files:
        terms += f" Ogni caso è un test di {TESTBOOK_FILE}."
    return "\n\n".join(["## Riepilogo", text, terms, _md_table(["Voce", "Numero"], rows)])


def _section_checks(result: GenerationResult) -> str:
    if not result.checks:
        return "## Trust check\n\nSu questi file non è stato eseguito alcun trust check."
    failed = [check for check in result.checks if not check.passed]
    total = len(result.checks)
    if failed:
        passed = total - len(failed)
        text = (f"{passed} trust check su {total} {'è superato' if passed == 1 else 'sono superati'}, "
                f"{len(failed)} {'non è superato' if len(failed) == 1 else 'non sono superati'}: i dettagli sono "
                "qui sotto.")
    else:
        text = "Il trust check è superato." if total == 1 else f"Tutti i {total} trust check sono superati."
    meaning = ("Dopo aver scritto i file, il generatore li rilegge e li controlla. Un check non superato significa che "
               "i file potrebbero non fare quello che dicono questo report e il testbook. Non importarli finché la "
               "causa non è chiarita.")
    rows = [[check.name, "superato" if check.passed else "NON SUPERATO", len(check.details)]
            for check in result.checks]
    parts = ["## Trust check", text, meaning, _md_table(["Trust check", "Esito", "Dettagli"], rows)]
    for check in result.checks:
        if not check.details:
            continue
        shown = check.details[:_REPORT_DETAIL_LIMIT]
        lines = [f"### {check.name}", _bullets(_sentence(detail) for detail in shown)]
        if len(check.details) > len(shown):
            lines.append(f"Ce ne sono altri {len(check.details) - len(shown)}.")
        parts.append("\n\n".join(lines))
    return "\n\n".join(parts)


def _section_tables(result: GenerationResult) -> str:
    rows = []
    for role in result.table_model.tables.values():
        data = result.data.tables.get(role.name)
        rows.append([role.name, ", ".join(sorted(role.roles)) or "nessuno",
                     _LEVEL_WORDS.get(role.level, role.level) if role.level else "-",
                     table_file_name(role.name) if role.selected else "no",
                     len(data.rows) if data is not None else "-", role.reason])
    selected = [table_file_name(name) for name in result.data.tables]
    text = (f"{_plural(len(selected), 'tabella riceve', 'tabelle ricevono')} un CSV: "
            f"{_join_words(selected) if selected else 'nessuna'}.")
    meaning = ("Una tabella riceve un CSV quando il journey o la entry query la leggono. Una tabella a livello di "
               "contatto ha una riga per contatto. Una tabella a livello di scenario ha una riga per scenario, "
               "condivisa dai suoi contatti.")
    return "\n\n".join(["## Tabelle", text, meaning,
                        _md_table(["Tabella", "Ruolo", "Livello", "CSV", "Righe", "Motivo"], rows)])


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
    """Spec: "The tester imports the entry CSV directly, together with the CSVs of the linked tables";
    "One scenario at a time"; "Data is read live". The user's decision: the entry table is filled by the
    direct import only, and no automation runs during the test."""
    model = result.table_model
    entry_csv = table_file_name(model.entry_table)
    others = [name for name in context.csv_names if name != entry_csv]
    automation = _entry_procedures(result)
    parts = ["### Come eseguire i test"]
    if others:
        parts.append(f"Importa prima {_join_words(others)}, poi {entry_csv}, così ogni riga che serve a un contatto è "
                     "già presente quando entra.")
    else:
        parts.append(f"Importa {entry_csv}.")
    if automation:
        parts.append(f"Assunzione da verificare al primo run reale: l'ingresso in questo journey è pianificato "
                     f"dall'automation {automation}. Per una entry source di tipo data extension pianificata da "
                     "un'automation, Salesforce potrebbe richiedere il passo di ingresso nel journey di "
                     "quell'automation perché i contatti importati entrino. docs/assumptions.md descrive questa "
                     "assunzione nelle righe da 23 a 27.")
    if context.one_active and context.first_scenario is not None:
        table, field = context.activation_ref
        key_column = _scenario_key_column(context, table)
        row = f" La riga di uno scenario è quella in cui {key_column} è la chiave dello scenario." if key_column else ""
        parts.append("Esegui uno scenario alla volta, in ordine di esecuzione. Gli scenari con un'azione manuale "
                     "vengono per primi, perché la loro scadenza è una data e un'ora fisse. Per rendere attivo uno "
                     f"scenario, imposta {field} in {table} a True sulla riga dello scenario e a False su tutte le "
                     f"altre righe.{row}")
        parts.append(_numbered([
            f"I CSV partono con {context.first_scenario.key} come scenario attivo, quindi il primo run non richiede "
            "modifiche.",
            "Aspetta che i contatti di uno scenario siano usciti dal journey.",
            "Poi rendi attivo lo scenario successivo. Non cambiare altro e non reimportare nulla, perché il journey "
            "legge queste righe mentre i contatti sono al suo interno.",
        ]))
        if automation and _activation_is_entry_filter(result, context.activation_ref):
            parts.append(f"{field} è un filtro della entry query e nessuno split lo legge, quindi con l'import "
                         "diretto non trattiene alcuno scenario.")
    elif result.coverage.scenarios:
        parts.append("Nei CSV tutti gli scenari sono attivi, quindi vengono eseguiti insieme.")
    parts.extend(_contact_address_text(result))
    for case in result.coverage.cases:
        smallest = _smallest_branch(case)
        if case.random is None or smallest is None:
            continue
        journey = result.package.journey
        parts.append(f"Il caso statistico {case.id} ha {len(case.contact_keys)} contatti per il random split "
                     f"{_activity_label(journey, case.random.activity_key)}. Ogni contatto prende un branch a caso. "
                     f"L'intervallo accettato è da {case.random.expected_low} a {case.random.expected_high} contatti "
                     f"sul branch {_branch_label(journey, case.random.activity_key, smallest)}.")
    return "\n\n".join(parts)


def _contact_address_text(result: GenerationResult) -> list[str]:
    """Spec, "Email": the real inbox with plus-addressing for contacts that must open or click; an
    undeliverable address for all others."""
    kinds = _unique(action.kind for case in result.coverage.cases for action in case.manual_actions)
    actions = _join_words(_ACTION_INFINITIVE.get(kind, kind) for kind in kinds).replace(" e ", " o ") if kinds else ""
    inbox = result.settings.real_inbox.strip()
    real = [contact for contact in result.data.contacts if contact.uses_real_inbox]
    undeliverable = f"un indirizzo non recapitabile che termina con @{UNDELIVERABLE_DOMAIN}"
    if kinds and inbox and real:
        return [f"I contatti che devono {actions} un'email ricevono l'inbox reale {inbox} con plus-addressing, per "
                f"esempio {real[0].email}. Tutti gli altri contatti ricevono {undeliverable}."]
    if kinds:
        return [f"Non è stata indicata un'inbox reale. I contatti che devono {actions} un'email ricevono "
                f"{undeliverable}, quindi quei branch non sono coperti."]
    if result.data.contacts:
        return [f"Nessun contatto deve aprire o cliccare un'email, quindi tutti i contatti ricevono {undeliverable}."]
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
        scenario_rows.append([scenario.key, scenario.run_order, "sì" if active else "no",
                              str(bool(scenario.has_manual_action)), str(bool(scenario.is_statistical)),
                              len(scenario.cases), len(keys),
                              f"da {keys[0] if keys else '-'} a {keys[-1] if keys else '-'}",
                              "; ".join(items) or "nessuno"])
    list_intro = "Gli scenari in ordine di esecuzione, come in scenarios.csv."
    if one_table:
        list_intro += f" I valori sono campi di {one_table}."
    case_rows = []
    for scenario in _ordered_scenarios(result):
        for case in scenario.cases:
            if case.random is not None:
                smallest = _smallest_branch(case)
                label = _branch_label(journey, case.random.activity_key, smallest) if smallest else "?"
                special = (f"random split {_activity_label(journey, case.random.activity_key)}: "
                           f"da {case.random.expected_low} a {case.random.expected_high} contatti attesi sul "
                           f"branch {label}")
            else:
                actions = []
                for action in case.manual_actions:
                    deadline = _deadline(context, scenario, case, action)
                    when = f"prima del {deadline}" if deadline else "appena arriva"
                    actions.append(f"{action.kind} di '{action.email_name}' {when}")
                special = "; ".join(actions)
            case_rows.append([case.id, scenario.key, len(case.contact_keys), _key_range(case.contact_keys),
                              special or "nessuna", _activity_label(journey, case.end_activity_key),
                              _case_summary(context, case)])
    cases_intro = "Un caso è un gruppo di contatti con lo stesso risultato atteso."
    if TESTBOOK_FILE in result.files:
        cases_intro += f" Ogni caso è un test di {TESTBOOK_FILE}, con lo stesso nome."
    return "\n\n".join([
        "## Scenari",
        _how_to_run(result, context),
        "### Elenco degli scenari",
        list_intro,
        _md_table(["Scenario", "Ordine di esecuzione", "Attivo all'inizio", "Azione manuale", "Statistico", "Casi",
                   "Contatti", "Chiavi dei contatti", "Valori"], scenario_rows),
        "### Casi",
        cases_intro,
        _md_table(["Caso", "Scenario", "Contatti", "Chiavi dei contatti", "Azione manuale o random split",
                   "Ultima attività", "Sintesi"], case_rows),
    ])


def _root_text(journey: Journey, root: tuple[str, str], branches: list[BranchStatus],
               by_ref: dict) -> str:
    """One line per root cause: "N branch si trovano a valle di 'split: outcome' (KEY), che non è raggiungibile
    perché ..."."""
    activity = journey.activities.get(root[0])
    name = (activity.name or root[0]) if activity is not None else root[0]
    label = _outcome_label(journey, root[0], root[1])
    status = by_ref.get(root)
    reason = status.reason if status is not None and status.reason else ""
    if not reason:
        inherited = _REASON_BEHIND_BRANCH.match(branches[0].reason or "")
        reason = inherited.group("reason") if inherited else ""
    state, clause = _explain_reason(reason, journey, root[0], root[1])
    count = _lie_behind(len(branches))
    if state is None:
        tail = f"che non è coperto: {clause}" if clause else "che non è coperto"
    else:
        tail = f"che {_STATE_WORDS.get(state, state)} perché {clause}"
    return f"{count} a valle di '{name}: {label}' ({root[0]}), {tail.rstrip('.')}."


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
            entry = f"{key} per {_join_words(repr(_outcome_label(journey, key, o)) for o in keys)}"
        name = (activity.name or key) if activity is not None else key
        by_name.setdefault(name, []).append(entry)
    count = len(outcomes)
    which = "questo split" if count == 1 else f"questi {count} split"
    lead = f"Sono tutti i branch di {which}:" if complete else f"Sono branch di {which}:"
    items = []
    for name, keys in by_name.items():
        keys = sorted(keys, key=_natural_key)
        items.append(", ".join(keys) if name in keys else f"{name}: {', '.join(keys)}")
    return lead + "\n\n" + _bullets(items)


def _section_not_covered(result: GenerationResult) -> str:
    journey = result.package.journey
    missing = [b for b in result.coverage.branches if b.status == STATUS_NOT_COVERED]
    if not missing:
        return "## Branch non coperti\n\nTutti i branch sono coperti."
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
        causes.append(_plural(len(behind_branch), "branch che nessun contatto può raggiungere",
                              "branch che nessun contatto può raggiungere"))
    if behind_unsupported:
        causes.append(_plural(len(behind_unsupported), "elemento non supportato", "elementi non supportati"))
    intro = f"{_plural(len(missing), 'branch non è coperto', 'branch non sono coperti')}."
    if grouped and own:
        intro += (f" Di questi, {grouped} {'si trova' if grouped == 1 else 'si trovano'} a valle di "
                  f"{' o '.join(causes)}: le cause sono spiegate per prime. "
                  f"{'Il restante ha un motivo proprio' if len(own) == 1 else f'I restanti {len(own)} hanno ciascuno un motivo proprio'}, "
                  "indicato nella tabella alla fine.")
    elif grouped:
        intro += (f" {'Si trova' if grouped == 1 else 'Si trovano tutti'} a valle di {' o '.join(causes)}, come "
                  "spiegato di seguito.")
    parts = ["## Branch non coperti", intro]
    if grouped:
        parts.append("### Cause a monte")
        for root, branches in sorted(behind_branch.items(),
                                     key=lambda item: (-len(item[1]), _natural_key(item[0][0]), item[0][1])):
            parts.append(_root_text(journey, root, branches, by_ref))
            parts.append(_behind_list(journey, branches))
        for reason, branches in behind_unsupported.items():
            detail = _REASON_BEHIND_UNSUPPORTED.match(reason).group("detail")
            after = _REASON_AFTER_UNSUPPORTED.match(detail)
            count = len(branches)
            if after:
                text = (f"{count} branch {'viene' if count == 1 else 'vengono'} dopo il branch non supportato "
                        f"'{after.group('label')}' dello stesso split, quindi non "
                        f"{'viene mai valutato' if count == 1 else 'vengono mai valutati'}.")
            else:
                text = f"{_lie_behind(count)} a valle di un elemento non supportato: {detail.rstrip('.')}."
            parts.append(text + " Vedi la sezione Elementi non supportati.")
            parts.append(_behind_list(journey, branches))
    if own:
        rows = []
        for b in own:
            activity = f"{b.activity_name} ({b.activity_key})" if b.activity_name else b.activity_key
            outcome = b.outcome_label if b.outcome_label == b.outcome_key else f"{b.outcome_label} ({b.outcome_key})"
            text = _reason_sentence(b.reason, journey, b.activity_key, b.outcome_key)
            behind = behind_branch.get((b.activity_key, b.outcome_key))
            if behind:
                below = "si trova 1 branch" if len(behind) == 1 else f"si trovano {len(behind)} branch"
                text += f" A valle di questo branch {below}."
            rows.append([activity, outcome, text])
        if grouped:
            parts.append("### Branch con un motivo proprio")
        parts.append(_md_table(["Attività", "Branch", "Motivo"], rows))
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
    parts = ["## Branch coperti con un'azione manuale o tramite un random split"]
    if manual:
        rows = [[f"{_activity_name(journey, b.activity_key)} ({b.activity_key})", b.outcome_label,
                 ", ".join(b.covered_by)] for b in manual]
        covered = "è coperto" if len(manual) == 1 else "sono coperti"
        parts.append(f"{len(manual)} branch {covered} solo da contatti che devono aprire o cliccare un'email. Il "
                     "testbook indica l'azione e la sua scadenza.")
        parts.append(_md_table(["Attività", "Branch", "Casi"], rows))
    if statistical:
        rows = [[f"{_activity_name(journey, b.activity_key)} ({b.activity_key})", b.outcome_label,
                 ", ".join(b.covered_by)] for b in statistical]
        crossed = "viene attraversato" if len(statistical) == 1 else "vengono attraversati"
        parts.append(f"{len(statistical)} branch {crossed} solo dopo un random split, dai contatti di un caso "
                     "statistico. Il testbook indica l'intervallo accettato.")
        parts.append(_md_table(["Attività", "Branch", "Casi"], rows))
    return "\n\n".join(parts)


def _section_unsupported(result: GenerationResult) -> str:
    journey = result.package.journey
    items = []
    for key in _unique(list(result.package.unsupported_activities) + list(result.coverage.unsupported)):
        activity = journey.activities.get(key)
        label = _activity_label(journey, key)
        reason = getattr(activity, "unsupported_reason", None) if activity is not None else None
        if reason:
            items.append(f"L'attività {label} non è supportata: {reason.rstrip('.')}. I suoi branch e quelli a valle "
                         "non sono coperti.")
        elif activity is not None:
            items.append(f"L'attività {label} è di tipo {activity.raw_type}, che il generatore non supporta. I suoi "
                         "branch e quelli a valle non sono coperti.")
        else:
            items.append(f"L'attività {key} non è supportata. I branch a valle non sono coperti.")
    query = result.table_model.entry_query
    if query is not None:
        for flt in query.filters:
            if isinstance(flt, UnsupportedFilter):
                items.append(f"Il filtro `{flt.text}` della entry query non è supportato, quindi le righe generate "
                             "potrebbero non soddisfarlo.")
    items.extend(f"Placeholder: {_sentence(text)}" for text in result.data.placeholders)
    if not items:
        return "## Elementi non supportati\n\nNon è stato trovato alcun elemento non supportato."
    return "\n\n".join(["## Elementi non supportati", _bullets(items)])


def _key_list(text: str) -> list[str]:
    """Activity keys written as ``A, B, C``, in natural order."""
    return sorted((key.strip() for key in text.split(",") if key.strip()), key=_natural_key)


def _case_line(matches: list[re.Match], tail: str, package: Package) -> str:
    """Fields compared with one value written in several letter cases."""
    values = _join_words(_quoted_values(matches[0].group("values"))) or matches[0].group("values")
    refs = _ordered_refs(package, [(m.group("table"), m.group("field")) for m in matches])
    if len(refs) == 1:
        text = f"{refs[0][0]}.{refs[0][1]} viene confrontato con {values}."
    elif len({table.lower() for table, _ in refs}) == 1:
        text = f"{_join_words(field for _, field in refs)} di {refs[0][0]} vengono confrontati ciascuno con {values}."
    else:
        text = f"{_join_words(f'{table}.{field}' for table, field in refs)} vengono confrontati ciascuno con {values}."
    if tail:
        text += f" {_CASE_TAILS.get(tail, _sentence(tail))} Come li confronta Salesforce è un'assunzione da verificare."
    return text


def _same_name_line(matches: list[re.Match]) -> str:
    """Splits that share a name but test different conditions."""
    groups = [f"'{m.group('name')}' in {m.group('count')} versioni, comparse per la prima volta in "
              f"{_join_words(_key_list(m.group('keys')))}" for m in matches]
    return "Alcuni split con lo stesso nome verificano condizioni diverse: " + "; ".join(groups) + "."


def _constant_key_line(matches: list[re.Match]) -> str:
    """Update contact steps that write a constant into a primary-key field."""
    steps = [_key_list(m.group("keys")) for m in matches]
    tables = {m.group("table") for m in matches}
    if all(keys == steps[0] for keys in steps) and len(tables) == 1:
        first = matches[0]
        if len(matches) == 1:
            what = (f"la costante {first.group('value')} nel campo di chiave primaria "
                    f"{first.group('table')}.{first.group('field')}")
        else:
            writes = _join_words(f"{m.group('value')} in {m.group('field')}" for m in matches)
            what = f"costanti nei campi di chiave primaria di {first.group('table')}: {writes}"
        count = _plural(len(steps[0]), "attività Update contact scrive", "attività Update contact scrivono")
        same = "lo stesso valore in quel campo" if len(matches) == 1 else "gli stessi valori in quei campi"
        which = "L'attività è" if len(steps[0]) == 1 else "Le attività sono"
        return f"{count} {what}. Quindi tutti i contatti hanno {same}. {which} {_join_words(steps[0])}."
    parts = [f"{m.group('value')} in {m.group('table')}.{m.group('field')}, da {_join_words(keys)}"
             for m, keys in zip(matches, steps)]
    return ("Alcune attività Update contact scrivono costanti in campi di chiave primaria, quindi tutti i contatti "
            "hanno lo stesso valore in quei campi: " + "; ".join(parts) + ".")


def _one_to_one_line(matches: list[re.Match]) -> str:
    """One-to-one relationships that join on part of a primary key."""
    parts = [f"'{m.group('name')}' collega {m.group('table')} tramite {m.group('fields')}, ma la chiave primaria di "
             f"{m.group('table')} comprende anche {_join_words(k.strip() for k in m.group('extra').split(','))}"
             for m in matches]
    lead = ("Una relazione uno a uno collega una tabella" if len(parts) == 1
            else "Alcune relazioni uno a uno collegano una tabella")
    return (f"{lead} su una parte della sua chiave primaria, quindi a un contatto possono corrispondere più righe: "
            + "; ".join(parts) + ".")


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
    return (f"La entry query seleziona {_plural(len(columns), 'colonna', 'colonne')} che {match.group('table')} non "
            f"ha: {_join_words(columns)}. Il generatore {'la' if len(columns) == 1 else 'le'} ignora. Cosa fa "
            "Salesforce con una query del genere è un'assunzione da verificare, elencata nella sezione Assunzioni.")


def _section_warnings(result: GenerationResult) -> str:
    query = result.table_model.entry_query
    sources = [
        ("Lettura dell'export", result.package.warnings),
        ("Selezione delle tabelle e SQL", list(result.table_model.warnings) + (list(query.warnings) if query else [])),
        ("Coverage", result.coverage.warnings),
        ("Generazione dei dati", result.data.warnings),
    ]
    patterns: list[str] = []
    groups: list[tuple[str, list[str]]] = []
    for title, warnings in sources:
        found, others = _split_suspicious(warnings)
        patterns.extend(found)
        groups.append((title, [_reword_warning(warning, result) for warning in others]))
    patterns = _merge_patterns(_unique(patterns), result.package)
    parts = ["## Warning e pattern sospetti"]
    for title, items in [("Pattern sospetti", patterns)] + groups:
        items = _unique(_sentence(item) for item in items)
        if items:
            parts.append(f"### {title}\n\n{_bullets(items)}")
    if len(parts) == 1:
        parts.append("Nessun warning.")
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
        case_text = ("I confronti di testo non distinguono maiuscole e minuscole, quindi `Email` e `EMAIL` sono lo "
                     "stesso valore. L'impostazione che ignora maiuscole e minuscole è attiva.")
    else:
        case_text = ("I confronti di testo distinguono maiuscole e minuscole, quindi `Email` e `EMAIL` sono valori "
                     "diversi. L'impostazione che ignora maiuscole e minuscole è disattivata.")
    zones = sorted({a.wait_timezone for a in result.package.journey.activities.values()
                    if a.kind == KIND_WAIT_ATTRIBUTE and a.wait_timezone})
    zone_text = (f" I wait by attribute di questo journey sono impostati sul fuso orario {_join_words(zones)}."
                 if zones else "")
    items = [
        "I branch di un decision split vengono valutati in ordine e vince il primo la cui condizione è soddisfatta.",
        case_text,
        "Un wait by attribute la cui data è già passata termina subito.",
        f"L'import accetta date scritte come {_date(result.generation_time, settings)}, nel formato "
        f"{_human_date_format(settings.date_format)}, e `True` e `False` per i Boolean.",
        "Un engagement split viene valutato quando il contatto lo raggiunge, non quando l'email viene inviata.",
        "Il fuso orario applicato alla data del wait non è noto, quindi le scadenze del testbook potrebbero "
        f"spostarsi di qualche ora.{zone_text}",
    ]
    automation = _entry_procedures(result)
    if automation:
        items.append(f"L'import diretto di {table_file_name(result.table_model.entry_table)} fa entrare i suoi "
                     f"contatti. L'ingresso in questo journey è pianificato dall'automation {automation} e la review "
                     "Salesforce indica che potrebbe servire il passo di ingresso nel journey di quell'automation. "
                     "Vedi la sezione Come eseguire i test.")
    ignored = _ignored_entry_columns(result)
    if ignored and result.table_model.entry_query is not None:
        items.append(f"La entry query {result.table_model.entry_query.name} viene eseguita anche se seleziona "
                     f"{_plural(len(ignored), 'colonna', 'colonne')} che {result.table_model.entry_table} non ha. "
                     f"Il generatore ignora {'quella colonna' if len(ignored) == 1 else 'quelle colonne'}.")
    return "\n\n".join([
        "## Assunzioni",
        "I risultati attesi dipendono da queste assunzioni sul comportamento di Salesforce. Verifica ciascuna una "
        "volta con un piccolo run reale. Il file docs/assumptions.md del repository CJ Test Helper le elenca tutte, "
        "con il modo di verificarle e quali controllare per prime.",
        _bullets(items),
    ])


_SETTING_LABELS = {
    "contacts_per_case": "Contatti per caso",
    "contacts_per_random_case": "Contatti per caso di random split",
    "real_inbox": "Inbox reale per i test di open e click",
    "real_phone": "Numero di telefono reale",
    "fake_phone": "Numero di telefono fittizio",
    "window_start_days": "Inizio della finestra di validità",
    "window_end_days": "Fine della finestra di validità",
    "wait_offset_hours": "Offset della data di wait",
    "wait_offset_before_engagement_hours": "Offset della data di wait prima di un engagement split",
    "date_format": "Formato delle date nei CSV",
    "one_active_scenario": "Un solo scenario attivo alla volta",
    "activation_field": "Campo di attivazione",
    "run_id": "Run identifier nelle chiavi",
    "case_insensitive_text": "I confronti di testo ignorano maiuscole e minuscole",
    "seed": "Seed del set cover",
    "generation_time": "Ora di generazione",
}


def _days_text(days: int) -> str:
    if days == 0:
        return "l'ora di generazione"
    side = "prima" if days < 0 else "dopo"
    return f"{_plural(abs(days), 'giorno', 'giorni')} {side} dell'ora di generazione"


def _setting_text(name: str, value, result: GenerationResult) -> str:
    if name == "generation_time":
        return _date(result.generation_time, result.settings)
    if name == "one_active_scenario" and value is None:
        return "sì, quando viene rilevato un campo di attivazione"
    if name == "activation_field" and value is None:
        return "suggerito dai filtri della entry query"
    if name in ("window_start_days", "window_end_days") and isinstance(value, int):
        return _days_text(value)
    if name in ("wait_offset_hours", "wait_offset_before_engagement_hours") and isinstance(value, int):
        return _plural(value, "ora", "ore")
    if name == "date_format" and isinstance(value, str):
        return _human_date_format(value)
    if value is None or value == "":
        return "nessuno"
    if isinstance(value, bool):
        return "sì" if value else "no"
    if isinstance(value, tuple):
        return ".".join(str(part) for part in value)
    return str(value)


def _section_settings(result: GenerationResult) -> str:
    rows = [[_SETTING_LABELS.get(f.name, f.name), _setting_text(f.name, getattr(result.settings, f.name), result)]
            for f in dataclasses.fields(result.settings)]
    on, ref, _ = activation_setting(result.package, result.table_model, result.settings)
    rows.append(["Un solo scenario attivo alla volta, come applicato",
                 f"sì, campo di attivazione {ref[0]}.{ref[1]}" if on else "no"])
    return "\n\n".join(["## Impostazioni usate", _md_table(["Impostazione", "Valore"], rows)])


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
