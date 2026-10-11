"""The one-page app (spec "The app"): the page through Streamlit's AppTest, and its helpers.

``AppTest.from_file`` runs the whole page (title, step 1 and the uploader); ``AppTest.from_function``
runs ``app.render(bytes)``, the steps below the uploader, with the bytes passed in. Step 4 is tested
with a stand-in generator that returns a small result at once; only one test runs the full
generation on the pilot (about 45 s), and it is marked ``slow``.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest, element_tree

from cjhelper import app, outputs, pipeline
from cjhelper.loader import LoadError
from cjhelper.model import STATUS_COVERED, STATUS_NOT_COVERED, CheckResult, Settings

ROOT = Path(__file__).resolve().parent.parent
APP_FILE = ROOT / "cjhelper" / "app.py"
PILOT = ROOT / "fixtures" / "CJ template complesso-v1.json"
PILOT_JOURNEY = "CJ_SkYDE_NCRM_Demo_final"
PILOT_CSV_TABLES = ["DE_NCM_AdHoc_Entry", "SF_Master_DataExtension_DE", "DE_NCRM_AD_HOC_CONFIG", "DE_NCRM_AdHoc_Target"]
PILOT_ACTIVATION = ("DE_NCRM_AD_HOC_CONFIG", "ACTIVE")
TIMEOUT = 60

needs_pilot = pytest.mark.skipif(not PILOT.exists(), reason="pilot export not present")
CAN_UPLOAD = hasattr(getattr(element_tree, "FileUploader", None), "set_value")   # AppTest drives st.file_uploader


def _render_page(data):
    """The page below the uploader, as AppTest.from_function runs it."""
    from cjhelper import app
    app.render(data)


def _result_page(result, zip_bytes):
    """Step 4's output alone, as AppTest.from_function runs it."""
    from cjhelper import app
    app.render_result(result, zip_bytes)


def _plain(markdown: str) -> str:
    """Undo the page's Markdown escaping."""
    return re.sub(r"\\([^A-Za-z0-9\s])", r"\1", markdown)


def _markdown(at) -> str:
    return "\n".join(_plain(m.value) for m in at.markdown)


def _captions(at) -> list[str]:
    return [_plain(c.value) for c in at.caption]


def _widget(widgets, label: str):
    found = [w for w in widgets if w.label == label]
    assert len(found) == 1, (label, [w.label for w in widgets])
    return found[0]


def _expander(at, label: str):
    found = [e for e in at.expander if _plain(e.label) == label]
    assert len(found) == 1, (label, [e.label for e in at.expander])
    return found[0]


def _step_content(at) -> list:
    """Everything a step after the upload would show."""
    return (list(at.header[1:]) + list(at.subheader) + list(at.get("dataframe")) + list(at.table)
            + list(at.button) + list(at.checkbox) + list(at.number_input) + list(at.text_input)
            + list(at.selectbox) + list(at.expander) + list(at.get("download_button")))


@pytest.fixture(scope="module")
def pilot_bytes() -> bytes:
    return PILOT.read_bytes()


# ---------------------------------------------------------------------------
# Step 1: upload, and the edges
# ---------------------------------------------------------------------------

def test_page_without_file_shows_the_upload_step_and_no_error():
    at = AppTest.from_file(str(APP_FILE)).run(timeout=TIMEOUT)
    assert not at.exception
    assert [t.value for t in at.title] == [app.TITLE]
    assert [h.value for h in at.header] == [app.STEP_UPLOAD]
    uploaders = at.get("file_uploader")
    assert len(uploaders) == 1 and uploaders[0].label == app.UPLOAD_LABEL
    assert _captions(at) == [app.UPLOAD_NOTE]          # visible, says where the file comes from
    assert not at.error
    assert not _step_content(at)


@pytest.mark.skipif(not CAN_UPLOAD, reason="this Streamlit's AppTest cannot drive st.file_uploader")
def test_the_uploader_takes_any_file_and_the_page_answers_with_one_sentence():
    at = AppTest.from_file(str(APP_FILE)).run(timeout=TIMEOUT)
    uploader = at.get("file_uploader")[0]
    assert uploader.allowed_type == []                  # no file-type filter: the page's own message answers
    uploader.set_value(("export.txt", b"just some notes", "text/plain")).run(timeout=TIMEOUT)
    assert not at.exception
    assert [_plain(e.value) for e in at.error] == [
        "The file is not valid JSON: there is a problem at line 1, column 1. " + app.NEXT_STEP]
    assert [h.value for h in at.header] == [app.STEP_UPLOAD]
    assert not _step_content(at)


@pytest.mark.parametrize("data, words", [
    (b"{not json", "The file is not valid JSON: there is a problem at line 1, column 2."),
    (b"", "The file is not valid JSON: there is a problem at line 1, column 1."),
    (b"[1, 2]", "a JSON object is expected."),
    (b'{"entities": {"dataExtensions": {}}}', "The export holds no journey."),
    (b'{"name": "x"}', "so it holds no journey."),
    (b"\xff\xfe\x00{", "The file is not UTF-8 text"),
])
def test_unreadable_file_shows_one_plain_error_and_nothing_else(data, words):
    at = AppTest.from_function(_render_page, args=(data,)).run(timeout=TIMEOUT)
    assert not at.exception
    assert len(at.error) == 1
    message = _plain(at.error[0].value)
    assert words in message and message.endswith(" " + app.NEXT_STEP) and "\n" not in message
    assert "Expecting" not in message
    assert not at.header and not at.markdown and not at.caption and not _step_content(at)


def test_without_a_file_nothing_is_kept():
    at = AppTest.from_function(_render_page, args=(None,))
    at.session_state[app.DETECTION_KEY] = ("digest", "summary")
    at.session_state[app.RESULT_KEY] = "result"
    at.session_state[app.PENDING_KEY] = ("digest", "settings")
    at.run(timeout=TIMEOUT)
    assert not at.exception
    for key in (app.DETECTION_KEY, app.RESULT_KEY, app.PENDING_KEY):
        assert key not in at.session_state
    assert not at.header and not at.error and not _step_content(at)


def test_error_messages_are_plain_and_end_with_the_next_step():
    assert app.error_message(LoadError("The export holds no journey.")) == (
        "The export holds no journey. Choose the JSON file that Package Manager produces.")
    with pytest.raises(LoadError) as not_json:
        from cjhelper import loader
        loader.load_package(b"{oops")
    assert app.error_message(not_json.value) == ("The file is not valid JSON: there is a problem at line 1, "
                                                 "column 2. " + app.NEXT_STEP)
    with pytest.raises(json.JSONDecodeError) as raw_json:
        json.loads("\n\n  ]")
    assert app.error_message(raw_json.value).startswith("The file is not valid JSON: there is a problem at line 3, "
                                                        "column 3.")
    with pytest.raises(UnicodeDecodeError) as not_text:
        b"\xff".decode("utf-8")
    assert app.error_message(not_text.value) == ("The file is not UTF-8 text, so it is not a valid JSON package "
                                                 "export. " + app.NEXT_STEP)
    assert app.is_file_error(LoadError("x")) and not app.is_file_error(KeyError("name"))
    assert app.error_message(KeyError("name")) == app.UNEXPECTED_READ
    try:
        {}["name"]
    except KeyError as error:
        details = app.technical_details(error)
    assert details.startswith("Traceback") and details.endswith("KeyError: 'name'")


@needs_pilot
def test_an_unexpected_error_while_reading_shows_a_sentence_and_closed_details(pilot_bytes, monkeypatch):
    def broken(package):
        raise AttributeError("'TableModel' object has no attribute 'x'")
    monkeypatch.setattr("cjhelper.tables.build_table_model", broken)
    at = AppTest.from_function(_render_page, args=(pilot_bytes,)).run(timeout=TIMEOUT)
    assert not at.exception
    assert [_plain(e.value) for e in at.error] == [app.UNEXPECTED_READ]
    details = _expander(at, app.TECHNICAL_DETAILS)
    assert details.proto.expanded is False
    assert "AttributeError: 'TableModel' object has no attribute 'x'" in details.code[0].value
    assert not at.header


# ---------------------------------------------------------------------------
# Step 2: what was detected
# ---------------------------------------------------------------------------

@needs_pilot
def test_detection_summary_on_pilot(pilot_bytes):
    summary = app.load_summary(pilot_bytes)
    assert summary.journey_name == PILOT_JOURNEY
    assert summary.activity_count == 178
    counts = dict(summary.activities)
    assert sum(counts.values()) == 178
    assert counts == {"Decision split": 106, "Engagement split": 6, "Random split": 1, "Wait by duration": 10,
                      "Wait by attribute": 3, "Send-time wait": 7, "Email": 11, "Update contact": 34}
    names = [line.name for line in summary.tables]
    assert sorted(names[:4]) == sorted(PILOT_CSV_TABLES)            # the tables that get a CSV come first
    assert all(line.csv for line in summary.tables[:4]) and not any(line.csv for line in summary.tables[4:])
    assert sorted(summary.csv_files) == sorted(f"{name}.csv" for name in PILOT_CSV_TABLES)
    lines = {line.name: line for line in summary.tables}
    assert (lines["DE_NCM_AdHoc_Entry"].role, lines["DE_NCM_AdHoc_Entry"].level) == ("entry", "contact")
    assert (lines["DE_NCRM_AD_HOC_CONFIG"].role, lines["DE_NCRM_AD_HOC_CONFIG"].level) == ("source, split", "scenario")
    assert lines["DE_NCRM_AdHoc_Target"].role == "source"
    assert lines["DE_SkyDE_AdHoc_Log_partial"] == app.TableLine("DE_SkyDE_AdHoc_Log_partial", "written", "-", False)
    assert summary.activation_field == PILOT_ACTIVATION
    assert PILOT_ACTIVATION in summary.activation_choices
    assert all(table == "DE_NCRM_AD_HOC_CONFIG" for table, _ in summary.activation_choices)
    patterns = [w for w in summary.warnings if w.startswith("Suspicious pattern: ")]
    assert patterns and summary.warnings[:len(patterns)] == patterns   # suspicious patterns first
    assert all(w[:1].isupper() for w in summary.warnings)
    assert not any("UPDATECONTACTDATAV2" in w for w in summary.warnings) and summary.ids_left_out


@needs_pilot
def test_detection_step_on_pilot_shows_journey_activities_and_the_four_csv_tables(pilot_bytes):
    at = AppTest.from_function(_render_page, args=(pilot_bytes,)).run(timeout=TIMEOUT)
    assert not at.exception and not at.error
    assert [h.value for h in at.header] == [app.STEP_REVIEW, app.STEP_SETTINGS, app.STEP_GENERATE]
    assert not at.subheader                              # the numbered steps are the only headings
    text = _markdown(at)
    assert f"The export holds the journey {PILOT_JOURNEY}, with 178 activities." in text
    for label in ("Activities by type", "Tables", "Warnings found in the export"):
        assert f"**{label}**" in text
    assert "| Decision split | 106 |" in text and "| Unsupported |" not in text
    assert re.search(r"^4 tables get a CSV: \S+\.csv, \S+\.csv, \S+\.csv and \S+\.csv\.$", text, flags=re.MULTILINE)
    rows = re.findall(r"^\| (\S+) \| ([^|]+) \| ([^|]+) \| (yes|no) \|$", text, flags=re.MULTILINE)
    assert sorted(name for name, _, _, csv in rows[:4] if csv == "yes") == sorted(PILOT_CSV_TABLES)
    assert ("DE_Check_Active_Campaigns", "written", "-", "no") in rows
    assert "- Suspicious pattern: 23 update contact step(s) write the constant 'DemoSKY'" in text
    assert "UPDATECONTACTDATAV2" not in text and "report.md lists the activities concerned" in text
    assert [b.label for b in at.button] == [app.GENERATE_LABEL]
    assert not at.get("download_button")      # nothing generated yet


def test_activity_counts_and_roles_use_plain_names():
    activities = {key: SimpleNamespace(kind=kind) for key, kind in
                  [("a", "decision"), ("b", "unsupported"), ("c", "decision"), ("d", "wait_sto"), ("e", "new_kind")]}
    journey = SimpleNamespace(activities=activities)
    assert app.activity_counts(journey) == [("Decision split", 2), ("Send-time wait", 1), ("Unsupported", 1),
                                            ("new_kind", 1)]
    assert app.role_text({"source", "split"}) == "source, split"      # as report.md writes it
    assert app.role_text({"written"}) == "written"
    assert app.role_text(set()) == "none"


def test_warning_lines_put_patterns_first_and_leave_key_lists_to_the_report():
    keys = ["SPLIT-1", "SPLIT-2", "UPDATE-1"]
    lines, left_out = app.warning_lines([
        "assets/1 has no value at 'data/x'.",
        "suspicious pattern: 2 different conditions share the split name 'Consent' (SPLIT-1, SPLIT-2)",
        "Decision split Consent (SPLIT-1) is reported as unsupported.",
        "suspicious pattern: 2 different conditions share the split name 'Consent' (SPLIT-1, SPLIT-2)",
        "the note (not keys, SPLIT-1) stays",
    ], keys)
    assert lines == ["Suspicious pattern: 2 different conditions share the split name 'Consent'",
                     "Assets/1 has no value at 'data/x'.",
                     "Decision split Consent (SPLIT-1) is reported as unsupported.",
                     "The note (not keys, SPLIT-1) stays"]
    assert left_out
    assert app.warning_lines(["One plain warning."], keys) == (["One plain warning."], False)


# ---------------------------------------------------------------------------
# Step 3: settings
# ---------------------------------------------------------------------------

def test_settings_mapping_gives_the_spec_defaults():
    settings = app.settings_from_form(app.default_form_values(PILOT_ACTIVATION))
    assert settings.contacts_per_case == 3
    assert settings.contacts_per_random_case == 50
    assert settings.real_inbox == "" and settings.real_phone == ""
    assert settings.fake_phone == "333333333333"
    assert (settings.window_start_days, settings.window_end_days) == (-1, 7)
    assert settings.wait_offset_hours == 0
    assert settings.wait_offset_before_engagement_hours == 24
    assert settings.date_format == "%Y-%m-%d %H:%M"
    assert settings.one_active_scenario is True and settings.activation_field == PILOT_ACTIVATION
    assert settings.run_id == "R01"
    assert settings.case_insensitive_text is False
    defaults = Settings()
    assert (settings.seed, settings.generation_time) == (defaults.seed, defaults.generation_time)


def test_settings_mapping_without_a_detected_activation_field_is_off():
    values = app.default_form_values(None)
    assert values["one_active_scenario"] is False and values["activation_field"] is None
    settings = app.settings_from_form(values)
    assert settings.one_active_scenario is False and settings.activation_field is None


def test_settings_mapping_reads_the_changed_values():
    values = app.default_form_values(PILOT_ACTIVATION)
    values.update(contacts_per_case=5.0, contacts_per_random_case=80, real_inbox="  tester@example.com ",
                  real_phone=" 3471234567", fake_phone="390000000000", window_start_days=-2, window_end_days=3,
                  wait_offset_hours=-1, wait_offset_before_engagement_hours=48, date_format="%d/%m/%Y %H:%M",
                  one_active_scenario=False, run_id=" R07 ", case_insensitive_text=True)
    settings = app.settings_from_form(values)
    assert settings == Settings(contacts_per_case=5, contacts_per_random_case=80, real_inbox="tester@example.com",
                                real_phone="3471234567", fake_phone="390000000000", window_start_days=-2,
                                window_end_days=3, wait_offset_hours=-1, wait_offset_before_engagement_hours=48,
                                date_format="%d/%m/%Y %H:%M", one_active_scenario=False, activation_field=None,
                                run_id="R07", case_insensitive_text=True)
    assert isinstance(settings.contacts_per_case, int)
    values.update(one_active_scenario=True, activation_field=("DE_NCRM_AD_HOC_CONFIG", "HAS_RUN"))
    assert app.settings_from_form(values).activation_field == ("DE_NCRM_AD_HOC_CONFIG", "HAS_RUN")


def test_settings_notes_in_words():
    assert app.days_text(-1) == "1 day before the generation time."
    assert app.days_text(7) == "7 days after the generation time."
    assert app.days_text(0) == "At the generation time."
    assert app.date_format_note(datetime(2026, 10, 11, 13, 45)) == (
        "By default, dates are written as YYYY-MM-DD HH:MM, for example 2026-10-11 13:45.")


@needs_pilot
def test_settings_start_at_the_spec_defaults_with_inbox_and_run_identifier_first(pilot_bytes):
    at = AppTest.from_function(_render_page, args=(pilot_bytes,)).run(timeout=TIMEOUT)
    labels = app.SETTING_LABELS
    assert [w.label for w in at.text_input][:2] == [labels["real_inbox"], labels["run_id"]]
    more = _expander(at, app.MORE_SETTINGS)
    assert more.proto.expanded is False
    numbers = {name: _widget(at.number_input, labels[name]).value for name in app.NUMBER_SETTINGS}
    assert numbers == {"contacts_per_case": 3, "contacts_per_random_case": 50, "window_start_days": -1,
                       "window_end_days": 7, "wait_offset_hours": 0, "wait_offset_before_engagement_hours": 24}
    assert {w.label for w in more.number_input} == {labels[name] for name in app.NUMBER_SETTINGS}
    texts = {name: _widget(at.text_input, labels[name]).value
             for name in ("real_inbox", "real_phone", "fake_phone", "date_format", "run_id")}
    assert texts == {"real_inbox": "", "real_phone": "", "fake_phone": "333333333333",
                     "date_format": "%Y-%m-%d %H:%M", "run_id": "R01"}
    captions = _captions(at)
    for note in (app.SETTING_NOTES["real_inbox"], app.SETTING_NOTES["run_id"], app.SETTING_NOTES["real_phone"],
                 "1 day before the generation time.", "7 days after the generation time.", app.GENERATE_NOTE):
        assert note in captions
    assert any(c.startswith("By default, dates are written as YYYY-MM-DD HH:MM, for example ") for c in captions)
    one_active = _widget(at.checkbox, labels["one_active_scenario"])
    assert one_active.value is True and not one_active.disabled
    assert any("detected in the entry query filters: DE_NCRM_AD_HOC_CONFIG.ACTIVE." in c for c in captions)
    activation = _widget(at.selectbox, labels["activation_field"])
    assert activation.value == PILOT_ACTIVATION
    assert "DE_NCRM_AD_HOC_CONFIG.HAS_RUN" in activation.options
    assert _widget(at.checkbox, labels["case_insensitive_text"]).value is False
    generate = _widget(at.button, app.GENERATE_LABEL)
    assert generate.proto.type == "primary" and not generate.disabled


# ---------------------------------------------------------------------------
# Step 4: the result
# ---------------------------------------------------------------------------

def _stub_result(checks=None, files=None, journey_name="CJ demo", real_inbox="", one_active=True):
    """The parts of a GenerationResult that step 4 reads."""
    rows = "".join(f"TST_R01_C{n:04d},,x_{n}\n" for n in range(1, 13)).encode()
    if files is None:
        files = {"DE_Entry.csv": b"ContactId,Email,Note\n" + rows,
                 "scenarios.csv": b"scenario_key,run_order\nTST_R01_S01,1\nTST_R01_S02,2\n",
                 "testbook.xlsx": b"xlsx", "report.md": b"# Report\n"}
    field = "DE_Config.ACTIVE" if one_active else None
    scenario_rows = [{"scenario_key": "TST_R01_S01", "active_at_start": "yes", "activation_field": field},
                     {"scenario_key": "TST_R01_S02", "active_at_start": "no" if one_active else "yes",
                      "activation_field": field}]
    branches = ([SimpleNamespace(status=STATUS_COVERED, behind=None)] * 4
                + [SimpleNamespace(status=STATUS_NOT_COVERED, behind=("SPLIT-1", "yes"))] * 2
                + [SimpleNamespace(status=STATUS_NOT_COVERED, behind=("SPLIT-2", "yes"))]
                + [SimpleNamespace(status=STATUS_NOT_COVERED, behind=None)])
    cases = [SimpleNamespace(manual_actions=[SimpleNamespace(kind="open")]), SimpleNamespace(manual_actions=[])]
    return SimpleNamespace(
        package=SimpleNamespace(journey=SimpleNamespace(name=journey_name, activities={"SPLIT-1": 1, "SPLIT-2": 2})),
        coverage=SimpleNamespace(stats={"scenarios": 2, "cases": 3, "contacts": 9, "covered": 4,
                                        "covered_manual": 1, "not_covered": 4},
                                 branches=branches, cases=cases,
                                 warnings=["suspicious pattern: T.F is compared with 'Email' and 'EMAIL' "
                                           "(SPLIT-1, SPLIT-2)"]),
        data=SimpleNamespace(warnings=["No real inbox is set, so the contacts of the 1 case(s) get undeliverable "
                                       "addresses.", "the entry query selects 2 columns it does not have."],
                             scenarios_rows=scenario_rows),
        checks=checks if checks is not None else [CheckResult("Every key joins", True, [])],
        files=files,
        settings=Settings(real_inbox=real_inbox),
        generation_time=datetime(2026, 10, 11, 13, 45),
    )


def test_summary_import_and_download_notes():
    result = _stub_result()
    assert app.done_line(result) == "Done at 13:45, run identifier R01. 1 of 1 trust check passed."
    failing = _stub_result([CheckResult("A", True, []), CheckResult("B", False, ["why"])])
    assert app.done_line(failing) == ("Done at 13:45, run identifier R01. 1 of 2 trust checks failed: read Trust "
                                      "checks below before you import.")
    assert app.summary_notes(result) == [
        "3 of the 4 branches not covered lie behind 2 branches that no contact can reach (see report.md).",
        "No real inbox was given, so the contacts that must open an email get undeliverable addresses and those "
        "branches are reported as not covered."]
    assert app.summary_notes(_stub_result(real_inbox="tester@example.com"))[1:] == []
    assert app.import_notes(result) == [
        "Open report.md first: its How to run section gives the import order.",
        "Only TST_R01_S01, the first scenario in run order, is active in the CSVs.",
        "Run the scenarios one at a time, in run order. When the contacts of a scenario have left the journey, "
        "make the next one active: set DE_Config.ACTIVE to True on its row and to False on every other row. Change "
        "nothing else and import nothing again."]
    assert app.import_notes(_stub_result(one_active=False))[1:] == [
        "Every scenario is active in the CSVs, so the scenarios run together."]
    assert app.download_lines(result) == [
        "DE_Entry.csv: the data to import.",
        "scenarios.csv: the scenarios in run order, with the one active at the start.",
        "testbook.xlsx: the tests and their expected results.",
        "report.md: what is covered, what is not and why, and how to run the tests."]
    assert app.preview_files(result) == ["scenarios.csv", "DE_Entry.csv"]
    warnings, left_out = app.generation_warnings(result)
    assert warnings == ["Suspicious pattern: T.F is compared with 'Email' and 'EMAIL'",
                        "The entry query selects 2 columns it does not have."] and left_out


def test_result_step_shows_summary_import_previews_download_checks_and_warnings():
    checks = [CheckResult("Every key joins", True, ["a note on a passed check"]),
              CheckResult("Values respect the schema", False, [f"problem {n}" for n in range(1, 24)])]
    at = AppTest.from_function(_result_page, args=(_stub_result(checks), b"zip bytes")).run(timeout=TIMEOUT)
    assert not at.exception and not at.error and not at.subheader
    text = _markdown(at)
    labels = re.findall(r"^\*\*(.+)\*\*$", text, flags=re.MULTILINE)
    assert labels == ["Summary", "Before you import", "Preview of the CSVs", "Download", "Trust checks",
                      "Warnings from the generation"]
    assert text.startswith("Done at 13:45, run identifier R01. 1 of 2 trust checks failed: read Trust checks below "
                           "before you import.")
    for label, count in [("Scenarios", 2), ("Cases", 3), ("Contacts", 9), ("Branches covered", 4),
                         ("Branches covered with manual action", 1), ("Branches not covered", 4)]:
        assert f"| {label} | {count} |" in text
    assert "3 of the 4 branches not covered lie behind 2 branches that no contact can reach (see report.md)." in text
    assert "No real inbox was given, so the contacts that must open an email" in text
    assert "- Only TST_R01_S01, the first scenario in run order, is active in the CSVs." in text
    assert "1 of 2 trust checks passed." in text
    assert "- Passed: Every key joins" in text and "a note on a passed check" not in text
    assert "- Failed: Values respect the schema" in text
    assert "    - problem 20" in text and "problem 21" not in text and "    - and 3 more" in text
    previews = [_plain(e.label) for e in at.expander]
    assert previews == ["scenarios.csv: the run plan (2 rows)", "DE_Entry.csv (12 rows)"]
    assert all(e.proto.expanded is False for e in at.expander)
    assert not at.get("dataframe") and not at.table     # the file's own lines: no CSV download of a preview
    entry = _expander(at, "DE_Entry.csv (12 rows)")
    assert [_plain(c.value) for c in entry.caption] == ["The first 10 of 12 rows."]
    lines = entry.code[0].value.splitlines()
    assert lines[0] == "ContactId,Email,Note" and lines[1] == "TST_R01_C0001,,x_1" and len(lines) == 11
    assert "CJ demo_test_data.zip holds 4 files:" in text
    assert "- DE_Entry.csv: the data to import." in text
    assert "- Suspicious pattern: T.F is compared with 'Email' and 'EMAIL'" in text
    assert "No real inbox is set" not in text           # said in the summary instead
    assert "report.md lists the activities concerned." in text
    buttons = at.get("download_button")
    assert len(buttons) == 1 and buttons[0].label == app.DOWNLOAD_LABEL and buttons[0].proto.type == "primary"


@needs_pilot
def test_generate_runs_once_and_the_download_does_not_generate_again(pilot_bytes, monkeypatch):
    calls = []

    def stand_in_generate(data, settings):
        calls.append(settings)
        return _stub_result(journey_name=PILOT_JOURNEY)

    monkeypatch.setattr(pipeline, "generate", stand_in_generate)
    at = AppTest.from_function(_render_page, args=(pilot_bytes,)).run(timeout=TIMEOUT)
    _widget(at.text_input, app.SETTING_LABELS["real_inbox"]).input("tester@example.com")
    _widget(at.button, app.GENERATE_LABEL).click().run(timeout=TIMEOUT)
    assert not at.exception and not at.error
    assert len(calls) == 1 and calls[0].real_inbox == "tester@example.com"
    assert not _widget(at.button, app.GENERATE_LABEL).disabled          # enabled again under the result
    assert app.PENDING_KEY not in at.session_state
    assert _markdown(at).count("Done at 13:45") == 1
    stored = at.session_state[app.RESULT_KEY]
    with zipfile.ZipFile(io.BytesIO(stored.zip_bytes)) as archive:
        assert archive.namelist() == list(stored.result.files)

    at.get("download_button")[0].click().run(timeout=TIMEOUT)
    assert not at.exception
    assert len(calls) == 1                     # the download reran the page, not the generation
    assert at.session_state[app.RESULT_KEY] is stored and len(at.get("download_button")) == 1


@needs_pilot
def test_a_failed_generation_shows_one_sentence_and_closed_technical_details(pilot_bytes, monkeypatch):
    def failing_generate(data, settings):
        raise AttributeError("'CoverageEngine' object has no attribute '_flag_case_variants'")

    monkeypatch.setattr(pipeline, "generate", failing_generate)
    at = AppTest.from_function(_render_page, args=(pilot_bytes,)).run(timeout=TIMEOUT)
    _widget(at.button, app.GENERATE_LABEL).click().run(timeout=TIMEOUT)
    assert not at.exception
    assert [_plain(e.value) for e in at.error] == [app.UNEXPECTED_GENERATION]
    details = _expander(at, app.TECHNICAL_DETAILS)
    assert details.proto.expanded is False
    assert "'CoverageEngine' object has no attribute '_flag_case_variants'" in details.code[0].value
    assert "_flag_case_variants" not in _markdown(at)
    assert not _widget(at.button, app.GENERATE_LABEL).disabled and not at.get("download_button")


@needs_pilot
def test_a_kept_result_shows_only_for_the_same_file_and_settings(pilot_bytes):
    at = AppTest.from_function(_render_page, args=(pilot_bytes,)).run(timeout=TIMEOUT)
    settings = app.settings_from_form(app.default_form_values(PILOT_ACTIVATION))
    stub = _stub_result(journey_name=PILOT_JOURNEY)
    digest = hashlib.sha256(pilot_bytes).hexdigest()

    at.session_state[app.RESULT_KEY] = app.StoredRun(digest, settings, result=stub, zip_bytes=b"zip")
    at.run(timeout=TIMEOUT)
    assert "**Summary**" in _markdown(at) and len(at.get("download_button")) == 1

    other = app.settings_from_form({**app.default_form_values(PILOT_ACTIVATION), "run_id": "R02"})
    at.session_state[app.RESULT_KEY] = app.StoredRun(digest, other, result=stub, zip_bytes=b"zip")
    at.run(timeout=TIMEOUT)
    assert "**Summary**" not in _markdown(at) and not at.get("download_button")


def test_csv_preview_keeps_the_first_lines_as_written():
    content = b"A,B,C\n1,,x\n2,\"a,b\",\n3,True,\n"
    assert app.csv_preview(content, limit=2) == ("A,B,C\n1,,x\n2,\"a,b\",", 3)
    assert app.csv_preview(content) == (content.decode().rstrip("\n"), 3)
    assert app.csv_preview(b"") == ("", 0)
    assert app.csv_preview(b"A,B\n") == ("A,B", 0)


def test_zip_file_name():
    assert app.zip_file_name(PILOT_JOURNEY) == "CJ_SkYDE_NCRM_Demo_final_test_data.zip"
    assert app.zip_file_name("Journey 1/2: test?") == "Journey 1_2_ test__test_data.zip"
    assert app.zip_file_name("") == "journey_test_data.zip"


@pytest.mark.slow
@needs_pilot
def test_generate_on_pilot_then_download_without_generating_again(pilot_bytes, monkeypatch):
    calls = []
    real_generate = pipeline.generate

    def counting_generate(*args, **kwargs):
        calls.append(args[1] if len(args) > 1 else kwargs.get("settings"))
        return real_generate(*args, **kwargs)

    monkeypatch.setattr(pipeline, "generate", counting_generate)
    at = AppTest.from_function(_render_page, args=(pilot_bytes,)).run(timeout=TIMEOUT)
    _widget(at.text_input, app.SETTING_LABELS["real_inbox"]).input("tester@example.com")
    _widget(at.button, app.GENERATE_LABEL).click().run(timeout=600)
    assert not at.exception and not at.error
    assert len(calls) == 1 and calls[0].real_inbox == "tester@example.com" and calls[0].contacts_per_case == 3

    stored = at.session_state[app.RESULT_KEY]
    result = stored.result
    text = _markdown(at)
    assert app.done_line(result) in text and app.done_line(result).startswith(
        f"Done at {result.generation_time:%H:%M}, run identifier R01.")
    stats = result.coverage.stats
    for label, key in [("Scenarios", "scenarios"), ("Cases", "cases"), ("Contacts", "contacts"),
                       ("Branches covered", "covered"), ("Branches covered with manual action", "covered_manual"),
                       ("Branches not covered", "not_covered")]:
        assert f"| {label} | {stats[key]} |" in text
    assert re.search(r"\d+ of the \d+ branches not covered lie behind \d+ branch(es)? that no contact can reach",
                     text)
    assert "No real inbox was given" not in text
    assert "- Only TST_R01_S01, the first scenario in run order, is active in the CSVs." in text
    assert "set DE_NCRM_AD_HOC_CONFIG.ACTIVE to True on its row" in text
    assert len(re.findall(r"^- (Passed|Failed): ", text, flags=re.MULTILINE)) == len(result.checks)
    previews = [_plain(e.label) for e in at.expander if _plain(e.label) not in (app.MORE_SETTINGS,)]
    assert previews[0].startswith("scenarios.csv: the run plan (")
    assert sorted(p.split(" ")[0].rstrip(":") for p in previews) == sorted(
        [f"{t}.csv" for t in PILOT_CSV_TABLES] + ["scenarios.csv"])
    assert len(at.code) == len(previews) and not at.table and not at.get("dataframe")
    entry = _expander(at, next(p for p in previews if p.startswith("DE_NCM_AdHoc_Entry.csv")))
    entry_columns = [f.name for f in result.package.tables["DE_NCM_AdHoc_Entry"].fields]
    entry_lines = entry.code[0].value.splitlines()
    assert next(csv.reader(entry_lines[:1])) == entry_columns
    assert entry_lines == result.files["DE_NCM_AdHoc_Entry.csv"].decode("utf-8").splitlines()[:app.PREVIEW_ROWS + 1]
    assert all(len(code.value.splitlines()) <= app.PREVIEW_ROWS + 1 for code in at.code)
    with zipfile.ZipFile(io.BytesIO(stored.zip_bytes)) as archive:
        assert archive.namelist() == list(result.files)
    assert sorted(result.files) == sorted([f"{t}.csv" for t in PILOT_CSV_TABLES]
                                          + [outputs.SCENARIOS_FILE, outputs.TESTBOOK_FILE, outputs.REPORT_FILE])
    assert "CJ_SkYDE_NCRM_Demo_final_test_data.zip holds 7 files:" in text
    assert "UPDATECONTACTDATAV2" not in text and "MULTICRITERIADECISIONV2" not in text

    at.get("download_button")[0].click().run(timeout=TIMEOUT)
    assert not at.exception
    assert len(calls) == 1                     # the download reran the page, not the generation
    assert at.session_state[app.RESULT_KEY] is stored
    assert len(at.get("download_button")) == 1
