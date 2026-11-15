// Words shown or spoken on the phone. CPR lines follow spec section 3 (medically reviewed wording).

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

export const CPR_GUIDE = 'CPR guide';
