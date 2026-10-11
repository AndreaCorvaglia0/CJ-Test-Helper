"""The one-page Streamlit app (spec priority 5, "The app").

Spec: "The app is a single Streamlit page run locally, with no login and nothing stored: the file is
processed in memory and discarded. The tester goes through four steps on the same page":

1. Upload the package export JSON.
2. Review what was detected: journey name, number of activities by type, the tables with their role,
   and any warnings.
3. Adjust settings if needed; every setting has a default.
4. Generate, look at the summary and a preview of each CSV, then download the zip.

Spec, "Behaviour at the edges": "A file that is not valid JSON, or holds no journey, gives a plain
error message and nothing else."

The page is a thin layer ("Code structure": the Streamlit page is a thin layer on top of the
package). Every decision comes from the package: ``loader`` and ``tables`` for what was detected,
``model.Settings`` for the defaults, ``pipeline.generate`` for the files and checks, the generated
rows (``scenarios.csv``) for the active scenario and its activation field, ``outputs`` for reading
the CSVs back, for the file names and for the zip. This module only turns their results into
widgets and text. The look follows docs/ux-review.md.

Run it with ``streamlit run cjhelper/app.py`` from the repository root, so that
``.streamlit/config.toml`` applies. ``main()`` draws the title and step 1 and passes the uploaded
bytes to ``render()``, which draws steps 2 to 4; the tests drive ``render()`` directly.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
import traceback
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

import streamlit as st

# ``streamlit run cjhelper/app.py`` runs this file as a script, with only cjhelper/ on the path.
_ROOT = str(Path(__file__).resolve().parent.parent)
if not __package__ and _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cjhelper import loader, outputs, pipeline, tables  # noqa: E402
from cjhelper.loader import LoadError  # noqa: E402
from cjhelper.model import (  # noqa: E402
    KIND_DECISION,
    KIND_EMAIL,
    KIND_ENGAGEMENT,
    KIND_RANDOM,
    KIND_UNSUPPORTED,
    KIND_UPDATE,
    KIND_WAIT_ATTRIBUTE,
    KIND_WAIT_DURATION,
    KIND_WAIT_STO,
    STATUS_NOT_COVERED,
    FieldRef,
    GenerationResult,
    Journey,
    Package,
    Settings,
    TableModel,
)

LOG = logging.getLogger(__name__)

TITLE = "CJ Test Helper"
DESCRIPTION = "Upload a Marketing Cloud package export and download CSV test data for every branch of its journey."
STEP_UPLOAD = "1. Upload the package export"
STEP_REVIEW = "2. Review what was detected"
STEP_SETTINGS = "3. Adjust the settings"
STEP_GENERATE = "4. Generate and download"
UPLOAD_LABEL = "Package export (JSON)"
UPLOAD_NOTE = ("The JSON file that Package Manager exports for the journey. It is read in memory and discarded; "
               "nothing is stored.")
GENERATE_LABEL = "Generate"
GENERATE_NOTE = "Generation can take about a minute. The result appears below when it is done."
SPINNER_TEXT = "Generating the test data. This can take about a minute."
DOWNLOAD_LABEL = "Download the zip"
MORE_SETTINGS = "More settings"
TECHNICAL_DETAILS = "Technical details"

# Spec, "Behaviour at the edges": a plain message; it ends with what to do next.
NEXT_STEP = "Choose the JSON file that Package Manager produces."
UNEXPECTED_READ = "The file could not be read because of an unexpected error in the generator."
UNEXPECTED_GENERATION = "The test data could not be generated because of an unexpected error in the generator."

PREVIEW_ROWS = 10        # first rows of each CSV shown in step 4
DETAIL_LIMIT = 20        # details shown under a failed trust check

DETECTION_KEY = "cjhelper.detection"   # st.session_state: (file digest, DetectionSummary)
RESULT_KEY = "cjhelper.result"         # st.session_state: StoredRun of the last generation
PENDING_KEY = "cjhelper.pending"       # st.session_state: (file digest, Settings) from the Generate click to the run that generates

# Plain names of the activity kinds, in the order of the spec's "Supported in the PoC" table.
ACTIVITY_NAMES: dict[str, str] = {
    KIND_DECISION: "Decision split",
    KIND_ENGAGEMENT: "Engagement split",
    KIND_RANDOM: "Random split",
    KIND_WAIT_DURATION: "Wait by duration",
    KIND_WAIT_ATTRIBUTE: "Wait by attribute",
    KIND_WAIT_STO: "Send-time wait",
    KIND_EMAIL: "Email",
    KIND_UPDATE: "Update contact",
    KIND_UNSUPPORTED: "Unsupported",
}

# The spec's settings, with the wording report.md uses for "Settings used".
SETTING_LABELS: dict[str, str] = {
    "contacts_per_case": "Contacts per case",
    "contacts_per_random_case": "Contacts per random-split case",
    "real_inbox": "Real inbox for open and click tests",
    "real_phone": "Real phone number",
    "fake_phone": "Fake phone number",
    "window_start_days": "Validity window start (days from the generation time)",
    "window_end_days": "Validity window end (days from the generation time)",
    "wait_offset_hours": "Wait date offset (hours)",
    "wait_offset_before_engagement_hours": "Wait date offset before an engagement split (hours)",
    "date_format": "Date format in the CSVs",
    "one_active_scenario": "One active scenario at a time",
    "activation_field": "Activation field",
    "run_id": "Run identifier in keys",
    "case_insensitive_text": "Text comparisons ignore letter case",
}
NUMBER_SETTINGS = ("contacts_per_case", "contacts_per_random_case", "window_start_days", "window_end_days",
                   "wait_offset_hours", "wait_offset_before_engagement_hours")
TEXT_SETTINGS = ("real_inbox", "real_phone", "fake_phone", "run_id")

# Visible notes under a field (spec wording where it has some).
SETTING_NOTES: dict[str, str] = {
    "real_inbox": ("Contacts that must open or click an email get this inbox with plus-addressing. Left empty, "
                   "they get undeliverable addresses and those branches are reported as not covered."),
    "run_id": ("Added to every key, for example TST_R01_C0001. Use a new one for each generation, so that the "
               "evidence of two runs does not mix."),
    "real_phone": "Not used: none of the activity types the generator supports sends a message to a phone.",
}
SETTING_HELP: dict[str, str] = {
    "fake_phone": "The clearly fake number written for every contact.",
    "wait_offset_hours": "Wait-by-attribute dates are the generation time plus this offset, so 0 ends the wait at once.",
    "wait_offset_before_engagement_hours": ("For a wait-by-attribute on the path to an engagement split: "
                                            "time left to open the email."),
    "activation_field": ("A Boolean field of a scenario-level table. When one active scenario at a time is on, "
                         "only the first scenario is active in the CSVs."),
    "case_insensitive_text": ("Whether Salesforce treats Email and EMAIL as the same value is still to be "
                              "verified; off treats them as different."),
}
DEFAULT_DATE_PATTERN = "YYYY-MM-DD HH:MM"     # how the spec writes the default date format

# What each file of the zip is for (spec, "Outputs").
FILE_PURPOSES: dict[str, str] = {
    outputs.SCENARIOS_FILE: "the scenarios in run order, with the one active at the start",
    outputs.TESTBOOK_FILE: "the tests and their expected results",
    outputs.REPORT_FILE: "what is covered, what is not and why, and how to run the tests",
}

# Text shown with st.markdown is escaped, so that names such as _Sent or values with * stay plain.
_MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()<>#+\-.!|~$:&@])")
_FILE_NAME_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
_PARENTHESES = re.compile(r"\s*\(([^()]*)\)")
_LIST_SEPARATOR = re.compile(r",\s*|\s+and\s+")


# ---------------------------------------------------------------------------
# What step 2 shows (load and table model only, no generation)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TableLine:
    """One table of the export as step 2 shows it, in the words of report.md's Tables section."""
    name: str
    role: str              # report.md's role names, e.g. "source, split", "written", "none"
    level: str             # "contact", "scenario", or "-" for a table without a CSV
    csv: bool              # gets a CSV


@dataclass
class DetectionSummary:
    """Spec, step 2: "journey name, number of activities by type, the tables with their role, and any warnings"."""
    journey_name: str
    activity_count: int
    activities: list[tuple[str, int]]      # (plain activity type, count), in the spec's order
    tables: list[TableLine]                # the tables that get a CSV first, then the others
    csv_files: list[str]                   # file names of the tables that get a CSV
    warnings: list[str]                    # from loading and table selection, one plain line each
    ids_left_out: bool                     # some warnings named activities that only report.md lists
    activation_field: Optional[FieldRef]   # suggested from the entry query filters, or None
    activation_choices: list[FieldRef]     # Boolean fields of the scenario-level tables


def activity_counts(journey: Journey) -> list[tuple[str, int]]:
    """Number of activities of each kind present in the journey, with plain names, in the spec's order."""
    counts = Counter(activity.kind for activity in journey.activities.values())
    known = [kind for kind in ACTIVITY_NAMES if counts[kind]]
    others = sorted(kind for kind in counts if kind not in ACTIVITY_NAMES)
    return [(ACTIVITY_NAMES.get(kind, kind), counts[kind]) for kind in known + others]


def role_text(roles: Iterable[str]) -> str:
    """The roles of a table as report.md writes them, e.g. ``{"split", "source"}`` -> "source, split"."""
    return ", ".join(sorted(roles)) or "none"


def table_lines(table_model: TableModel) -> list[TableLine]:
    """Spec, step 2: "the tables with their role"; the tables that get a CSV come first."""
    lines = [TableLine(name=role.name, role=role_text(role.roles),
                       level=(role.level or "-") if role.selected else "-", csv=role.selected)
             for role in table_model.tables.values()]
    return [line for line in lines if line.csv] + [line for line in lines if not line.csv]


def activation_choices(package: Package, table_model: TableModel) -> list[FieldRef]:
    """The fields that can be the activation field: the Boolean fields of the scenario-level tables.

    The suggestion of the table model comes first if it is not among them, so it can always be chosen.
    """
    choices: list[FieldRef] = []
    for name in table_model.scenario_tables:
        table = package.tables.get(name)
        if table is not None:
            choices.extend((table.name, f.name) for f in table.fields if f.type.lower() == "boolean")
    suggested = table_model.activation_field
    if suggested is not None and suggested not in choices:
        choices.insert(0, suggested)
    return choices


def warning_lines(warnings: Iterable[str], activity_keys: Iterable[str]) -> tuple[list[str], bool]:
    """One sentence-case line per warning, suspicious patterns first, as report.md orders them.

    A list of activity keys in parentheses is left to report.md, which names them; the second value
    says whether that happened. Suspicious patterns are marked by other modules with the prefix
    ``outputs.SUSPICIOUS_PREFIX``.
    """
    keys = set(activity_keys)
    patterns: list[str] = []
    others: list[str] = []
    left_out = False
    for warning in _unique(_one_line(w) for w in warnings):
        text, removed = _without_key_lists(warning, keys)
        left_out = left_out or removed
        if text.lower().startswith(outputs.SUSPICIOUS_PREFIX):
            rest = text[len(outputs.SUSPICIOUS_PREFIX):].strip()
            patterns.append(f"Suspicious pattern: {rest}")
        else:
            others.append(text[:1].upper() + text[1:])
    return patterns + others, left_out


def summarize_detection(package: Package, table_model: TableModel) -> DetectionSummary:
    lines, left_out = warning_lines(list(package.warnings) + list(table_model.warnings), package.journey.activities)
    return DetectionSummary(
        journey_name=package.journey.name,
        activity_count=package.journey.activity_count,
        activities=activity_counts(package.journey),
        tables=table_lines(table_model),
        csv_files=[outputs.table_file_name(name) for name in table_model.selected_tables],
        warnings=lines,
        ids_left_out=left_out,
        activation_field=table_model.activation_field,
        activation_choices=activation_choices(package, table_model),
    )


def load_summary(data: bytes) -> DetectionSummary:
    """Read the export and select its tables, without generating anything. Raises LoadError."""
    package = loader.load_package(data)
    return summarize_detection(package, tables.build_table_model(package))


# ---------------------------------------------------------------------------
# Settings (step 3)
# ---------------------------------------------------------------------------

def default_form_values(activation_field: Optional[FieldRef]) -> dict[str, Any]:
    """The value each setting widget starts with: the spec defaults, which are ``Settings()``'s.

    Spec settings table: "One active scenario at a time: On when an activation field is detected";
    "Activation field: Suggested from the entry query filters" (``activation_field``, or None).
    """
    defaults = Settings()
    values = {name: getattr(defaults, name) for name in SETTING_LABELS}
    values["one_active_scenario"] = activation_field is not None
    values["activation_field"] = activation_field
    return values


def settings_from_form(values: Mapping[str, Any]) -> Settings:
    """Map the values of the settings widgets to ``Settings``.

    Numbers become integers and the one-line texts lose surrounding spaces; the date format is kept as
    typed. The activation field only applies when one active scenario at a time is on. The settings
    that the spec does not list (seed, generation time) keep their defaults.
    """
    one_active = bool(values["one_active_scenario"])
    activation = values.get("activation_field") if one_active else None
    return Settings(
        **{name: int(values[name]) for name in NUMBER_SETTINGS},
        **{name: str(values[name] or "").strip() for name in TEXT_SETTINGS},
        date_format=str(values["date_format"]),
        one_active_scenario=one_active,
        activation_field=tuple(activation) if activation else None,
        case_insensitive_text=bool(values["case_insensitive_text"]),
    )


def days_text(days: int) -> str:
    """A validity window bound in words, as report.md's "Settings used" writes it."""
    if days == 0:
        return "At the generation time."
    side = "before" if days < 0 else "after"
    return f"{_count(abs(days), 'day', 'days')} {side} the generation time."


def date_format_note(now: datetime) -> str:
    default = Settings().date_format
    return f"By default, dates are written as {DEFAULT_DATE_PATTERN}, for example {now.strftime(default)}."


# ---------------------------------------------------------------------------
# What step 4 shows
# ---------------------------------------------------------------------------

@dataclass
class StoredRun:
    """The last generation, kept in st.session_state so that a download does not generate again."""
    digest: str                                 # of the uploaded bytes it was generated from
    settings: Settings                          # it was generated with
    result: Optional[GenerationResult] = None   # None when it failed
    zip_bytes: bytes = b""
    error: str = ""                             # one plain sentence when it failed
    details: str = ""                           # the exception and where it happened


def done_line(result: GenerationResult) -> str:
    text = f"Done at {result.generation_time:%H:%M}"
    run_id = result.settings.run_id
    return f"{text}, run identifier {run_id}." if run_id else f"{text}."


def summary_rows(result: GenerationResult) -> list[tuple[str, int]]:
    """Spec, "Outputs": "number of scenarios, cases and contacts, and branches covered, covered with manual
    action, and not covered" (the counts of the coverage, as in report.md and the command line)."""
    stats = result.coverage.stats
    return [
        ("Scenarios", stats.get("scenarios", 0)),
        ("Cases", stats.get("cases", 0)),
        ("Contacts", stats.get("contacts", 0)),
        ("Branches covered", stats.get("covered", 0)),
        ("Branches covered with manual action", stats.get("covered_manual", 0)),
        ("Branches not covered", stats.get("not_covered", 0)),
    ]


def summary_notes(result: GenerationResult) -> list[str]:
    """Plain sentences under the counts.

    - The branches not covered that lie behind another branch (``BranchStatus.behind``, the root cause
      report.md groups them by), so that the count does not read as a failure.
    - Spec, "Behaviour at the edges": "If the real inbox is empty, generation still works. The open and
      click contacts get undeliverable addresses, and those branches are reported as not covered."
    """
    notes: list[str] = []
    missing = [b for b in result.coverage.branches if b.status == STATUS_NOT_COVERED]
    behind = [b for b in missing if b.behind is not None]
    if behind:
        roots = {tuple(b.behind) for b in behind}
        verb = "lies" if len(behind) == 1 else "lie"
        notes.append(f"{len(behind)} of the {_count(len(missing), 'branch', 'branches')} not covered {verb} behind "
                     f"{_count(len(roots), 'branch', 'branches')} that no contact can reach. report.md explains "
                     "why, under Branches not covered.")
    elif missing:
        notes.append("report.md gives the reason for each branch not covered.")
    kinds = _unique(action.kind for case in result.coverage.cases for action in case.manual_actions)
    if kinds and not result.settings.real_inbox.strip():
        notes.append(f"No real inbox was given, so the contacts that must {_join_words(kinds, 'or')} an email get "
                     "undeliverable addresses and those branches are reported as not covered.")
    return notes


def import_notes(result: GenerationResult) -> list[str]:
    """Spec, "One scenario at a time" and "Data is read live", in the words of report.md's How to run.

    The active scenario and its activation field come from the generated scenarios.csv rows.
    """
    notes = [f"Open {outputs.REPORT_FILE} first: its How to run section gives the import order."]
    rows = result.data.scenarios_rows
    active = [row for row in rows if str(row.get("active_at_start", "")).lower() == "yes"]
    field = next((row.get("activation_field") for row in rows if row.get("activation_field")), None)
    if field and len(active) == 1:
        notes.append(f"Only {active[0].get('scenario_key')}, the first scenario in run order, is active in the CSVs.")
        notes.append(f"Run the scenarios one at a time, in run order. When the contacts of a scenario have left the "
                     f"journey, make the next one active: set {field} to True on its row and to False on every "
                     "other row. Change nothing else and import nothing again.")
    elif rows:
        notes.append("Every scenario is active in the CSVs, so the scenarios run together.")
    return notes


def generation_warnings(result: GenerationResult) -> tuple[list[str], bool]:
    """Warnings of the coverage and of the data generation (step 2 already showed the others). The
    missing real inbox is said in the summary instead (``summary_notes``)."""
    inbox_note = any(note.startswith("No real inbox") for note in summary_notes(result))
    warnings = [w for w in list(result.coverage.warnings) + list(result.data.warnings)
                if not (inbox_note and w.startswith("No real inbox"))]
    return warning_lines(warnings, result.package.journey.activities)


def csv_preview(content: bytes, limit: int = PREVIEW_ROWS) -> tuple[dict[str, list[str]], int]:
    """The first ``limit`` rows of a written CSV as {column: values}, exactly as written (an empty cell
    stays empty), and the number of rows."""
    header, rows = outputs.read_csv(content)
    shown = rows[:limit]
    columns = {name: ["" if row.get(name) is None else str(row[name]) for row in shown] for name in header}
    return columns, len(rows)


def preview_files(result: GenerationResult) -> list[str]:
    """The CSVs of the zip, scenarios.csv first because it is the run plan."""
    names = [name for name in result.files if name.lower().endswith(".csv")]
    return sorted(names, key=lambda name: name != outputs.SCENARIOS_FILE)


def download_lines(result: GenerationResult) -> list[str]:
    """Spec, "Outputs": what each file of the zip is for."""
    data_files = [name for name in result.files if name.lower().endswith(".csv") and name not in FILE_PURPOSES]
    lines = []
    if data_files:
        lines.append(f"{_join_words(data_files)}: the data to import.")
    for name in result.files:
        if name in FILE_PURPOSES:
            lines.append(f"{name}: {FILE_PURPOSES[name]}.")
        elif name not in data_files:
            lines.append(f"{name}.")
    return lines


def zip_file_name(journey_name: str) -> str:
    """``<journey name>_test_data.zip``; characters a file name cannot hold become ``_``."""
    safe = _FILE_NAME_UNSAFE.sub("_", journey_name).strip(" .")
    return f"{safe or 'journey'}_test_data.zip"


# ---------------------------------------------------------------------------
# Error messages
# ---------------------------------------------------------------------------

def is_file_error(error: BaseException) -> bool:
    """The errors that say something about the file: not valid JSON, not UTF-8, no journey, no entry table."""
    return isinstance(error, (LoadError, json.JSONDecodeError, UnicodeDecodeError))


def error_message(error: BaseException) -> str:
    """Plain words for a file that cannot be read, ending with what to do next.

    Spec, "Behaviour at the edges": "A file that is not valid JSON, or holds no journey, gives a plain
    error message and nothing else." LoadError already says why in plain words; for a JSON error the
    position comes from the parser's error that LoadError replaced.
    """
    if not is_file_error(error):
        return UNEXPECTED_READ
    parse_error = error if isinstance(error, json.JSONDecodeError) else _json_error_behind(error)
    if parse_error is not None:
        text = f"The file is not valid JSON: there is a problem at line {parse_error.lineno}, column {parse_error.colno}."
    elif isinstance(error, UnicodeDecodeError):
        text = "The file is not UTF-8 text, so it is not a valid JSON package export."
    else:
        text = str(error).strip() or "The file could not be read as a package export."
    if not text.endswith("."):
        text += "."
    return f"{text} {NEXT_STEP}"


def technical_details(error: BaseException) -> str:
    return "".join(traceback.format_exception(type(error), error, error.__traceback__)).strip()


def _json_error_behind(error: BaseException) -> Optional[json.JSONDecodeError]:
    for cause in (error.__cause__, error.__context__):
        if isinstance(cause, json.JSONDecodeError):
            return cause
    return None


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

def main() -> None:
    """Title, description and step 1; the uploaded bytes go to ``render``."""
    st.set_page_config(page_title=TITLE)
    st.title(TITLE)
    st.write(DESCRIPTION)
    st.header(STEP_UPLOAD)
    uploaded = st.file_uploader(UPLOAD_LABEL)
    st.caption(_md(UPLOAD_NOTE))
    render(uploaded.getvalue() if uploaded is not None else None)


def render(data: Optional[bytes]) -> None:
    """Steps 2 to 4 for the uploaded bytes (None: no file, so nothing to show).

    Generate takes three short runs of the page, so that its button is disabled while it works: the
    click keeps the settings as pending, the next run shows the button disabled and generates, and a
    last run shows the result with the button enabled again. (Streamlit ignores a click on a button
    that is drawn disabled in the same run, so the click and the generation cannot share one run.)
    """
    if data is None:
        _forget()
        return
    try:
        digest, summary = _detection(data)
    except Exception as error:   # spec: a plain error message and nothing else
        _forget()
        if is_file_error(error):
            st.error(_md(error_message(error)))
        else:
            LOG.exception("The export could not be read")
            _show_failure(UNEXPECTED_READ, technical_details(error))
        return
    _show_detection(summary)
    pending = st.session_state.get(PENDING_KEY)
    running = pending is not None and pending[0] == digest
    settings, submitted = _settings_form(summary, running)
    if submitted:
        st.session_state.pop(RESULT_KEY, None)
        st.session_state[PENDING_KEY] = (digest, settings)
        st.rerun()
    if running:
        st.session_state.pop(PENDING_KEY, None)
        _generate(data, digest, pending[1])
    stored = st.session_state.get(RESULT_KEY)
    if stored is not None and stored.digest == digest and stored.settings == settings:
        if stored.result is None:
            _show_failure(stored.error, stored.details)
        else:
            render_result(stored.result, stored.zip_bytes)


def render_result(result: GenerationResult, zip_bytes: bytes) -> None:
    """Step 4 after a generation: done line, summary, what to do before importing, trust checks, a
    preview of each CSV, the download, then the warnings of the generation."""
    st.markdown(_md(done_line(result)))

    _label("Summary")
    st.markdown(_markdown_table(["Item", "Count"], summary_rows(result), right=(1,)))
    for note in summary_notes(result):
        st.markdown(_md(note))

    _label("Before you import")
    _show_list(import_notes(result), empty="")

    _label("Trust checks")
    checks = result.checks
    passed = sum(1 for check in checks if check.passed)
    st.markdown(f"{passed} of {_count(len(checks), 'trust check', 'trust checks')} passed.")
    lines: list[str] = []
    for check in checks:
        lines.append(f"- {'Passed' if check.passed else 'Failed'}: {_md(_one_line(check.name))}")
        if not check.passed:
            lines.extend(f"    - {_md(_one_line(detail))}" for detail in check.details[:DETAIL_LIMIT])
            if len(check.details) > DETAIL_LIMIT:
                lines.append(f"    - and {len(check.details) - DETAIL_LIMIT} more")
    if lines:
        st.markdown("\n".join(lines))

    _label("Preview of the CSVs")
    for name in preview_files(result):
        columns, total = csv_preview(result.files[name])
        title = f"{name}: the run plan" if name == outputs.SCENARIOS_FILE else name
        with st.expander(_md(f"{title} ({_count(total, 'row', 'rows')})")):
            if total > PREVIEW_ROWS:
                st.caption(f"The first {PREVIEW_ROWS} of {total} rows.")
            # A static table: a preview holds only its first rows, so it offers no CSV download of its own.
            st.table({_md(column): [_md(value) for value in values] for column, values in columns.items()},
                     hide_index=True, hide_header=False)

    _label("Download")
    file_name = zip_file_name(result.package.journey.name)
    st.markdown(_md(f"{file_name} holds {_count(len(result.files), 'file', 'files')}:"))
    _show_list(download_lines(result), empty="")
    st.download_button(DOWNLOAD_LABEL, data=zip_bytes, file_name=file_name, mime="application/zip", type="primary")

    warnings, left_out = generation_warnings(result)
    _label("Warnings from the generation")
    _show_list(warnings, empty="No warnings.")
    if left_out:
        st.markdown(_md(f"{outputs.REPORT_FILE} lists the activities concerned."))


def _detection(data: bytes) -> tuple[str, DetectionSummary]:
    """Step 2 for these bytes, read once per file: a new file drops what the previous one gave."""
    digest = hashlib.sha256(data).hexdigest()
    cached = st.session_state.get(DETECTION_KEY)
    if cached is not None and cached[0] == digest:
        return cached
    _forget()
    summary = load_summary(data)
    st.session_state[DETECTION_KEY] = (digest, summary)
    return digest, summary


def _forget() -> None:
    """Nothing is kept once the file is gone or replaced."""
    st.session_state.pop(DETECTION_KEY, None)
    st.session_state.pop(RESULT_KEY, None)
    st.session_state.pop(PENDING_KEY, None)


def _show_detection(summary: DetectionSummary) -> None:
    st.header(STEP_REVIEW)
    st.markdown(_md(f"The export holds the journey {summary.journey_name}, with "
                    f"{_count(summary.activity_count, 'activity', 'activities')}."))
    _label("Activities by type")
    st.markdown(_markdown_table(["Activity type", "Count"], summary.activities, right=(1,)))
    _label("Tables")
    files = summary.csv_files
    st.markdown(_md(f"{_count(len(files), 'table gets', 'tables get')} a CSV: "
                    f"{_join_words(files) if files else 'none'}."))
    rows = [(line.name, line.role, line.level, "yes" if line.csv else "no") for line in summary.tables]
    st.markdown(_markdown_table(["Table", "Role", "Level", "CSV"], rows))
    _label("Warnings found in the export")
    _show_list(summary.warnings, empty="No warnings.")
    if summary.ids_left_out:
        st.markdown(_md(f"{outputs.REPORT_FILE} lists the activities concerned once the test data is generated."))


def _settings_form(summary: DetectionSummary, running: bool) -> tuple[Settings, bool]:
    """Step 3 in a form whose submit button is step 4's Generate, so the settings apply together.

    The real inbox and the run identifier come first; the other settings wait in a closed expander.
    The Generate button is disabled while a generation runs (``running``).
    """
    st.header(STEP_SETTINGS)
    defaults = default_form_values(summary.activation_field)
    values: dict[str, Any] = {}
    with st.form("settings", border=False):
        values["real_inbox"] = _text("real_inbox", defaults, placeholder="name@domain")
        st.caption(_md(SETTING_NOTES["real_inbox"]))
        values["run_id"] = _text("run_id", defaults)
        st.caption(_md(SETTING_NOTES["run_id"]))
        with st.expander(MORE_SETTINGS):
            _label("Contacts")
            left, right = st.columns(2, vertical_alignment="bottom")
            with left:
                values["contacts_per_case"] = _number("contacts_per_case", defaults, min_value=1)
            with right:
                values["contacts_per_random_case"] = _number("contacts_per_random_case", defaults, min_value=1)
            _label("Contact details")
            values["real_phone"] = _text("real_phone", defaults)
            st.caption(_md(SETTING_NOTES["real_phone"]))
            values["fake_phone"] = _text("fake_phone", defaults)
            _label("Dates")
            left, right = st.columns(2, vertical_alignment="bottom")
            with left:
                values["window_start_days"] = _number("window_start_days", defaults)
                st.caption(_md(days_text(int(values["window_start_days"]))))
            with right:
                values["window_end_days"] = _number("window_end_days", defaults)
                st.caption(_md(days_text(int(values["window_end_days"]))))
            left, right = st.columns(2, vertical_alignment="bottom")
            with left:
                values["wait_offset_hours"] = _number("wait_offset_hours", defaults)
            with right:
                values["wait_offset_before_engagement_hours"] = _number("wait_offset_before_engagement_hours",
                                                                        defaults)
            values["date_format"] = _text("date_format", defaults)
            st.caption(_md(date_format_note(datetime.now())))
            _label("Scenarios")
            values["one_active_scenario"] = st.checkbox(SETTING_LABELS["one_active_scenario"],
                                                        value=defaults["one_active_scenario"],
                                                        disabled=not summary.activation_choices)
            st.caption(_md(_activation_note(summary)))
            values["activation_field"] = None
            if summary.activation_choices:
                choices = summary.activation_choices
                suggested = summary.activation_field
                values["activation_field"] = st.selectbox(
                    SETTING_LABELS["activation_field"], choices, format_func=_field_text,
                    index=choices.index(suggested) if suggested in choices else None,
                    placeholder="Choose a field", help=SETTING_HELP["activation_field"])
            values["case_insensitive_text"] = st.checkbox(SETTING_LABELS["case_insensitive_text"],
                                                          value=defaults["case_insensitive_text"],
                                                          help=SETTING_HELP["case_insensitive_text"])
        st.header(STEP_GENERATE)
        submitted = st.form_submit_button(GENERATE_LABEL, type="primary", disabled=running)
        st.caption(GENERATE_NOTE)
    return settings_from_form(values), submitted


def _number(name: str, defaults: Mapping[str, Any], min_value: Optional[int] = None) -> int:
    return st.number_input(SETTING_LABELS[name], value=defaults[name], min_value=min_value, step=1,
                           help=SETTING_HELP.get(name))


def _text(name: str, defaults: Mapping[str, Any], placeholder: Optional[str] = None) -> str:
    return st.text_input(SETTING_LABELS[name], value=defaults[name], placeholder=placeholder,
                         help=SETTING_HELP.get(name))


def _activation_note(summary: DetectionSummary) -> str:
    if summary.activation_field is not None:
        return (f"Activation field detected in the entry query filters: {_field_text(summary.activation_field)}. "
                "Turn this off to make every scenario active in the CSV.")
    if summary.activation_choices:
        return "No activation field was detected in the entry query filters."
    return "No activation field was detected, and no scenario-level table has a Boolean field."


def _generate(data: bytes, digest: str, settings: Settings) -> None:
    """Spec, step 4: generate from the bytes in memory; the result is kept for this session only.

    The page then runs once more, so that the Generate button is enabled again under the result.
    """
    try:
        with st.spinner(SPINNER_TEXT):
            result = pipeline.generate(data, settings)
            zip_bytes = outputs.build_zip(result.files)
        stored = StoredRun(digest, settings, result=result, zip_bytes=zip_bytes)
    except Exception as error:   # one plain sentence on the page, the details in a closed expander
        LOG.exception("The generation failed")
        stored = StoredRun(digest, settings, error=UNEXPECTED_GENERATION, details=technical_details(error))
    st.session_state[RESULT_KEY] = stored
    st.rerun()


def _show_failure(message: str, details: str) -> None:
    st.error(_md(message))
    with st.expander(TECHNICAL_DETAILS):
        st.code(details, language=None)


# ---------------------------------------------------------------------------
# Small text helpers
# ---------------------------------------------------------------------------

def _md(text: str) -> str:
    """Text shown through Markdown exactly as written: Markdown characters are escaped."""
    return _MARKDOWN_SPECIAL.sub(r"\\\1", text)


def _one_line(text: str) -> str:
    return " ".join(str(text).split())


def _label(text: str) -> None:
    """A label at body size: the four numbered steps are the only headings."""
    st.markdown(f"**{_md(text)}**")


def _show_list(items: list[str], empty: str) -> None:
    if items:
        st.markdown("\n".join(f"- {_md(_one_line(item))}" for item in items))
    elif empty:
        st.markdown(empty)


def _markdown_table(header: list[str], rows: Iterable[Iterable[Any]], right: tuple[int, ...] = ()) -> str:
    def line(cells: Iterable[Any]) -> str:
        return "| " + " | ".join(_md(_one_line(str(cell))) for cell in cells) + " |"
    rule = "| " + " | ".join("---:" if i in right else "---" for i in range(len(header))) + " |"
    return "\n".join([line(header), rule] + [line(row) for row in rows])


def _without_key_lists(text: str, keys: set[str]) -> tuple[str, bool]:
    """Drop parenthesised lists of two or more activity keys, which report.md names in full."""
    removed = False

    def replace(match: re.Match) -> str:
        nonlocal removed
        items = [item.strip() for item in _LIST_SEPARATOR.split(match.group(1)) if item.strip()]
        if len(items) >= 2 and all(item in keys for item in items):
            removed = True
            return ""
        return match.group(0)

    return _PARENTHESES.sub(replace, text), removed


def _field_text(ref: FieldRef) -> str:
    return f"{ref[0]}.{ref[1]}"


def _count(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _join_words(items: list[str], last: str = "and") -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" {last} " + items[-1]


def _unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))


if __name__ == "__main__":
    main()
