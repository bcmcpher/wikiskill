"""`wikiskill graph`: build and read the collection's relation graph."""

from __future__ import annotations

import argparse
import json
from typing import TYPE_CHECKING

from ._common import OK, add_collection_argument, load

if TYPE_CHECKING:
    from ..graph import Graph


def register(sub) -> None:
    from .. import graph as graph_mod

    graph_cmd = sub.add_parser("graph", help="build and read the collection's relation graph")
    actions = graph_cmd.add_subparsers(dest="action", required=True)
    build_graph = actions.add_parser(
        "build", help="rebuild graph.json from the sources and eval runs, and commit it"
    )
    build_graph.add_argument(
        "--run",
        action="append",
        default=None,
        metavar="RUN",
        help="read only this run (repeatable; default every run of the collection)",
    )
    build_graph.set_defaults(func=cmd_graph_build)
    show = actions.add_parser("show", help="print the stored graph")
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=cmd_graph_show)
    near = actions.add_parser("neighbours", help="a component's depth-1 neighbours")
    near.add_argument("component")
    near.add_argument(
        "--min-conflict",
        type=float,
        default=graph_mod.MIN_CONFLICT,
        help="smallest confusion rate that makes a neighbour (default 0.05)",
    )
    near.set_defaults(func=cmd_graph_neighbours)
    for action in (build_graph, show, near):
        add_collection_argument(action, required=True)


def _stored_graph(collection: str) -> Graph:
    from .. import graph as graph_mod
    from .. import wiki as wiki_mod

    found = graph_mod.load(collection)
    if found is None:
        raise wiki_mod.WikiError(
            f"{collection} has no graph yet; run `wikiskill graph build --collection {collection}`"
        )
    return found


def cmd_graph_build(args: argparse.Namespace) -> int:
    from .. import graph as graph_mod

    found = graph_mod.build(load(args.collection), args.run or None)
    target = graph_mod.write(found)
    print(graph_mod.render(found))
    print(f"\nwrote {target}")
    return OK


def cmd_graph_show(args: argparse.Namespace) -> int:
    from .. import graph as graph_mod

    found = _stored_graph(args.collection)
    if args.json:
        print(json.dumps(found.as_dict(), indent=2))
    else:
        print(graph_mod.render(found))
    return OK


def cmd_graph_neighbours(args: argparse.Namespace) -> int:
    from .. import graph as graph_mod

    found = _stored_graph(args.collection)
    neighbours = found.neighbours(args.component, min_conflict=args.min_conflict)
    print(graph_mod.render_neighbours(args.component, neighbours))
    return OK
