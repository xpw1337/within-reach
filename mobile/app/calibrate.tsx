// Hidden GPS calibration screen. Opened by a long press on the Home title; not part of the alert
// flow. It walks one person through the building's reference spots one at a time ("Spot 2 of 4"):
// which spot, where it is on the plan (and where GPS puts you, when a calibration is already in use),
// whether GPS is good enough, and one button to press. It then solves lat/lng -> plan (x, z), saves it
// on this phone on request and offers the numbers for lib/georefDefaults.ts. README section 7 has the
// on-site procedure. Nothing here writes to the database. All wording is in lib/copy.ts.

import * as Haptics from 'expo-haptics';
import { router } from 'expo-router';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  BackHandler,
  Platform,
  Pressable,
  ScrollView,
  Share,
  StyleSheet,
  Text,
  View,
  type DimensionValue,
  type ScrollViewInstance,
} from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';

import { CalibrationPlan, type PlanSpot } from '../components/CalibrationPlan';
import { colors, space } from '../components/theme';
import { Body, Button, Card, Field, Label, Notice, Title } from '../components/ui';
import { buildingLabel, searchBuildings } from '../lib/buildings';
import { loadCalibrationData, referenceSpots, type CalibrationData, type RefSpot } from '../lib/calibration';
import {
  CAL_ALL_SPOTS,
  CAL_BACK,
  CAL_BEFORE_LINES,
  CAL_BEFORE_TITLE,
  CAL_BUILDING,
  CAL_BUILDING_CHANGE,
  CAL_BUILDING_LOAD_ERROR,
  CAL_BUILDING_LOADING,
  CAL_BUILDING_NONE,
  CAL_BUILDING_PLACEHOLDER,
  CAL_BUILDING_SEARCH,
  CAL_BUILDING_SEARCH_ERROR,
  CAL_CHECK,
  CAL_CHECK_HELP,
  CAL_CHECK_NEAREST,
  CAL_CHECK_NEEDS,
  CAL_CHECK_NO_ACCURACY,
  CAL_CHECK_NO_SWEEPS,
  CAL_CHECK_OFF_MAP,
  CAL_CHECK_OK,
  CAL_CHECK_POOR,
  CAL_CHECK_TITLE,
  CAL_CONTINUE,
  CAL_DETAIL_MIRROR,
  CAL_DETAIL_PAIR,
  CAL_DETAIL_PAIRS,
  CAL_DETAIL_RMS,
  CAL_DETAIL_SNIPPET,
  CAL_DETAIL_TRANSFORM,
  CAL_DETAILS_HIDE,
  CAL_DETAILS_SHOW,
  CAL_DONE,
  CAL_GPS_DENIED,
  CAL_GPS_DENIED_SHORT,
  CAL_GPS_ERROR,
  CAL_GPS_ERROR_SHORT,
  CAL_GPS_GOOD,
  CAL_GPS_NO_ACCURACY,
  CAL_GPS_NO_ACCURACY_HELP,
  CAL_GPS_NOT_PRECISE,
  CAL_GPS_NOT_PRECISE_SHORT,
  CAL_GPS_RETRY,
  CAL_GPS_STARTING,
  CAL_GPS_WAITING,
  CAL_GPS_WEAK,
  CAL_GPS_WEAK_HELP,
  CAL_HOW,
  CAL_LEAVE_OUT,
  CAL_NEXT_SPOT,
  CAL_NO_SPOTS,
  CAL_OVERVIEW,
  CAL_RECORD,
  CAL_RECORD_AGAIN,
  CAL_RECORD_ERROR,
  CAL_RECORD_SHORT,
  CAL_RECORD_SPOT,
  CAL_RECORDED,
  CAL_RECORDED_DETAIL,
  CAL_RECORDED_ROUGH,
  CAL_RECORDING,
  CAL_RECORDING_LEFT,
  CAL_REDO,
  CAL_REDO_SPOT,
  CAL_REMOVE_DEVICE,
  CAL_REMOVED_TO_DEFAULT,
  CAL_REMOVED_TO_NONE,
  CAL_RESULT_BETTER,
  CAL_RESULT_ERROR,
  CAL_RESULT_ERROR_HELP,
  CAL_RESULT_FIRST,
  CAL_RESULT_FROM,
  CAL_RESULT_IN_USE,
  CAL_RESULT_MIRROR,
  CAL_RESULT_NEED_TWO,
  CAL_RESULT_NOT_BETTER,
  CAL_RESULT_SPOT_OFF,
  CAL_RESULT_SPOTS,
  CAL_RESULT_TITLE,
  CAL_RESULT_TOO_ROUGH,
  CAL_RESULT_TWO_SPOTS,
  CAL_RESULT_UNSOLVABLE,
  CAL_RESULT_WORST,
  CAL_SAVE,
  CAL_SAVE_ANYWAY,
  CAL_SAVE_SCOPE,
  CAL_SAVED,
  CAL_SCAN_FLOOR,
  CAL_SEE_RESULT,
  CAL_SHARE,
  CAL_SKIP,
  CAL_SKIP_TO_RESULT,
  CAL_SPOT_NAME,
  CAL_SPOT_NOT_RECORDED,
  CAL_SPOT_OF,
  CAL_SPOT_RECORDED,
  CAL_SPOT_ROLE,
  CAL_SPOTS_TITLE,
  CAL_STAND_HOW,
  CAL_START,
  CAL_START_AGAIN,
  CAL_START_OVER,
  CAL_START_OVER_CONFIRM,
  CAL_STATUS_DEFAULT,
  CAL_STATUS_DEFAULT_AGAIN,
  CAL_STATUS_DEVICE,
  CAL_STATUS_DEVICE_OVER_DEFAULT,
  CAL_STATUS_DONE,
  CAL_STATUS_NO_CAL,
  CAL_STATUS_NONE,
  CAL_STEPS,
  CAL_STEPS_TITLE,
  CAL_TEAM_NOTE,
  CAL_TITLE,
  CAL_WHOSE_DEFAULT,
  CAL_WHOSE_DEVICE,
  CAL_WHY,
  CAL_WHY_TITLE,
  CAL_YOU_CLOSE,
  CAL_YOU_FAR,
  CAL_YOU_NO_CAL,
  CAL_YOU_ROUGH,
  CAL_YOU_WAITING,
} from '../lib/copy';
import { buildFloorGraph, distance, reachableFrom, type FloorGraph, type PlanPoint } from '../lib/floorPlan';
import {
  defaultsSnippet,
  fixDistanceM,
  judgeStartFix,
  latLngToPlan,
  localDate,
  MAX_SNAP_DISTANCE_M,
  MAX_START_ACCURACY_M,
  solveCalibration,
  type Georef,
  type GeorefTransform,
} from '../lib/georef';
import { GEOREF_DEFAULTS } from '../lib/georefDefaults';
import {
  clearDeviceGeoref,
  defaultsKey,
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
import { useLiveFix, type LiveGps } from '../lib/useLiveFix';

type Mode = 'overview' | 'walk' | 'result' | 'check';
type Tone = 'ok' | 'warn' | 'bad' | 'info' | 'muted';

/** "Good enough" is the alert's own GPS start limit (lib/georef.ts), not a separate figure. */
const LIMIT_M = MAX_START_ACCURACY_M;
const RECORD_S = Math.round(RECORD_MS / 1000);

const TONE: Record<Tone, string> = {
  ok: colors.ok,
  warn: colors.warn,
  bad: colors.primary,
  info: colors.info,
  muted: colors.muted,
};

type GpsView = {
  tone: Tone;
  /** One line next to the button. */
  short: string;
  /** What to do about it, shown in the page. */
  help: string | null;
  retry: boolean;
  /** Recording cannot work in this state (no permission, or only approximate location). */
  blocks: boolean;
};

const noPeriod = (s: string) => s.replace(/\.\s*$/, '');

function gpsView(gps: LiveGps): GpsView {
  if (gps.status === 'denied') return { tone: 'bad', short: CAL_GPS_DENIED_SHORT, help: CAL_GPS_DENIED, retry: true, blocks: true };
  if (gps.status === 'error') {
    return { tone: 'bad', short: CAL_GPS_ERROR_SHORT, help: CAL_GPS_ERROR(noPeriod(gps.error ?? '')), retry: true, blocks: false };
  }
  if (gps.precise === false) return { tone: 'bad', short: CAL_GPS_NOT_PRECISE_SHORT, help: CAL_GPS_NOT_PRECISE, retry: true, blocks: true };
  if (gps.status !== 'watching') return { tone: 'muted', short: CAL_GPS_STARTING, help: null, retry: false, blocks: false };
  if (!gps.fix) {
    return gps.error
      ? { tone: 'bad', short: CAL_GPS_ERROR_SHORT, help: CAL_GPS_ERROR(noPeriod(gps.error)), retry: true, blocks: false }
      : { tone: 'muted', short: CAL_GPS_WAITING, help: null, retry: false, blocks: false };
  }
  const acc = gps.fix.accuracyM;
  if (acc === null) return { tone: 'warn', short: CAL_GPS_NO_ACCURACY, help: CAL_GPS_NO_ACCURACY_HELP, retry: false, blocks: false };
  if (acc > LIMIT_M) return { tone: 'warn', short: CAL_GPS_WEAK(acc, LIMIT_M), help: CAL_GPS_WEAK_HELP(LIMIT_M), retry: false, blocks: false };
  return { tone: 'ok', short: CAL_GPS_GOOD(acc), help: null, retry: false, blocks: false };
}

function sameTransform(a: GeorefTransform, b: GeorefTransform): boolean {
  const close = (x: number, y: number) => Math.abs(x - y) < 1e-9;
  return (
    close(a.originLat, b.originLat) &&
    close(a.originLng, b.originLng) &&
    close(a.rotationDeg, b.rotationDeg) &&
    close(a.tx, b.tx) &&
    close(a.tz, b.tz)
  );
}

const spotName = (s: RefSpot) => CAL_SPOT_NAME(s.kind, s.place);
const timeOf = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });

export default function Calibrate() {
  const insets = useSafeAreaInsets();
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

  const [mode, setMode] = useState<Mode>('overview');
  const [index, setIndex] = useState(0);
  const [recording, setRecording] = useState<{ id: string; fixes: number; msLeft: number } | null>(null);
  const [recordError, setRecordError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [showDetails, setShowDetails] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const [gpsAttempt, setGpsAttempt] = useState(0);
  const scrollRef = useRef<ScrollViewInstance>(null);

  // Live GPS only while someone is walking the spots or checking a position. It pauses during a
  // recording, so the recording's own GPS watch (lib/georefStore.ts, unchanged) runs alone.
  const gps = useLiveFix((mode === 'walk' && recording === null) || mode === 'check', gpsAttempt);
  const view = gpsView(gps);

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
      })
      .catch((error) => !cancelled && setLoadError(errorMessage(error)));
    return () => {
      cancelled = true;
    };
  }, [buildingId]);

  function go(next: Mode, i?: number) {
    if (i !== undefined) setIndex(i);
    setMode(next);
    setRecordError(null);
    setConfirmReset(false);
    scrollRef.current?.scrollTo({ y: 0, animated: false });
  }

  // Android back steps out of a spot or the result to the overview, not off the screen.
  useEffect(() => {
    if (mode === 'overview') return;
    const sub = BackHandler.addEventListener('hardwareBackPress', () => {
      if (recording) return true;
      setMode('overview');
      setRecordError(null);
      scrollRef.current?.scrollTo({ y: 0, animated: false });
      return true;
    });
    return () => sub.remove();
  }, [mode, recording]);

  function chooseBuilding(id: string) {
    setPicking(false);
    if (id === buildingId) return;
    setData(null);
    setLoadError(null);
    setNote(null);
    setRecordError(null);
    setIndex(0);
    setMode('overview');
    setBuildingId(id);
  }

  const goBack = () => (router.canGoBack() ? router.back() : router.replace('/'));

  const spots = useMemo(() => (data ? referenceSpots(data) : []), [data]);
  const total = spots.length;
  const recorded = spots.filter((s) => recordings[s.id]);
  const firstUnrecorded = spots.findIndex((s) => !recordings[s.id]);
  const multiFloor = new Set(spots.map((s) => s.floor)).size > 1;
  const solve = useMemo(
    () => solveCalibration(spots.filter((s) => recordings[s.id]).map((s) => ({ id: s.id, fix: recordings[s.id], plan: s.plan }))),
    [spots, recordings],
  );
  const solvedGeoref: Georef | null =
    solve && data?.building ? { ...solve.transform, calibratedAt: localDate(), spots: recorded.length, rmsM: solve.rmsM } : null;
  const key = data?.building ? defaultsKey(data.building) : null;
  const snippet = solvedGeoref && key ? defaultsSnippet(key, solvedGeoref) : null;
  const hasDefault = Boolean(
    data?.building && ((data.building.costar_property_id && GEOREF_DEFAULTS[data.building.costar_property_id]) || GEOREF_DEFAULTS[data.building.id]),
  );

  // One floor graph per floor that has a spot. The position check builds its own for the camera's floor.
  const graphs = useMemo(() => {
    const map = new Map<number, FloorGraph>();
    if (!data) return map;
    for (const f of new Set(spots.map((s) => s.floor))) map.set(f, buildFloorGraph(data.nodes, f));
    return map;
  }, [data, spots]);
  const check = useMemo(() => {
    if (!data) return null;
    // Same rule as the alert: the camera's floor, sweeps that can reach the camera's sweep.
    const camera = data.cameras.find((c) => c.sweep_id && data.nodes.some((n) => n.sweep_id === c.sweep_id)) ?? null;
    const camNode = camera ? data.nodes.find((n) => n.sweep_id === camera.sweep_id) : undefined;
    const floor = camera?.floor ?? camNode?.floor ?? spots[0]?.floor ?? 0;
    const graph = buildFloorGraph(data.nodes, floor);
    const reach = camNode ? reachableFrom(graph, camNode.sweep_id) : new Set(graph.nodes.keys());
    return { floor, graph, reach };
  }, [data, spots]);

  const planSpots = (floor: number): PlanSpot[] =>
    spots.flatMap((s, i) => (s.floor === floor ? [{ id: s.id, n: i + 1, plan: s.plan, recorded: Boolean(recordings[s.id]) }] : []));

  const youPoint: PlanPoint | null = active && gps.fix ? latLngToPlan(active.georef, gps.fix) : null;
  const you = youPoint && gps.fix ? { point: youPoint, accuracyM: gps.fix.accuracyM } : null;
  const northDeg = active ? active.georef.rotationDeg : null;

  /** The next spot not recorded yet after `from` (wrapping round), or null when every other one is done. */
  const nextUnrecorded = (from: number): number | null => {
    for (let k = 1; k < total; k += 1) {
      const j = (from + k) % total;
      if (!recordings[spots[j].id]) return j;
    }
    return null;
  };

  async function onRecord(spot: RefSpot) {
    if (!buildingId || recording) return;
    setRecordError(null);
    setRecording({ id: spot.id, fixes: 0, msLeft: RECORD_MS });
    try {
      const rec = await recordSpot((fixes, msLeft) => setRecording({ id: spot.id, fixes, msLeft }));
      const next = { ...recordings, [spot.id]: rec };
      setRecordings(next);
      await saveSpotRecordings(buildingId, next);
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
    } catch (error) {
      setRecordError(errorMessage(error));
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error).catch(() => {});
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

  async function onStartOver() {
    if (!buildingId) return;
    if (!confirmReset) {
      setConfirmReset(true);
      return;
    }
    setConfirmReset(false);
    setRecordings({});
    await saveSpotRecordings(buildingId, {});
  }

  async function onSave() {
    if (!buildingId || !solvedGeoref || !data) return;
    await saveDeviceGeoref(buildingId, solvedGeoref);
    setActive(await loadActiveGeoref(data.building));
    setNote(CAL_SAVED);
  }

  async function onClear() {
    if (!buildingId || !data) return;
    await clearDeviceGeoref(buildingId);
    const next = await loadActiveGeoref(data.building);
    setActive(next);
    setNote(next ? CAL_REMOVED_TO_DEFAULT : CAL_REMOVED_TO_NONE);
  }

  const gpsHelp = view.help ? (
    <View style={styles.gap}>
      <Notice tone={view.tone === 'bad' ? 'error' : 'warn'}>{view.help}</Notice>
      {view.retry ? <Button title={CAL_GPS_RETRY} kind="secondary" onPress={() => setGpsAttempt((a) => a + 1)} /> : null}
    </View>
  ) : null;

  let content: ReactNode = null;
  let footer: ReactNode = null;

  if (mode === 'overview' || !data || total === 0) {
    // ---------- Overview: is it calibrated already, what this is, the spots, start ----------
    content = (
      <>
        <Title>{CAL_TITLE}</Title>
        <Text style={styles.small}>{CAL_TEAM_NOTE}</Text>

        <Card>
          <Label>{CAL_BUILDING}</Label>
          <Body>{data?.building ? buildingLabel(data.building) : buildingId ? CAL_BUILDING_LOADING : CAL_BUILDING_NONE}</Body>
          {picking ? (
            <>
              <Field
                label={CAL_BUILDING_SEARCH}
                value={query}
                onChangeText={setQuery}
                placeholder={CAL_BUILDING_PLACEHOLDER}
                autoCorrect={false}
              />
              {searchError ? <Notice tone="error">{CAL_BUILDING_SEARCH_ERROR(searchError)}</Notice> : null}
              {results.map((b) => (
                <Button key={b.id} title={buildingLabel(b)} kind="secondary" onPress={() => chooseBuilding(b.id)} />
              ))}
            </>
          ) : (
            <Button title={CAL_BUILDING_CHANGE} kind="secondary" onPress={() => setPicking(true)} />
          )}
          {loadError ? <Notice tone="error">{CAL_BUILDING_LOAD_ERROR(loadError)}</Notice> : null}
        </Card>

        {data ? (
          <Card style={{ borderLeftWidth: 6, borderLeftColor: active ? colors.ok : colors.warn }}>
            <Text style={[styles.statusTitle, { color: active ? colors.ok : colors.warn }]}>{active ? CAL_STATUS_DONE : CAL_STATUS_NONE}</Text>
            {active?.source === 'default' ? (
              <>
                <Body>{CAL_STATUS_DEFAULT(active.georef.calibratedAt, active.georef.spots, active.georef.rmsM)}</Body>
                <Body muted>{CAL_STATUS_DEFAULT_AGAIN}</Body>
              </>
            ) : active?.source === 'device' ? (
              <>
                <Body>
                  {CAL_STATUS_DEVICE(active.georef.calibratedAt, active.georef.spots, active.georef.rmsM)}
                  {hasDefault ? ` ${CAL_STATUS_DEVICE_OVER_DEFAULT}` : ''}
                </Body>
                <Button title={CAL_REMOVE_DEVICE} kind="secondary" onPress={() => void onClear()} />
              </>
            ) : (
              <Body>{CAL_STATUS_NO_CAL}</Body>
            )}
          </Card>
        ) : null}
        {note ? <Notice tone="info">{note}</Notice> : null}

        {data && total === 0 ? <Notice>{CAL_NO_SPOTS}</Notice> : null}

        {data && total > 0 ? (
          <>
            <Card>
              <Label>{CAL_WHY_TITLE}</Label>
              <Body>{CAL_WHY}</Body>
              <Body>{CAL_HOW(total, RECORD_S)}</Body>
            </Card>

            <Label>{CAL_SPOTS_TITLE}</Label>
            <CalibrationPlan
              graph={graphs.get(spots[0].floor)!}
              spots={planSpots(spots[0].floor)}
              targetId={null}
              you={null}
              rotationDeg={northDeg}
              caption={multiFloor ? CAL_SCAN_FLOOR(spots[0].floor) : null}
            />
            <View style={styles.list}>
              {spots.map((s, i) => (
                <Pressable
                  key={s.id}
                  accessibilityRole="button"
                  onPress={() => go('walk', i)}
                  style={({ pressed }) => [styles.spotRow, pressed && styles.pressed]}
                >
                  <NumberBadge n={i + 1} color={recordings[s.id] ? colors.ok : '#64748B'} />
                  <View style={styles.flex}>
                    <Text style={styles.rowName}>{spotName(s)}</Text>
                    <Text style={styles.rowSub}>
                      {CAL_SPOT_ROLE(s.kind, s.note)}
                      {multiFloor ? ` ${CAL_SCAN_FLOOR(s.floor)}.` : ''}
                    </Text>
                    <Text style={[styles.rowStatus, { color: recordings[s.id] ? colors.ok : colors.muted }]}>
                      {recordings[s.id] ? CAL_SPOT_RECORDED : CAL_SPOT_NOT_RECORDED}
                    </Text>
                  </View>
                </Pressable>
              ))}
            </View>

            <Card>
              <Label>{CAL_BEFORE_TITLE}</Label>
              {CAL_BEFORE_LINES.map((line, i) => (
                <Numbered key={line} n={i + 1} text={line} />
              ))}
            </Card>

            {recorded.length >= 2 && firstUnrecorded >= 0 ? (
              <Button title={CAL_SEE_RESULT} kind="secondary" onPress={() => go('result')} />
            ) : null}
            {recorded.length > 0 ? (
              <Button
                title={confirmReset ? CAL_START_OVER_CONFIRM(recorded.length) : CAL_START_OVER}
                kind="secondary"
                onPress={() => void onStartOver()}
              />
            ) : null}
            <Button title={CAL_CHECK} kind="secondary" onPress={() => go('check')} disabled={!active} />
            {!active ? <Text style={styles.small}>{CAL_CHECK_NEEDS}</Text> : null}
          </>
        ) : null}

        <Button title={CAL_BACK} kind="secondary" onPress={goBack} />
      </>
    );
    if (data && total > 0) {
      footer =
        recorded.length === 0 ? (
          <Button big title={active ? CAL_START_AGAIN : CAL_START} onPress={() => go('walk', 0)} />
        ) : firstUnrecorded >= 0 ? (
          <Button big title={CAL_CONTINUE(firstUnrecorded + 1, total)} onPress={() => go('walk', firstUnrecorded)} />
        ) : (
          <Button big title={CAL_SEE_RESULT} onPress={() => go('result')} />
        );
    }
  } else if (mode === 'walk') {
    // ---------- One spot: where it is, where you are, GPS state, one button ----------
    const i = Math.min(index, total - 1);
    const spot = spots[i];
    const n = i + 1;
    const rec = recordings[spot.id];
    const busy = recording !== null;
    const here = recording && recording.id === spot.id ? recording : null;
    const next = nextUnrecorded(i);
    const awayM = you ? distance(you.point, spot.plan) : null;
    // "Close" only when GPS itself is good enough and cannot tell you apart from the spot. With rough
    // GPS the distance is still shown, never "close".
    const acc = you?.accuracyM ?? null;
    const close = awayM !== null && acc !== null && acc <= LIMIT_M && awayM <= acc;

    content = (
      <>
        <View style={styles.stepper}>
          <Text style={styles.stepOf}>{CAL_SPOT_OF(n, total)}</Text>
          <View style={styles.chips}>
            {spots.map((s, j) => {
              const done = Boolean(recordings[s.id]);
              const current = j === i;
              return (
                <Pressable
                  key={s.id}
                  accessibilityRole="button"
                  accessibilityLabel={`${CAL_SPOT_OF(j + 1, total)}: ${spotName(s)}, ${done ? CAL_SPOT_RECORDED : CAL_SPOT_NOT_RECORDED}`}
                  accessibilityState={{ selected: current, disabled: busy }}
                  disabled={busy}
                  hitSlop={4}
                  onPress={() => go('walk', j)}
                  style={[styles.chip, done && styles.chipDone, current && styles.chipCurrent]}
                >
                  <Text style={[styles.chipText, done && styles.chipTextDone]}>{j + 1}</Text>
                </Pressable>
              );
            })}
          </View>
        </View>

        <View style={styles.gapSm}>
          <Text style={styles.spotName}>{spotName(spot)}</Text>
          <Text style={styles.spotRole}>
            {CAL_SPOT_ROLE(spot.kind, spot.note)}
            {multiFloor ? ` ${CAL_SCAN_FLOOR(spot.floor)}.` : ''}
          </Text>
        </View>

        {gpsHelp}

        {!active ? (
          <Body muted>{CAL_YOU_NO_CAL}</Body>
        ) : you && awayM !== null ? (
          <View style={styles.gapSm}>
            <Text style={[styles.where, { color: close ? colors.ok : colors.info }]}>{close ? CAL_YOU_CLOSE(n) : CAL_YOU_FAR(awayM, n)}</Text>
            <Text style={styles.small}>{CAL_YOU_ROUGH(active.georef.rmsM)}</Text>
          </View>
        ) : gps.status === 'starting' || gps.status === 'watching' ? (
          <Body muted>{CAL_YOU_WAITING}</Body>
        ) : null}

        <CalibrationPlan
          graph={graphs.get(spot.floor)!}
          spots={planSpots(spot.floor)}
          targetId={spot.id}
          targetName={spotName(spot)}
          you={you}
          rotationDeg={northDeg}
          caption={multiFloor ? CAL_SCAN_FLOOR(spot.floor) : null}
        />

        {rec && !here ? (
          <Card style={{ borderLeftWidth: 6, borderLeftColor: colors.ok }}>
            <Text style={[styles.statusTitle, { color: colors.ok }]}>{CAL_RECORDED(n)}</Text>
            <Body>{CAL_RECORDED_DETAIL(rec.fixes, rec.accuracyM, timeOf(rec.recordedAt))}</Body>
            {rec.accuracyM != null && rec.accuracyM > LIMIT_M ? <Notice>{CAL_RECORDED_ROUGH(LIMIT_M)}</Notice> : null}
            <Button title={CAL_RECORD_AGAIN(n)} kind="secondary" onPress={() => void onRecord(spot)} disabled={busy || view.blocks} />
          </Card>
        ) : null}

        <Body>{CAL_STAND_HOW}</Body>
        <Card>
          <Label>{CAL_STEPS_TITLE}</Label>
          {CAL_STEPS(n, RECORD_S).map((line, k) => (
            <Numbered key={line} n={k + 1} text={line} />
          ))}
        </Card>

        <View style={styles.row}>
          <View style={styles.flex}>
            {next !== null ? (
              <Button title={CAL_SKIP} kind="secondary" onPress={() => go('walk', next)} disabled={busy} />
            ) : (
              <Button title={CAL_SKIP_TO_RESULT} kind="secondary" onPress={() => go('result')} disabled={busy || recorded.length < 2} />
            )}
          </View>
          <View style={styles.flex}>
            <Button title={CAL_ALL_SPOTS} kind="secondary" onPress={() => go('overview')} disabled={busy} />
          </View>
        </View>
      </>
    );

    footer = here ? (
      <View style={styles.recBar} accessibilityLiveRegion="polite">
        <View style={[styles.recFill, { width: `${Math.round((1 - here.msLeft / RECORD_MS) * 100)}%` as DimensionValue }]} />
        <Text style={styles.recTitle}>{CAL_RECORDING(n)}</Text>
        <Text style={styles.recSub}>{CAL_RECORDING_LEFT(Math.ceil(here.msLeft / 1000), here.fixes)}</Text>
      </View>
    ) : (
      <>
        {recordError ? (
          <StatusLine tone="bad" text={CAL_RECORD_ERROR(recordError)} />
        ) : rec ? (
          <StatusLine tone="ok" text={CAL_RECORDED(n)} />
        ) : (
          <StatusLine tone={view.tone} text={view.short} />
        )}
        {rec ? (
          next !== null ? (
            <Button big title={CAL_NEXT_SPOT(next + 1)} onPress={() => go('walk', next)} />
          ) : (
            <Button big title={CAL_SEE_RESULT} onPress={() => go('result')} disabled={recorded.length < 2} />
          )
        ) : (
          <Button big title={CAL_RECORD(n)} onPress={() => void onRecord(spot)} disabled={busy || view.blocks} />
        )}
      </>
    );
  } else if (mode === 'result') {
    // ---------- Result: the fit in plain words, each spot with redo, then save ----------
    const count = recorded.length;
    const mirrorBad = solve?.mirroredRmsM != null && solve.mirroredRmsM < solve.rmsM;
    const tooRough = solve ? solve.rmsM >= LIMIT_M : false;
    const inUse = Boolean(solve && active?.source === 'device' && sameTransform(active.georef, solve.transform));
    const better = solve && active ? solve.rmsM < active.georef.rmsM : null;
    const whose = active?.source === 'device' ? CAL_WHOSE_DEVICE : CAL_WHOSE_DEFAULT;
    const recommend = Boolean(solve) && !inUse && !tooRough && !mirrorBad && count >= 3 && (active === null || better === true);
    const residual = (id: string) => solve?.residuals.find((r) => r.id === id)?.errorM ?? null;
    let worstIdx = -1;
    if (solve && count >= 3) {
      let worstM = -1;
      spots.forEach((s, j) => {
        const e = residual(s.id);
        if (e !== null && e > worstM) {
          worstM = e;
          worstIdx = j;
        }
      });
    }
    const verdictColor = recommend || inUse ? colors.ok : mirrorBad || tooRough ? colors.primary : colors.warn;

    content = (
      <>
        <Title>{CAL_RESULT_TITLE}</Title>
        <Body muted>{CAL_RESULT_FROM(count, total)}</Body>

        {count < 2 ? (
          <Notice>{CAL_RESULT_NEED_TWO}</Notice>
        ) : !solve ? (
          <Notice tone="error">{CAL_RESULT_UNSOLVABLE}</Notice>
        ) : (
          <Card style={{ borderLeftWidth: 6, borderLeftColor: verdictColor }}>
            <Text style={styles.bigNumber}>{CAL_RESULT_ERROR(solve.rmsM)}</Text>
            <Body muted>{CAL_RESULT_ERROR_HELP}</Body>
            {inUse ? <ToneLine tone="ok" text={CAL_RESULT_IN_USE} /> : null}
            {mirrorBad && solve.mirroredRmsM != null ? <ToneLine tone="bad" text={CAL_RESULT_MIRROR(solve.mirroredRmsM, solve.rmsM)} /> : null}
            {tooRough ? <ToneLine tone="bad" text={CAL_RESULT_TOO_ROUGH(LIMIT_M)} /> : null}
            {count === 2 ? <ToneLine tone="warn" text={CAL_RESULT_TWO_SPOTS} /> : null}
            {!inUse && count >= 3 && active ? (
              better ? (
                <ToneLine tone="ok" text={CAL_RESULT_BETTER(whose, active.georef.rmsM)} />
              ) : (
                <ToneLine tone="warn" text={CAL_RESULT_NOT_BETTER(whose, active.georef.rmsM)} />
              )
            ) : null}
            {!inUse && count >= 3 && !active ? <ToneLine tone="info" text={CAL_RESULT_FIRST} /> : null}
          </Card>
        )}

        <Label>{CAL_RESULT_SPOTS}</Label>
        <View style={styles.list}>
          {spots.map((s, j) => {
            const rec = recordings[s.id];
            const e = residual(s.id);
            return (
              <View key={s.id} style={styles.resultRow}>
                <View style={styles.resultHead}>
                  <NumberBadge n={j + 1} color={rec ? colors.ok : '#64748B'} />
                  <View style={styles.flex}>
                    <Text style={styles.rowName}>{spotName(s)}</Text>
                    <Text style={[styles.rowStatus, { color: j === worstIdx ? colors.warn : rec ? colors.text : colors.muted }]}>
                      {rec ? (e !== null ? CAL_RESULT_SPOT_OFF(e) : CAL_SPOT_RECORDED) : CAL_SPOT_NOT_RECORDED}
                      {j === worstIdx ? ` (${CAL_RESULT_WORST})` : ''}
                    </Text>
                  </View>
                </View>
                <View style={styles.row}>
                  <View style={styles.flex}>
                    <Button title={rec ? CAL_REDO : CAL_RECORD_SHORT} kind="secondary" onPress={() => go('walk', j)} />
                  </View>
                  {rec ? (
                    <View style={styles.flex}>
                      <Button title={CAL_LEAVE_OUT} kind="secondary" onPress={() => void onForget(s)} />
                    </View>
                  ) : null}
                </View>
              </View>
            );
          })}
        </View>

        {note ? <Notice tone="info">{note}</Notice> : null}
        {solve && !inUse && !recommend ? <Button title={CAL_SAVE_ANYWAY} kind="secondary" onPress={() => void onSave()} /> : null}
        {solve ? <Body muted>{CAL_SAVE_SCOPE}</Body> : null}
        {snippet ? <Button title={CAL_SHARE} kind="secondary" onPress={() => void Share.share({ message: snippet })} /> : null}
        {solve ? (
          <Button title={showDetails ? CAL_DETAILS_HIDE : CAL_DETAILS_SHOW} kind="secondary" onPress={() => setShowDetails((v) => !v)} />
        ) : null}
        {solve && showDetails ? (
          <Card>
            <Text style={styles.small}>
              {CAL_DETAIL_TRANSFORM(solve.transform.rotationDeg, solve.transform.tx, solve.transform.tz, count)}
            </Text>
            <Text style={styles.small}>{CAL_DETAIL_RMS(solve.rmsM)}</Text>
            {solve.mirroredRmsM !== null ? <Text style={styles.small}>{CAL_DETAIL_MIRROR(solve.mirroredRmsM)}</Text> : null}
            <Text style={styles.small}>{CAL_DETAIL_PAIRS}</Text>
            {recorded.map((a, j) =>
              recorded.slice(j + 1).map((b) => (
                <Text key={`${a.id}-${b.id}`} style={styles.small}>
                  {CAL_DETAIL_PAIR(spotName(a), spotName(b), fixDistanceM(recordings[a.id], recordings[b.id]), distance(a.plan, b.plan))}
                </Text>
              )),
            )}
            {snippet ? (
              <>
                <Label>{CAL_DETAIL_SNIPPET}</Label>
                <Text selectable style={styles.code}>
                  {snippet}
                </Text>
              </>
            ) : null}
          </Card>
        ) : null}
        <Button title={CAL_OVERVIEW} kind="secondary" onPress={() => go('overview')} />
      </>
    );

    footer = inUse ? (
      <Button big title={CAL_DONE} onPress={() => go('overview')} />
    ) : recommend ? (
      <Button big title={CAL_SAVE} onPress={() => void onSave()} />
    ) : firstUnrecorded >= 0 ? (
      <Button big title={CAL_RECORD_SPOT(firstUnrecorded + 1)} onPress={() => go('walk', firstUnrecorded)} />
    ) : worstIdx >= 0 ? (
      <Button big title={CAL_REDO_SPOT(worstIdx + 1)} onPress={() => go('walk', worstIdx)} />
    ) : (
      <Button big title={CAL_OVERVIEW} onPress={() => go('overview')} />
    );
  } else if (mode === 'check' && check) {
    // ---------- Check: the alert's own GPS start rule against the calibration in use, live ----------
    const verdict = active && gps.fix ? judgeStartFix(active.georef, gps.fix, [...check.graph.nodes.values()], (id) => check.reach.has(id)) : null;
    const alertStart = verdict?.ok ? (check.graph.nodes.get(verdict.sweepId) ?? null) : null;
    let nearest: { name: string; m: number } | null = null;
    if (youPoint) {
      for (const s of spots) {
        if (s.floor !== check.floor) continue;
        const m = distance(youPoint, s.plan);
        if (!nearest || m < nearest.m) nearest = { name: spotName(s), m };
      }
    }
    let verdictText: string | null = null;
    if (verdict) {
      if (verdict.ok) verdictText = CAL_CHECK_OK(verdict.snapM);
      else if (verdict.reason === 'no_accuracy') verdictText = CAL_CHECK_NO_ACCURACY;
      else if (verdict.reason === 'poor_accuracy') verdictText = CAL_CHECK_POOR(verdict.accuracyM ?? 0, LIMIT_M);
      else if (verdict.reason === 'off_map') verdictText = CAL_CHECK_OFF_MAP(MAX_SNAP_DISTANCE_M);
      else verdictText = CAL_CHECK_NO_SWEEPS;
    }

    content = (
      <>
        <Title>{CAL_CHECK_TITLE}</Title>
        <Body muted>{CAL_CHECK_HELP}</Body>
        {gpsHelp}
        {!active ? <Notice>{CAL_CHECK_NEEDS}</Notice> : null}
        {verdictText ? <ToneLine tone={verdict?.ok ? 'ok' : 'warn'} text={verdictText} /> : null}
        {nearest ? <Body>{CAL_CHECK_NEAREST(nearest.name, nearest.m)}</Body> : null}
        {active && !you && (gps.status === 'starting' || gps.status === 'watching') ? <Body muted>{CAL_YOU_WAITING}</Body> : null}
        <CalibrationPlan
          graph={check.graph}
          spots={planSpots(check.floor)}
          targetId={null}
          you={you}
          alertStart={alertStart}
          rotationDeg={northDeg}
          caption={multiFloor ? CAL_SCAN_FLOOR(check.floor) : null}
        />
        {active ? <Text style={styles.small}>{CAL_YOU_ROUGH(active.georef.rmsM)}</Text> : null}
      </>
    );
    footer = (
      <>
        <StatusLine tone={view.tone} text={view.short} />
        <Button big title={CAL_DONE} onPress={() => go('overview')} />
      </>
    );
  }

  return (
    <SafeAreaView style={[styles.flex, { backgroundColor: colors.bg }]} edges={['top']}>
      <ScrollView
        ref={scrollRef}
        contentContainerStyle={[styles.scroll, { paddingBottom: footer ? space.xl : space.xl + insets.bottom }]}
        keyboardShouldPersistTaps="handled"
      >
        {content}
      </ScrollView>
      {footer ? <View style={[styles.footer, { paddingBottom: space.md + insets.bottom }]}>{footer}</View> : null}
    </SafeAreaView>
  );
}

function NumberBadge({ n, color }: { n: number; color: string }) {
  return (
    <View style={[styles.badge, { backgroundColor: color }]}>
      <Text style={styles.badgeText}>{n}</Text>
    </View>
  );
}

function Numbered({ n, text }: { n: number; text: string }) {
  return (
    <View style={styles.numbered}>
      <Text style={styles.numberedN}>{n}.</Text>
      <Text style={[styles.body, styles.flex]}>{text}</Text>
    </View>
  );
}

/** A colored line with a bar on the left, like Notice, with a green tone too. */
function ToneLine({ tone, text }: { tone: Tone; text: string }) {
  return (
    <View style={[styles.toneLine, { borderLeftColor: TONE[tone] }]}>
      <Text style={[styles.body, styles.bold, { color: TONE[tone] }]}>{text}</Text>
    </View>
  );
}

/** One line above the main button: a colored dot and the state in words. */
function StatusLine({ tone, text }: { tone: Tone; text: string }) {
  return (
    <View style={styles.statusLine} accessibilityLiveRegion="polite">
      <View style={[styles.statusDot, { backgroundColor: TONE[tone] }]} />
      <Text style={[styles.statusText, { color: tone === 'muted' ? colors.muted : TONE[tone] }]}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  gap: { gap: space.sm },
  gapSm: { gap: space.xs },
  row: { flexDirection: 'row', gap: space.md },
  scroll: { padding: space.lg, gap: space.lg },
  footer: {
    backgroundColor: colors.card,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    paddingHorizontal: space.lg,
    paddingTop: space.md,
    gap: space.sm,
  },
  body: { fontSize: 16, lineHeight: 22, color: colors.text },
  bold: { fontWeight: '700' },
  small: { fontSize: 14, lineHeight: 20, color: colors.muted },
  pressed: { opacity: 0.7 },
  statusTitle: { fontSize: 20, fontWeight: '800' },
  list: { gap: space.sm },
  spotRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    minHeight: 64,
    padding: space.md,
    borderRadius: 12,
    backgroundColor: colors.card,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  rowName: { fontSize: 18, fontWeight: '700', color: colors.text },
  rowSub: { fontSize: 14, lineHeight: 19, color: colors.muted },
  rowStatus: { fontSize: 15, fontWeight: '700', marginTop: 2 },
  badge: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
  badgeText: { color: '#FFFFFF', fontSize: 17, fontWeight: '800' },
  numbered: { flexDirection: 'row', gap: space.sm },
  numberedN: { fontSize: 16, lineHeight: 22, fontWeight: '800', color: colors.text, minWidth: 18 },
  stepper: { gap: space.sm },
  stepOf: { fontSize: 15, fontWeight: '800', color: colors.muted, textTransform: 'uppercase', letterSpacing: 0.5 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  chip: {
    width: 48,
    height: 48,
    borderRadius: 24,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 2,
    borderColor: colors.border,
    backgroundColor: colors.card,
  },
  chipDone: { backgroundColor: colors.ok, borderColor: colors.ok },
  chipCurrent: { borderColor: colors.primary, borderWidth: 4 },
  chipText: { fontSize: 18, fontWeight: '800', color: colors.text },
  chipTextDone: { color: '#FFFFFF' },
  spotName: { fontSize: 30, lineHeight: 36, fontWeight: '800', color: colors.text },
  spotRole: { fontSize: 16, lineHeight: 22, color: colors.muted },
  where: { fontSize: 18, lineHeight: 24, fontWeight: '800' },
  statusLine: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  statusDot: { width: 14, height: 14, borderRadius: 7 },
  statusText: { flex: 1, fontSize: 17, lineHeight: 22, fontWeight: '700' },
  recBar: {
    minHeight: 72,
    borderRadius: 12,
    backgroundColor: '#1E3A8A',
    justifyContent: 'center',
    paddingHorizontal: space.lg,
    overflow: 'hidden',
  },
  recFill: { position: 'absolute', left: 0, top: 0, bottom: 0, backgroundColor: colors.info },
  recTitle: { color: '#FFFFFF', fontSize: 20, fontWeight: '800' },
  recSub: { color: '#FFFFFF', fontSize: 15, fontWeight: '600' },
  bigNumber: { fontSize: 26, lineHeight: 32, fontWeight: '800', color: colors.text },
  toneLine: { borderLeftWidth: 4, paddingLeft: space.md, paddingVertical: space.xs },
  resultRow: {
    gap: space.sm,
    padding: space.md,
    borderRadius: 12,
    backgroundColor: colors.card,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  resultHead: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  code: {
    fontFamily: Platform.select({ ios: 'Courier', default: 'monospace' }),
    fontSize: 12,
    color: colors.text,
    backgroundColor: '#F1F5F9',
    padding: space.sm,
  },
});
