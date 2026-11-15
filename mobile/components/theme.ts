// Design tokens: plain white surfaces, one strong red (Red Cross), chunky rounded shapes and a
// rounded bold face (Duolingo-style), from the sos/phone-app redesign. The screens keep using the
// original token names below; only their values changed to the new palette.

const palette = {
  // brand
  red: '#ED1B2E',
  redDark: '#B8101F',
  redSoft: '#FDE8EA',
  // status
  green: '#34C759',
  greenDark: '#23A047',
  greenSoft: '#E6F8EC',
  orange: '#FF8A00',
  orangeDark: '#D16F00',
  orangeSoft: '#FFF1E0',
  blue: '#1C8EF6',
  blueSoft: '#E8F3FE',
  // neutrals
  ink: '#1A1A1A',
  faint: '#AFAFAF',
  line: '#E8E8E8',
  surface: '#F6F6F6',
  white: '#FFFFFF',
};

export const colors = {
  ...palette,
  // Original names used across the app.
  bg: palette.white,
  card: palette.white,
  text: palette.ink,
  muted: '#7A7A7A',
  border: palette.line,
  primary: palette.red,
  primaryText: palette.white,
  alertBg: palette.red,
  alertText: palette.white,
  ok: palette.green,
  warn: palette.orange,
  info: palette.blue,
};

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 };
export const radius = { sm: 12, md: 16, lg: 22, pill: 999 } as const;

export const font = {
  regular: 'Nunito_600SemiBold',
  bold: 'Nunito_700Bold',
  heavy: 'Nunito_800ExtraBold',
  black: 'Nunito_900Black',
} as const;

export const type = {
  hero: { fontFamily: font.black, fontSize: 34, lineHeight: 38, color: colors.ink },
  title: { fontFamily: font.heavy, fontSize: 26, lineHeight: 31, color: colors.ink },
  heading: { fontFamily: font.heavy, fontSize: 19, lineHeight: 24, color: colors.ink },
  body: { fontFamily: font.regular, fontSize: 17, lineHeight: 24, color: colors.ink },
  small: { fontFamily: font.regular, fontSize: 14, lineHeight: 19, color: colors.muted },
  label: { fontFamily: font.heavy, fontSize: 13, letterSpacing: 1.2, color: colors.muted, textTransform: 'uppercase' as const },
};
