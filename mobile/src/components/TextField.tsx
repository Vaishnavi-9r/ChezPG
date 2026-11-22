import { TextInput, TextInputProps } from "react-native";
import { colors, radius, spacing } from "../theme";

type TextFieldProps = TextInputProps & { accessibilityLabel: string };

export function TextField({ accessibilityLabel, style, ...props }: TextFieldProps) {
  return (
    <TextInput
      accessibilityLabel={accessibilityLabel}
      placeholderTextColor={colors.muted}
      style={[
        {
          minHeight: 54,
          borderRadius: radius.lg,
          borderWidth: 1,
          borderColor: colors.border,
          backgroundColor: colors.surface,
          color: colors.ink,
          paddingHorizontal: spacing.md,
          fontSize: 15,
        },
        style,
      ]}
      {...props}
    />
  );
}
