import Ionicons from '@expo/vector-icons/Ionicons';
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { Animated, StyleSheet, Text, View } from 'react-native';

import { colors, font, space, type } from '../components/theme';
import { Button, Card, Row, Screen } from '../components/ui';
import { AED_HELP_BUTTON, AED_STEP, CPR_CHECK, CPR_DEPTH_RATE, MOD_BREATHING } from '../lib/copy';
import { METRONOME_BPM, useMetronome } from '../lib/metronome';

export default function CprGuide() {
  const { live } = useLocalSearchParams<{ live?: string }>();
  const metronome = useMetronome();
  const { start } = metronome;
  const [pulse] = useState(() => new Animated.Value(1));

  // Opened at the person: start the beat right away.
  useEffect(() => {
    if (live === '1') start();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live]);

  useEffect(() => {
    if (metronome.beat === 0) return;
    pulse.setValue(1.14);
    Animated.timing(pulse, { toValue: 1, duration: 240, useNativeDriver: true }).start();
  }, [metronome.beat, pulse]);

  return (
    <Screen>
      <Text style={type.title}>CPR</Text>
      <View style={styles.center}>
        <Animated.View style={[styles.beat, metronome.running && styles.beatOn, { transform: [{ scale: pulse }] }]}>
          <Ionicons name="heart" size={44} color={colors.white} />
          <Text style={styles.beatText}>{METRONOME_BPM}</Text>
          <Text style={styles.beatUnit}>pushes a minute</Text>
        </Animated.View>
      </View>
      <Button
        title={metronome.running ? 'Stop the beat' : 'Start the beat'}
        kind={metronome.running ? 'secondary' : 'primary'}
        icon={metronome.running ? 'stop' : 'play'}
        onPress={metronome.running ? metronome.stop : metronome.start}
      />
      <Card>
        <Row icon="hand-left" title="Check and start" />
        <Text style={type.body}>{CPR_CHECK}</Text>
      </Card>
      <Card>
        <Row icon="arrow-down" title="Push" />
        <Text style={type.body}>{CPR_DEPTH_RATE}</Text>
      </Card>
      <Card>
        <Row icon="leaf" tint={colors.blue} title="If they're breathing" />
        <Text style={type.body}>{MOD_BREATHING}</Text>
      </Card>
      <Card tone="green">
        <Row icon="flash" tint={colors.greenDark} title="AED" />
        <Text style={type.body}>{AED_STEP}</Text>
        <Button
          title={AED_HELP_BUTTON}
          kind="green"
          onPress={() => {
            metronome.stop(); // it would talk over the spoken AED steps
            router.push('/aed-help');
          }}
        />
      </Card>
      <Button
        title="Back"
        kind="ghost"
        onPress={() => {
          metronome.stop();
          if (router.canGoBack()) router.back();
          else router.replace('/');
        }}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  center: { alignItems: 'center', paddingVertical: space.md },
  beat: {
    width: 190, height: 190, borderRadius: 95, alignItems: 'center', justifyContent: 'center',
    backgroundColor: colors.faint, borderBottomWidth: 6, borderBottomColor: 'rgba(0,0,0,0.15)',
  },
  beatOn: { backgroundColor: colors.red },
  beatText: { fontFamily: font.black, fontSize: 46, lineHeight: 50, color: colors.white, fontVariant: ['tabular-nums'] },
  beatUnit: { fontFamily: font.bold, fontSize: 13, color: colors.white },
});
