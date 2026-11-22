import { PropsWithChildren } from "react";
import { SafeAreaView } from "react-native-safe-area-context";
import { colors, spacing } from "../theme";

export function Screen({ children }: PropsWithChildren) {
  return (
    <SafeAreaView
      edges={["top", "bottom"]}
      style={{ flex: 1, backgroundColor: colors.background, paddingHorizontal: spacing.lg }}
    >
      {children}
    </SafeAreaView>
  );
}
