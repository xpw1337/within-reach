// Floor plan for the calibration screen (app/calibrate.tsx). Draws the floor's walkable links, every
// calibration spot as a numbered circle (green once recorded) and the spot to stand on now, large and
// red with its name. When a calibration is in use it also draws where GPS puts the phone, with the
// accuracy the phone reports as a halo, a dashed line from there to the spot, and a north arrow taken
// from that calibration. The alert's plan is components/FloorPlan.tsx; both use lib/floorPlan.ts.

import { useMemo, useState } from 'react';
import { StyleSheet, Text, View, type LayoutChangeEvent } from 'react-native';
import Svg, { Circle, G, Line, Polygon, Rect, Text as SvgText } from 'react-native-svg';

import {
  CAL_PLAN_A11Y,
  CAL_PLAN_ALERT_START,
  CAL_PLAN_DONE,
  CAL_PLAN_NORTH,
  CAL_PLAN_TARGET,
  CAL_PLAN_TODO,
  CAL_PLAN_YOU,
  CAL_PLAN_YOU_OFF,
} from '../lib/copy';
import { project, type FloorGraph, type PlanPoint } from '../lib/floorPlan';
import { colors, space } from './theme';

const PAD = 30;
const MAX_HEIGHT = 420;
/** Keeps an off-plan GPS dot this many pixels inside the drawing's edge. */
const EDGE = 10;

const C = {
  bg: '#F8FAFC',
  walkable: '#E2E8F0',
  target: colors.primary,
  done: colors.ok,
  todo: '#64748B',
  you: colors.info,
  north: colors.text,
};

export type PlanSpot = { id: string; n: number; plan: PlanPoint; recorded: boolean };

type Props = {
  graph: FloorGraph;
  /** The calibration spots on this floor. */
  spots: PlanSpot[];
  /** The spot to stand on now, drawn large. Null on the overview. */
  targetId: string | null;
  targetName?: string | null;
  /** Where GPS puts the phone, converted with the calibration in use. Null without one or before a fix. */
  you: { point: PlanPoint; accuracyM: number | null } | null;
  /** The scan point an alert would start the helper at (check mode). */
  alertStart?: PlanPoint | null;
  /** The calibration in use, for the north arrow. Null hides the arrow. */
  rotationDeg: number | null;
  /** Small text at the end of the legend, for example the scan floor. */
  caption?: string | null;
};

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/**
 * North on the drawing. The plan is drawn x right and z down, and lib/georef.ts maps one meter north
 * to (x, z) += (-sin r, -cos r), so that is north's direction on screen.
 */
function northArrow(width: number, rotationDeg: number) {
  const r = (rotationDeg * Math.PI) / 180;
  const dx = -Math.sin(r);
  const dy = -Math.cos(r);
  const cx = width - 30;
  const cy = 34;
  const px = -dy;
  const py = dx;
  const tip: [number, number] = [cx + dx * 12, cy + dy * 12];
  const left: [number, number] = [cx - dx * 8 + px * 6, cy - dy * 8 + py * 6];
  const right: [number, number] = [cx - dx * 8 - px * 6, cy - dy * 8 - py * 6];
  const label: [number, number] = [clamp(cx + dx * 24, 8, width - 8), clamp(cy + dy * 24 + 5, 14, cy + 40)];
  return { cx, cy, points: [tip, left, right].map((p) => p.join(',')).join(' '), label };
}

export function CalibrationPlan({ graph, spots, targetId, targetName, you, alertStart, rotationDeg, caption }: Props) {
  const [width, setWidth] = useState(0);
  const onLayout = (e: LayoutChangeEvent) => setWidth(Math.round(e.nativeEvent.layout.width));
  const proj = useMemo(() => (width > 0 ? project(graph, width, PAD, MAX_HEIGHT) : null), [graph, width]);
  const target = spots.find((s) => s.id === targetId) ?? null;

  let youPx: [number, number] | null = null;
  let youOff = false;
  let haloR = 0;
  if (proj && you) {
    const [x, y] = proj.toPx(you.point);
    const cx = clamp(x, EDGE, proj.width - EDGE);
    const cy = clamp(y, EDGE, proj.height - EDGE);
    youOff = cx !== x || cy !== y;
    youPx = [cx, cy];
    const pxPerM = Math.abs(proj.toPx({ x: 1, z: 0 })[0] - proj.toPx({ x: 0, z: 0 })[0]);
    if (!youOff && you.accuracyM) haloR = Math.min(you.accuracyM * pxPerM, proj.width);
  }
  const north = proj && rotationDeg !== null ? northArrow(proj.width, rotationDeg) : null;

  const nameLabel = () => {
    if (!proj || !target || !targetName) return null;
    const [x, y] = proj.toPx(target.plan);
    const half = Math.min(proj.width / 2 - 4, targetName.length * 4.1 + 6);
    const lx = clamp(x, half + 2, proj.width - half - 2);
    const ly = y > 50 ? y - 38 : y + 50;
    // A white outline copy first, then the colored text on top, so the name stays readable over lines.
    return (
      <G>
        <SvgText x={lx} y={ly} fill="#FFFFFF" stroke="#FFFFFF" strokeWidth={5} fontSize={15} fontWeight="800" textAnchor="middle">
          {targetName}
        </SvgText>
        <SvgText x={lx} y={ly} fill={C.target} fontSize={15} fontWeight="800" textAnchor="middle">
          {targetName}
        </SvgText>
      </G>
    );
  };

  const hasDone = spots.some((s) => s.recorded && s.id !== targetId);
  const hasTodo = spots.some((s) => !s.recorded && s.id !== targetId);

  return (
    <View onLayout={onLayout} style={styles.wrap}>
      {proj ? (
        <Svg width={proj.width} height={proj.height} accessibilityLabel={CAL_PLAN_A11Y}>
          <Rect x={0} y={0} width={proj.width} height={proj.height} rx={12} fill={C.bg} />
          {graph.edges.map(([a, b]) => {
            const [x1, y1] = proj.toPx(graph.nodes.get(a)!);
            const [x2, y2] = proj.toPx(graph.nodes.get(b)!);
            return <Line key={`${a}-${b}`} x1={x1} y1={y1} x2={x2} y2={y2} stroke={C.walkable} strokeWidth={8} strokeLinecap="round" />;
          })}
          {[...graph.nodes.values()].map((n) => {
            const [cx, cy] = proj.toPx(n);
            return <Circle key={n.id} cx={cx} cy={cy} r={4} fill={C.walkable} />;
          })}

          {youPx && haloR > 0 ? (
            <Circle cx={youPx[0]} cy={youPx[1]} r={haloR} fill={C.you} fillOpacity={0.1} stroke={C.you} strokeOpacity={0.35} strokeWidth={1} />
          ) : null}
          {youPx && target ? (
            <Line
              x1={youPx[0]}
              y1={youPx[1]}
              x2={proj.toPx(target.plan)[0]}
              y2={proj.toPx(target.plan)[1]}
              stroke={C.you}
              strokeWidth={3}
              strokeDasharray="7,6"
              strokeLinecap="round"
            />
          ) : null}

          {spots
            .filter((s) => s.id !== targetId)
            .map((s) => {
              const [cx, cy] = proj.toPx(s.plan);
              return (
                <G key={s.id}>
                  <Circle cx={cx} cy={cy} r={12} fill={s.recorded ? C.done : C.todo} stroke="#FFFFFF" strokeWidth={2.5} />
                  <SvgText x={cx} y={cy + 4.5} fill="#FFFFFF" fontSize={13} fontWeight="800" textAnchor="middle">
                    {String(s.n)}
                  </SvgText>
                </G>
              );
            })}

          {alertStart ? (
            <Circle cx={proj.toPx(alertStart)[0]} cy={proj.toPx(alertStart)[1]} r={14} fill="none" stroke={C.you} strokeWidth={3} />
          ) : null}

          {target ? (
            <G>
              <Circle cx={proj.toPx(target.plan)[0]} cy={proj.toPx(target.plan)[1]} r={30} fill={C.target} fillOpacity={0.14} />
              <Circle cx={proj.toPx(target.plan)[0]} cy={proj.toPx(target.plan)[1]} r={23} fill="none" stroke={C.target} strokeOpacity={0.55} strokeWidth={2} />
              <Circle cx={proj.toPx(target.plan)[0]} cy={proj.toPx(target.plan)[1]} r={17} fill={C.target} stroke="#FFFFFF" strokeWidth={3} />
              <SvgText x={proj.toPx(target.plan)[0]} y={proj.toPx(target.plan)[1] + 6} fill="#FFFFFF" fontSize={17} fontWeight="800" textAnchor="middle">
                {String(target.n)}
              </SvgText>
            </G>
          ) : null}

          {youPx ? (
            <Circle
              cx={youPx[0]}
              cy={youPx[1]}
              r={8}
              fill={youOff ? '#FFFFFF' : C.you}
              stroke={youOff ? C.you : '#FFFFFF'}
              strokeWidth={3}
            />
          ) : null}

          {nameLabel()}

          {north ? (
            <G>
              <Circle cx={north.cx} cy={north.cy} r={16} fill="#FFFFFF" stroke={colors.border} strokeWidth={1} />
              <Polygon points={north.points} fill={C.north} />
              <SvgText x={north.label[0]} y={north.label[1]} fill={C.north} fontSize={12} fontWeight="800" textAnchor="middle">
                N
              </SvgText>
            </G>
          ) : null}
        </Svg>
      ) : (
        <View style={{ height: 200 }} />
      )}

      <View style={styles.legend}>
        {target ? <LegendDot color={C.target} text={CAL_PLAN_TARGET(target.n)} /> : null}
        {hasDone ? <LegendDot color={C.done} text={CAL_PLAN_DONE} /> : null}
        {hasTodo ? <LegendDot color={C.todo} text={CAL_PLAN_TODO} /> : null}
        {youPx ? <LegendDot color={C.you} hollow={youOff} text={youOff ? CAL_PLAN_YOU_OFF : CAL_PLAN_YOU} /> : null}
        {alertStart ? <LegendDot color={C.you} hollow text={CAL_PLAN_ALERT_START} /> : null}
        {north ? (
          <View style={styles.legendItem}>
            <Text style={styles.northKey}>N</Text>
            <Text style={styles.legendText}>{CAL_PLAN_NORTH}</Text>
          </View>
        ) : null}
        {caption ? <Text style={styles.caption}>{caption}</Text> : null}
      </View>
    </View>
  );
}

function LegendDot({ color, text, hollow }: { color: string; text: string; hollow?: boolean }) {
  return (
    <View style={styles.legendItem}>
      <View style={[styles.dot, hollow ? { borderWidth: 3, borderColor: color } : { backgroundColor: color }]} />
      <Text style={styles.legendText}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: space.sm },
  legend: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', columnGap: space.md, rowGap: space.xs },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: space.xs },
  dot: { width: 14, height: 14, borderRadius: 7 },
  legendText: { fontSize: 15, color: colors.text },
  northKey: { fontSize: 13, fontWeight: '800', color: colors.text },
  caption: { fontSize: 14, color: colors.muted, marginLeft: 'auto' },
});
