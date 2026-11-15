import { router, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { useCallback, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { colors, font, space } from '../components/theme';
import { Body, Button, Progress, Screen, Title } from '../components/ui';
import {
  AED_HELP_BACK,
  AED_HELP_NEXT,
  AED_HELP_NOTE,
  AED_HELP_REPEAT,
  AED_HELP_STEP_OF,
  AED_HELP_STEPS,
  AED_HELP_TITLE,
  CPR_GUIDE,
} from '../lib/copy';
import { say, stopSpeaking } from '../lib/speech';

/**
 * AED help: one step at a time, in large text, spoken aloud on the phone (no network). Step 1 is
 * spoken on open; the screen only advances on Next. Speech stops whenever the screen loses focus.
 * The "GIVE ME HELP WITH AED" milestone is sent by the button that opens this screen (lib/aedHelp.ts).
 */
export default function AedHelp() {
  const { incidentId, from } = useLocalSearchParams<{ incidentId?: string; from?: string }>();
  const [step, setStep] = useState(0);
  const total = AED_HELP_STEPS.length;
  const text = AED_HELP_STEPS[step];

  // Speaks the current step on open, on every step change and on coming back to this screen.
  useFocusEffect(
    useCallback(() => {
      void say(AED_HELP_STEPS[step]);
      return () => stopSpeaking();
    }, [step]),
  );

  function openCpr() {
    stopSpeaking();
    if (from === 'cpr' && router.canGoBack()) router.back();
    else router.push({ pathname: '/cpr', params: { incidentId: incidentId ?? '', live: incidentId ? '1' : '' } });
  }

  return (
    <Screen>
      <View style={styles.top}>
        <View style={styles.flex}>
          <Progress value={(step + 1) / total} color={colors.green} />
        </View>
        <Text style={styles.counter}>{AED_HELP_STEP_OF(step + 1, total)}</Text>
      </View>
      <Title>{AED_HELP_TITLE}</Title>
      <Body muted>{AED_HELP_NOTE}</Body>

      <View style={styles.stepBox} accessibilityLiveRegion="polite">
        <Text style={styles.stepText}>{text}</Text>
      </View>

      <View style={styles.row}>
        <View style={styles.flex}>
          <Button title={AED_HELP_BACK} kind="secondary" disabled={step === 0} onPress={() => setStep((s) => Math.max(0, s - 1))} />
        </View>
        <View style={styles.flex}>
          <Button title={AED_HELP_NEXT} kind="green" disabled={step >= total - 1} onPress={() => setStep((s) => Math.min(total - 1, s + 1))} />
        </View>
      </View>
      <Button title={AED_HELP_REPEAT} kind="secondary" icon="refresh" onPress={() => void say(text)} />
      <Button title={CPR_GUIDE} kind="ghost" onPress={openCpr} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  top: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  counter: { fontFamily: font.heavy, fontSize: 14, color: colors.muted },
  stepBox: {
    backgroundColor: colors.greenSoft,
    borderRadius: 22,
    padding: space.xl,
    minHeight: 240,
    justifyContent: 'center',
  },
  stepText: { fontFamily: font.heavy, fontSize: 28, lineHeight: 36, color: colors.ink },
  row: { flexDirection: 'row', gap: space.md },
  flex: { flex: 1 },
});
