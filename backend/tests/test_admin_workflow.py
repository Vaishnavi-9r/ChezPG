import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from http import HTTPStatus
from unittest.mock import patch

from fastapi import HTTPException, status
from fastapi import Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.admin import (
    create_nearby_place,
    get_pending_pgs,
    get_pg_review_history,
    require_admin,
    review_owner_verification,
    review_pg,
    update_nearby_place,
)
from app.api.v1.nearby_places import get_nearby_place, list_nearby_places
from app.api.v1.dependencies import require_owner
from app.api.v1.owners import (
    get_owner_pgs,
    login_owner,
    register_owner,
    submit_owner_verification,
    update_owner_pg,
)
from app.api.v1.pgs import get_pgs
from app.api.v1.rooms import (
    create_room,
    get_room_availability_history,
    list_rooms,
    update_room,
)
from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.models import (
    Area,
    Amenity,
    City,
    Owner,
    OwnerVerification,
    OwnerVerificationAuditEvent,
    NearbyPlace,
    PG,
    PGReviewEvent,
    Room,
    RoomAvailabilityHistory,
)
from app.schemas.admin import PGReviewRequest
from app.schemas.owner import (
    OwnerLoginRequest,
    OwnerPGUpdate,
    OwnerRegistration,
    OwnerVerificationSubmission,
)
from app.schemas.owner_admin import OwnerVerificationReviewRequest
from app.schemas.nearby_place import (
    NearbyPlaceCreate,
    NearbyPlaceUpdate,
)
from app.schemas.room import RoomCreate, RoomUpdate
from app.services.distance import haversine_distance_km


class ChezPGWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

        city = City(name="Test City", state="Test State", country="India")
        self.db.add(city)
        self.db.flush()
        area = Area(city_id=city.id, name="Test Area")
        self.db.add(area)
        self.db.flush()
        self.city_id = city.id
        self.area_id = area.id

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def add_owner(
        self,
        email="owner@example.com",
        verified=False,
        role="owner",
    ):
        owner = Owner(
            full_name="Test Owner",
            email=email,
            phone_number="+919876543210",
            relationship_type="property_owner",
            password_hash=hash_password("safe-password-for-test"),
            account_status="active",
            role=role,
        )
        self.db.add(owner)
        self.db.flush()
        owner.phone_number = f"+9198765{owner.id:05d}"
        if verified:
            self.db.add(
                OwnerVerification(
                    owner_id=owner.id,
                    verification_status="approved",
                    management_authority_status="approved",
                    legal_name=owner.full_name,
                    identity_document_key="identity-test-document.pdf",
                    authority_document_key="authority-test-document.pdf",
                )
            )
        self.db.commit()
        return owner

    def add_admin(self, email="reviewer@example.com"):
        return self.add_owner(email=email, role="admin")

    def add_pg(
        self,
        verification_status="pending",
        is_active=False,
        owner=None,
    ):
        pg = PG(
            city_id=self.city_id,
            area_id=self.area_id,
            owner_id=owner.id if owner else None,
            name="Test PG",
            address="123 Test Street",
            stay_type="co_living",
            monthly_rent=Decimal("10000.00"),
            verification_status=verification_status,
            is_active=is_active,
        )
        self.db.add(pg)
        self.db.commit()
        return pg

    def search_pgs(self, **filters):
        parameters = {
            "city_id": None,
            "area_id": None,
            "stay_type": None,
            "min_rent": None,
            "max_rent": None,
            "food_available": None,
            "electricity_included": None,
            "verified_only": False,
            "available_only": False,
            "min_available_beds": None,
            "max_monthly_rent_per_person": None,
            "sharing_type": None,
            "amenity_ids": None,
            "availability_updated_within_hours": None,
            "nearby_place_id": None,
            "max_distance_km": None,
            "limit": 20,
            "offset": 0,
            "response": Response(),
            "db": self.db,
        }
        parameters.update(filters)
        return get_pgs(**parameters)

    def test_missing_and_invalid_admin_tokens_return_401(self):
        with patch.object(
            settings,
            "owner_token_secret",
            "a-test-token-secret-that-is-at-least-32-bytes",
        ):
            for provided_key in (None, "wrong-key"):
                with self.subTest(provided_key=provided_key):
                    with self.assertRaises(HTTPException) as raised:
                        credentials = (
                            HTTPAuthorizationCredentials(
                                scheme="Bearer",
                                credentials=provided_key,
                            )
                            if provided_key is not None
                            else None
                        )
                        require_admin(credentials, self.db)
                    self.assertEqual(
                        raised.exception.status_code,
                        status.HTTP_401_UNAUTHORIZED,
                    )

    def test_admin_requires_server_assigned_admin_role(self):
        owner = self.add_owner(role="owner")
        with patch.object(
            settings,
            "owner_token_secret",
            "a-test-token-secret-that-is-at-least-32-bytes",
        ):
            token = create_access_token(owner.id, owner.token_version)
            with self.assertRaises(HTTPException) as raised:
                require_admin(
                    HTTPAuthorizationCredentials(
                        scheme="Bearer",
                        credentials=token,
                    ),
                    self.db,
                )
        self.assertEqual(
            raised.exception.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_pending_list_only_returns_pending_inactive_rows_in_id_order(self):
        expected_first = self.add_pg()
        self.add_pg(verification_status="pending", is_active=True)
        self.add_pg(verification_status="verified", is_active=False)
        self.add_pg(verification_status="rejected", is_active=False)
        expected_last = self.add_pg()

        result = get_pending_pgs(self.db)

        self.assertEqual(
            [pg.id for pg in result],
            [expected_first.id, expected_last.id],
        )

    def test_approval_requires_separately_verified_owner(self):
        owner = self.add_owner(verified=True)
        pg = self.add_pg(owner=owner)
        admin = self.add_admin()

        result = review_pg(
            pg.id,
            PGReviewRequest(action="approve"),
            self.db,
            admin,
        )

        self.assertEqual(result.verification_status, "verified")
        self.assertTrue(result.is_active)
        self.assertEqual(owner.verification.verification_status, "approved")

    def test_unverified_owner_cannot_have_a_pg_approved(self):
        owner = self.add_owner()
        pg = self.add_pg(owner=owner)
        admin = self.add_admin()

        with self.assertRaises(HTTPException) as raised:
            review_pg(
                pg.id,
                PGReviewRequest(action="approve"),
                self.db,
                admin,
            )

        self.assertEqual(raised.exception.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(pg.verification_status, "pending")
        self.assertFalse(pg.is_active)

    def test_rejection_marks_listing_rejected_and_inactive(self):
        pg = self.add_pg()
        admin = self.add_admin()

        result = review_pg(
            pg.id,
            PGReviewRequest(action="reject", reason="Evidence did not match"),
            self.db,
            admin,
        )

        self.assertEqual(result.verification_status, "rejected")
        self.assertFalse(result.is_active)

    def test_reviewing_an_already_reviewed_listing_returns_409(self):
        pg = self.add_pg(verification_status="verified", is_active=True)
        admin = self.add_admin()

        with self.assertRaises(HTTPException) as raised:
            review_pg(
                pg.id,
                PGReviewRequest(action="approve"),
                self.db,
                admin,
            )

        self.assertEqual(
            raised.exception.status_code,
            status.HTTP_409_CONFLICT,
        )

    def test_reviewing_a_missing_listing_returns_404(self):
        admin = self.add_admin()
        with self.assertRaises(HTTPException) as raised:
            review_pg(999, PGReviewRequest(action="approve"), self.db, admin)

        self.assertEqual(
            raised.exception.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_invalid_review_action_fails_schema_validation(self):
        with self.assertRaises(ValidationError):
            PGReviewRequest(action="activate")

    def test_public_search_excludes_inactive_and_supports_verified_filter(self):
        pending = self.add_pg(verification_status="pending", is_active=False)
        rejected = self.add_pg(verification_status="rejected", is_active=False)
        active_pending = self.add_pg(
            verification_status="pending",
            is_active=True,
        )
        verified = self.add_pg(verification_status="verified", is_active=True)

        active_results = get_pgs(
            city_id=None,
            area_id=None,
            stay_type=None,
            min_rent=None,
            max_rent=None,
            verified_only=False,
            min_available_beds=None,
            max_monthly_rent_per_person=None,
            sharing_type=None,
            availability_updated_within_hours=None,
            db=self.db,
        )
        verified_results = get_pgs(
            city_id=None,
            area_id=None,
            stay_type=None,
            min_rent=None,
            max_rent=None,
            verified_only=True,
            min_available_beds=None,
            max_monthly_rent_per_person=None,
            sharing_type=None,
            availability_updated_within_hours=None,
            db=self.db,
        )

        self.assertEqual([pg.id for pg in active_results], [verified.id])
        self.assertEqual([pg.id for pg in verified_results], [verified.id])
        self.assertNotIn(pending.id, [pg.id for pg in active_results])
        self.assertNotIn(rejected.id, [pg.id for pg in active_results])
        self.assertNotIn(active_pending.id, [pg.id for pg in active_results])

    def test_public_search_no_filters_excludes_pending_and_inactive_pgs(self):
        active = self.add_pg(verification_status="verified", is_active=True)
        self.add_pg(verification_status="pending", is_active=False)
        self.add_pg(verification_status="verified", is_active=False)

        results = self.search_pgs()

        self.assertEqual([result.id for result in results], [active.id])

    def test_public_search_rent_range_and_invalid_bounds(self):
        lower = self.add_pg(verification_status="verified", is_active=True)
        lower.monthly_rent = Decimal("8000")
        self.db.commit()
        upper = self.add_pg(verification_status="verified", is_active=True)
        upper.monthly_rent = Decimal("16000")
        self.db.commit()

        results = self.search_pgs(
            min_rent=Decimal("8000"),
            max_rent=Decimal("10000"),
        )
        self.assertEqual([result.id for result in results], [lower.id])

        with self.assertRaises(HTTPException) as raised:
            self.search_pgs(
                min_rent=Decimal("15000"),
                max_rent=Decimal("10000"),
            )
        self.assertEqual(
            raised.exception.status_code,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    def test_public_search_stay_type_food_electricity_and_verified(self):
        matching = self.add_pg(verification_status="verified", is_active=True)
        matching.stay_type = "women"
        matching.food_available = True
        matching.electricity_included = True
        other = self.add_pg(verification_status="verified", is_active=True)
        other.stay_type = "men"
        other.food_available = True
        other.electricity_included = False
        pending = self.add_pg(verification_status="pending", is_active=True)
        pending.stay_type = "women"
        pending.food_available = True
        pending.electricity_included = True
        self.db.commit()

        results = self.search_pgs(
            stay_type="women",
            food_available=True,
            electricity_included=True,
            verified_only=True,
        )
        self.assertEqual([result.id for result in results], [matching.id])

    def test_public_search_available_beds_and_combined_filters(self):
        owner = self.add_owner(verified=True)
        matching = self.add_pg(
            verification_status="verified",
            is_active=True,
            owner=owner,
        )
        matching.food_available = True
        wifi = Amenity(name="Wi-Fi", is_active=True)
        laundry = Amenity(name="Laundry", is_active=True)
        self.db.add_all([wifi, laundry])
        self.db.flush()
        matching.amenities = [wifi, laundry]
        create_room(
            matching.id,
            RoomCreate(
                label="Open double",
                sharing_type="double",
                monthly_rent_per_person=Decimal("12000"),
                total_beds=3,
                occupied_beds=1,
            ),
            owner,
            self.db,
        )
        no_beds = self.add_pg(verification_status="verified", is_active=True)
        no_beds.amenities = [wifi, laundry]
        self.db.commit()

        results = self.search_pgs(
            city_id=self.city_id,
            area_id=self.area_id,
            food_available=True,
            available_only=True,
            min_available_beds=2,
            amenity_ids=[wifi.id, laundry.id],
        )
        self.assertEqual([result.id for result in results], [matching.id])
        self.assertEqual(results[0].total_available_beds, 2)

    def test_public_search_multiple_amenities_do_not_duplicate_listings(self):
        first = self.add_pg(verification_status="verified", is_active=True)
        second = self.add_pg(verification_status="verified", is_active=True)
        wifi = Amenity(name="Wi-Fi", is_active=True)
        parking = Amenity(name="Parking", is_active=True)
        self.db.add_all([wifi, parking])
        self.db.flush()
        first.amenities = [wifi, parking]
        second.amenities = [wifi]
        self.db.commit()

        results = self.search_pgs(amenity_ids=[wifi.id, parking.id])

        self.assertEqual([result.id for result in results], [first.id])

    def test_public_search_pagination_has_total_and_deterministic_order(self):
        created = [
            self.add_pg(verification_status="verified", is_active=True)
            for _ in range(3)
        ]
        response = Response()

        page = self.search_pgs(limit=2, offset=0, response=response)
        next_page = self.search_pgs(limit=2, offset=2)

        self.assertEqual([item.id for item in page], [created[2].id, created[1].id])
        self.assertEqual([item.id for item in next_page], [created[0].id])
        self.assertEqual(response.headers["X-Total-Count"], "3")
        self.assertEqual(response.headers["X-Limit"], "2")
        self.assertEqual(response.headers["X-Offset"], "0")

    def test_nearby_place_admin_create_and_public_filters(self):
        created = create_nearby_place(
            NearbyPlaceCreate(
                city_id=self.city_id,
                area_id=self.area_id,
                name="Example Campus",
                category="university",
                address="Development test address",
                latitude=17.0,
                longitude=78.0,
            ),
            db=self.db,
        )
        self.assertEqual(created.category, "university")

        matching = list_nearby_places(
            city_id=self.city_id,
            area_id=self.area_id,
            category="university",
            q="campus",
            limit=10,
            offset=0,
            db=self.db,
        )
        self.assertEqual([place.id for place in matching], [created.id])
        self.assertEqual(get_nearby_place(created.id, db=self.db).name, "Example Campus")
        additional = create_nearby_place(
            NearbyPlaceCreate(
                city_id=self.city_id,
                area_id=self.area_id,
                name="Example Campus Annex",
                category="university",
                latitude=17.1,
                longitude=78.1,
            ),
            db=self.db,
        )
        page_response = Response()
        second_page = list_nearby_places(
            city_id=self.city_id,
            area_id=self.area_id,
            category="university",
            q="campus",
            limit=1,
            offset=1,
            response=page_response,
            db=self.db,
        )
        self.assertEqual([place.id for place in second_page], [additional.id])
        self.assertEqual(page_response.headers["X-Total-Count"], "2")
        update_nearby_place(
            additional.id,
            NearbyPlaceUpdate(is_active=False),
            db=self.db,
        )
        self.assertEqual(
            [place.id for place in list_nearby_places(db=self.db)],
            [created.id],
        )

        inactive = create_nearby_place(
            NearbyPlaceCreate(
                city_id=self.city_id,
                name="Inactive Hospital",
                category="hospital",
                latitude=0,
                longitude=0,
            ),
            db=self.db,
        )
        self.db.get(NearbyPlace, inactive.id).is_active = False
        self.db.commit()
        self.assertEqual(
            get_nearby_place(created.id, db=self.db).id,
            created.id,
        )
        with self.assertRaises(HTTPException) as raised:
            get_nearby_place(inactive.id, db=self.db)
        self.assertEqual(raised.exception.status_code, status.HTTP_404_NOT_FOUND)

    def test_nearby_place_rejects_bad_coordinates_and_city_area_pair(self):
        with self.assertRaises(ValidationError):
            NearbyPlaceCreate(
                city_id=self.city_id,
                name="Invalid Place",
                category="college",
                latitude=91,
                longitude=0,
            )
        with self.assertRaises(HTTPException) as raised:
            create_nearby_place(
                NearbyPlaceCreate(
                    city_id=self.city_id,
                    area_id=self.area_id + 1,
                    name="Bad Area Place",
                    category="college",
                    latitude=17,
                    longitude=78,
                ),
                db=self.db,
            )
        self.assertEqual(
            raised.exception.status_code,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    def test_nearby_place_duplicate_and_coordinate_constraints(self):
        payload = NearbyPlaceCreate(
            city_id=self.city_id,
            name="Unique Place",
            category="college",
            latitude=17,
            longitude=78,
        )
        create_nearby_place(payload, db=self.db)
        with self.assertRaises(HTTPException) as duplicate:
            create_nearby_place(payload, db=self.db)
        self.assertEqual(
            duplicate.exception.status_code,
            status.HTTP_409_CONFLICT,
        )

        invalid_pg = PG(
            city_id=self.city_id,
            area_id=self.area_id,
            name="Invalid Coordinate PG",
            address="123 Test Street",
            stay_type="co_living",
            monthly_rent=Decimal("10000"),
            verification_status="verified",
            is_active=True,
            latitude=91,
            longitude=0,
        )
        self.db.add(invalid_pg)
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_haversine_distance_known_equatorial_coordinates(self):
        distance = haversine_distance_km(0, 0, 0, 1)
        self.assertAlmostEqual(distance, 111.195, places=2)

    def test_distance_search_radius_combines_filters_and_excludes_missing_coordinates(self):
        nearby_place = NearbyPlace(
            city_id=self.city_id,
            area_id=self.area_id,
            name="Distance Origin",
            category="tech_park",
            latitude=0,
            longitude=0,
            is_active=True,
        )
        self.db.add(nearby_place)
        self.db.flush()

        owner = self.add_owner(verified=True)
        inside = self.add_pg(
            verification_status="verified",
            is_active=True,
            owner=owner,
        )
        inside.latitude, inside.longitude = 0, 0.5
        inside.monthly_rent = Decimal("9000")
        inside.stay_type = "women"

        outside = self.add_pg(
            verification_status="verified",
            is_active=True,
            owner=owner,
        )
        outside.latitude, outside.longitude = 0, 2
        outside.monthly_rent = Decimal("8000")
        outside.stay_type = "women"

        missing_coordinates = self.add_pg(
            verification_status="verified",
            is_active=True,
            owner=owner,
        )
        missing_coordinates.monthly_rent = Decimal("7000")
        missing_coordinates.stay_type = "women"
        self.db.commit()

        results = self.search_pgs(
            nearby_place_id=nearby_place.id,
            max_distance_km=Decimal("100"),
            min_rent=Decimal("8500"),
            max_rent=Decimal("10000"),
            stay_type="women",
        )
        self.assertEqual([result.id for result in results], [inside.id])
        self.assertAlmostEqual(results[0].distance_km, 55.6, places=0)

    def test_distance_search_reference_errors_and_inactive_listings(self):
        place = NearbyPlace(
            city_id=self.city_id,
            name="Radius Origin",
            category="metro_station",
            latitude=17,
            longitude=78,
            is_active=True,
        )
        self.db.add(place)
        self.db.commit()

        with self.assertRaises(HTTPException) as missing:
            self.search_pgs(nearby_place_id=999)
        self.assertEqual(missing.exception.status_code, status.HTTP_404_NOT_FOUND)

        with self.assertRaises(HTTPException) as radius_without_reference:
            self.search_pgs(max_distance_km=Decimal("10"))
        self.assertEqual(
            radius_without_reference.exception.status_code,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
        for invalid_distance in (Decimal("-1"), Decimal("20041")):
            with self.subTest(invalid_distance=invalid_distance):
                with self.assertRaises(HTTPException) as invalid_radius:
                    self.search_pgs(
                        nearby_place_id=place.id,
                        max_distance_km=invalid_distance,
                    )
                self.assertEqual(
                    invalid_radius.exception.status_code,
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                )
        with self.assertRaises(HTTPException) as invalid_place_id:
            self.search_pgs(nearby_place_id=0)
        self.assertEqual(
            invalid_place_id.exception.status_code,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

        with self.assertRaises(ValidationError):
            NearbyPlaceUpdate(latitude=18)

        visible = self.add_pg(verification_status="verified", is_active=True)
        visible.latitude, visible.longitude = 17, 78
        hidden = self.add_pg(verification_status="verified", is_active=False)
        hidden.latitude, hidden.longitude = 17, 78
        self.db.commit()
        results = self.search_pgs(
            nearby_place_id=place.id,
            max_distance_km=Decimal("0"),
        )
        self.assertEqual([result.id for result in results], [visible.id])

    def test_registration_hashes_password_and_does_not_verify_owner(self):
        payload = OwnerRegistration(
            full_name=" New Owner ",
            email="New.Owner@example.com",
            phone_number="+919876543210",
            relationship_type="pg_operator",
            password="long-enough-password",
        )

        response = register_owner(payload, self.db)
        owner = self.db.get(Owner, response.id)

        self.assertEqual(response.email, "new.owner@example.com")
        self.assertEqual(response.verification_status, "unverified")
        self.assertNotEqual(owner.password_hash, payload.password)
        self.assertNotIn("password_hash", response.model_dump())
        self.assertEqual(owner.account_status, "active")

    def test_registration_rejects_client_supplied_privileges(self):
        with self.assertRaises(ValidationError):
            OwnerRegistration.model_validate(
                {
                    "full_name": "Test Owner",
                    "email": "owner@example.com",
                    "phone_number": "+919876543210",
                    "relationship_type": "property_owner",
                    "password": "long-enough-password",
                    "account_status": "admin",
                    "verification_status": "verified",
                }
            )

    def test_owner_login_issues_token_only_for_valid_credentials(self):
        owner = self.add_owner(verified=True)
        with patch.object(
            settings,
            "owner_token_secret",
            "a-test-token-secret-that-is-at-least-32-bytes",
        ):
            result = login_owner(
                OwnerLoginRequest(
                    email=owner.email,
                    password="safe-password-for-test",
                ),
                self.db,
            )
            self.assertEqual(result.token_type, "bearer")
            self.assertGreater(result.expires_in, 0)

            with self.assertRaises(HTTPException) as raised:
                login_owner(
                    OwnerLoginRequest(
                        email=owner.email,
                        password="incorrect-password",
                    ),
                    self.db,
                )
        self.assertEqual(
            raised.exception.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_owner_token_authentication_and_owner_isolation(self):
        owner = self.add_owner()
        other_owner = self.add_owner(email="other@example.com")
        owned_pg = self.add_pg(owner=owner)
        token_secret = "a-test-token-secret-that-is-at-least-32-bytes"

        with patch.object(settings, "owner_token_secret", token_secret):
            token = create_access_token(other_owner.id)
            authenticated = require_owner(
                HTTPAuthorizationCredentials(scheme="Bearer", credentials=token),
                self.db,
            )

        self.assertEqual(authenticated.id, other_owner.id)
        self.assertEqual(get_owner_pgs(other_owner, self.db), [])
        with self.assertRaises(HTTPException) as raised:
            update_owner_pg(
                owned_pg.id,
                OwnerPGUpdate(name="Hijacked listing"),
                other_owner,
                self.db,
            )
        self.assertEqual(raised.exception.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.db.get(PG, owned_pg.id).name, "Test PG")

    def test_missing_or_invalid_owner_token_is_unauthorized(self):
        owner = self.add_owner()
        with patch.object(
            settings,
            "owner_token_secret",
            "a-test-token-secret-that-is-at-least-32-bytes",
        ):
            for credentials in (
                None,
                HTTPAuthorizationCredentials(
                    scheme="Bearer",
                    credentials="not-a-valid-token",
                ),
            ):
                with self.subTest(credentials=credentials):
                    with self.assertRaises(HTTPException) as raised:
                        require_owner(credentials, self.db)
                    self.assertEqual(
                        raised.exception.status_code,
                        status.HTTP_401_UNAUTHORIZED,
                    )
        self.assertIsNotNone(owner)

    def test_owner_authentication_requires_a_strong_configured_signing_secret(self):
        with patch.object(settings, "owner_token_secret", None):
            with self.assertRaises(HTTPException) as raised:
                require_owner(None, self.db)
        self.assertEqual(
            raised.exception.status_code,
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    def test_owner_cannot_set_verification_status_in_submission(self):
        with self.assertRaises(ValidationError):
            OwnerVerificationSubmission.model_validate(
                {
                    "submission_notes": "Please verify me",
                    "verification_status": "verified",
                }
            )

    def test_owner_verification_requires_admin_and_does_not_verify_pg(self):
        owner = self.add_owner()
        pg = self.add_pg(owner=owner)
        submission = submit_owner_verification(
            OwnerVerificationSubmission(submission_notes="Ready for review"),
            owner,
            self.db,
        )

        self.assertEqual(submission.verification_status, "pending")
        verification = self.db.scalar(
            select(OwnerVerification).where(
                OwnerVerification.owner_id == owner.id
            )
        )
        verification.legal_name = "Test Owner"
        verification.identity_document_type = "passport"
        verification.identity_document_key = "private-identity.pdf"
        verification.authority_document_type = "ownership_deed"
        verification.authority_document_key = "private-authority.pdf"
        self.db.commit()
        self.assertEqual(pg.verification_status, "pending")
        self.assertFalse(pg.is_active)

        administrator = self.add_owner(
            email="administrator@example.com",
            role="admin",
        )
        with patch.object(
            settings,
            "owner_token_secret",
            "a-test-token-secret-that-is-at-least-32-bytes",
        ):
            require_admin(
                HTTPAuthorizationCredentials(
                    scheme="Bearer",
                    credentials=create_access_token(
                        administrator.id,
                        administrator.token_version,
                    ),
                ),
                self.db,
            )
        reviewed = review_owner_verification(
            owner.id,
            OwnerVerificationReviewRequest(
                verification_type="identity",
                action="approve",
                review_notes="Reviewed offline",
            ),
            self.db,
            administrator,
        )

        self.assertEqual(reviewed.status, "approved")
        self.assertEqual(
            self.db.query(OwnerVerificationAuditEvent)
            .filter_by(verification_id=verification.id)
            .count(),
            1,
        )
        self.assertEqual(verification.management_authority_status, "pending")
        self.assertEqual(pg.verification_status, "pending")
        self.assertFalse(pg.is_active)

    def test_owner_cannot_change_or_manage_another_owners_listing(self):
        owner = self.add_owner()
        other_owner = self.add_owner(email="other@example.com")
        pg = self.add_pg(owner=owner, verification_status="verified", is_active=True)

        with self.assertRaises(ValidationError):
            OwnerPGUpdate.model_validate(
                {"name": "Changed", "owner_id": other_owner.id, "is_active": True}
            )

        with self.assertRaises(HTTPException) as raised:
            update_owner_pg(
                pg.id,
                OwnerPGUpdate(name="Changed"),
                other_owner,
                self.db,
            )
        self.assertEqual(raised.exception.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(pg.owner_id, owner.id)
        self.assertEqual(pg.verification_status, "verified")
        self.assertTrue(pg.is_active)

    def test_listing_creation_rejects_client_owner_and_review_fields(self):
        from app.schemas.pg import PGCreate

        other_owner = self.add_owner(email="other@example.com")
        with self.assertRaises(ValidationError):
            PGCreate.model_validate(
                {
                    "city_id": self.city_id,
                    "area_id": self.area_id,
                    "name": "New Listing",
                    "address": "123 Test Street",
                    "stay_type": "co_living",
                    "monthly_rent": "12000.00",
                    "owner_id": other_owner.id,
                    "is_active": True,
                    "verification_status": "verified",
                }
            )

    def test_owner_update_resets_listing_to_pending_and_inactive(self):
        owner = self.add_owner(verified=True)
        pg = self.add_pg(owner=owner, verification_status="verified", is_active=True)

        result = update_owner_pg(
            pg.id,
            OwnerPGUpdate(name="Updated Test PG"),
            owner,
            self.db,
        )

        self.assertEqual(result.name, "Updated Test PG")
        self.assertEqual(result.verification_status, "pending")
        self.assertFalse(result.is_active)
        edit_event = self.db.scalar(
            select(PGReviewEvent)
            .where(PGReviewEvent.pg_id == pg.id)
            .order_by(PGReviewEvent.id.desc())
        )
        self.assertEqual(edit_event.action, "needs_resubmission")
        self.assertEqual(
            edit_event.details["name"],
            {"previous": "Test PG", "new": "Updated Test PG"},
        )

    def test_room_creation_calculates_available_beds_and_creates_history(self):
        owner = self.add_owner()
        pg = self.add_pg(owner=owner)
        payload = RoomCreate(
            label="Room 101",
            sharing_type="double",
            monthly_rent_per_person=Decimal("12500.00"),
            total_beds=2,
            occupied_beds=1,
        )

        result = create_room(pg.id, payload, owner, self.db)

        self.assertEqual(result.available_beds, 1)
        self.assertEqual(result.total_beds, 2)
        self.assertFalse(result.is_stale)
        history = self.db.scalars(
            select(RoomAvailabilityHistory).where(
                RoomAvailabilityHistory.room_id == result.id
            )
        ).one()
        self.assertIsNone(history.previous_occupied_beds)
        self.assertEqual(history.new_occupied_beds, 1)
        self.assertEqual(
            history.new_monthly_rent_per_person,
            Decimal("12500.00"),
        )
        self.assertEqual(history.actor_owner_id, owner.id)

    def test_room_validation_rejects_bad_capacity_rent_and_sharing(self):
        valid = {
            "label": "Room 1",
            "sharing_type": "single",
            "monthly_rent_per_person": "0",
            "total_beds": 1,
            "occupied_beds": 0,
        }
        for invalid in (
            {**valid, "total_beds": 0},
            {**valid, "occupied_beds": -1},
            {**valid, "occupied_beds": 2},
            {**valid, "monthly_rent_per_person": "-1"},
            {**valid, "sharing_type": "six_sharing"},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValidationError):
                    RoomCreate.model_validate(invalid)

    def test_database_constraints_prevent_invalid_room_inventory(self):
        owner = self.add_owner()
        pg = self.add_pg(owner=owner)
        invalid_room = Room(
            pg_id=pg.id,
            label="Invalid",
            sharing_type="single",
            monthly_rent_per_person=Decimal("1000"),
            total_beds=1,
            occupied_beds=2,
            is_active=True,
        )
        self.db.add(invalid_room)

        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_owner_only_lists_and_updates_rooms_for_owned_pg(self):
        owner = self.add_owner()
        other_owner = self.add_owner(email="other@example.com")
        pg = self.add_pg(owner=owner)
        other_pg = self.add_pg(owner=other_owner)
        room = create_room(
            pg.id,
            RoomCreate(
                label="Owner room",
                sharing_type="double",
                monthly_rent_per_person=Decimal("9000"),
                total_beds=2,
            ),
            owner,
            self.db,
        )
        other_room = create_room(
            other_pg.id,
            RoomCreate(
                label="Other room",
                sharing_type="single",
                monthly_rent_per_person=Decimal("15000"),
                total_beds=1,
            ),
            other_owner,
            self.db,
        )

        self.assertEqual(
            [item.id for item in list_rooms(pg.id, owner, self.db)],
            [room.id],
        )
        with self.assertRaises(HTTPException) as raised:
            list_rooms(other_pg.id, owner, self.db)
        self.assertEqual(raised.exception.status_code, status.HTTP_404_NOT_FOUND)

        with self.assertRaises(HTTPException) as raised:
            update_room(
                other_room.id,
                RoomUpdate(occupied_beds=1),
                owner,
                self.db,
            )
        self.assertEqual(raised.exception.status_code, status.HTTP_404_NOT_FOUND)

    def test_room_update_records_history_and_refreshes_timestamp(self):
        owner = self.add_owner()
        pg = self.add_pg(owner=owner)
        room = create_room(
            pg.id,
            RoomCreate(
                label="Room A",
                sharing_type="double",
                monthly_rent_per_person=Decimal("10000"),
                total_beds=2,
                occupied_beds=0,
            ),
            owner,
            self.db,
        )
        original_updated_at = room.updated_at
        result = update_room(
            room.id,
            RoomUpdate(
                occupied_beds=1,
                monthly_rent_per_person=Decimal("11000"),
            ),
            owner,
            self.db,
        )

        self.assertEqual(result.available_beds, 1)
        self.assertGreaterEqual(result.updated_at, original_updated_at)
        histories = get_room_availability_history(room.id, owner, self.db)
        update_history = histories[0]
        self.assertEqual(update_history.previous_occupied_beds, 0)
        self.assertEqual(update_history.new_occupied_beds, 1)
        self.assertEqual(
            update_history.previous_monthly_rent_per_person,
            Decimal("10000"),
        )
        self.assertEqual(
            update_history.new_monthly_rent_per_person,
            Decimal("11000"),
        )
        self.assertEqual(update_history.actor_owner_id, owner.id)

    def test_room_update_rejects_occupied_beds_above_capacity(self):
        owner = self.add_owner()
        pg = self.add_pg(owner=owner)
        room = create_room(
            pg.id,
            RoomCreate(
                label="Room B",
                sharing_type="double",
                monthly_rent_per_person=Decimal("10000"),
                total_beds=2,
                occupied_beds=1,
            ),
            owner,
            self.db,
        )

        with self.assertRaises(HTTPException) as raised:
            update_room(room.id, RoomUpdate(occupied_beds=3), owner, self.db)

        self.assertEqual(
            raised.exception.status_code,
            HTTPStatus.UNPROCESSABLE_ENTITY,
        )
        self.assertEqual(room.total_beds, 2)

    def test_stale_room_availability_is_flagged_not_removed(self):
        owner = self.add_owner()
        pg = self.add_pg(owner=owner)
        room = create_room(
            pg.id,
            RoomCreate(
                label="Old inventory",
                sharing_type="single",
                monthly_rent_per_person=Decimal("10000"),
                total_beds=1,
            ),
            owner,
            self.db,
        )
        db_room = self.db.get(Room, room.id)
        db_room.updated_at = datetime.now(timezone.utc) - timedelta(hours=169)
        self.db.commit()

        rooms = list_rooms(pg.id, owner, self.db)

        self.assertEqual(len(rooms), 1)
        self.assertTrue(rooms[0].is_stale)

    def test_public_search_returns_inventory_and_applies_room_filters(self):
        owner = self.add_owner(verified=True)
        pg = self.add_pg(verification_status="verified", is_active=True, owner=owner)
        create_room(
            pg.id,
            RoomCreate(
                label="Double",
                sharing_type="double",
                monthly_rent_per_person=Decimal("12000"),
                total_beds=3,
                occupied_beds=1,
            ),
            owner,
            self.db,
        )
        pg.availability_confirmed_at = datetime.now(timezone.utc)
        self.db.commit()
        results = get_pgs(
            city_id=None,
            area_id=None,
            stay_type=None,
            min_rent=None,
            max_rent=None,
            verified_only=True,
            min_available_beds=2,
            max_monthly_rent_per_person=Decimal("13000"),
            sharing_type="double",
            availability_updated_within_hours=24,
            db=self.db,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].total_available_beds, 2)
        self.assertEqual(results[0].rooms[0].available_beds, 2)
        self.assertIsNotNone(results[0].availability_updated_at)
        self.assertFalse(results[0].availability_is_stale)
        self.assertFalse(hasattr(results[0], "owner_id"))

    def test_public_search_excludes_inactive_rooms_and_marks_listing_stale(self):
        owner = self.add_owner(verified=True)
        pg = self.add_pg(verification_status="verified", is_active=True, owner=owner)
        room = create_room(
            pg.id,
            RoomCreate(
                label="Inactive room",
                sharing_type="single",
                monthly_rent_per_person=Decimal("10000"),
                total_beds=1,
            ),
            owner,
            self.db,
        )
        update_room(
            room.id,
            RoomUpdate(is_active=False),
            owner,
            self.db,
        )

        results = get_pgs(
            city_id=None,
            area_id=None,
            stay_type=None,
            min_rent=None,
            max_rent=None,
            verified_only=False,
            min_available_beds=None,
            max_monthly_rent_per_person=None,
            sharing_type=None,
            availability_updated_within_hours=None,
            db=self.db,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].rooms, [])
        self.assertEqual(results[0].total_available_beds, 0)
        self.assertTrue(results[0].availability_is_stale)

    def test_freshness_filter_excludes_stale_room_inventory(self):
        owner = self.add_owner()
        pg = self.add_pg(verification_status="verified", is_active=True, owner=owner)
        room = create_room(
            pg.id,
            RoomCreate(
                label="Stale room",
                sharing_type="single",
                monthly_rent_per_person=Decimal("10000"),
                total_beds=1,
            ),
            owner,
            self.db,
        )
        db_room = self.db.get(Room, room.id)
        db_room.updated_at = datetime.now(timezone.utc) - timedelta(hours=25)
        self.db.commit()

        results = get_pgs(
            city_id=None,
            area_id=None,
            stay_type=None,
            min_rent=None,
            max_rent=None,
            verified_only=False,
            min_available_beds=None,
            max_monthly_rent_per_person=None,
            sharing_type=None,
            availability_updated_within_hours=24,
            db=self.db,
        )

        self.assertEqual(results, [])

    def test_room_search_filters_must_match_the_same_room(self):
        owner = self.add_owner()
        pg = self.add_pg(verification_status="verified", is_active=True, owner=owner)
        for label, sharing, rent in (
            ("Expensive double", "double", Decimal("15000")),
            ("Cheap single", "single", Decimal("10000")),
        ):
            create_room(
                pg.id,
                RoomCreate(
                    label=label,
                    sharing_type=sharing,
                    monthly_rent_per_person=rent,
                    total_beds=1,
                ),
                owner,
                self.db,
            )

        results = get_pgs(
            city_id=None,
            area_id=None,
            stay_type=None,
            min_rent=None,
            max_rent=None,
            verified_only=False,
            min_available_beds=1,
            max_monthly_rent_per_person=Decimal("12000"),
            sharing_type="double",
            availability_updated_within_hours=None,
            db=self.db,
        )

        self.assertEqual(results, [])

    def test_simultaneous_inventory_updates_cannot_overbook_capacity(self):
        handle, db_path = tempfile.mkstemp(suffix=".sqlite")
        os.close(handle)
        engine = create_engine(
            f"sqlite+pysqlite:///{db_path}",
            connect_args={"check_same_thread": False, "timeout": 10},
        )
        Base.metadata.create_all(engine)
        with Session(engine) as setup_db:
            city = City(name="Concurrent City", state="TS")
            setup_db.add(city)
            setup_db.flush()
            area = Area(city_id=city.id, name="Concurrent Area")
            owner = Owner(
                full_name="Concurrent Owner",
                email="concurrent@example.com",
                phone_number="+919876543210",
                relationship_type="property_owner",
                password_hash=hash_password("safe-password-for-test"),
            )
            setup_db.add_all((area, owner))
            setup_db.flush()
            pg = PG(
                city_id=city.id,
                area_id=area.id,
                owner_id=owner.id,
                name="Concurrent PG",
                address="123 Concurrent Street",
                stay_type="co_living",
                monthly_rent=Decimal("10000"),
                verification_status="verified",
                is_active=True,
            )
            setup_db.add(pg)
            setup_db.flush()
            room = Room(
                pg_id=pg.id,
                label="Two beds",
                sharing_type="double",
                monthly_rent_per_person=Decimal("10000"),
                total_beds=2,
                occupied_beds=0,
                is_active=True,
            )
            setup_db.add(room)
            setup_db.commit()
            owner_id, room_id = owner.id, room.id

        barrier = threading.Barrier(2)
        outcomes = []
        outcome_lock = threading.Lock()

        def update_concurrently(occupied_beds):
            with Session(engine) as worker_db:
                worker_owner = worker_db.get(Owner, owner_id)
                barrier.wait(timeout=5)
                try:
                    update_room(
                        room_id,
                        RoomUpdate(occupied_beds=occupied_beds),
                        worker_owner,
                        worker_db,
                    )
                    outcome = ("ok", occupied_beds)
                except HTTPException as exc:
                    outcome = ("http_error", exc.status_code)
                except Exception as exc:
                    outcome = ("error", type(exc).__name__)
                with outcome_lock:
                    outcomes.append(outcome)

        threads = [
            threading.Thread(target=update_concurrently, args=(2,)),
            threading.Thread(target=update_concurrently, args=(3,)),
        ]
        try:
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
            with Session(engine) as check_db:
                saved_room = check_db.get(Room, room_id)
                self.assertGreaterEqual(saved_room.occupied_beds, 0)
                self.assertLessEqual(
                    saved_room.occupied_beds,
                    saved_room.total_beds,
                )
            self.assertIn(
                ("http_error", HTTPStatus.UNPROCESSABLE_ENTITY),
                outcomes,
            )
            self.assertIn(("ok", 2), outcomes)
        finally:
            engine.dispose()
            os.unlink(db_path)


if __name__ == "__main__":
    unittest.main()
