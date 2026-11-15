import { describe, expect, it } from "vitest";
import { distanceToPathPoint, latLngToPlan, nearestPathIndex, parseGeoParam } from "@/lib/georef";

const M_PER_DEG_LAT = (6_371_008.8 * Math.PI) / 180;

describe("latLngToPlan", () => {
  it("puts the origin at (tx, tz)", () => {
    const t = { originLat: 40.349, originLng: -74.655, rotationDeg: -29.67, tx: -4.35, tz: 3.989 };
    const p = latLngToPlan(t, { lat: t.originLat, lng: t.originLng });
    expect(p.x).toBeCloseTo(-4.35, 9);
    expect(p.z).toBeCloseTo(3.989, 9);
  });

  it("with no rotation, north is -z and east is +x", () => {
    const t = { originLat: 0, originLng: 0, rotationDeg: 0, tx: 0, tz: 0 };
    const north = latLngToPlan(t, { lat: 10 / M_PER_DEG_LAT, lng: 0 });
    expect(north.x).toBeCloseTo(0, 6);
    expect(north.z).toBeCloseTo(-10, 6);
    const east = latLngToPlan(t, { lat: 0, lng: 10 / M_PER_DEG_LAT });
    expect(east.x).toBeCloseTo(10, 6);
    expect(east.z).toBeCloseTo(0, 6);
  });
});

describe("parseGeoParam", () => {
  it("reads five numbers", () => {
    expect(parseGeoParam("40.349,-74.655,-29.67,-4.35,3.989")).toEqual({
      originLat: 40.349,
      originLng: -74.655,
      rotationDeg: -29.67,
      tx: -4.35,
      tz: 3.989,
    });
  });

  it("refuses anything else", () => {
    expect(parseGeoParam(undefined)).toBeNull();
    expect(parseGeoParam("1,2,3,4")).toBeNull();
    expect(parseGeoParam("1,2,3,4,x")).toBeNull();
    expect(parseGeoParam("95,0,0,0,0")).toBeNull();
    expect(parseGeoParam("0,0,0,0,1e9")).toBeNull();
  });
});

describe("nearestPathIndex", () => {
  const nodes = new Map([
    ["a", { x: 0, z: 0 }],
    ["b", { x: 3, z: 0 }],
    ["c", { x: 6, z: 0 }],
    ["n", { x: null, z: null }],
  ]);

  it("finds the path point nearest to the phone", () => {
    expect(nearestPathIndex(["a", "b", "c"], nodes, { x: 5, z: 1 })).toBe(2);
    expect(nearestPathIndex(["a", "b", "c"], nodes, { x: 1.4, z: 0 })).toBe(0);
    expect(distanceToPathPoint(["a", "b", "c"], nodes, 1, { x: 3, z: 4 })).toBeCloseTo(4, 9);
  });

  it("skips points without a position", () => {
    expect(nearestPathIndex(["n", "b"], nodes, { x: 0, z: 0 })).toBe(1);
    expect(nearestPathIndex(["n"], nodes, { x: 0, z: 0 })).toBe(-1);
  });
});
