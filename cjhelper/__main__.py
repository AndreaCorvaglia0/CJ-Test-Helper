"""Command line: python -m cjhelper <export.json> --out <dir> [options]

Spec: until the page is built, the generator runs from the command line with the default settings.
Every file of the zip is also written into the output directory.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import outputs, pipeline
from .model import Settings


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m cjhelper", description="Test data from a Marketing Cloud package export")
    p.add_argument("export", help="package export JSON")
    p.add_argument("--out", default="output", help="output directory (default: output)")
    p.add_argument("--run-id", default="R01", help="run identifier added to every key (default R01)")
    p.add_argument("--inbox", default="", help="real inbox for open and click tests")
    p.add_argument("--phone", default="", help="real phone number")
    p.add_argument("--contacts", type=int, default=3, help="contacts per case (default 3)")
    p.add_argument("--random-contacts", type=int, default=50, help="contacts per random-split case (default 50)")
    p.add_argument("--case-insensitive", action="store_true", help="text comparisons ignore letter case")
    p.add_argument("--no-single-active", action="store_true", help="activate every scenario in the CSV at once")
    p.add_argument("--time", default=None, help="generation time YYYY-MM-DD HH:MM (default now), for reproducible runs")
    p.add_argument("--no-testbook", action="store_true", help="skip testbook.xlsx")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings(
        contacts_per_case=args.contacts, contacts_per_random_case=args.random_contacts,
        real_inbox=args.inbox, real_phone=args.phone, run_id=args.run_id,
        case_insensitive_text=args.case_insensitive,
        one_active_scenario=False if args.no_single_active else None,
        generation_time=datetime.strptime(args.time, "%Y-%m-%d %H:%M") if args.time else None,
    )
    try:
        result = pipeline.generate(args.export, settings, with_testbook=not args.no_testbook)
    except Exception as exc:  # the CLI shows a plain message, like the page will
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, content in result.files.items():
        (out / name).write_bytes(content)
    (out / "test_data.zip").write_bytes(outputs.build_zip(result.files))
    for line in pipeline.summary_lines(result):
        print(line)
    print(f"Files written to {out}/")
    return 0 if all(c.passed for c in result.checks) else 2


if __name__ == "__main__":
    sys.exit(main())
