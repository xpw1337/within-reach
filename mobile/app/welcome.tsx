import Ionicons from '@expo/vector-icons/Ionicons';
import * as Location from 'expo-location';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { colors, space, type } from '../components/theme';
import { Body, Button, Field, Progress, Small } from '../components/ui';
import { updateSettings, useSettings } from '../lib/settings';

const STEPS = ['intro', 'name', 'phone', 'location'] as const;
type Step = (typeof STEPS)[number];

function digits(s: string): string {
  return s.replace(/\D/g, '');
}

/** Looks like a phone number we can ring: 10 digits (US), or a + and 8 to 15 digits. */
function phoneOk(s: string): boolean {
  const d = digits(s);
  if (s.trim().startsWith('+')) return d.length >= 8 && d.length <= 15;
  return d.length === 10 || (d.length === 11 && d.startsWith('1'));
}

/** First run: what this is, your name, your number (so an alert can ring you), location. */
export default function Welcome() {
  const { settings } = useSettings();
  const [step, setStep] = useState<Step>('intro');
  const [name, setName] = useState(settings.name);
  const [phone, setPhone] = useState(settings.phone);
  const [asking, setAsking] = useState(false);
  const [denied, setDenied] = useState(false);
  const index = STEPS.indexOf(step);

  const back = () => index > 0 && setStep(STEPS[index - 1]);

  async function finish() {
    setAsking(true);
    const perm = await Location.requestForegroundPermissionsAsync().catch(() => null);
    setAsking(false);
    if (perm?.status !== 'granted') {
      setDenied(true);
      return;
    }
    await updateSettings({ name: name.trim(), phone: phone.trim(), onboarded: true, onDuty: true });
  }

  return (
    <SafeAreaView style={styles.flex} edges={['top', 'bottom']}>
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        {step !== 'intro' ? (
          <View style={styles.top}>
            <Pressable onPress={back} hitSlop={12} accessibilityLabel="Back">
              <Ionicons name="arrow-back" size={26} color={colors.faint} />
            </Pressable>
            <View style={styles.flex}>
              <Progress value={index / (STEPS.length - 1)} />
            </View>
          </View>
        ) : null}

        <View style={styles.body}>
          {step === 'intro' ? (
            <>
              <View style={styles.badge}>
                <Ionicons name="heart" size={64} color={colors.white} />
              </View>
              <Text style={[type.hero, styles.center]}>Be the help{'\n'}that arrives first</Text>
              <Body muted center>
                When a camera sees someone collapse nearby, the closest person with Within Reach gets an alert and is
                walked straight to them, past the nearest AED.
              </Body>
            </>
          ) : null}

          {step === 'name' ? (
            <>
              <Text style={type.title}>What should we call you?</Text>
              <Field value={name} onChangeText={setName} placeholder="First name" autoFocus autoCapitalize="words" returnKeyType="next"
                onSubmitEditing={() => name.trim() && setStep('phone')} />
              <Small>The 911 dispatcher hears this name when you are on your way.</Small>
            </>
          ) : null}

          {step === 'phone' ? (
            <>
              <Text style={type.title}>Your phone number</Text>
              <Field value={phone} onChangeText={setPhone} placeholder="(555) 123-4567" autoFocus keyboardType="phone-pad"
                textContentType="telephoneNumber" autoComplete="tel" />
              <View style={styles.why}>
                <Ionicons name="call" size={20} color={colors.red} />
                <Small color={colors.ink}>
                  If someone falls near you, we call this number so the alert reaches you even when the app is closed.
                  It is used for nothing else.
                </Small>
              </View>
            </>
          ) : null}

          {step === 'location' ? (
            <>
              <View style={[styles.badge, { backgroundColor: colors.blue }]}>
                <Ionicons name="navigate" size={56} color={colors.white} />
              </View>
              <Text style={[type.title, styles.center]}>Share your location</Text>
              <Body muted center>
                We use it only to find the closest helper and to guide you there. It is shared while you are available,
                and you can turn that off any time.
              </Body>
              {denied ? (
                <Small color={colors.red}>Location is off for this app. Turn it on in Settings, then try again.</Small>
              ) : null}
            </>
          ) : null}
        </View>

        <View style={styles.footer}>
          {step === 'intro' ? <Button title="Get started" onPress={() => setStep('name')} /> : null}
          {step === 'name' ? <Button title="Continue" disabled={!name.trim()} onPress={() => setStep('phone')} /> : null}
          {step === 'phone' ? <Button title="Continue" disabled={!phoneOk(phone)} onPress={() => setStep('location')} /> : null}
          {step === 'location' ? <Button title="Allow location" icon="navigate" busy={asking} onPress={() => void finish()} /> : null}
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.white },
  top: { flexDirection: 'row', alignItems: 'center', gap: space.lg, paddingHorizontal: space.xl, paddingTop: space.md },
  body: { flex: 1, padding: space.xl, gap: space.lg, justifyContent: 'center' },
  center: { textAlign: 'center' },
  badge: {
    width: 120, height: 120, borderRadius: 60, backgroundColor: colors.red, alignSelf: 'center',
    alignItems: 'center', justifyContent: 'center', marginBottom: space.md,
    borderBottomWidth: 6, borderBottomColor: 'rgba(0,0,0,0.15)',
  },
  why: { flexDirection: 'row', gap: space.sm, backgroundColor: colors.redSoft, padding: space.md, borderRadius: 14, alignItems: 'flex-start' },
  footer: { padding: space.xl, paddingTop: 0 },
});
