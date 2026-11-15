import Ionicons from '@expo/vector-icons/Ionicons';
import * as Haptics from 'expo-haptics';
import type { ComponentProps, ReactNode } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  type TextInputProps,
  type TextStyle,
  type ViewStyle,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { colors, font, radius, space, type } from './theme';

export type IconName = ComponentProps<typeof Ionicons>['name'];

export function Screen({ children, scroll = true, background = colors.bg, style }: {
  children: ReactNode;
  scroll?: boolean;
  background?: string;
  style?: ViewStyle;
}) {
  return (
    <SafeAreaView style={[styles.flex, { backgroundColor: background }]} edges={['top', 'bottom']}>
      {scroll ? (
        <ScrollView contentContainerStyle={[styles.screen, style]} keyboardShouldPersistTaps="handled">
          {children}
        </ScrollView>
      ) : (
        <View style={[styles.flex, styles.screen, style]}>{children}</View>
      )}
    </SafeAreaView>
  );
}

export function Text2({ children, style, kind = 'body' }: { children: ReactNode; style?: TextStyle | TextStyle[]; kind?: keyof typeof type }) {
  return <Text style={[type[kind], style]}>{children}</Text>;
}

export const Hero = ({ children, color }: { children: ReactNode; color?: string }) => <Text style={[type.hero, color ? { color } : null]}>{children}</Text>;
export const Title = ({ children, color }: { children: ReactNode; color?: string }) => <Text style={[type.title, color ? { color } : null]}>{children}</Text>;
export const Heading = ({ children, color }: { children: ReactNode; color?: string }) => <Text style={[type.heading, color ? { color } : null]}>{children}</Text>;
export const Body = ({ children, muted, color, center }: { children: ReactNode; muted?: boolean; color?: string; center?: boolean }) => (
  <Text style={[type.body, muted ? { color: colors.muted } : null, color ? { color } : null, center ? { textAlign: 'center' } : null]}>{children}</Text>
);
export const Small = ({ children, color }: { children: ReactNode; color?: string }) => <Text style={[type.small, color ? { color } : null]}>{children}</Text>;
export const Label = ({ children, color }: { children: ReactNode; color?: string }) => <Text style={[type.label, color ? { color } : null]}>{children}</Text>;

type ButtonKind = 'primary' | 'secondary' | 'ghost' | 'green' | 'orange' | 'white';

const BUTTON: Record<ButtonKind, { bg: string; edge: string; fg: string; border?: string }> = {
  primary: { bg: colors.red, edge: colors.redDark, fg: colors.white },
  green: { bg: colors.green, edge: colors.greenDark, fg: colors.white },
  orange: { bg: colors.orange, edge: colors.orangeDark, fg: colors.white },
  secondary: { bg: colors.white, edge: colors.line, fg: colors.ink, border: colors.line },
  white: { bg: colors.white, edge: 'rgba(0,0,0,0.18)', fg: colors.red },
  ghost: { bg: 'transparent', edge: 'transparent', fg: colors.muted },
};

/** Chunky button with a solid bottom edge that presses down. */
export function Button({ title, onPress, kind = 'primary', disabled, busy, icon, size = 'lg' }: {
  title: string;
  onPress: () => void;
  kind?: ButtonKind;
  disabled?: boolean;
  busy?: boolean;
  icon?: IconName;
  size?: 'lg' | 'md';
}) {
  const c = BUTTON[kind];
  const edge = kind === 'ghost' ? 0 : 4;
  return (
    <Pressable
      accessibilityRole="button"
      disabled={disabled || busy}
      onPressIn={() => void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {})}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        size === 'md' && styles.buttonMd,
        {
          backgroundColor: c.bg,
          borderColor: c.border ?? c.bg,
          borderBottomColor: c.edge,
          borderBottomWidth: pressed ? 2 : edge + (c.border ? 2 : 0),
          marginTop: pressed ? edge - 2 : 0,
          opacity: disabled ? 0.45 : 1,
        },
      ]}
    >
      {busy ? (
        <ActivityIndicator color={c.fg} />
      ) : (
        <View style={styles.buttonInner}>
          {icon ? <Ionicons name={icon} size={size === 'md' ? 18 : 22} color={c.fg} /> : null}
          <Text style={[styles.buttonText, size === 'md' && styles.buttonTextMd, { color: c.fg }]}>{title}</Text>
        </View>
      )}
    </Pressable>
  );
}

/** Round icon button (Find My style). */
export function IconButton({ icon, onPress, tint = colors.ink, bg = 'rgba(0,0,0,0.08)', size = 56, label }: {
  icon: IconName;
  onPress: () => void;
  tint?: string;
  bg?: string;
  size?: number;
  label: string;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      style={({ pressed }) => [{ width: size, height: size, borderRadius: size / 2, backgroundColor: bg, alignItems: 'center', justifyContent: 'center', opacity: pressed ? 0.7 : 1 }]}
    >
      <Ionicons name={icon} size={size * 0.43} color={tint} />
    </Pressable>
  );
}

export function Card({ children, style, tone }: { children: ReactNode; style?: ViewStyle; tone?: 'red' | 'green' | 'orange' }) {
  const toneStyle = tone === 'red'
    ? { backgroundColor: colors.redSoft, borderColor: colors.redSoft }
    : tone === 'green'
      ? { backgroundColor: colors.greenSoft, borderColor: colors.greenSoft }
      : tone === 'orange'
        ? { backgroundColor: colors.orangeSoft, borderColor: colors.orangeSoft }
        : null;
  return <View style={[styles.card, toneStyle, style]}>{children}</View>;
}

/** A row with an icon in a tinted circle, a title and a detail. */
export function Row({ icon, tint = colors.red, title, detail, right }: {
  icon: IconName;
  tint?: string;
  title: string;
  detail?: string | null;
  right?: ReactNode;
}) {
  return (
    <View style={styles.row}>
      <View style={[styles.rowIcon, { backgroundColor: tint + '1F' }]}>
        <Ionicons name={icon} size={20} color={tint} />
      </View>
      <View style={styles.flex}>
        <Text style={type.heading} numberOfLines={1}>{title}</Text>
        {detail ? <Text style={type.small} numberOfLines={2}>{detail}</Text> : null}
      </View>
      {right}
    </View>
  );
}

export function Chip({ text, tone = 'neutral', icon }: { text: string; tone?: 'neutral' | 'red' | 'green' | 'orange'; icon?: IconName }) {
  const t = {
    neutral: [colors.surface, colors.muted],
    red: [colors.redSoft, colors.red],
    green: [colors.greenSoft, colors.greenDark],
    orange: [colors.orangeSoft, colors.orangeDark],
  }[tone];
  return (
    <View style={[styles.chip, { backgroundColor: t[0] }]}>
      {icon ? <Ionicons name={icon} size={14} color={t[1]} /> : null}
      <Text style={[styles.chipText, { color: t[1] }]}>{text}</Text>
    </View>
  );
}

export function Field({ label, ...props }: { label?: string } & TextInputProps) {
  return (
    <View style={{ gap: space.sm }}>
      {label ? <Label>{label}</Label> : null}
      <TextInput placeholderTextColor={colors.faint} {...props} style={[styles.input, props.style]} />
    </View>
  );
}

/** Duolingo-style progress bar. */
export function Progress({ value, color = colors.red }: { value: number; color?: string }) {
  return (
    <View style={styles.track}>
      <View style={[styles.fill, { width: `${Math.max(4, Math.min(100, value * 100))}%`, backgroundColor: color }]}>
        <View style={styles.shine} />
      </View>
    </View>
  );
}

/** Big on/off switch drawn as a pill. */
export function Toggle({ value, onChange, disabled }: { value: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <Pressable
      accessibilityRole="switch"
      accessibilityState={{ checked: value, disabled }}
      disabled={disabled}
      onPress={() => {
        void Haptics.selectionAsync().catch(() => {});
        onChange(!value);
      }}
      style={[styles.toggle, { backgroundColor: value ? colors.green : colors.line }]}
    >
      <View style={[styles.knob, { alignSelf: value ? 'flex-end' : 'flex-start' }]} />
    </Pressable>
  );
}

export function Notice({ children, tone = 'red' }: { children: ReactNode; tone?: 'red' | 'orange' }) {
  return (
    <View style={[styles.notice, { backgroundColor: tone === 'red' ? colors.redSoft : colors.orangeSoft }]}>
      <Ionicons name="alert-circle" size={20} color={tone === 'red' ? colors.red : colors.orangeDark} />
      <Text style={[type.small, { color: colors.ink, flex: 1 }]}>{children}</Text>
    </View>
  );
}

export const styles = StyleSheet.create({
  flex: { flex: 1 },
  screen: { padding: space.xl, gap: space.lg },
  button: {
    borderRadius: radius.md,
    borderWidth: 2,
    minHeight: 58,
    paddingHorizontal: space.xl,
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonMd: { minHeight: 46 },
  buttonInner: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  buttonText: { fontFamily: font.heavy, fontSize: 17, letterSpacing: 0.8, textTransform: 'uppercase' },
  buttonTextMd: { fontSize: 15 },
  card: {
    backgroundColor: colors.white,
    borderRadius: radius.lg,
    borderWidth: 2,
    borderColor: colors.line,
    padding: space.lg,
    gap: space.md,
  },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  rowIcon: { width: 42, height: 42, borderRadius: 21, alignItems: 'center', justifyContent: 'center' },
  chip: { flexDirection: 'row', alignItems: 'center', gap: 5, alignSelf: 'flex-start', paddingHorizontal: 10, paddingVertical: 5, borderRadius: radius.pill },
  chipText: { fontFamily: font.heavy, fontSize: 13 },
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
  track: { height: 16, borderRadius: 8, backgroundColor: colors.line, overflow: 'hidden' },
  fill: { height: 16, borderRadius: 8 },
  shine: { position: 'absolute', top: 4, left: 8, right: 8, height: 4, borderRadius: 2, backgroundColor: 'rgba(255,255,255,0.35)' },
  toggle: { width: 64, height: 36, borderRadius: 18, padding: 4, justifyContent: 'center' },
  knob: { width: 28, height: 28, borderRadius: 14, backgroundColor: colors.white },
  notice: { flexDirection: 'row', gap: space.sm, alignItems: 'center', padding: space.md, borderRadius: radius.md },
});
