import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from pydantic import ValidationError

from app.api.v1.admin import (
    get_admin_dashboard,
    get_admin_pg_detail,
    get_pg_report_history,
    list_admin_pgs,
    review_owner_verification,
    review_pg,
    review_pg_report,
)
from app.api.v1.dependencies import require_admin_account
from app.api.v1.pgs import create_pg_report, get_pgs
from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.models import (
    Area,
    City,
    Owner,
    OwnerVerification,
    PG,
    PGReport,
    PGReviewEvent,
    Room,
)
from app.schemas.admin import PGReportCreate, PGReportReviewRequest, PGReviewRequest
from app.schemas.owner_admin import OwnerVerificationReviewRequest


class AdminDashboardReportTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        city = City(name="Moderation City", state="Telangana", country="India")
        self.db.add(city)
        self.db.flush()
        area = Area(city_id=city.id, name="Moderation Area")
        self.db.add(area)
        self.db.flush()
        self.city_id = city.id
        self.area_id = area.id
        self.owner = self.make_account("owner", "owner")
        self.reporter = self.make_account("reporter", "user")
        self.admin = self.make_account("admin", "admin")
        self.admin_owner_listing = self.make_pg(
            owner=self.admin,
            verification_status="pending",
        )

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def make_account(self, suffix, role):
        account = Owner(
            full_name=f"Test {suffix}",
            email=f"{suffix}@admin-tests.example",
            phone_number="+919876543210",
            relationship_type="property_owner" if role != "user" else None,
            password_hash=hash_password("safe-dashboard-test-password"),
            role=role,
            account_status="active",
        )
        self.db.add(account)
        self.db.flush()
        account.phone_number = f"+9198765{account.id:05d}"
        self.db.commit()
        return account

    def make_pg(
        self,
        *,
        owner=None,
        verification_status="pending",
        is_active=False,
        name="Moderation PG",
    ):
        pg = PG(
            city_id=self.city_id,
            area_id=self.area_id,
            owner_id=owner.id if owner is not None else None,
            name=name,
            address="123 Moderation Road",
            stay_type="co_living",
            monthly_rent=Decimal("10000"),
            verification_status=verification_status,
            is_active=is_active,
        )
        self.db.add(pg)
        self.db.commit()
        return pg

    def approve_owner_reviews(self, owner):
        verification = OwnerVerification(
            owner_id=owner.id,
            verification_status="approved",
            management_authority_status="approved",
            legal_name=owner.full_name,
            identity_document_key="identity-evidence.pdf",
            authority_document_key="authority-evidence.pdf",
        )
        self.db.add(verification)
        self.db.commit()
        return verification

    def test_dashboard_counts_statuses_freshness_and_zero_beds(self):
        self.approve_owner_reviews(self.owner)
        approved = self.make_pg(
            owner=self.owner,
            verification_status="verified",
            is_active=True,
        )
        self.make_pg(verification_status="rejected", name="Rejected")
        self.make_pg(
            verification_status="needs_resubmission",
            name="Needs Resubmission",
        )
        self.make_pg(
            owner=self.owner,
            verification_status="verified",
            is_active=True,
            name="Full PG",
        )
        self.db.add(
            Room(
                pg_id=approved.id,
                label="Full room",
                sharing_type="double",
                monthly_rent_per_person=Decimal("10000"),
                total_beds=2,
                occupied_beds=2,
                is_active=True,
            )
        )
        self.db.commit()

        result = get_admin_dashboard(self.db)
        self.assertEqual(result.total_listings, 5)
        self.assertEqual(result.active_listings, 2)
        self.assertEqual(result.inactive_listings, 3)
        self.assertEqual(result.pending_listings, 1)
        self.assertEqual(result.approved_listings, 2)
        self.assertEqual(result.rejected_listings, 1)
        self.assertEqual(result.resubmission_required_listings, 1)
        self.assertEqual(result.stale_availability_listings, 2)
        self.assertEqual(result.zero_available_bed_listings, 1)
        self.assertEqual(result.pending_owner_identity_reviews, 0)
        self.assertEqual(result.pending_management_authority_reviews, 0)
        self.assertEqual(result.unreviewed_reports, 0)

    def test_dashboard_counts_pending_owner_reviews_and_reports(self):
        verification = OwnerVerification(
            owner_id=self.owner.id,
            verification_status="pending",
            management_authority_status="needs_resubmission",
        )
        verified_owner = self.make_account("verified-owner", "owner")
        self.approve_owner_reviews(verified_owner)
        listing = self.make_pg(
            owner=verified_owner,
            verification_status="verified",
            is_active=True,
        )
        self.db.add(verification)
        self.db.commit()
        create_pg_report(
            listing.id,
            PGReportCreate(category="incorrect_price", details="Price differs"),
            self.reporter,
            self.db,
        )

        result = get_admin_dashboard(self.db)

        self.assertEqual(result.pending_owner_identity_reviews, 1)
        self.assertEqual(result.pending_management_authority_reviews, 1)
        self.assertEqual(result.unreviewed_reports, 1)

    def test_admin_listing_filters_and_unknown_legacy_dates(self):
        first = self.make_pg(verification_status="verified", is_active=True)
        second = self.make_pg(verification_status="rejected", name="Rejected")
        self.db.execute(
            select(PG).where(PG.id == first.id)
        ).scalar_one().created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.db.execute(
            select(PG).where(PG.id == second.id)
        ).scalar_one().created_at = None
        self.db.commit()

        result = list_admin_pgs(
            verification_status="approved",
            city_id=self.city_id,
            area_id=self.area_id,
            created_from=datetime(2025, 12, 31, tzinfo=timezone.utc),
            db=self.db,
        )
        self.assertEqual([pg.id for pg in result], [first.id])

        with self.assertRaises(HTTPException) as raised:
            list_admin_pgs(
                created_from=datetime(2026, 2, 1, tzinfo=timezone.utc),
                created_to=datetime(2026, 1, 1, tzinfo=timezone.utc),
                db=self.db,
            )
        self.assertEqual(
            raised.exception.status_code,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    def test_admin_detail_includes_review_metadata_without_document_keys(self):
        verification = self.approve_owner_reviews(self.owner)
        listing = self.make_pg(owner=self.owner)

        result = get_admin_pg_detail(listing.id, db=self.db)
        data = result.model_dump()

        self.assertEqual(result.owner_full_name, self.owner.full_name)
        self.assertEqual(result.owner_identity_status, "approved")
        self.assertTrue(result.has_identity_document)
        self.assertTrue(result.has_authority_document)
        self.assertNotIn("identity_document_key", data)
        self.assertNotIn("authority_document_key", data)
        self.assertEqual(
            verification.identity_document_key,
            "identity-evidence.pdf",
        )

    def test_admin_approval_rejects_self_review_and_records_other_review(self):
        with self.assertRaises(HTTPException) as raised:
            review_pg(
                self.admin_owner_listing.id,
                PGReviewRequest(action="approve"),
                self.db,
                self.admin,
            )
        self.assertEqual(raised.exception.status_code, status.HTTP_403_FORBIDDEN)

        listing = self.make_pg(owner=self.owner)
        self.approve_owner_reviews(self.owner)
        approved = review_pg(
            listing.id,
            PGReviewRequest(action="approve"),
            self.db,
            self.admin,
        )
        self.assertEqual(approved.verification_status, "verified")
        event = self.db.scalar(
            select(PGReviewEvent).where(PGReviewEvent.pg_id == listing.id)
        )
        self.assertEqual(event.reviewer_owner_id, self.admin.id)
        self.assertEqual(event.new_status, "verified")

    def test_rejection_reason_is_required_and_audited(self):
        with self.assertRaises(ValidationError):
            PGReviewRequest(action="reject")
        listing = self.make_pg(owner=self.owner)
        rejected = review_pg(
            listing.id,
            PGReviewRequest(action="reject", reason="Address could not be verified"),
            self.db,
            self.admin,
        )
        self.assertEqual(rejected.verification_status, "rejected")

    def test_owner_verification_cannot_be_reviewed_by_that_same_account(self):
        verification = OwnerVerification(owner_id=self.admin.id)
        self.db.add(verification)
        self.db.commit()
        with self.assertRaises(HTTPException) as raised:
            review_owner_verification(
                self.admin.id,
                OwnerVerificationReviewRequest(
                    verification_type="identity",
                    action="reject",
                    review_notes="Self review is prohibited",
                ),
                self.db,
                self.admin,
            )
        self.assertEqual(raised.exception.status_code, status.HTTP_403_FORBIDDEN)

    def test_report_submission_is_authenticated_deduplicated_and_publicly_private(self):
        self.approve_owner_reviews(self.owner)
        listing = self.make_pg(
            owner=self.owner,
            verification_status="verified",
            is_active=True,
        )
        receipt = create_pg_report(
            listing.id,
            PGReportCreate(
                category="suspected_fraud",
                details="The posted details do not match the property",
            ),
            self.reporter,
            self.db,
        )
        self.assertEqual(receipt.status, "submitted")
        with self.assertRaises(HTTPException) as raised:
            create_pg_report(
                listing.id,
                PGReportCreate(category="incorrect_address"),
                self.reporter,
                self.db,
            )
        self.assertEqual(raised.exception.status_code, status.HTTP_409_CONFLICT)
        public = get_pgs(
            city_id=None,
            area_id=None,
            stay_type=None,
            min_rent=None,
            max_rent=None,
            verified_only=False,
            db=self.db,
        )
        serialized = [item.model_dump() for item in public]
        self.assertFalse(any("reports" in item or "details" in item for item in serialized))

    def test_report_resolution_is_stateful_and_audited(self):
        self.approve_owner_reviews(self.owner)
        listing = self.make_pg(
            owner=self.owner,
            verification_status="verified",
            is_active=True,
        )
        receipt = create_pg_report(
            listing.id,
            PGReportCreate(category="incorrect_price"),
            self.reporter,
            self.db,
        )
        resolved = review_pg_report(
            receipt.id,
            PGReportReviewRequest(
                status="resolved",
                reason="Owner confirmed and corrected the price",
            ),
            self.db,
            self.admin,
        )
        self.assertEqual(resolved.status, "resolved")
        history = get_pg_report_history(receipt.id, db=self.db)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].reviewer_owner_id, self.admin.id)
        self.assertEqual(history[0].previous_status, "submitted")
        self.assertEqual(history[0].new_status, "resolved")
        self.assertEqual(history[0].reason, "Owner confirmed and corrected the price")

        with self.assertRaises(HTTPException) as raised:
            review_pg_report(
                receipt.id,
                PGReportReviewRequest(
                    status="dismissed",
                    reason="Already closed and cannot be changed",
                ),
                self.db,
                self.admin,
            )
        self.assertEqual(raised.exception.status_code, status.HTTP_409_CONFLICT)

    def test_listing_owner_admin_cannot_dismiss_report_against_own_pg(self):
        self.approve_owner_reviews(self.admin)
        listing = self.make_pg(
            owner=self.admin,
            verification_status="verified",
            is_active=True,
        )
        report = PGReport(
            pg_id=listing.id,
            reporter_owner_id=self.reporter.id,
            category="other",
            details="Please verify this listing",
            status="submitted",
        )
        self.db.add(report)
        self.db.commit()

        with self.assertRaises(HTTPException) as raised:
            review_pg_report(
                report.id,
                PGReportReviewRequest(
                    status="dismissed",
                    reason="I own this listing",
                ),
                self.db,
                self.admin,
            )
        self.assertEqual(raised.exception.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.db.get(PGReport, report.id).status, "submitted")

    def test_non_admin_is_denied_by_shared_admin_dependency(self):
        with patch.object(
            settings,
            "owner_token_secret",
            "a-test-token-secret-that-is-at-least-32-bytes",
        ):
            credentials = HTTPAuthorizationCredentials(
                scheme="Bearer",
                credentials=create_access_token(
                    self.owner.id,
                    self.owner.token_version,
                ),
            )
            with self.assertRaises(HTTPException) as raised:
                require_admin_account(credentials, self.db)
        self.assertEqual(raised.exception.status_code, status.HTTP_403_FORBIDDEN)


if __name__ == "__main__":
    unittest.main()
