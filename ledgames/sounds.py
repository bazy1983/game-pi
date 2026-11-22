"""The sounds, made here from scratch (there are no sound files): mono
samples, RATE a second, -1 to 1. The speaker makes them all once it's open
(see speaker.py), so making them can take a moment.

Game sounds come in packs, named "<pack>/<sound>":

  modern  smooth sweeps, chimes and chords
  retro   like the sound chip of an early home game console: square waves on
          a coarse set of pitches, a noise generator, 16 volume steps, and
          nothing changes faster than 60 times a second (see retro())

A game picks a pack and asks for sounds by name (see games/base.py).
"""

import math
import random
from collections.abc import Callable

RATE = 48_000
PEAK = 0.85  # sounds are scaled down to this if they'd go louder (chords add up)


# --- building blocks ---------------------------------------------------------------


def _wave(name: str) -> Callable[[float], float]:
    """One cycle of a wave, from its phase (0–1)."""
    if name == "sine":
        return lambda p: math.sin(2 * math.pi * p)
    if name == "triangle":
        return lambda p: 4 * abs(p - 0.5) - 1
    raise ValueError(name)


def tone(
    seconds: float,
    freq: float,
    to: float | None = None,
    wave: str = "sine",
    vol: float = 0.5,
    decay: float | None = None,
    attack: float = 0.003,
    vibrato: tuple[float, float] = (0.0, 0.0),
) -> list[float]:
    """A note: `freq` Hz, gliding to `to` Hz if given. `decay` (s) makes it
    ring out; `vibrato` is (depth as a fraction of the pitch, rate in Hz)."""
    n = int(seconds * RATE)
    shape = _wave(wave)
    depth, rate = vibrato
    ratio = (to / freq) if to else 1.0
    out = []
    phase = 0.0
    for i in range(n):
        t = i / RATE
        f = freq * ratio ** (t / seconds)  # glides evenly in pitch
        if depth:
            f *= 1 + depth * math.sin(2 * math.pi * rate * t)
        phase = (phase + f / RATE) % 1.0
        env = min(1.0, t / attack, (seconds - t) / 0.005)  # no clicks at either end
        if decay:
            env *= math.exp(-t / decay)
        out.append(vol * env * shape(phase))
    return out


def noise(seconds: float, vol: float = 0.4, decay: float | None = None, smooth: float = 1.0, seed: int = 1) -> list[float]:
    """A burst of noise. `smooth` below 1 takes the hiss off (a simple filter)."""
    rng = random.Random(seed)  # the same sound every time
    n = int(seconds * RATE)
    out = []
    y = 0.0
    for i in range(n):
        t = i / RATE
        y += smooth * (rng.uniform(-1, 1) - y)
        env = min(1.0, (seconds - t) / 0.005)
        if decay:
            env *= math.exp(-t / decay)
        out.append(vol * env * y)
    return out


def mix(*parts: tuple[float, list[float]]) -> list[float]:
    """Sounds laid over each other, each (when it starts in s, sound)."""
    length = max(int(at * RATE) + len(s) for at, s in parts)
    out = [0.0] * length
    for at, s in parts:
        start = int(at * RATE)
        for i, v in enumerate(s):
            out[start + i] += v
    peak = max((abs(v) for v in out), default=0.0)
    if peak > PEAK:
        out = [v * PEAK / peak for v in out]
    return out


# An early console's sound chip makes its pitches by dividing a ~31 kHz
# clock by a whole number, so only a few, slightly out-of-tune notes exist.
# "pure" halves it (490 Hz–15.7 kHz), "low" divides by 6 (163 Hz–5.2 kHz);
# "noise" clocks a 9-bit shift register at the clock / (div + 1).
CLOCK = 31_400
FRAME = RATE // 60


def retro(frames: list[tuple[str, int, int]]) -> list[float]:
    """Retro sound, frame by frame (1/60 s each): (wave, divider 0–31,
    volume 0–15). Wave "pure", "low" or "noise"; "" is silence."""
    out = []
    phase = 0.0
    lfsr = 0x1FF
    for wave, div, vol in frames:
        amp = 0.6 * vol / 15
        if wave == "noise":
            step = CLOCK / (div + 1) / RATE
            for _ in range(FRAME):
                phase += step
                while phase >= 1:
                    phase -= 1
                    bit = (lfsr ^ (lfsr >> 4)) & 1
                    lfsr = (lfsr >> 1) | (bit << 8)
                out.append(amp if lfsr & 1 else -amp)
        elif wave in ("pure", "low"):
            freq = CLOCK / (2 if wave == "pure" else 6) / (div + 1)
            step = freq / RATE
            for _ in range(FRAME):
                phase = (phase + step) % 1.0
                out.append(amp if phase < 0.5 else -amp)
        else:
            out.extend([0.0] * FRAME)
    return out


# --- the sounds -----------------------------------------------------------------------


def chime() -> list[float]:
    """The speaker's test sound: three rising notes that ring out."""
    return mix(*((at, tone(0.9 - at, f, vol=0.33, decay=0.2)) for at, f in ((0, 523.25), (0.12, 659.25), (0.24, 783.99))))


C5, E5, G5, C6 = 523.25, 659.25, 783.99, 1046.5

MODERN = {
    "shoot": lambda: tone(0.08, 700, 1600, "triangle", vol=0.45, decay=0.05),
    "hit": lambda: mix((0, tone(0.2, 1318.5, vol=0.4, decay=0.06)), (0, tone(0.2, 1975.5, vol=0.22, decay=0.05)),
                       (0, noise(0.02, 0.25))),
    "miss": lambda: tone(0.25, 260, 130, "triangle", vol=0.6, decay=0.12),
    "grow": lambda: tone(0.07, 140, 110, vol=0.3, decay=0.025),
    "spit": lambda: mix((0, noise(0.12, 0.35, decay=0.05, smooth=0.15)), (0, tone(0.15, 500, 220, vol=0.3, decay=0.06))),
    "block": lambda: mix((0, tone(0.3, 880, vol=0.35, decay=0.08)), (0, tone(0.3, 1245, vol=0.25, decay=0.06)),
                         (0, noise(0.015, 0.3))),
    "poisoned": lambda: tone(0.6, 180, 140, "triangle", vol=0.6, decay=0.35, vibrato=(0.08, 14)),
    "dud": lambda: tone(0.05, 120, 80, vol=0.4, decay=0.015),
    "win": lambda: mix(*((0.1 * k, tone(1.3 - 0.1 * k, f, wave="triangle", vol=0.3, decay=0.35)) for k, f in enumerate((C5, E5, G5, C6)))),
    "lose": lambda: mix((0.0, tone(0.3, 392.0, wave="triangle", vol=0.45, decay=0.25)),
                        (0.32, tone(0.3, 370.0, wave="triangle", vol=0.45, decay=0.25)),
                        (0.64, tone(0.3, 349.2, wave="triangle", vol=0.45, decay=0.25)),
                        (0.96, tone(0.9, 329.6, wave="triangle", vol=0.45, decay=0.5, vibrato=(0.02, 6)))),
}

RETRO = {
    "shoot": lambda: retro([("pure", d, 12 - k) for k, d in enumerate((2, 3, 4, 5, 7, 9, 12))]),
    "hit": lambda: retro([("noise", 8 + k, max(0, 14 - 2 * k)) for k in range(8)]),
    "miss": lambda: retro([("low", 20, 10)] * 5 + [("low", 26, 8)] * 7),
    "grow": lambda: retro([("low", 31, 5)]),
    "spit": lambda: retro([("noise", 2 + k, 9 - k) for k in range(8)]),
    "block": lambda: retro([("pure", 6, 12), ("pure", 4, 12)] * 3 + [("pure", 6, v) for v in (8, 5, 3)]),
    "poisoned": lambda: retro([("low", 28 if k % 4 < 2 else 31, 10) for k in range(36)]),
    "dud": lambda: retro([("noise", 30, 6), ("noise", 31, 3)]),
    "win": lambda: retro([("pure", d, 12) for d, n in ((31, 6), (27, 6), (24, 6), (20, 6), (24, 6), (20, 6)) for _ in range(n)]
                         + [("pure", 15, 12 - k * 12 // 30) for k in range(30)]),
    "lose": lambda: retro([("low", 10 + k // 3, 12) for k in range(48)] + [("noise", 31, max(0, 10 - k // 2)) for k in range(20)]),
}

PACKS = {"modern": MODERN, "retro": RETRO}

# Everything the speaker can play, by name.
SOUNDS: dict[str, Callable[[], list[float]]] = {
    "chime": chime,
    **{f"{pack}/{name}": make for pack, sounds in PACKS.items() for name, make in sounds.items()},
}
