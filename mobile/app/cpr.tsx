import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { Animated, StyleSheet, Text, View } from 'react-native';

import { colors, space } from '../components/theme';
import { Body, Button, Card, Label, Screen, Title } from '../components/ui';
import { openAedHelp } from '../lib/aedHelp';
import { AED_HELP_BUTTON, AED_STEP, CPR_CHECK, CPR_DEPTH_RATE, MOD_BREATHING, MOD_SEIZURE } from '../lib/copy';
import { METRONOME_BPM, useMetronome } from '../lib/metronome';
import { useProfile } from '../lib/profile';
import { supabase } from '../lib/supabase';
import { closeAlert } from '../lib/useDispatches';

export default function CprGuide() {
  const { incidentId, live } = useLocalSearchParams<{ incidentId?: string; live?: string }>();
  const { profile } = useProfile();
  const metronome = useMetronome();
  const { start } = metronome;
  const [modifiers, setModifiers] = useState<string[]>([]);
  const [pulse] = useState(() => new Animated.Value(1));

  // Arriving from an alert: start the metronome right away.
  useEffect(() => {
    if (live === '1') start();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live]);

  // Show the spec's modifier lines only when this incident has those modifiers.
  useEffect(() => {
    if (!incidentId || !supabase) return;
    let cancelled = false;
    supabase
      .from('incidents')
      .select('modifiers')
      .eq('id', incidentId)
      .maybeSingle()
      .then(({ data }) => {
        if (!cancelled) setModifiers(((data as { modifiers: string[] | null } | null)?.modifiers ?? []) as string[]);
      });
    return () => {
      cancelled = true;
    };
  }, [incidentId]);

  useEffect(() => {
    if (metronome.beat === 0) return;
    pulse.setValue(1.18);
    Animated.timing(pulse, { toValue: 1, duration: 220, useNativeDriver: true }).start();
  }, [metronome.beat, pulse]);

  return (
    <Screen>
      <Title>CPR guide</Title>

      <View style={styles.center}>
        <Animated.View style={[styles.beat, metronome.running && styles.beatOn, { transform: [{ scale: pulse }] }]}>
          <Text style={styles.beatText}>{METRONOME_BPM}</Text>
          <Text style={styles.beatUnit}>per minute</Text>
        </Animated.View>
      </View>
      <Button
        title={metronome.running ? 'Stop metronome' : 'Start metronome'}
        kind={metronome.running ? 'secondary' : 'primary'}
        big
        onPress={metronome.running ? metronome.stop : metronome.start}
      />

      <Card>
        <Label>Check and start</Label>
        <Body>{CPR_CHECK}</Body>
      </Card>
      <Card>
        <Label>Push</Label>
        <Body>{CPR_DEPTH_RATE}</Body>
      </Card>
      <Card>
        <Label>AED</Label>
        <Body>{AED_STEP}</Body>
        {/* The CPR guide is only reached at the person (or from Home to practice), so AED help is always offered. */}
        <Button
          title={AED_HELP_BUTTON}
          big
          onPress={() => {
            // The metronome would talk over the spoken AED steps; the AED help screen links back here.
            metronome.stop();
            openAedHelp(incidentId, profile?.id, 'cpr');
          }}
        />
      </Card>
      {modifiers.includes('breathing') ? (
        <Card>
          <Label>Breathing</Label>
          <Body>{MOD_BREATHING}</Body>
        </Card>
      ) : null}
      {modifiers.includes('seizure') ? (
        <Card>
          <Label>Shaking</Label>
          <Body>{MOD_SEIZURE}</Body>
        </Card>
      ) : null}

      <Button
        title="Done"
        kind="secondary"
        onPress={() => {
          metronome.stop();
          if (live === '1') closeAlert();
          if (router.canDismiss()) router.dismissTo('/');
          else router.replace('/');
        }}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  center: { alignItems: 'center', paddingVertical: space.md },
  beat: {
    width: 168,
    height: 168,
    borderRadius: 84,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.muted,
  },
  beatOn: { backgroundColor: colors.primary },
  beatText: { fontSize: 52, fontWeight: '800', color: colors.primaryText, fontVariant: ['tabular-nums'] },
  beatUnit: { fontSize: 15, color: colors.primaryText },
});
