"""Command line: python -m cjtest {analyze,generate} PACKAGE.json"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

from . import engine, generator, outputs, package_loader, profile, static_checks

PROFILES_DIR = Path("profiles")


def _profile_path(pkg, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    safe = re.sub(r"[^\w.-]", "_", pkg.journey.name)
    return PROFILES_DIR / f"{safe}.json"


def _load_profile(pkg, explicit: str | None) -> tuple[dict, Path, bool]:
    path = _profile_path(pkg, explicit)
    if path.exists():
        return profile.load(path), path, False
    prof = profile.infer(pkg)
    profile.save(prof, path)
    return prof, path, True


def cmd_analyze(args) -> int:
    pkg = package_loader.load(args.package)
    prof, ppath, created = _load_profile(pkg, args.profile)
    j = pkg.journey
    types: dict[str, int] = {}
    for a in j.activities.values():
        types[a.type] = types.get(a.type, 0) + 1
    print(f"Journey: {j.name} ({len(j.activities)} activities, entry mode {j.entry_mode})")
    print("Activities: " + ", ".join(f"{k} {v}" for k, v in sorted(types.items())))
    print(f"Entry DE: {pkg.entry_de}  populated by: {prof['entry'].get('automation') or '-'}")
    print(f"DEs to load: {', '.join(prof['injection_des'])}")
    print(f"Profile: {ppath} ({'created, please review' if created else 'existing'})")
    for n in prof.get("notes", []):
        print(f"  note: {n}")
    for w in pkg.warnings:
        print(f"  warning: {w}")
    eng = engine.Engine(pkg, prof)
    print(f"Scenario-level variables: {', '.join(v[1] for v in eng.scenario_vars) or '-'}")
    print(f"Contact-level variables: {', '.join(v[1] for v in eng.contact_vars) or '-'}")
    print("\nStatic checks:")
    for f in static_checks.run(pkg):
        print(f"  [{f.severity}] {f.code}: {f.message}")
    return 0


def cmd_generate(args) -> int:
    pkg = package_loader.load(args.package)
    prof, ppath, created = _load_profile(pkg, args.profile)
    if created:
        print(f"Profile created at {ppath}: review it, then run generate again.")
        return 2
    run_id = args.run_id or dt.datetime.now().strftime("%y%m%d%H%M")
    print(f"Deriving test cases for {pkg.journey.name}...")
    result = engine.Engine(pkg, prof).derive()
    ds = generator.Generator(pkg, prof, result, run_id).build()
    findings = static_checks.run(pkg, result.unreachable_engagement)
    out = Path(args.out) / f"{run_id}_{re.sub(r'[^\w.-]', '_', pkg.journey.name)}"
    files = outputs.write_run(out, pkg, prof, result, ds, findings)
    path_s = [s for s in result.scenarios if s.kind == "path"]
    print(f"Scenarios: {len(path_s)} path + {len(result.scenarios) - len(path_s)} statistical; "
          f"cases: {sum(len(s.cases) for s in path_s)}; "
          f"outcomes covered {len(result.covered)}/{len(result.goals)}")
    print(f"Output: {out}")
    for k in ("testbook", "matrix", "report"):
        print(f"  {k}: {files[k].name}")
    if ds.errors:
        print(f"\n{len(ds.errors)} validation errors (see report.md):", file=sys.stderr)
        for e in ds.errors[:20]:
            print(f"  {e}", file=sys.stderr)
        return 1
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cjtest", description="Synthetic test datasets for SFMC journeys")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn, help_ in (("analyze", cmd_analyze, "show the journey structure and static checks"),
                            ("generate", cmd_generate, "derive test cases and write the test run")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("package", help="Package Manager export (JSON)")
        p.add_argument("--profile", help="test profile JSON (default: profiles/<journey>.json)")
        p.set_defaults(fn=fn)
        if name == "generate":
            p.add_argument("--out", default="runs", help="output folder (default: runs)")
            p.add_argument("--run-id", help="run identifier (default: yyMMddHHmm)")
    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except (package_loader.PackageError, generator.GenerationError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
