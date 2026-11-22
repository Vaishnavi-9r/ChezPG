import { Pressable, Text, View, ViewStyle } from "react-native";
import { colors, radius, spacing } from "../theme";

export function ErrorMessage({
  message,
  onRetry,
  style,
}: {
  message: string;
  onRetry?: () => void;
  style?: ViewStyle;
}) {
  return (
    <View
      accessibilityRole="alert"
      style={[
        {
          backgroundColor: colors.dangerSoft,
          borderRadius: radius.md,
          padding: spacing.md,
        },
        style,
      ]}
    >
      <Text style={{ color: colors.danger, lineHeight: 21 }}>{message}</Text>
      {onRetry ? (
        <Pressable onPress={onRetry} accessibilityRole="button" style={{ alignSelf: "flex-start" }}>
          <Text style={{ color: colors.danger, fontWeight: "700", marginTop: spacing.xs }}>Try again</Text>
        </Pressable>
      ) : null}
    </View>
  );
}
