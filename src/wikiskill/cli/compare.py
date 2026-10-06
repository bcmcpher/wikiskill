"""`wikiskill compare`: compare two runs of one suite across versions of a component."""

from __future__ import annotations

import argparse
import sys

from ._common import FAILED, OK, add_collection_argument


def register(sub) -> None:
    cmp = sub.add_parser(
        "compare", help="compare two runs of one suite across versions of a component"
    )
    cmp.add_argument("run_a", help="the earlier run: an id under the collection's evals, or a path")
    cmp.add_argument("run_b", help="the later run")
    add_collection_argument(cmp, required=True)
    cmp.add_argument(
        "--component", default=None, help="the component under test (default: inferred)"
    )
    cmp.add_argument(
        "--record",
        choices=("accept", "reject"),
        default=None,
        help=(
            "record these runs as the proposal's replay and this decision in the wiki's "
            "skill-impact.md; nothing is applied or reverted"
        ),
    )
    cmp.add_argument("--proposal", default=None, help="the proposal id the decision is about")
    cmp.add_argument("--note", default="", help="the reviewer's note for --record")
    cmp.set_defaults(func=cmd_compare)


def cmd_compare(args: argparse.Namespace) -> int:
    from .. import compare as compare_mod
    from .. import gate as gate_mod

    a = compare_mod.load_run(args.collection, args.run_a)
    b = compare_mod.load_run(args.collection, args.run_b)
    comparison = compare_mod.compare(a, b, component=args.component)
    out = compare_mod.output_dir(args.collection, a, b)
    md, js = compare_mod.write(comparison, out)
    print(compare_mod.render(comparison))
    print(f"wrote {md}")
    print(f"wrote {js}")
    if args.record:
        if not args.proposal:
            print("error: --record needs --proposal <id>", file=sys.stderr)
            return FAILED
        replayed = gate_mod.replay(args.collection, args.proposal, a.root, b.root)
        print(f"replayed {args.proposal}: recommendation {replayed.recommendation}")
        target = gate_mod.decide(args.collection, args.proposal, args.record, note=args.note)
        print(f"recorded {args.record} for {args.proposal} in {target}")
    return OK
