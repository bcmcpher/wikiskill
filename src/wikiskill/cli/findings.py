"""`wikiskill findings`: keep a study's runs in the repo, and make its tables from them."""

from __future__ import annotations

import argparse

from ._common import FAILED, OK, misuse


def register(sub) -> None:
    findings = sub.add_parser(
        "findings", help="bundle a study's runs into the repo, and make its tables and data"
    )
    actions = findings.add_subparsers(dest="action", required=True)

    bundle = actions.add_parser(
        "bundle", help="copy each run's run.json and results.jsonl into the study; no transcripts"
    )
    bundle.add_argument("study", help="the study directory, holding findings.toml")
    bundle.set_defaults(func=cmd_bundle)

    add = actions.add_parser("add", help="add one run to the study's findings.toml")
    add.add_argument("study", help="the study directory, holding findings.toml")
    add.add_argument("run_id")
    add.add_argument("--role", required=True, help="the run's role, which tables draw on")
    add.add_argument("--label", default=None, help="the component version's name on a board")
    add.set_defaults(func=cmd_add)

    tables = actions.add_parser(
        "tables", help="make every declared table, the slide-sized ones, and findings.csv"
    )
    tables.add_argument("study", help="the study directory, holding findings.toml")
    tables.add_argument(
        "--check",
        action="store_true",
        help="write nothing; fail when a generated file differs from what the bundle gives",
    )
    tables.set_defaults(func=cmd_tables)


def cmd_bundle(args: argparse.Namespace) -> int:
    from .. import findings

    study = findings.load(args.study)
    result = findings.bundle(study)
    for run_id in result.copied:
        print(f"  + {run_id}")
    if result.kept:
        print(f"  {len(result.kept)} already bundled")
    for run_id in result.missing:
        print(f"  ? {run_id}: not found in the collection's evals; bundle the rest")
    for run_id in result.changed:
        print(f"  ! {run_id}: the bundled copy differs from its source; left as it was")
    return FAILED if result.changed or result.missing else OK


def cmd_add(args: argparse.Namespace) -> int:
    from .. import findings

    try:
        findings.add(args.study, args.run_id, args.role, args.label)
    except findings.FindingsError as exc:
        return misuse(str(exc))
    print(f"added {args.run_id} ({args.role}) to {args.study}/findings.toml")
    return OK


def cmd_tables(args: argparse.Namespace) -> int:
    from .. import findings

    study = findings.load(args.study)
    rendered = findings.render(study)
    if args.check:
        stale = findings.stale(study, rendered)
        for relative in stale:
            print(f"  stale: {relative}")
        if stale:
            print(f"run `wikiskill findings tables {args.study}` to regenerate")
            return FAILED
        print(f"all {len(rendered.files)} generated files are current")
        return OK
    for path in findings.write(study, rendered):
        print(f"wrote {path}")
    return OK
