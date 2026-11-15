import * as WebBrowser from 'expo-web-browser';
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useMemo, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { FloorPlan, WalkingFloorPlan } from '../../components/FloorPlan';
import { IncidentMap } from '../../components/IncidentMap';
import { colors, space } from '../../components/theme';
import { Body, Button, Card, Label, Notice, Screen } from '../../components/ui';
import { openAedHelp } from '../../lib/aedHelp';
import { stopAlarm } from '../../lib/alarm';
import { incidentPoint, loadAlertContext, type AlertContext } from '../../lib/alertData';
import { acceptDispatch, arrivedDispatch, declineDispatch, postMilestone, quietly } from '../../lib/api';
import {
  AED_HELP_BUTTON,
  ALERT_ACCEPT,
  ALERT_ACCEPTED,
  ALERT_ARRIVED,
  ALERT_BACK_HOME,
  ALERT_DECLINE,
  ALERT_DISTANCE_FROM_YOU,
  ALERT_DONE,
  ALERT_FROM_PERSON,
  ALERT_GONE,
  ALERT_LOADING,
  ALERT_LOAD_ERROR,
  ALERT_VIEW_3D,
  ALERT_WAITING_ROLE,
  ALERT_WHERE,
  ALERT_YOUR_ROLE,
  BUTTON_HAVE_AED,
  BUTTON_IM_HERE,
  BUTTON_WITH_PERSON,
  CPR_GUIDE,
  DISPATCH_ROLE_HELP,
  DISPATCH_ROLE_TITLES,
  INCIDENT_TITLE,
  INCIDENT_TYPE_LABELS,
  PLAN_AED,
  PLAN_AED_OTHER_FLOOR,
  PLAN_AED_SIMULATED,
  PLAN_LOCATING,
  PLAN_NO_AED_ROUTE,
  PLAN_START_GPS,
  PLAN_START_TAPPED,
  PLAN_TAP_PROMPT,
  STEP_BRING_AED,
  STEP_GET_AED,
  STEP_GO_TO_PERSON,
  STEP_WITH_PERSON,
} from '../../lib/copy';
import { env } from '../../lib/env';
import { buildAlertPlan, legFromStart } from '../../lib/floorPlan';
import { loadActiveGeoref, type ActiveGeoref } from '../../lib/georefStore';
import { distanceMeters, useLocationState } from '../../lib/location';
import { useProfile } from '../../lib/profile';
import { errorMessage } from '../../lib/supabase';
import { adoptDispatch, closeAlert, patchDispatch, secondsLeft, useAlertState } from '../../lib/useDispatches';
import { useHelperStart } from '../../lib/useHelperStart';

function formatDistance(m: number): string {
  return m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`;
}

function goHome() {
  if (router.canDismiss()) router.dismissTo('/');
  else router.replace('/');
}

/** Where the helper is in the flow after accepting. The buttons, not the helper dot, move it on. */
type Leg = 'to_aed' | 'to_person' | 'with_person';

export default function AlertScreen() {
  const { dispatchId } = useLocalSearchParams<{ dispatchId: string }>();
  const { profile } = useProfile();
  const { dispatch } = useAlertState();
  const location = useLocationState();
  const d = dispatch && dispatch.id === dispatchId ? dispatch : null;

  const [ctx, setCtx] = useState<AlertContext | null>(null);
  const [ctxError, setCtxError] = useState<string | null>(null);
  const [busy, setBusy] = useState<'accept' | 'decline' | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [missing, setMissing] = useState(false);
  /** AED runner only: set by "I have the AED". */
  const [hasAed, setHasAed] = useState(false);
  /** Set by "I'm with the person" right away, before (and whether or not) the server answers. */
  const [withPerson, setWithPerson] = useState(false);

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

  const plan = useMemo(() => buildAlertPlan(ctx), [ctx]);

  // The building's georeference calibration (phone first, then lib/georefDefaults.ts), for the GPS start.
  const [georef, setGeoref] = useState<{ buildingId: string; active: ActiveGeoref | null } | null>(null);
  const ctxBuilding = ctx?.building ?? null;
  useEffect(() => {
    if (!ctxBuilding) return;
    let cancelled = false;
    void loadActiveGeoref(ctxBuilding).then((active) => {
      if (!cancelled) setGeoref({ buildingId: ctxBuilding.id, active });
    });
    return () => {
      cancelled = true;
    };
  }, [ctxBuilding]);

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

  function onHaveAed() {
    setHasAed(true);
    if (d?.incident_id && profile) {
      const id = d.incident_id;
      const by = profile.id;
      void quietly(() => postMilestone(id, 'aed_picked_up', by));
    }
  }

  /** "I'm with the person" (AED runner) and "I'm here" (everyone else). Never blocks on the server. */
  function onArrived() {
    if (!d) return;
    const id = d.id;
    const runner = d.role === 'aed_runner';
    setWithPerson(true);
    void quietly(() => arrivedDispatch(id, runner)).then((res) => {
      if (res) patchDispatch(id, { status: res.status ?? 'arrived' });
    });
    // The runner stays here for the AED help button; everyone else goes to the CPR guide.
    if (!runner) router.replace({ pathname: '/cpr', params: { incidentId: d.incident_id ?? '', live: '1' } });
  }

  // The first leg (start -> AED for the runner, start -> person for everyone else) gets its start from
  // GPS, a tap, or the simulated start (lib/useHelperStart.ts). Hooks run before the early return.
  // The helper dot is drawn only when the plan has an AED on this floor (`simulate`), and then the
  // runner always has an AED leg, so the first leg is: runner before "I have the AED", or anyone else
  // before "I'm here".
  const simulate = Boolean(plan && plan.aed !== null && plan.startToAed !== null);
  const isRunner = d?.role === 'aed_runner';
  const onFirstLeg = simulate && d?.status === 'accepted' && Boolean(d.role) && !withPerson && (isRunner ? !hasAed : true);
  const helperStart = useHelperStart({
    plan,
    firstLeg: onFirstLeg,
    target: isRunner ? 'aed' : 'person',
    georef: georef?.active?.georef ?? null,
    georefReady: Boolean(ctx && (!ctx.building || georef?.buildingId === ctx.building.id)),
    locationGranted: location.status === 'watching',
  });

  if (!d) {
    return (
      <Screen>
        <Body>{missing ? ALERT_GONE : ALERT_LOADING}</Body>
        <Button title={ALERT_BACK_HOME} kind="secondary" onPress={goHome} />
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

  const runner = d.role === 'aed_runner';
  const arrived = d.status === 'arrived' || withPerson;
  const accepted = d.status === 'accepted' || arrived;
  // AED steps only when an AED route is mapped. Before the twin loads, fall back to the route row.
  const aedMapped = plan ? plan.hasAedRoute : Boolean(aedRoute && ctx?.aed);
  let leg: Leg | null = null;
  if (arrived) leg = 'with_person';
  else if (d.status === 'accepted' && d.role) leg = runner && aedMapped && !hasAed ? 'to_aed' : 'to_person';

  // "View route in 3D": the dashboard's responder route page (dashboard/app/building/[id]/route), with
  // this helper's leg, role and start sweep so the 3D walk matches the plan below.
  const startSweep = helperStart.start.phase === 'done' ? helperStart.start.sweepId : null;
  const routeQuery = [
    camera?.id ? `camera=${encodeURIComponent(camera.id)}` : null,
    leg === 'to_aed' || leg === 'to_person' ? `leg=${leg}` : null,
    d.role ? `role=${encodeURIComponent(d.role)}` : null,
    startSweep && (leg === 'to_aed' || (leg === 'to_person' && !runner)) ? `from=${encodeURIComponent(startSweep)}` : null,
  ]
    .filter(Boolean)
    .join('&');
  const routeUrl =
    env.dashboardUrl && buildingId
      ? `${env.dashboardUrl}/building/${encodeURIComponent(buildingId)}/route${routeQuery ? `?${routeQuery}` : ''}`
      : null;

  const aedLabel = plan?.aedSimulated || (ctx?.aed?.flags ?? []).includes('simulated') ? PLAN_AED_SIMULATED : PLAN_AED;
  const stepTitle =
    leg === 'to_aed' ? STEP_GET_AED : leg === 'to_person' ? (runner && aedMapped ? STEP_BRING_AED : STEP_GO_TO_PERSON) : leg === 'with_person' ? STEP_WITH_PERSON : null;

  const where = [
    camera?.landmark ? `By ${camera.landmark}` : null,
    camera?.floor != null ? `floor ${camera.floor}` : null,
    building?.name ?? null,
    building?.address ?? null,
  ]
    .filter(Boolean)
    .join(', ');

  // The indoor plan. A new key per leg restarts the walk from the leg's first point and decides again
  // between step tracking and the timed walk (components/FloorPlan.tsx, lib/useStepWalk.ts). The first
  // leg mounts only once its start is set, so the dot never jumps from the simulated start to GPS.
  let planView = null;
  if (plan) {
    const common = { graph: plan.graph, person: plan.person, aed: plan.aed, aedLabel };
    const isFirstLeg = leg === 'to_aed' || (!runner && leg === 'to_person');
    const s = helperStart.start;
    if (!simulate || leg === null) {
      planView = <FloorPlan {...common} activeRoute={null} laterRoute={plan.aedToPerson} helper={null} />;
    } else if (isFirstLeg && s.phase !== 'done') {
      // Still choosing the start: no dot yet; the buttons below work as always.
      const prompt = s.phase === 'tap' ? PLAN_TAP_PROMPT : s.phase === 'locating' ? PLAN_LOCATING : null;
      planView = (
        <FloorPlan
          {...common}
          activeRoute={null}
          laterRoute={runner ? plan.aedToPerson : null}
          helper={null}
          prompt={prompt}
          onTapPlan={helperStart.onTapPlan}
        />
      );
    } else if (isFirstLeg) {
      const target = leg === 'to_aed' ? 'aed' : 'person';
      const done = s.phase === 'done' ? s : null;
      const chosen = done?.sweepId ? legFromStart(plan, done.sweepId, target) : null;
      const route = chosen ?? (target === 'aed' ? plan.startToAed : plan.startToPerson);
      const source = chosen && done ? done.source : 'default';
      let startNote: string | null = null;
      if (source === 'gps' && done?.accuracyM != null) startNote = PLAN_START_GPS(Math.round(done.accuracyM));
      else if (source === 'tap') startNote = PLAN_START_TAPPED;
      const key = `${leg}:${source}:${chosen ? done?.sweepId : 'default'}`;
      planView = (
        <WalkingFloorPlan
          key={key}
          {...common}
          walkRoute={route}
          standAt={null}
          laterRoute={target === 'aed' ? plan.aedToPerson : null}
          startNote={startNote}
        />
      );
    } else if (leg === 'to_person') {
      // AED runner, second leg: AED -> person, unchanged.
      planView = <WalkingFloorPlan key="aed_to_person" {...common} walkRoute={plan.aedToPerson} standAt={null} laterRoute={null} />;
    } else {
      planView = <WalkingFloorPlan key="with_person" {...common} walkRoute={null} standAt={plan.person} laterRoute={null} />;
    }
  }

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

      {ctxError ? (
        <Notice tone="error">
          {ALERT_LOAD_ERROR} {ctxError}
        </Notice>
      ) : null}

      {accepted ? (
        <Card>
          <Label>{ALERT_YOUR_ROLE}</Label>
          <Text style={styles.role}>{d.role ? DISPATCH_ROLE_TITLES[d.role] : ALERT_ACCEPTED}</Text>
          {d.role ? <Body>{DISPATCH_ROLE_HELP[d.role]}</Body> : <Body muted>{ALERT_WAITING_ROLE}</Body>}
        </Card>
      ) : null}

      {stepTitle ? <Text style={styles.step}>{stepTitle}</Text> : null}

      <Card>
        <Label>{ALERT_WHERE}</Label>
        <Body>{where || '--'}</Body>
        {plan ? (
          <>
            {planView}
            {!plan.hasAedRoute ? <Notice tone="info">{PLAN_NO_AED_ROUTE}</Notice> : null}
            {plan.aedOffFloor ? <Notice tone="info">{PLAN_AED_OTHER_FLOOR}</Notice> : null}
          </>
        ) : (
          <>
            {/* No twin for this building: the outdoor map, as before. */}
            <Body muted>
              {ALERT_DISTANCE_FROM_YOU} {distance !== null ? formatDistance(distance) : '--'}
            </Body>
            {point ? <IncidentMap target={point} title={INCIDENT_TITLE} me={location.coords} /> : null}
          </>
        )}
        <Button
          title={ALERT_VIEW_3D}
          kind="secondary"
          disabled={!routeUrl}
          onPress={() => routeUrl && void WebBrowser.openBrowserAsync(routeUrl)}
        />
      </Card>

      {/* With the indoor plan, a missing AED route is already noted on the plan. */}
      {(runner || d.status === 'sent') && (aedMapped || !plan) ? (
        <Card>
          <Label>{aedLabel}</Label>
          {aedRoute && aedMapped ? (
            <>
              <Body>{aedRoute.directions ?? '--'}</Body>
              {ctx?.aed?.label ? <Body muted>{ctx.aed.label}</Body> : null}
              <Body muted>
                {ALERT_FROM_PERSON} {aedRoute.distance_m != null ? `${spokenMeters(aedRoute.distance_m)} meters` : '--'}
              </Body>
            </>
          ) : (
            <Body muted>{PLAN_NO_AED_ROUTE}</Body>
          )}
        </Card>
      ) : null}

      {actionError ? <Notice tone="error">{actionError}</Notice> : null}

      {d.status === 'sent' ? (
        <View style={styles.actions}>
          <Button title={ALERT_ACCEPT} kind="ok" big onPress={onAccept} busy={busy === 'accept'} disabled={busy !== null} />
          <Button title={ALERT_DECLINE} kind="secondary" onPress={onDecline} disabled={busy !== null} />
        </View>
      ) : null}

      {leg === 'to_aed' ? <Button title={BUTTON_HAVE_AED} kind="primary" big onPress={onHaveAed} /> : null}

      {leg === 'to_person' ? (
        <Button title={runner ? BUTTON_WITH_PERSON : BUTTON_IM_HERE} kind="primary" big onPress={onArrived} />
      ) : null}

      {/* Accepted, role not known yet (it comes with the accept answer or a Realtime update). */}
      {d.status === 'accepted' && !d.role && !arrived ? <Button title={BUTTON_IM_HERE} kind="primary" big onPress={onArrived} /> : null}

      {arrived ? (
        <>
          <Notice tone="info">{ALERT_ARRIVED}</Notice>
          {runner ? (
            <>
              <Button title={AED_HELP_BUTTON} kind="primary" big onPress={() => openAedHelp(d.incident_id, profile?.id, 'alert')} />
              <Button
                title={CPR_GUIDE}
                kind="secondary"
                onPress={() => router.push({ pathname: '/cpr', params: { incidentId: d.incident_id ?? '', live: '1' } })}
              />
            </>
          ) : (
            <>
              <Button
                title={CPR_GUIDE}
                big
                onPress={() => router.push({ pathname: '/cpr', params: { incidentId: d.incident_id ?? '', live: '1' } })}
              />
              <Button title={AED_HELP_BUTTON} kind="secondary" onPress={() => openAedHelp(d.incident_id, profile?.id, 'alert')} />
            </>
          )}
          <Button
            title={ALERT_DONE}
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
  step: { fontSize: 26, fontWeight: '800', color: colors.text, textAlign: 'center' },
  actions: { gap: space.md },
});

/** Whole meters rounded like the speaker (Python's round: halves go to the even number), so the
 * screen and the spoken "{n} meters" never differ by one. */
function spokenMeters(meters: number): number {
  const floor = Math.floor(meters);
  if (Math.abs(meters - floor - 0.5) < 1e-9) return floor % 2 === 0 ? floor : floor + 1;
  return Math.round(meters);
}
