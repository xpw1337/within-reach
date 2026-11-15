/**
 * GPS to scan-plan conversion for the responder route page. The same math as the app's
 * mobile/lib/georef.ts (`toEastNorth` + `latLngToPlan`), which owns the calibration: the app passes
 * the building's transform in the page URL (`geo=originLat,originLng,rotationDeg,tx,tz`).
 *
 *   x = tx + cos(r) * e - sin(r) * n
 *   z = tz - (sin(r) * e + cos(r) * n)
 *
 * where (e, n) are meters east and north of (originLat, originLng) and r is rotationDeg in radians.
 * (x, z) is the plan of twin_nodes (y-up, the Showcase SDK frame).
 */

export type GeorefTransform = {
  originLat: number;
  originLng: number;
  rotationDeg: number;
  tx: number;
  tz: number;
};

export type LatLng = { lat: number; lng: number };
export type PlanPoint = { x: number; z: number };

/** Mean Earth radius in meters (IUGG), as in the app. */
const EARTH_RADIUS_M = 6_371_008.8;
const DEG = Math.PI / 180;

export function latLngToPlan(t: GeorefTransform, p: LatLng): PlanPoint {
  const e = (p.lng - t.originLng) * DEG * EARTH_RADIUS_M * Math.cos(t.originLat * DEG);
  const n = (p.lat - t.originLat) * DEG * EARTH_RADIUS_M;
  const c = Math.cos(t.rotationDeg * DEG);
  const s = Math.sin(t.rotationDeg * DEG);
  return { x: t.tx + c * e - s * n, z: t.tz - (s * e + c * n) };
}

/** The `geo` URL value, or null when it is missing or not five plausible numbers. */
export function parseGeoParam(value: unknown): GeorefTransform | null {
  const v = Array.isArray(value) ? value[0] : value;
  if (typeof v !== "string" || v.length > 200) return null;
  const parts = v.split(",").map((s) => Number(s));
  if (parts.length !== 5 || parts.some((x) => !Number.isFinite(x))) return null;
  const [originLat, originLng, rotationDeg, tx, tz] = parts;
  if (Math.abs(originLat) > 90 || Math.abs(originLng) > 180 || Math.abs(rotationDeg) > 360) return null;
  if (Math.abs(tx) > 100_000 || Math.abs(tz) > 100_000) return null;
  return { originLat, originLng, rotationDeg, tx, tz };
}

type PlanNodeLike = { x: number | null; z: number | null };

/**
 * Index of the path's scan point nearest to `p` on the plan (x, z). Ties keep the earlier point.
 * -1 when no point of the path has a position.
 */
export function nearestPathIndex(path: string[], nodes: Map<string, PlanNodeLike>, p: PlanPoint): number {
  let best = -1;
  let bestD = Infinity;
  path.forEach((id, i) => {
    const n = nodes.get(id);
    if (!n || typeof n.x !== "number" || typeof n.z !== "number") return;
    const d = Math.hypot(n.x - p.x, n.z - p.z);
    if (d < bestD) {
      best = i;
      bestD = d;
    }
  });
  return best;
}

/** Distance on the plan from `p` to the path point at `i`, or Infinity without a position. */
export function distanceToPathPoint(path: string[], nodes: Map<string, PlanNodeLike>, i: number, p: PlanPoint): number {
  const n = i >= 0 ? nodes.get(path[i]) : undefined;
  if (!n || typeof n.x !== "number" || typeof n.z !== "number") return Infinity;
  return Math.hypot(n.x - p.x, n.z - p.z);
}
