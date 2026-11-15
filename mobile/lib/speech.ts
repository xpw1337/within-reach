import { setAudioModeAsync } from 'expo-audio';
import * as Speech from 'expo-speech';

// On-device text to speech for the AED help screen (expo-speech: no network, works in Expo Go).
//
// Silent mode: on iOS, expo-speech's synthesizer uses the app's audio session by default
// (`useApplicationAudioSession`, passed explicitly below). expo-audio's `playsInSilentMode: true`
// puts that session in the playback category, which ignores the ring/silent switch, the same way the
// alarm and the metronome do. 'mixWithOthers' so a 911 call on speaker is not cut off.
// On Android, speech plays on the media stream, which the ringer's silent mode does not mute; the
// media volume must be up. Both need a real-device check (mobile/README.md).

async function ensureAudioMode(): Promise<void> {
  // Set every time: the alarm switches the mode to 'doNotMix' while it rings.
  try {
    await setAudioModeAsync({ playsInSilentMode: true, interruptionMode: 'mixWithOthers', shouldPlayInBackground: false });
  } catch {
    // Speech may still be audible with the ringer on; the screen shows the text either way.
  }
}

// Bumped by every say() and stopSpeaking(), so a slow earlier call never speaks over a newer one.
let generation = 0;

/** Stops anything being spoken, then speaks `text`. */
export async function say(text: string): Promise<void> {
  const mine = ++generation;
  await ensureAudioMode();
  try {
    await Speech.stop();
  } catch {
    // Nothing was speaking.
  }
  if (mine !== generation) return;
  try {
    Speech.speak(text, { language: 'en-US', useApplicationAudioSession: true });
  } catch {
    // No speech engine: the large text on screen is the fallback.
  }
}

export function stopSpeaking(): void {
  generation += 1;
  void Speech.stop().catch(() => {});
}
