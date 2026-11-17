"""Rebuild the project's original notification chimes (no external samples)."""
import math
import struct
import wave
from pathlib import Path

SAMPLE_RATE = 44100
# Start time, note frequency, duration. Short, distinct musical motifs.
MOTIFS = {
    "started": ((0, 523.25, 0.14), (0.10, 659.25, 0.20)),
    "finished": ((0, 523.25, 0.20), (0.14, 659.25, 0.20), (0.28, 783.99, 0.35)),
    "error": ((0, 392.00, 0.23), (0.18, 311.13, 0.23), (0.36, 261.63, 0.32)),
}


def generate(directory):
    directory.mkdir(parents=True, exist_ok=True)
    for name, notes in MOTIFS.items():
        length = math.ceil((max(start + duration for start, _, duration in notes) + 0.05) * SAMPLE_RATE)
        samples = [0.0] * length
        for start, frequency, duration in notes:
            for i in range(round(duration * SAMPLE_RATE)):
                t = i / SAMPLE_RATE
                attack = min(1, t / 0.012)
                release = min(1, (duration - t) / 0.075)
                envelope = attack * release * math.exp(-3 * t / duration)
                tone = math.sin(2 * math.pi * frequency * t) + 0.18 * math.sin(4 * math.pi * frequency * t)
                samples[round(start * SAMPLE_RATE) + i] += tone * envelope * 0.38
        with wave.open(str(directory / f"{name}.wav"), "wb") as output:
            output.setparams((1, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
            output.writeframes(b"".join(struct.pack("<h", round(max(-1, min(1, value)) * 32767)) for value in samples))


if __name__ == "__main__":
    generate(Path(__file__).resolve().parents[1] / "static" / "sounds")
