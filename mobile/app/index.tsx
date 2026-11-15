import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { Animated, Easing, StyleSheet, Text, View } from 'react-native';

import { colors, font, space, type } from '../components/theme';
import { Button, Card, IconButton, Notice, Row, Screen, Toggle } from '../components/ui';
import { formatDistance } from '../lib/geo';
import { updateSettings, useSettings } from '../lib/settings';
import { useSos } from '../lib/sos';

/** A soft ring that breathes out from the status badge while you are on call. */
function Pulse({ on, color }: { on: boolean; color: string }) {
  const [v] = useState(() => new Animated.Value(0));
  useEffect(() => {
    if (!on) return;
    const loop = Animated.loop(Animated.timing(v, { toValue: 1, duration: 1800, easing: Easing.out(Easing.quad), useNativeDriver: true }));
    loop.start();
    return () => loop.stop();
  }, [on, v]);
  if (!on) return null;
  return (
    <Animated.View
      style={[styles.pulse, { borderColor: color, opacity: v.interpolate({ inputRange: [0, 1], outputRange: [0.5, 0] }),
        transform: [{ scale: v.interpolate({ inputRange: [0, 1], outputRange: [1, 1.6] }) }] }]}
    />
  );
}

export default function Home() {
  const { settings } = useSettings();
  const sos = useSos();
  const mission = sos.phone?.mission;
  const active = mission && mission.status !== 'resolved';
  const connected = sos.conn === 'connected';
  const live = settings.onDuty && connected;
  const calls = sos.phone?.me?.calls;

  const badgeColor = live ? colors.green : settings.onDuty ? colors.orange : colors.faint;
  const headline = !settings.onDuty ? "You're off call" : connected ? "You're on call" : 'Reconnecting...';
  const sub = !settings.onDuty
    ? 'Turn this on to help people near you.'
    : connected
      ? "We'll alert you if someone nearby needs help. Keep the app open."
      : `Trying to reach ${sos.server || 'the server'}.`;

  let locationText = 'Off';
  if (settings.onDuty || active) {
    if (sos.locationStatus === 'denied') locationText = 'Permission denied in Settings';
    else if (sos.location) locationText = `Accurate to ${formatDistance(sos.location.accuracy_m)}`;
    else locationText = 'Finding you...';
  }

  return (
    <Screen>
      <View style={styles.header}>
        <View style={styles.brand}>
          <Ionicons name="heart" size={22} color={colors.red} />
          <Text style={styles.brandText}>within reach</Text>
        </View>
        <IconButton icon="settings-sharp" label="Settings" size={44} tint={colors.muted} bg={colors.surface} onPress={() => router.push('/settings')} />
      </View>

      {active ? (
        <Button title="Back to the emergency" icon="navigate" onPress={() => router.replace('/mission')} />
      ) : null}

      <View style={styles.hero}>
        <View style={styles.badgeWrap}>
          <Pulse on={live} color={badgeColor} />
          <View style={[styles.badge, { backgroundColor: badgeColor }]}>
            <Ionicons name={settings.onDuty ? 'shield-checkmark' : 'moon'} size={58} color={colors.white} />
          </View>
        </View>
        <Text style={[type.hero, { textAlign: 'center' }]}>{headline}</Text>
        <Text style={[type.body, { color: colors.muted, textAlign: 'center' }]}>{sub}</Text>
      </View>

      <Card>
        <Row
          icon="hand-left"
          tint={colors.red}
          title="Available to help"
          detail={settings.onDuty ? 'Alerts are on' : 'Alerts are off'}
          right={<Toggle value={settings.onDuty} onChange={(v) => void updateSettings({ onDuty: v })} />}
        />
      </Card>

      <Card>
        <Row icon="wifi" tint={connected ? colors.green : colors.orange} title={connected ? 'Connected' : 'Not connected'} detail={sos.server || 'No server'} />
        <Row icon="navigate" tint={sos.location ? colors.blue : colors.faint} title="Location" detail={locationText} />
        <Row
          icon="call"
          tint={calls && settings.phone ? colors.green : colors.faint}
          title={settings.phone ? `Calls to ${settings.phone}` : 'No phone number'}
          detail={calls ? 'An alert also rings your phone' : 'Phone calls are not set up on the server yet'}
        />
      </Card>

      {sos.conn !== 'connected' && sos.error ? <Notice>{sos.error}</Notice> : null}

      <Button title="Practice CPR" kind="secondary" icon="pulse" onPress={() => router.push('/cpr')} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  brand: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  brandText: { fontFamily: font.black, fontSize: 22, color: colors.red, letterSpacing: -0.3 },
  hero: { alignItems: 'center', gap: space.sm, paddingVertical: space.lg },
  badgeWrap: { width: 132, height: 132, alignItems: 'center', justifyContent: 'center', marginBottom: space.md },
  badge: { width: 120, height: 120, borderRadius: 60, alignItems: 'center', justifyContent: 'center', borderBottomWidth: 6, borderBottomColor: 'rgba(0,0,0,0.15)' },
  pulse: { position: 'absolute', width: 120, height: 120, borderRadius: 60, borderWidth: 6 },
});
