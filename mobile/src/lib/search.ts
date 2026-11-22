import type { PGListing } from "./api";

export const PRICE_RANGES = [
  { label: "Under ₹10k", min: undefined, max: 10000 },
  { label: "₹10k–₹20k", min: 10000, max: 20000 },
  { label: "₹20k+", min: 20000, max: undefined },
] as const;

export function makeSearchParams(filters: {
  cityId: number;
  minRent?: number;
  maxRent?: number;
  stayType?: "men" | "women" | "co_living" | null;
  foodAvailable?: boolean;
}): URLSearchParams {
  const params = new URLSearchParams({ city_id: String(filters.cityId), limit: "100" });
  if (filters.minRent !== undefined) params.set("min_rent", String(filters.minRent));
  if (filters.maxRent !== undefined) params.set("max_rent", String(filters.maxRent));
  if (filters.stayType) params.set("stay_type", filters.stayType);
  if (filters.foodAvailable !== undefined) {
    params.set("food_available", String(filters.foodAvailable));
  }
  return params;
}

export function filterListings(listings: PGListing[], query: string): PGListing[] {
  const normalized = query.trim().toLocaleLowerCase();
  if (!normalized) return listings;
  return listings.filter((listing) =>
    [listing.name, listing.address, listing.area_name ?? ""].some((value) =>
      value.toLocaleLowerCase().includes(normalized),
    ),
  );
}
