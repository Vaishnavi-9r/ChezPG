import { useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, View } from "react-native";
import { router } from "expo-router";
import { Button } from "../src/components/Button";
import { ErrorMessage } from "../src/components/ErrorMessage";
import { Screen } from "../src/components/Screen";
import { TextField } from "../src/components/TextField";
import { api, ApiError, NearbyPlace, PGListing } from "../src/lib/api";
import { filterListings, makeSearchParams, PRICE_RANGES } from "../src/lib/search";
import { useCity } from "../src/state/CityContext";
import { colors, radius, spacing } from "../src/theme";

type StayType = "men" | "women" | "co_living";

export default function HomeScreen() {
  const { city, isTemporary } = useCity();
  const [query, setQuery] = useState("");
  const [budgetIndex, setBudgetIndex] = useState<number | null>(null);
  const [stayType, setStayType] = useState<StayType | null>(null);
  const [foodOnly, setFoodOnly] = useState(false);
  const [amenitiesInfo, setAmenitiesInfo] = useState(false);
  const [listings, setListings] = useState<PGListing[]>([]);
  const [nearbyMatches, setNearbyMatches] = useState<NearbyPlace[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);

  const selectedBudget = budgetIndex === null ? null : PRICE_RANGES[budgetIndex];
  const visibleListings = useMemo(
    () => filterListings(listings, query),
    [listings, query],
  );

  async function search() {
    if (!city || isTemporary || city.id <= 0) {
      setError("Connect to the backend and select a city from its city list before searching PGs.");
      setSearched(true);
      return;
    }
    setLoading(true);
    setError(null);
    setSearched(true);
    try {
      const params = makeSearchParams({
        cityId: city.id,
        minRent: selectedBudget?.min,
        maxRent: selectedBudget?.max,
        stayType,
        foodAvailable: foodOnly ? true : undefined,
      });
      const [pgResults, placeResults] = await Promise.all([
        api.searchPGs(params),
        query.trim()
          ? api.searchNearbyPlaces(city.id, query.trim())
          : Promise.resolve([] as NearbyPlace[]),
      ]);
      setListings(pgResults);
      setNearbyMatches(placeResults);
    } catch (reason) {
      setListings([]);
      setNearbyMatches([]);
      setError(
        reason instanceof ApiError
          ? reason.message
          : "Could not load PGs. Check your connection and try again.",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (city && !isTemporary) void search();
  }, [city?.id, isTemporary]);

  return (
    <Screen>
      <ScrollView
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={{ paddingBottom: spacing.xl }}
      >
        <Pressable onPress={() => router.push("/city-select")} accessibilityRole="button" style={{ alignSelf: "flex-start", paddingTop: spacing.xs }}>
          <Text style={{ color: colors.muted, fontSize: 12, fontWeight: "700", letterSpacing: 1 }}>YOUR CITY</Text>
          <View style={{ flexDirection: "row", alignItems: "center", marginTop: 3 }}>
            <Text style={{ color: colors.ink, fontSize: 22, fontWeight: "800" }}>
              {city?.name ?? "Choose a city"}
            </Text>
            <Text style={{ color: colors.primary, fontSize: 18, marginLeft: 8 }}>⌄</Text>
          </View>
          {isTemporary ? (
            <Text style={{ color: colors.warning, fontSize: 12, marginTop: 4 }}>
              Temporary city choice · connect to load verified city data
            </Text>
          ) : null}
        </Pressable>

        <View style={{ marginTop: spacing.lg, backgroundColor: colors.surface, borderColor: colors.border, borderWidth: 1, borderRadius: radius.xl, padding: spacing.lg }}>
          <View style={{ alignSelf: "flex-start", borderRadius: radius.pill, backgroundColor: colors.accentSoft, paddingHorizontal: spacing.sm, paddingVertical: 6, marginBottom: spacing.md }}>
            <Text style={{ color: colors.primaryDark, fontSize: 11, fontWeight: "800", letterSpacing: 0.7 }}>YOUR NEXT CHAPTER STARTS HERE</Text>
          </View>
          <Text style={{ color: colors.ink, fontSize: 29, fontWeight: "800", lineHeight: 36 }}>
            Find your place{"\n"}in {city?.name ?? "your city"}.
          </Text>
          <Text style={{ color: colors.muted, fontSize: 15, marginTop: spacing.xs }}>
            A good stay makes a new city feel closer.
          </Text>
        </View>

        <View style={{ marginTop: spacing.md }}>
          <TextField
            value={query}
            onChangeText={setQuery}
            placeholder="Area, PG name, or nearby place"
            returnKeyType="search"
            onSubmitEditing={() => void search()}
            accessibilityLabel="Search area, PG name, or nearby place"
          />
        </View>

        <Text style={{ color: colors.ink, fontWeight: "700", fontSize: 16, marginTop: spacing.lg }}>
          Quick filters
        </Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: spacing.sm }}>
          {PRICE_RANGES.map((range, index) => (
            <FilterChip
              key={range.label}
              label={range.label}
              selected={budgetIndex === index}
              onPress={() => setBudgetIndex(budgetIndex === index ? null : index)}
            />
          ))}
        </ScrollView>
        <View style={{ flexDirection: "row", flexWrap: "wrap", marginTop: spacing.xs }}>
          {([
            ["men", "Men"],
            ["women", "Women"],
            ["co_living", "Co-living"],
          ] as const).map(([value, label]) => (
            <FilterChip
              key={value}
              label={label}
              selected={stayType === value}
              onPress={() => setStayType(stayType === value ? null : value)}
            />
          ))}
          <FilterChip
            label="Food included"
            selected={foodOnly}
            onPress={() => setFoodOnly(!foodOnly)}
          />
          <FilterChip
            label="Amenities"
            selected={amenitiesInfo}
            onPress={() => setAmenitiesInfo(!amenitiesInfo)}
          />
        </View>

        {amenitiesInfo ? (
          <View
            style={{
              backgroundColor: colors.accentSoft,
              borderRadius: radius.md,
              padding: spacing.md,
              marginTop: spacing.xs,
            }}
          >
            <Text style={{ color: colors.ink, lineHeight: 20 }}>
              Amenity filtering will be available when the backend exposes a public amenity list.
            </Text>
          </View>
        ) : null}

        <Button label="Browse PGs" onPress={() => void search()} style={{ marginTop: spacing.md }} />

        {loading ? (
          <View style={{ alignItems: "center", paddingVertical: spacing.xl }}>
            <ActivityIndicator color={colors.primary} />
            <Text style={{ color: colors.muted, marginTop: spacing.sm }}>Loading PGs…</Text>
          </View>
        ) : null}
        {error ? (
          <ErrorMessage message={error} onRetry={() => void search()} style={{ marginTop: spacing.md }} />
        ) : null}
        {searched && !loading && !error && visibleListings.length === 0 ? (
          <View style={{ paddingVertical: spacing.xl, alignItems: "center" }}>
            <Text style={{ color: colors.ink, fontSize: 17, fontWeight: "700" }}>
              No PGs found
            </Text>
            <Text style={{ color: colors.muted, marginTop: spacing.xs, textAlign: "center" }}>
              Try a different search or adjust your filters.
            </Text>
          </View>
        ) : null}

        {searched && !loading && !error && visibleListings.length > 0 ? (
          <Text style={{ color: colors.muted, fontSize: 13, fontWeight: "600", marginTop: spacing.lg }}>
            {visibleListings.length} {visibleListings.length === 1 ? "stay" : "stays"} to explore
          </Text>
        ) : null}

        {visibleListings.map((listing) => (
          <View
            key={listing.id}
            style={{
              backgroundColor: colors.surface,
              borderColor: colors.border,
              borderWidth: 1,
              borderRadius: radius.lg,
              padding: spacing.lg,
              marginTop: spacing.md,
            }}
          >
            <Text style={{ color: colors.ink, fontSize: 19, fontWeight: "800" }}>
              {listing.name}
            </Text>
            <Text style={{ color: colors.muted, marginTop: 4 }}>
              {listing.area_name ?? "Hyderabad"} · ₹{Number(listing.monthly_rent).toLocaleString("en-IN")}
              /month
            </Text>
            <Text style={{ color: colors.muted, marginTop: spacing.xs, lineHeight: 20 }}>
              {listing.address}
            </Text>
          </View>
        ))}
        {nearbyMatches.length > 0 ? (
          <View style={{ marginTop: spacing.lg }}>
            <Text style={{ color: colors.ink, fontWeight: "700" }}>Nearby places</Text>
            {nearbyMatches.map((place) => (
              <Text key={place.id} style={{ color: colors.muted, marginTop: spacing.xs }}>
                {place.name} · {place.category.replaceAll("_", " ")}
              </Text>
            ))}
          </View>
        ) : null}
      </ScrollView>
    </Screen>
  );
}

function FilterChip({
  label,
  selected,
  onPress,
}: {
  label: string;
  selected: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected }}
      onPress={onPress}
      style={{
        paddingHorizontal: spacing.md,
        paddingVertical: spacing.sm,
        marginRight: spacing.xs,
        marginBottom: spacing.xs,
        borderRadius: radius.pill,
        backgroundColor: selected ? colors.primary : colors.surface,
        borderColor: selected ? colors.primary : colors.border,
        borderWidth: 1,
      }}
    >
      <Text style={{ color: selected ? colors.white : colors.ink, fontWeight: "600", fontSize: 13 }}>
        {label}
      </Text>
    </Pressable>
  );
}
