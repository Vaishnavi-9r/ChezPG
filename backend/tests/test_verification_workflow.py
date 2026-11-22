import asyncio
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException, status
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.api.v1 import owners as owners_api
from app.api.v1.admin import (
    get_owner_verification_audit,
    get_owner_verification_document,
    get_pg_review_detail,
    get_pg_review_history,
    require_admin,
    review_owner_verification,
    review_pg,
)
from app.api.v1.media import get_public_pg_media
from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.integrations.verification_storage import LocalPrivateVerificationStorage
from app.models import (
    Area,
    City,
    Owner,
    OwnerVerification,
    OwnerVerificationAuditEvent,
    PG,
    PGReviewEvent,
)
from app.schemas.admin import PGReviewRequest
from app.schemas.owner import OwnerVerificationDocumentSubmission
from app.schemas.owner_admin import OwnerVerificationReviewRequest


class VerificationWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        city = City(name="Verification City", state="Telangana")
        self.db.add(city)
        self.db.flush()
        area = Area(city_id=city.id, name="Verification Area")
        self.db.add(area)
        self.db.flush()
        self.city_id = city.id
        self.area_id = area.id
        self.owner = self.make_account("owner", "property_owner")
        self.admin = self.make_account("admin", "property_owner", role="admin")
        self.other_owner = self.make_account("other", "property_manager")
        self.storage_temp = tempfile.TemporaryDirectory()
        self.storage = LocalPrivateVerificationStorage(
            Path(self.storage_temp.name)
        )
        self.storage_patch = patch.object(
            owners_api,
            "verification_storage",
            self.storage,
        )
        self.storage_patch.start()
        self.admin_storage_patch = patch(
            "app.api.v1.admin._verification_document_response",
            owners_api._verification_document_response,
        )
        self.admin_storage_patch.start()

    def tearDown(self):
        self.admin_storage_patch.stop()
        self.storage_patch.stop()
        self.db.close()
        self.engine.dispose()
        self.storage_temp.cleanup()

    def make_account(self, suffix, relationship, role="owner"):
        owner = Owner(
            full_name=f"Test {suffix}",
            email=f"{suffix}@verification.example",
            phone_number=f"+9198765{len(suffix):05d}{role == 'admin' and '1' or '2'}",
            relationship_type=relationship,
            password_hash=hash_password("safe-verification-test-password"),
            role=role,
            account_status="active",
        )
        self.db.add(owner)
        self.db.flush()
        owner.phone_number = f"+9198765{owner.id:05d}"
        self.db.commit()
        return owner

    def make_pg(self, owner=None):
        pg = PG(
            city_id=self.city_id,
            area_id=self.area_id,
            owner_id=(owner or self.owner).id,
            name="Verification PG",
            address="123 Verification Street",
            stay_type="co_living",
            monthly_rent=12000,
            security_deposit=5000,
            food_available=True,
            electricity_included=False,
            verification_status="pending",
            is_active=False,
        )
        self.db.add(pg)
        self.db.commit()
        return pg

    def submit_documents(self, owner=None):
        owner = owner or self.owner
        return asyncio.run(
            owners_api.submit_owner_verification_documents(
                legal_name="Legal Test Owner",
                identity_document_type="passport",
                authority_document_type=(
                    "ownership_deed"
                    if owner.relationship_type == "property_owner"
                    else "authorization_letter"
                ),
                submission_notes="Ready for manual review",
                identity_document=UploadFile(
                    filename="identity.pdf",
                    file=BytesIO(b"%PDF-1.7\nprivate identity evidence\n%%EOF"),
                    headers={"content-type": "application/pdf"},
                ),
                authority_document=UploadFile(
                    filename="authority.pdf",
                    file=BytesIO(b"%PDF-1.7\nprivate authority evidence\n%%EOF"),
                    headers={"content-type": "application/pdf"},
                ),
                owner=owner,
                db=self.db,
            )
        )

    def test_submission_defaults_both_independent_reviews_to_pending(self):
        response = self.submit_documents()
        verification = self.db.scalar(
            select(OwnerVerification).where(
                OwnerVerification.owner_id == self.owner.id
            )
        )

        self.assertEqual(response.identity_verification_status, "pending")
        self.assertEqual(response.management_authority_status, "pending")
        self.assertEqual(verification.verification_status, "pending")
        self.assertEqual(verification.management_authority_status, "pending")
        self.assertEqual(verification.legal_name, "Legal Test Owner")
        self.assertNotIn("document_key", response.model_dump())
        self.assertNotIn("legal_name", response.model_dump())

    def test_owner_submission_rejects_mismatched_management_evidence_type(self):
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                owners_api.submit_owner_verification_documents(
                    legal_name="Legal Test Owner",
                    identity_document_type="passport",
                    authority_document_type="authorization_letter",
                    submission_notes=None,
                    identity_document=UploadFile(
                        filename="identity.pdf",
                        file=BytesIO(b"%PDF-1.7\nvalid\n%%EOF"),
                    ),
                    authority_document=UploadFile(
                        filename="authority.pdf",
                        file=BytesIO(b"%PDF-1.7\nvalid\n%%EOF"),
                    ),
                    owner=self.owner,
                    db=self.db,
                )
            )
        self.assertEqual(
            raised.exception.status_code,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    def test_document_content_is_validated_from_bytes_not_filename_or_header(self):
        self.assertEqual(
            owners_api._validate_verification_document(
                b"%PDF-1.7\ncontent\n%%EOF"
            ),
            ("pdf", "application/pdf"),
        )
        with self.assertRaises(HTTPException):
            owners_api._validate_verification_document(
                b"not a pdf, despite the filename"
            )

    def test_private_documents_are_only_available_to_their_owner_or_admin(self):
        self.submit_documents()
        verification = self.db.scalar(
            select(OwnerVerification).where(
                OwnerVerification.owner_id == self.owner.id
            )
        )
        response = owners_api.get_my_verification_document(
            "identity",
            self.owner,
            self.db,
        )
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.assertNotIn("private_uploads", str(response.path))

        with self.assertRaises(HTTPException) as owner_denied:
            owners_api.get_my_verification_document(
                "identity",
                self.other_owner,
                self.db,
            )
        self.assertEqual(owner_denied.exception.status_code, status.HTTP_404_NOT_FOUND)

        admin_response = get_owner_verification_document(
            self.owner.id,
            "identity",
            self.db,
        )
        self.assertTrue(Path(admin_response.path).is_file())
        self.assertNotIn(
            "identity_document_key",
            response.headers.get("content-disposition", ""),
        )
        self.assertTrue(verification.identity_document_key)

    def test_public_media_does_not_expose_verification_document_fields(self):
        self.submit_documents()
        pg = self.make_pg()

        with self.assertRaises(HTTPException) as hidden:
            get_public_pg_media(pg.id, self.db)

        self.assertEqual(hidden.exception.status_code, status.HTTP_404_NOT_FOUND)

    def test_identity_and_authority_reviews_are_independent_and_audited(self):
        self.submit_documents()

        identity_result = review_owner_verification(
            self.owner.id,
            OwnerVerificationReviewRequest(
                verification_type="identity",
                action="approve",
            ),
            self.db,
            self.admin,
        )
        self.assertEqual(identity_result.status, "approved")
        verification = self.db.scalar(
            select(OwnerVerification).where(
                OwnerVerification.owner_id == self.owner.id
            )
        )
        self.assertEqual(verification.management_authority_status, "pending")

        authority_result = review_owner_verification(
            self.owner.id,
            OwnerVerificationReviewRequest(
                verification_type="management_authority",
                action="approve",
            ),
            self.db,
            self.admin,
        )
        self.assertEqual(authority_result.status, "approved")
        events = get_owner_verification_audit(
            self.owner.id,
            50,
            0,
            self.db,
        )
        self.assertEqual(len(events), 2)
        self.assertEqual(
            {event.verification_type for event in events},
            {"identity", "management_authority"},
        )
        self.assertTrue(all(event.reviewer_owner_id == self.admin.id for event in events))

    def test_corrections_and_rejection_are_audited_for_owner_reviews(self):
        self.submit_documents()
        correction = review_owner_verification(
            self.owner.id,
            OwnerVerificationReviewRequest(
                verification_type="identity",
                action="request_corrections",
                review_notes="Please upload a clearer identity document",
            ),
            self.db,
            self.admin,
        )
        self.assertEqual(correction.status, "needs_resubmission")

        rejected = review_owner_verification(
            self.owner.id,
            OwnerVerificationReviewRequest(
                verification_type="identity",
                action="reject",
                review_notes="Document does not match the submitted legal name",
            ),
            self.db,
            self.admin,
        )
        self.assertEqual(rejected.status, "rejected")

    def test_pg_approval_requires_both_owner_reviews_and_records_admin(self):
        self.submit_documents()
        pg = self.make_pg()
        with self.assertRaises(HTTPException):
            review_pg(
                pg.id,
                PGReviewRequest(action="approve"),
                self.db,
                self.admin,
            )
        review_owner_verification(
            self.owner.id,
            OwnerVerificationReviewRequest(
                verification_type="identity",
                action="approve",
            ),
            self.db,
            self.admin,
        )
        review_owner_verification(
            self.owner.id,
            OwnerVerificationReviewRequest(
                verification_type="management_authority",
                action="approve",
            ),
            self.db,
            self.admin,
        )
        approved_pg = review_pg(
            pg.id,
            PGReviewRequest(action="approve"),
            self.db,
            self.admin,
        )
        self.assertEqual(approved_pg.verification_status, "verified")
        self.assertTrue(approved_pg.is_active)

        history = get_pg_review_history(pg.id, 50, 0, self.db)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].reviewer_owner_id, self.admin.id)
        self.assertEqual(history[0].action, "approved")
        detail = get_pg_review_detail(pg.id, self.db)
        self.assertTrue(detail.has_identity_document)
        self.assertTrue(detail.has_authority_document)

    def test_pg_corrections_and_rejection_have_reasons_and_audit(self):
        pg = self.make_pg()
        correction = review_pg(
            pg.id,
            PGReviewRequest(
                action="request_corrections",
                reason="Address documentation is incomplete",
            ),
            self.db,
            self.admin,
        )
        self.assertEqual(correction.verification_status, "needs_resubmission")
        self.assertFalse(correction.is_active)

        rejected = review_pg(
            pg.id,
            PGReviewRequest(action="reject", reason="Address is not verifiable"),
            self.db,
            self.admin,
        )
        self.assertEqual(rejected.verification_status, "rejected")
        history = get_pg_review_history(pg.id, 50, 0, self.db)
        self.assertEqual(
            [event.action for event in history],
            ["rejected", "needs_resubmission"],
        )
        self.assertTrue(all(event.reviewer_owner_id == self.admin.id for event in history))

    def test_non_admin_is_rejected_by_existing_admin_authorization_dependency(self):
        with patch.object(
            settings,
            "owner_token_secret",
            "a-test-token-secret-that-is-at-least-32-bytes",
        ):
            from fastapi.security import HTTPAuthorizationCredentials

            token = create_access_token(self.owner.id, self.owner.token_version)
            with self.assertRaises(HTTPException) as raised:
                require_admin(
                    HTTPAuthorizationCredentials(
                        scheme="Bearer",
                        credentials=token,
                    ),
                    self.db,
                )
        self.assertEqual(raised.exception.status_code, status.HTTP_403_FORBIDDEN)


if __name__ == "__main__":
    unittest.main()
