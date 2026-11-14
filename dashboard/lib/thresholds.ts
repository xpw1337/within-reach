// Red-zone rules and unit conversions for display (decisions D3 and D4).
//
// The limits come from GET /config/thresholds (shared/thresholds.py); nothing
// here hardcodes a limit. Every *_s value in the database is one-way walking
// seconds (docs/CONTRACTS.md section 1). This file is the only place in the
// dashboard that converts them:
//   AED            -> round trip seconds (2 x one-way)
//   extinguisher   -> one-way meters (seconds x walk_speed_mps)
//   exit           -> one-way meters (seconds x walk_speed_mps)
import { api, type Thresholds } from "./api";
import type { GapType } from "./rows";

export type { Thresholds };
export type Zone = "green" | "yellow" | "red" | "unknown";

export function isGapType(t: string | null | undefined): t is GapType {
  return t === "aed" || t === "extinguisher" || t === "exit";
}

export function validThresholds(x: unknown): x is Thresholds {
  if (!x || typeof x !== "object") return false;
  const o = x as Record<string, unknown>;
  const pos = (k: string) => typeof o[k] === "number" && Number.isFinite(o[k]) && (o[k] as number) > 0;
  return (
    pos("walk_speed_mps") &&
    pos("aed_roundtrip_target_s") &&
    pos("ext_max_travel_m") &&
    pos("exit_max_travel_m") &&
    pos("yellow_fraction") &&
    (o.yellow_fraction as number) < 1
  );
}

/** The red limit as one-way seconds, the unit of coverage.time_s. Mirrors shared/thresholds.limit_seconds. */
export function limitSeconds(t: Thresholds, type: GapType): number {
  switch (type) {
    case "aed":
      return t.aed_roundtrip_target_s / 2;
    case "extinguisher":
      return t.ext_max_travel_m / t.walk_speed_mps;
    case "exit":
      return t.exit_max_travel_m / t.walk_speed_mps;
  }
}

/**
 * Mirrors shared/thresholds.zone: NULL time -> unknown (no asset of that type
 * visible in the scan, or unreachable); > limit -> red; > yellow_fraction x
 * limit -> yellow; else green. Without thresholds every zone is unknown.
 */
export function zone(t: Thresholds | null, type: string, timeS: number | null | undefined): Zone {
  if (!t || !isGapType(type) || timeS === null || timeS === undefined || !Number.isFinite(timeS)) {
    return "unknown";
  }
  const limit = limitSeconds(t, type);
  if (timeS > limit) return "red";
  if (timeS > t.yellow_fraction * limit) return "yellow";
  return "green";
}

// ---------- display conversions ----------

export function aedRoundTripSeconds(oneWayS: number): number {
  return 2 * oneWayS;
}

export function oneWayMeters(oneWayS: number, t: Thresholds): number {
  return oneWayS * t.walk_speed_mps;
}

function trimNumber(n: number, digits: number): string {
  return Number(n.toFixed(digits)).toString();
}

/** What the value means for each type, for labels next to a number. */
export function measureName(type: GapType): string {
  return type === "aed" ? "round trip" : "one-way distance";
}

export type Measure = { value: string; unit: string; note: string };

/**
 * A stored one-way time as a person should read it. Returns null when the
 * value is missing or, for distances, when the walk speed is unknown.
 */
export function measure(type: GapType, oneWayS: number | null | undefined, t: Thresholds | null): Measure | null {
  if (oneWayS === null || oneWayS === undefined || !Number.isFinite(oneWayS)) return null;
  if (type === "aed") {
    return { value: Math.round(aedRoundTripSeconds(oneWayS)).toString(), unit: "s", note: "round trip" };
  }
  if (!t) return null;
  const m = oneWayMeters(oneWayS, t);
  return { value: m < 10 ? trimNumber(m, 1) : Math.round(m).toString(), unit: "m", note: "one way" };
}

/** "142 s round trip", "31 m one way", or "--". */
export function formatMeasure(type: GapType, oneWayS: number | null | undefined, t: Thresholds | null): string {
  const m = measure(type, oneWayS, t);
  return m ? `${m.value} ${m.unit} ${m.note}` : "--";
}

/** The red limit as configured, in the unit people read: "180 s round trip", "22.9 m one way". */
export function formatLimit(type: GapType, t: Thresholds | null): string {
  if (!t) return "--";
  if (type === "aed") return `${trimNumber(t.aed_roundtrip_target_s, 1)} s round trip`;
  const m = type === "extinguisher" ? t.ext_max_travel_m : t.exit_max_travel_m;
  return `${trimNumber(m, 1)} m one way`;
}

/** The yellow band start in the same unit as formatLimit. */
export function formatYellowStart(type: GapType, t: Thresholds | null): string {
  if (!t) return "--";
  return formatMeasure(type, t.yellow_fraction * limitSeconds(t, type), t);
}

// ---------- fetch + cache ----------

export type ThresholdState =
  | { status: "loading"; thresholds: null; error: null }
  | { status: "ok"; thresholds: Thresholds; error: null }
  | { status: "unavailable"; thresholds: null; error: string };

let state: ThresholdState = { status: "loading", thresholds: null, error: null };
let inflight: Promise<void> | null = null;
const listeners = new Set<() => void>();

function setState(next: ThresholdState) {
  state = next;
  listeners.forEach((l) => l());
}

export function getThresholdState(): ThresholdState {
  return state;
}

export function subscribeThresholds(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Fetch once and share; call again to retry after a failure. */
export function loadThresholds(force = false): Promise<void> {
  if (state.status === "ok" && !force) return Promise.resolve();
  if (inflight) return inflight;
  inflight = api
    .getThresholds()
    .then((res) => {
      if (res.ok && validThresholds(res.data)) {
        setState({ status: "ok", thresholds: res.data, error: null });
      } else if (res.ok) {
        setState({ status: "unavailable", thresholds: null, error: "Thresholds response had an unexpected shape" });
      } else {
        // Keep values we already have if a refresh fails.
        if (state.status !== "ok") setState({ status: "unavailable", thresholds: null, error: res.error });
      }
    })
    .finally(() => {
      inflight = null;
    });
  return inflight;
}
