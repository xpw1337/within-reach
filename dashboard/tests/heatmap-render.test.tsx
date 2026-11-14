// Renders the heatmap from a synthetic graph and checks the zone colors.
// Set HEATMAP_SNAPSHOT=<file.html> to also write the markup for a visual check.
import { writeFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { FloorHeatmap } from "@/components/building/FloorHeatmap";
import { boundsOf, indexCoverage } from "@/lib/heatmap";
import type { TwinNode } from "@/lib/rows";

const T = { walk_speed_mps: 1, aed_roundtrip_target_s: 40, ext_max_travel_m: 10, exit_max_travel_m: 30, yellow_fraction: 0.5 };

function grid(): TwinNode[] {
  const nodes: TwinNode[] = [];
  for (let i = 0; i < 8; i++) {
    for (let j = 0; j < 4; j++) {
      const id = `s${i}_${j}`;
      const neighbors = [`s${i + 1}_${j}`, `s${i - 1}_${j}`, `s${i}_${j + 1}`, `s${i}_${j - 1}`];
      nodes.push({
        building_id: "b",
        sweep_id: id,
        floor: 0,
        x: i * 3,
        y: 0,
        z: j * 3,
        neighbors,
        room_type: null,
        label: null,
        is_elevator: false,
        is_stairs: i === 7 && j === 3,
      });
    }
  }
  return nodes;
}

describe("FloorHeatmap", () => {
  const nodes = grid();
  // one-way seconds grow with distance from the AED at s0_0
  const coverage = nodes.flatMap((n) => [
    { sweep_id: n.sweep_id, asset_type: "aed", scenario: "current", time_s: (n.x as number) + (n.z as number) },
    { sweep_id: n.sweep_id, asset_type: "aed", scenario: "proposed", time_s: Math.min((n.x as number) + (n.z as number), Math.abs((n.x as number) - 21) + (n.z as number)) },
  ]);
  const assets = [
    { id: "a1", type: "aed" as const, sweep_id: "s0_0", floor: 0, x: null, z: null, source: "detected", flags: [], label: "front desk" },
    { id: "a2", type: "aed" as const, sweep_id: "s7_0", floor: 0, x: null, z: null, source: "proposed", flags: [], label: "proposed" },
  ];

  const render = (scenario: "current" | "proposed") =>
    renderToStaticMarkup(
      <FloorHeatmap
        nodes={nodes}
        assets={assets}
        index={indexCoverage(coverage)}
        thresholds={T}
        bounds={boundsOf(nodes)!}
        floor={0}
        type="aed"
        scenario={scenario}
        rippleFrom={{ x: 21, z: 0 }}
      />,
    );

  it("colors sweeps by zone and hides the proposed AED in the current scenario", () => {
    const html = render("current");
    // limit 20 s one way, yellow above 10 s: s0_0 (0 s) green, s3_1 (12 s) yellow, s7_3 (30 s) red
    expect(html).toContain("var(--zone-green)");
    expect(html).toContain("var(--zone-yellow)");
    expect(html).toContain("var(--zone-red)");
    expect(html).not.toContain("NEW AED");
    expect(html).toContain(">AED<");
  });

  it("shows the proposed AED and turns the far end green", () => {
    const current = render("current");
    const proposed = render("proposed");
    expect(proposed).toContain("NEW AED");
    const reds = (s: string) => s.split("var(--zone-red)").length - 1;
    expect(reds(proposed)).toBeLessThan(reds(current));
    if (process.env.HEATMAP_SNAPSHOT) {
      const css = `body{background:#090c11;margin:0;padding:24px;display:grid;grid-template-columns:1fr 1fr;gap:24px}
      :root{--zone-green:#2ec27e;--zone-yellow:#f5c542;--zone-red:#ff4d4f;--zone-unknown:#5b6676;--line-strong:#33415a;--faint:#5f6c7e;--accent:#5cc8ff;--danger:#ff4d4f}`;
      writeFileSync(process.env.HEATMAP_SNAPSHOT, `<html><style>${css}</style><body><div>${current}</div><div>${proposed}</div></body></html>`);
    }
  });
});
