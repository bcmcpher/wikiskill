"""`wikiskill review` and `wikiskill sample`: distil one component's evidence into wiki patterns."""

from __future__ import annotations

import argparse
from pathlib import Path

from ._common import FAILED, OK, add_collection_argument, load, misuse


def register(sub) -> None:
    from .. import review as review_mod

    rev = sub.add_parser("review", help="distil one component's evidence into wiki patterns")
    _add_sampling_arguments(rev)
    rev.add_argument("--retries", type=int, default=review_mod.DEFAULT_RETRIES)
    rev.add_argument("--dry-run", action="store_true", help="print the prompt and stop")
    rev.add_argument(
        "--reply-file",
        default=None,
        help="validate and apply a maintainer reply written elsewhere, e.g. in-harness",
    )
    rev.add_argument(
        "--sample",
        default=None,
        help="the `wikiskill sample` id (or directory) the --reply-file answers",
    )
    rev.set_defaults(func=cmd_review)

    sam = sub.add_parser(
        "sample", help="take and keep a review sample, for a maintainer that runs elsewhere"
    )
    _add_sampling_arguments(sam)
    sam.set_defaults(func=cmd_sample)


def _add_sampling_arguments(parser: argparse.ArgumentParser) -> None:
    from .. import review as review_mod

    parser.add_argument("component", help="e.g. datalad/datalad-doer")
    add_collection_argument(parser, required=True)
    parser.add_argument(
        "--run", action="append", default=None, help="only this run (default: every run of it)"
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=None,
        help=(
            f"prompt characters (default {review_mod.DEFAULT_BUDGET}, less for a maintainer "
            "whose `context_tokens` is under 64k)"
        ),
    )
    parser.add_argument(
        "--signals",
        type=int,
        default=review_mod.DEFAULT_SIGNALS,
        help="most pieces of evidence with a correction or failure signal",
    )
    parser.add_argument(
        "--clean",
        type=int,
        default=review_mod.DEFAULT_CLEAN,
        help="most pieces of evidence with no signal",
    )
    parser.add_argument(
        "--resample", action="store_true", help="include evidence earlier reviews were shown"
    )
    parser.add_argument(
        "--model",
        default=None,
        help="only eval units and live sessions run on this model",
    )


def _sampling(args: argparse.Namespace) -> dict:
    """The sampling options `review` and `sample` share."""
    return {
        "budget": args.budget,
        "signals": args.signals,
        "clean": args.clean,
        "resample": args.resample,
        "model": args.model,
    }


def cmd_sample(args: argparse.Namespace) -> int:
    from .. import compare as compare_mod
    from .. import review as review_mod

    coll = load(args.collection)
    runs = [compare_mod.load_run(coll.name, run) for run in args.run] if args.run else None
    try:
        found = review_mod.digest(coll, args.component, runs=runs, **_sampling(args))
    except review_mod.NothingToReview as exc:
        print(exc)
        return OK
    sample_id, directory = review_mod.save_sample(coll, found)
    print(f"sample {sample_id}")
    print(f"  prompt        {directory / 'prompt.md'}")
    print(f"  instructions  {directory / 'instructions.md'}")
    print(
        f"  evidence      {len(found.evidence)} shown, {found.omitted} waiting, "
        f"{len(found.text)} of {found.budget} characters"
    )
    print(
        f"  apply with    wikiskill review {args.component} --collection {coll.name} "
        f"--sample {sample_id} --reply-file <reply.json>"
    )
    return OK


def cmd_review(args: argparse.Namespace) -> int:
    from .. import compare as compare_mod
    from .. import review as review_mod
    from .. import roles as roles_mod

    coll = load(args.collection)
    runs = [compare_mod.load_run(coll.name, run) for run in args.run] if args.run else None
    if args.sample and not args.reply_file:
        return misuse("--sample needs --reply-file")
    if args.sample and args.model:
        return misuse(
            "--model chooses evidence when a sample is taken; --sample keeps the evidence it was "
            "taken with. Take a new one with `wikiskill sample --model`"
        )
    try:
        sample = review_mod.load_sample(coll, args.sample) if args.sample else None
        if sample and sample.component != args.component:
            raise review_mod.ReviewError(
                f"sample {args.sample} is of {sample.component}, not {args.component}"
            )
        if args.dry_run:
            found = sample or review_mod.digest(coll, args.component, runs=runs, **_sampling(args))
            print(found.text)
            print(
                f"--- {len(found.text)} characters, {len(found.evidence)} pieces of evidence, "
                f"{found.omitted} omitted, runs: {', '.join(found.runs) or 'none'}"
            )
            return OK
        if args.reply_file:
            replies = iter([Path(args.reply_file).read_text(encoding="utf-8")])
            ask = lambda _messages: next(replies)  # noqa: E731
            maintainer, retries = f"reply file {args.reply_file}", 0
        else:
            ask, maintainer = roles_mod.role_asker(coll, "maintainer")
            retries = args.retries
        outcome = review_mod.review(
            coll,
            args.component,
            ask=ask,
            maintainer=maintainer,
            runs=runs,
            retries=retries,
            sample=sample,
            **_sampling(args),
        )
    except review_mod.NothingToReview as exc:
        print(exc)
        return OK
    return _report_review(args.component, coll.name, outcome)


def _report_review(component: str, collection: str, outcome) -> int:
    from .. import wiki as wiki_mod

    if outcome.applied is None:
        print(
            f"no pattern written: the reply failed validation after {outcome.attempts} "
            f"attempt(s); the failure is in {wiki_mod.wiki_root(collection) / wiki_mod.LOG}"
        )
        for problem in outcome.problems:
            print(f"  - {problem}")
        return FAILED
    applied = outcome.applied
    print(f"review of {component} applied after {outcome.attempts} attempt(s)")
    print(f"  created  {', '.join(applied.created) or 'none'}")
    print(f"  updated  {', '.join(applied.updated) or 'none'}")
    if applied.superseded:
        print(f"  retired  {', '.join(applied.superseded)}")
    note = "" if applied.committed else " (not committed)"
    print(f"  wiki     {wiki_mod.wiki_root(collection)}{note}")
    for warning in applied.warnings:
        print(f"  warning: {warning}")
    return OK
