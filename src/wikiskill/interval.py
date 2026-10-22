"""A 95% t-interval of a mean, for graded scores reported beside a pass rate.

A task has three or five repeats. At that n a percentile bootstrap under-covers badly: it can never
reach past the observed scores, so 60, 70 and 80 give [60, 80]. The t-interval widens for small n
as it should, giving about [45.2, 94.8] for the same scores, and it is deterministic, so a rebuilt
report gives the same interval with no seed to keep. It is not clipped to the grader's scale: an
interval past 0 or 100 says the n is too small to say much, which is the honest reading.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

#: Two-sided coverage of the interval.
LEVEL = 0.95

#: t(0.975) by degrees of freedom, 1 to 30. Past 30 the normal 1.96 is used: t(0.975, 30) is 2.042,
#: and the gap shrinks from there, small beside the spread of a handful of scores.
_T975 = (
    12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
    2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
    2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042,
)  # fmt: skip
_Z975 = 1.96


def t975(df: int) -> float:
    """The t quantile a 95% two-sided interval needs, at ``df`` degrees of freedom."""
    return _T975[df - 1] if df <= len(_T975) else _Z975


def mean_interval(values: Sequence[float]) -> tuple[float, float | None, float | None] | None:
    """``(mean, low, high)`` of ``values``: mean ± t(0.975, n-1)·s/√n.

    `None` for no values. One value has no spread to estimate, so its bounds are `None`. Values that
    are all the same give an interval of no width, which the caller marks rather than prints as a
    range.
    """
    if not values:
        return None
    n = len(values)
    mean = math.fsum(values) / n
    if n == 1:
        return mean, None, None
    spread = math.sqrt(math.fsum((value - mean) ** 2 for value in values) / (n - 1))
    half = t975(n - 1) * spread / math.sqrt(n)
    return mean, mean - half, mean + half
