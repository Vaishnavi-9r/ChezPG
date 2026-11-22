import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from fastapi import HTTPException, status
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.api.v1.notifications import (
    get_unread_notification_count,
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
)
from app.api.v1.pgs import create_pg_report
from app.api.v1.reviews import create_pg_review
from app.api.v1.admin import (
    moderate_pg_user_review,
    review_owner_verification,
    review_pg,
    review_pg_report,
)
from app.core.config import settings
from app.db.base import Base
from app.models import (
    Area,
    City,
    Notification,
    Owner,
    OwnerVerification,
    PG,
    PGUserReview,
)
from app.schemas.admin import PGReportCreate, PGReportReviewRequest, PGReviewRequest
from app.schemas.pg import PGCreate
from app.schemas.reviews import PGReviewCreate
from app.schemas.admin import PGReviewModerationRequest
from app.schemas.owner_admin import OwnerVerificationReviewRequest
from app.services.availability_reminders import create_stale_availability_reminders
from app.services.owner_listings import create_pg_listing


class NotificationWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        city = City(name="Notifications City", state="Telangana", country="India")
        self.db.add(city)
        self.db.flush()
        area = Area(city_id=city.id, name="Notifications Area")
        self.db.add(area)
        self.db.flush()
        self.city_id = city.id
        self.area_id = area.id
        self.owner = self.make_account("owner", "owner")
        self.user = self.make_account("user", "user")
        self.admin = self.make_account("admin", "admin")
        self.db.add(
            OwnerVerification(
                owner_id=self.owner.id,
                verification_status="approved",
                management_authority_status="approved",
                legal_name=self.owner.full_name,
                identity_document_key="identity-document.pdf",
                authority_document_key="authority-document.pdf",
            )
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def make_account(self, suffix, role):
        owner = Owner(
            full_name=f"Notification {suffix}",
            email=f"{suffix}@notification-tests.example",
            phone_number="+919876543210",
            relationship_type="property_owner" if role != "user" else None,
            password_hash="not-used-in-notification-tests",
            role=role,
            account_status="active",
        )
        self.db.add(owner)
        self.db.flush()
        owner.phone_number = f"+9198765{owner.id:05d}"
        self.db.commit()
        return owner

    def make_pg(self, *, active=True, confirmed_at=None, name="Notification PG"):
        pg = PG(
            city_id=self.city_id,
            area_id=self.area_id,
            owner_id=self.owner.id,
            name=name,
            address="123 Notification Street",
            stay_type="co_living",
            monthly_rent=Decimal("10000"),
            verification_status="verified" if active else "pending",
            is_active=active,
            availability_confirmed_at=confirmed_at,
        )
        self.db.add(pg)
        self.db.commit()
        return pg

    def add_notification(self, recipient, key, *, created_at=None):
        notification = Notification(
            recipient_user_id=recipient.id,
            type="test",
            title="Test notification",
            message="Safe test message",
            dedupe_key=key,
            created_at=created_at or datetime.now(timezone.utc),
        )
        self.db.add(notification)
        self.db.commit()
        return notification

    def test_listing_submission_notifies_owner_and_admin_in_same_workflow(self):
        payload = PGCreate(
            city_id=self.city_id,
            area_id=self.area_id,
            name="Submitted Notification PG",
            address="123 Notification Street",
            stay_type="co_living",
            monthly_rent=Decimal("11000"),
        )
        pg = create_pg_listing(payload, self.owner, self.db)

        notifications = self.db.scalars(
            select(Notification).where(
                Notification.related_entity_type == "pg",
                Notification.related_entity_id == pg.id,
            )
        ).all()
        self.assertEqual(
            {notification.recipient_user_id for notification in notifications},
            {self.owner.id, self.admin.id},
        )
        self.assertTrue(
            all(
                "password" not in notification.message.lower()
                and "token" not in notification.message.lower()
                for notification in notifications
            )
        )

    def test_report_and_review_submissions_notify_admins(self):
        pg = self.make_pg()
        create_pg_report(
            pg.id,
            PGReportCreate(category="incorrect_price"),
            self.user,
            self.db,
        )
        create_pg_review(
            pg.id,
            PGReviewCreate(rating=4, text="Helpful"),
            self.user,
            self.db,
        )
        admin_notifications = self.db.scalars(
            select(Notification).where(
                Notification.recipient_user_id == self.admin.id
            )
        ).all()
        self.assertEqual(
            {item.type for item in admin_notifications},
            {"pg_report_submitted", "pg_review_submitted"},
        )

    def test_report_resolution_notifies_reporter(self):
        pg = self.make_pg()
        receipt = create_pg_report(
            pg.id,
            PGReportCreate(category="incorrect_price"),
            self.user,
            self.db,
        )

        review_pg_report(
            receipt.id,
            PGReportReviewRequest(
                status="resolved",
                reason="The listing price was reviewed",
            ),
            self.db,
            self.admin,
        )

        notification = self.db.scalar(
            select(Notification).where(
                Notification.recipient_user_id == self.user.id,
                Notification.type == "pg_report_resolved",
            )
        )
        self.assertEqual(notification.message, "Your PG report has been resolved.")

    def test_pg_moderation_notifies_owner(self):
        pg = self.make_pg(active=False)
        pg.verification_status = "pending"
        self.db.commit()
        reviewed = review_pg(
            pg.id,
            PGReviewRequest(action="approve"),
            self.db,
            self.admin,
        )
        self.assertEqual(reviewed.verification_status, "verified")
        item = self.db.scalar(
            select(Notification).where(
                Notification.recipient_user_id == self.owner.id,
                Notification.related_entity_id == pg.id,
            )
        )
        self.assertEqual(item.type, "pg_approved")

    def test_owner_verification_decision_notifies_owner_without_notes(self):
        verification = self.db.scalar(
            select(OwnerVerification).where(
                OwnerVerification.owner_id == self.owner.id
            )
        )
        verification.verification_status = "pending"
        self.db.commit()

        review_owner_verification(
            self.owner.id,
            OwnerVerificationReviewRequest(
                verification_type="identity",
                action="reject",
                review_notes="Sensitive internal reviewer discussion",
            ),
            self.db,
            self.admin,
        )

        notification = self.db.scalar(
            select(Notification).where(
                Notification.recipient_user_id == self.owner.id,
                Notification.type == "owner_verification_identity_rejected",
            )
        )
        self.assertIsNotNone(notification)
        self.assertNotIn("Sensitive", notification.message)

    def test_review_moderation_notifies_author_without_revealing_admin_reason(self):
        pg = self.make_pg()
        review = create_pg_review(
            pg.id,
            PGReviewCreate(rating=5, text="Good place"),
            self.user,
            self.db,
        )
        result = moderate_pg_user_review(
            review.id,
            PGReviewModerationRequest(
                action="approve",
                reason="Internal note: hidden admin information",
            ),
            self.db,
            self.admin,
        )
        self.assertEqual(result.status, "approved")
        notification = self.db.scalar(
            select(Notification).where(
                Notification.recipient_user_id == self.user.id
            )
        )
        self.assertEqual(notification.type, "pg_review_approved")
        self.assertNotIn("Internal note", notification.message)

    def test_notifications_are_private_ordered_paginated_and_readable(self):
        first = self.add_notification(
            self.user,
            "first",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        second = self.add_notification(
            self.user,
            "second",
            created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        other = self.add_notification(self.owner, "owner-only")

        page = list_notifications(1, 0, recipient=self.user, db=self.db)
        self.assertEqual([item.id for item in page], [second.id])
        self.assertEqual(
            get_unread_notification_count(recipient=self.user, db=self.db).unread_count,
            2,
        )
        with self.assertRaises(HTTPException) as raised:
            mark_notification_read(other.id, self.user, self.db)
        self.assertEqual(raised.exception.status_code, status.HTTP_404_NOT_FOUND)

        read = mark_notification_read(first.id, self.user, self.db)
        self.assertTrue(read.is_read)
        self.assertIsNotNone(read.read_at)
        self.assertEqual(
            get_unread_notification_count(recipient=self.user, db=self.db).unread_count,
            1,
        )
        result = mark_all_notifications_read(recipient=self.user, db=self.db)
        self.assertEqual(result.updated_count, 1)
        self.assertTrue(self.db.get(Notification, other.id).is_read is False)

    def test_stale_availability_reminders_are_owner_scoped_and_idempotent(self):
        now = datetime.now(timezone.utc)
        stale = self.make_pg(
            confirmed_at=now - timedelta(hours=settings.availability_stale_hours + 1),
            name="Stale PG",
        )
        fresh = self.make_pg(
            confirmed_at=now,
            name="Fresh PG",
        )

        first_count = create_stale_availability_reminders(self.db, now=now)
        self.db.commit()
        second_count = create_stale_availability_reminders(self.db, now=now)
        self.db.commit()
        reminders = self.db.scalars(
            select(Notification).where(Notification.type == "availability_stale")
        ).all()

        self.assertEqual(first_count, 1)
        self.assertEqual(second_count, 0)
        self.assertEqual(len(reminders), 1)
        self.assertEqual(reminders[0].recipient_user_id, self.owner.id)
        self.assertEqual(reminders[0].related_entity_id, stale.id)
        self.assertNotEqual(reminders[0].related_entity_id, fresh.id)
        stored_confirmation = self.db.get(PG, stale.id).availability_confirmed_at
        if stored_confirmation.tzinfo is None:
            stored_confirmation = stored_confirmation.replace(tzinfo=timezone.utc)
        self.assertEqual(
            stored_confirmation,
            now - timedelta(hours=settings.availability_stale_hours + 1),
        )

    def test_notification_failure_rolls_back_listing_and_moderation(self):
        payload = PGCreate(
            city_id=self.city_id,
            area_id=self.area_id,
            name="Failure Notification PG",
            address="123 Notification Street",
            stay_type="co_living",
            monthly_rent=Decimal("11000"),
        )
        with patch(
            "app.services.owner_listings.create_notification",
            side_effect=RuntimeError("notification persistence failed"),
        ):
            with self.assertRaises(RuntimeError):
                create_pg_listing(payload, self.owner, self.db)
        self.assertEqual(
            self.db.scalar(select(func.count(PG.id)).where(PG.name == payload.name)),
            0,
        )

        pg = self.make_pg(active=False)
        pg.verification_status = "pending"
        self.db.commit()
        with patch(
            "app.api.v1.admin.create_notification",
            side_effect=RuntimeError("notification persistence failed"),
        ):
            with self.assertRaises(RuntimeError):
                review_pg(
                    pg.id,
                    PGReviewRequest(action="reject", reason="Not valid"),
                    self.db,
                    self.admin,
                )
        self.assertEqual(self.db.get(PG, pg.id).verification_status, "pending")
        self.assertFalse(self.db.get(PG, pg.id).is_active)


if __name__ == "__main__":
    unittest.main()
