import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { Animated, Easing, Linking, Pressable, StyleSheet, Text, View } from 'react-native';

import { colors, font, space, type } from '../components/theme';
import { Button, Card, IconButton, Notice, Row, Screen, Small, Toggle } from '../components/ui';
import { CONSENT_LOCATION_HELP, PRIVACY_LINE, RESPONDER_ROLE_LABELS } from '../lib/copy';
import { missingEnv } from '../lib/env';
import { useLocationState } from '../lib/location';
import { setOnDuty, useProfile } from '../lib/profile';
import { errorMessage } from '../lib/supabase';
import { isOpen, useAlertState, type RealtimeStatus } from '../lib/useDispatches';

// Layout from the sos/phone-app redesign (status badge, "You're on call", icon rows). The data and
// actions are this app's: the responder profile, the duty switch, alerts over Realtime, location.

const REALTIME_DETAIL: Record<RealtimeStatus, string> = {
  connected: 'Keep the app open to be alerted.',
  connecting: 'Connecting...',
  error: 'Connection problem. Reopen the app to retry.',
  off: 'Not connected.',
};

function formatTime(iso: string | null): string {
  return iso ? new Date(iso).toLocaleTimeString() : '--';
}

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
      style={[
        styles.pulse,
        {
          borderColor: color,
          opacity: v.interpolate({ inputRange: [0, 1], outputRange: [0.5, 0] }),
          transform: [{ scale: v.interpolate({ inputRange: [0, 1], outputRange: [1, 1.6] }) }],
        },
      ]}
    />
  );
}

export default function Home() {
  const { profile } = useProfile();
  const location = useLocationState();
  const alert = useAlertState();
  const [dutyError, setDutyError] = useState<string | null>(null);
  const [savingDuty, setSavingDuty] = useState(false);
  const missing = missingEnv();

  if (!profile) return null;

  async function onToggleDuty(value: boolean) {
    setSavingDuty(true);
    setDutyError(null);
    try {
      await setOnDuty(value);
    } catch (error) {
      setDutyError(errorMessage(error));
    } finally {
      setSavingDuty(false);
    }
  }

  const connected = alert.realtime === 'connected';
  const live = profile.on_duty && connected;
  const badgeColor = live ? colors.green : profile.on_duty ? colors.orange : colors.faint;
  const headline = !profile.on_duty ? "You're off call" : connected ? "You're on call" : 'Reconnecting...';
  const sub = !profile.on_duty
    ? 'Turn this on to help people near you.'
    : connected
      ? "We'll alert you if someone nearby needs help. Keep the app open."
      : REALTIME_DETAIL[alert.realtime];

  let locationLine: string;
  if (!profile.consent_location) locationLine = 'Off: you have not agreed to share your location.';
  else if (!profile.on_duty) locationLine = 'Off while you are off duty.';
  else if (location.status === 'requesting') locationLine = 'Asking for permission...';
  else if (location.status === 'denied') locationLine = 'Permission denied. Allow location for Expo Go in Settings.';
  else if (location.status === 'watching') locationLine = `Sharing. Last update ${formatTime(location.lastWriteAt)}.`;
  else if (location.status === 'error') locationLine = 'Location is unavailable on this phone right now.';
  else locationLine = 'Off.';
  const locationOn = location.status === 'watching' && profile.consent_location && profile.on_duty;

  const responderDetail = [
    RESPONDER_ROLE_LABELS[profile.role],
    profile.cpr_trained ? 'CPR trained' : null,
    profile.building_label,
  ]
    .filter(Boolean)
    .join(', ');

  return (
    <Screen>
      <View style={styles.header}>
        {/* A long press on the brand opens the hidden georeference calibration screen (team setup only). */}
        <Pressable onLongPress={() => router.push('/calibrate')} delayLongPress={1200} accessible={false} style={styles.brand}>
          <Ionicons name="heart" size={22} color={colors.red} />
          <Text style={styles.brandText}>within reach</Text>
        </Pressable>
        <IconButton icon="settings-sharp" label="Edit profile" size={44} tint={colors.muted} bg={colors.surface} onPress={() => router.push('/onboarding')} />
      </View>

      {missing.length > 0 ? <Notice tone="error">Missing settings in this build: {missing.join(', ')}.</Notice> : null}

      {alert.dispatch && isOpen(alert.dispatch) ? (
        <Button
          title="Back to the emergency"
          icon="navigate"
          big
          onPress={() => router.push({ pathname: '/alert/[dispatchId]', params: { dispatchId: alert.dispatch!.id } })}
        />
      ) : null}

      <View style={styles.hero}>
        <View style={styles.badgeWrap}>
          <Pulse on={live} color={badgeColor} />
          <View style={[styles.badge, { backgroundColor: badgeColor }]}>
            <Ionicons name={profile.on_duty ? 'shield-checkmark' : 'moon'} size={58} color={colors.white} />
          </View>
        </View>
        <Text style={[type.hero, styles.center]}>{headline}</Text>
        <Text style={[type.body, styles.center, { color: colors.muted }]}>{sub}</Text>
      </View>

      <Card>
        <Row
          icon="hand-left"
          tint={colors.red}
          title="Available to help"
          detail={profile.on_duty ? 'Alerts are on' : 'Alerts are off'}
          right={<Toggle value={profile.on_duty} onChange={(v) => void onToggleDuty(v)} disabled={savingDuty} />}
        />
        {dutyError ? <Notice tone="error">Could not change duty status: {dutyError}</Notice> : null}
      </Card>

      <Card>
        <Row
          icon="wifi"
          tint={connected ? colors.green : colors.orange}
          title={connected ? 'Connected' : 'Not connected'}
          detail={alert.realtimeError ?? REALTIME_DETAIL[alert.realtime]}
        />
        <Row icon="navigate" tint={locationOn ? colors.blue : colors.faint} title="Location" detail={locationLine} />
        <Row
          icon="call"
          tint={profile.consent_calls ? colors.green : colors.faint}
          title={profile.consent_calls ? `Calls to ${profile.phone}` : 'Phone calls off'}
          detail={profile.consent_calls ? 'An alert can also ring your phone.' : 'You only get alerts in this app and by message.'}
        />
        <Row icon="person" tint={colors.red} title={profile.name} detail={responderDetail} />
        {!profile.consent_location ? <Small>{CONSENT_LOCATION_HELP}</Small> : null}
        {location.status === 'denied' ? (
          <Button title="Open Settings" kind="secondary" onPress={() => void Linking.openSettings()} />
        ) : null}
        {location.error ? <Notice tone="error">{location.error}</Notice> : null}
      </Card>

      <Button title="Practice CPR" kind="secondary" icon="pulse" onPress={() => router.push('/cpr')} />
      <Button title="Edit profile" kind="secondary" icon="person-circle" onPress={() => router.push('/onboarding')} />
      <Small center>{PRIVACY_LINE}</Small>
    </Screen>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  brand: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  brandText: { fontFamily: font.black, fontSize: 22, color: colors.red, letterSpacing: -0.3 },
  hero: { alignItems: 'center', gap: space.sm, paddingVertical: space.lg },
  center: { textAlign: 'center' },
  badgeWrap: { width: 132, height: 132, alignItems: 'center', justifyContent: 'center', marginBottom: space.md },
  badge: {
    width: 120,
    height: 120,
    borderRadius: 60,
    alignItems: 'center',
    justifyContent: 'center',
    borderBottomWidth: 6,
    borderBottomColor: 'rgba(0,0,0,0.15)',
  },
  pulse: { position: 'absolute', width: 120, height: 120, borderRadius: 60, borderWidth: 6 },
});
