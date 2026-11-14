// Pure logic tests on tiny synthetic inputs. These values are test fixtures,
// never shown in the app.
import { describe, expect, it } from "vitest";
import {
  boundsOf,
  edgesOf,
  floorsOf,
  hasScenario,
  indexCoverage,
  project,
  sweepZone,
  typicalSpacing,
} from "@/lib/heatmap";
import { formatLimit, formatMeasure, limitSeconds, measure, validThresholds, zone } from "@/lib/thresholds";

const T = {
  walk_speed_mps: 2,
  aed_roundtrip_target_s: 100,
  ext_max_travel_m: 20,
  exit_max_travel_m: 40,
  yellow_fraction: 0.5,
};

describe("thresholds", () => {
  it("expresses each limit as one-way seconds", () => {
    expect(limitSeconds(T, "aed")).toBe(50);
    expect(limitSeconds(T, "extinguisher")).toBe(10);
    expect(limitSeconds(T, "exit")).toBe(20);
  });

  it("matches shared/thresholds.zone on the boundaries", () => {
    expect(zone(T, "aed", 50)).toBe("yellow"); // equal to the limit is not red
    expect(zone(T, "aed", 50.01)).toBe("red");
    expect(zone(T, "aed", 25)).toBe("green"); // equal to the yellow start is not yellow
    expect(zone(T, "aed", 25.01)).toBe("yellow");
    expect(zone(T, "aed", 0)).toBe("green");
  });

  it("returns unknown for null time, missing thresholds or other types", () => {
    expect(zone(T, "aed", null)).toBe("unknown");
    expect(zone(null, "aed", 1)).toBe("unknown");
    expect(zone(T, "sprinkler", 1)).toBe("unknown");
  });

  it("shows AED as round trip and the others as one-way meters", () => {
    expect(formatMeasure("aed", 30, T)).toBe("60 s round trip");
    expect(formatMeasure("aed", 30, null)).toBe("60 s round trip");
    expect(formatMeasure("extinguisher", 7, T)).toBe("14 m one way");
    expect(formatMeasure("exit", 3, T)).toBe("6 m one way");
    expect(formatMeasure("exit", 3, null)).toBe("--");
    expect(formatMeasure("aed", null, T)).toBe("--");
    expect(measure("extinguisher", 1.2, T)?.value).toBe("2.4");
  });

  it("formats limits from the API values", () => {
    expect(formatLimit("aed", T)).toBe("100 s round trip");
    expect(formatLimit("extinguisher", T)).toBe("20 m one way");
    expect(formatLimit("exit", null)).toBe("--");
  });

  it("validates the thresholds shape", () => {
    expect(validThresholds(T)).toBe(true);
    expect(validThresholds({ ...T, yellow_fraction: 1.5 })).toBe(false);
    expect(validThresholds({ ...T, walk_speed_mps: "fast" })).toBe(false);
    expect(validThresholds(null)).toBe(false);
  });
});

const nodes = [
  { sweep_id: "a", floor: 0, x: 0, z: 0, neighbors: ["b"] },
  { sweep_id: "b", floor: 0, x: 4, z: 0, neighbors: ["a", "c", "s"] },
  { sweep_id: "c", floor: 0, x: 4, z: 2, neighbors: ["b"] },
  { sweep_id: "s", floor: 1, x: 4, z: 0, neighbors: ["b"] },
  { sweep_id: "u", floor: null, x: null, z: null, neighbors: [] },
];

describe("heatmap layout", () => {
  it("lists floors in order, null as floor 0", () => {
    expect(floorsOf(nodes)).toEqual([0, 1]);
  });

  it("bounds ignore unplaced nodes", () => {
    expect(boundsOf(nodes)).toEqual({ minX: 0, maxX: 4, minZ: 0, maxZ: 2 });
  });

  it("projects with the aspect ratio kept", () => {
    const p = project({ minX: 0, maxX: 4, minZ: 0, maxZ: 2 }, 420, 10);
    expect(p.scale).toBe(100);
    expect(p.height).toBe(220);
    expect(p.toPx(0, 0)).toEqual([10, 10]);
    expect(p.toPx(4, 2)).toEqual([410, 210]);
  });

  it("caps the height and centers horizontally", () => {
    const p = project({ minX: 0, maxX: 1, minZ: 0, maxZ: 10 }, 400, 0, 100);
    expect(p.height).toBe(100);
    expect(p.scale).toBe(10);
    expect(p.toPx(0, 0)[0]).toBe(195);
  });

  it("draws each same-floor edge once", () => {
    expect(edgesOf(nodes, 0)).toEqual([
      ["a", "b"],
      ["b", "c"],
    ]);
    expect(edgesOf(nodes, 1)).toEqual([]);
  });

  it("finds a typical spacing", () => {
    expect(typicalSpacing(nodes)).toBe(2);
  });
});

describe("coverage zones", () => {
  const idx = indexCoverage([
    { sweep_id: "a", asset_type: "aed", scenario: "current", time_s: 60 },
    { sweep_id: "b", asset_type: "aed", scenario: "current", time_s: null },
    { sweep_id: "a", asset_type: "aed", scenario: "proposed", time_s: 10 },
  ]);

  it("separates unmapped, unknown and measured sweeps", () => {
    expect(sweepZone(idx, T, "current", "aed", "a")).toBe("red");
    expect(sweepZone(idx, T, "current", "aed", "b")).toBe("unknown");
    expect(sweepZone(idx, T, "current", "aed", "c")).toBe("unmapped");
    expect(sweepZone(idx, T, "proposed", "aed", "a")).toBe("green");
  });

  it("knows which scenarios exist", () => {
    expect(hasScenario(idx, "proposed", "aed")).toBe(true);
    expect(hasScenario(idx, "proposed", "exit")).toBe(false);
  });
});
