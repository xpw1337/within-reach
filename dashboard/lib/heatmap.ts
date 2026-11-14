// Pure layout logic for the 2D floor heatmap: sweeps are drawn from model-space
// x and z (y is up, docs/CONTRACTS.md section 1). No React, no network.
import { zone, type Thresholds, type Zone } from "./thresholds";

export type PlanNode = {
  sweep_id: string | null;
  floor: number | null;
  x: number | null;
  z: number | null;
  neighbors: string[];
  is_stairs?: boolean | null;
  is_elevator?: boolean | null;
};

export type CoverageLike = {
  sweep_id: string | null;
  asset_type: string | null;
  scenario: string | null;
  time_s: number | null;
};

export type Bounds = { minX: number; maxX: number; minZ: number; maxZ: number };
export type Projection = { width: number; height: number; scale: number; toPx: (x: number, z: number) => [number, number] };

export function floorOf(n: { floor: number | null }): number {
  return n.floor ?? 0;
}

export function floorsOf(nodes: { floor: number | null }[]): number[] {
  return [...new Set(nodes.map(floorOf))].sort((a, b) => a - b);
}

function placed(n: PlanNode): n is PlanNode & { sweep_id: string; x: number; z: number } {
  return Boolean(n.sweep_id) && typeof n.x === "number" && typeof n.z === "number";
}

/** Bounds over all floors, so the plan does not shift when switching floors. */
export function boundsOf(nodes: PlanNode[]): Bounds | null {
  const ps = nodes.filter(placed);
  if (ps.length === 0) return null;
  let minX = Infinity;
  let maxX = -Infinity;
  let minZ = Infinity;
  let maxZ = -Infinity;
  for (const n of ps) {
    minX = Math.min(minX, n.x);
    maxX = Math.max(maxX, n.x);
    minZ = Math.min(minZ, n.z);
    maxZ = Math.max(maxZ, n.z);
  }
  return { minX, maxX, minZ, maxZ };
}

/** Fit the bounds into a box of the given width, keeping the aspect ratio. */
export function project(b: Bounds, width: number, pad: number, maxHeight = width): Projection {
  const spanX = Math.max(b.maxX - b.minX, 1e-6);
  const spanZ = Math.max(b.maxZ - b.minZ, 1e-6);
  const innerW = width - 2 * pad;
  let scale = innerW / spanX;
  let height = spanZ * scale + 2 * pad;
  if (height > maxHeight) {
    scale = (maxHeight - 2 * pad) / spanZ;
    height = maxHeight;
  }
  if (b.maxX - b.minX < 1e-6 && b.maxZ - b.minZ < 1e-6) {
    // A single point: center it.
    return { width, height: maxHeight, scale: 1, toPx: () => [width / 2, maxHeight / 2] };
  }
  const offsetX = (width - spanX * scale) / 2;
  return {
    width,
    height,
    scale,
    toPx: (x, z) => [offsetX + (x - b.minX) * scale, pad + (z - b.minZ) * scale],
  };
}

/** Unique neighbor pairs on one floor where both ends are placed. */
export function edgesOf(nodes: PlanNode[], floor: number): [string, string][] {
  const onFloor = new Map<string, PlanNode>();
  for (const n of nodes) if (placed(n) && floorOf(n) === floor) onFloor.set(n.sweep_id, n);
  const seen = new Set<string>();
  const out: [string, string][] = [];
  for (const [id, n] of onFloor) {
    for (const m of n.neighbors ?? []) {
      if (!onFloor.has(m) || m === id) continue;
      const k = id < m ? `${id}|${m}` : `${m}|${id}`;
      if (seen.has(k)) continue;
      seen.add(k);
      out.push(id < m ? [id, m] : [m, id]);
    }
  }
  return out;
}

/** Median distance from each placed node to its nearest neighbor on the same floor, in model meters. */
export function typicalSpacing(nodes: PlanNode[]): number | null {
  const ps = nodes.filter(placed);
  if (ps.length < 2) return null;
  const d: number[] = [];
  for (const a of ps) {
    let best = Infinity;
    for (const b of ps) {
      if (a === b || floorOf(a) !== floorOf(b)) continue;
      const dd = Math.hypot(a.x - b.x, a.z - b.z);
      if (dd > 1e-6 && dd < best) best = dd;
    }
    if (Number.isFinite(best)) d.push(best);
  }
  if (d.length === 0) return null;
  d.sort((x, y) => x - y);
  return d[Math.floor(d.length / 2)];
}

export function coverageKey(scenario: string, type: string, sweepId: string): string {
  return `${scenario}|${type}|${sweepId}`;
}

/** scenario|type|sweep -> time_s. A present key with null time means "no asset visible or unreachable". */
export function indexCoverage(rows: CoverageLike[]): Map<string, number | null> {
  const m = new Map<string, number | null>();
  for (const r of rows) {
    if (!r.sweep_id || !r.asset_type) continue;
    m.set(coverageKey(r.scenario ?? "current", r.asset_type, r.sweep_id), r.time_s);
  }
  return m;
}

export function hasScenario(index: Map<string, number | null>, scenario: string, type: string): boolean {
  const prefix = `${scenario}|${type}|`;
  for (const k of index.keys()) if (k.startsWith(prefix)) return true;
  return false;
}

export type SweepZone = Zone | "unmapped";

/** Zone of one sweep, or "unmapped" when the census wrote no coverage row for it. */
export function sweepZone(
  index: Map<string, number | null>,
  t: Thresholds | null,
  scenario: string,
  type: string,
  sweepId: string,
): SweepZone {
  const k = coverageKey(scenario, type, sweepId);
  if (!index.has(k)) return "unmapped";
  return zone(t, type, index.get(k) ?? null);
}

export function zoneCounts(zones: SweepZone[]): Record<SweepZone, number> {
  const c: Record<SweepZone, number> = { green: 0, yellow: 0, red: 0, unknown: 0, unmapped: 0 };
  for (const z of zones) c[z] += 1;
  return c;
}

export const ZONE_COLORS: Record<SweepZone, string> = {
  green: "var(--zone-green)",
  yellow: "var(--zone-yellow)",
  red: "var(--zone-red)",
  unknown: "var(--zone-unknown)",
  unmapped: "transparent",
};
