import { router } from 'expo-router';
import { useState } from 'react';
import { Linking } from 'react-native';

import { Body, Button, Card, Label, Notice, Screen, Title, ToggleRow } from '../components/ui';
import { CONSENT_LOCATION_HELP, PRIVACY_LINE, RESPONDER_ROLE_LABELS } from '../lib/copy';
import { missingEnv } from '../lib/env';
import { useLocationState } from '../lib/location';
import { setOnDuty, useProfile } from '../lib/profile';
import { errorMessage } from '../lib/supabase';
import { isOpen, useAlertState, type RealtimeStatus } from '../lib/useDispatches';

const REALTIME_LINES: Record<RealtimeStatus, string> = {
  connected: 'Connected. Keep the app open to be alerted.',
  connecting: 'Connecting...',
  error: 'Connection problem. Reopen the app to retry.',
  off: 'Not connected.',
};

function formatTime(iso: string | null): string {
  return iso ? new Date(iso).toLocaleTimeString() : '--';
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

  let locationLine: string;
  if (!profile.consent_location) locationLine = 'Off: you have not agreed to share your location.';
  else if (!profile.on_duty) locationLine = 'Off while you are off duty.';
  else if (location.status === 'requesting') locationLine = 'Asking for permission...';
  else if (location.status === 'denied') locationLine = 'Permission denied. Allow location for Expo Go in Settings.';
  else if (location.status === 'watching') locationLine = `Sharing. Last update ${formatTime(location.lastWriteAt)}.`;
  else if (location.status === 'error') locationLine = 'Location is unavailable on this phone right now.';
  else locationLine = 'Off.';

  return (
    <Screen>
      <Title>Within Reach</Title>

      {missing.length > 0 ? <Notice tone="error">Missing settings in this build: {missing.join(', ')}.</Notice> : null}

      <Card>
        <ToggleRow
          label={profile.on_duty ? 'On duty' : 'Off duty'}
          help={profile.on_duty ? 'You can be alerted while this app is open.' : 'You will not be alerted.'}
          value={profile.on_duty}
          onValueChange={onToggleDuty}
          disabled={savingDuty}
        />
        {dutyError ? <Notice tone="error">Could not change duty status: {dutyError}</Notice> : null}
      </Card>

      {alert.dispatch && isOpen(alert.dispatch) ? (
        <Button
          title="Open the current alert"
          big
          onPress={() => router.push({ pathname: '/alert/[dispatchId]', params: { dispatchId: alert.dispatch!.id } })}
        />
      ) : null}

      <Card>
        <Label>Alerts</Label>
        <Body>{REALTIME_LINES[alert.realtime]}</Body>
        {alert.realtimeError ? <Body muted>{alert.realtimeError}</Body> : null}
      </Card>

      <Card>
        <Label>Location</Label>
        <Body>{locationLine}</Body>
        {!profile.consent_location ? <Body muted>{CONSENT_LOCATION_HELP}</Body> : null}
        {location.status === 'denied' ? (
          <Button title="Open Settings" kind="secondary" onPress={() => void Linking.openSettings()} />
        ) : null}
        {location.error ? <Notice tone="error">{location.error}</Notice> : null}
      </Card>

      <Card>
        <Label>Responder</Label>
        <Body>{profile.name}</Body>
        <Body muted>
          {RESPONDER_ROLE_LABELS[profile.role]}
          {profile.cpr_trained ? ', CPR trained' : ''}
          {profile.building_label ? `, ${profile.building_label}` : ''}
        </Body>
      </Card>

      <Button title="CPR guide" kind="secondary" onPress={() => router.push('/cpr')} />
      <Button title="Edit profile" kind="secondary" onPress={() => router.push('/onboarding')} />
      <Body muted>{PRIVACY_LINE}</Body>
    </Screen>
  );
}
