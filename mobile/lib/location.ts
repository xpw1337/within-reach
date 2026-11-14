import * as Location from 'expo-location';
import { useEffect } from 'react';
import { AppState } from 'react-native';

import { createStore, useStore } from './store';
import { errorMessage, requireSupabase } from './supabase';

/** Minimum gap between writes to responders.last_lat/last_lng/last_seen_at. */
export const LOCATION_WRITE_INTERVAL_MS = 15_000;
/** How often the heartbeat checks whether a write is due. Writes still respect the 15 s minimum. */
const HEARTBEAT_MS = 5_000;

export type Coords = { lat: number; lng: number };

export type LocationState = {
  status: 'off' | 'requesting' | 'denied' | 'watching' | 'error';
  coords: Coords | null;
  /** ISO time of the last successful write to the database. */
  lastWriteAt: string | null;
  error: string | null;
};

export const locationStore = createStore<LocationState>({
  status: 'off',
  coords: null,
  lastWriteAt: null,
  error: null,
});

export function useLocationState(): LocationState {
  return useStore(locationStore);
}

/**
 * Foreground location watch for this responder. While `enabled` and the app is active, writes the
 * latest position and a fresh last_seen_at at most every 15 s. The live agent only considers
 * responders seen in the last 10 minutes (spec 9.10), so the heartbeat keeps writing even when
 * the phone is not moving and the OS sends no new fix.
 */
export function useLocationReporter(responderId: string | null, enabled: boolean): void {
  useEffect(() => {
    if (!responderId || !enabled) {
      locationStore.set((s) => ({ ...s, status: 'off', error: null }));
      return;
    }

    let cancelled = false;
    let subscription: Location.LocationSubscription | null = null;
    let latest: Coords | null = null;
    let lastWriteMs = 0;
    let writing = false;

    const writeIfDue = async () => {
      if (cancelled || writing || !latest) return;
      if (AppState.currentState !== 'active') return;
      const now = Date.now();
      if (now - lastWriteMs < LOCATION_WRITE_INTERVAL_MS) return;
      writing = true;
      lastWriteMs = now;
      const seenAt = new Date(now).toISOString();
      try {
        const { error } = await requireSupabase()
          .from('responders')
          .update({ last_lat: latest.lat, last_lng: latest.lng, last_seen_at: seenAt })
          .eq('id', responderId);
        if (error) throw error;
        if (!cancelled) locationStore.set((s) => ({ ...s, lastWriteAt: seenAt, error: null }));
      } catch (error) {
        if (!cancelled) locationStore.set((s) => ({ ...s, error: `Could not update location: ${errorMessage(error)}` }));
      } finally {
        writing = false;
      }
    };

    const onFix = (location: Location.LocationObject) => {
      latest = { lat: location.coords.latitude, lng: location.coords.longitude };
      locationStore.set((s) => ({ ...s, coords: latest }));
      void writeIfDue();
    };

    (async () => {
      locationStore.set((s) => ({ ...s, status: 'requesting', error: null }));
      try {
        const permission = await Location.requestForegroundPermissionsAsync();
        if (cancelled) return;
        if (!permission.granted) {
          locationStore.set((s) => ({ ...s, status: 'denied' }));
          return;
        }
        const sub = await Location.watchPositionAsync(
          // timeInterval is honored on Android only; the 15 s write limit above applies everywhere.
          { accuracy: Location.Accuracy.Balanced, timeInterval: LOCATION_WRITE_INTERVAL_MS, distanceInterval: 10 },
          onFix,
          (reason) => {
            if (!cancelled) locationStore.set((s) => ({ ...s, error: `Location error: ${reason}` }));
          },
        );
        if (cancelled) {
          sub.remove();
          return;
        }
        subscription = sub;
        locationStore.set((s) => ({ ...s, status: 'watching' }));
      } catch (error) {
        if (!cancelled) locationStore.set((s) => ({ ...s, status: 'error', error: errorMessage(error) }));
      }
    })();

    const heartbeat = setInterval(() => void writeIfDue(), HEARTBEAT_MS);
    const appStateSub = AppState.addEventListener('change', (state) => {
      if (state === 'active') void writeIfDue();
    });

    return () => {
      cancelled = true;
      clearInterval(heartbeat);
      appStateSub.remove();
      subscription?.remove();
    };
  }, [responderId, enabled]);
}

/** Great-circle distance in meters. */
export function distanceMeters(a: Coords, b: Coords): number {
  const R = 6_371_000;
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
