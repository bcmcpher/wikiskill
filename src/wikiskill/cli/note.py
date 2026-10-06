"""`wikiskill note`: record what a skill or agent got wrong, in its session."""

from __future__ import annotations

import argparse
import sys

from ._common import FAILED, OK, add_collection_argument, named_or_every


def register(sub) -> None:
    note = sub.add_parser(
        "note", help="record an explicit note on what a skill or agent got wrong, in its session"
    )
    note.add_argument("text", nargs="+", help="the note, as you would say it")
    note.add_argument(
        "--component",
        default=None,
        help="the component it is about, e.g. preregister or agent:datalad-doer "
        "(default: the session's last activated)",
    )
    note.add_argument(
        "--session",
        default=None,
        help="the session it is about (default: the most recent logged one in this directory)",
    )
    add_collection_argument(note, "only this collection (default: every one logging it)")
    note.set_defaults(func=cmd_note)


def cmd_note(args: argparse.Namespace) -> int:
    from .. import corrections as corrections_mod

    text = " ".join(args.text)
    collections = named_or_every(args.collection)
    if not collections:
        print("error: no collection manifests to attach a note to", file=sys.stderr)
        return FAILED
    # Without --collection, the note goes to every collection logging the session, as the logger
    # writes every other event to each of them.
    written, problems = [], []
    for coll in collections:
        try:
            note = corrections_mod.write_note(
                coll, text, session=args.session, component=args.component
            )
        except corrections_mod.NoteError as exc:
            problems.append(f"{coll.name}: {exc}")
            continue
        written.append((coll, note))
    if not written:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return FAILED
    for coll, note in written:
        component = note.event.get("component") or {}
        label = f"{component['kind']}:{component['name']}" if component else "no component"
        print(f"note  {coll.name}  {note.event['session_id']}  {label}")
        for warning in note.warnings:
            print(f"  warning: {warning}", file=sys.stderr)
    return OK
