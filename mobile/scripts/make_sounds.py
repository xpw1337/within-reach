"""Generate the app's sound assets from pure sine tones (no third-party audio).

Writes:
  assets/alarm.mp3  two-tone alert, 2 s, meant to loop
  assets/tick.wav   short metronome click (WAV, so there is no MP3 encoder delay)

Run from mobile/:  python3 scripts/make_sounds.py   (needs ffmpeg on PATH for the MP3)
"""

import math
import os
import struct
import subprocess
import tempfile
import wave

RATE = 44100
HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "..", "assets")


def tone(freq_hz, seconds, volume=0.8, fade_s=0.008, decay=None):
    n = int(RATE * seconds)
    fade_n = max(1, int(RATE * fade_s))
    out = []
    for i in range(n):
        t = i / RATE
        amp = volume
        if i < fade_n:
            amp *= i / fade_n
        if i > n - fade_n:
            amp *= (n - i) / fade_n
        if decay is not None:
            amp *= math.exp(-t / decay)
        # Add a quiet third harmonic so the tone cuts through on small phone speakers.
        s = math.sin(2 * math.pi * freq_hz * t) + 0.25 * math.sin(2 * math.pi * 3 * freq_hz * t)
        out.append(amp * s / 1.25)
    return out


def silence(seconds):
    return [0.0] * int(RATE * seconds)


def write_wav(path, samples):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        frames = b"".join(struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767)) for s in samples)
        w.writeframes(frames)


def main():
    os.makedirs(ASSETS, exist_ok=True)

    # Alarm: four high/low pairs (960 Hz / 720 Hz), 0.25 s each, 2 s total.
    alarm = []
    for _ in range(4):
        alarm += tone(960, 0.25)
        alarm += tone(720, 0.25)
    with tempfile.TemporaryDirectory() as tmp:
        wav_path = os.path.join(tmp, "alarm.wav")
        write_wav(wav_path, alarm)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", wav_path, "-codec:a", "libmp3lame", "-b:a", "128k",
             os.path.join(ASSETS, "alarm.mp3")],
            check=True,
        )

    # Metronome tick: 30 ms click at 1.6 kHz with a fast decay, then a little silence.
    tick = tone(1600, 0.03, volume=0.9, fade_s=0.001, decay=0.012) + silence(0.02)
    write_wav(os.path.join(ASSETS, "tick.wav"), tick)
    print("wrote assets/alarm.mp3 and assets/tick.wav")


if __name__ == "__main__":
    main()
