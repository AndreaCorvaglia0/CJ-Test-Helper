"""One call from export to files: load, select tables, cover, generate, write, check, report."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from . import checks, coverage, datagen, loader, outputs, tables
from .model import GenerationResult, Settings


def _data_files(package, table_model, cov, settings, now) -> tuple[dict[str, bytes], object]:
    data = datagen.generate_data(package, table_model, cov, settings, now)
    files: dict[str, bytes] = {}
    for name in table_model.selected_tables:
        table_data = data.tables.get(name)
        if table_data is not None:
            files[f"{name}.csv"] = outputs.write_table_csv(table_data, package.tables[name])
    files["scenarios.csv"] = outputs.write_scenarios_csv(data.scenarios_rows)
    return files, data


def generate(source, settings: Optional[Settings] = None, with_testbook: bool = True) -> GenerationResult:
    settings = settings or Settings()
    now = settings.generation_time or datetime.now().replace(second=0, microsecond=0)

    package = loader.load_package(source)
    table_model = tables.build_table_model(package)
    cov = coverage.compute_coverage(package, table_model, settings, now)
    files, data = _data_files(package, table_model, cov, settings, now)

    results = checks.run_checks(package, table_model, cov, data, files, settings, now)

    # Determinism: everything after loading is run a second time and must give the same bytes.
    cov2 = coverage.compute_coverage(package, table_model, settings, now)
    files2, _ = _data_files(package, table_model, cov2, settings, now)
    results.append(checks.check_determinism(files, files2))

    result = GenerationResult(package=package, table_model=table_model, coverage=cov, data=data,
                              checks=results, settings=settings, files=files, generation_time=now)
    if with_testbook:
        files["testbook.xlsx"] = outputs.write_testbook(result)
    files["report.md"] = outputs.write_report(result).encode("utf-8")
    return result


def summary_lines(result: GenerationResult) -> list[str]:
    s = result.coverage.stats
    lines = [
        f"Journey: {result.package.journey.name} ({result.package.journey.activity_count} activities)",
        f"Scenarios: {s.get('scenarios', 0)}  Cases: {s.get('cases', 0)}  Contacts: {s.get('contacts', 0)}",
        f"Branches: {s.get('covered', 0)} covered, {s.get('covered_manual', 0)} covered with manual action, "
        f"{s.get('not_covered', 0)} not covered",
        "Tables: " + ", ".join(result.table_model.selected_tables),
    ]
    for c in result.checks:
        lines.append(("PASS  " if c.passed else "FAIL  ") + c.name)
    return lines
