import unittest
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.api.v1.pgs import get_pgs, is_loopback_request
from app.core.config import Settings, settings
from app.db.base import Base
from app.db.seed_dev_pgs import (
    SAMPLE_PGS,
    seed_development_pgs,
    validate_development_database,
)
from app.models import Amenity, Area, City, PG, Room


class DevelopmentPGSeedTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.city = City(
            name="Hyderabad",
            state="Telangana",
            country="India",
            is_active=True,
        )
        self.db.add(self.city)
        self.db.flush()
        for area_name in {sample.area for sample in SAMPLE_PGS}:
            self.db.add(
                Area(
                    city_id=self.city.id,
                    name=area_name,
                    is_active=True,
                )
            )
        amenity_names = {
            name for sample in SAMPLE_PGS for name in sample.amenities
        }
        self.db.add_all(
            Amenity(name=name, is_active=True) for name in amenity_names
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_seed_is_idempotent_and_samples_are_not_publicly_visible(self):
        self.assertEqual(seed_development_pgs(self.db), (8, 0))
        self.db.commit()

        self.assertEqual(seed_development_pgs(self.db), (0, 8))
        self.db.commit()
        self.assertEqual(self.db.scalar(select(func.count(PG.id))), 8)
        self.assertEqual(self.db.scalar(select(func.count(Room.id))), 8)

        samples = self.db.scalars(
            select(PG).where(PG.description.contains("[chezpg-dev-sample:v1:"))
        ).all()
        self.assertEqual(len(samples), 8)
        self.assertTrue(
            all(
                pg.owner_id is None
                and pg.is_active is False
                and pg.verification_status == "pending"
                and pg.latitude is None
                and pg.longitude is None
                for pg in samples
            )
        )
        self.assertTrue(all(pg.rooms[0].available_beds > 0 for pg in samples))
        self.assertTrue(all(pg.amenities for pg in samples))
        self.assertEqual(
            get_pgs(
                city_id=self.city.id,
                max_rent=Decimal("10000"),
                stay_type="men",
                db=self.db,
            ),
            [],
        )

    def test_development_search_opt_in_exposes_only_marked_samples_and_filters(self):
        seed_development_pgs(self.db)
        self.db.commit()

        with patch.object(settings, "development_sample_search_enabled", False):
            self.assertEqual(
                self.search_pgs(city_id=self.city.id),
                [],
            )

        with patch.object(settings, "development_sample_search_enabled", True):
            all_samples = self.search_pgs(city_id=self.city.id)
            remote_samples = self.search_pgs(
                request_host="192.0.2.1",
                city_id=self.city.id,
            )
            men = self.search_pgs(city_id=self.city.id, stay_type="men")
            women = self.search_pgs(city_id=self.city.id, stay_type="women")
            budget = self.search_pgs(
                city_id=self.city.id,
                max_rent=Decimal("10000"),
            )
            madhapur = self.search_pgs(
                city_id=self.city.id,
                area_id=self.area_id("Madhapur"),
            )

        self.assertEqual(len(all_samples), 8)
        self.assertEqual(remote_samples, [])
        self.assertEqual({pg.stay_type for pg in men}, {"men"})
        self.assertEqual(len(men), 3)
        self.assertEqual({pg.stay_type for pg in women}, {"women"})
        self.assertEqual(len(women), 3)
        self.assertTrue(all(pg.monthly_rent <= Decimal("10000") for pg in budget))
        self.assertEqual(len(budget), 3)
        self.assertEqual(len(madhapur), 2)
        self.assertTrue(
            all(pg.verification_status == "pending" for pg in all_samples)
        )

    def test_seed_does_not_overwrite_unmarked_listing_name_collision(self):
        sample = SAMPLE_PGS[0]
        area = self.db.scalar(
            select(Area).where(
                Area.city_id == self.city.id,
                Area.name == sample.area,
            )
        )
        self.db.add(
            PG(
                city_id=self.city.id,
                area_id=area.id,
                name=sample.name,
                address="Existing user-created record",
                stay_type="men",
                monthly_rent=Decimal("8500"),
                verification_status="pending",
                is_active=False,
            )
        )
        self.db.commit()

        with self.assertRaisesRegex(RuntimeError, "already exists without the seed marker"):
            seed_development_pgs(self.db)
        self.db.rollback()
        self.assertEqual(self.db.scalar(select(func.count(PG.id))), 1)

    def test_development_database_guard_requires_explicit_local_target(self):
        valid_url = "postgresql+psycopg://127.0.0.1:5433/chezpg"
        validate_development_database(valid_url, "development")

        for url, environment in (
            (valid_url, ""),
            (valid_url, "production"),
            (
                "postgresql+psycopg://example.com:5433/chezpg",
                "development",
            ),
            (
                "postgresql+psycopg://127.0.0.1:5432/chezpg",
                "development",
            ),
            (
                "postgresql+psycopg://127.0.0.1:5433/other",
                "development",
            ),
        ):
            with self.subTest(environment=environment, url=url):
                with self.assertRaises(RuntimeError):
                    validate_development_database(url, environment)

    def test_sample_search_setting_requires_development_and_local_database(self):
        local_database = "postgresql+psycopg://127.0.0.1:5433/chezpg"
        Settings(
            database_url=local_database,
            app_env="development",
            development_sample_search_enabled=True,
        )

        invalid_settings = (
            {
                "database_url": local_database,
                "app_env": "production",
                "development_sample_search_enabled": True,
            },
            {
                "database_url": "postgresql+psycopg://db.example:5433/chezpg",
                "app_env": "development",
                "development_sample_search_enabled": True,
            },
            {
                "database_url": "postgresql+psycopg://127.0.0.1:5432/chezpg",
                "app_env": "development",
                "development_sample_search_enabled": True,
            },
        )
        for values in invalid_settings:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    Settings(**values)

    def search_pgs(self, request_host="127.0.0.1", **filters):
        parameters = {
            "request_is_local": is_loopback_request(
                Request(
                    {"type": "http", "client": (request_host, 12345)}
                )
            ),
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
            "limit": 100,
            "offset": 0,
            "db": self.db,
        }
        parameters.update(filters)
        return get_pgs(**parameters)

    def area_id(self, name):
        area = self.db.scalar(
            select(Area).where(
                Area.city_id == self.city.id,
                Area.name == name,
            )
        )
        return area.id


if __name__ == "__main__":
    unittest.main()
