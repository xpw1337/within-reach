// Committed georeference calibrations, keyed by the building's `costar_property_id` (for example
// 'DEMO-RABINOWITZ') or, if it has none, its `buildings.id`.
//
// Empty on purpose: every entry must come from a real calibration on site (the hidden calibration
// screen, README "Georeference calibration on site"). Never type in a rotation guessed from the
// building's shape or a map. A calibration saved on the phone wins over an entry here; with neither,
// the GPS start is off and the helper dot starts from a tap or the simulated start.
//
// To add one, paste the block the calibration screen shows between the braces below.

import type { Georef } from './georef';

export const GEOREF_DEFAULTS: Record<string, Georef> = {
  // Recorded on site by the team on 2026-11-14 from 4 spots (patient spot, AED spot, corridor
  // wing, atrium edge). Residual 3.64 m RMS: good enough to start the dot in the right area,
  // not to place it on an exact spot.
  'DEMO-RABINOWITZ': {
    originLat: 40.34909293,
    originLng: -74.65548296,
    rotationDeg: -29.67,
    tx: -4.35,
    tz: 3.989,
    calibratedAt: '2026-11-14',
    spots: 4,
    rmsM: 3.64,
  },
};
