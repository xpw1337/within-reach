// Fixture and demo buildings, and demo props placed by the team
// (demo/PLANTED_AED.md). Every value here is a synthetic test fixture.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { FlagsList } from "@/components/building/BuildingFacts";
import { FloorHeatmap } from "@/components/building/FloorHeatmap";
import { ZoneLegend } from "@/components/building/ZoneLegend";
import { readRunBuildingIds } from "@/lib/contracts";
import { assetDisplayLabel, copy, onlySimulatedOfType, simulatedLabel } from "@/lib/copy";
import { boundsOf, indexCoverage } from "@/lib/heatmap";
import {
  isCensusRun,
  isExcludedFromCensus,
  isSimulated,
  nonCensusFilter,
  nonCensusKind,
  type Asset,
  type TwinNode,
} from "@/lib/rows";

describe("census exclusion", () => {
  it("excludes the FALLBACK- fixture and DEMO- venue with one helper", () => {
    expect(isExcludedFromCensus({ costar_property_id: "FALLBACK-1" })).toBe(true);
    expect(isExcludedFromCensus({ costar_property_id: "DEMO-RABINOWITZ" })).toBe(true);
    expect(nonCensusKind({ costar_property_id: "FALLBACK-1" })).toBe("fixture");
    expect(nonCensusKind({ costar_property_id: "DEMO-RABINOWITZ" })).toBe("demo");
  });

  it("keeps census buildings and missing ids", () => {
    expect(isExcludedFromCensus({ costar_property_id: "12345678" })).toBe(false);
    // prefix only, case sensitive, not a substring match
    expect(isExcludedFromCensus({ costar_property_id: "X-DEMO-1" })).toBe(false);
    expect(isExcludedFromCensus({ costar_property_id: "demo-1" })).toBe(false);
    expect(isExcludedFromCensus({ costar_property_id: null })).toBe(false);
    expect(isExcludedFromCensus(null)).toBe(false);
    expect(nonCensusKind(undefined)).toBeNull();
  });

  it("builds the database filter from the same prefixes", () => {
    expect(nonCensusFilter()).toBe("costar_property_id.like.FALLBACK-*,costar_property_id.like.DEMO-*");
  });

  it("hides a run only when every building it touched is excluded", () => {
    const excluded = new Set(["demo-b", "fixture-b"]);
    expect(isCensusRun([], excluded)).toBe(true);
    expect(isCensusRun(["demo-b"], excluded)).toBe(false);
    expect(isCensusRun(["demo-b", "fixture-b"], excluded)).toBe(false);
    expect(isCensusRun(["demo-b", "census-b"], excluded)).toBe(true);
    expect(isCensusRun(["census-b"], excluded)).toBe(true);
  });

  it("reads building ids from run notes defensively", () => {
    expect(readRunBuildingIds(JSON.stringify({ budget_usd: 5, building_ids: ["b1", 3, null, "b2"] }))).toEqual(["b1", "b2"]);
    expect(readRunBuildingIds(JSON.stringify({ building_ids: null }))).toEqual([]);
    expect(readRunBuildingIds("plain text note")).toEqual([]);
    expect(readRunBuildingIds(null)).toEqual([]);
  });
});

const demoAed = { type: "aed" as const, label: "lobby", flags: ["simulated"], source: "manual" };

describe("simulated label", () => {
  it("names a demo prop as placed by the team, never as detected or visible in the scan", () => {
    expect(isSimulated(demoAed)).toBe(true);
    expect(isSimulated({ flags: ["blocked_exit"] })).toBe(false);
    expect(isSimulated({ flags: null })).toBe(false);
    expect(simulatedLabel("aed")).toBe("Demo AED (placed by team)");
    expect(assetDisplayLabel(demoAed)).toBe("Demo AED (placed by team)");
    expect(assetDisplayLabel({ type: "aed", label: "front desk", flags: [] })).toBe("front desk");
    expect(assetDisplayLabel({ type: "aed", label: null, flags: null })).toBe("AED");
    for (const text of [simulatedLabel("aed"), copy.simulatedNotice, copy.simulatedNotCensus, copy.simulatedRoute]) {
      expect(text).not.toMatch(/detected|visible in the scan/i);
    }
  });

  it("says when all equipment of a type is a demo prop", () => {
    const real = { type: "aed", source: "detected", flags: [] };
    const proposed = { type: "aed", source: "proposed", flags: [] };
    expect(onlySimulatedOfType([demoAed], "aed")).toBe(true);
    expect(onlySimulatedOfType([demoAed, proposed], "aed")).toBe(true);
    expect(onlySimulatedOfType([demoAed, real], "aed")).toBe(false);
    expect(onlySimulatedOfType([], "aed")).toBe(false);
    expect(copy.unknownZone("aed", true, true)).toBe("Not connected in the scan: no route to the Demo AED (placed by team)");
    expect(copy.unknownZone("aed", false, false)).toBe("No AED visible in the scan");
  });
});

function nodes(): TwinNode[] {
  return [0, 1, 2].map((i) => ({
    building_id: "b",
    sweep_id: `s${i}`,
    floor: 0,
    x: i * 3,
    y: 0,
    z: 0,
    neighbors: [`s${i - 1}`, `s${i + 1}`],
    room_type: null,
    label: null,
    is_elevator: false,
    is_stairs: false,
  }));
}

describe("demo props on screen", () => {
  it("draws a demo AED with a dashed DEMO marker and the demo label", () => {
    const n = nodes();
    const html = renderToStaticMarkup(
      <FloorHeatmap
        nodes={n}
        assets={[{ id: "a1", type: "aed", sweep_id: "s0", floor: 0, x: null, z: null, source: "manual", flags: ["simulated"], label: "lobby" }]}
        index={indexCoverage([])}
        thresholds={null}
        bounds={boundsOf(n)!}
        floor={0}
        type="aed"
        scenario="current"
      />,
    );
    expect(html).toContain(">DEMO AED<");
    expect(html).toContain('data-simulated="true"');
    expect(html).toContain("stroke-dasharray");
    expect(html).toContain("Demo AED (placed by team)");
    expect(html).not.toContain(">AED<");
  });

  it("keeps 'No AED visible in the scan' and lists the demo prop in the flags", () => {
    const asset = {
      id: "a1",
      building_id: "b",
      type: "aed",
      sweep_id: "s0",
      floor: 0,
      x: null,
      y: null,
      z: null,
      source: "manual",
      flags: ["simulated"],
      label: "Demo AED (placed by team)",
      detection_ids: [],
      verified: false,
    } satisfies Asset;
    const html = renderToStaticMarkup(<FlagsList score={null} assets={[asset]} mapped />);
    expect(html).toContain("No AED visible in the scan");
    expect(html).toContain("Demo AED (placed by team)");
    expect(html).toContain(copy.simulatedNotCensus);
  });

  it("adds the demo prop to the legend", () => {
    const html = renderToStaticMarkup(
      <ZoneLegend
        type="aed"
        thresholds={{ status: "unavailable", thresholds: null, error: "offline" }}
        hasAsset
        onlySimulated
        simulatedLabels={["Demo AED (placed by team)"]}
      />,
    );
    expect(html).toContain("Demo AED (placed by team)");
    expect(html).toContain(copy.simulatedNotCensus);
  });
});
