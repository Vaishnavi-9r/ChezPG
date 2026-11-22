import assert from "node:assert/strict";
import test from "node:test";
import type { PGListing } from "../src/lib/api.ts";
import { filterListings, makeSearchParams } from "../src/lib/search.ts";

const listings: PGListing[] = [
  {
    id: 1,
    city_id: 1,
    area_id: 1,
    name: "Green Nest",
    description: null,
    address: "Road 1",
    stay_type: "women",
    monthly_rent: "12000",
    security_deposit: null,
    electricity_included: false,
    food_available: true,
    contact_phone: null,
    verification_status: "approved",
    area_name: "Madhapur",
    total_available_beds: 2,
    average_rating: null,
    published_review_count: 0,
  },
  {
    id: 2,
    city_id: 1,
    area_id: 2,
    name: "City House",
    description: null,
    address: "Road 2",
    stay_type: "men",
    monthly_rent: 9000,
    security_deposit: null,
    electricity_included: true,
    food_available: false,
    contact_phone: null,
    verification_status: "approved",
    area_name: "Gachibowli",
    total_available_beds: 1,
    average_rating: null,
    published_review_count: 0,
  },
];

test("builds only supported public PG search filters", () => {
  const params = makeSearchParams({
    cityId: 7,
    minRent: 10000,
    maxRent: 20000,
    stayType: "women",
    foodAvailable: true,
  });
  assert.equal(
    params.toString(),
    "city_id=7&limit=100&min_rent=10000&max_rent=20000&stay_type=women&food_available=true",
  );
});

test("filters loaded PG listings by PG name, area, or address without faking results", () => {
  assert.deepEqual(filterListings(listings, "madhapur").map((listing) => listing.id), [1]);
  assert.deepEqual(filterListings(listings, "city house").map((listing) => listing.id), [2]);
  assert.deepEqual(filterListings(listings, "not listed"), []);
  assert.equal(filterListings(listings, "  ").length, 2);
});
