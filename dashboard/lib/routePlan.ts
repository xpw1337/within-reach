import type { TwinNode } from "./rows";

/** Which leg of the responder's trip the 3D route shows (mobile/app/alert/[dispatchId].tsx). */
export type Leg = "to_aed" | "to_person";

export type RouteNode = Pick<TwinNode, "sweep_id" | "x" | "y" | "z" | "neighbors">;

export type PlannedLeg = {
  leg: Leg;
  /** Sweep ids from the start to the destination, both included. Empty when no route exists. */
  path: string[];
  start: string | null;
  end: string | null;
  /** Walking distance along the path in meters (straight lines between sweeps), null without a path. */
  meters: number | null;
  /** True when the path is the census route of the camera (the one the speaker reads out). */
  censusRoute: boolean;
};

const SWEEP_ID = /^[A-Za-z0-9_-]{1,64}$/;

/** Whole meters rounded like the speaker (Python's round: halves go to the even number), so the
 * page and the spoken "{n} meters" never differ by one. */
export function spokenMeters(meters: number): number {
  const floor = Math.floor(meters);
  const diff = meters - floor;
  if (Math.abs(diff - 0.5) < 1e-9) return floor % 2 === 0 ? floor : floor + 1;
  return Math.round(meters);
}

/** A sweep id from a URL, or null when it is missing or malformed. */
export function cleanSweepId(value: unknown): string | null {
  const v = Array.isArray(value) ? value[0] : value;
  return typeof v === "string" && SWEEP_ID.test(v) ? v : null;
}

export function cleanLeg(value: unknown): Leg | null {
  const v = Array.isArray(value) ? value[0] : value;
  return v === "to_aed" || v === "to_person" ? v : null;
}

function placed(n: RouteNode): n is RouteNode & { x: number; y: number; z: number } {
  return typeof n.x === "number" && typeof n.y === "number" && typeof n.z === "number";
}

function gap(a: RouteNode & { x: number; y: number; z: number }, b: RouteNode & { x: number; y: number; z: number }) {
  return Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
}

/**
 * Shortest walk between two sweeps over the scan graph: neighbors are edges (both directions, as
 * in census/core/graph.py), weighted by the 3D distance. Null when either end is unknown or the
 * two are not connected.
 */
export function shortestSweepPath(nodes: RouteNode[], from: string, to: string): string[] | null {
  const byId = new Map<string, RouteNode & { x: number; y: number; z: number }>();
  for (const n of nodes) if (placed(n)) byId.set(n.sweep_id, n);
  if (!byId.has(from) || !byId.has(to)) return null;
  if (from === to) return [from];

  const adj = new Map<string, Set<string>>();
  const link = (a: string, b: string) => {
    if (!adj.has(a)) adj.set(a, new Set());
    adj.get(a)!.add(b);
  };
  for (const n of byId.values()) {
    for (const m of n.neighbors ?? []) {
      if (m === n.sweep_id || !byId.has(m)) continue;
      link(n.sweep_id, m);
      link(m, n.sweep_id);
    }
  }

  const dist = new Map<string, number>([[from, 0]]);
  const prev = new Map<string, string>();
  const done = new Set<string>();
  // The graphs are small (tens to a few thousand sweeps): a linear scan for the next node is enough.
  while (true) {
    let cur: string | null = null;
    let best = Infinity;
    for (const [id, d] of dist) {
      if (!done.has(id) && (d < best || (d === best && cur !== null && id < cur))) {
        best = d;
        cur = id;
      }
    }
    if (cur === null) return null;
    if (cur === to) break;
    done.add(cur);
    const here = byId.get(cur)!;
    for (const m of adj.get(cur) ?? []) {
      if (done.has(m)) continue;
      const nd = best + gap(here, byId.get(m)!);
      if (nd < (dist.get(m) ?? Infinity)) {
        dist.set(m, nd);
        prev.set(m, cur);
      }
    }
  }

  const path = [to];
  while (path[path.length - 1] !== from) path.push(prev.get(path[path.length - 1])!);
  return path.reverse();
}

export function pathMeters(nodes: RouteNode[], path: string[]): number | null {
  if (path.length === 0) return null;
  const byId = new Map(nodes.filter(placed).map((n) => [n.sweep_id, n]));
  let total = 0;
  for (let i = 1; i < path.length; i++) {
    const a = byId.get(path[i - 1]);
    const b = byId.get(path[i]);
    if (!a || !b) return null;
    total += gap(a, b);
  }
  return total;
}

/**
 * The path for one leg of a responder's trip.
 *
 * - `to_aed`: from `from` (the helper's start in the app) to the AED. Without a start, from the
 *   person, which is the camera's census route (the AED runner usually starts at the collapse).
 * - `to_person`: from `from` to the person. Without a start, from the AED when one is mapped (the
 *   runner bringing it back, the census route reversed), else from the person's own sweep.
 *
 * The census route (`camera_routes.path`, person -> AED) is used whenever its ends match, so the
 * 3D route and the speaker's "{n} meters" describe the same walk.
 */
export function planLeg(input: {
  nodes: RouteNode[];
  leg: Leg;
  personSweep: string | null;
  aedSweep: string | null;
  aedPath: string[] | null;
  from: string | null;
}): PlannedLeg {
  const { nodes, leg, personSweep, aedSweep, from } = input;
  const census = input.aedPath && input.aedPath.length > 0 ? input.aedPath : null;
  const end = leg === "to_aed" ? aedSweep : personSweep;
  const start = from ?? (leg === "to_aed" ? personSweep : (aedSweep ?? personSweep));
  const none: PlannedLeg = { leg, path: [], start, end, meters: null, censusRoute: false };
  if (!start || !end) return none;

  if (census && census[0] === personSweep && census[census.length - 1] === aedSweep) {
    if (leg === "to_aed" && start === personSweep) {
      return { leg, path: [...census], start, end, meters: pathMeters(nodes, census), censusRoute: true };
    }
    if (leg === "to_person" && start === aedSweep) {
      const back = [...census].reverse();
      return { leg, path: back, start, end, meters: pathMeters(nodes, back), censusRoute: true };
    }
  }
  const path = shortestSweepPath(nodes, start, end);
  if (!path) return none;
  return { leg, path, start, end, meters: pathMeters(nodes, path), censusRoute: false };
}

/** Every sweep from which `target` can be walked to (neighbors as two-way edges). */
export function reachableTo(nodes: RouteNode[], target: string): Set<string> {
  const adj = new Map<string, Set<string>>();
  const link = (a: string, b: string) => {
    if (!adj.has(a)) adj.set(a, new Set());
    adj.get(a)!.add(b);
  };
  const ids = new Set(nodes.map((n) => n.sweep_id));
  for (const n of nodes) {
    for (const m of n.neighbors ?? []) {
      if (m === n.sweep_id || !ids.has(m)) continue;
      link(n.sweep_id, m);
      link(m, n.sweep_id);
    }
  }
  const seen = new Set<string>();
  if (!ids.has(target)) return seen;
  const queue = [target];
  seen.add(target);
  while (queue.length) {
    const cur = queue.shift()!;
    for (const m of adj.get(cur) ?? []) {
      if (!seen.has(m)) {
        seen.add(m);
        queue.push(m);
      }
    }
  }
  return seen;
}

type FollowNode = { sweep_id: string; x: number | null; z: number | null };

/**
 * Where the 3D view should go for a new position of the helper (plan meters): the scan point nearest
 * to them among `candidates` (the leg's floor, able to reach the leg's end). If it is on the current
 * path, move there; if not, re-plan the leg from it. Nothing when it is not at least `minGainM`
 * closer than the point the view is at now, so GPS or step jitter does not flip the view.
 */
export function followStep(args: {
  path: string[];
  byId: Map<string, { x: number | null; z: number | null }>;
  candidates: FollowNode[];
  at: number;
  p: { x: number; z: number };
  minGainM?: number;
}): { kind: "move"; index: number } | { kind: "reroute"; sweep: string } | null {
  const { path, byId, candidates, at, p, minGainM = 1 } = args;
  let near: FollowNode | null = null;
  let nearD = Infinity;
  for (const n of candidates) {
    if (typeof n.x !== "number" || typeof n.z !== "number") continue;
    const d = Math.hypot(n.x - p.x, n.z - p.z);
    if (d < nearD) {
      near = n;
      nearD = d;
    }
  }
  if (!near) return null;
  const cur = at >= 0 && at < path.length ? byId.get(path[at]) : undefined;
  const curD = cur && typeof cur.x === "number" && typeof cur.z === "number" ? Math.hypot(cur.x - p.x, cur.z - p.z) : Infinity;
  if (nearD + minGainM > curD) return null;
  const i = path.indexOf(near.sweep_id);
  if (i >= 0) return i === at ? null : { kind: "move", index: i };
  return { kind: "reroute", sweep: near.sweep_id };
}
