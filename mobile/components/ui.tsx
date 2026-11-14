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

import { colors, space } from './theme';

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
  const bg =
    kind === 'primary' ? colors.primary : kind === 'ok' ? colors.ok : kind === 'danger' ? colors.text : colors.card;
  const fg = kind === 'secondary' ? colors.text : colors.primaryText;
  const isDisabled = disabled || busy;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: !!isDisabled, busy: !!busy }}
      onPress={onPress}
      disabled={isDisabled}
      style={({ pressed }) => [
        styles.button,
        big && styles.buttonBig,
        { backgroundColor: bg, opacity: isDisabled ? 0.5 : pressed ? 0.8 : 1 },
        kind === 'secondary' && styles.buttonSecondary,
      ]}
    >
      {busy ? <ActivityIndicator color={fg} /> : <Text style={[styles.buttonText, big && styles.buttonTextBig, { color: fg }]}>{title}</Text>}
    </Pressable>
  );
}

export function Field({ label, ...props }: { label: string } & TextInputProps) {
  return (
    <View style={styles.field}>
      <Label>{label}</Label>
      <TextInput placeholderTextColor={colors.muted} style={styles.input} {...props} />
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
        <Text style={styles.body}>{label}</Text>
        {help ? <Text style={styles.help}>{help}</Text> : null}
      </View>
      <Switch
        accessibilityLabel={label}
        value={value}
        onValueChange={onValueChange}
        disabled={disabled}
        trackColor={{ true: colors.ok, false: colors.border }}
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
  const color = tone === 'info' ? colors.info : tone === 'error' ? colors.primary : colors.warn;
  return (
    <View style={[styles.notice, { borderColor: color }]}>
      <Text style={[styles.body, { color }]}>{children}</Text>
    </View>
  );
}

export const styles = StyleSheet.create({
  flex: { flex: 1 },
  screen: { padding: space.lg, gap: space.lg, paddingBottom: space.xl * 2 },
  title: { fontSize: 28, fontWeight: '700' },
  body: { fontSize: 16, lineHeight: 22 },
  help: { fontSize: 13, lineHeight: 18, color: colors.muted, marginTop: 2 },
  label: { fontSize: 13, fontWeight: '600', color: colors.muted, textTransform: 'uppercase', letterSpacing: 0.5 },
  card: {
    backgroundColor: colors.card,
    borderRadius: 14,
    padding: space.lg,
    gap: space.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  button: {
    minHeight: 52,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: space.lg,
  },
  buttonBig: { minHeight: 72 },
  buttonSecondary: { borderWidth: 1, borderColor: colors.border },
  buttonText: { fontSize: 17, fontWeight: '700' },
  buttonTextBig: { fontSize: 22 },
  field: { gap: space.xs },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 10,
    paddingHorizontal: space.md,
    paddingVertical: space.md,
    fontSize: 17,
    color: colors.text,
    backgroundColor: colors.card,
  },
  toggleRow: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  segmented: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  segment: {
    paddingVertical: space.sm,
    paddingHorizontal: space.md,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
  },
  segmentSelected: { backgroundColor: colors.text, borderColor: colors.text },
  segmentText: { fontSize: 15, color: colors.text },
  segmentTextSelected: { color: colors.primaryText, fontWeight: '700' },
  notice: { borderLeftWidth: 4, paddingLeft: space.md, paddingVertical: space.xs },
});
