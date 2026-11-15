// Indoor floor plan logic for the Alert screen: one floor of the building's scan graph, shortest
// paths over it, the simulated helper's start sweep, and walking along a route.
// Coordinates are the scan's model space in meters with y up (docs/CONTRACTS.md section 1), so the
// plan is drawn from x and z and distances here are real meters.

import type { AlertContext } from './alertData';
import type { CameraRow, TwinNodeRow } from './types';

/** Spec 9.4 WALK_SPEED_MPS default. Used only to animate the simulated helper dot. */
export const WALK_SPEED_MPS = 1.4;

export type PlanPoint = { x: number; z: number };
export type PlanNode = PlanPoint & { id: string };

export type FloorGraph = {
  floor: number;
  nodes: Map<string, PlanNode>;
  /** Symmetric adjacency, same-floor neighbors only. */
  adj: Map<string, string[]>;
  /** Unique undirected edges, for drawing the walkable area. */
  edges: [string, string][];
};

function placed(n: TwinNodeRow): n is TwinNodeRow & { x: number; z: number } {
  return Boolean(n.sweep_id) && typeof n.x === 'number' && typeof n.z === 'number';
}

/** Same rule as the dashboard's floor plan: a missing floor counts as floor 0. */
function floorOf(n: TwinNodeRow): number {
  return n.floor ?? 0;
}

/** The floor the camera is on: the camera row's floor, else the floor of the camera's sweep. */
export function cameraFloor(nodes: TwinNodeRow[], camera: CameraRow | null): number | null {
  if (!camera) return null;
  if (camera.floor != null) return camera.floor;
  const node = camera.sweep_id ? nodes.find((n) => n.sweep_id === camera.sweep_id) : undefined;
  return node ? floorOf(node) : null;
}

export function buildFloorGraph(rows: TwinNodeRow[], floor: number): FloorGraph {
  const nodes = new Map<string, PlanNode>();
  for (const r of rows) {
    if (placed(r) && floorOf(r) === floor) nodes.set(r.sweep_id, { id: r.sweep_id, x: r.x, z: r.z });
  }
  const sets = new Map<string, Set<string>>();
  for (const id of nodes.keys()) sets.set(id, new Set());
  for (const r of rows) {
    if (!nodes.has(r.sweep_id)) continue;
    for (const nb of r.neighbors ?? []) {
      if (nb === r.sweep_id || !nodes.has(nb)) continue;
      sets.get(r.sweep_id)!.add(nb);
      sets.get(nb)!.add(r.sweep_id);
    }
  }
  const adj = new Map<string, string[]>();
  const edges: [string, string][] = [];
  for (const [id, set] of sets) {
    const list = [...set].sort();
    adj.set(id, list);
    for (const nb of list) if (id < nb) edges.push([id, nb]);
  }
  return { floor, nodes, adj, edges };
}

export function distance(a: PlanPoint, b: PlanPoint): number {
  return Math.hypot(a.x - b.x, a.z - b.z);
}

/** Dijkstra from one sweep. Unreachable sweeps are absent from the result. */
function dijkstra(g: FloorGraph, source: string): { dist: Map<string, number>; prev: Map<string, string> } {
  const dist = new Map<string, number>();
  const prev = new Map<string, string>();
  if (!g.nodes.has(source)) return { dist, prev };
  dist.set(source, 0);
  const done = new Set<string>();
  // Floors have tens to a few hundred sweeps, so a linear scan for the next node is fine.
  for (;;) {
    let current: string | null = null;
    let best = Infinity;
    for (const [id, d] of dist) {
      if (!done.has(id) && (d < best || (d === best && current !== null && id < current))) {
        best = d;
        current = id;
      }
    }
    if (current === null) break;
    done.add(current);
    const here = g.nodes.get(current)!;
    for (const nb of g.adj.get(current) ?? []) {
      if (done.has(nb)) continue;
      const nd = best + distance(here, g.nodes.get(nb)!);
      const old = dist.get(nb);
      if (old === undefined || nd < old) {
        dist.set(nb, nd);
        prev.set(nb, current);
      }
    }
  }
  return { dist, prev };
}

/** Sweep ids from `from` to `to` over the floor graph, or null when they are not connected on this floor. */
export function shortestPath(g: FloorGraph, from: string, to: string): string[] | null {
  if (!g.nodes.has(from) || !g.nodes.has(to)) return null;
  if (from === to) return [from];
  const { prev } = dijkstra(g, from);
  if (!prev.has(to)) return null;
  const path = [to];
  let cur = to;
  while (cur !== from) {
    cur = prev.get(cur)!;
    path.push(cur);
  }
  return path.reverse();
}

/** Sweeps that can reach `target` over this floor's walkable links (including `target` itself). */
export function reachableFrom(g: FloorGraph, target: string): Set<string> {
  return g.nodes.has(target) ? new Set(hopCounts(g, target).keys()) : new Set();
}

function hopCounts(g: FloorGraph, source: string): Map<string, number> {
  const hops = new Map<string, number>([[source, 0]]);
  const queue = [source];
  for (let i = 0; i < queue.length; i += 1) {
    const id = queue[i];
    const h = hops.get(id)!;
    for (const nb of g.adj.get(id) ?? []) {
      if (!hops.has(nb)) {
        hops.set(nb, h + 1);
        queue.push(nb);
      }
    }
  }
  return hops;
}

/**
 * Deterministic start sweep for the simulated helper: on the far side of the AED from the person.
 * 1. Walk the graph outward from the AED sweep. Among sweeps 2 or 3 hops away that are farther from
 *    the person than the AED is, take the one farthest from the person.
 * 2. Otherwise take the AED's direct neighbor farthest from the person.
 * 3. Otherwise (the AED sweep has no neighbors on this floor) start at the AED itself.
 * "Farther from the person" is walking distance on the floor graph, or straight-line distance for a
 * sweep the person's sweep cannot reach on this floor. Ties go to the smaller sweep id.
 */
export function pickStartSweep(g: FloorGraph, aedSweep: string, personSweep: string): string | null {
  const aed = g.nodes.get(aedSweep);
  const person = g.nodes.get(personSweep);
  if (!aed || !person) return null;
  const fromPerson = dijkstra(g, personSweep).dist;
  const away = (id: string) => fromPerson.get(id) ?? distance(g.nodes.get(id)!, person);
  const aedAway = away(aedSweep);
  const hops = hopCounts(g, aedSweep);

  const farthest = (ids: string[]): string | null => {
    let best: string | null = null;
    let bestD = -Infinity;
    for (const id of [...ids].sort()) {
      const d = away(id);
      if (d > bestD) {
        best = id;
        bestD = d;
      }
    }
    return best;
  };

  const ring = [...hops].filter(([id, h]) => (h === 2 || h === 3) && id !== personSweep && away(id) > aedAway).map(([id]) => id);
  const fromRing = farthest(ring);
  if (fromRing) return fromRing;
  const neighbors = (g.adj.get(aedSweep) ?? []).filter((id) => id !== personSweep);
  return farthest(neighbors) ?? aedSweep;
}

/** Points for a list of sweep ids, skipping ids that are not on this floor. */
export function pointsOf(g: FloorGraph, ids: string[]): PlanPoint[] {
  const out: PlanPoint[] = [];
  for (const id of ids) {
    const n = g.nodes.get(id);
    if (n) out.push({ x: n.x, z: n.z });
  }
  return out;
}

/** A route between two sweeps: the graph path, or a straight segment if they are not connected here. */
export function routeBetween(g: FloorGraph, from: string, to: string): PlanPoint[] {
  const path = shortestPath(g, from, to);
  if (path) return pointsOf(g, path);
  return pointsOf(g, [from, to]);
}

export function polylineLength(pts: PlanPoint[]): number {
  let total = 0;
  for (let i = 1; i < pts.length; i += 1) total += distance(pts[i - 1], pts[i]);
  return total;
}

/** The point `s` meters along the polyline, clamped to its ends. */
export function pointAlong(pts: PlanPoint[], s: number): PlanPoint | null {
  if (pts.length === 0) return null;
  let left = Math.max(0, s);
  for (let i = 1; i < pts.length; i += 1) {
    const seg = distance(pts[i - 1], pts[i]);
    if (left <= seg && seg > 0) {
      const t = left / seg;
      return { x: pts[i - 1].x + (pts[i].x - pts[i - 1].x) * t, z: pts[i - 1].z + (pts[i].z - pts[i - 1].z) * t };
    }
    left -= seg;
  }
  return pts[pts.length - 1];
}

/** Everything the Alert screen draws on the indoor plan, worked out once per incident. */
export type AlertPlan = {
  graph: FloorGraph;
  /** The camera's sweep, where the person is. */
  personId: string;
  person: PlanPoint;
  /** The AED's sweep on this floor, when the AED is drawn. */
  aedId: string | null;
  /** The AED marker, when the building has an AED on this floor and a mapped AED route. */
  aed: PlanPoint | null;
  aedSimulated: boolean;
  /** An AED route is mapped (`camera_routes` target `aed`) and there is an AED row. */
  hasAedRoute: boolean;
  /** The AED is mapped but not on the camera's floor, so it cannot be drawn here. */
  aedOffFloor: boolean;
  /** The simulated start sweep (pickStartSweep), used when the start is not set from GPS or a tap. */
  defaultStartId: string | null;
  /** Simulated helper legs. Null when there is no AED on this floor to start from. */
  startToAed: PlanPoint[] | null;
  aedToPerson: PlanPoint[] | null;
  startToPerson: PlanPoint[] | null;
};

function withEnds(pts: PlanPoint[], first: PlanPoint | null, last: PlanPoint | null): PlanPoint[] {
  const out = [...pts];
  if (first && (out.length === 0 || distance(out[0], first) > 0.01)) out.unshift(first);
  if (last && (out.length === 0 || distance(out[out.length - 1], last) > 0.01)) out.push(last);
  return out;
}

/**
 * Builds the indoor plan from the alert context, or null when the building has no twin nodes or the
 * camera's sweep is not among them (the Alert screen then falls back to the outdoor map).
 */
export function buildAlertPlan(ctx: AlertContext | null): AlertPlan | null {
  if (!ctx || ctx.nodes.length === 0 || !ctx.camera?.sweep_id) return null;
  const floor = cameraFloor(ctx.nodes, ctx.camera);
  if (floor === null) return null;
  const graph = buildFloorGraph(ctx.nodes, floor);
  const personId = ctx.camera.sweep_id;
  const personNode = graph.nodes.get(personId);
  if (!personNode) return null;
  const person: PlanPoint = { x: personNode.x, z: personNode.z };

  const route = ctx.routes.find((r) => r.target === 'aed') ?? null;
  const asset = ctx.aed;
  const hasAedRoute = Boolean(asset && route && (route.path?.length ?? 0) > 0);
  const empty: AlertPlan = {
    graph,
    personId,
    person,
    aedId: null,
    aed: null,
    aedSimulated: false,
    hasAedRoute,
    aedOffFloor: false,
    defaultStartId: null,
    startToAed: null,
    aedToPerson: null,
    startToPerson: null,
  };
  if (!hasAedRoute || !asset || !route) return empty;

  const routePath = route.path ?? [];
  const aedId = asset.sweep_id ?? routePath[routePath.length - 1] ?? null;
  const aedNode = aedId ? graph.nodes.get(aedId) : undefined;
  const aedSimulated = (asset.flags ?? []).includes('simulated');
  if (!aedId || !aedNode) return { ...empty, aedSimulated, aedOffFloor: true };
  const aed: PlanPoint =
    typeof asset.x === 'number' && typeof asset.z === 'number' ? { x: asset.x, z: asset.z } : { x: aedNode.x, z: aedNode.z };

  // AED to the person: the census route reversed (it runs camera -> AED), else the floor graph path.
  const reversed = pointsOf(graph, [...routePath].reverse());
  const aedToPerson = withEnds(reversed.length >= 2 ? reversed : routeBetween(graph, aedId, personId), aed, person);

  const startId = pickStartSweep(graph, aedId, personId);
  const startToAed = startId ? withEnds(routeBetween(graph, startId, aedId), null, aed) : null;
  const startToPerson = startId ? routeBetween(graph, startId, personId) : null;

  return {
    ...empty,
    aedId,
    aed,
    aedSimulated,
    defaultStartId: startId,
    startToAed,
    aedToPerson,
    startToPerson,
  };
}

/**
 * The first leg from a chosen start sweep (from GPS or a tap): the shortest path on the floor graph to
 * the AED (AED runner) or to the person (everyone else). Null when there is nothing to walk to.
 */
export function legFromStart(plan: AlertPlan, startId: string, to: 'aed' | 'person'): PlanPoint[] | null {
  if (!plan.graph.nodes.has(startId)) return null;
  if (to === 'aed') {
    if (!plan.aedId || !plan.aed) return null;
    return withEnds(routeBetween(plan.graph, startId, plan.aedId), null, plan.aed);
  }
  return routeBetween(plan.graph, startId, plan.personId);
}

export type Projection = {
  width: number;
  height: number;
  toPx: (p: PlanPoint) => [number, number];
  /** The inverse of toPx: a point on the drawing back to plan meters (for "tap where you are"). */
  fromPx: (px: number, py: number) => PlanPoint;
};

/** Fits the floor's sweeps into `width`, capped at `maxHeight`, x to the right and z downward (as on the dashboard). */
export function project(g: FloorGraph, width: number, pad: number, maxHeight: number): Projection {
  let minX = Infinity;
  let maxX = -Infinity;
  let minZ = Infinity;
  let maxZ = -Infinity;
  for (const n of g.nodes.values()) {
    minX = Math.min(minX, n.x);
    maxX = Math.max(maxX, n.x);
    minZ = Math.min(minZ, n.z);
    maxZ = Math.max(maxZ, n.z);
  }
  const spanX = Math.max(maxX - minX, 1e-6);
  const spanZ = Math.max(maxZ - minZ, 1e-6);
  if (!Number.isFinite(minX) || (spanX <= 1e-6 && spanZ <= 1e-6)) {
    const height = Math.min(maxHeight, width);
    const only: PlanPoint = Number.isFinite(minX) ? { x: minX, z: minZ } : { x: 0, z: 0 };
    return { width, height, toPx: () => [width / 2, height / 2], fromPx: () => only };
  }
  let scale = (width - 2 * pad) / spanX;
  let height = spanZ * scale + 2 * pad;
  if (height > maxHeight) {
    scale = (maxHeight - 2 * pad) / spanZ;
    height = maxHeight;
  }
  height = Math.max(height, 120);
  const offsetX = (width - spanX * scale) / 2;
  const offsetZ = (height - spanZ * scale) / 2;
  return {
    width,
    height,
    toPx: (p) => [offsetX + (p.x - minX) * scale, offsetZ + (p.z - minZ) * scale],
    fromPx: (px, py) => ({ x: minX + (px - offsetX) / scale, z: minZ + (py - offsetZ) / scale }),
  };
}
