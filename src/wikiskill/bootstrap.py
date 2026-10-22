"""A seeded percentile bootstrap of a mean, for graded scores reported beside a pass rate.

A grader's score is bounded and lumpy: scores pile up at 0 and at 100, and a task has three or five
repeats. A t-interval assumes neither, so it runs past the scale's ends and is too narrow at small
n. Resampling the scores themselves needs no such assumption.

The seed is fixed, so the same scores give the same interval every time a report is rebuilt, and a
committed table never goes stale on a reroll.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

RESAMPLES = 2000
SEED = 0
#: Two-sided coverage of the interval.
LEVEL = 0.95


def mean_interval(
    values: Sequence[float], *, resamples: int = RESAMPLES, seed: int = SEED
) -> tuple[float, float, float] | None:
    """``(mean, low, high)`` of ``values``, with a 95% percentile bootstrap interval of the mean.

    `None` for no values. One value, or values that are all the same, give an interval of no width:
    there is nothing to resample, and the caller says so rather than printing a range.
    """
    if not values:
        return None
    n = len(values)
    mean = sum(values) / n
    if n == 1 or min(values) == max(values):
        return mean, mean, mean
    draw = random.Random(seed)
    means = sorted(sum(draw.choices(values, k=n)) / n for _ in range(resamples))
    tail = (1 - LEVEL) / 2
    # Every resampled mean lies inside the data's range; rounding can leave one a hair outside.
    low = max(min(values), _percentile(means, tail))
    high = min(max(values), _percentile(means, 1 - tail))
    return mean, low, high


def _percentile(ordered: Sequence[float], fraction: float) -> float:
    """Linear interpolation between the closest ranks, as numpy's default does."""
    position = fraction * (len(ordered) - 1)
    below = int(position)
    above = min(below + 1, len(ordered) - 1)
    weight = position - below
    return ordered[below] * (1 - weight) + ordered[above] * weight
