import * as WebBrowser from 'expo-web-browser';
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { IncidentMap } from '../../components/IncidentMap';
import { colors, space } from '../../components/theme';
import { Body, Button, Card, Label, Notice, Screen } from '../../components/ui';
import { stopAlarm } from '../../lib/alarm';
import { incidentPoint, loadAlertContext, type AlertContext } from '../../lib/alertData';
import { acceptDispatch, arrivedDispatch, declineDispatch } from '../../lib/api';
import { DISPATCH_ROLE_HELP, DISPATCH_ROLE_TITLES, INCIDENT_TITLE, INCIDENT_TYPE_LABELS } from '../../lib/copy';
import { env } from '../../lib/env';
import { distanceMeters, useLocationState } from '../../lib/location';
import { useProfile } from '../../lib/profile';
import { errorMessage } from '../../lib/supabase';
import { adoptDispatch, closeAlert, patchDispatch, secondsLeft, useAlertState } from '../../lib/useDispatches';

function formatDistance(m: number): string {
  return m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`;
}

function goHome() {
  if (router.canDismiss()) router.dismissTo('/');
  else router.replace('/');
}

export default function AlertScreen() {
  const { dispatchId } = useLocalSearchParams<{ dispatchId: string }>();
  const { profile } = useProfile();
  const { dispatch } = useAlertState();
  const location = useLocationState();
  const d = dispatch && dispatch.id === dispatchId ? dispatch : null;

  const [ctx, setCtx] = useState<AlertContext | null>(null);
  const [ctxError, setCtxError] = useState<string | null>(null);
  const [busy, setBusy] = useState<'accept' | 'decline' | 'arrive' | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [missing, setMissing] = useState(false);

  // Opened without the store knowing this dispatch (deep link, restart): load it.
  useEffect(() => {
    if (d || !dispatchId || !profile) return;
    let cancelled = false;
    adoptDispatch(dispatchId, profile.id).then((row) => {
      if (!cancelled && !row) setMissing(true);
    });
    return () => {
      cancelled = true;
    };
  }, [d, dispatchId, profile]);

  const incidentId = d?.incident_id ?? null;
  useEffect(() => {
    if (!incidentId) return;
    let cancelled = false;
    loadAlertContext(incidentId)
      .then((value) => !cancelled && setCtx(value))
      .catch((error) => !cancelled && setCtxError(errorMessage(error)));
    return () => {
      cancelled = true;
    };
  }, [incidentId]);

  const waiting = d?.status === 'sent';
  useEffect(() => {
    if (!waiting) return;
    const timer = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(timer);
  }, [waiting]);

  const left = d && waiting ? secondsLeft(d, now) : null;
  // Countdown over: close the screen. The agent marks the timeout on its side.
  useEffect(() => {
    if (left === 0 && busy === null) {
      closeAlert();
      goHome();
    }
  }, [left, busy]);

  async function onAccept() {
    if (!d) return;
    stopAlarm();
    setBusy('accept');
    setActionError(null);
    try {
      const res = await acceptDispatch(d.id);
      patchDispatch(d.id, { status: res.status ?? 'accepted', ...(res.role ? { role: res.role } : {}) });
    } catch (error) {
      setActionError(errorMessage(error));
    } finally {
      setBusy(null);
    }
  }

  async function onDecline() {
    if (!d) return;
    const id = d.id;
    setBusy('decline');
    closeAlert();
    goHome();
    // If this fails the agent times the dispatch out after 20 s, which has the same effect.
    await declineDispatch(id).catch(() => {});
  }

  async function onArrived() {
    if (!d) return;
    setBusy('arrive');
    setActionError(null);
    try {
      const res = await arrivedDispatch(d.id, d.role === 'aed_runner');
      patchDispatch(d.id, { status: res.status ?? 'arrived' });
    } catch (error) {
      setActionError(errorMessage(error));
    } finally {
      setBusy(null);
    }
  }

  if (!d) {
    return (
      <Screen>
        <Body>{missing ? 'This alert is no longer active.' : 'Loading alert...'}</Body>
        <Button title="Back to home" kind="secondary" onPress={goHome} />
      </Screen>
    );
  }

  const incident = ctx?.incident ?? null;
  const camera = ctx?.camera ?? null;
  const building = ctx?.building ?? null;
  const aedRoute = ctx?.routes.find((r) => r.target === 'aed') ?? null;
  const point = incidentPoint(ctx);
  const distance = point && location.coords ? distanceMeters(location.coords, point) : null;
  const buildingId = building?.id ?? incident?.building_id ?? camera?.building_id ?? null;
  const routeUrl = env.dashboardUrl && buildingId ? `${env.dashboardUrl}/building/${encodeURIComponent(buildingId)}` : null;

  const where = [
    camera?.landmark ? `By ${camera.landmark}` : null,
    camera?.floor != null ? `floor ${camera.floor}` : null,
    building?.name ?? null,
    building?.address ?? null,
  ]
    .filter(Boolean)
    .join(', ');

  return (
    <Screen background={waiting ? colors.alertBg : colors.bg}>
      <View style={styles.header}>
        <Text style={[styles.title, waiting && styles.onAlert]}>{INCIDENT_TITLE}</Text>
        {incident ? (
          <Text style={[styles.subtitle, waiting && styles.onAlert]}>
            {INCIDENT_TYPE_LABELS[incident.type]}
            {incident.witnessed ? ', witnessed collapse' : ''}
          </Text>
        ) : null}
        {left !== null ? (
          <Text style={[styles.countdown, styles.onAlert]} accessibilityLabel={`${Math.ceil(left)} seconds left to answer`}>
            {Math.ceil(left)}
          </Text>
        ) : null}
      </View>

      {ctxError ? <Notice tone="error">Could not load the incident details: {ctxError}</Notice> : null}

      {d.status === 'accepted' || d.status === 'arrived' ? (
        <Card>
          <Label>Your role</Label>
          <Text style={styles.role}>{d.role ? DISPATCH_ROLE_TITLES[d.role] : 'Accepted'}</Text>
          {d.role ? <Body>{DISPATCH_ROLE_HELP[d.role]}</Body> : <Body muted>Waiting for your role.</Body>}
        </Card>
      ) : null}

      <Card>
        <Label>Where</Label>
        <Body>{where || '--'}</Body>
        <Body muted>Distance from you: {distance !== null ? formatDistance(distance) : '--'}</Body>
        {point ? <IncidentMap target={point} title={INCIDENT_TITLE} me={location.coords} /> : null}
        <Button
          title="View route in 3D"
          kind="secondary"
          disabled={!routeUrl}
          onPress={() => routeUrl && void WebBrowser.openBrowserAsync(routeUrl)}
        />
      </Card>

      {d.role === 'aed_runner' || d.status === 'sent' ? (
        <Card>
          <Label>AED</Label>
          {aedRoute ? (
            <>
              <Body>{aedRoute.directions ?? '--'}</Body>
              <Body muted>
                From the person: {aedRoute.distance_m != null ? `${Math.round(aedRoute.distance_m)} meters` : '--'}
              </Body>
            </>
          ) : (
            <Body muted>No AED route is mapped for this spot.</Body>
          )}
        </Card>
      ) : null}

      {actionError ? <Notice tone="error">{actionError}</Notice> : null}

      {d.status === 'sent' ? (
        <View style={styles.actions}>
          <Button title="Accept" kind="ok" big onPress={onAccept} busy={busy === 'accept'} disabled={busy !== null} />
          <Button title="Can't help" kind="secondary" onPress={onDecline} disabled={busy !== null} />
        </View>
      ) : null}

      {d.status === 'accepted' ? (
        <Button
          title={d.role === 'aed_runner' ? 'AED here' : "I'm here"}
          kind="primary"
          big
          onPress={onArrived}
          busy={busy === 'arrive'}
        />
      ) : null}

      {d.status === 'arrived' ? (
        <>
          <Notice tone="info">You are marked as arrived.</Notice>
          <Button
            title="Done"
            kind="secondary"
            onPress={() => {
              closeAlert();
              goHome();
            }}
          />
        </>
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  header: { gap: space.xs, alignItems: 'center', paddingVertical: space.md },
  title: { fontSize: 34, fontWeight: '800', color: colors.text },
  subtitle: { fontSize: 18, color: colors.muted, textAlign: 'center' },
  onAlert: { color: colors.alertText },
  countdown: { fontSize: 64, fontWeight: '800', fontVariant: ['tabular-nums'] },
  role: { fontSize: 24, fontWeight: '800', color: colors.text },
  actions: { gap: space.md },
});
