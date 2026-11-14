import { createAudioPlayer, setAudioModeAsync, type AudioPlayer } from 'expo-audio';
import * as Haptics from 'expo-haptics';

// Looped alarm plus repeating haptics while a new dispatch is waiting for an answer.
// The player outlives any one screen, so it is created with createAudioPlayer and kept for the
// app's lifetime (never released; there is only one).

const HAPTIC_EVERY_MS = 800;

let player: AudioPlayer | null = null;
let hapticTimer: ReturnType<typeof setInterval> | null = null;
let running = false;

function getPlayer(): AudioPlayer {
  if (!player) {
    player = createAudioPlayer(require('../assets/alarm.mp3'));
    player.loop = true;
    player.volume = 1;
  }
  return player;
}

/**
 * Plays even with the iOS ring/silent switch on silent: playsInSilentMode is set explicitly
 * (it is also the expo-audio default). 'doNotMix' pauses other apps' audio during the alarm.
 * Needs a check on a real iPhone; see mobile/README.md.
 */
export async function startAlarm(): Promise<void> {
  if (running) return;
  running = true;
  try {
    await setAudioModeAsync({ playsInSilentMode: true, interruptionMode: 'doNotMix', shouldPlayInBackground: false });
  } catch {
    // Keep going: haptics still work and the screen still shows the alert.
  }
  if (!running) return; // stopped while the audio mode was being set
  try {
    const p = getPlayer();
    await p.seekTo(0);
    if (!running) return;
    p.play();
  } catch {
    // Audio can fail (for example, web autoplay rules). Haptics and the screen still alert.
  }
  void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning).catch(() => {});
  if (hapticTimer) clearInterval(hapticTimer);
  hapticTimer = setInterval(() => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy).catch(() => {});
  }, HAPTIC_EVERY_MS);
}

export function stopAlarm(): void {
  running = false;
  if (hapticTimer) {
    clearInterval(hapticTimer);
    hapticTimer = null;
  }
  try {
    player?.pause();
  } catch {
    // Nothing to stop.
  }
}

export function isAlarmRunning(): boolean {
  return running;
}
