import asyncio
from io import BytesIO
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException, UploadFile, status
from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1 import media
from app.api.v1.media import reorder_pg_photos
from app.api.v1.pgs import get_pgs
from app.core.config import settings
from app.core.security import hash_password
from app.db.base import Base
from app.integrations.photo_storage import LocalPrivatePhotoStorage
from app.models import Amenity, Area, City, Owner, OwnerVerification, PG, PGPhoto
from app.schemas.photo import (
    AmenityIdsRequest,
    PhotoOrderRequest,
    PhotoReviewRequest,
)


class MediaWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage = LocalPrivatePhotoStorage(Path(self.temp_dir.name))
        self.storage_patch = patch.object(media, "photo_storage", self.storage)
        self.storage_patch.start()

        city = City(name="Media City", state="Test State", country="India")
        self.db.add(city)
        self.db.flush()
        area = Area(city_id=city.id, name="Media Area")
        self.db.add(area)
        self.db.flush()
        self.city_id = city.id
        self.area_id = area.id
        self.owner = self.add_owner("media-owner@example.com")
        self.other_owner = self.add_owner("other-owner@example.com")
        self.pg = self.add_pg(self.owner)
        self.other_pg = self.add_pg(self.other_owner, name="Other PG")

    def tearDown(self):
        self.storage_patch.stop()
        self.db.close()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def add_owner(self, email):
        owner = Owner(
            full_name="Media Owner",
            email=email,
            phone_number="+919876543210",
            relationship_type="property_owner",
            password_hash=hash_password("safe-test-password"),
            account_status="active",
        )
        self.db.add(owner)
        self.db.flush()
        owner.phone_number = f"+9198765{owner.id:05d}"
        self.db.add(
            OwnerVerification(
                owner_id=owner.id,
                verification_status="approved",
                management_authority_status="approved",
                legal_name=owner.full_name,
                identity_document_key="identity-test.pdf",
                authority_document_key="authority-test.pdf",
            )
        )
        return owner

    def add_pg(self, owner, name="Media PG"):
        pg = PG(
            city_id=self.city_id,
            area_id=self.area_id,
            owner_id=owner.id,
            name=name,
            address="123 Test Street",
            stay_type="co_living",
            monthly_rent=Decimal("10000.00"),
            verification_status="verified",
            is_active=True,
        )
        self.db.add(pg)
        self.db.commit()
        return pg

    @staticmethod
    def image_upload(format="JPEG", filename="not-an-image.txt"):
        image_bytes = BytesIO()
        Image.new("RGB", (4, 4), "red").save(image_bytes, format=format)
        image_bytes.seek(0)
        return UploadFile(filename=filename, file=image_bytes)

    def upload(self, pg=None, owner=None, upload=None):
        return asyncio.run(
            media.upload_pg_photo(
                pg_id=(pg or self.pg).id,
                file=upload or self.image_upload(),
                caption="  Room  ",
                owner=owner or self.owner,
                db=self.db,
            )
        )

    def test_amenities_are_unique_and_owner_scoped(self):
        wifi = Amenity(name="Wi-Fi", is_active=True)
        self.db.add(wifi)
        self.db.commit()
        response = media.set_pg_amenities(
            self.pg.id,
            AmenityIdsRequest(amenity_ids=[wifi.id]),
            owner=self.owner,
            db=self.db,
        )
        self.assertEqual(response[0].name, "Wi-Fi")

        with self.assertRaises(HTTPException) as raised:
            media.set_pg_amenities(
                self.other_pg.id,
                AmenityIdsRequest(amenity_ids=[wifi.id]),
                owner=self.owner,
                db=self.db,
            )
        self.assertEqual(raised.exception.status_code, status.HTTP_404_NOT_FOUND)

        self.db.add(Amenity(name="Wi-Fi", is_active=True))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_upload_moderation_and_public_visibility(self):
        photo = self.upload()
        self.assertEqual(photo.review_status, "pending")
        self.assertEqual(photo.caption, "Room")
        storage_key = next(iter(self.storage.iter_keys()))
        self.assertNotIn(storage_key, photo.url)
        self.assertEqual(
            media.get_public_pg_media(self.pg.id, db=self.db).photos,
            [],
        )

        media.review_photo(
            photo.id,
            PhotoReviewRequest(action="approve"),
            db=self.db,
        )
        public_media = media.get_public_pg_media(self.pg.id, db=self.db)
        self.assertEqual(len(public_media.photos), 1)
        self.assertEqual(public_media.cover_photo, None)
        search_results = get_pgs(
            stay_type=None,
            min_rent=None,
            max_rent=None,
            min_available_beds=None,
            max_monthly_rent_per_person=None,
            sharing_type=None,
            availability_updated_within_hours=None,
            db=self.db,
        )
        self.assertEqual(len(search_results), 2)
        self.assertTrue(
            all(
                result.photos == [] or result.photos[0].id == photo.id
                for result in search_results
            )
        )

    def test_upload_rejects_invalid_image_content(self):
        upload = UploadFile(filename="photo.jpg", file=BytesIO(b"not image data"))
        with self.assertRaises(HTTPException) as raised:
            self.upload(upload=upload)
        self.assertEqual(
            raised.exception.status_code,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
        self.assertEqual(list(self.storage.iter_keys() or []), [])

    def test_upload_storage_failure_does_not_create_photo_record(self):
        class BrokenStorage:
            def store(self, content, extension):
                raise OSError("test storage failure")

            def delete(self, storage_key):
                raise AssertionError("nothing should be stored")

        with patch.object(media, "photo_storage", BrokenStorage()):
            with self.assertRaises(HTTPException) as raised:
                self.upload()
        self.assertEqual(
            raised.exception.status_code,
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
        self.assertEqual(
            self.db.scalar(
                select(PGPhoto.id).where(PGPhoto.pg_id == self.pg.id)
            ),
            None,
        )

    def test_cover_selection_moves_cover_without_duplicates(self):
        photos = []
        for order in range(2):
            photo = PGPhoto(
                pg_id=self.pg.id,
                storage_key=f"{order + 1:032x}.jpg",
                media_type="image/jpeg",
                display_order=order,
                is_cover=False,
                review_status="approved",
            )
            self.db.add(photo)
            photos.append(photo)
        self.db.commit()

        media.select_cover_photo(photos[0].id, owner=self.owner, db=self.db)
        media.select_cover_photo(photos[1].id, owner=self.owner, db=self.db)
        covers = self.db.scalars(
            select(PGPhoto).where(
                PGPhoto.pg_id == self.pg.id,
                PGPhoto.is_cover.is_(True),
            )
        ).all()
        self.assertEqual([photo.id for photo in covers], [photos[1].id])

    def test_photo_order_is_replaced_as_a_complete_gallery(self):
        photos = []
        for order in range(2):
            photo = PGPhoto(
                pg_id=self.pg.id,
                storage_key=f"{order + 3:032x}.jpg",
                media_type="image/jpeg",
                display_order=order,
                review_status="pending",
            )
            self.db.add(photo)
            photos.append(photo)
        self.db.commit()

        updated = reorder_pg_photos(
            self.pg.id,
            PhotoOrderRequest(photo_ids=[photos[1].id, photos[0].id]),
            owner=self.owner,
            db=self.db,
        )
        self.assertEqual(
            [(photo.id, photo.display_order) for photo in updated],
            [(photos[1].id, 0), (photos[0].id, 1)],
        )

    def test_owner_cannot_upload_to_another_owners_pg(self):
        with self.assertRaises(HTTPException) as raised:
            self.upload(pg=self.other_pg, owner=self.owner)
        self.assertEqual(raised.exception.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(list(self.storage.iter_keys() or []), [])

    def test_upload_enforces_configured_file_size(self):
        with patch.object(settings, "photo_max_upload_bytes", 32):
            with self.assertRaises(HTTPException) as raised:
                self.upload()
        self.assertEqual(
            raised.exception.status_code,
            status.HTTP_413_CONTENT_TOO_LARGE,
        )
        self.assertEqual(list(self.storage.iter_keys() or []), [])

    def test_rejected_photos_and_unapproved_listings_are_hidden(self):
        photo = self.upload()
        media.review_photo(
            photo.id,
            PhotoReviewRequest(action="reject"),
            db=self.db,
        )
        self.assertEqual(
            media.get_public_pg_media(self.pg.id, db=self.db).photos,
            [],
        )
        self.pg.is_active = False
        self.db.commit()
        with self.assertRaises(HTTPException) as raised:
            media.get_public_pg_media(self.pg.id, db=self.db)
        self.assertEqual(raised.exception.status_code, status.HTTP_404_NOT_FOUND)

    def test_owner_resubmission_removes_listing_and_media_from_public_apis(self):
        verification = self.db.scalar(
            select(OwnerVerification).where(
                OwnerVerification.owner_id == self.owner.id
            )
        )
        verification.verification_status = "pending"
        self.db.commit()

        with self.assertRaises(HTTPException) as raised:
            media.get_public_pg_media(self.pg.id, db=self.db)
        self.assertEqual(raised.exception.status_code, status.HTTP_404_NOT_FOUND)

        results = get_pgs(
            city_id=None,
            area_id=None,
            stay_type=None,
            min_rent=None,
            max_rent=None,
            verified_only=False,
            db=self.db,
        )
        self.assertNotIn(self.pg.id, [pg.id for pg in results])


if __name__ == "__main__":
    unittest.main()
