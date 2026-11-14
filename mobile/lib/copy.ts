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
  aed_runner: 'Get the AED, then bring it to the person. Tap "AED here" when you reach them with it.',
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
