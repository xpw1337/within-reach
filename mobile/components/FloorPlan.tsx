import { useEffect, useMemo, useRef, useState } from 'react';
import { StyleSheet, Text, View, type GestureResponderEvent, type LayoutChangeEvent } from 'react-native';
import Svg, { Circle, G, Line, Polyline, Rect, Text as SvgText } from 'react-native-svg';

import {
  PLAN_FLOOR,
  PLAN_MOVE_SIMULATED,
  PLAN_MOVE_STEPS,
  PLAN_NO_STEPS_YET,
  PLAN_PERSON,
  PLAN_SIMULATED_POSITION,
  PLAN_STEPS_POSITION,
  PLAN_YOU,
} from '../lib/copy';
import { pointAlong, polylineLength, project, type FloorGraph, type PlanPoint } from '../lib/floorPlan';
import { useStepWalk } from '../lib/useStepWalk';
import { colors, space } from './theme';

const PAD = 22;
const MAX_HEIGHT = 340;

const C = {
  bg: '#F8FAFC',
  walkable: '#E2E8F0',
  person: colors.primary,
  aed: colors.ok,
  you: colors.info,
  route: colors.info,
  routeLater: '#94A3B8',
};

type PlanProps = {
  graph: FloorGraph;
  /** The person (camera sweep). Null on a floor without the camera (calibration screen). */
  person: PlanPoint | null;
  aed: PlanPoint | null;
  aedLabel: string;
  /** The leg the helper is walking now (solid). */
  activeRoute: PlanPoint[] | null;
  /** The leg after this one (dashed), for the AED runner. */
  laterRoute: PlanPoint[] | null;
  helper: PlanPoint | null;
  /** Small lines under the plan, shown with the helper dot: where it started and how it moves. */
  positionLines?: string[];
  /** A line shown above the plan whether or not there is a helper dot, for example "Tap the map where you are". */
  prompt?: string | null;
  /** When set, a tap on the plan reports the plan point under the finger (meters, x and z). */
  onTapPlan?: ((p: PlanPoint) => void) | null;
};

function toPoints(pts: PlanPoint[], toPx: (p: PlanPoint) => [number, number]): string {
  return pts.map((p) => toPx(p).join(',')).join(' ');
}

/** One floor of the scan: walkable links drawn faintly, the person, the AED, the route and the helper. */
export function FloorPlan({ graph, person, aed, aedLabel, activeRoute, laterRoute, helper, positionLines, prompt, onTapPlan }: PlanProps) {
  const [width, setWidth] = useState(0);
  const onLayout = (e: LayoutChangeEvent) => setWidth(Math.round(e.nativeEvent.layout.width));
  const proj = useMemo(() => (width > 0 ? project(graph, width, PAD, MAX_HEIGHT) : null), [graph, width]);

  const label = (p: PlanPoint, text: string, color: string, key: string) => {
    if (!proj) return null;
    const [x, y] = proj.toPx(p);
    const half = Math.min(proj.width / 2 - 4, text.length * 3.6 + 6);
    const cx = Math.max(half + 2, Math.min(proj.width - half - 2, x));
    const ty = y > 24 ? y - 14 : y + 24;
    // A white outline copy first, then the colored text on top, so labels stay readable over routes.
    return (
      <G key={key}>
        <SvgText x={cx} y={ty} fill="#FFFFFF" stroke="#FFFFFF" strokeWidth={4} fontSize={12} fontWeight="700" textAnchor="middle">
          {text}
        </SvgText>
        <SvgText x={cx} y={ty} fill={color} fontSize={12} fontWeight="700" textAnchor="middle">
          {text}
        </SvgText>
      </G>
    );
  };

  // A child-less overlay takes the tap, so the touch position is relative to the drawing on every
  // platform (on web, react-native-web measures it against the responder view itself).
  const onRelease = (e: GestureResponderEvent) => {
    if (!proj || !onTapPlan) return;
    const { locationX, locationY } = e.nativeEvent;
    if (Number.isFinite(locationX) && Number.isFinite(locationY)) onTapPlan(proj.fromPx(locationX, locationY));
  };

  return (
    <View onLayout={onLayout} style={styles.wrap}>
      {prompt ? <Text style={styles.prompt}>{prompt}</Text> : null}
      {proj ? (
        <View style={{ width: proj.width, height: proj.height }}>
          <Svg width={proj.width} height={proj.height} accessibilityLabel="Floor plan">
            <Rect x={0} y={0} width={proj.width} height={proj.height} rx={12} fill={C.bg} />
            {graph.edges.map(([a, b]) => {
              const [x1, y1] = proj.toPx(graph.nodes.get(a)!);
              const [x2, y2] = proj.toPx(graph.nodes.get(b)!);
              return <Line key={`${a}-${b}`} x1={x1} y1={y1} x2={x2} y2={y2} stroke={C.walkable} strokeWidth={7} strokeLinecap="round" />;
            })}
            {[...graph.nodes.values()].map((n) => {
              const [cx, cy] = proj.toPx(n);
              return <Circle key={n.id} cx={cx} cy={cy} r={3.5} fill={C.walkable} />;
            })}
            {laterRoute && laterRoute.length > 1 ? (
              <Polyline
                points={toPoints(laterRoute, proj.toPx)}
                fill="none"
                stroke={C.routeLater}
                strokeWidth={3}
                strokeDasharray="6,6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            ) : null}
            {activeRoute && activeRoute.length > 1 ? (
              <Polyline
                points={toPoints(activeRoute, proj.toPx)}
                fill="none"
                stroke={C.route}
                strokeWidth={5}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            ) : null}
            {aed ? <Circle cx={proj.toPx(aed)[0]} cy={proj.toPx(aed)[1]} r={11} fill={C.aed} stroke="#FFFFFF" strokeWidth={2.5} /> : null}
            {person ? (
              <>
                <Circle cx={proj.toPx(person)[0]} cy={proj.toPx(person)[1]} r={14} fill="none" stroke={C.person} strokeWidth={2} opacity={0.5} />
                <Circle cx={proj.toPx(person)[0]} cy={proj.toPx(person)[1]} r={8} fill={C.person} stroke="#FFFFFF" strokeWidth={2.5} />
              </>
            ) : null}
            {helper ? (
              <Circle cx={proj.toPx(helper)[0]} cy={proj.toPx(helper)[1]} r={6.5} fill={C.you} stroke="#FFFFFF" strokeWidth={2.5} />
            ) : null}
            {person ? label(person, PLAN_PERSON, C.person, 'l-person') : null}
            {aed ? label(aed, aedLabel, C.aed, 'l-aed') : null}
          </Svg>
          {onTapPlan ? (
            <View
              style={StyleSheet.absoluteFill}
              accessibilityLabel="Floor plan. Tap where you are."
              onStartShouldSetResponder={() => true}
              onResponderRelease={onRelease}
            />
          ) : null}
        </View>
      ) : (
        <View style={{ height: 200 }} />
      )}

      <View style={styles.legend}>
        {person ? <LegendDot color={C.person} text={PLAN_PERSON} /> : null}
        {aed ? <LegendDot color={C.aed} text={aedLabel} /> : null}
        {helper ? <LegendDot color={C.you} text={PLAN_YOU} /> : null}
        <Text style={styles.floor}>
          {PLAN_FLOOR} {graph.floor}
        </Text>
      </View>
      {helper
        ? (positionLines ?? []).map((line) => (
            <Text key={line} style={styles.simulated}>
              {line}
            </Text>
          ))
        : null}
    </View>
  );
}

function LegendDot({ color, text }: { color: string; text: string }) {
  return (
    <View style={styles.legendItem}>
      <View style={[styles.dot, { backgroundColor: color }]} />
      <Text style={styles.legendText}>{text}</Text>
    </View>
  );
}

type WalkingProps = Omit<PlanProps, 'helper' | 'activeRoute' | 'positionLines' | 'prompt' | 'onTapPlan'> & {
  /** The helper walks this route from its first point and stops at the end (see useStepWalk). */
  walkRoute: PlanPoint[] | null;
  /** Where the helper stands when there is no route to walk (placed there by a button). */
  standAt: PlanPoint | null;
  /**
   * Where the start came from, when it was not the simulated start: "Start position from GPS (...)"
   * or "Start position set by you". Null for the simulated start.
   */
  startNote?: string | null;
  /**
   * Called as the helper dot moves (at most every 500 ms, and only after it moved 0.3 m), so the 3D
   * route page can follow the walk (app/alert/[dispatchId].tsx sends it over Realtime).
   */
  onHelperMove?: (p: PlanPoint) => void;
};

/**
 * Floor plan with the helper dot. Give it a new `key` for each leg: the walk restarts from the leg's
 * first point (which is how a button press snaps the dot to the AED or the person), and the step
 * tracking or timer fallback is decided again for the new leg.
 */
export function WalkingFloorPlan({ walkRoute, standAt, startNote, onHelperMove, ...rest }: WalkingProps) {
  const length = walkRoute ? polylineLength(walkRoute) : 0;
  const walk = useStepWalk(length);
  const helper = walkRoute && walkRoute.length > 0 ? pointAlong(walkRoute, walk.walked) : standAt;
  const onMove = useRef(onHelperMove);
  const last = useRef<{ p: PlanPoint; at: number } | null>(null);
  useEffect(() => {
    onMove.current = onHelperMove;
  }, [onHelperMove]);
  const hx = helper ? Math.round(helper.x * 10) / 10 : null;
  const hz = helper ? Math.round(helper.z * 10) / 10 : null;
  useEffect(() => {
    if (hx === null || hz === null || !onMove.current) return;
    const t = Date.now();
    const prev = last.current;
    if (prev && (t - prev.at < 500 || Math.hypot(prev.p.x - hx, prev.p.z - hz) < 0.3)) return;
    last.current = { p: { x: hx, z: hz }, at: t };
    onMove.current({ x: hx, z: hz });
  }, [hx, hz]);
  // Simulated start: one line, as before. A GPS or tapped start: the start line, then a movement line
  // worded as movement, so a real start never reads as "simulated" and a timed walk never reads as GPS.
  const lines: string[] = [];
  if (startNote) {
    lines.push(startNote);
    if (walk.mode === 'steps') lines.push(PLAN_MOVE_STEPS);
    else if (walk.mode === 'timer') lines.push(PLAN_MOVE_SIMULATED);
  } else if (walk.mode === 'steps') lines.push(PLAN_STEPS_POSITION);
  else if (walk.mode === 'timer') lines.push(PLAN_SIMULATED_POSITION);
  if (walk.noStepsYet) lines.push(PLAN_NO_STEPS_YET);
  return <FloorPlan {...rest} activeRoute={walkRoute} helper={helper} positionLines={lines} />;
}

const styles = StyleSheet.create({
  wrap: { gap: space.sm },
  legend: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: space.md },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: space.xs },
  dot: { width: 12, height: 12, borderRadius: 6 },
  legendText: { fontSize: 14, color: colors.text },
  floor: { fontSize: 13, color: colors.muted, marginLeft: 'auto' },
  simulated: { fontSize: 12, color: colors.muted },
  prompt: { fontSize: 17, fontWeight: '700', color: colors.info },
});
