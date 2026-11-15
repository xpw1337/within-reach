import * as Haptics from 'expo-haptics';
import type { ReactNode } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
  type TextInputProps,
  type ViewStyle,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { colors, font, radius, space, type } from './theme';

// The look of the sos/phone-app redesign (white, Red Cross red, Nunito, chunky buttons with a solid
// bottom edge), applied to this app's own components: same names, props and behavior as before.

export function Screen({ children, background = colors.bg }: { children: ReactNode; background?: string }) {
  return (
    <SafeAreaView style={[styles.flex, { backgroundColor: background }]} edges={['top', 'bottom']}>
      <ScrollView contentContainerStyle={styles.screen} keyboardShouldPersistTaps="handled">
        {children}
      </ScrollView>
    </SafeAreaView>
  );
}

export function Title({ children, color = colors.text }: { children: ReactNode; color?: string }) {
  return <Text style={[styles.title, { color }]}>{children}</Text>;
}

export function Body({ children, color = colors.text, muted }: { children: ReactNode; color?: string; muted?: boolean }) {
  return <Text style={[styles.body, { color: muted ? colors.muted : color }]}>{children}</Text>;
}

export function Card({ children, style }: { children: ReactNode; style?: ViewStyle }) {
  return <View style={[styles.card, style]}>{children}</View>;
}

export function Label({ children }: { children: ReactNode }) {
  return <Text style={styles.label}>{children}</Text>;
}

type ButtonKind = 'primary' | 'secondary' | 'danger' | 'ok';

// bg, darker bottom edge, text color, and an outline for the light button.
const BUTTON: Record<ButtonKind, { bg: string; edge: string; fg: string; border?: string }> = {
  primary: { bg: colors.red, edge: colors.redDark, fg: colors.white },
  ok: { bg: colors.green, edge: colors.greenDark, fg: colors.white },
  danger: { bg: colors.ink, edge: '#000000', fg: colors.white },
  secondary: { bg: colors.white, edge: colors.line, fg: colors.ink, border: colors.line },
};
const EDGE = 4;

/** Chunky button with a solid bottom edge that presses down. */
export function Button({
  title,
  onPress,
  kind = 'primary',
  disabled,
  busy,
  big,
}: {
  title: string;
  onPress: () => void;
  kind?: ButtonKind;
  disabled?: boolean;
  busy?: boolean;
  big?: boolean;
}) {
  const c = BUTTON[kind];
  const isDisabled = disabled || busy;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: !!isDisabled, busy: !!busy }}
      onPressIn={() => void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {})}
      onPress={onPress}
      disabled={isDisabled}
      style={({ pressed }) => [
        styles.button,
        big && styles.buttonBig,
        {
          backgroundColor: c.bg,
          borderColor: c.border ?? c.bg,
          borderBottomColor: c.edge,
          borderBottomWidth: pressed ? 2 : EDGE + (c.border ? 2 : 0),
          marginTop: pressed ? EDGE - 2 : 0,
          opacity: isDisabled ? 0.45 : 1,
        },
      ]}
    >
      {busy ? (
        <ActivityIndicator color={c.fg} />
      ) : (
        <Text style={[styles.buttonText, big && styles.buttonTextBig, { color: c.fg }]}>{title}</Text>
      )}
    </Pressable>
  );
}

export function Field({ label, ...props }: { label: string } & TextInputProps) {
  return (
    <View style={styles.field}>
      <Label>{label}</Label>
      <TextInput placeholderTextColor={colors.faint} style={styles.input} {...props} />
    </View>
  );
}

export function ToggleRow({
  label,
  help,
  value,
  onValueChange,
  disabled,
}: {
  label: string;
  help?: string;
  value: boolean;
  onValueChange: (value: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <View style={styles.toggleRow}>
      <View style={styles.flex}>
        <Text style={styles.toggleLabel}>{label}</Text>
        {help ? <Text style={styles.help}>{help}</Text> : null}
      </View>
      <Switch
        accessibilityLabel={label}
        value={value}
        onValueChange={onValueChange}
        disabled={disabled}
        trackColor={{ true: colors.green, false: colors.line }}
      />
    </View>
  );
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <View style={styles.segmented}>
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <Pressable
            key={option.value}
            accessibilityRole="radio"
            accessibilityState={{ selected }}
            onPress={() => onChange(option.value)}
            style={[styles.segment, selected && styles.segmentSelected]}
          >
            <Text style={[styles.segmentText, selected && styles.segmentTextSelected]}>{option.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export function Notice({ children, tone = 'warn' }: { children: ReactNode; tone?: 'warn' | 'info' | 'error' }) {
  const t =
    tone === 'info'
      ? { bg: colors.blueSoft, accent: colors.blue }
      : tone === 'error'
        ? { bg: colors.redSoft, accent: colors.red }
        : { bg: colors.orangeSoft, accent: colors.orangeDark };
  return (
    <View style={[styles.notice, { backgroundColor: t.bg }]}>
      <View style={[styles.noticeDot, { backgroundColor: t.accent }]} />
      <Text style={styles.noticeText}>{children}</Text>
    </View>
  );
}

export const styles = StyleSheet.create({
  flex: { flex: 1 },
  screen: { padding: space.xl, gap: space.lg, paddingBottom: space.xl * 2 },
  title: { ...type.title },
  body: { ...type.body },
  help: { ...type.small, marginTop: 2 },
  label: { ...type.label },
  card: {
    backgroundColor: colors.white,
    borderRadius: radius.lg,
    borderWidth: 2,
    borderColor: colors.line,
    padding: space.lg,
    gap: space.md,
  },
  button: {
    minHeight: 58,
    borderRadius: radius.md,
    borderWidth: 2,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: space.xl,
  },
  buttonBig: { minHeight: 76 },
  buttonText: { fontFamily: font.heavy, fontSize: 17, letterSpacing: 0.8, textTransform: 'uppercase', textAlign: 'center' },
  buttonTextBig: { fontSize: 21 },
  field: { gap: space.sm },
  input: {
    fontFamily: font.bold,
    fontSize: 19,
    color: colors.ink,
    backgroundColor: colors.surface,
    borderWidth: 2,
    borderColor: colors.line,
    borderRadius: radius.md,
    paddingHorizontal: space.lg,
    paddingVertical: 14,
  },
  toggleRow: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  toggleLabel: { ...type.body, fontFamily: font.bold },
  segmented: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  segment: {
    paddingVertical: space.sm,
    paddingHorizontal: space.lg,
    borderRadius: radius.pill,
    borderWidth: 2,
    borderColor: colors.line,
    backgroundColor: colors.white,
  },
  segmentSelected: { backgroundColor: colors.red, borderColor: colors.red },
  segmentText: { fontFamily: font.bold, fontSize: 15, color: colors.ink },
  segmentTextSelected: { color: colors.white, fontFamily: font.heavy },
  notice: { flexDirection: 'row', gap: space.sm, alignItems: 'flex-start', padding: space.md, borderRadius: radius.md },
  noticeDot: { width: 8, height: 8, borderRadius: 4, marginTop: 7 },
  noticeText: { ...type.small, color: colors.ink, flex: 1 },
});
