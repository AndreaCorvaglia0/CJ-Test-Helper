"""End-to-end acceptance test on the pilot export (spec, "Acceptance criteria on the pilot journey")."""

from __future__ import annotations

import io
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from cjhelper import checks, outputs, pipeline
from cjhelper.model import STATUS_COVERED, STATUS_MANUAL, STATUS_NOT_COVERED, Settings

PILOT = Path(__file__).resolve().parent.parent / "fixtures" / "CJ template complesso-v1.json"
NOW = datetime(2026, 10, 11, 12, 0)

pytestmark = pytest.mark.skipif(not PILOT.exists(), reason="pilot export not present")


@pytest.fixture(scope="module")
def result():
    return pipeline.generate(str(PILOT), Settings(real_inbox="tester@example.com", generation_time=NOW))


def test_journey_parsed(result):
    assert result.package.journey.name == "CJ_SkYDE_NCRM_Demo_final"
    assert result.package.journey.activity_count == 178


def test_exactly_four_csvs(result):
    csvs = sorted(n for n in result.files if n.endswith(".csv") and n != "scenarios.csv")
    assert csvs == sorted(["DE_NCM_AdHoc_Entry.csv", "SF_Master_DataExtension_DE.csv", "DE_NCRM_AdHoc_Target.csv", "DE_NCRM_AD_HOC_CONFIG.csv"])


def test_trust_checks_pass(result):
    failed = [(c.name, c.details) for c in result.checks if not c.passed]
    assert not failed, failed


def test_every_reachable_decision_branch_is_covered(result):
    decisions = [b for b in result.coverage.branches if b.activity_kind == "decision"]
    assert len({b.activity_key for b in decisions}) == 106
    for b in decisions:
        if b.status == STATUS_NOT_COVERED:
            assert b.reason.startswith("unreachable"), (b.activity_key, b.outcome_key, b.reason)
        else:
            assert b.covered_by
    for case in result.coverage.cases:
        assert case.contact_count == (50 if case.random else 3)


def test_engagement_yes_after_channels_2_and_3_unreachable(result):
    by_key = {(b.activity_key, b.outcome_key): b for b in result.coverage.branches}
    for split in ("ENGAGEMENTSPLITV2-3", "ENGAGEMENTSPLITV2-4", "ENGAGEMENTSPLITV2-5", "ENGAGEMENTSPLITV2-6"):
        b = by_key[(split, "branchResult-1")]
        assert b.status == STATUS_NOT_COVERED and b.reason.startswith("unreachable"), (split, b.reason)
    # channel 1: open is covered with a manual action, click has no link
    assert by_key[("ENGAGEMENTSPLITV2-1", "branchResult-1")].status == STATUS_MANUAL
    assert by_key[("ENGAGEMENTSPLITV2-1", "branchResult-2")].status == STATUS_COVERED
    click = by_key[("ENGAGEMENTSPLITV2-2", "branchResult-1")]
    assert click.status == STATUS_NOT_COVERED and "no link" in click.reason


def test_random_split_statistical_case(result):
    stat = [c for c in result.coverage.cases if c.random is not None]
    assert len(stat) == 1
    assert stat[0].contact_count == 50 and stat[0].random.activity_key == "RANDOMSPLITV2-1"
    assert (stat[0].random.expected_low, stat[0].random.expected_high) == (1, 9)
    assert sorted(b.percentage for b in stat[0].random.branches) == [10, 90]


def test_counts_in_the_expected_range(result):
    s = result.coverage.stats
    assert 15 <= s["scenarios"] <= 80, s
    assert 25 <= s["cases"] <= 300, s
    assert 100 <= s["contacts"] <= 1000, s
    assert s["contact_classes"] == 8


def test_addresses(result):
    header, rows = checks.read_csv_bytes(result.files["SF_Master_DataExtension_DE.csv"])
    manual = {k for c in result.coverage.cases if c.manual_actions for k in c.contact_keys}
    assert manual
    for r in rows:
        if r["ContactId"] in manual:
            assert r["Emailaddress"] == f"tester+{r['ContactId']}@example.com"
        else:
            assert r["Emailaddress"] == f"{r['ContactId']}@example.invalid"


def test_testbook_and_report_totals(result):
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(result.files["testbook.xlsx"]))
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header, body = rows[0], [r for r in rows[1:] if any(r)]
    assert list(header)[:9] == ["ID", "Owner system", "Test name", "Description", "Pre conditions", "Detailed steps",
                                "Expected result", "Status", "Note"]
    assert len(body) == len(result.coverage.cases)
    text = "\n".join(" ".join(str(c) for c in r if c is not None) for r in body)
    for case in result.coverage.cases:
        if case.random is None:
            for key in case.contact_keys:
                assert key in text
        else:
            assert case.contact_keys[0] in text and case.contact_keys[-1] in text
    report = result.files["report.md"].decode("utf-8")
    s = result.coverage.stats
    for n in (s["scenarios"], s["cases"], s["contacts"]):
        assert str(n) in report
    assert "EMAIL" in report and "Email" in report


def test_same_settings_same_files(result):
    again = pipeline.generate(str(PILOT), Settings(real_inbox="tester@example.com", generation_time=NOW))
    for name, content in result.files.items():
        if name.endswith(".xlsx"):
            continue   # openpyxl stamps the creation time inside the file
        assert again.files[name] == content, name
    assert [s.key for s in again.coverage.scenarios] == [s.key for s in result.coverage.scenarios]
    assert [c.id for c in again.coverage.cases] == [c.id for c in result.coverage.cases]


def test_zip_holds_every_file(result):
    data = outputs.build_zip(result.files)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert sorted(z.namelist()) == sorted(result.files)
