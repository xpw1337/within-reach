import { useEffect, useRef, useState } from 'react';

import { reachableFrom, type AlertPlan, type PlanPoint } from './floorPlan';
import { latLngToPlan, nearestNode, type GeorefTransform } from './georef';
import { freshFix } from './georefStore';

/**
 * How long the "Tap the map where you are" prompt waits before the simulated start is used. A demo
 * choice, not a measured figure.
 */
export const TAP_START_WAIT_MS = 8_000;

export type StartSource = 'gps' | 'tap' | 'default';

/**
 * Where the helper dot starts on the first leg:
 * - `waiting`: the first leg has not started (no Accept yet).
 * - `locating`: reading a fresh GPS fix (a few seconds at most).
 * - `tap`: GPS start not used; the plan asks the helper to tap where they are.
 * - `done`: the start is set. `sweepId` null with source `default` means "use the simulated start".
 */
export type HelperStart =
  | { phase: 'waiting' | 'locating' | 'tap' }
  | { phase: 'done'; source: StartSource; sweepId: string | null; accuracyM: number | null };

type Options = {
  plan: AlertPlan | null;
  /** True while the helper is on their first leg (start -> AED or start -> person). */
  firstLeg: boolean;
  /** Where the first leg goes. */
  target: 'aed' | 'person';
  /** The building's calibration, or null when there is none (GPS start off). */
  georef: GeorefTransform | null;
  /** The calibration lookup has finished (so a missing calibration really is missing). */
  georefReady: boolean;
  /** The location module already has foreground permission (lib/location.ts status 'watching'). */
  locationGranted: boolean;
};

/**
 * Decides the first leg's start once per alert screen: GPS when there is a calibration and a good
 * enough fix, else a tap on the plan, else (after TAP_START_WAIT_MS, or once the helper moves on with
 * a button) the simulated start. Never blocks the buttons.
 */
export function useHelperStart({ plan, firstLeg, target, georef, georefReady, locationGranted }: Options): {
  start: HelperStart;
  onTapPlan: ((p: PlanPoint) => void) | null;
} {
  const [start, setStart] = useState<HelperStart>({ phase: 'waiting' });
  const began = useRef(false);
  const mounted = useRef(true);
  const targetId = plan ? (target === 'aed' ? plan.aedId : plan.personId) : null;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // Begin once, when the first leg starts and the calibration lookup is done. The fix is not
  // cancelled if these inputs change later: it is a one-off decision for this alert.
  useEffect(() => {
    if (began.current || !firstLeg || !plan || !targetId || !georefReady) return;
    began.current = true;
    if (!georef || !locationGranted) {
      setStart({ phase: 'tap' });
      return;
    }
    setStart({ phase: 'locating' });
    const reachable = reachableFrom(plan.graph, targetId);
    void freshFix().then((fix) => {
      if (!mounted.current) return;
      // GPS is taken as accurate (team lead, 2026-11-15): any fix snaps to the nearest scan point that
      // can reach the leg's target, with no accuracy or distance limit. No fix at all: ask for a tap.
      const snap = fix
        ? nearestNode([...plan.graph.nodes.values()].filter((n) => reachable.has(n.id)), latLngToPlan(georef, fix))
        : null;
      setStart((s) => {
        if (s.phase !== 'locating') return s;
        return snap && fix ? { phase: 'done', source: 'gps', sweepId: snap.node.id, accuracyM: fix.accuracyM } : { phase: 'tap' };
      });
    });
  }, [firstLeg, plan, targetId, georef, georefReady, locationGranted]);

  // The tap prompt waits a few seconds, then the simulated start is used.
  useEffect(() => {
    if (start.phase !== 'tap') return;
    const timer = setTimeout(() => {
      setStart((s) => (s.phase === 'tap' ? { phase: 'done', source: 'default', sweepId: null, accuracyM: null } : s));
    }, TAP_START_WAIT_MS);
    return () => clearTimeout(timer);
  }, [start.phase]);

  // The helper moved on with a button before a start was set: settle on the simulated start.
  useEffect(() => {
    if (firstLeg || !began.current) return;
    setStart((s) => (s.phase === 'done' ? s : { phase: 'done', source: 'default', sweepId: null, accuracyM: null }));
  }, [firstLeg]);

  const onTapPlan =
    start.phase === 'tap' && plan && targetId
      ? (p: PlanPoint) => {
          const reachable = reachableFrom(plan.graph, targetId);
          const snap = nearestNode(
            [...plan.graph.nodes.values()].filter((n) => reachable.has(n.id)),
            p,
          );
          setStart((s) =>
            s.phase === 'tap'
              ? snap
                ? { phase: 'done', source: 'tap', sweepId: snap.node.id, accuracyM: null }
                : { phase: 'done', source: 'default', sweepId: null, accuracyM: null }
              : s,
          );
        }
      : null;

  return { start, onTapPlan };
}
