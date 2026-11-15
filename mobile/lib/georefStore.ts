// Georeference storage and the GPS reads that feed it. The math is in lib/georef.ts (pure).
// - Calibrations live on the phone in AsyncStorage, one per building id. A saved one wins over the
//   committed default in lib/georefDefaults.ts.
// - Recorded calibration spots are kept too, so the screen can be reopened and re-solved.
// Nothing here writes to the database.

import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Location from 'expo-location';

import type { Georef, LatLng, StartFix } from './georef';
import { GEOREF_DEFAULTS } from './georefDefaults';
import type { BuildingRow } from './types';

const CALIBRATION_KEY = (buildingId: string) => `within-reach.georef.v1.${buildingId}`;
const SPOTS_KEY = (buildingId: string) => `within-reach.georef-spots.v1.${buildingId}`;

/** How long a calibration spot is recorded for: GPS fixes over this window are averaged. */
export const RECORD_MS = 10_000;

/** GPS start after Accept: how long to wait for a fresh fix before falling back to "tap the map". */
export const START_FIX_TIMEOUT_MS = 4_000;

export type GeorefSource = 'device' | 'default';
export type ActiveGeoref = { georef: Georef; source: GeorefSource; key: string };

function isGeoref(v: unknown): v is Georef {
  if (!v || typeof v !== 'object') return false;
  const g = v as Record<string, unknown>;
  return ['originLat', 'originLng', 'rotationDeg', 'tx', 'tz'].every((k) => typeof g[k] === 'number' && Number.isFinite(g[k] as number));
}

/** The key a committed default would use for this building: its CoStar id when it has one, else its id. */
export function defaultsKey(building: Pick<BuildingRow, 'id' | 'costar_property_id'>): string {
  return building.costar_property_id || building.id;
}

/** The calibration in force for a building: the one saved on this phone, else the committed default, else null. */
export async function loadActiveGeoref(building: Pick<BuildingRow, 'id' | 'costar_property_id'> | null): Promise<ActiveGeoref | null> {
  if (!building) return null;
  try {
    const raw = await AsyncStorage.getItem(CALIBRATION_KEY(building.id));
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    if (isGeoref(parsed)) return { georef: parsed, source: 'device', key: building.id };
  } catch {
    // Unreadable storage: fall through to the committed default.
  }
  const byCostar = building.costar_property_id ? GEOREF_DEFAULTS[building.costar_property_id] : undefined;
  const fallback = byCostar ?? GEOREF_DEFAULTS[building.id];
  if (fallback && isGeoref(fallback)) return { georef: fallback, source: 'default', key: defaultsKey(building) };
  return null;
}

export async function saveDeviceGeoref(buildingId: string, georef: Georef): Promise<void> {
  await AsyncStorage.setItem(CALIBRATION_KEY(buildingId), JSON.stringify(georef));
}

export async function clearDeviceGeoref(buildingId: string): Promise<void> {
  await AsyncStorage.removeItem(CALIBRATION_KEY(buildingId));
}

/** One recorded calibration spot: the mean of the fixes, and what the phone said about them. */
export type SpotRecording = LatLng & {
  /** Mean of the accuracy values the phone reported for these fixes, in meters; null if none reported one. */
  accuracyM: number | null;
  fixes: number;
  recordedAt: string;
};

export async function loadSpotRecordings(buildingId: string): Promise<Record<string, SpotRecording>> {
  try {
    const raw = await AsyncStorage.getItem(SPOTS_KEY(buildingId));
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, SpotRecording>) : {};
  } catch {
    return {};
  }
}

export async function saveSpotRecordings(buildingId: string, spots: Record<string, SpotRecording>): Promise<void> {
  await AsyncStorage.setItem(SPOTS_KEY(buildingId), JSON.stringify(spots));
}

/**
 * Records one calibration spot: watches GPS in the highest accuracy mode for RECORD_MS and averages
 * every fix that arrives (ignoring any fix time-stamped before the recording started, which would be
 * a cached position). Averaging only smooths jitter; it does not remove a steady indoor GPS bias.
 */
export async function recordSpot(onProgress: (fixes: number, msLeft: number) => void): Promise<SpotRecording> {
  const permission = await Location.requestForegroundPermissionsAsync();
  if (!permission.granted) throw new Error('Location permission is not granted.');
  const started = Date.now();
  const fixes: Location.LocationObject[] = [];
  const sub = await Location.watchPositionAsync(
    { accuracy: Location.Accuracy.BestForNavigation, timeInterval: 1000, distanceInterval: 0 },
    (loc) => {
      if (loc.timestamp >= started - 500) {
        fixes.push(loc);
        onProgress(fixes.length, Math.max(0, RECORD_MS - (Date.now() - started)));
      }
    },
  );
  try {
    await new Promise<void>((resolve) => {
      const tick = setInterval(() => {
        const left = RECORD_MS - (Date.now() - started);
        onProgress(fixes.length, Math.max(0, left));
        if (left <= 0) {
          clearInterval(tick);
          resolve();
        }
      }, 250);
    });
  } finally {
    sub.remove();
  }
  if (fixes.length === 0) throw new Error('No GPS fix arrived in 10 seconds. Try again, nearer a window or the entrance.');
  const lat = fixes.reduce((sum, f) => sum + f.coords.latitude, 0) / fixes.length;
  const lng = fixes.reduce((sum, f) => sum + f.coords.longitude, 0) / fixes.length;
  const acc = fixes.map((f) => f.coords.accuracy).filter((a): a is number => typeof a === 'number' && Number.isFinite(a));
  return {
    lat,
    lng,
    accuracyM: acc.length ? acc.reduce((sum, a) => sum + a, 0) / acc.length : null,
    fixes: fixes.length,
    recordedAt: new Date().toISOString(),
  };
}

/**
 * One fresh high-accuracy fix for the GPS start, or null when none arrives within `timeoutMs` or the
 * read fails. Does not ask for permission: callers check the location module's state first.
 */
export async function freshFix(timeoutMs: number = START_FIX_TIMEOUT_MS): Promise<StartFix | null> {
  const read = Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Highest }).then(
    (loc): StartFix => ({ lat: loc.coords.latitude, lng: loc.coords.longitude, accuracyM: loc.coords.accuracy }),
    () => null,
  );
  const timeout = new Promise<null>((resolve) => setTimeout(() => resolve(null), timeoutMs));
  return Promise.race([read, timeout]);
}
