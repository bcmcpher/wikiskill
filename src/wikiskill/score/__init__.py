"""Scoring an evaluation run. Verifier-first: deterministic checks before any model judge.

Routing (task 4.1) and deterministic verifiers (task 4.2) are implemented. The rubric judge
arrives with task 4.3 and plugs in alongside, not in front: verifiers decide pass or fail, a judge
only scores its own dimensions.
"""

from __future__ import annotations

from .route import (
    NONE,
    UNSCORED,
    RouteScore,
    activated_names,
    aggregate,
    bare,
    confusion,
    first_activation,
    same,
    score_all,
    score_group,
    scored,
)
from .verify import (
    VERIFIER_TIMEOUT_S,
    VerifierError,
    VerifierResult,
    resolve_in,
    run_verifier,
    verify_task,
)

__all__ = [
    "NONE",
    "UNSCORED",
    "VERIFIER_TIMEOUT_S",
    "RouteScore",
    "VerifierError",
    "VerifierResult",
    "activated_names",
    "aggregate",
    "bare",
    "confusion",
    "first_activation",
    "resolve_in",
    "run_verifier",
    "same",
    "score_all",
    "score_group",
    "scored",
    "verify_task",
]
