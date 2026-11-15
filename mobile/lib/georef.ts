// Georeference: phone GPS (lat/lng) to the floor plan's (x, z) for one building, and the
// calibration math that solves it from a few spots where the scan position is known.
//
// Pure: no React, no native modules and only `import type`, so plain Node can run it directly
// (`npm run check:georef`, scripts/check-georef.mjs).
//
// Handedness (worked out once, not fitted, so a mirror can never sneak in):
// - twin_nodes are y-up. data/matterport.py converts the Matterport Model API position (z-up) to the
//   Showcase SDK frame as sdk = (x, z, -y). That map has determinant +1, so it keeps handedness, and
//   the SDK frame is three.js, which is right-handed. So the Model API frame is right-handed z-up too.
// - In a right-handed z-up frame, the horizontal axes (X, Y) seen from above are a plain rotation of
//   (east, north): no mirror. Stored plan coordinates are x = X and z = -Y.
// - So (east, north) -> (x, -z) is a proper rotation, and (east, north) -> (x, z) is a rotation plus
//   a flip of z. With rotation 0, east is +x and north is -z.
// - components/FloorPlan.tsx (project in lib/floorPlan.ts) draws x to the right and z downward. Up on
//   the screen is -z = Y, so the drawn plan is a true top view, rotated but never mirrored. With
//   rotation 0 it would be a north-up map with east on the right.
//
// The fit is rigid: rotation and translation only. Scale stays 1 because the scan is in meters.

import type { PlanNode, PlanPoint } from './floorPlan';

/** Mean Earth radius in meters (IUGG). The equirectangular approximation below is fine over a building. */
export const EARTH_RADIUS_M = 6_371_008.8;

/**
 * GPS start: the phone's reported accuracy must be this good or better, in meters. A judgment call for
 * this demo (a floor here is about 25 m across), not a standard or a measured figure.
 */
export const MAX_START_ACCURACY_M = 15;

/**
 * GPS start: the converted point must be within this many meters of a sweep on the camera's floor, or
 * the fix is treated as off the map. Also a judgment call for this demo, not a standard.
 */
export const MAX_SNAP_DISTANCE_M = 15;

export type LatLng = { lat: number; lng: number };

/** Local meters east and north of an origin. */
export type EastNorth = { e: number; n: number };

/**
 * One building's transform:
 *   x = tx + cos(r) * e - sin(r) * n
 *   z = tz - (sin(r) * e + cos(r) * n)
 * where (e, n) are meters east and north of (originLat, originLng) and r is rotationDeg in radians:
 * the counterclockwise angle, seen from above, from east to the plan's +x axis.
 */
export type GeorefTransform = {
  originLat: number;
  originLng: number;
  rotationDeg: number;
  tx: number;
  tz: number;
};

/** A solved calibration as stored on the phone or in lib/georefDefaults.ts. */
export type Georef = GeorefTransform & {
  /** Date the spots were recorded, YYYY-MM-DD. */
  calibratedAt: string;
  /** How many spots the transform was solved from. */
  spots: number;
  /** Root mean square of the per-spot residuals in meters, from the calibration itself. */
  rmsM: number;
};

const DEG = Math.PI / 180;

export function toEastNorth(origin: LatLng, p: LatLng): EastNorth {
  return {
    e: (p.lng - origin.lng) * DEG * EARTH_RADIUS_M * Math.cos(origin.lat * DEG),
    n: (p.lat - origin.lat) * DEG * EARTH_RADIUS_M,
  };
}

export function fromEastNorth(origin: LatLng, en: EastNorth): LatLng {
  return {
    lat: origin.lat + en.n / (EARTH_RADIUS_M * DEG),
    lng: origin.lng + en.e / (EARTH_RADIUS_M * DEG * Math.cos(origin.lat * DEG)),
  };
}

export function latLngToPlan(t: GeorefTransform, p: LatLng): PlanPoint {
  const { e, n } = toEastNorth({ lat: t.originLat, lng: t.originLng }, p);
  const c = Math.cos(t.rotationDeg * DEG);
  const s = Math.sin(t.rotationDeg * DEG);
  return { x: t.tx + c * e - s * n, z: t.tz - (s * e + c * n) };
}

export function planToLatLng(t: GeorefTransform, p: PlanPoint): LatLng {
  const c = Math.cos(t.rotationDeg * DEG);
  const s = Math.sin(t.rotationDeg * DEG);
  // Back to the proper (unmirrored) frame q = (x, -z), then rotate by -r.
  const qx = p.x - t.tx;
  const qy = t.tz - p.z;
  return fromEastNorth({ lat: t.originLat, lng: t.originLng }, { e: c * qx + s * qy, n: -s * qx + c * qy });
}

/** Angle in degrees normalized to (-180, 180]. */
export function normalizeDeg(deg: number): number {
  let d = deg % 360;
  if (d <= -180) d += 360;
  if (d > 180) d -= 360;
  return d;
}

/** One calibration spot: where the phone said it was, and the scan position of the sweep it stood on. */
export type CalibrationSpot = { id: string; fix: LatLng; plan: PlanPoint };

export type SpotResidual = { id: string; errorM: number };

export type CalibrationSolve = {
  transform: GeorefTransform;
  residuals: SpotResidual[];
  rmsM: number;
  /**
   * The same fit with z flipped (the wrong handedness), only as a diagnostic. With 3 or more spots
   * that are not in a line, a mirrored fit that is much better than the real one means something is
   * off (wrong spots, or a frame convention we got wrong). With 2 spots both fits are exact, so this
   * says nothing and is null.
   */
  mirroredRmsM: number | null;
};

type Pair = { p: EastNorth; q: { x: number; y: number } };

/** Least-squares rotation + translation taking p to q (2D Procrustes, no scale, no reflection). */
function fitRigid(pairs: Pair[]): { theta: number; t: { x: number; y: number } } | null {
  const k = pairs.length;
  let pe = 0;
  let pn = 0;
  let qx = 0;
  let qy = 0;
  for (const { p, q } of pairs) {
    pe += p.e;
    pn += p.n;
    qx += q.x;
    qy += q.y;
  }
  pe /= k;
  pn /= k;
  qx /= k;
  qy /= k;
  let dot = 0;
  let cross = 0;
  for (const { p, q } of pairs) {
    const a = { x: p.e - pe, y: p.n - pn };
    const b = { x: q.x - qx, y: q.y - qy };
    dot += a.x * b.x + a.y * b.y;
    cross += a.x * b.y - a.y * b.x;
  }
  if (Math.hypot(dot, cross) < 1e-9) return null;
  const theta = Math.atan2(cross, dot);
  const c = Math.cos(theta);
  const s = Math.sin(theta);
  return { theta, t: { x: qx - (c * pe - s * pn), y: qy - (s * pe + c * pn) } };
}

function residualsOf(t: GeorefTransform, spots: CalibrationSpot[]): SpotResidual[] {
  return spots.map((spot) => {
    const got = latLngToPlan(t, spot.fix);
    return { id: spot.id, errorM: Math.hypot(got.x - spot.plan.x, got.z - spot.plan.z) };
  });
}

function rms(values: number[]): number {
  return values.length ? Math.sqrt(values.reduce((sum, v) => sum + v * v, 0) / values.length) : 0;
}

/**
 * Solves the transform from two or more spots (least squares when there are more than two). The
 * origin is the mean of the fixes, which keeps the numbers small. Returns null with fewer than two
 * spots, or when the fixes or the scan positions all coincide (no direction to fit).
 */
export function solveCalibration(spots: CalibrationSpot[]): CalibrationSolve | null {
  if (spots.length < 2) return null;
  const origin: LatLng = {
    lat: spots.reduce((sum, s) => sum + s.fix.lat, 0) / spots.length,
    lng: spots.reduce((sum, s) => sum + s.fix.lng, 0) / spots.length,
  };
  const en = spots.map((s) => toEastNorth(origin, s.fix));
  // Proper frame: q = (x, -z). See the handedness note at the top of the file.
  const fit = fitRigid(spots.map((s, i) => ({ p: en[i], q: { x: s.plan.x, y: -s.plan.z } })));
  if (!fit) return null;
  const transform: GeorefTransform = {
    originLat: origin.lat,
    originLng: origin.lng,
    rotationDeg: normalizeDeg(fit.theta / DEG),
    tx: fit.t.x,
    tz: -fit.t.y,
  };
  const residuals = residualsOf(transform, spots);

  let mirroredRmsM: number | null = null;
  if (spots.length >= 3) {
    const mirrored = fitRigid(spots.map((s, i) => ({ p: en[i], q: { x: s.plan.x, y: s.plan.z } })));
    if (mirrored) {
      const c = Math.cos(mirrored.theta);
      const s = Math.sin(mirrored.theta);
      mirroredRmsM = rms(
        spots.map((spot, i) => {
          const x = mirrored.t.x + c * en[i].e - s * en[i].n;
          const z = mirrored.t.y + s * en[i].e + c * en[i].n;
          return Math.hypot(x - spot.plan.x, z - spot.plan.z);
        }),
      );
    }
  }
  return { transform, residuals, rmsM: rms(residuals.map((r) => r.errorM)), mirroredRmsM };
}

/** Distance in meters between two fixes, with the same flat approximation as the transform. */
export function fixDistanceM(a: LatLng, b: LatLng): number {
  const { e, n } = toEastNorth(a, b);
  return Math.hypot(e, n);
}

/** The node closest to `p` (ties go to the smaller id), or null for an empty list. */
export function nearestNode(nodes: Iterable<PlanNode>, p: PlanPoint): { node: PlanNode; distanceM: number } | null {
  let best: PlanNode | null = null;
  let bestD = Infinity;
  for (const node of nodes) {
    const d = Math.hypot(node.x - p.x, node.z - p.z);
    if (d < bestD || (d === bestD && best !== null && node.id < best.id)) {
      best = node;
      bestD = d;
    }
  }
  return best ? { node: best, distanceM: bestD } : null;
}

export type StartFix = { lat: number; lng: number; accuracyM: number | null };

export type StartVerdict =
  | { ok: true; sweepId: string; accuracyM: number; point: PlanPoint; snapM: number }
  | { ok: false; reason: 'no_accuracy' | 'poor_accuracy' | 'off_map' | 'no_sweeps'; accuracyM: number | null; point: PlanPoint | null };

/**
 * The accuracy rule for starting the helper dot from GPS:
 * - the phone must report an accuracy, no worse than MAX_START_ACCURACY_M;
 * - the converted point must be within MAX_SNAP_DISTANCE_M of a sweep on the floor (`floorNodes`);
 * - it then snaps to the nearest sweep that can reach the leg's target (`reachable`), which must also
 *   be within MAX_SNAP_DISTANCE_M.
 */
export function judgeStartFix(
  t: GeorefTransform,
  fix: StartFix,
  floorNodes: PlanNode[],
  reachable: (id: string) => boolean,
): StartVerdict {
  const accuracyM = fix.accuracyM;
  if (accuracyM === null || !Number.isFinite(accuracyM) || accuracyM <= 0) return { ok: false, reason: 'no_accuracy', accuracyM: null, point: null };
  const point = latLngToPlan(t, fix);
  if (accuracyM > MAX_START_ACCURACY_M) return { ok: false, reason: 'poor_accuracy', accuracyM, point };
  const anyNear = nearestNode(floorNodes, point);
  if (!anyNear) return { ok: false, reason: 'no_sweeps', accuracyM, point };
  if (anyNear.distanceM > MAX_SNAP_DISTANCE_M) return { ok: false, reason: 'off_map', accuracyM, point };
  const snap = nearestNode(
    floorNodes.filter((n) => reachable(n.id)),
    point,
  );
  if (!snap || snap.distanceM > MAX_SNAP_DISTANCE_M) return { ok: false, reason: 'off_map', accuracyM, point };
  return { ok: true, sweepId: snap.node.id, accuracyM, point, snapM: snap.distanceM };
}

/** Today's date as YYYY-MM-DD in the phone's time zone. */
export function localDate(d: Date = new Date()): string {
  const pad = (v: number) => String(v).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** The text the calibration screen shows to paste into lib/georefDefaults.ts. */
export function defaultsSnippet(key: string, g: Georef): string {
  const r = (v: number, digits: number) => Number(v.toFixed(digits));
  return [
    `  '${key}': {`,
    `    originLat: ${r(g.originLat, 8)},`,
    `    originLng: ${r(g.originLng, 8)},`,
    `    rotationDeg: ${r(g.rotationDeg, 2)},`,
    `    tx: ${r(g.tx, 3)},`,
    `    tz: ${r(g.tz, 3)},`,
    `    calibratedAt: '${g.calibratedAt}',`,
    `    spots: ${g.spots},`,
    `    rmsM: ${r(g.rmsM, 2)},`,
    `  },`,
  ].join('\n');
}
