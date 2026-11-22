import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from fastapi import HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.dependencies import require_owner
from app.api.v1.owners import (
    confirm_pg_availability,
    create_managed_pg,
    deactivate_managed_pg,
    get_managed_pg,
    get_pg_availability,
    get_pg_availability_history,
    get_owner_dashboard,
    list_managed_pgs,
    request_managed_pg_reactivation,
    update_pg_availability,
    update_managed_pg,
)
from app.api.v1.pgs import get_pgs
from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.models import (
    Area,
    City,
    Owner,
    OwnerVerification,
    PG,
    PGAvailabilityEvent,
    Room,
    RoomAvailabilityHistory,
)
from app.schemas.availability import (
    PGAvailabilityConfirmation,
    PGAvailabilityUpdate,
)
from app.schemas.owner import OwnerPGUpdate
from app.schemas.pg import PGCreate


class OwnerDashboardTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.city = City(name="Dashboard City", state="Telangana", country="India")
        self.db.add(self.city)
        self.db.flush()
        self.area = Area(city_id=self.city.id, name="Dashboard Area")
        self.db.add(self.area)
        self.db.flush()
        self.owner = self.make_owner()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def make_owner(self, email="dashboard-owner@example.com", role="owner"):
        owner = Owner(
            full_name="Dashboard Owner",
            email=email,
            phone_number=f"+9198765{len(email):05d}",
            relationship_type="property_owner",
            password_hash=hash_password("dashboard-test-password"),
            role=role,
            account_status="active",
        )
        self.db.add(owner)
        self.db.flush()
        return owner

    def make_pg(self, name, *, status="pending", active=False, owner=None):
        pg = PG(
            city_id=self.city.id,
            area_id=self.area.id,
            owner_id=(owner or self.owner).id,
            name=name,
            description="A listing for tests",
            address="123 Dashboard Street",
            stay_type="co_living",
            monthly_rent=Decimal("10000"),
            security_deposit=Decimal("5000"),
            food_available=True,
            electricity_included=False,
            verification_status=status,
            is_active=active,
        )
        self.db.add(pg)
        self.db.flush()
        return pg

    def create_payload(self, **overrides):
        fields = {
            "city_id": self.city.id,
            "area_id": self.area.id,
            "name": "New ChezPG Listing",
            "description": "Comfortable shared accommodation",
            "address": "456 New Street, Hyderabad",
            "stay_type": "women",
            "monthly_rent": Decimal("12500.00"),
            "security_deposit": Decimal("10000.00"),
            "food_available": True,
            "electricity_included": False,
        }
        fields.update(overrides)
        return PGCreate(**fields)

    def test_create_listing_uses_authenticated_owner_and_starts_pending(self):
        result = create_managed_pg(self.create_payload(), self.owner, self.db)

        persisted = self.db.get(PG, result.id)
        self.assertEqual(persisted.owner_id, self.owner.id)
        self.assertEqual(persisted.verification_status, "pending")
        self.assertFalse(persisted.is_active)
        self.assertEqual(result.total_available_beds, 0)

    def test_create_rejects_area_from_another_city(self):
        other_city = City(name="Other City", state="Telangana")
        self.db.add(other_city)
        self.db.flush()
        other_area = Area(city_id=other_city.id, name="Other Area")
        self.db.add(other_area)
        self.db.commit()

        with self.assertRaises(HTTPException) as raised:
            create_managed_pg(
                self.create_payload(area_id=other_area.id),
                self.owner,
                self.db,
            )
        self.assertEqual(raised.exception.status_code, status.HTTP_400_BAD_REQUEST)

    def test_dashboard_summarizes_listing_status_and_availability(self):
        active = self.make_pg("Active verified", status="verified", active=True)
        pending = self.make_pg("Pending", status="pending")
        rejected = self.make_pg("Rejected", status="rejected")
        self.db.add_all(
            [
                Room(
                    pg_id=active.id,
                    label="Room 1",
                    sharing_type="double",
                    monthly_rent_per_person=Decimal("9000"),
                    total_beds=3,
                    occupied_beds=2,
                    updated_at=datetime.now(timezone.utc),
                ),
                Room(
                    pg_id=rejected.id,
                    label="Room 2",
                    sharing_type="single",
                    monthly_rent_per_person=Decimal("12000"),
                    total_beds=1,
                    occupied_beds=1,
                    updated_at=datetime.now(timezone.utc)
                    - timedelta(days=5),
                ),
            ]
        )
        self.db.commit()

        summary = get_owner_dashboard(self.owner, self.db)

        self.assertEqual(summary.total_listings, 3)
        self.assertEqual(summary.active_listings, 1)
        self.assertEqual(summary.pending_verification, 1)
        self.assertEqual(summary.approved_listings, 1)
        self.assertEqual(summary.rejected_listings, 1)
        self.assertEqual(summary.needs_availability_update, 3)
        self.assertEqual(summary.zero_available_beds, 2)
        self.assertEqual(summary.full_listings, 2)
        self.assertEqual(summary.listings_with_available_beds, 1)

    def test_owner_listing_list_and_detail_are_scoped_and_paginated(self):
        first = self.make_pg("First")
        second = self.make_pg("Second")
        other_owner = self.make_owner("another-owner@example.com")
        other = self.make_pg("Not owned", owner=other_owner)
        self.db.commit()

        page = list_managed_pgs(
            limit=1,
            offset=0,
            response=Response(),
            owner=self.owner,
            db=self.db,
        )
        self.assertEqual([pg.id for pg in page], [second.id])
        self.assertEqual(page[0].area_name, self.area.name)
        self.assertEqual(
            get_managed_pg(first.id, self.owner, self.db).id,
            first.id,
        )
        with self.assertRaises(HTTPException) as raised:
            get_managed_pg(other.id, self.owner, self.db)
        self.assertEqual(raised.exception.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_owned_listing_validates_location_and_requires_review(self):
        pg = self.make_pg("Before")
        updated = update_managed_pg(
            pg.id,
            OwnerPGUpdate(name="Updated name"),
            self.owner,
            self.db,
        )
        self.assertEqual(updated.name, "Updated name")
        self.assertEqual(updated.verification_status, "pending")
        self.assertFalse(updated.is_active)

        other_city = City(name="Update City", state="Telangana")
        self.db.add(other_city)
        self.db.flush()
        other_area = Area(city_id=other_city.id, name="Update Area")
        self.db.add(other_area)
        self.db.commit()
        with self.assertRaises(HTTPException):
            update_managed_pg(
                pg.id,
                OwnerPGUpdate(city_id=self.city.id, area_id=other_area.id),
                self.owner,
                self.db,
            )

    def test_owner_cannot_read_or_edit_another_owners_listing(self):
        owner_with_listing = self.make_owner("owner-with-listing@example.com")
        pg = self.make_pg("Private listing", owner=owner_with_listing)
        self.db.commit()

        with self.assertRaises(HTTPException) as read_error:
            get_managed_pg(pg.id, self.owner, self.db)
        self.assertEqual(read_error.exception.status_code, status.HTTP_404_NOT_FOUND)
        with self.assertRaises(HTTPException) as update_error:
            update_managed_pg(
                pg.id,
                OwnerPGUpdate(name="Unauthorized"),
                self.owner,
                self.db,
            )
        self.assertEqual(
            update_error.exception.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_deactivation_and_reactivation_require_moderation(self):
        pg = self.make_pg("Verified listing", status="verified", active=True)
        self.db.commit()

        deactivated = deactivate_managed_pg(pg.id, self.owner, self.db)
        self.assertFalse(deactivated.is_active)
        self.assertEqual(deactivated.verification_status, "verified")

        reactivation = request_managed_pg_reactivation(pg.id, self.owner, self.db)
        self.assertFalse(reactivation.is_active)
        self.assertEqual(reactivation.verification_status, "pending")

        with self.assertRaises(HTTPException) as raised:
            request_managed_pg_reactivation(pg.id, self.owner, self.db)
        self.assertEqual(raised.exception.status_code, status.HTTP_409_CONFLICT)

    def test_forged_owner_and_moderation_fields_are_rejected(self):
        payload = self.create_payload().model_dump()
        payload["owner_id"] = 9999
        with self.assertRaises(ValidationError):
            PGCreate.model_validate(payload)

        with self.assertRaises(ValidationError):
            PGCreate.model_validate(
                self.create_payload().model_dump()
                | {"verification_status": "verified"}
            )
        with self.assertRaises(ValidationError):
            OwnerPGUpdate.model_validate({"owner_id": 9999})
        with self.assertRaises(ValidationError):
            OwnerPGUpdate.model_validate({"verification_status": "verified"})

    def test_pending_owner_listing_remains_hidden_from_public_search(self):
        self.approve_owner_for_public_listings()
        pending = self.make_pg("Pending", status="pending", active=False)
        verified = self.make_pg("Verified", status="verified", active=True)
        self.db.commit()

        results = get_pgs(
            city_id=None,
            area_id=None,
            stay_type=None,
            min_rent=None,
            max_rent=None,
            food_available=None,
            electricity_included=None,
            verified_only=False,
            available_only=False,
            min_available_beds=None,
            max_monthly_rent_per_person=None,
            sharing_type=None,
            amenity_ids=None,
            availability_updated_within_hours=None,
            nearby_place_id=None,
            max_distance_km=None,
            limit=20,
            offset=0,
            response=Response(),
            db=self.db,
        )
        self.assertEqual([result.id for result in results], [verified.id])
        self.assertNotIn(pending.id, [result.id for result in results])

    def test_non_owner_role_is_denied_owner_dependency(self):
        user = self.make_owner("regular-user@example.com", role="user")
        with patch.object(
            settings,
            "owner_token_secret",
            "a-test-token-secret-that-is-at-least-32-bytes",
        ):
            token = create_access_token(user.id, user.token_version)
            credentials = HTTPAuthorizationCredentials(
                scheme="Bearer",
                credentials=token,
            )
            with self.assertRaises(HTTPException) as raised:
                require_owner(credentials, self.db)
        self.assertEqual(raised.exception.status_code, status.HTTP_403_FORBIDDEN)

    def add_room(self, pg, *, total_beds=4, occupied_beds=2):
        room = Room(
            pg_id=pg.id,
            label=f"Room for {pg.name}",
            sharing_type="double",
            monthly_rent_per_person=Decimal("10000"),
            total_beds=total_beds,
            occupied_beds=occupied_beds,
            is_active=True,
        )
        self.db.add(room)
        self.db.commit()
        return room

    def approve_owner_for_public_listings(self):
        self.db.add(
            OwnerVerification(
                owner_id=self.owner.id,
                verification_status="approved",
                management_authority_status="approved",
                legal_name=self.owner.full_name,
                identity_document_key="identity-test.pdf",
                authority_document_key="authority-test.pdf",
            )
        )
        self.db.commit()

    def test_availability_update_records_room_and_pg_history(self):
        pg = self.make_pg("Availability update")
        room = self.add_room(pg)
        result = update_pg_availability(
            pg.id,
            PGAvailabilityUpdate(
                rooms=[{"room_id": room.id, "available_beds": 3}],
                availability_status="available",
            ),
            self.owner,
            self.db,
        )

        self.assertEqual(result.total_beds, 4)
        self.assertEqual(result.available_beds, 3)
        self.assertEqual(result.availability_status, "available")
        self.assertIsNone(result.availability_confirmed_at)
        self.assertTrue(result.availability_needs_update)
        self.assertEqual(
            self.db.query(RoomAvailabilityHistory).filter_by(pg_id=pg.id).count(),
            1,
        )
        event = self.db.query(PGAvailabilityEvent).filter_by(pg_id=pg.id).one()
        self.assertEqual(event.previous_available_beds, 2)
        self.assertEqual(event.new_available_beds, 3)
        self.assertEqual(event.actor_owner_id, self.owner.id)

        unchanged = update_pg_availability(
            pg.id,
            PGAvailabilityUpdate(
                rooms=[{"room_id": room.id, "available_beds": 3}],
                availability_status="available",
            ),
            self.owner,
            self.db,
        )
        self.assertEqual(unchanged.available_beds, 3)
        self.assertEqual(
            self.db.query(PGAvailabilityEvent).filter_by(pg_id=pg.id).count(),
            1,
        )
        self.assertEqual(
            self.db.query(RoomAvailabilityHistory).filter_by(pg_id=pg.id).count(),
            1,
        )

    def test_bed_count_validation_and_marking_pg_full(self):
        pg = self.make_pg("Full listing")
        room = self.add_room(pg, total_beds=3, occupied_beds=1)

        with self.assertRaises(ValidationError):
            PGAvailabilityUpdate(
                rooms=[{"room_id": room.id, "available_beds": -1}],
                availability_status="available",
            )
        with self.assertRaises(HTTPException) as too_many:
            update_pg_availability(
                pg.id,
                PGAvailabilityUpdate(
                    rooms=[{"room_id": room.id, "available_beds": 4}],
                    availability_status="available",
                ),
                self.owner,
                self.db,
            )
        self.assertEqual(
            too_many.exception.status_code,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
        with self.assertRaises(HTTPException) as false_full:
            update_pg_availability(
                pg.id,
                PGAvailabilityUpdate(
                    rooms=[{"room_id": room.id, "available_beds": 1}],
                    availability_status="full",
                ),
                self.owner,
                self.db,
            )
        self.assertEqual(
            false_full.exception.status_code,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

        full = update_pg_availability(
            pg.id,
            PGAvailabilityUpdate(
                rooms=[{"room_id": room.id, "available_beds": 0}],
                availability_status="full",
            ),
            self.owner,
            self.db,
        )
        self.assertEqual(full.available_beds, 0)
        self.assertEqual(full.availability_status, "full")

    def test_confirmation_updates_freshness_and_records_deliberate_event(self):
        pg = self.make_pg("Confirmed listing")
        self.add_room(pg)
        old_confirmation = datetime.now(timezone.utc) - timedelta(days=10)
        pg.availability_confirmed_at = old_confirmation
        self.db.commit()

        viewed = get_pg_availability(pg.id, self.owner, self.db)
        self.assertEqual(
            viewed.availability_confirmed_at.replace(tzinfo=timezone.utc),
            old_confirmation,
        )
        self.assertTrue(viewed.availability_needs_update)
        self.assertEqual(
            self.db.query(PGAvailabilityEvent).filter_by(pg_id=pg.id).count(),
            0,
        )

        confirmed = confirm_pg_availability(
            pg.id,
            PGAvailabilityConfirmation(confirm_rent=True),
            self.owner,
            self.db,
        )
        self.assertIsNotNone(confirmed.availability_confirmed_at)
        self.assertGreater(
            confirmed.availability_confirmed_at.replace(tzinfo=timezone.utc),
            old_confirmation,
        )
        self.assertEqual(
            confirmed.availability_confirmed_at,
            confirmed.rent_confirmed_at,
        )
        self.assertFalse(confirmed.availability_needs_update)
        event = get_pg_availability_history(pg.id, 50, 0, self.owner, self.db)[0]
        self.assertEqual(event.event_type, "confirmed")
        self.assertEqual(event.actor_owner_id, self.owner.id)

    def test_read_does_not_refresh_confirmation_and_stale_threshold_is_seven_days(self):
        pg = self.make_pg("Stale confirmation")
        self.add_room(pg)
        pg.availability_confirmed_at = datetime.now(timezone.utc) - timedelta(
            days=8
        )
        self.db.commit()

        with patch.object(settings, "availability_stale_hours", 168):
            availability = get_pg_availability(pg.id, self.owner, self.db)
        self.assertTrue(availability.availability_needs_update)
        self.assertLess(
            availability.availability_confirmed_at.replace(tzinfo=timezone.utc),
            datetime.now(timezone.utc) - timedelta(days=7),
        )

    def test_owner_cannot_update_other_listing_and_user_cannot_manage_availability(self):
        other_owner = self.make_owner("availability-other@example.com")
        pg = self.make_pg("Private availability", owner=other_owner)
        room = self.add_room(pg)

        with self.assertRaises(HTTPException) as denied_owner:
            update_pg_availability(
                pg.id,
                PGAvailabilityUpdate(
                    rooms=[{"room_id": room.id, "available_beds": 1}],
                    availability_status="available",
                ),
                self.owner,
                self.db,
            )
        self.assertEqual(
            denied_owner.exception.status_code,
            status.HTTP_404_NOT_FOUND,
        )
        regular_user = self.make_owner(
            "availability-user@example.com",
            role="user",
        )
        with self.assertRaises(HTTPException) as denied_user:
            get_pg_availability(pg.id, regular_user, self.db)
        self.assertEqual(
            denied_user.exception.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_admin_can_manage_another_owners_availability(self):
        other_owner = self.make_owner("admin-managed-owner@example.com")
        pg = self.make_pg("Admin managed", owner=other_owner)
        room = self.add_room(pg)
        administrator = self.make_owner(
            "availability-admin@example.com",
            role="admin",
        )

        updated = update_pg_availability(
            pg.id,
            PGAvailabilityUpdate(
                rooms=[{"room_id": room.id, "available_beds": 1}],
                availability_status="available",
            ),
            administrator,
            self.db,
        )

        self.assertEqual(updated.available_beds, 1)
        event = self.db.query(PGAvailabilityEvent).filter_by(pg_id=pg.id).one()
        self.assertEqual(event.actor_owner_id, administrator.id)

    def test_public_availability_filter_and_visibility_rules(self):
        self.approve_owner_for_public_listings()
        available = self.make_pg(
            "Verified with beds",
            status="verified",
            active=True,
        )
        available_room = self.add_room(available, total_beds=3, occupied_beds=1)
        full = self.make_pg("Verified full", status="verified", active=True)
        self.add_room(full, total_beds=2, occupied_beds=2)
        pending = self.make_pg("Pending with beds", status="pending", active=True)
        self.add_room(pending, total_beds=2, occupied_beds=0)
        paused = self.make_pg(
            "Temporarily paused",
            status="verified",
            active=True,
        )
        self.add_room(paused, total_beds=2, occupied_beds=0)
        paused.is_temporarily_unavailable = True
        self.db.commit()

        results = get_pgs(
            city_id=None,
            area_id=None,
            stay_type=None,
            min_rent=None,
            max_rent=None,
            food_available=None,
            electricity_included=None,
            verified_only=False,
            available_only=True,
            min_available_beds=2,
            max_monthly_rent_per_person=None,
            sharing_type=None,
            amenity_ids=None,
            availability_updated_within_hours=None,
            nearby_place_id=None,
            max_distance_km=None,
            limit=20,
            offset=0,
            response=Response(),
            db=self.db,
        )
        self.assertEqual([result.id for result in results], [available.id])
        self.assertEqual(results[0].total_available_beds, 2)
        self.assertEqual(results[0].availability_status, "available")
        self.assertIsNone(results[0].availability_confirmed_at)
        self.assertNotIn(pending.id, [result.id for result in results])
        self.assertNotIn(full.id, [result.id for result in results])
        self.assertNotIn(paused.id, [result.id for result in results])

    def test_dashboard_and_owner_list_include_confirmed_freshness_and_status(self):
        pg = self.make_pg("Dashboard availability")
        self.add_room(pg)
        pg.availability_confirmed_at = datetime.now(timezone.utc)
        self.db.commit()

        listing = get_managed_pg(pg.id, self.owner, self.db)
        dashboard = get_owner_dashboard(self.owner, self.db)
        self.assertEqual(listing.availability_status, "available")
        self.assertFalse(listing.availability_is_stale)
        self.assertIsNotNone(listing.availability_confirmed_at)
        self.assertEqual(dashboard.listings_with_available_beds, 1)
        self.assertEqual(dashboard.needs_availability_update, 0)

    def test_listing_read_does_not_change_confirmation_timestamp(self):
        pg = self.make_pg("Read-only listing")
        self.add_room(pg)
        confirmed_at = datetime.now(timezone.utc) - timedelta(days=2)
        pg.availability_confirmed_at = confirmed_at
        self.db.commit()

        listing = get_managed_pg(pg.id, self.owner, self.db)

        self.assertEqual(
            listing.availability_confirmed_at.replace(tzinfo=timezone.utc),
            confirmed_at,
        )
        self.assertEqual(
            self.db.get(PG, pg.id).availability_confirmed_at.replace(
                tzinfo=timezone.utc
            ),
            confirmed_at,
        )


if __name__ == "__main__":
    unittest.main()
