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
