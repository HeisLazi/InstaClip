"""Stage-2 budget for automatic clip materialization.

Stage 1 keeps every detected moment in metadata so it remains searchable and can
be rendered later. Stage 2 limits the files produced by unattended runs to the
same ranked budget promoted into the Clip Room.
"""

from __future__ import annotations

from typing import Any

DEFAULT_AUTO_CUT_TOP = 12


def _candidate_score(candidate: dict[str, Any]) -> float:
    for key in ("final_score", "quality_score", "peak_score", "score"):
        value = candidate.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


def select_auto_cut_candidates(
    highlights: list[dict[str, Any]],
    limit: int = DEFAULT_AUTO_CUT_TOP,
) -> list[dict[str, Any]]:
    """Return the top ranked physical cuts without mutating Stage-1 metadata."""
    budget = max(0, int(limit))
    if budget == 0:
        return []
    return sorted(highlights, key=_candidate_score, reverse=True)[:budget]


__all__ = ["DEFAULT_AUTO_CUT_TOP", "select_auto_cut_candidates"]
