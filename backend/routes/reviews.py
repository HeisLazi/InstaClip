"""Clip review endpoints for human ratings, reasons, and caption notes."""

from fastapi import APIRouter, Query

from backend.schemas import ClipReviewRequest

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.get("")
def list_reviews(limit: int = Query(500, ge=1, le=2000)):
    from modules.clip_reviews import list_reviews
    return {"reviews": list_reviews(limit=limit)}


@router.get("/options")
def review_options():
    from modules.clip_reviews import REASON_PRESETS
    return {
        "verdicts": ["keeper", "maybe", "miss", "undecided"],
        "reasons": REASON_PRESETS,
    }


@router.get("/{stem}")
def get_review(stem: str):
    from modules.clip_reviews import get_review
    return {"review": get_review(stem)}


@router.put("/{stem}")
def save_review(stem: str, review: ClipReviewRequest, bucket: str = "output"):
    from modules.clip_reviews import save_review
    return {"review": save_review(stem, bucket, review.model_dump())}
