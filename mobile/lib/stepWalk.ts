// Pure logic for moving the helper dot on the indoor plan from the phone's step count. No React and
// no native imports, so it can be checked in plain Node (see README section 5).
//
// One "leg" is one route the helper walks: start -> AED, AED -> person, or start -> person. Every leg
// gets its own pedometer subscription, and the readings that subscription reports are cumulative
// from the moment it started (expo-sensors on both platforms). The leg state turns those readings
// into "steps taken on this leg", then into meters along the leg, clamped to the leg's end.

/**
 * Distance the dot moves per counted step, in meters. This is a commonly cited average adult walking
 * step length (about 0.7 m, roughly 2.3 ft) used as an approximation only. It is NOT measured for
 * this user, varies a lot with height and pace, and the figure itself has not been verified by the
 * team against a primary source.
 */
export const STRIDE_LENGTH_M = 0.7;

/** How long the dot takes to glide to a new step distance, so batched step reports do not jump. */
export const GLIDE_MS = 1000;

/**
 * With step tracking on, how long without any step report before the plan shows a hint to use the
 * buttons. The dot never moves without steps; this only adds a line of text.
 */
export const NO_STEPS_HINT_MS = 10_000;

export type StepLeg = {
  /** The reading that counts as zero steps on this leg. Null until the first reading arrives. */
  baseline: number | null;
  /** The highest reading seen on this leg, or null before any reading. */
  latest: number | null;
};

/**
 * Leg state at the start of a leg.
 * - `baseline: 0` when the subscription's readings already start from zero (iOS: CoreMotion reports
 *   cumulative steps from the subscription's start date).
 * - `baseline: null` when the first reading should become the baseline instead (Android: the step
 *   counter is an on-change sensor, which must report once right after it is turned on, so the first
 *   event is an activation report, not a step).
 */
export function startLeg(baseline: number | null): StepLeg {
  return { baseline, latest: null };
}

/** The baseline rule per platform, as described on `startLeg`. */
export function baselineFor(os: string): number | null {
  return os === 'android' ? null : 0;
}

/**
 * Applies one pedometer reading. Readings that are not finite are ignored. A reading lower than one
 * already seen is ignored too (cumulative counts never go down within one subscription), so the dot
 * never walks backwards.
 */
export function addReading(leg: StepLeg, reading: number): StepLeg {
  if (!Number.isFinite(reading)) return leg;
  if (leg.baseline === null) return { baseline: reading, latest: reading };
  if (leg.latest !== null && reading <= leg.latest) return leg;
  return { baseline: leg.baseline, latest: reading };
}

/** Whole steps taken on this leg so far (never negative). */
export function stepsOnLeg(leg: StepLeg): number {
  if (leg.baseline === null || leg.latest === null) return 0;
  return Math.max(0, Math.floor(leg.latest - leg.baseline));
}

/** Meters along a leg of `legLength` meters after `steps` steps, clamped to [0, legLength]. */
export function distanceForSteps(steps: number, legLength: number, stride: number = STRIDE_LENGTH_M): number {
  if (!(legLength > 0) || !(steps > 0) || !(stride > 0)) return 0;
  return Math.min(legLength, steps * stride);
}

/** The dot's movement toward the latest step distance: from `from` to `to`, starting at `startMs`. */
export type Glide = { from: number; to: number; startMs: number };

export function restingGlide(at: number, nowMs: number): Glide {
  return { from: at, to: at, startMs: nowMs };
}

/** Where the dot is at `nowMs`: a straight-line interpolation over `durationMs`, then it rests at `to`. */
export function glidePosition(g: Glide, nowMs: number, durationMs: number = GLIDE_MS): number {
  if (durationMs <= 0 || nowMs >= g.startMs + durationMs) return g.to;
  if (nowMs <= g.startMs) return g.from;
  const t = (nowMs - g.startMs) / durationMs;
  return g.from + (g.to - g.from) * t;
}

/** Whether the glide has reached its target at `nowMs`. */
export function glideDone(g: Glide, nowMs: number, durationMs: number = GLIDE_MS): boolean {
  return g.from === g.to || nowMs >= g.startMs + durationMs;
}

/**
 * A new glide toward `target`, starting from wherever the dot is at `nowMs` (so a batch that arrives
 * mid-glide continues smoothly instead of restarting from the old point). Never moves backwards.
 */
export function glideTo(g: Glide, target: number, nowMs: number, durationMs: number = GLIDE_MS): Glide {
  const here = glidePosition(g, nowMs, durationMs);
  if (target <= here) return g.to === here && g.from === here ? g : restingGlide(here, nowMs);
  return { from: here, to: target, startMs: nowMs };
}
