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
``model.Settings`` for the defaults, ``pipeline.generate`` for the files and checks, ``outputs`` for
reading the CSVs back and for the zip. This module only turns their results into widgets and text.

Run it with ``streamlit run cjhelper/app.py``. ``main()`` draws the title and step 1 and passes the
uploaded bytes to ``render()``, which draws steps 2 to 4; the tests drive ``render()`` directly.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
from collections import Counter
from dataclasses import dataclass
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
    LEVEL_CONTACT,
    LEVEL_SCENARIO,
    ROLE_ENTRY,
    ROLE_SOURCE,
    ROLE_SPLIT,
    ROLE_WRITTEN,
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
STEP_GENERATE = "4. Generate"
UPLOAD_LABEL = "Package export (JSON)"
GENERATE_LABEL = "Generate"
DOWNLOAD_LABEL = "Download the zip"

PREVIEW_ROWS = 10        # first rows of each CSV shown in step 4
DETAIL_LIMIT = 20        # details shown under a failed trust check

DETECTION_KEY = "cjhelper.detection"   # st.session_state: (file digest, DetectionSummary)
RESULT_KEY = "cjhelper.result"         # st.session_state: StoredResult of the last generation

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

# Spec, "Table selection": entry, split and source tables get a CSV; written-only tables do not.
ROLE_NAMES: dict[str, str] = {
    ROLE_ENTRY: "entry",
    ROLE_SPLIT: "split",
    ROLE_SOURCE: "source",
    ROLE_WRITTEN: "written only",
}
LEVEL_NAMES: dict[str, str] = {LEVEL_CONTACT: "Contact", LEVEL_SCENARIO: "Scenario"}

# The spec's settings table, in its order, with the wording report.md uses for "Settings used".
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

SETTING_HELP: dict[str, str] = {
    "real_inbox": ("Contacts that must open or click an email get this inbox with plus-addressing. "
                   "Left empty, they get undeliverable addresses and those branches are reported as not covered."),
    "real_phone": ("In each case whose path sends a message to a phone, one contact gets this number. "
                   "Left empty, every contact gets the fake number."),
    "fake_phone": "The clearly fake number written for every other contact.",
    "window_start_days": "Date-range filter of the entry query. The default window starts yesterday.",
    "window_end_days": "Date-range filter of the entry query. The default window ends in 7 days.",
    "wait_offset_hours": "Wait-by-attribute dates are the generation time plus this offset, so 0 ends the wait at once.",
    "wait_offset_before_engagement_hours": ("For a wait-by-attribute on the path to an engagement split: "
                                            "time left to open the email."),
    "activation_field": ("A Boolean field of a scenario-level table. When one active scenario at a time is on, "
                         "only the first scenario is active in the CSV."),
    "run_id": "Added to every key, for example TST_R01_C0001. Use a new one for each generation.",
    "case_insensitive_text": ("Whether Salesforce treats Email and EMAIL as the same value is still to be "
                              "verified; off treats them as different."),
}
DATE_FORMAT_NOTE = "The default, %Y-%m-%d %H:%M, writes dates as YYYY-MM-DD HH:MM."

# Text shown with st.markdown is escaped, so that names such as _Sent or values with * stay plain.
_MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()<>#+\-.!|~$:&@])")
_FILE_NAME_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


# ---------------------------------------------------------------------------
# What step 2 shows (load and table model only, no generation)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TableLine:
    """One table of the export as step 2 shows it."""
    name: str
    role: str              # plain words, e.g. "Split and source", "Written only", "None"
    level: str             # "Contact", "Scenario", or "-" for a table without a CSV
    csv: bool              # gets a CSV


@dataclass
class DetectionSummary:
    """Spec, step 2: "journey name, number of activities by type, the tables with their role, and any warnings"."""
    journey_name: str
    activity_count: int
    activities: list[tuple[str, int]]      # (plain activity type, count), in the spec's order
    tables: list[TableLine]                # every table of the export, in table-model order
    warnings: list[str]                    # from loading and table selection
    activation_field: Optional[FieldRef]   # suggested from the entry query filters, or None
    activation_choices: list[FieldRef]     # Boolean fields of the scenario-level tables


def activity_counts(journey: Journey) -> list[tuple[str, int]]:
    """Number of activities of each kind present in the journey, with plain names, in the spec's order."""
    counts = Counter(activity.kind for activity in journey.activities.values())
    known = [kind for kind in ACTIVITY_NAMES if counts[kind]]
    others = sorted(kind for kind in counts if kind not in ACTIVITY_NAMES)
    return [(ACTIVITY_NAMES.get(kind, kind), counts[kind]) for kind in known + others]


def role_text(roles: Iterable[str]) -> str:
    """The roles of a table in plain words, e.g. ``{"split", "source"}`` -> "Split and source"."""
    roles = set(roles)
    names = [ROLE_NAMES[role] for role in ROLE_NAMES if role in roles]
    names += sorted(role for role in roles if role not in ROLE_NAMES)
    if not names:
        return "None"
    text = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return text[:1].upper() + text[1:]


def table_lines(table_model: TableModel) -> list[TableLine]:
    """Spec, step 2: "the tables with their role"; level and CSV come from the table model."""
    return [TableLine(name=role.name, role=role_text(role.roles),
                      level=LEVEL_NAMES.get(role.level or "", role.level or "-") if role.selected else "-",
                      csv=role.selected)
            for role in table_model.tables.values()]


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


def summarize_detection(package: Package, table_model: TableModel) -> DetectionSummary:
    return DetectionSummary(
        journey_name=package.journey.name,
        activity_count=package.journey.activity_count,
        activities=activity_counts(package.journey),
        tables=table_lines(table_model),
        warnings=_unique(list(package.warnings) + list(table_model.warnings)),
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


# ---------------------------------------------------------------------------
# What step 4 shows
# ---------------------------------------------------------------------------

@dataclass
class StoredResult:
    """The last generation, kept in st.session_state so that a download does not generate again."""
    digest: str            # of the uploaded bytes it was generated from
    settings: Settings     # it was generated with
    result: GenerationResult
    zip_bytes: bytes


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


def generation_warnings(result: GenerationResult) -> list[str]:
    """Warnings of the coverage and of the data generation (step 2 already showed the others)."""
    warnings = _unique(list(result.coverage.warnings) + list(result.data.warnings))
    return [warning[:1].upper() + warning[1:] for warning in warnings]


def csv_preview(content: bytes, limit: int = PREVIEW_ROWS) -> tuple[dict[str, list[str]], int]:
    """The first ``limit`` rows of a written CSV as {column: values}, exactly as written (an empty cell
    stays empty), and the number of rows."""
    header, rows = outputs.read_csv(content)
    shown = rows[:limit]
    columns = {name: ["" if row.get(name) is None else str(row[name]) for row in shown] for name in header}
    return columns, len(rows)


def zip_file_name(journey_name: str) -> str:
    """``<journey name>_test_data.zip``; characters a file name cannot hold become ``_``."""
    safe = _FILE_NAME_UNSAFE.sub("_", journey_name).strip(" .")
    return f"{safe or 'journey'}_test_data.zip"


# ---------------------------------------------------------------------------
# Error messages
# ---------------------------------------------------------------------------

def error_message(error: BaseException) -> str:
    """One plain sentence for a file that cannot be read.

    Spec, "Behaviour at the edges": "A file that is not valid JSON, or holds no journey, gives a plain
    error message and nothing else." LoadError already says why in plain words.
    """
    if isinstance(error, LoadError):
        return str(error).strip() or "The file could not be read as a package export."
    if isinstance(error, json.JSONDecodeError):
        return f"The file is not valid JSON ({error.msg} at line {error.lineno}, column {error.colno})."
    if isinstance(error, UnicodeDecodeError):
        return "The file is not UTF-8 text, so it is not a valid JSON package export."
    return f"The file could not be read as a package export ({type(error).__name__}: {error})."


def generation_error_message(error: BaseException) -> str:
    detail = str(error).strip().rstrip(".") or type(error).__name__
    return f"The generation failed: {detail}."


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

def main() -> None:
    """Title, description and step 1; the uploaded bytes go to ``render``."""
    st.set_page_config(page_title=TITLE)
    st.title(TITLE)
    st.write(DESCRIPTION)
    st.header(STEP_UPLOAD)
    uploaded = st.file_uploader(UPLOAD_LABEL, type=["json"],
                                help="The file is read in memory and discarded; nothing is stored.")
    render(uploaded.getvalue() if uploaded is not None else None)


def render(data: Optional[bytes]) -> None:
    """Steps 2 to 4 for the uploaded bytes (None: no file, so nothing to show)."""
    if data is None:
        _forget()
        return
    try:
        digest, summary = _detection(data)
    except Exception as error:   # spec: a plain error message and nothing else
        if not isinstance(error, (LoadError, ValueError)):
            LOG.exception("The export could not be read")
        _forget()
        st.error(_md(error_message(error)))
        return
    _show_detection(summary)
    settings, submitted = _settings_form(summary)
    if submitted:
        _generate(data, digest, settings)
    stored = st.session_state.get(RESULT_KEY)
    if stored is not None and stored.digest == digest and stored.settings == settings:
        render_result(stored.result, stored.zip_bytes)


def render_result(result: GenerationResult, zip_bytes: bytes) -> None:
    """Step 4 after a generation: summary, trust checks, a preview of each CSV, warnings, download."""
    st.subheader("Summary")
    st.markdown(_markdown_table(["Item", "Count"], summary_rows(result), right=(1,)))

    st.subheader("Trust checks")
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

    st.subheader("Preview of the CSVs")
    for name, content in result.files.items():
        if not name.lower().endswith(".csv"):
            continue
        columns, total = csv_preview(content)
        shown = _count(total, "row", "rows") if total <= PREVIEW_ROWS else f"{total} rows, the first {PREVIEW_ROWS} shown"
        st.markdown(f"**{_md(name)}**: {shown}")
        st.dataframe(columns, hide_index=True)

    st.subheader("Warnings")
    _show_list(generation_warnings(result), empty="No warnings.")

    st.subheader("Download")
    file_name = zip_file_name(result.package.journey.name)
    names = list(result.files)
    st.markdown(_md(f"{file_name} holds {_count(len(names), 'file', 'files')}: {_join_words(names)}."))
    st.download_button(DOWNLOAD_LABEL, data=zip_bytes, file_name=file_name, mime="application/zip")


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


def _show_detection(summary: DetectionSummary) -> None:
    st.header(STEP_REVIEW)
    st.markdown(_md(f"The export holds the journey {summary.journey_name}, with "
                    f"{_count(summary.activity_count, 'activity', 'activities')}."))
    st.subheader("Activities by type")
    st.markdown(_markdown_table(["Activity type", "Count"], summary.activities, right=(1,)))
    st.subheader("Tables")
    rows = [(line.name, line.role, line.level, "Yes" if line.csv else "No") for line in summary.tables]
    st.markdown(_markdown_table(["Table", "Role", "Level", "CSV"], rows))
    st.subheader("Warnings")
    _show_list(summary.warnings, empty="No warnings.")


def _settings_form(summary: DetectionSummary) -> tuple[Settings, bool]:
    """Step 3 in a form whose submit button is step 4's Generate, so the settings apply together."""
    st.header(STEP_SETTINGS)
    defaults = default_form_values(summary.activation_field)
    values: dict[str, Any] = {}
    with st.form("settings", border=False):
        values["contacts_per_case"] = _number("contacts_per_case", defaults, min_value=1)
        values["contacts_per_random_case"] = _number("contacts_per_random_case", defaults, min_value=1)
        values["real_inbox"] = _text("real_inbox", defaults, placeholder="name@domain")
        values["real_phone"] = _text("real_phone", defaults)
        values["fake_phone"] = _text("fake_phone", defaults)
        values["window_start_days"] = _number("window_start_days", defaults)
        values["window_end_days"] = _number("window_end_days", defaults)
        values["wait_offset_hours"] = _number("wait_offset_hours", defaults)
        values["wait_offset_before_engagement_hours"] = _number("wait_offset_before_engagement_hours", defaults)
        values["date_format"] = _text("date_format", defaults)
        st.caption(_md(DATE_FORMAT_NOTE))
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
        values["run_id"] = _text("run_id", defaults)
        values["case_insensitive_text"] = st.checkbox(SETTING_LABELS["case_insensitive_text"],
                                                      value=defaults["case_insensitive_text"],
                                                      help=SETTING_HELP["case_insensitive_text"])
        st.header(STEP_GENERATE)
        submitted = st.form_submit_button(GENERATE_LABEL)
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
    """Spec, step 4: generate from the bytes in memory; the result is kept for this session only."""
    st.session_state.pop(RESULT_KEY, None)
    error: Optional[Exception] = None
    with st.spinner("Generating the test data..."):
        try:
            result = pipeline.generate(data, settings)
            zip_bytes = outputs.build_zip(result.files)
        except Exception as exc:   # one plain sentence on the page, the traceback in the server log
            LOG.exception("The generation failed")
            error = exc
    if error is not None:
        st.error(_md(generation_error_message(error)))
        return
    st.session_state[RESULT_KEY] = StoredResult(digest, settings, result, zip_bytes)


# ---------------------------------------------------------------------------
# Small text helpers
# ---------------------------------------------------------------------------

def _md(text: str) -> str:
    """Text shown through st.markdown exactly as written: Markdown characters are escaped."""
    return _MARKDOWN_SPECIAL.sub(r"\\\1", text)


def _one_line(text: str) -> str:
    return " ".join(str(text).split())


def _show_list(items: list[str], empty: str) -> None:
    if items:
        st.markdown("\n".join(f"- {_md(_one_line(item))}" for item in items))
    else:
        st.markdown(empty)


def _markdown_table(header: list[str], rows: Iterable[Iterable[Any]], right: tuple[int, ...] = ()) -> str:
    def line(cells: Iterable[Any]) -> str:
        return "| " + " | ".join(_md(_one_line(str(cell))) for cell in cells) + " |"
    rule = "| " + " | ".join("---:" if i in right else "---" for i in range(len(header))) + " |"
    return "\n".join([line(header), rule] + [line(row) for row in rows])


def _field_text(ref: FieldRef) -> str:
    return f"{ref[0]}.{ref[1]}"


def _count(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _join_words(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))


if __name__ == "__main__":
    main()
