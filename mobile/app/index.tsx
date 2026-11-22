import { router } from "expo-router";
import { Text, View } from "react-native";
import { Button } from "../src/components/Button";
import { Screen } from "../src/components/Screen";
import { colors, radius, spacing } from "../src/theme";

export default function WelcomeScreen() {
  return (
    <Screen>
      <View style={{ flex: 1, justifyContent: "space-between", paddingVertical: spacing.xl }}>
        <View>
          <View
            style={{
              alignSelf: "flex-start",
              borderRadius: radius.pill,
              backgroundColor: colors.accentSoft,
              paddingHorizontal: spacing.md,
              paddingVertical: spacing.xs,
            }}
          >
            <Text style={{ color: colors.ink, fontWeight: "700", fontSize: 13 }}>
              YOUR NEXT CITY, FEELS LIKE HOME
            </Text>
          </View>
          <View style={{ marginTop: 54 }}>
            <Text style={{ color: colors.ink, fontSize: 48, fontWeight: "800", letterSpacing: -2 }}>
              ChezPG
            </Text>
            <Text
              style={{
                color: colors.ink,
                fontSize: 30,
                fontWeight: "700",
                lineHeight: 38,
                marginTop: spacing.md,
                maxWidth: 330,
              }}
            >
              Moving Cities?{"\n"}Come Chez Us.
            </Text>
            <Text
              style={{
                color: colors.muted,
                fontSize: 17,
                lineHeight: 26,
                marginTop: spacing.md,
                maxWidth: 330,
              }}
            >
              Find a place to settle in, meet your new neighborhood, and make Hyderabad feel like
              home.
            </Text>
          </View>
        </View>

        <View
          style={{
            backgroundColor: colors.surface,
            borderRadius: radius.xl,
            padding: spacing.lg,
            borderWidth: 1,
            borderColor: colors.border,
          }}
        >
          <Text style={{ color: colors.ink, fontSize: 18, fontWeight: "700" }}>
            A better start in a new city
          </Text>
          <Text style={{ color: colors.muted, fontSize: 14, lineHeight: 21, marginTop: spacing.xs }}>
            Explore PGs by area, budget, and the details that matter to you.
          </Text>
          <View style={{ marginTop: spacing.lg, gap: spacing.sm }}>
            <Button label="Find a PG" onPress={() => router.push("/city-select")} />
            <Button
              label="I’m a PG owner"
              variant="secondary"
              onPress={() => router.push("/owner")}
            />
          </View>
        </View>
      </View>
    </Screen>
  );
}
