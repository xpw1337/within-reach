// The before/after figures on the building page must come straight from the
// fixes row, converted only by lib/thresholds.ts. Synthetic test values.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { FixSummary } from "@/components/building/FixSummary";
import type { Fix } from "@/lib/rows";

const T = { walk_speed_mps: 1.5, aed_roundtrip_target_s: 100, ext_max_travel_m: 20, exit_max_travel_m: 40, yellow_fraction: 0.5 };
const fix: Fix = {
  id: "f1",
  building_id: "b1",
  asset_type: "aed",
  sweep_id: "s9",
  before_worst_s: 70,
  after_worst_s: 30,
  before_red_frac: 0.38,
  after_red_frac: 0.04,
  rationale: "Covers the far end.",
};

describe("FixSummary", () => {
  it("shows AED worst case as round trip from the fixes row", () => {
    const html = renderToStaticMarkup(<FixSummary fix={fix} type="aed" thresholds={T} nodes={[]} />);
    expect(html).toContain("140 s");
    expect(html).toContain("60 s");
    expect(html).toContain("round trip");
    expect(html).toContain("38%");
    expect(html).toContain("4%");
    expect(html).toContain("Covers the far end.");
  });

  it("shows extinguisher worst case as one-way meters", () => {
    const html = renderToStaticMarkup(
      <FixSummary fix={{ ...fix, asset_type: "extinguisher" }} type="extinguisher" thresholds={T} nodes={[]} />,
    );
    expect(html).toContain("105 m");
    expect(html).toContain("45 m");
    expect(html).toContain("one way");
  });

  it("shows -- for missing values, never a guess", () => {
    const html = renderToStaticMarkup(
      <FixSummary fix={{ ...fix, after_worst_s: null, after_red_frac: null }} type="aed" thresholds={T} nodes={[]} />,
    );
    expect(html).toContain("--");
  });
});
