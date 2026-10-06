"""`wikiskill install`: install built components and the harness logger."""

from __future__ import annotations

import argparse
from pathlib import Path

from ._common import OK, add_collection_argument, collection_for


def register(sub) -> None:
    from ..build import HARNESSES
    from ..install import SCOPES

    inst = sub.add_parser("install", help="install built components and the harness logger")
    inst.add_argument("--harness", choices=HARNESSES, required=True)
    inst.add_argument("--scope", choices=SCOPES, required=True)
    add_collection_argument(inst)
    inst.add_argument("--target", default=None, help="override the harness config directory")
    inst.add_argument("--uninstall", action="store_true", help="remove exactly what was installed")
    inst.add_argument("--force", action="store_true", help="on uninstall, remove changed files too")
    inst.set_defaults(func=cmd_install)


def cmd_install(args: argparse.Namespace) -> int:
    from .. import install as install_mod

    target = Path(args.target).expanduser() if args.target else None
    if args.uninstall:
        result = install_mod.uninstall(args.harness, args.scope, target=target, force=args.force)
        print(f"uninstalled from {result.target}")
        for path in result.removed:
            print(f"  removed  {path}")
        for warning in result.warnings:
            print(f"  warning: {warning}")
        print(f"  {len(result.removed)} removed, {len(result.skipped)} left in place")
        return OK

    coll = collection_for(args.collection)
    result = install_mod.install(args.harness, args.scope, collection=coll, target=target)
    print(f"installed {args.harness} components into {result.target}")
    for path in result.written:
        print(f"  wrote     {path}")
    for path in result.removed:
        print(f"  removed   {path}")
    if not result.changed:
        print("  no changes")
    print(f"  {len(result.unchanged)} unchanged")
    for note in result.notes:
        print(f"  {note}")
    for warning in result.warnings:
        print(f"  warning: {warning}")
    print(f"  record    {result.record}")
    print(f"  wikiskill {install_mod.resolved_cli_path()}")
    return OK
