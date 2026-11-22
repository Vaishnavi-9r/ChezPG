import { ReactNode } from "react";
import { ActivityIndicator, Pressable, StyleProp, Text, ViewStyle } from "react-native";
import { colors, radius, spacing } from "../theme";

type ButtonProps = {
  label: string;
  onPress: () => void;
  variant?: "primary" | "secondary";
  disabled?: boolean;
  loading?: boolean;
  style?: StyleProp<ViewStyle>;
  icon?: ReactNode;
};

export function Button({
  label,
  onPress,
  variant = "primary",
  disabled = false,
  loading = false,
  style,
  icon,
}: ButtonProps) {
  const primary = variant === "primary";
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: disabled || loading }}
      onPress={onPress}
      disabled={disabled || loading}
      style={[
        {
          minHeight: 54,
          borderRadius: radius.lg,
          paddingHorizontal: spacing.lg,
          backgroundColor: primary ? colors.primary : colors.surface,
          borderColor: primary ? colors.primary : colors.border,
          borderWidth: 1,
          opacity: disabled || loading ? 0.6 : 1,
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "center",
          gap: spacing.xs,
        },
        style,
      ]}
    >
      {loading ? <ActivityIndicator color={primary ? colors.white : colors.primary} /> : icon}
      <Text style={{ color: primary ? colors.white : colors.ink, fontSize: 16, fontWeight: "700" }}>
        {label}
      </Text>
    </Pressable>
  );
}
