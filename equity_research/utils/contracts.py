"""Error-handling contract for all financial computation modules.

Every function that fetches or computes financial data returns (or embeds) a
``ComputationResult`` so the report can render gracefully with "Data Not
Available" sections instead of crashing. Nothing in the pipeline may silently
return 0 for missing data — missing inputs surface as ``value=None`` plus a
specific warning naming the field and source attempted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ComputationResult:
    """Standard result wrapper for a single computed financial quantity.

    Attributes:
        value:              The computed value, or None if computation failed.
        is_reliable:        False when data gaps forced substitutions/fallbacks.
        data_quality_score: 0–1; fraction of required inputs that were available.
        warnings:           Specific, human-readable warnings shown in the report.
        error:              Set only when the computation failed entirely.
    """

    value: Optional[float]
    is_reliable: bool = True
    data_quality_score: float = 1.0
    warnings: list[str] = field(default_factory=list)
    error: Optional[str] = None

    @classmethod
    def failed(cls, error: str) -> "ComputationResult":
        """Construct a fully-failed result with a descriptive error."""
        return cls(value=None, is_reliable=False, data_quality_score=0.0, error=error)


class ValuationError(ValueError):
    """Raised when a valuation model cannot produce an economically valid result
    (e.g. WACC <= terminal growth would imply a negative terminal value)."""
