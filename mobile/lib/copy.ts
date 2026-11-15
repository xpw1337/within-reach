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
