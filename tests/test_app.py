"""The one-page app (spec "The app"): the page through Streamlit's AppTest, and its helpers.

``AppTest.from_file`` runs the whole page (title, step 1 and the uploader); ``AppTest.from_function``
runs ``app.render(bytes)``, the steps below the uploader, with the bytes passed in. Only one test
runs the full generation on the pilot (about 30 s); it is marked ``slow``.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest, element_tree

from cjhelper import app, pipeline
from cjhelper.loader import LoadError
from cjhelper.model import CheckResult, Settings

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


def _markdown(at: AppTest) -> str:
    return "\n".join(_plain(m.value) for m in at.markdown)


def _widget(widgets, label: str):
    found = [w for w in widgets if w.label == label]
    assert len(found) == 1, (label, [w.label for w in widgets])
    return found[0]


def _step_content(at: AppTest) -> list:
    """Everything a step after the upload would show."""
    return (list(at.subheader) + list(at.caption) + list(at.get("dataframe")) + list(at.button)
            + list(at.checkbox) + list(at.number_input) + list(at.text_input) + list(at.selectbox)
            + list(at.get("download_button")))


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
    assert not at.error
    assert not _step_content(at)


@pytest.mark.parametrize("data, words", [
    (b"{not json", "not valid JSON"),
    (b"", "not valid JSON"),
    (b"[1, 2]", "JSON object"),
    (b'{"entities": {"dataExtensions": {}}}', "no journey"),
    (b'{"name": "x"}', "no journey"),
    (b"\xff\xfe\x00{", "not UTF-8"),
])
def test_unreadable_file_shows_one_plain_error_and_nothing_else(data, words):
    at = AppTest.from_function(_render_page, args=(data,)).run(timeout=TIMEOUT)
    assert not at.exception
    assert len(at.error) == 1
    message = _plain(at.error[0].value)
    assert words in message and message.endswith(".") and "\n" not in message
    assert not at.header and not at.markdown and not _step_content(at)


@pytest.mark.skipif(not CAN_UPLOAD, reason="this Streamlit's AppTest cannot drive st.file_uploader")
def test_invalid_upload_through_the_uploader_shows_only_the_error():
    at = AppTest.from_file(str(APP_FILE)).run(timeout=TIMEOUT)
    at.get("file_uploader")[0].set_value(("export.json", b"{not json", "application/json")).run(timeout=TIMEOUT)
    assert not at.exception
    assert len(at.error) == 1 and "not valid JSON" in _plain(at.error[0].value)
    assert [h.value for h in at.header] == [app.STEP_UPLOAD]
    assert not _step_content(at)


def test_without_a_file_nothing_is_kept():
    at = AppTest.from_function(_render_page, args=(None,))
    at.session_state[app.DETECTION_KEY] = ("digest", "summary")
    at.session_state[app.RESULT_KEY] = "result"
    at.run(timeout=TIMEOUT)
    assert not at.exception
    assert app.DETECTION_KEY not in at.session_state and app.RESULT_KEY not in at.session_state
    assert not at.header and not at.error and not _step_content(at)


def test_error_messages_are_one_plain_sentence():
    assert app.error_message(LoadError("The export holds no journey.")) == "The export holds no journey."
    with pytest.raises(json.JSONDecodeError) as not_json:
        json.loads("{oops")
    assert app.error_message(not_json.value) == ("The file is not valid JSON (Expecting property name enclosed in "
                                                 "double quotes at line 1, column 2).")
    with pytest.raises(UnicodeDecodeError) as not_text:
        b"\xff".decode("utf-8")
    assert app.error_message(not_text.value) == "The file is not UTF-8 text, so it is not a valid JSON package export."
    assert app.error_message(KeyError("name")) == "The file could not be read as a package export (KeyError: 'name')."
    assert app.generation_error_message(RuntimeError("no path.")) == "The generation failed: no path."
    assert app.generation_error_message(RuntimeError()) == "The generation failed: RuntimeError."


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
    lines = {line.name: line for line in summary.tables}
    assert sorted(name for name, line in lines.items() if line.csv) == sorted(PILOT_CSV_TABLES)
    assert lines["DE_NCM_AdHoc_Entry"].role == "Entry" and lines["DE_NCM_AdHoc_Entry"].level == "Contact"
    assert lines["DE_NCRM_AD_HOC_CONFIG"].role == "Split and source"
    assert lines["DE_NCRM_AD_HOC_CONFIG"].level == "Scenario"
    assert lines["DE_NCRM_AdHoc_Target"].role == "Source"
    assert lines["DE_SkyDE_AdHoc_Log_partial"] == app.TableLine("DE_SkyDE_AdHoc_Log_partial", "Written only", "-", False)
    assert summary.activation_field == PILOT_ACTIVATION
    assert PILOT_ACTIVATION in summary.activation_choices
    assert all(table == "DE_NCRM_AD_HOC_CONFIG" for table, _ in summary.activation_choices)


@needs_pilot
def test_detection_step_on_pilot_shows_journey_activities_and_the_four_csv_tables(pilot_bytes):
    at = AppTest.from_function(_render_page, args=(pilot_bytes,)).run(timeout=TIMEOUT)
    assert not at.exception and not at.error
    assert [h.value for h in at.header] == [app.STEP_REVIEW, app.STEP_SETTINGS, app.STEP_GENERATE]
    text = _markdown(at)
    assert f"The export holds the journey {PILOT_JOURNEY}, with 178 activities." in text
    assert "| Decision split | 106 |" in text and "| Unsupported |" not in text
    with_csv = re.findall(r"^\| (\S+) \| [^|]+ \| [^|]+ \| Yes \|$", text, flags=re.MULTILINE)
    assert sorted(with_csv) == sorted(PILOT_CSV_TABLES)
    assert "| DE_Check_Active_Campaigns | Written only | - | No |" in text
    assert [b.label for b in at.button] == [app.GENERATE_LABEL]
    assert not at.get("download_button")      # nothing generated yet


def test_activity_counts_and_roles_use_plain_names():
    activities = {key: SimpleNamespace(kind=kind) for key, kind in
                  [("a", "decision"), ("b", "unsupported"), ("c", "decision"), ("d", "wait_sto"), ("e", "new_kind")]}
    journey = SimpleNamespace(activities=activities)
    assert app.activity_counts(journey) == [("Decision split", 2), ("Send-time wait", 1), ("Unsupported", 1),
                                            ("new_kind", 1)]
    assert app.role_text({"source", "split"}) == "Split and source"
    assert app.role_text({"entry", "split", "source"}) == "Entry, split and source"
    assert app.role_text({"written"}) == "Written only"
    assert app.role_text(set()) == "None"


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


@needs_pilot
def test_settings_widgets_start_at_the_spec_defaults(pilot_bytes):
    at = AppTest.from_function(_render_page, args=(pilot_bytes,)).run(timeout=TIMEOUT)
    labels = app.SETTING_LABELS
    numbers = {name: _widget(at.number_input, labels[name]).value for name in app.NUMBER_SETTINGS}
    assert numbers == {"contacts_per_case": 3, "contacts_per_random_case": 50, "window_start_days": -1,
                       "window_end_days": 7, "wait_offset_hours": 0, "wait_offset_before_engagement_hours": 24}
    texts = {name: _widget(at.text_input, labels[name]).value
             for name in ("real_inbox", "real_phone", "fake_phone", "date_format", "run_id")}
    assert texts == {"real_inbox": "", "real_phone": "", "fake_phone": "333333333333",
                     "date_format": "%Y-%m-%d %H:%M", "run_id": "R01"}
    captions = " ".join(_plain(c.value) for c in at.caption)
    assert "The default, %Y-%m-%d %H:%M, writes dates as YYYY-MM-DD HH:MM." in captions
    one_active = _widget(at.checkbox, labels["one_active_scenario"])
    assert one_active.value is True and not one_active.disabled
    assert "detected in the entry query filters: DE_NCRM_AD_HOC_CONFIG.ACTIVE." in captions
    activation = _widget(at.selectbox, labels["activation_field"])
    assert activation.value == PILOT_ACTIVATION
    assert "DE_NCRM_AD_HOC_CONFIG.HAS_RUN" in activation.options
    assert _widget(at.checkbox, labels["case_insensitive_text"]).value is False


# ---------------------------------------------------------------------------
# Step 4: the result
# ---------------------------------------------------------------------------

def _stub_result(checks, files, journey_name="CJ demo"):
    """The parts of a GenerationResult that step 4 reads."""
    return SimpleNamespace(
        package=SimpleNamespace(journey=SimpleNamespace(name=journey_name)),
        coverage=SimpleNamespace(stats={"scenarios": 2, "cases": 3, "contacts": 9, "covered": 4,
                                        "covered_manual": 1, "not_covered": 2},
                                 warnings=["suspicious pattern: T.F is compared with 'Email' and 'EMAIL'"]),
        data=SimpleNamespace(warnings=["No real inbox is set."]),
        checks=checks,
        files=files,
    )


def test_result_step_shows_summary_checks_previews_warnings_and_download():
    rows = "".join(f"TST_R01_C{n:04d},,x_{n}\n" for n in range(1, 13)).encode()
    files = {"DE_Entry.csv": b"ContactId,Email,Note\n" + rows, "scenarios.csv": b"scenario_key\nTST_R01_S01\n",
             "report.md": b"# Report\n"}
    checks = [CheckResult("Every key joins", True, ["a note on a passed check"]),
              CheckResult("Values respect the schema", False, [f"problem {n}" for n in range(1, 24)])]
    at = AppTest.from_function(_result_page, args=(_stub_result(checks, files), b"zip bytes")).run(timeout=TIMEOUT)
    assert not at.exception and not at.error
    assert [s.value for s in at.subheader] == ["Summary", "Trust checks", "Preview of the CSVs", "Warnings", "Download"]
    text = _markdown(at)
    for label, count in [("Scenarios", 2), ("Cases", 3), ("Contacts", 9), ("Branches covered", 4),
                         ("Branches covered with manual action", 1), ("Branches not covered", 2)]:
        assert f"| {label} | {count} |" in text
    assert "1 of 2 trust checks passed." in text
    assert "- Passed: Every key joins" in text and "a note on a passed check" not in text
    assert "- Failed: Values respect the schema" in text
    assert "    - problem 20" in text and "problem 21" not in text and "    - and 3 more" in text
    assert "**DE_Entry.csv**: 12 rows, the first 10 shown" in text
    assert "**scenarios.csv**: 1 row" in text
    frames = at.get("dataframe")
    assert len(frames) == 2
    entry = frames[0].value
    assert list(entry.columns) == ["ContactId", "Email", "Note"] and len(entry) == 10
    assert entry.iloc[0].tolist() == ["TST_R01_C0001", "", "x_1"]
    assert "- Suspicious pattern: T.F is compared with 'Email' and 'EMAIL'" in text
    assert "- No real inbox is set." in text
    assert "CJ demo_test_data.zip holds 3 files: DE_Entry.csv, scenarios.csv and report.md." in text
    buttons = at.get("download_button")
    assert len(buttons) == 1 and buttons[0].label == app.DOWNLOAD_LABEL


@needs_pilot
def test_a_kept_result_shows_only_for_the_same_file_and_settings(pilot_bytes):
    at = AppTest.from_function(_render_page, args=(pilot_bytes,)).run(timeout=TIMEOUT)
    settings = app.settings_from_form(app.default_form_values(PILOT_ACTIVATION))
    files = {"scenarios.csv": b"scenario_key\nTST_R01_S01\n"}
    stub = _stub_result([CheckResult("A check", True, [])], files, journey_name=PILOT_JOURNEY)
    digest = hashlib.sha256(pilot_bytes).hexdigest()

    at.session_state[app.RESULT_KEY] = app.StoredResult(digest, settings, stub, b"zip")
    at.run(timeout=TIMEOUT)
    assert "Summary" in [s.value for s in at.subheader] and len(at.get("download_button")) == 1

    other = app.settings_from_form({**app.default_form_values(PILOT_ACTIVATION), "run_id": "R02"})
    at.session_state[app.RESULT_KEY] = app.StoredResult(digest, other, stub, b"zip")
    at.run(timeout=TIMEOUT)
    assert "Summary" not in [s.value for s in at.subheader] and not at.get("download_button")


def test_csv_preview_keeps_cells_as_written():
    content = b"A,B,C\n1,,x\n2,\"a,b\",\n3,True,\n"
    columns, total = app.csv_preview(content, limit=2)
    assert total == 3
    assert columns == {"A": ["1", "2"], "B": ["", "a,b"], "C": ["x", ""]}
    assert app.csv_preview(b"") == ({}, 0)


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
    assert [s.value for s in at.subheader][-5:] == ["Summary", "Trust checks", "Preview of the CSVs", "Warnings",
                                                    "Download"]
    text = _markdown(at)
    stats = result.coverage.stats
    for label, key in [("Scenarios", "scenarios"), ("Cases", "cases"), ("Contacts", "contacts"),
                       ("Branches covered", "covered"), ("Branches covered with manual action", "covered_manual"),
                       ("Branches not covered", "not_covered")]:
        assert f"| {label} | {stats[key]} |" in text
    assert len(re.findall(r"^- (Passed|Failed): ", text, flags=re.MULTILINE)) == len(result.checks)
    csv_names = [name for name in result.files if name.endswith(".csv")]
    assert sorted(csv_names) == sorted([f"{t}.csv" for t in PILOT_CSV_TABLES] + ["scenarios.csv"])
    frames = at.get("dataframe")
    assert len(frames) == len(csv_names)
    entry_columns = [f.name for f in result.package.tables["DE_NCM_AdHoc_Entry"].fields]
    assert list(frames[csv_names.index("DE_NCM_AdHoc_Entry.csv")].value.columns) == entry_columns
    assert all(len(frame.value) <= app.PREVIEW_ROWS for frame in frames)
    with zipfile.ZipFile(io.BytesIO(stored.zip_bytes)) as archive:
        assert archive.namelist() == list(result.files)
    assert app.zip_file_name(result.package.journey.name) == "CJ_SkYDE_NCRM_Demo_final_test_data.zip"

    at.get("download_button")[0].click().run(timeout=TIMEOUT)
    assert not at.exception
    assert len(calls) == 1                     # the download reran the page, not the generation
    assert at.session_state[app.RESULT_KEY] is stored
    assert len(at.get("download_button")) == 1
