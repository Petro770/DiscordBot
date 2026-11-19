"""Estimate a steady beat grid from the attack envelope of a downloaded track."""
from array import array
from dataclasses import dataclass
import math
import subprocess
import sys


_SAMPLE_RATE = 120
_MIN_BPM = 65
_MAX_BPM = 200


@dataclass(frozen=True)
class BeatGrid:
    bpm: float
    seconds: tuple[float, ...]


def read_beat_grid(ffmpeg: str, audio_path: str) -> BeatGrid | None:
    result = subprocess.run(
        [ffmpeg, "-nostdin", "-loglevel", "error", "-i", audio_path,
         "-vn", "-sn", "-dn", "-af",
         f"aformat=channel_layouts=mono,highpass=f=35,lowpass=f=250,"
         f"aeval=abs(val(0)):c=mono,lowpass=f=20,aresample={_SAMPLE_RATE}",
         "-f", "f32le", "pipe:1"],
        check=True, capture_output=True, timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    envelope = array("f")
    envelope.frombytes(result.stdout)
    if sys.byteorder != "little":
        envelope.byteswap()
    return estimate_beat_grid(envelope)


def estimate_beat_grid(envelope: array, *, relaxed: bool = False) -> BeatGrid | None:
    rate = _SAMPLE_RATE
    if len(envelope) < (3 if relaxed else 4) * rate:
        return None

    # Emphasize attacks over sustained bass, with a noise floor for quiet sections.
    levels = [math.log1p(200 * max(0, level)) for level in envelope]
    attack_span = 3
    attacks = [0.0] * attack_span + [
        max(0.0, levels[i] - levels[i - attack_span])
        for i in range(attack_span, len(levels))
    ]
    threshold = max(0.015, 0.7 * sum(attacks) / len(attacks))
    onsets = [max(0.0, attack - threshold) for attack in attacks]
    if not any(onsets):
        return None

    # A short blur tolerates small timing deviations between repeated attacks.
    signal = [0.0, *(
        (before + 2 * current + after) / 4
        for before, current, after in zip(onsets, onsets[1:], onsets[2:])
    ), 0.0]
    if relaxed:
        # Smooth over timing jitter in real performances and compressed audio.
        signal = [0.0] * 3 + [
            sum(signal[i - 3:i + 4]) / 7 for i in range(3, len(signal) - 3)
        ] + [0.0] * 3
    energy = [0.0]
    for value in signal:
        energy.append(energy[-1] + value * value)
    first_lag = round(60 * rate / _MAX_BPM)
    last_lag = round(60 * rate / _MIN_BPM)
    scores = {}
    for lag in range(first_lag - 1, last_lag + 2):
        norm = math.sqrt(energy[-1 - lag] * max(0, energy[-1] - energy[lag]))
        scores[lag] = sum(a * b for a, b in zip(signal, signal[lag:])) / norm if norm else 0.0

    peaks = [
        lag for lag in range(first_lag, last_lag + 1)
        if scores[lag] > scores[lag - 1] and scores[lag] >= scores[lag + 1]
    ]
    if not peaks:
        return None
    best = max(scores[lag] for lag in peaks)
    if best < (0.22 if relaxed else 0.28):
        return None
    # Prefer the shorter interval when a multiple scores almost equally well.
    lag = next(lag for lag in peaks if scores[lag] >= 0.9 * best)
    left, center, right = (scores[lag + delta] for delta in (-1, 0, 1))
    period = lag + (right - left) / (2 * (2 * center - left - right))

    # Pick the phase supported by the greatest concentration of attacks.
    bins = [0.0] * round(period)
    for index, onset in enumerate(onsets):
        phase_bin = round(index / period * len(bins)) % len(bins)
        bins[phase_bin] += onset
    phase_window = range(-4, 5) if relaxed else range(-2, 3)
    phase_bin = max(
        range(len(bins)),
        key=lambda i: sum(bins[(i + delta) % len(bins)] for delta in phase_window),
    )
    phase_weight = sum(bins[(phase_bin + delta) % len(bins)] for delta in phase_window)
    if phase_weight < 0.2 * sum(bins):
        return None
    # Use the weighted center of the winning phase window to break plateaus.
    offset = sum(delta * bins[(phase_bin + delta) % len(bins)]
                 for delta in phase_window) / phase_weight
    phase = ((phase_bin + offset) / len(bins) * period) % period
    beats = tuple(
        (phase + index * period) / rate
        for index in range(math.ceil((len(envelope) - phase) / period))
    )
    return BeatGrid(60 * rate / period, beats)


def estimate_downbeat_phase(envelope: array, beats: tuple[float, ...]) -> int | None:
    """Find a strongly repeated four-beat accent in the low-frequency attacks."""
    bar_count = len(beats) // 4
    if bar_count < 9:
        return None

    attacks = []
    for beat in beats[:bar_count * 4]:
        center = round(beat * _SAMPLE_RATE)
        first = max(4, center - 7)
        end = min(len(envelope), center + 10)
        attacks.append(max((envelope[i] - envelope[i - 4] for i in range(first, end)), default=0))

    votes = []
    for start in range(0, len(attacks), 4):
        bar = attacks[start:start + 4]
        strongest = max(range(4), key=bar.__getitem__)
        winner, runner_up = sorted(bar, reverse=True)[:2]
        # Equal kicks (including two-beat patterns) provide no bar-start evidence.
        votes.append(strongest if winner >= 0.004 and winner > 1.35 * runner_up else None)

    phase = max(range(4), key=votes.count)
    # Require agreement throughout the track so a single loud section cannot
    # determine the bar phase for the entire video.
    for section in range(3):
        chunk = votes[section * bar_count // 3:(section + 1) * bar_count // 3]
        if chunk.count(phase) * 4 < len(chunk) * 3:
            return None
    return phase
