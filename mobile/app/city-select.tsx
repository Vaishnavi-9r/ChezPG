import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";
import { router } from "expo-router";
import { ErrorMessage } from "../src/components/ErrorMessage";
import { Screen } from "../src/components/Screen";
import { api, ApiError, City } from "../src/lib/api";
import { useCity } from "../src/state/CityContext";
import { colors, radius, spacing } from "../src/theme";

const HYDERABAD_FALLBACK: City = {
  id: 0,
  name: "Hyderabad",
  state: "Telangana",
  country: "India",
};

export default function CitySelectScreen() {
  const { city, setCity } = useCity();
  const [cities, setCities] = useState<City[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadCities() {
    setLoading(true);
    setError(null);
    try {
      const results = await api.getCities();
      setCities(results);
      if (!results.length) {
        setError("The city API returned no active cities. Hyderabad is available as a temporary choice.");
      }
    } catch (reason) {
      setCities([]);
      setError(
        reason instanceof ApiError
          ? reason.message
          : "Could not reach the city service. Check the backend URL and try again.",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadCities();
  }, []);

  const fallbackAvailable = cities.length === 0;
  const options = fallbackAvailable ? [HYDERABAD_FALLBACK] : cities;

  function chooseCity(selected: City) {
    setCity(selected, selected.id === 0);
    router.replace("/home");
  }

  return (
    <Screen>
      <View style={{ flex: 1, paddingTop: spacing.md }}>
        <Pressable onPress={() => router.back()} accessibilityRole="button">
          <Text style={{ color: colors.muted, fontSize: 16 }}>‹  Back</Text>
        </Pressable>
        <Text style={{ color: colors.ink, fontSize: 30, fontWeight: "800", marginTop: spacing.xl }}>
          Where to next?
        </Text>
        <Text style={{ color: colors.muted, fontSize: 16, lineHeight: 24, marginTop: spacing.sm }}>
          Choose a city to start exploring.
        </Text>

        {loading ? (
          <View style={{ alignItems: "center", marginTop: spacing.xl }}>
            <ActivityIndicator color={colors.primary} />
            <Text style={{ color: colors.muted, marginTop: spacing.sm }}>Finding cities…</Text>
          </View>
        ) : (
          <View style={{ marginTop: spacing.xl, gap: spacing.sm }}>
            {error ? <ErrorMessage message={error} onRetry={() => void loadCities()} /> : null}
            {options.map((option) => (
              <Pressable
                key={option.id || "hyderabad-temporary"}
                accessibilityRole="button"
                onPress={() => chooseCity(option)}
                style={{
                  padding: spacing.lg,
                  backgroundColor: colors.surface,
                  borderRadius: radius.lg,
                  borderWidth: 1,
                  borderColor: city?.id === option.id ? colors.primary : colors.border,
                }}
              >
                <Text style={{ color: colors.ink, fontSize: 19, fontWeight: "700" }}>
                  {option.name}
                </Text>
                <Text style={{ color: colors.muted, fontSize: 14, marginTop: 4 }}>
                  {option.state}, {option.country}
                  {option.id === 0 ? " · temporary fallback" : ""}
                </Text>
              </Pressable>
            ))}
          </View>
        )}

        <View style={{ marginTop: "auto", paddingVertical: spacing.xl }}>
          <View
            style={{
              backgroundColor: colors.accentSoft,
              borderRadius: radius.lg,
              padding: spacing.md,
            }}
          >
            <Text style={{ color: colors.ink, fontWeight: "700" }}>More cities are on the way</Text>
            <Text style={{ color: colors.muted, lineHeight: 21, marginTop: 4 }}>
              Hyderabad is our first launch city. We’ll bring ChezPG to more places soon.
            </Text>
          </View>
        </View>
      </View>
    </Screen>
  );
}
