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

export const GEOREF_DEFAULTS: Record<string, Georef> = {};
