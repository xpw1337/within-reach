import { setAudioModeAsync, useAudioPlayer } from 'expo-audio';
import * as Haptics from 'expo-haptics';
import { useEffect, useState } from 'react';

/** Spec 9.11: 110 bpm, inside the 100 to 120 per minute range from spec section 3. */
export const METRONOME_BPM = 110;
const BEAT_MS = 60_000 / METRONOME_BPM;
/** The tick is 50 ms long; rewind the player well after it ends, long before its next turn. */
const REWIND_AFTER_MS = 150;

/**
 * Audio tick plus haptic on every beat. Two players alternate so each one has a full beat to
 * rewind, and the schedule is drift-corrected against the wall clock.
 */
export function useMetronome() {
  const tickA = useAudioPlayer(require('../assets/tick.wav'));
  const tickB = useAudioPlayer(require('../assets/tick.wav'));
  const [running, setRunning] = useState(false);
  const [beat, setBeat] = useState(0);

  useEffect(() => {
    if (!running) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let count = 0;
    let next = Date.now();
    const players = [tickA, tickB];

    // Plays with the iOS silent switch on. 'mixWithOthers' so the metronome does not stop other
    // audio, for example a 911 call on speaker. Needs a real-device check; see mobile/README.md.
    void setAudioModeAsync({ playsInSilentMode: true, interruptionMode: 'mixWithOthers', shouldPlayInBackground: false }).catch(
      () => {},
    );

    const tick = () => {
      if (cancelled) return;
      const player = players[count % 2];
      try {
        player.play();
      } catch {
        // Audio unavailable: the haptic and the visual pulse still keep time.
      }
      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy).catch(() => {});
      setTimeout(() => void player.seekTo(0).catch(() => {}), REWIND_AFTER_MS);
      count += 1;
      setBeat(count);

      next += BEAT_MS;
      const now = Date.now();
      if (now - next > BEAT_MS) next = now + BEAT_MS; // fell far behind (app paused): do not burst
      timer = setTimeout(tick, Math.max(0, next - now));
    };
    tick();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      try {
        tickA.pause();
        tickB.pause();
      } catch {
        // Players may already be released on unmount.
      }
    };
  }, [running, tickA, tickB]);

  return { running, beat, start: () => setRunning(true), stop: () => setRunning(false) };
}
