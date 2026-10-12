"""Command line: python -m cjhelper <export.json> --out <dir> [options]

Spec: until the page is built, the generator runs from the command line with the default settings.
Every file of the zip is also written into the output directory.

Spec, "Extensions beyond the pilot": with a Run Once entry source "All scenarios enter together, so 'one
active scenario at a time' is not offered": the setting is off whatever the options say. When unsupported
elements leave branches not covered, the summary opens with that warning, as report.md does.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import loader, outputs, pipeline
from .model import ENTRY_RUN_ONCE, Settings


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m cjhelper", description="Dati di test dall'export di un package di Marketing Cloud")
    p.add_argument("export", help="file JSON dell'export del package")
    p.add_argument("--out", default="output", help="cartella in cui scrivere i file (default: output)")
    p.add_argument("--run-id", default="R01", help="run identifier aggiunto a ogni chiave (default: R01)")
    p.add_argument("--inbox", default="", help="inbox reale per i test di open e click")
    p.add_argument("--phone", default="", help="numero di telefono reale")
    p.add_argument("--contacts", type=int, default=3, help="contatti per caso (default: 3)")
    p.add_argument("--random-contacts", type=int, default=50, help="contatti per caso di random split (default: 50)")
    p.add_argument("--case-insensitive", action="store_true", help="i confronti di testo non distinguono maiuscole e minuscole")
    p.add_argument("--no-single-active", action="store_true",
                   help="rende attivi nel CSV tutti gli scenari insieme (sempre così con un'entry source Run Once)")
    p.add_argument("--time", default=None, help="ora di generazione nella forma YYYY-MM-DD HH:MM (default: adesso), per run riproducibili")
    p.add_argument("--no-testbook", action="store_true", help="non genera testbook.xlsx")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        generation_time = datetime.strptime(args.time, "%Y-%m-%d %H:%M") if args.time else None
    except ValueError:
        print(f"Errore: --time va scritto nella forma YYYY-MM-DD HH:MM, non {args.time!r}", file=sys.stderr)
        return 1
    try:
        package = loader.load_package(args.export)
        run_once = package.entry_event is not None and package.entry_event.kind == ENTRY_RUN_ONCE
        settings = Settings(
            contacts_per_case=args.contacts, contacts_per_random_case=args.random_contacts,
            real_inbox=args.inbox, real_phone=args.phone, run_id=args.run_id,
            case_insensitive_text=args.case_insensitive,
            one_active_scenario=False if args.no_single_active or run_once else None,
            generation_time=generation_time,
        )
        result = pipeline.generate(args.export, settings, with_testbook=not args.no_testbook)
    except Exception as exc:  # the CLI shows a plain message, like the page will
        print(f"Errore: {exc}", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, content in result.files.items():
        (out / name).write_bytes(content)
    (out / "test_data.zip").write_bytes(outputs.build_zip(result.files))
    warning = outputs.unsupported_warning(result)
    if warning:
        print(f"Attenzione: {warning} {outputs.REPORT_FILE} spiega il motivo.")
    for line in pipeline.summary_lines(result):
        print(line)
    print(f"File scritti in {out}/")
    return 0 if all(c.passed for c in result.checks) else 2


if __name__ == "__main__":
    sys.exit(main())
