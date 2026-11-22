import { router } from "expo-router";
import { Pressable, Text, View } from "react-native";
import { Button } from "../src/components/Button";
import { Screen } from "../src/components/Screen";
import { colors, radius, spacing } from "../src/theme";

export default function OwnerEntryScreen() {
  return (
    <Screen>
      <Pressable onPress={() => router.back()} accessibilityRole="button">
        <Text style={{ color: colors.muted, fontSize: 16 }}>‹  Back</Text>
      </Pressable>
      <View style={{ flex: 1, justifyContent: "center" }}>
        <View
          style={{
            backgroundColor: colors.accentSoft,
            padding: spacing.lg,
            borderRadius: radius.xl,
          }}
        >
          <Text style={{ color: colors.ink, fontSize: 28, fontWeight: "800" }}>
            Welcome, PG owners
          </Text>
          <Text style={{ color: colors.muted, fontSize: 16, lineHeight: 24, marginTop: spacing.sm }}>
            ChezPG owner tools are not part of this first mobile release. You can still explore the
            app, and owner tools will be added in a future update.
          </Text>
          <Button
            label="Explore Hyderabad"
            onPress={() => router.replace("/city-select")}
            style={{ marginTop: spacing.lg }}
          />
        </View>
      </View>
    </Screen>
  );
}
