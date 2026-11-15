// User-facing wording. Lines marked VERBATIM are copied from the build spec (CLAUDE.md)
// and must not be reworded. Repo rule: no em-dash characters anywhere.

import type { DispatchRole, IncidentType, ResponderRole } from './types';

// Spec section 16: say "person down" / "possible cardiac arrest"; never diagnose.
export const INCIDENT_TITLE = 'Person down';
export const INCIDENT_TYPE_LABELS: Record<IncidentType, string> = {
  cardiac: 'Possible cardiac arrest',
  fall: 'Fall, the person responded to the voice check',
  fire: 'Fire',
  unknown: 'Person down',
};

export const DISPATCH_ROLE_TITLES: Record<DispatchRole, string> = {
  patient: 'Go to the person',
  aed_runner: "You're the AED runner",
  staff: 'Staff response',
  broadcast: 'Help nearby',
};

export const DISPATCH_ROLE_HELP: Record<DispatchRole, string> = {
  patient: 'Go straight to the person. Tap "I\'m here" when you reach them.',
  aed_runner: 'Get the AED first. Tap "I have the AED" when you pick it up, then bring it to the person and tap "I\'m with the person".',
  staff: 'Go to the person. Tap "I\'m here" when you reach them.',
  broadcast: 'Go to the person. Tap "I\'m here" when you reach them.',
};

// CPR guide. VERBATIM from the spec section 3 CARDIAC playbook and modifiers.
export const CPR_CHECK =
  "Go to them, tap their shoulder and shout. If they don't respond and aren't breathing normally, call 911 on speaker and start CPR: push hard and fast in the center of the chest.";
export const CPR_DEPTH_RATE = 'Push at least 2 inches deep, 100 to 120 times a minute, let the chest come back up.';
export const AED_STEP = 'When the AED arrives, turn it on and follow its voice.';
export const MOD_BREATHING = 'If they are breathing, roll them onto their side and stay with them.';
// The spec sentence has an em-dash after "check breathing"; replaced with a comma (repo rule).
export const MOD_SEIZURE =
  "If they're shaking, don't hold them down or put anything in their mouth. Move hard objects away. When it stops, check breathing, if they're not breathing normally, start CPR.";

// AED help screen script. General public AED guidance, NOT medically reviewed by the team (unlike
// the spec section 3 wording above). The AED's own voice prompts always take priority over these
// lines, which is what step 1 tells the helper. Wording approved by the team lead; keep it exact.
export const AED_HELP_STEPS: readonly string[] = [
  'Turn on the AED. It will talk to you. Do what it says, even if it differs from me.',
  'Remove clothing from the chest. If the chest is wet, wipe it dry.',
  'Peel the pads and stick them on bare skin as the pictures on the pads show: one on the upper right chest, below the collarbone. The other on the lower left side, below the armpit.',
  'If the pads are not already plugged in, plug the connector into the AED.',
  'Stop CPR and make sure nobody is touching the person while the AED analyzes.',
  'If it tells you to shock, say stand clear loudly, check nobody is touching the person, then press the shock button.',
  'Start CPR again right away: push hard and fast in the center of the chest. Keep following the AED until help takes over.',
];
export const AED_HELP_TITLE = 'AED help';
export const AED_HELP_BUTTON = 'GIVE ME HELP WITH AED';
export const AED_HELP_NOTE = "Follow the AED's own voice first. These steps are spoken by this phone.";
export const AED_HELP_REPEAT = 'Repeat';
export const AED_HELP_NEXT = 'Next';
export const AED_HELP_BACK = 'Back';
export const AED_HELP_STEP_OF = (n: number, total: number) => `Step ${n} of ${total}`;

// Indoor floor plan on the Alert screen.
export const PLAN_PERSON = 'Person';
export const PLAN_AED = 'AED';
/** Shown instead of "AED" when the AED row has the `simulated` flag. Never call a planted AED detected. */
export const PLAN_AED_SIMULATED = 'Demo AED (placed by team)';
export const PLAN_YOU = 'You';
/** Under the plan when the dot follows the timed walk (web, no pedometer, or no motion permission). */
export const PLAN_SIMULATED_POSITION = 'Position simulated for the demo';
/** Under the plan when the dot follows the phone's step count. Never imply GPS or an exact position. */
export const PLAN_STEPS_POSITION = 'Position estimated from your steps';
/**
 * Start of the first leg from a GPS fix. `n` is the accuracy the phone itself reported, rounded to a
 * whole meter; never a figure of ours.
 */
export const PLAN_START_GPS = (n: number) => `Start position from GPS (accurate to about ${n} m)`;
/** Start of the first leg from the helper's tap on the plan. */
export const PLAN_START_TAPPED = 'Start position set by you';
/**
 * Second line under a GPS or tapped start: how the dot moves from there. Worded as movement so it
 * does not read as if the start itself were estimated or simulated.
 */
export const PLAN_MOVE_STEPS = 'Movement estimated from your steps';
export const PLAN_MOVE_SIMULATED = 'Movement simulated for the demo';
/** While the GPS fix for the start is read (a few seconds at most). */
export const PLAN_LOCATING = 'Checking GPS for your start position...';
/** GPS start not used: the helper can tap the plan; the buttons still work. */
export const PLAN_TAP_PROMPT = 'Tap the map where you are';
/** Step tracking is on but no step has been reported yet; the dot stays put until one is. */
export const PLAN_NO_STEPS_YET = 'No steps counted yet. Use the button below when you get there.';
export const PLAN_NO_AED_ROUTE = 'No AED route is mapped for this spot';
export const PLAN_AED_OTHER_FLOOR = 'The AED is not on this floor. Follow the directions below.';
export const PLAN_FLOOR = 'Floor';

export const STEP_GET_AED = 'Go to the AED';
export const STEP_BRING_AED = 'Bring the AED to the person';
export const STEP_GO_TO_PERSON = 'Go to the person';
export const STEP_WITH_PERSON = 'You are with the person';
export const BUTTON_HAVE_AED = 'I have the AED';
export const BUTTON_WITH_PERSON = "I'm with the person";
export const BUTTON_IM_HERE = "I'm here";

// Alert screen labels and buttons.
export const ALERT_LOADING = 'Loading alert...';
export const ALERT_GONE = 'This alert is no longer active.';
export const ALERT_BACK_HOME = 'Back to home';
export const ALERT_LOAD_ERROR = 'Could not load the incident details:';
export const ALERT_YOUR_ROLE = 'Your role';
export const ALERT_ACCEPTED = 'Accepted';
export const ALERT_WAITING_ROLE = 'Waiting for your role.';
export const ALERT_WHERE = 'Where';
export const ALERT_DISTANCE_FROM_YOU = 'Distance from you:';
export const ALERT_FROM_PERSON = 'From the person:';
export const ALERT_ARRIVED = 'You are marked as arrived.';
export const ALERT_VIEW_3D = 'View route in 3D';
export const ALERT_ACCEPT = 'Accept';
export const ALERT_DECLINE = "Can't help";
export const ALERT_DONE = 'Done';
export const CPR_GUIDE = 'CPR guide';

export const RELEASED_TITLE = "You're released";
export const RELEASED_BODY = 'No further action is needed from you for this alert. Thank you for answering.';

// VERBATIM, spec section 9.11
export const PRIVACY_LINE =
  'We only use your location to alert you to emergencies nearby; we never identify people on camera.';

// VERBATIM, spec section 9.11
export const GOOD_SAMARITAN_LINE =
  'Every US state has a Good Samaritan law protecting people who help in good faith; details vary by state.';

export const CONSENT_LOCATION_LABEL = 'Share my location while the app is open';
export const CONSENT_LOCATION_HELP =
  'Responders are matched to emergencies by location, so without this you will not be alerted.';
export const CONSENT_CALLS_LABEL = 'I agree to receive phone calls about emergencies nearby';

export const RESPONDER_ROLE_LABELS: Record<ResponderRole, string> = {
  public: 'Public',
  staff: 'Staff',
  security: 'Security',
  tenant: 'Tenant',
};

// Calibration screen (app/calibrate.tsx): a team setup screen, opened by a long press on the Home
// title. Every number in these lines comes from the app's constants, the data or the phone itself;
// never type one in.
const whole = (m: number) => String(Math.round(m));
const tenth = (m: number) => m.toFixed(1);
const spotsWord = (n: number) => (n === 1 ? '1 spot' : `${n} spots`);
const readingsWord = (n: number) => (n === 1 ? '1 GPS reading' : `${n} GPS readings`);
type CalSpotKind = 'patient' | 'aed' | 'label';

export const CAL_TITLE = 'GPS calibration';
export const CAL_TEAM_NOTE =
  'Setup screen for the team, not part of an alert. Nothing here is sent anywhere: a calibration is saved on this phone only.';

export const CAL_BUILDING = 'Building';
export const CAL_BUILDING_NONE = 'No building chosen yet. Search for the one you are in.';
export const CAL_BUILDING_LOADING = 'Loading...';
export const CAL_BUILDING_CHANGE = 'Change building';
export const CAL_BUILDING_SEARCH = 'Search buildings';
export const CAL_BUILDING_PLACEHOLDER = 'Name or address';
export const CAL_BUILDING_SEARCH_ERROR = (e: string) => `Could not load buildings: ${e}`;
export const CAL_BUILDING_LOAD_ERROR = (e: string) => `Could not load the building: ${e}`;
export const CAL_NO_SPOTS =
  'This building has no camera, AED or named scan spot to stand on, so it cannot be calibrated here.';

// Is there a calibration already? Shown first, so nobody calibrates when they do not need to.
export const CAL_STATUS_DONE = 'Already calibrated';
export const CAL_STATUS_NONE = 'Not calibrated yet';
export const CAL_STATUS_DEFAULT = (date: string, spots: number, rmsM: number) =>
  `The team calibrated this building on ${date} from ${spotsWord(spots)} (typical error about ${tenth(rmsM)} m). Alerts already use it, so there is nothing you need to do here.`;
export const CAL_STATUS_DEFAULT_AGAIN =
  'Calibrating again is optional: do it only if the blue dot in an alert starts in the wrong part of the building.';
export const CAL_STATUS_DEVICE = (date: string, spots: number, rmsM: number) =>
  `This phone has its own calibration from ${date} (${spotsWord(spots)}, typical error about ${tenth(rmsM)} m). Alerts on this phone use it.`;
export const CAL_STATUS_DEVICE_OVER_DEFAULT = "On this phone it replaces the team's calibration.";
export const CAL_STATUS_NO_CAL =
  'There is no calibration for this building yet, so alerts here ask the helper to tap the map where they are. Calibrating is optional: it lets alerts start the blue dot from GPS instead.';
export const CAL_REMOVE_DEVICE = "Remove this phone's calibration";
export const CAL_REMOVED_TO_DEFAULT = "This phone's calibration was removed. Alerts use the team's calibration again.";
export const CAL_REMOVED_TO_NONE = "This phone's calibration was removed. Alerts ask the helper to tap the map again.";

export const CAL_WHY_TITLE = 'What calibration does';
export const CAL_WHY =
  "It lines up GPS with this building's floor plan. Then, when a helper accepts an alert here, the app can start their blue dot where they really are instead of asking them to tap the map.";
export const CAL_HOW = (spots: number, seconds: number) =>
  `You walk to ${spotsWord(spots)} marked on the plan. At each one you stand still, press one button and wait ${seconds} seconds while the phone listens to GPS.`;
export const CAL_SPOTS_TITLE = 'The spots';
export const CAL_SPOT_RECORDED = 'Recorded';
export const CAL_SPOT_NOT_RECORDED = 'Not recorded yet';
export const CAL_BEFORE_TITLE = 'Before you start';
export const CAL_BEFORE_LINES: readonly string[] = [
  'Turn on Precise Location for Expo Go. iPhone: Settings, Expo Go, Location, Precise Location. Android: allow precise location.',
  'At each spot, hold the phone flat at chest height, screen up, and stand still while it records.',
];

export const CAL_START = 'Start calibration';
export const CAL_START_AGAIN = 'Calibrate again';
export const CAL_CONTINUE = (n: number, total: number) => `Continue at spot ${n} of ${total}`;
export const CAL_SEE_RESULT = 'See the result';
export const CAL_START_OVER = 'Start over';
export const CAL_START_OVER_CONFIRM = (n: number) =>
  n === 1 ? 'Tap again to forget the recorded spot' : `Tap again to forget all ${n} recorded spots`;
export const CAL_CHECK = 'Check where GPS puts me';
export const CAL_CHECK_NEEDS = 'Checking needs a calibration first.';
export const CAL_BACK = 'Back';
export const CAL_OVERVIEW = 'Back to the overview';
/** The same, short enough for a half-width button next to "Skip this spot". */
export const CAL_ALL_SPOTS = 'All spots';

/** A spot's name in plain words: the place from the data, else what kind of spot it is. */
export const CAL_SPOT_NAME = (kind: CalSpotKind, place: string | null) => {
  if (place) return place.charAt(0).toUpperCase() + place.slice(1);
  return kind === 'patient' ? 'Patient spot' : kind === 'aed' ? 'AED spot' : 'Scan spot';
};
/** Why this spot is on the list, from the data. `note` is the camera's name or the AED's label. */
export const CAL_SPOT_ROLE = (kind: CalSpotKind, note: string | null) => {
  if (kind === 'patient') {
    return note ? `The patient spot: where the person lies in the demo (${note}).` : 'The patient spot: where the person lies in the demo.';
  }
  if (kind === 'aed') return note ? `Where the app shows the AED: ${note}.` : 'Where the app shows the AED.';
  return 'A named spot from the 3D scan.';
};

// One spot at a time.
export const CAL_SPOT_OF = (n: number, total: number) => `Spot ${n} of ${total}`;
export const CAL_SCAN_FLOOR = (floor: number) => `Scan floor ${floor}`;
export const CAL_STAND_HOW =
  'Stand on the big numbered circle: the exact place the 3D scan camera stood. Every meter you are off makes this spot about a meter off.';
export const CAL_YOU_FAR = (m: number, n: number) =>
  `GPS puts you about ${whole(m)} m from spot ${n}. Follow the dashed line on the plan.`;
export const CAL_YOU_CLOSE = (n: number) =>
  `You are close: within GPS accuracy of spot ${n}. Use the name and the plan to stand exactly on it.`;
export const CAL_YOU_ROUGH = (rmsM: number) =>
  `Your blue dot comes from the calibration in use now (typical error about ${tenth(rmsM)} m), so treat it as a rough guide.`;
export const CAL_YOU_NO_CAL =
  'There is no calibration yet, so the plan cannot show where you are. Find the spot by its name and the plan.';
export const CAL_YOU_WAITING = 'Your blue dot appears on the plan when GPS answers.';
export const CAL_STEPS_TITLE = 'What to do';
export const CAL_STEPS = (n: number, seconds: number): string[] => [
  `Walk to spot ${n} and stand on it.`,
  'Wait until the GPS line at the bottom says good enough.',
  `Press "I'm standing at spot ${n}" and stand still for ${seconds} seconds.`,
  'Then the screen tells you where to go next.',
];

// GPS state: one short line next to the button...
export const CAL_GPS_STARTING = 'Turning on GPS...';
export const CAL_GPS_WAITING = 'Waiting for GPS...';
export const CAL_GPS_GOOD = (accM: number) => `GPS accuracy about ${whole(accM)} m: good enough`;
export const CAL_GPS_WEAK = (accM: number, limitM: number) => `GPS accuracy about ${whole(accM)} m: wait for ${limitM} m or better`;
export const CAL_GPS_NO_ACCURACY = 'The phone does not report GPS accuracy';
export const CAL_GPS_DENIED_SHORT = 'Location is not allowed';
export const CAL_GPS_NOT_PRECISE_SHORT = 'Precise Location is off';
export const CAL_GPS_ERROR_SHORT = 'GPS is not working';
// ...and what to do about it, in the page.
export const CAL_GPS_DENIED =
  'Location is not allowed for this app, so it cannot record. Allow location for Expo Go in Settings, then tap "Check again".';
export const CAL_GPS_NOT_PRECISE =
  'Precise Location is off, so the phone blurs GPS on purpose and calibration cannot work. Turn it on (iPhone: Settings, Expo Go, Location, Precise Location), then tap "Check again".';
export const CAL_GPS_ERROR = (e: string) => `GPS error: ${e}. Check that location is on, then tap "Check again".`;
export const CAL_GPS_WEAK_HELP = (limitM: number) =>
  `GPS is rough right now. Alerts use GPS only at ${limitM} m or better. Stand still and give it a moment; nearer a window or the entrance helps. You can still record, but this spot may land farther off.`;
export const CAL_GPS_NO_ACCURACY_HELP = 'You can still record. The result shows how well the spots fit.';
export const CAL_GPS_RETRY = 'Check again';

export const CAL_RECORD = (n: number) => `I'm standing at spot ${n}`;
export const CAL_RECORD_AGAIN = (n: number) => `Record spot ${n} again`;
export const CAL_RECORDING = (n: number) => `Recording spot ${n}: stand still`;
export const CAL_RECORDING_LEFT = (secondsLeft: number, fixes: number) => `${secondsLeft} s left, ${readingsWord(fixes)} so far`;
export const CAL_RECORDED = (n: number) => `Spot ${n} recorded`;
export const CAL_RECORDED_DETAIL = (fixes: number, accM: number | null, time: string) =>
  `${readingsWord(fixes)} at ${time}, phone accuracy ${accM != null ? `about ${whole(accM)} m` : 'not reported'}.`;
export const CAL_RECORDED_ROUGH = (limitM: number) =>
  `That accuracy is worse than ${limitM} m. If you can, record it again once GPS improves.`;
export const CAL_RECORD_ERROR = (e: string) => `Not recorded. ${e}`;
export const CAL_NEXT_SPOT = (n: number) => `Go to spot ${n}`;
export const CAL_SKIP = 'Skip this spot';
export const CAL_SKIP_TO_RESULT = 'Skip to the result';

export const CAL_PLAN_TARGET = (n: number) => `Spot ${n}: stand here`;
export const CAL_PLAN_DONE = 'Recorded';
export const CAL_PLAN_TODO = 'Not recorded yet';
export const CAL_PLAN_YOU = 'You (GPS)';
export const CAL_PLAN_YOU_OFF = 'You (GPS, off the plan)';
export const CAL_PLAN_NORTH = 'North';
export const CAL_PLAN_ALERT_START = 'Alert start';
export const CAL_PLAN_A11Y = 'Floor plan with the calibration spots';

// The result, in plain words first; the numbers for the team are behind a toggle.
export const CAL_RESULT_TITLE = 'Result';
export const CAL_RESULT_FROM = (n: number, total: number) => `From ${n} of ${total} spots.`;
export const CAL_RESULT_ERROR = (rmsM: number) => `Typical error: about ${tenth(rmsM)} m`;
export const CAL_RESULT_ERROR_HELP =
  'After GPS is lined up with the plan, this is how far a recorded spot typically lands from its real place. Expect the blue dot in an alert to start about this far off, sometimes more.';
export const CAL_WHOSE_DEFAULT = "the team's calibration";
export const CAL_WHOSE_DEVICE = "this phone's calibration";
export const CAL_RESULT_BETTER = (whose: string, rmsM: number) => `Better than ${whose} in use now (about ${tenth(rmsM)} m). Use this one.`;
export const CAL_RESULT_NOT_BETTER = (whose: string, rmsM: number) =>
  `Not better than ${whose} in use now (about ${tenth(rmsM)} m). Keep that one, or redo the worst spot and look again.`;
export const CAL_RESULT_FIRST = 'No calibration is in use yet, so this would be the first one.';
export const CAL_RESULT_IN_USE = 'This is the calibration in use on this phone.';
export const CAL_RESULT_TOO_ROUGH = (limitM: number) =>
  `Too rough to use: as large as the ${limitM} m limit alerts use, so the blue dot could start on the wrong side of the room. Redo the worst spots.`;
export const CAL_RESULT_TWO_SPOTS =
  'Only 2 spots: with two, this number cannot show whether the plan is turned the wrong way. Record a third spot before using it.';
export const CAL_RESULT_MIRROR = (mirrorM: number, rmsM: number) =>
  `Something is off: the fit is closer with the plan flipped (about ${tenth(mirrorM)} m against ${tenth(rmsM)} m). A spot was probably recorded in the wrong place. Redo the spots, and tell the team if it stays like this.`;
export const CAL_RESULT_UNSOLVABLE =
  'These recordings cannot be lined up with the plan: their GPS readings are all in one place. Redo the spots.';
export const CAL_RESULT_NEED_TWO = 'Record at least 2 spots to see a result.';
export const CAL_RESULT_SPOTS = 'Each spot';
export const CAL_RESULT_SPOT_OFF = (m: number) => `about ${tenth(m)} m off`;
export const CAL_RESULT_WORST = 'worst';
export const CAL_REDO = 'Redo';
export const CAL_RECORD_SHORT = 'Record';
export const CAL_LEAVE_OUT = 'Leave out';
export const CAL_REDO_SPOT = (n: number) => `Redo spot ${n}`;
export const CAL_RECORD_SPOT = (n: number) => `Record spot ${n}`;
export const CAL_SAVE = 'Use it on this phone';
export const CAL_SAVE_ANYWAY = 'Use it on this phone anyway';
export const CAL_SAVED = 'Saved. Alerts on this phone in this building now use this calibration.';
export const CAL_SAVE_SCOPE =
  'Saving changes this phone only. To give every phone this calibration, send the numbers to the team: they go into lib/georefDefaults.ts in the app.';
export const CAL_SHARE = 'Send the numbers to the team';
export const CAL_DETAILS_SHOW = 'Show details for the team';
export const CAL_DETAILS_HIDE = 'Hide details for the team';
export const CAL_DONE = 'Done';
export const CAL_DETAIL_TRANSFORM = (rotDeg: number, tx: number, tz: number, spots: number) =>
  `Rotation ${rotDeg.toFixed(2)} degrees, translation x ${tx.toFixed(2)} m, z ${tz.toFixed(2)} m, from ${spotsWord(spots)}.`;
export const CAL_DETAIL_RMS = (rmsM: number) => `RMS of the residuals: ${tenth(rmsM)} m.`;
export const CAL_DETAIL_PAIRS = 'Distance between spots, GPS against scan:';
export const CAL_DETAIL_PAIR = (a: string, b: string, gpsM: number, scanM: number) =>
  `${a} to ${b}: GPS ${tenth(gpsM)} m, scan ${tenth(scanM)} m`;
export const CAL_DETAIL_MIRROR = (mirrorM: number) =>
  `Mirror check: the same fit with the plan flipped has RMS ${tenth(mirrorM)} m. It should be clearly worse than the real fit.`;
export const CAL_DETAIL_SNIPPET = 'For lib/georefDefaults.ts';

// "Check where GPS puts me": the alert's own GPS start rule, live.
export const CAL_CHECK_TITLE = 'Where GPS puts you';
export const CAL_CHECK_HELP =
  'The blue dot is where an alert would think you are, using the calibration in use now. Walk around and compare it with where you really are.';
export const CAL_CHECK_NEAREST = (name: string, m: number) => `Nearest named spot: ${name}, about ${whole(m)} m from your dot.`;
export const CAL_CHECK_OK = (m: number) =>
  `An alert would use GPS now and start your dot at the ringed scan point, about ${whole(m)} m from the blue dot.`;
export const CAL_CHECK_NO_ACCURACY =
  'An alert would not use GPS now: the phone gives no accuracy figure. It would ask the helper to tap the map instead.';
export const CAL_CHECK_POOR = (accM: number, limitM: number) =>
  `An alert would not use GPS now: accuracy is about ${whole(accM)} m and alerts need ${limitM} m or better. It would ask the helper to tap the map instead.`;
export const CAL_CHECK_OFF_MAP = (limitM: number) =>
  `An alert would not use GPS now: your dot is more than ${limitM} m from every scan point on this floor. It would ask the helper to tap the map instead.`;
export const CAL_CHECK_NO_SWEEPS = 'An alert would not use GPS here: this floor has no scan points.';
