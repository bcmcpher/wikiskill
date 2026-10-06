"""`wikiskill refine`: propose one patch to one component; never apply it."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING

from ._common import FAILED, OK, add_collection_argument, load, misuse

if TYPE_CHECKING:
    from ..collection import Collection


def register(sub) -> None:
    from .. import review as review_mod

    ref = sub.add_parser("refine", help="propose one patch to one component; never applies it")
    ref.add_argument("component", help="e.g. datalad/datalad-doer")
    add_collection_argument(ref, required=True)
    ref.add_argument("--retries", type=int, default=review_mod.DEFAULT_RETRIES)
    ref.add_argument(
        "--budget", type=int, default=None, help="characters of evidence in the prompt"
    )
    ref.add_argument("--dry-run", action="store_true", help="print the prompt and stop")
    ref.add_argument(
        "--prepare",
        action="store_true",
        help="persist the prompt for a proposer run elsewhere, e.g. in-harness, and stop",
    )
    ref.add_argument(
        "--prompt", default=None, help="the --prepare id (or directory) the --reply-file answers"
    )
    ref.add_argument(
        "--reply-file", default=None, help="validate a proposer reply written elsewhere"
    )
    ref.add_argument(
        "--allow-overlap",
        action="store_true",
        help="accept text the leakage check matched; recorded with the proposal",
    )
    ref.set_defaults(func=cmd_refine)


def cmd_refine(args: argparse.Namespace) -> int:
    from .. import refine as refine_mod
    from .. import roles as roles_mod

    coll = load(args.collection)
    if args.prompt and not args.reply_file:
        return misuse("--prompt needs --reply-file")
    found = (
        refine_mod.load_prompt(coll, args.component, args.prompt)
        if args.prompt
        else refine_mod.context(coll, args.component, budget=args.budget)
    )
    if args.dry_run or args.prepare:
        return _prepare_prompt(args, coll, found)
    if args.reply_file:
        replies = iter([Path(args.reply_file).read_text(encoding="utf-8")])
        ask = lambda _messages: next(replies)  # noqa: E731
        proposer, retries = f"reply file {args.reply_file}", 0
    else:
        ask, proposer = roles_mod.role_asker(coll, "proposer")
        retries = args.retries
    proposal = refine_mod.refine(
        coll,
        args.component,
        ask=ask,
        proposer=proposer,
        retries=retries,
        found=found,
        allow_overlap=args.allow_overlap,
    )
    if proposal.action == "failed":
        print(f"no proposal: the reply failed validation after {proposal.attempts} attempt(s)")
        for problem in proposal.problems:
            print(f"  - {problem}")
        return FAILED
    if proposal.action == "no_action":
        print(f"no_action for {args.component}: {proposal.reason}")
        return OK
    directory = proposal.directory
    assert directory is not None, "a patch proposal is always written to a directory"
    print(f"proposal {directory.name} for {args.component}: {directory}")
    print(f"  patterns  {', '.join(proposal.patterns)}")
    print(f"  why       {proposal.reason}")
    print(f"  read      {directory / 'preview.md'}")
    print("  nothing has been applied")
    return OK


def _prepare_prompt(args: argparse.Namespace, coll: Collection, found) -> int:
    """Print the proposer prompt, or persist it for a proposer run elsewhere."""
    from .. import refine as refine_mod

    if args.dry_run:
        print(found.prompt)
        return OK
    if not found.patterns:
        print(f"no_action for {args.component}: the wiki holds no pattern for it")
        return OK
    prompt_id, directory = refine_mod.save_prompt(coll, found)
    print(f"prompt {prompt_id}")
    print(f"  prompt        {directory / 'prompt.md'}")
    print(f"  instructions  {directory / 'instructions.md'}")
    print(f"  evidence      {len(found.evidence.evidence)} shown")
    print(
        f"  apply with    wikiskill refine {args.component} --collection {coll.name} "
        f"--prompt {prompt_id} --reply-file <reply.json>"
    )
    return OK
