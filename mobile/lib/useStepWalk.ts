import { Pedometer } from 'expo-sensors';
import { useEffect, useRef, useState } from 'react';
import { Platform } from 'react-native';

import { WALK_SPEED_MPS } from './floorPlan';
import {
  addReading,
  baselineFor,
  distanceForSteps,
  glideDone,
  glidePosition,
  glideTo,
  NO_STEPS_HINT_MS,
  restingGlide,
  startLeg,
  stepsOnLeg,
  type Glide,
} from './stepWalk';

/** Timer fallback tick, unchanged from the original simulated walk. */
const TIMER_TICK_MS = 100;
/** Redraw rate while the dot glides to a new step distance. */
const GLIDE_TICK_MS = 50;
/** isAvailableAsync shows no UI, so it should answer quickly; past this the leg uses the timer. */
const AVAILABLE_TIMEOUT_MS = 3000;

/**
 * How the dot moves on this leg, decided once when the leg starts:
 * - `deciding`: checking the pedometer and asking for motion permission; the dot waits at the start.
 * - `steps`: each counted step moves the dot by STRIDE_LENGTH_M; standing still keeps it still.
 * - `timer`: the original simulated walk at WALK_SPEED_MPS (web, no pedometer, or no permission).
 * - `off`: nothing to walk (no route).
 */
export type StepWalkMode = 'deciding' | 'steps' | 'timer' | 'off';

export type StepWalk = {
  mode: StepWalkMode;
  /** Meters along the leg to draw the dot at. */
  walked: number;
  /** Steps mode only: no step report has arrived for a while (the dot stays put). */
  noStepsYet: boolean;
};

function withTimeout<T>(p: Promise<T>, ms: number, fallback: T): Promise<T> {
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(fallback), ms);
    p.then(
      (v) => {
        clearTimeout(timer);
        resolve(v);
      },
      () => {
        clearTimeout(timer);
        resolve(fallback);
      },
    );
  });
}

/** True when this leg can use the pedometer. Asks for motion permission the first time (standard OS prompt). */
async function pedometerUsable(): Promise<boolean> {
  if (Platform.OS === 'web') return false;
  const available = await withTimeout(Pedometer.isAvailableAsync(), AVAILABLE_TIMEOUT_MS, false);
  if (!available) return false;
  try {
    const permission = await Pedometer.requestPermissionsAsync();
    return permission.granted;
  } catch {
    return false;
  }
}

/**
 * Moves the helper dot along one leg of `length` meters. Mount it once per leg (the floor plan gets
 * a new `key` per leg): the mode is decided on mount and never changes during the leg, and the
 * pedometer subscription and timers are removed on unmount.
 */
export function useStepWalk(length: number): StepWalk {
  const hasLeg = length > 0;
  const [mode, setMode] = useState<StepWalkMode>(() => (!hasLeg ? 'off' : Platform.OS === 'web' ? 'timer' : 'deciding'));
  const [timerStart, setTimerStart] = useState(() => Date.now());
  const [now, setNow] = useState(() => Date.now());
  const [glide, setGlide] = useState<Glide>(() => restingGlide(0, Date.now()));
  const [noStepsYet, setNoStepsYet] = useState(false);
  const glideRef = useRef(glide);

  // Decide once for this leg.
  useEffect(() => {
    if (mode !== 'deciding') return;
    let cancelled = false;
    void pedometerUsable().then((usable) => {
      if (cancelled) return;
      if (!usable) {
        // Start the timed walk now, so the dot does not jump ahead by the time the prompt was open.
        const t = Date.now();
        setTimerStart(t);
        setNow(t);
      }
      setMode(usable ? 'steps' : 'timer');
    });
    return () => {
      cancelled = true;
    };
  }, [mode]);

  // Timer fallback: exactly the original simulated walk.
  useEffect(() => {
    if (mode !== 'timer' || length <= 0) return;
    const timer = setInterval(() => {
      const t = Date.now();
      setNow(t);
      if (((t - timerStart) / 1000) * WALK_SPEED_MPS >= length) clearInterval(timer);
    }, TIMER_TICK_MS);
    return () => clearInterval(timer);
  }, [mode, length, timerStart]);

  // Step tracking: one subscription for this leg, removed on unmount.
  useEffect(() => {
    if (mode !== 'steps') return;
    let leg = startLeg(baselineFor(Platform.OS));
    let sawReading = false;
    const hint = setTimeout(() => {
      if (!sawReading) setNoStepsYet(true);
    }, NO_STEPS_HINT_MS);
    let subscription: { remove: () => void } | null = null;
    try {
      subscription = Pedometer.watchStepCount((result) => {
        sawReading = true;
        setNoStepsYet(false);
        leg = addReading(leg, result.steps);
        const target = distanceForSteps(stepsOnLeg(leg), length);
        const t = Date.now();
        const next = glideTo(glideRef.current, target, t);
        if (next !== glideRef.current) {
          glideRef.current = next;
          setGlide(next);
          setNow(t);
        }
      });
    } catch {
      // Subscribing failed after permission was granted: the dot stays put and the buttons still work.
      subscription = null;
    }
    return () => {
      clearTimeout(hint);
      subscription?.remove();
    };
  }, [mode, length]);

  // Redraw while the dot glides to the latest step distance.
  useEffect(() => {
    if (mode !== 'steps' || glideDone(glide, Date.now())) return;
    const timer = setInterval(() => {
      const t = Date.now();
      setNow(t);
      if (glideDone(glide, t)) clearInterval(timer);
    }, GLIDE_TICK_MS);
    return () => clearInterval(timer);
  }, [mode, glide]);

  let walked = 0;
  if (mode === 'timer') walked = Math.min(length, ((now - timerStart) / 1000) * WALK_SPEED_MPS);
  else if (mode === 'steps') walked = Math.min(length, glidePosition(glide, now));
  return { mode, walked: Math.max(0, walked), noStepsYet: mode === 'steps' && noStepsYet };
}
