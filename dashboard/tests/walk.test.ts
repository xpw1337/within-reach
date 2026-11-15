import { describe, expect, it } from "vitest";
import { segmentMs, yawToward } from "@/components/building/MatterportTwin";

describe("yawToward", () => {
  // Measured on the demo model: rotation.y = 0 faces -z, 90 faces -x.
  it("matches the measured Matterport convention", () => {
    expect(yawToward({ x: 0, z: 0 }, { x: 0, z: -5 })).toBeCloseTo(0, 9);
    expect(yawToward({ x: 0, z: 0 }, { x: -5, z: 0 })).toBeCloseTo(90, 9);
    expect(yawToward({ x: 0, z: 0 }, { x: 5, z: 0 })).toBeCloseTo(-90, 9);
    expect(Math.abs(yawToward({ x: 0, z: 0 }, { x: 0, z: 5 }))).toBeCloseTo(180, 9);
  });
});

describe("segmentMs", () => {
  it("takes as long as walking the segment, within 1.2 s and 10 s", () => {
    expect(segmentMs(4.2, 1.4)).toBeCloseTo(3000, 6);
    expect(segmentMs(0.5, 1.4)).toBe(1200);
    expect(segmentMs(40, 1.4)).toBe(10000);
    expect(segmentMs(4, 0.8)).toBeCloseTo(5000, 6);
  });
});
