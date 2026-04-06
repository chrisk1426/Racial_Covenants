"""
/detections endpoints — submit and retrieve researcher review decisions.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class ReviewIn(BaseModel):
    reviewer: str | None = None
    # confirmed | false_positive | needs_review
    decision: str
    notes: str | None = None
    grantor_grantee: str | None = None
    property_info: str | None = None


class ReviewOut(BaseModel):
    id: int
    detection_id: int
    reviewer: str | None
    decision: str
    notes: str | None
    grantor_grantee: str | None
    property_info: str | None
    reviewed_at: str


@router.post("/{detection_id}/review", response_model=ReviewOut)
def submit_review(detection_id: int, body: ReviewIn) -> ReviewOut:
    """
    Submit or update a researcher's review decision for a detection.

    If a review already exists for this detection, it is updated (upsert).
    This is the endpoint called when Trevor clicks "Confirm Covenant" or
    "False Positive" in the results UI.
    """
    from src.database import get_session
    from src.database.models import Detection, Review

    valid_decisions = {"confirmed", "false_positive", "needs_review"}
    if body.decision not in valid_decisions:
        raise HTTPException(
            status_code=422,
            detail=f"decision must be one of: {', '.join(sorted(valid_decisions))}",
        )

    with get_session() as session:
        detection = session.query(Detection).filter_by(id=detection_id).first()
        if not detection:
            raise HTTPException(status_code=404, detail="Detection not found")

        # Upsert: update existing review or create new one
        review = session.query(Review).filter_by(detection_id=detection_id).first()
        if review:
            review.decision = body.decision
            review.reviewer = body.reviewer
            review.notes = body.notes
            review.grantor_grantee = body.grantor_grantee
            review.property_info = body.property_info
        else:
            review = Review(
                detection_id=detection_id,
                reviewer=body.reviewer,
                decision=body.decision,
                notes=body.notes,
                grantor_grantee=body.grantor_grantee,
                property_info=body.property_info,
            )
            session.add(review)
        session.flush()

        return ReviewOut(
            id=review.id,
            detection_id=review.detection_id,
            reviewer=review.reviewer,
            decision=review.decision,
            notes=review.notes,
            grantor_grantee=review.grantor_grantee,
            property_info=review.property_info,
            reviewed_at=review.reviewed_at.isoformat(),
        )


@router.get("/{detection_id}/review", response_model=ReviewOut | None)
def get_review(detection_id: int) -> ReviewOut | None:
    """Return the current review for a detection, or null if unreviewed."""
    from src.database import get_session
    from src.database.models import Review

    with get_session() as session:
        review = session.query(Review).filter_by(detection_id=detection_id).first()
        if not review:
            return None
        return ReviewOut(
            id=review.id,
            detection_id=review.detection_id,
            reviewer=review.reviewer,
            decision=review.decision,
            notes=review.notes,
            grantor_grantee=review.grantor_grantee,
            property_info=review.property_info,
            reviewed_at=review.reviewed_at.isoformat(),
        )
