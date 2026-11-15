// Live GPS for the calibration screen (app/calibrate.tsx): a foreground watch in the same
// high-accuracy mode the spot recording uses, so the screen can show the accuracy the phone reports
// right now and, with a calibration in use, where GPS puts you on the plan. Read only: nothing is
// stored or sent anywhere.

import * as Location from 'expo-location';
import { useEffect, useState } from 'react';

import { errorMessage } from './supabase';

export type LiveFix = { lat: number; lng: number; accuracyM: number | null };

export type LiveGps = {
  status: 'off' | 'starting' | 'denied' | 'watching' | 'error';
  /**
   * False when the phone allows only approximate location (iOS Precise Location off, Android
   * "approximate"), which makes calibration useless. Null when the platform does not say (web).
   */
  precise: boolean | null;
  /** The latest fix, or null until the first one arrives. */
  fix: LiveFix | null;
  error: string | null;
};

const OFF: LiveGps = { status: 'off', precise: null, fix: null, error: null };
const STARTING: LiveGps = { ...OFF, status: 'starting' };

/** Only a clear "approximate" answer counts as not precise; anything unexpected is unknown (null). */
function preciseOf(p: Location.LocationPermissionResponse): boolean | null {
  const a = p.ios?.accuracy ?? p.android?.accuracy;
  if (a === 'full' || a === 'fine') return true;
  if (a === 'reduced' || a === 'coarse') return false;
  return null;
}

/**
 * Watches GPS while `enabled` (asking for permission the first time). Change `attempt` to ask again,
 * for example after the person changed a setting.
 */
export function useLiveFix(enabled: boolean, attempt: number): LiveGps {
  const [state, setState] = useState<LiveGps>(STARTING);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let sub: Location.LocationSubscription | null = null;
    (async () => {
      try {
        const permission = await Location.requestForegroundPermissionsAsync();
        if (cancelled) return;
        const precise = preciseOf(permission);
        if (!permission.granted) {
          setState({ ...OFF, status: 'denied', precise });
          return;
        }
        setState({ ...OFF, status: 'watching', precise });
        const s = await Location.watchPositionAsync(
          { accuracy: Location.Accuracy.BestForNavigation, timeInterval: 1000, distanceInterval: 0 },
          (loc) => {
            if (cancelled) return;
            const acc = loc.coords.accuracy;
            setState((prev) => ({
              ...prev,
              fix: {
                lat: loc.coords.latitude,
                lng: loc.coords.longitude,
                accuracyM: typeof acc === 'number' && Number.isFinite(acc) && acc > 0 ? acc : null,
              },
              error: null,
            }));
          },
          (reason) => {
            if (!cancelled) setState((prev) => ({ ...prev, error: reason }));
          },
        );
        if (cancelled) s.remove();
        else sub = s;
      } catch (error) {
        if (!cancelled) setState({ ...OFF, status: 'error', error: errorMessage(error) });
      }
    })();
    return () => {
      cancelled = true;
      sub?.remove();
      // The next start shows "starting" again rather than an old fix.
      setState(STARTING);
    };
  }, [enabled, attempt]);

  return enabled ? state : OFF;
}
