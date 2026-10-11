"""Trust checks (cjhelper/checks.py): each check passes on a clean run and fails on the mutation it must catch.

One small world (examples/two_levels: Master -> Target -> Config, 4 scenarios, 6 cases, 18 contacts) is
generated once; every test mutates a copy of its files or of its result objects and runs the checks again.
"""

from __future__ import annotations

import csv
import io
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from cjhelper import checks, pipeline
from cjhelper.model import Settings

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "two_levels" / "package.json"

# The order of Checker.run_all.
SCHEMA, JOINS, ENTRY, SIMULATION, COVERAGE, ADDRESSES = range(6)

C1 = "TST_R01_C0001"   # first contact of case S01-C01 (scenario TST_R01_S01, MarketingPermission True)


@pytest.fixture(scope="module")
def world():
    settings = Settings(generation_time=datetime(2026, 10, 10, 9, 0), real_inbox="qa@test.com")
    return pipeline.generate(str(EXAMPLE), settings, with_testbook=False)


def run(world, files=None, coverage=None, data=None):
    return checks.run_checks(world.package, world.table_model, coverage or world.coverage, data or world.data,
                             files if files is not None else dict(world.files), world.settings,
                             world.generation_time)


def edit(world, table, change, files=None):
    """A copy of the files (``world.files`` by default) where ``change(rows)`` has edited the rows of
    ``<table>.csv`` in place."""
    files = dict(files if files is not None else world.files)
    reader = csv.DictReader(io.StringIO(files[f"{table}.csv"].decode("utf-8"), newline=""))
    rows = list(reader)
    change(rows)
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=reader.fieldnames, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    files[f"{table}.csv"] = out.getvalue().encode("utf-8")
    return files


def set_value(key_field, key, field, value):
    def change(rows):
        for row in rows:
            if row[key_field] == key:
                row[field] = value
    return change


def drop(key_field, key):
    def change(rows):
        rows[:] = [row for row in rows if row[key_field] != key]
    return change


def failed(results, index):
    check = results[index]
    assert not check.passed, f"{check.name} should fail"
    return " | ".join(check.details)


def test_clean_run_passes_every_check(world):
    assert all(c.passed for c in world.checks), [(c.name, c.details) for c in world.checks if not c.passed]
    assert all(c.passed for c in run(world))
    assert [c.name for c in world.checks] == [
        "I valori rispettano tipo, lunghezza, null e chiave primaria",
        "Ogni chiave trova le sue righe nelle altre tabelle",
        "Le righe della tabella di ingresso corrispondono alla entry query",
        "Ogni contatto simulato dai file segue il percorso previsto",
        "Ogni branch raggiungibile è coperto e ogni branch non coperto ha un motivo",
        "Solo i contatti con un'azione manuale usano l'inbox reale, gli altri hanno indirizzi non recapitabili",
        "Due run con lo stesso input danno gli stessi file",
    ]


@pytest.mark.parametrize("table, field, value, words", [
    ("DE_Master", "FirstName", "x" * 51, "ha 51 caratteri, lo schema ne ammette 50"),   # Text(50)
    ("DE_Master", "MobilePhone", "333 abc", "non è un numero di telefono"),
    ("DE_Config", "IGNOREPERM", "Yes", "non è True o False"),
])
def test_schema_catches_length_and_type(world, table, field, value, words):
    key_field = "CampaignName" if table == "DE_Config" else "ContactId"
    key = "TST_R01_S02" if table == "DE_Config" else C1
    detail = failed(run(world, edit(world, table, set_value(key_field, key, field, value))), SCHEMA)
    assert field in detail and words in detail


@pytest.mark.parametrize("value", ["2026-10-10", "10/10/2026 09:00"])
def test_schema_catches_a_date_in_another_format(world, value):
    files = edit(world, "DE_Target", set_value("SubscriberId", C1, "CreatedDate", value))
    detail = failed(run(world, files), SCHEMA)
    assert "CreatedDate" in detail and "non è una data nel formato %Y-%m-%d %H:%M" in detail


def test_joins_catch_a_target_row_without_config_row(world):
    files = edit(world, "DE_Target", set_value("SubscriberId", C1, "CampaignName", "TST_R01_S99"))
    detail = failed(run(world, files), JOINS)
    assert "valori di DE_Target.CampaignName non hanno una riga in DE_Config.CampaignName" in detail
    assert "TST_R01_S99" in detail


def test_joins_catch_a_contact_in_two_scenarios(world):
    files = edit(world, "DE_Target", lambda rows: rows.append(
        {"SubscriberId": C1, "CampaignName": "TST_R01_S02", "CreatedDate": rows[0]["CreatedDate"]}))
    detail = failed(run(world, files), JOINS)
    assert f"il contatto {C1} è collegato a 2 righe di scenario" in detail and "più righe in DE_Target" in detail


def test_joins_and_coverage_catch_contacts_missing_from_the_files(world):
    files = None
    for table, key_field in (("DE_Entry", "ContactId"), ("DE_Master", "ContactId"), ("DE_Target", "SubscriberId")):
        files = edit(world, table, drop(key_field, C1), files)
    results = run(world, files)
    assert "contatti generati non hanno righe in DE_Master" in failed(results, JOINS)
    detail = failed(results, COVERAGE)
    assert C1 in detail and "contatti non hanno righe in DE_Entry.csv" in detail


def test_joins_catch_a_row_of_a_contact_that_was_not_generated(world):
    files = edit(world, "DE_Master", lambda rows: rows.append(dict(rows[0], ContactId="TST_R01_C9999")))
    detail = failed(run(world, files), JOINS)
    assert "TST_R01_C9999" in detail and "non sono stati generati" in detail


def test_entry_query_catches_a_value_it_would_not_produce(world):
    files = edit(world, "DE_Entry", set_value("ContactId", C1, "ActionId", "something else"))
    detail = failed(run(world, files), ENTRY)
    assert "ActionId vale 'something else' ma la entry query dà" in detail


def test_simulation_catches_a_contact_relinked_to_another_scenario(world):
    files = edit(world, "DE_Entry", set_value("ContactId", C1, "CampaignName", "TST_R01_S02"))
    files = edit(world, "DE_Target", set_value("SubscriberId", C1, "CampaignName", "TST_R01_S02"), files)
    results = run(world, files)
    assert results[JOINS].passed   # the links are consistent: only the scenario is wrong
    detail = failed(results, SIMULATION)
    assert f"il contatto {C1} (caso S01-C01) è collegato allo scenario 'TST_R01_S02'" in detail
    assert "creato per lo scenario 'TST_R01_S01'" in detail


def test_simulation_catches_a_value_that_changes_the_path(world):
    files = edit(world, "DE_Master", set_value("ContactId", C1, "MarketingPermission", "False"))
    detail = failed(run(world, files), SIMULATION)
    assert C1 in detail and "SPLIT-3/remainder_path" in detail and "invece di" in detail


@pytest.mark.parametrize("covered_by, expected", [
    (["S02-C01"], "il percorso di S02-C01 non lo attraversa"),   # a real case on SPLIT-1/path_b, not path_a
    (["S99-C01"], "cita il caso sconosciuto S99-C01"),            # no such case
])
def test_coverage_catches_a_wrong_covered_by(world, covered_by, expected):
    branches = [replace(b, covered_by=covered_by) if (b.activity_key, b.outcome_key) == ("SPLIT-1", "path_a") else b
                for b in world.coverage.branches]
    detail = failed(run(world, coverage=replace(world.coverage, branches=branches)), COVERAGE)
    assert "SPLIT-1" in detail and expected in detail


def test_addresses_catch_a_real_inbox_without_manual_action(world):
    address = f"qa+{C1}@test.com"
    files = edit(world, "DE_Entry", set_value("ContactId", C1, "Emailaddress", address))
    files = edit(world, "DE_Master", set_value("ContactId", C1, "Emailaddress", address), files)
    detail = failed(run(world, files), ADDRESSES)
    assert f"{C1} dovrebbe avere un indirizzo non recapitabile ma ha '{address}'" in detail


def test_addresses_catch_a_manual_action_without_real_inbox(world):
    contacts = [replace(c, uses_real_inbox=True) if c.key == C1 else c for c in world.data.contacts]
    detail = failed(run(world, data=replace(world.data, contacts=contacts)), ADDRESSES)
    assert f"{C1} deve usare l'inbox reale" in detail


def test_determinism_catches_a_changed_or_missing_file(world):
    first = {k: v for k, v in world.files.items() if k.endswith(".csv")}
    assert checks.check_determinism(first, dict(first)).passed
    changed = dict(first, **{"DE_Master.csv": first["DE_Master.csv"].replace(b"True", b"False", 1)})
    result = checks.check_determinism(first, changed)
    assert not result.passed and result.details == ["DE_Master.csv è diverso tra due run con lo stesso input"]
    missing = {k: v for k, v in first.items() if k != "DE_Config.csv"}
    result = checks.check_determinism(first, missing)
    assert not result.passed and result.details == ["DE_Config.csv è prodotto da uno solo dei due run"]
