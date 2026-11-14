// Lays out and renders demo/fallback/building.json (a fixture used in tests
// only, never shown as data in the app). Skips if the file is absent.
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { FloorHeatmap } from "@/components/building/FloorHeatmap";
import { boundsOf, edgesOf, floorsOf, indexCoverage } from "@/lib/heatmap";
import type { TwinNode } from "@/lib/rows";

const file = path.resolve(__dirname, "../../demo/fallback/building.json");
const has = existsSync(file);

type Fallback = {
  twin_nodes: Omit<TwinNode, "building_id">[];
  assets: { type: string; sweep_id: string; floor: number; label?: string; source?: string }[];
};

describe.skipIf(!has)("fallback building layout", () => {
  const fb = has ? (JSON.parse(readFileSync(file, "utf8")) as Fallback) : { twin_nodes: [], assets: [] };
  const nodes = fb.twin_nodes.map((n) => ({ ...n, building_id: "fixture" })) as TwinNode[];

  it("has placed sweeps on every floor with edges", () => {
    expect(boundsOf(nodes)).not.toBeNull();
    for (const f of floorsOf(nodes)) expect(edgesOf(nodes, f).length).toBeGreaterThan(0);
  });

  it("renders every floor; exit signs show as exits; no coverage means unmapped", () => {
    const assets = fb.assets.map((a, i) => ({
      id: `a${i}`,
      type: a.type as never,
      sweep_id: a.sweep_id,
      floor: a.floor,
      x: null,
      z: null,
      source: a.source ?? "manual",
      flags: [],
      label: a.label ?? null,
    }));
    const T = { walk_speed_mps: 1.4, aed_roundtrip_target_s: 180, ext_max_travel_m: 22.9, exit_max_travel_m: 61, yellow_fraction: 2 / 3 };
    let html = "";
    for (const floor of floorsOf(nodes)) {
      html += renderToStaticMarkup(
        <FloorHeatmap
          nodes={nodes}
          assets={assets}
          index={indexCoverage([])}
          thresholds={T}
          bounds={boundsOf(nodes)!}
          floor={floor}
          type="exit"
          scenario="current"
        />,
      );
    }
    expect(html).not.toContain("var(--zone-red)");
    if (fb.assets.some((a) => a.type === "exit" || a.type === "exit_sign")) expect(html).toContain(">EXIT<");
    if (fb.assets.some((a) => a.type === "aed")) expect(html).toContain(">AED<");
  });
});
