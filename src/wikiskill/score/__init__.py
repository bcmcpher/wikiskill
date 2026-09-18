"""Scoring an evaluation run. Verifier-first: deterministic checks before any model judge.

Only routing is implemented here so far (`add-explicit-eval` tasks 4.1). Verifiers and the rubric
judge arrive with tasks 4.2 and 4.3 and plug in alongside, not in front.
"""

from __future__ import annotations

from .route import (
    NONE,
    UNSCORED,
    RouteScore,
    aggregate,
    bare,
    confusion,
    first_activation,
    same,
    score_all,
    score_group,
    scored,
)

__all__ = [
    "NONE",
    "UNSCORED",
    "RouteScore",
    "aggregate",
    "bare",
    "confusion",
    "first_activation",
    "same",
    "score_all",
    "score_group",
    "scored",
]
