import { describe, expect, it } from "vitest";
import { cleanLeg, cleanSweepId, followStep, pathMeters, planLeg, reachableTo, shortestSweepPath, spokenMeters, type RouteNode } from "@/lib/routePlan";

// A small corridor: p (person) - a - b - d (AED), with a slower detour p - c - d.
const nodes: RouteNode[] = [
  { sweep_id: "p", x: 0, y: 0, z: 0, neighbors: ["a", "c"] },
  { sweep_id: "a", x: 3, y: 0, z: 0, neighbors: ["b"] },
  { sweep_id: "b", x: 6, y: 0, z: 0, neighbors: ["d"] },
  { sweep_id: "d", x: 9, y: 0, z: 0, neighbors: [] },
  { sweep_id: "c", x: 4.5, y: 0, z: 6, neighbors: ["d"] },
  { sweep_id: "island", x: 50, y: 0, z: 50, neighbors: [] },
  { sweep_id: "unplaced", x: null, y: null, z: null, neighbors: ["p"] },
];

describe("shortestSweepPath", () => {
  it("takes the shorter corridor and treats neighbors as two-way", () => {
    expect(shortestSweepPath(nodes, "p", "d")).toEqual(["p", "a", "b", "d"]);
    expect(shortestSweepPath(nodes, "d", "p")).toEqual(["d", "b", "a", "p"]);
  });

  it("returns null for unknown, unplaced or unconnected sweeps", () => {
    expect(shortestSweepPath(nodes, "p", "nowhere")).toBeNull();
    expect(shortestSweepPath(nodes, "unplaced", "p")).toBeNull();
    expect(shortestSweepPath(nodes, "p", "island")).toBeNull();
  });

  it("is a single sweep when start and end match", () => {
    expect(shortestSweepPath(nodes, "b", "b")).toEqual(["b"]);
  });
});

describe("planLeg", () => {
  const census = ["p", "c", "d"]; // the census route, deliberately not the graph's shortest
  const base = { nodes, personSweep: "p", aedSweep: "d", aedPath: census };

  it("uses the census route from the person to the AED when there is no start", () => {
    const leg = planLeg({ ...base, leg: "to_aed", from: null });
    expect(leg.path).toEqual(census);
    expect(leg.censusRoute).toBe(true);
    expect(leg.meters).toBeCloseTo(pathMeters(nodes, census)!, 6);
  });

  it("reverses the census route when bringing the AED back", () => {
    const leg = planLeg({ ...base, leg: "to_person", from: null });
    expect(leg.path).toEqual(["d", "c", "p"]);
    expect(leg.censusRoute).toBe(true);
  });

  it("routes over the graph from the helper's own start", () => {
    const leg = planLeg({ ...base, leg: "to_aed", from: "a" });
    expect(leg.path).toEqual(["a", "b", "d"]);
    expect(leg.censusRoute).toBe(false);
    expect(leg.meters).toBeCloseTo(6, 6);
  });

  it("goes to the person from their own sweep when no AED is mapped", () => {
    const leg = planLeg({ nodes, personSweep: "p", aedSweep: null, aedPath: null, leg: "to_person", from: null });
    expect(leg.path).toEqual(["p"]);
    expect(leg.meters).toBe(0);
  });

  it("is empty when the destination is unknown or unreachable", () => {
    expect(planLeg({ ...base, aedSweep: null, aedPath: null, leg: "to_aed", from: null }).path).toEqual([]);
    expect(planLeg({ ...base, leg: "to_person", from: "island" }).path).toEqual([]);
  });
});

describe("URL values", () => {
  it("accepts only plain sweep ids and the two legs", () => {
    expect(cleanSweepId("0f2a2fyf5iibscursb5gkyu9a")).toBe("0f2a2fyf5iibscursb5gkyu9a");
    expect(cleanSweepId(["s1", "s2"])).toBe("s1");
    expect(cleanSweepId("a b")).toBeNull();
    expect(cleanSweepId("<script>")).toBeNull();
    expect(cleanSweepId(undefined)).toBeNull();
    expect(cleanLeg("to_aed")).toBe("to_aed");
    expect(cleanLeg("to_person")).toBe("to_person");
    expect(cleanLeg("with_person")).toBeNull();
  });
});

describe("spokenMeters", () => {
  it("rounds like Python's round, which the speaker uses", () => {
    expect(spokenMeters(14.5)).toBe(14);
    expect(spokenMeters(15.5)).toBe(16);
    expect(spokenMeters(14.51)).toBe(15);
    expect(spokenMeters(14.49)).toBe(14);
    expect(spokenMeters(0)).toBe(0);
  });
});

describe("followStep", () => {
  const byId = new Map(nodes.map((n) => [n.sweep_id, n]));
  const candidates = nodes.filter((n) => n.sweep_id !== "island");
  const path = ["p", "a", "b", "d"];

  it("moves along the path when the helper is nearest a path point", () => {
    expect(followStep({ path, byId, candidates, at: 0, p: { x: 6.2, z: 0.3 } })).toEqual({ kind: "move", index: 2 });
  });

  it("re-plans from the helper's own spot when it is off the path", () => {
    expect(followStep({ path, byId, candidates, at: 0, p: { x: 4.4, z: 5.8 } })).toEqual({ kind: "reroute", sweep: "c" });
  });

  it("ignores small moves and staying put", () => {
    expect(followStep({ path, byId, candidates, at: 1, p: { x: 3.2, z: 0 } })).toBeNull();
    expect(followStep({ path, byId, candidates, at: 1, p: { x: 4.4, z: 0 } })).toBeNull(); // b is not 1 m closer than a
  });

  it("finds the sweeps that can reach the target", () => {
    expect([...reachableTo(nodes, "d")].sort()).toEqual(["a", "b", "c", "d", "p", "unplaced"]);
    expect([...reachableTo(nodes, "island")]).toEqual(["island"]);
  });
});
