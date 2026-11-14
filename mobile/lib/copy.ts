// User-facing wording. Lines marked VERBATIM are copied from the build spec (CLAUDE.md)
// and must not be reworded. Repo rule: no em-dash characters anywhere.

import type { ResponderRole } from './types';

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
