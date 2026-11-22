import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { CityProvider } from "../src/state/CityContext";
import { colors } from "../src/theme";

export default function RootLayout() {
  return (
    <CityProvider>
      <StatusBar style="dark" />
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: colors.background },
          animation: "slide_from_right",
        }}
      />
    </CityProvider>
  );
}
