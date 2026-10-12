"""Run every example in examples/ through the pipeline and compare with its hand-written expected answer.

The format of expected.json is described in docs/plan.md, section "Examples". A failing example is
never fixed by editing the expected answer without a written proof from the spec in its README.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import Path

import pytest

from cjhelper import outputs, pipeline
from cjhelper.model import Settings

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
NOW = datetime(2026, 10, 11, 12, 0)


def example_dirs():
    if not EXAMPLES.exists():
        return []
    return sorted(d for d in EXAMPLES.iterdir() if d.is_dir() and (d / "expected.json").exists())


def load_expected(d: Path) -> dict:
    return json.loads((d / "expected.json").read_text(encoding="utf-8"))


def settings_from(expected: dict) -> Settings:
    s = Settings(generation_time=NOW)
    for k, v in (expected.get("settings") or {}).items():
        if k == "activation_field" and isinstance(v, list):
            v = tuple(v)
        setattr(s, k, v)
    return s


def check_range(name, value, spec, problems):
    if spec is None:
        return
    if isinstance(spec, int):
        if value != spec:
            problems.append(f"{name}: {value} != {spec}")
        return
    lo, hi = spec.get("min"), spec.get("max")
    if lo is not None and value < lo:
        problems.append(f"{name}: {value} < min {lo}")
    if hi is not None and value > hi:
        problems.append(f"{name}: {value} > max {hi}")


def contains(text: str, wanted) -> bool:
    """Case-insensitive substring test; a list in `wanted` means "any of these" (wording the spec leaves free)."""
    options = wanted if isinstance(wanted, list) else [wanted]
    return any(o.lower() in text.lower() for o in options)


def report_head(report: str) -> str:
    """The opening of report.md: everything before its second "## " section."""
    head: list[str] = []
    sections = 0
    for line in report.splitlines():
        if line.startswith("## "):
            sections += 1
            if sections == 2:
                break
        head.append(line)
    return "\n".join(head)


def testbook_text(result) -> str:
    import openpyxl

    book = openpyxl.load_workbook(io.BytesIO(outputs.write_testbook(result)))
    return "\n".join(str(cell) for sheet in book.worksheets for row in sheet.iter_rows(values_only=True)
                     for cell in row if cell is not None)


def compare_texts(result, expected: dict, all_warnings: str, problems: list[str]) -> None:
    """Keys on the texts the tester reads: report.md, testbook.xlsx, warnings (docs/plan.md, "Esempi")."""
    for text in expected.get("warnings_not_contain") or []:
        if contains(all_warnings, text):
            problems.append(f"a warning contains {text!r}")
    if any(k in expected for k in ("report_contains", "report_not_contains", "report_head_contains")):
        report = result.files["report.md"].decode("utf-8")
        for text in expected.get("report_contains") or []:
            if not contains(report, text):
                problems.append(f"report.md does not contain {text!r}")
        for text in expected.get("report_not_contains") or []:
            if contains(report, text):
                problems.append(f"report.md contains {text!r}")
        head = report_head(report)
        for text in expected.get("report_head_contains") or []:
            if not contains(head, text):
                problems.append(f"the opening of report.md does not contain {text!r}")
    if expected.get("testbook_contains"):
        book = testbook_text(result)
        for text in expected["testbook_contains"]:
            if not contains(book, text):
                problems.append(f"testbook.xlsx does not contain {text!r}")
    if expected.get("csv_no_space_cells"):
        for name, content in sorted(result.files.items()):
            if not name.endswith(".csv"):
                continue
            for row in csv.reader(io.StringIO(content.decode("utf-8"))):
                for cell in row:
                    if cell and not cell.strip():
                        problems.append(f"{name}: a cell holds only spaces ({cell!r})")


def compare(result, expected: dict) -> list[str]:
    problems: list[str] = []
    cov = result.coverage
    if "journey_name" in expected and result.package.journey.name != expected["journey_name"]:
        problems.append(f"journey name {result.package.journey.name!r} != {expected['journey_name']!r}")
    if "activity_count" in expected and result.package.journey.activity_count != expected["activity_count"]:
        problems.append(f"activity count {result.package.journey.activity_count} != {expected['activity_count']}")
    if "csv_tables" in expected:
        got = sorted(result.table_model.selected_tables)
        if got != sorted(expected["csv_tables"]):
            problems.append(f"csv tables {got} != {sorted(expected['csv_tables'])}")
    for t, lvl in (expected.get("table_levels") or {}).items():
        role = result.table_model.tables.get(t)
        if role is None or role.level != lvl:
            problems.append(f"table {t} level {role.level if role else None} != {lvl}")
    branches = {f"{b.activity_key}/{b.outcome_key}": b for b in cov.branches}
    for key, exp in (expected.get("branches") or {}).items():
        b = branches.get(key)
        if b is None:
            problems.append(f"branch {key}: not in the journey")
            continue
        if b.status != exp.get("status"):
            problems.append(f"branch {key}: status {b.status!r} != {exp.get('status')!r} (reason: {b.reason})")
        if exp.get("reason_contains") and not contains(b.reason, exp["reason_contains"]):
            problems.append(f"branch {key}: reason {b.reason!r} does not contain {exp['reason_contains']!r}")
        if "statistical" in exp and bool(b.statistical) != bool(exp["statistical"]):
            problems.append(f"branch {key}: statistical {b.statistical} != {exp['statistical']}")
    for key, allowed in (expected.get("branches_any_of") or {}).items():
        b = branches.get(key)
        if b is None:
            problems.append(f"branch {key}: not in the journey")
        elif b.status not in allowed:
            problems.append(f"branch {key}: status {b.status!r} not in {allowed} (reason: {b.reason})")
    check_range("scenario_count", cov.stats["scenarios"], expected.get("scenario_count"), problems)
    check_range("case_count", cov.stats["cases"], expected.get("case_count"), problems)
    check_range("contact_count", cov.stats["contacts"], expected.get("contact_count"), problems)
    for want in expected.get("cases") or []:
        if not any(case_matches(result, c, s, want) for s in cov.scenarios for c in s.cases):
            problems.append(f"no case matches {want}")
    if "unsupported" in expected and sorted(cov.unsupported) != sorted(expected["unsupported"]):
        problems.append(f"unsupported {sorted(cov.unsupported)} != {sorted(expected['unsupported'])}")
    all_warnings = " || ".join(result.package.warnings + cov.warnings + result.table_model.warnings + result.data.warnings)
    for text in expected.get("warnings_contain") or []:
        if not contains(all_warnings, text):
            problems.append(f"no warning contains {text!r}")
    compare_texts(result, expected, all_warnings, problems)
    if expected.get("checks_pass"):
        for c in result.checks:
            if not c.passed:
                problems.append(f"check failed: {c.name}: {c.details[:5]}")
    return problems


def case_matches(result, case, scenario, want) -> bool:
    for k, v in (want.get("scenario_values") or {}).items():
        t, f = k.split(".", 1)
        if scenario.values.get((t, f)) != v:
            return False
    for k, v in (want.get("contact_values") or {}).items():
        t, f = k.split(".", 1)
        if case.contact_values.get((t, f)) != v:
            return False
    if "end_activity" in want and case.end_activity_key != want["end_activity"]:
        return False
    if "manual_actions" in want and [m.kind for m in case.manual_actions] != want["manual_actions"]:
        return False
    if "contact_count" in want and case.contact_count != want["contact_count"]:
        return False
    for k, rule in (want.get("contact_constraints") or {}).items():
        t, f = k.split(".", 1)
        if not value_satisfies(case.contact_values.get((t, f)), rule):
            return False
    for table, present in (want.get("has_row") or {}).items():
        if not rows_match(result, case, table, present):
            return False
    if "emails_sent" in want and case.emails_sent != want["emails_sent"]:
        return False
    if "random" in want:
        r = want["random"]
        if case.random is None:
            return False
        if "activity_key" in r and case.random.activity_key != r["activity_key"]:
            return False
        if "expected_low" in r and case.random.expected_low != r["expected_low"]:
            return False
        if "expected_high" in r and case.random.expected_high != r["expected_high"]:
            return False
    return True


def value_satisfies(value, rule: dict) -> bool:
    """`contact_constraints`: not_null, not_in, and strict numeric bounds gt / lt (never on a bound)."""
    if rule.get("not_null") and (value is None or value == ""):
        return False
    if value in (rule.get("not_in") or []):
        return False
    if "gt" in rule or "lt" in rule:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return False
        if "gt" in rule and not number > rule["gt"]:
            return False
        if "lt" in rule and not number < rule["lt"]:
            return False
    return True


def rows_match(result, case, table: str, present: bool) -> bool:
    """`has_row`: every contact of the case has a row in the table's CSV data (True), or none has (False).

    A row belongs to a contact when one of its cells holds the contact key.
    """
    if not case.contact_keys:
        return False
    data = result.data.tables.get(table)
    rows = data.rows if data is not None else []
    found = [any(key in row.values() for row in rows) for key in case.contact_keys]
    return all(found) if present else not any(found)


@pytest.mark.parametrize("example", example_dirs(), ids=lambda d: d.name)
def test_example(example: Path):
    expected = load_expected(example)
    package_path = example / expected.get("package", "package.json")
    result = pipeline.generate(str(package_path.resolve()), settings_from(expected), with_testbook=False)
    problems = compare(result, expected)
    assert not problems, f"{example.name}:\n  " + "\n  ".join(problems)
