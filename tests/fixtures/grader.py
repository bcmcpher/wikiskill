"""A synthetic scorer for `result: json` verifiers: prints a verdict and a score it is told to.

    python3 grader.py VERDICT SCORE [--log N] [--exit CODE] [--crash] [--pad BYTES]

SCORE is parsed as JSON, so `71.5`, `null` and `"high"` all work. `--log` prints N lines before the
result, as a scorer that logs its progress does. `--crash` prints a traceback and no result.
`--pad` adds a field of that many bytes, to push the result past a size cap.
"""

from __future__ import annotations

import argparse
import json
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("verdict")
    parser.add_argument("score")
    parser.add_argument("--log", type=int, default=0)
    parser.add_argument("--exit", type=int, default=0)
    parser.add_argument("--crash", action="store_true")
    parser.add_argument("--pad", type=int, default=0)
    args = parser.parse_args()

    for number in range(args.log):
        print(f"grading step {number + 1}")
    if args.crash:
        print("Traceback (most recent call last):")
        print('  File "grader.py", line 1, in <module>')
        print("ZeroDivisionError: division by zero")
        print("the scorer gave up", file=sys.stderr)
        return 1
    result = {"verdict": args.verdict, "score": json.loads(args.score)}
    if args.pad:
        result["padding"] = "x" * args.pad
    print(json.dumps(result))
    return args.exit


if __name__ == "__main__":
    sys.exit(main())
