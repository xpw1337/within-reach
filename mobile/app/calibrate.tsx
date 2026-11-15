// Hidden georeference calibration screen. Opened by a long press on the Home title; not part of the
// alert flow. Records GPS at known scan spots, solves lat/lng -> plan (x, z) for the building, saves it
// on this phone and shows the numbers to paste into lib/georefDefaults.ts. README section 7 has the
// on-site procedure. Nothing here writes to the database.

import { router } from 'expo-router';
import { useEffect, useMemo, useState } from 'react';
import { Platform, Pressable, Share, StyleSheet, Text, View } from 'react-native';

import { FloorPlan } from '../components/FloorPlan';
import { colors, space } from '../components/theme';
import { Body, Button, Card, Field, Label, Notice, Screen, Title } from '../components/ui';
import { buildingLabel, searchBuildings } from '../lib/buildings';
import { loadCalibrationData, referenceSpots, type CalibrationData, type RefSpot } from '../lib/calibration';
import { PLAN_AED, PLAN_AED_SIMULATED } from '../lib/copy';
import { buildFloorGraph, reachableFrom } from '../lib/floorPlan';
import {
  defaultsSnippet,
  fixDistanceM,
  judgeStartFix,
  latLngToPlan,
  localDate,
  MAX_SNAP_DISTANCE_M,
  MAX_START_ACCURACY_M,
  nearestNode,
  solveCalibration,
  type Georef,
  type StartVerdict,
} from '../lib/georef';
import {
  clearDeviceGeoref,
  defaultsKey,
  freshFix,
  loadActiveGeoref,
  loadSpotRecordings,
  RECORD_MS,
  recordSpot,
  saveDeviceGeoref,
  saveSpotRecordings,
  type ActiveGeoref,
  type SpotRecording,
} from '../lib/georefStore';
import { useProfile } from '../lib/profile';
import { errorMessage } from '../lib/supabase';
import type { BuildingRow } from '../lib/types';

/** "Check my position now" waits a little longer than the alert flow does, since nobody is waiting on it. */
const TEST_FIX_TIMEOUT_MS = 8_000;

const f1 = (v: number) => v.toFixed(1);

function shortId(id: string): string {
  return id.length > 8 ? `${id.slice(0, 8)}...` : id;
}

function verdictText(v: StartVerdict, label: (id: string) => string): string {
  if (v.ok) {
    return `GPS start would be used: snapped to ${label(v.sweepId)}, ${f1(v.snapM)} m from the converted point. The alert would say "accurate to about ${Math.round(v.accuracyM)} m".`;
  }
  switch (v.reason) {
    case 'no_accuracy':
      return 'GPS start would NOT be used: the phone reported no accuracy for this fix.';
    case 'poor_accuracy':
      return `GPS start would NOT be used: the phone reports ${Math.round(v.accuracyM ?? 0)} m, worse than the ${MAX_START_ACCURACY_M} m limit.`;
    case 'off_map':
      return `GPS start would NOT be used: the converted point is more than ${MAX_SNAP_DISTANCE_M} m from every usable sweep on the floor.`;
    default:
      return 'GPS start would NOT be used: the floor has no sweeps.';
  }
}

export default function Calibrate() {
  const { profile } = useProfile();
  const [buildingId, setBuildingId] = useState<string | null>(profile?.building_id ?? null);
  const [picking, setPicking] = useState(!profile?.building_id);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<BuildingRow[]>([]);
  const [searchError, setSearchError] = useState<string | null>(null);

  const [data, setData] = useState<CalibrationData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [recordings, setRecordings] = useState<Record<string, SpotRecording>>({});
  const [active, setActive] = useState<ActiveGeoref | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [recording, setRecording] = useState<{ id: string; fixes: number; msLeft: number } | null>(null);
  const [recordError, setRecordError] = useState<string | null>(null);
  const [saveNote, setSaveNote] = useState<string | null>(null);
  const [test, setTest] = useState<{ busy: boolean; text: string | null }>({ busy: false, text: null });

  useEffect(() => {
    if (!picking) return;
    let cancelled = false;
    const timer = setTimeout(() => {
      searchBuildings(query)
        .then((rows) => {
          if (!cancelled) {
            setResults(rows);
            setSearchError(null);
          }
        })
        .catch((error) => !cancelled && setSearchError(errorMessage(error)));
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query, picking]);

  useEffect(() => {
    if (!buildingId) return;
    let cancelled = false;
    Promise.all([loadCalibrationData(buildingId), loadSpotRecordings(buildingId)])
      .then(async ([d, recs]) => {
        const act = await loadActiveGeoref(d.building);
        if (cancelled) return;
        setData(d);
        setRecordings(recs);
        setActive(act);
        setSelected(referenceSpots(d)[0]?.id ?? null);
      })
      .catch((error) => !cancelled && setLoadError(errorMessage(error)));
    return () => {
      cancelled = true;
    };
  }, [buildingId]);

  function chooseBuilding(id: string) {
    setPicking(false);
    if (id === buildingId) return;
    setData(null);
    setLoadError(null);
    setSaveNote(null);
    setRecordError(null);
    setTest({ busy: false, text: null });
    setBuildingId(id);
  }

  const spots = useMemo(() => (data ? referenceSpots(data) : []), [data]);
  const recorded = spots.filter((s) => recordings[s.id]);
  const solve = useMemo(
    () => solveCalibration(spots.filter((s) => recordings[s.id]).map((s) => ({ id: s.id, fix: recordings[s.id], plan: s.plan }))),
    [spots, recordings],
  );
  const solvedGeoref: Georef | null =
    solve && data?.building
      ? { ...solve.transform, calibratedAt: localDate(), spots: recorded.length, rmsM: solve.rmsM }
      : null;
  const key = data?.building ? defaultsKey(data.building) : null;
  const snippet = solvedGeoref && key ? defaultsSnippet(key, solvedGeoref) : null;

  const selectedSpot = spots.find((s) => s.id === selected) ?? spots[0] ?? null;
  const planFloor = selectedSpot?.floor ?? null;
  const graph = useMemo(() => (data && planFloor !== null ? buildFloorGraph(data.nodes, planFloor) : null), [data, planFloor]);
  const spotLabel = (id: string) => {
    const spot = spots.find((s) => s.id === id);
    if (spot) return spot.title;
    const label = data?.nodes.find((n) => n.sweep_id === id)?.label;
    return label ? `"${label}"` : `sweep ${shortId(id)}`;
  };

  async function onRecord(spot: RefSpot) {
    if (!buildingId || recording) return;
    setSelected(spot.id);
    setRecordError(null);
    setRecording({ id: spot.id, fixes: 0, msLeft: RECORD_MS });
    try {
      const rec = await recordSpot((fixes, msLeft) => setRecording({ id: spot.id, fixes, msLeft }));
      const next = { ...recordings, [spot.id]: rec };
      setRecordings(next);
      await saveSpotRecordings(buildingId, next);
    } catch (error) {
      setRecordError(errorMessage(error));
    } finally {
      setRecording(null);
    }
  }

  async function onForget(spot: RefSpot) {
    if (!buildingId) return;
    const next = { ...recordings };
    delete next[spot.id];
    setRecordings(next);
    await saveSpotRecordings(buildingId, next);
  }

  async function onSave() {
    if (!buildingId || !solvedGeoref || !data) return;
    await saveDeviceGeoref(buildingId, solvedGeoref);
    setActive(await loadActiveGeoref(data.building));
    setSaveNote(`Saved on this phone (${solvedGeoref.calibratedAt}). Alerts in this building now try the GPS start.`);
  }

  async function onClear() {
    if (!buildingId || !data) return;
    await clearDeviceGeoref(buildingId);
    setActive(await loadActiveGeoref(data.building));
    setSaveNote('The calibration saved on this phone was removed.');
  }

  async function onTest() {
    if (!data || !active) return;
    setTest({ busy: true, text: null });
    const fix = await freshFix(TEST_FIX_TIMEOUT_MS);
    if (!fix) {
      setTest({ busy: false, text: 'No GPS fix arrived. In an alert this means "Tap the map where you are".' });
      return;
    }
    // Same rule as the alert: the camera's floor, sweeps that can reach the camera's sweep.
    const camera = data.cameras.find((c) => c.sweep_id && data.nodes.some((n) => n.sweep_id === c.sweep_id)) ?? null;
    const camNode = camera ? data.nodes.find((n) => n.sweep_id === camera.sweep_id) : undefined;
    const floor = camera?.floor ?? camNode?.floor ?? selectedSpot?.floor ?? 0;
    const g = buildFloorGraph(data.nodes, floor);
    const reach = camNode ? reachableFrom(g, camNode.sweep_id) : new Set(g.nodes.keys());
    const verdict = judgeStartFix(active.georef, fix, [...g.nodes.values()], (id) => reach.has(id));
    const p = latLngToPlan(active.georef, fix);
    const near = nearestNode(g.nodes.values(), p);
    const lines = [
      `Phone accuracy: ${fix.accuracyM != null ? `${Math.round(fix.accuracyM)} m` : 'not reported'}.`,
      `Converted to plan x ${f1(p.x)}, z ${f1(p.z)} on floor ${floor}.`,
      near ? `Nearest sweep: ${spotLabel(near.node.id)}, ${f1(near.distanceM)} m away.` : 'No sweeps on this floor.',
      verdictText(verdict, spotLabel),
    ];
    setTest({ busy: false, text: lines.join('\n') });
  }

  const aedOnFloor = data && planFloor !== null ? spots.find((s) => s.kind === 'aed' && s.floor === planFloor) : undefined;
  const personOnFloor = data && planFloor !== null ? spots.find((s) => s.kind === 'patient' && s.floor === planFloor) : undefined;
  const aedSimulated = (data?.aeds ?? []).some((a) => (a.flags ?? []).includes('simulated'));

  return (
    <Screen>
      <Title>Georeference calibration</Title>
      <Body muted>
        Setup screen for the team, not part of the alert flow. Stand on each spot, record it, then save. Nothing here is written to
        the database; the result is saved on this phone only.
      </Body>

      <Card>
        <Label>Building</Label>
        <Body>{data?.building ? buildingLabel(data.building) : buildingId ? 'Loading...' : 'None chosen'}</Body>
        {picking ? (
          <>
            <Field label="Search buildings" value={query} onChangeText={setQuery} placeholder="Name or address" autoCorrect={false} />
            {searchError ? <Notice tone="error">Could not load buildings: {searchError}</Notice> : null}
            {results.map((b) => (
              <Button
                key={b.id}
                title={buildingLabel(b)}
                kind="secondary"
                onPress={() => chooseBuilding(b.id)}
              />
            ))}
          </>
        ) : (
          <Button title="Change building" kind="secondary" onPress={() => setPicking(true)} />
        )}
        {loadError ? <Notice tone="error">Could not load the building: {loadError}</Notice> : null}
      </Card>

      {data && spots.length === 0 ? <Notice>This building has no camera, AED or labeled sweep to stand on.</Notice> : null}

      {graph && selectedSpot ? (
        <Card>
          <Label>Where to stand</Label>
          <Body muted>The blue dot is the selected spot: stand where the scanner stood for that sweep, phone held still at chest height.</Body>
          <FloorPlan
            graph={graph}
            person={personOnFloor ? personOnFloor.plan : null}
            aed={aedOnFloor ? aedOnFloor.plan : null}
            aedLabel={aedSimulated ? PLAN_AED_SIMULATED : PLAN_AED}
            activeRoute={null}
            laterRoute={null}
            helper={selectedSpot.plan}
          />
        </Card>
      ) : null}

      {recordError ? <Notice tone="error">{recordError}</Notice> : null}

      {spots.map((spot) => {
        const rec = recordings[spot.id];
        const res = solve?.residuals.find((r) => r.id === spot.id);
        const busyHere = recording?.id === spot.id;
        return (
          <Card key={spot.id} style={spot.id === selectedSpot?.id ? styles.selected : undefined}>
            <Pressable accessibilityRole="button" onPress={() => setSelected(spot.id)}>
              <Text style={styles.spotTitle}>{spot.title}</Text>
              <Text style={styles.small}>
                Floor {spot.floor}, sweep {shortId(spot.id)}, plan x {f1(spot.plan.x)} z {f1(spot.plan.z)}
              </Text>
            </Pressable>
            {rec ? (
              <Text style={styles.small}>
                Recorded {new Date(rec.recordedAt).toLocaleString()}: {rec.fixes} fixes, phone accuracy{' '}
                {rec.accuracyM != null ? `about ${Math.round(rec.accuracyM)} m` : 'not reported'}.
              </Text>
            ) : (
              <Text style={styles.small}>Not recorded yet.</Text>
            )}
            {res ? <Text style={styles.residual}>Residual after the fit: {f1(res.errorM)} m</Text> : null}
            {busyHere && recording ? (
              <Body>
                Stand still... {Math.ceil(recording.msLeft / 1000)} s left, {recording.fixes} fixes so far.
              </Body>
            ) : null}
            <View style={styles.row}>
              <View style={styles.flex}>
                <Button
                  title={rec ? 'Record again' : 'Record here'}
                  onPress={() => void onRecord(spot)}
                  busy={busyHere}
                  disabled={recording !== null && !busyHere}
                />
              </View>
              {rec ? (
                <View style={styles.flex}>
                  <Button title="Forget" kind="secondary" onPress={() => void onForget(spot)} disabled={recording !== null} />
                </View>
              ) : null}
            </View>
          </Card>
        );
      })}

      {data ? (
        <Card>
          <Label>Result</Label>
          {!solve ? (
            <Body muted>
              {recorded.length < 2 ? 'Record at least two spots to solve.' : 'These fixes cannot be solved (they are all in one place).'}
            </Body>
          ) : (
            <>
              <Body>
                Rotation {solve.transform.rotationDeg.toFixed(2)} degrees, translation x {solve.transform.tx.toFixed(2)} m, z{' '}
                {solve.transform.tz.toFixed(2)} m, from {recorded.length} spots.
              </Body>
              <Body>Residuals: RMS {f1(solve.rmsM)} m (per spot above).</Body>
              {recorded.length === 2 ? (
                <Body muted>
                  With two spots the fit always passes through the middle of both, so each residual is half the gap between the GPS
                  distance and the scan distance. It does not show how wrong the rotation is. Add a third spot to check that.
                </Body>
              ) : null}
              {recorded.map((a, i) =>
                recorded.slice(i + 1).map((b) => (
                  <Text key={`${a.id}-${b.id}`} style={styles.small}>
                    {a.title} to {b.title}: GPS {f1(fixDistanceM(recordings[a.id], recordings[b.id]))} m, scan{' '}
                    {f1(Math.hypot(a.plan.x - b.plan.x, a.plan.z - b.plan.z))} m
                  </Text>
                )),
              )}
              {solve.mirroredRmsM !== null ? (
                <Text style={styles.small}>
                  Mirror check: the same fit with the plan flipped has RMS {f1(solve.mirroredRmsM)} m. If that is much smaller than{' '}
                  {f1(solve.rmsM)} m, stop and tell the team: the spots or the axis convention are wrong.
                </Text>
              ) : null}
              <Button title="Save on this phone" onPress={() => void onSave()} />
              {snippet ? (
                <>
                  <Label>For lib/georefDefaults.ts</Label>
                  <Text selectable style={styles.code}>
                    {snippet}
                  </Text>
                  <Button title="Share these numbers" kind="secondary" onPress={() => void Share.share({ message: snippet })} />
                </>
              ) : null}
            </>
          )}
          {saveNote ? <Notice tone="info">{saveNote}</Notice> : null}
        </Card>
      ) : null}

      {data ? (
        <Card>
          <Label>In use for alerts</Label>
          {active ? (
            <Body>
              {active.source === 'device' ? 'Saved on this phone' : 'Committed default (lib/georefDefaults.ts)'}, calibrated{' '}
              {active.georef.calibratedAt} from {active.georef.spots} spots, RMS {f1(active.georef.rmsM)} m.
            </Body>
          ) : (
            <Body muted>{'None. Alerts in this building use "Tap the map where you are" or the simulated start.'}</Body>
          )}
          {active?.source === 'device' ? <Button title="Remove the calibration saved on this phone" kind="secondary" onPress={() => void onClear()} /> : null}
          <Button title="Check my position now" kind="secondary" onPress={() => void onTest()} busy={test.busy} disabled={!active} />
          {test.text ? <Text style={styles.small}>{test.text}</Text> : null}
        </Card>
      ) : null}

      <Button title="Back" kind="secondary" onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  row: { flexDirection: 'row', gap: space.md },
  selected: { borderColor: colors.info, borderWidth: 2 },
  spotTitle: { fontSize: 17, fontWeight: '700', color: colors.text },
  small: { fontSize: 13, lineHeight: 18, color: colors.muted },
  residual: { fontSize: 15, fontWeight: '700', color: colors.text },
  code: { fontFamily: Platform.select({ ios: 'Courier', default: 'monospace' }), fontSize: 12, color: colors.text, backgroundColor: '#F1F5F9', padding: space.sm },
});
