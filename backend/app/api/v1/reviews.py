from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_authenticated_account
from app.db.database import get_db
from app.models import Owner, PG, PGUserReview, PGUserReviewEvent
from app.schemas.reviews import (
    PGReviewCreate,
    PGReviewOut,
    PGReviewReceiptOut,
    PGReviewUpdate,
)
from app.services.listing_visibility import public_owner_eligibility
from app.services.notifications import notify_admins


router = APIRouter(tags=["PG Reviews"])


def _get_public_pg(db: Session, pg_id: int) -> PG:
    pg = db.scalar(
        select(PG).where(
            PG.id == pg_id,
            PG.is_active.is_(True),
            PG.verification_status == "verified",
            public_owner_eligibility(),
        )
    )
    if pg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PG listing not found",
        )
    return pg


def _owned_review(db: Session, author: Owner, review_id: int) -> PGUserReview:
    review = db.scalar(
        select(PGUserReview)
        .where(
            PGUserReview.id == review_id,
            PGUserReview.author_id == author.id,
        )
        .with_for_update()
    )
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found",
        )
    return review


@router.post(
    "/pgs/{pg_id}/reviews",
    response_model=PGReviewReceiptOut,
    status_code=status.HTTP_201_CREATED,
)
def create_pg_review(
    pg_id: int,
    payload: PGReviewCreate,
    author: Owner = Depends(get_authenticated_account),
    db: Session = Depends(get_db),
):
    pg = _get_public_pg(db, pg_id)
    if pg.owner_id == author.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Listing owners cannot review their own PG",
        )
    review = PGUserReview(
        pg_id=pg_id,
        author_id=author.id,
        rating=payload.rating,
        text=payload.text,
        status="pending",
    )
    now = datetime.now(timezone.utc)
    review.created_at = now
    review.updated_at = now
    try:
        db.add(review)
        db.flush()
        notify_admins(
            db,
            notification_type="pg_review_submitted",
            title="PG review needs moderation",
            message="A user submitted a PG review for moderation.",
            dedupe_key=f"pg-review-submitted:{review.id}",
            related_entity_type="pg_review",
            related_entity_id=review.id,
        )
        db.add(
            PGUserReviewEvent(
                review_id=review.id,
                actor_owner_id=author.id,
                action="submitted",
                previous_status=None,
                new_status="pending",
                reason="Review submitted for moderation",
                created_at=now,
            )
        )
        db.commit()
        db.refresh(review)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already reviewed this PG",
        ) from None
    except Exception:
        db.rollback()
        raise
    return review


@router.get(
    "/pgs/{pg_id}/reviews",
    response_model=list[PGReviewOut],
)
def list_public_pg_reviews(
    pg_id: int,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    response: Response = None,
    db: Session = Depends(get_db),
):
    _get_public_pg(db, pg_id)
    total = db.scalar(
        select(func.count(PGUserReview.id)).where(
            PGUserReview.pg_id == pg_id,
            PGUserReview.status == "approved",
        )
    ) or 0
    if response is not None:
        response.headers["X-Total-Count"] = str(total)
        response.headers["X-Limit"] = str(limit)
        response.headers["X-Offset"] = str(offset)
    return db.scalars(
        select(PGUserReview)
        .where(
            PGUserReview.pg_id == pg_id,
            PGUserReview.status == "approved",
        )
        .order_by(PGUserReview.created_at.desc(), PGUserReview.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()


@router.patch(
    "/reviews/{review_id}",
    response_model=PGReviewReceiptOut,
)
def edit_pg_review(
    review_id: int,
    payload: PGReviewUpdate,
    author: Owner = Depends(get_authenticated_account),
    db: Session = Depends(get_db),
):
    try:
        review = _owned_review(db, author, review_id)
        if review.status == "removed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Removed reviews cannot be edited",
            )
        previous_status = review.status
        review.rating = payload.rating
        review.text = payload.text
        review.status = "pending"
        now = datetime.now(timezone.utc)
        review.updated_at = now
        db.add(
            PGUserReviewEvent(
                review_id=review.id,
                actor_owner_id=author.id,
                action="edited",
                previous_status=previous_status,
                new_status="pending",
                reason="Review edited and returned to moderation",
                created_at=now,
            )
        )
        db.commit()
        db.refresh(review)
        return review
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


@router.delete(
    "/reviews/{review_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_pg_review(
    review_id: int,
    author: Owner = Depends(get_authenticated_account),
    db: Session = Depends(get_db),
):
    try:
        review = _owned_review(db, author, review_id)
        if review.status == "removed":
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        previous_status = review.status
        now = datetime.now(timezone.utc)
        review.status = "removed"
        review.updated_at = now
        db.add(
            PGUserReviewEvent(
                review_id=review.id,
                actor_owner_id=author.id,
                action="author_removed",
                previous_status=previous_status,
                new_status="removed",
                reason="Review removed by author",
                created_at=now,
            )
        )
        db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
