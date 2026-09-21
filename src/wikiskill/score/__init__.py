"""Scoring an evaluation run. Verifier-first: deterministic checks before any model judge.

Routing (task 4.1) and deterministic verifiers (task 4.2) are implemented. The rubric judge
arrives with task 4.3 and plugs in alongside, not in front: verifiers decide pass or fail, a judge
only scores its own dimensions.
"""

from __future__ import annotations

from .derive import (
    ROUTE,
    UNMEASURED,
    VERIFIER,
    Verdict,
    comparisons,
    difference,
    drift,
    mcnemar,
    pass_rate,
    verdicts,
)
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
    "ROUTE",
    "UNMEASURED",
    "UNSCORED",
    "VERIFIER",
    "VERIFIER_TIMEOUT_S",
    "RouteScore",
    "Verdict",
    "VerifierError",
    "VerifierResult",
    "activated_names",
    "aggregate",
    "bare",
    "comparisons",
    "confusion",
    "difference",
    "drift",
    "first_activation",
    "mcnemar",
    "pass_rate",
    "resolve_in",
    "run_verifier",
    "same",
    "score_all",
    "score_group",
    "scored",
    "verdicts",
    "verify_task",
]
