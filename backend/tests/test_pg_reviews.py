import unittest
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from pydantic import ValidationError
from unittest.mock import patch

from app.api.v1.admin import (
    get_pg_user_review_history,
    moderate_pg_user_review,
)
from app.api.v1.dependencies import require_admin_account
from app.api.v1.reviews import (
    create_pg_review,
    edit_pg_review,
    list_public_pg_reviews,
    remove_pg_review,
)
from app.api.v1.pgs import get_pgs
from app.core.config import settings
from app.core.security import hash_password
from app.db.base import Base
from app.models import (
    Area,
    City,
    Owner,
    OwnerVerification,
    PG,
    PGUserReview,
    PGUserReviewEvent,
)
from app.schemas.admin import PGReviewModerationRequest
from app.schemas.reviews import (
    PGReviewCreate,
    PGReviewOut,
    PGReviewReceiptOut,
    PGReviewUpdate,
)


class PGReviewWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        city = City(name="Reviews City", state="Telangana", country="India")
        self.db.add(city)
        self.db.flush()
        area = Area(city_id=city.id, name="Reviews Area")
        self.db.add(area)
        self.db.flush()
        self.city_id = city.id
        self.area_id = area.id
        self.owner = self.make_account("owner", "owner")
        self.author = self.make_account("author", "user")
        self.other_author = self.make_account("other", "user")
        self.admin = self.make_account("admin", "admin")
        self.db.add(
            OwnerVerification(
                owner_id=self.owner.id,
                verification_status="approved",
                management_authority_status="approved",
                legal_name=self.owner.full_name,
                identity_document_key="identity-evidence.pdf",
                authority_document_key="authority-evidence.pdf",
            )
        )
        self.pg = self.make_pg()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def make_account(self, suffix, role):
        account = Owner(
            full_name=f"Review {suffix}",
            email=f"{suffix}@review-tests.example",
            phone_number="+919876543210",
            relationship_type="property_owner" if role != "user" else None,
            password_hash=hash_password("safe-review-test-password"),
            role=role,
            account_status="active",
        )
        self.db.add(account)
        self.db.flush()
        account.phone_number = f"+9198765{account.id:05d}"
        self.db.commit()
        return account

    def make_pg(self, *, owner=None, name="Review PG"):
        pg = PG(
            city_id=self.city_id,
            area_id=self.area_id,
            owner_id=(owner or self.owner).id,
            name=name,
            address="123 Review Street",
            stay_type="co_living",
            monthly_rent=Decimal("10000"),
            verification_status="verified",
            is_active=True,
        )
        self.db.add(pg)
        self.db.commit()
        return pg

    def submit(self, author, rating=5, text="Helpful review"):
        return create_pg_review(
            self.pg.id,
            PGReviewCreate(rating=rating, text=text),
            author,
            self.db,
        )

    def test_create_review_is_pending_authenticated_and_unique(self):
        result = self.submit(self.author)
        self.assertEqual(result.status, "pending")
        self.assertEqual(result.author_id, self.author.id)
        public_receipt = PGReviewReceiptOut.model_validate(result)
        self.assertNotIn("author_id", public_receipt.model_dump())
        with self.assertRaises(HTTPException) as raised:
            self.submit(self.author)
        self.assertEqual(raised.exception.status_code, status.HTTP_409_CONFLICT)
        event = self.db.scalar(
            select(PGUserReviewEvent).where(
                PGUserReviewEvent.review_id == result.id
            )
        )
        self.assertEqual(event.action, "submitted")

    def test_ratings_require_strict_integer_between_one_and_five(self):
        for rating in (0, 6, 3.5, True):
            with self.subTest(rating=rating):
                with self.assertRaises(ValidationError):
                    PGReviewCreate(rating=rating)

    def test_unauthenticated_review_submission_requires_bearer_account(self):
        from app.api.v1.dependencies import get_authenticated_account

        with patch.object(
            settings,
            "owner_token_secret",
            "a-test-token-secret-that-is-at-least-32-bytes",
        ):
            with self.assertRaises(HTTPException) as raised:
                get_authenticated_account(None, self.db)
        self.assertEqual(raised.exception.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_owner_cannot_review_their_own_listing(self):
        with self.assertRaises(HTTPException) as raised:
            self.submit(self.owner)
        self.assertEqual(raised.exception.status_code, status.HTTP_409_CONFLICT)

    def test_pending_reviews_are_private_and_public_summary_uses_approved_only(self):
        pending = self.submit(self.author, rating=1)
        approved_a = self.submit(self.other_author, rating=4)
        moderation = PGReviewModerationRequest(
            action="approve",
            reason="Review is relevant and within policy",
        )
        from app.api.v1.admin import moderate_pg_user_review

        approved = moderate_pg_user_review(
            approved_a.id,
            moderation,
            self.db,
            self.admin,
        )
        self.assertEqual(approved.status, "approved")

        public = list_public_pg_reviews(self.pg.id, db=self.db)
        self.assertEqual([review.id for review in public], [approved_a.id])
        public_payloads = [PGReviewOut.model_validate(item) for item in public]
        self.assertFalse(any(hasattr(review, "author_id") for review in public_payloads))
        search = get_pgs(
            city_id=None,
            area_id=None,
            stay_type=None,
            min_rent=None,
            max_rent=None,
            verified_only=False,
            db=self.db,
        )
        listing = next(pg for pg in search if pg.id == self.pg.id)
        self.assertEqual(listing.average_rating, Decimal("4.0"))
        self.assertEqual(listing.published_review_count, 1)
        self.assertEqual(pending.status, "pending")
        self.assertEqual(approved_a.status, "approved")

    def test_public_rating_average_and_count_exclude_hidden_and_removed(self):
        review_one = self.submit(self.author, rating=4)
        review_two = self.submit(self.other_author, rating=2)
        for review in (review_one, review_two):
            moderate_pg_user_review(
                review.id,
                PGReviewModerationRequest(
                    action="approve",
                    reason="Review passed moderation",
                ),
                self.db,
                self.admin,
            )
        moderate_pg_user_review(
            review_two.id,
            PGReviewModerationRequest(action="hide", reason="Needs review"),
            self.db,
            self.admin,
        )
        search = get_pgs(
            city_id=None,
            area_id=None,
            stay_type=None,
            min_rent=None,
            max_rent=None,
            verified_only=False,
            db=self.db,
        )
        listing = next(pg for pg in search if pg.id == self.pg.id)
        self.assertEqual(listing.average_rating, Decimal("4.0"))
        self.assertEqual(listing.published_review_count, 1)

    def test_edit_and_remove_are_author_scoped_and_soft_delete(self):
        review = self.submit(self.author)
        with self.assertRaises(HTTPException) as raised:
            edit_pg_review(
                review.id,
                PGReviewUpdate(rating=4, text="Changed"),
                self.other_author,
                self.db,
            )
        self.assertEqual(raised.exception.status_code, status.HTTP_404_NOT_FOUND)

        edited = edit_pg_review(
            review.id,
            PGReviewUpdate(rating=3, text="<script>unsafe()</script>"),
            self.author,
            self.db,
        )
        self.assertEqual(edited.status, "pending")
        self.assertNotIn("<script>", edited.text)
        with self.assertRaises(HTTPException) as raised:
            remove_pg_review(review.id, self.other_author, self.db)
        self.assertEqual(raised.exception.status_code, status.HTTP_404_NOT_FOUND)

        remove_pg_review(review.id, self.author, self.db)
        stored = self.db.get(PGUserReview, review.id)
        self.assertEqual(stored.status, "removed")
        self.assertEqual(
            [event.action for event in get_pg_user_review_history(
                review.id,
                db=self.db,
            )],
            ["author_removed", "edited", "submitted"],
        )

    def test_admin_review_workflow_and_history(self):
        review = self.submit(self.author)
        with patch.object(
            settings,
            "owner_token_secret",
            "a-test-token-secret-that-is-at-least-32-bytes",
        ):
            from app.core.security import create_access_token
            from fastapi.security import HTTPAuthorizationCredentials

            credentials = HTTPAuthorizationCredentials(
                scheme="Bearer",
                credentials=create_access_token(
                    self.author.id,
                    self.author.token_version,
                ),
            )
            with self.assertRaises(HTTPException) as raised:
                require_admin_account(credentials, self.db)
        self.assertEqual(raised.exception.status_code, status.HTTP_403_FORBIDDEN)
        with self.assertRaises(HTTPException) as raised:
            moderate_pg_user_review(
                review.id,
                PGReviewModerationRequest(
                    action="approve",
                    reason="Non-admin should not reach this route",
                ),
                self.db,
                self.author,
            )
        self.assertEqual(raised.exception.status_code, status.HTTP_403_FORBIDDEN)

        moderated = moderate_pg_user_review(
            review.id,
            PGReviewModerationRequest(action="approve", reason="Approved"),
            self.db,
            self.admin,
        )
        self.assertEqual(moderated.status, "approved")
        hidden = moderate_pg_user_review(
            review.id,
            PGReviewModerationRequest(action="hide", reason="Policy review"),
            self.db,
            self.admin,
        )
        self.assertEqual(hidden.status, "hidden")
        restored = moderate_pg_user_review(
            review.id,
            PGReviewModerationRequest(action="restore", reason="Review restored"),
            self.db,
            self.admin,
        )
        self.assertEqual(restored.status, "approved")
        history = get_pg_user_review_history(review.id, db=self.db)
        self.assertEqual(
            [event.action for event in history],
            ["restored", "hidden", "approved", "submitted"],
        )
        self.assertEqual(history[0].actor_owner_id, self.admin.id)


if __name__ == "__main__":
    unittest.main()
