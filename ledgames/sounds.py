"""The sounds, made here from scratch (there are no sound files): mono
samples, RATE a second, -1 to 1. The speaker makes them all once it's open
(see speaker.py), so making them can take a moment.

Game sounds come in packs, named "<pack>/<sound>":

  modern  smooth sweeps, chimes and chords
  retro   like the sound chip of an early home game console: square waves on
          a coarse set of pitches, a noise generator, 16 volume steps, and
          nothing changes faster than 60 times a second (see retro())

A game picks a pack and asks for sounds by name (see games/base.py). Every
pack has every sound; games share the ones that fit (win, lose).
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
SIMON_NOTES = (329.6, 440.0, 554.4, 659.3, 880.0)  # one per color, a pentatonic scale: any order sounds fine
MORSE_BEEPS = (180, 250, 350, 540, 750, 1050)  # ms: Morse Code's dots and dashes, at each difficulty's speed
HEATS = ("freezing", "cold", "cool", "warm", "hot", "burning")  # Hot and Cold, coldest first


def _modern_heat(k: int) -> list[float]:
    """Hot and Cold's heats: higher and busier the hotter; freezing is an icy shimmer."""
    if k == 0:
        return mix((0, tone(0.5, 2637, vol=0.15, decay=0.2, vibrato=(0.01, 8))), (0, tone(0.5, 3136, vol=0.1, decay=0.15)))
    freq = (523.25, 659.25, 783.99, 987.8, 1174.7)[k - 1]
    parts = [(0, tone(0.45, freq, wave="sine" if k < 3 else "triangle", vol=0.38, decay=0.2,
                      vibrato=(0.03, 18) if k == 5 else (0.0, 0.0)))]
    if k >= 4:
        parts.append((0, noise(0.35, 0.08 * (k - 3), decay=0.15, smooth=0.6)))  # a sizzle
    return mix(*parts)


def _retro_heat(k: int) -> list[float]:
    if k == 0:
        return retro([("pure", 3, 6)] * 12)
    if k <= 3:
        return retro([("pure", (31, 24, 18)[k - 1], 10)] * 14)
    a, b = (13, 14) if k == 4 else (9, 10)
    return retro([("pure", a if f % 2 else b, 11 + (k == 5)) for f in range(16 + 4 * (k == 5))])

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
    # Fast Tap
    "ready": lambda: mix((0, tone(0.09, 660, vol=0.35, decay=0.05)), (0.15, tone(0.09, 880, vol=0.35, decay=0.05))),
    "sudden": lambda: mix((0, tone(0.18, 98, vol=0.6, decay=0.08)), (0.22, tone(0.18, 98, vol=0.6, decay=0.08)),
                          (0.44, tone(0.6, 147, 294, wave="triangle", vol=0.45, decay=0.35))),
    "out": lambda: mix((0, tone(0.12, 440, wave="triangle", vol=0.4)), (0.13, tone(0.22, 330, wave="triangle", vol=0.4, decay=0.12))),
    "round_win": lambda: mix((0, tone(0.35, 1046.5, vol=0.4, decay=0.12)), (0.1, tone(0.5, 1568, vol=0.35, decay=0.18))),
    "round_lose": lambda: tone(0.45, 330, 165, wave="triangle", vol=0.5, decay=0.25),
    # Countdowns, taps and bounces (Sumo, Ping Pong, Red Light, Hot Potato)
    "count": lambda: tone(0.12, 880, vol=0.4, decay=0.06),
    "go": lambda: mix((0, tone(0.3, 1320, vol=0.4, decay=0.15)), (0, tone(0.3, 1760, vol=0.2, decay=0.12))),
    "blip_low": lambda: tone(0.05, 330, wave="triangle", vol=0.35, decay=0.02),
    "blip_high": lambda: tone(0.05, 660, wave="triangle", vol=0.35, decay=0.02),
    "point": lambda: mix((0, tone(0.15, 784, vol=0.35, decay=0.08)), (0.08, tone(0.3, 1175, vol=0.35, decay=0.12))),
    "faster": lambda: tone(0.35, 400, 1600, wave="triangle", vol=0.35, decay=0.2),
    "tick": lambda: tone(0.03, 2000, vol=0.25, decay=0.008),
    # Simon Says
    **{f"note{k + 1}": (lambda f=f: tone(0.4, f, wave="triangle", vol=0.45, decay=0.25)) for k, f in enumerate(SIMON_NOTES)},
    # Morse Code
    **{f"beep_{ms}": (lambda ms=ms: tone(ms / 1000, 700, vol=0.45)) for ms in MORSE_BEEPS},
    "word_end": lambda: mix((0, tone(0.2, 988, vol=0.3, decay=0.1)), (0.12, tone(0.35, 740, vol=0.3, decay=0.15))),
    # Red Light, Green Light
    "light_green": lambda: tone(0.25, 523, 1046, wave="triangle", vol=0.4, decay=0.15),
    "light_yellow": lambda: mix((0, tone(0.1, 880, vol=0.35)), (0.16, tone(0.1, 880, vol=0.35))),
    "light_red": lambda: tone(0.4, 600, 200, wave="triangle", vol=0.5, decay=0.2),
    "slide": lambda: tone(0.5, 800, 150, wave="triangle", vol=0.4, decay=0.3),
    # Hot Potato
    "throw": lambda: mix((0, noise(0.18, 0.35, decay=0.08, smooth=0.25)), (0, tone(0.18, 300, 900, vol=0.2, decay=0.08))),
    "catch": lambda: tone(0.08, 220, 140, vol=0.45, decay=0.03),
    "boom": lambda: mix((0, noise(0.8, 0.8, decay=0.25, smooth=0.08)), (0, tone(0.6, 90, 40, vol=0.6, decay=0.25))),
    # Hot and Cold
    "dig": lambda: mix((0, noise(0.08, 0.5, decay=0.03, smooth=0.1)), (0, tone(0.1, 120, 70, vol=0.5, decay=0.04))),
    **{f"heat_{h}": (lambda k=k: _modern_heat(k)) for k, h in enumerate(HEATS)},
    "treasure": lambda: mix(*((0.07 * k, tone(0.45, f, vol=0.25, decay=0.15)) for k, f in enumerate((1046.5, 1318.5, 1568, 2093)))),
    # Tower Stack
    "chop": lambda: mix((0, noise(0.06, 0.45, decay=0.02, smooth=0.5)), (0, tone(0.1, 196, wave="triangle", vol=0.4, decay=0.04))),
    "perfect": lambda: mix((0, tone(0.3, 1568, vol=0.35, decay=0.12)), (0, tone(0.3, 2093, vol=0.2, decay=0.1))),
    "grew": lambda: tone(0.3, 523, 1046, vol=0.35, decay=0.15),
    "fall": lambda: tone(0.7, 600, 80, wave="triangle", vol=0.45, decay=0.4),
    "crumble": lambda: mix((0, noise(1.0, 0.5, decay=0.35, smooth=0.05)), (0, tone(0.8, 60, 40, vol=0.4, decay=0.3))),
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
    # Fast Tap
    "ready": lambda: retro([("pure", 24, 10)] * 6 + [("", 0, 0)] * 3 + [("pure", 20, 10)] * 6),
    "sudden": lambda: retro(([("low", 31, 12)] * 6 + [("", 0, 0)] * 6) * 2 + [("low", 31 - k // 2, 12) for k in range(30)]),
    "out": lambda: retro([("low", 18, 12)] * 10 + [("low", 18, v) for v in (8, 4)]),
    "round_win": lambda: retro([("pure", 15, 12)] * 5 + [("pure", 11, 12)] * 5 + [("pure", 7, v) for v in range(12, 0, -1)]),
    "round_lose": lambda: retro([("low", 14 + k // 2, 11) for k in range(24)]),
    # Countdowns, taps and bounces
    "count": lambda: retro([("pure", 20, 10)] * 6),
    "go": lambda: retro([("pure", 10, 12)] * 15),
    "blip_low": lambda: retro([("low", 16, 9)] * 2),
    "blip_high": lambda: retro([("pure", 22, 9)] * 2),
    "point": lambda: retro([("pure", 15, 11)] * 4 + [("pure", 11, 11)] * 8),
    "faster": lambda: retro([("pure", 31 - k, 10) for k in range(24)]),
    "tick": lambda: retro([("noise", 1, 6)]),
    # Simon Says
    **{f"note{k + 1}": (lambda d=d: retro([("pure", d, 11)] * 12 + [("pure", d, v) for v in (9, 7, 5, 3, 2, 1)]))
       for k, d in enumerate((31, 26, 22, 19, 15))},
    # Morse Code
    **{f"beep_{ms}": (lambda ms=ms: retro([("pure", 21, 10)] * round(ms * 60 / 1000))) for ms in MORSE_BEEPS},
    "word_end": lambda: retro([("pure", 12, 10)] * 6 + [("pure", 16, 10)] * 10),
    # Red Light, Green Light
    "light_green": lambda: retro([("pure", 24 - 2 * k, 11) for k in range(9)] + [("pure", 6, 11)] * 6),
    "light_yellow": lambda: retro([("pure", 15, 10)] * 5 + [("", 0, 0)] * 4 + [("pure", 15, 10)] * 5),
    "light_red": lambda: retro([("low", 10 + k, 12) for k in range(18)]),
    "slide": lambda: retro([("pure", 8 + k, 10) for k in range(24)]),
    # Hot Potato
    "throw": lambda: retro([("noise", 12 - k, 8) for k in range(8)]),
    "catch": lambda: retro([("low", 26, 10)] * 3),
    "boom": lambda: retro([("noise", 25 + k // 6, max(0, 15 - k // 3)) for k in range(45)]),
    # Hot and Cold
    "dig": lambda: retro([("noise", 28, 12), ("noise", 30, 9), ("low", 31, 8), ("low", 31, 4)]),
    **{f"heat_{h}": (lambda k=k: _retro_heat(k)) for k, h in enumerate(HEATS)},
    "treasure": lambda: retro([("pure", d, 12) for d in (15, 12, 9, 7) for _ in range(5)] + [("pure", 7, v) for v in range(12, 0, -1)]),
    # Tower Stack
    "chop": lambda: retro([("noise", 4, 11), ("noise", 6, 8), ("low", 30, 6)]),
    "perfect": lambda: retro([("pure", 9, 12)] * 4 + [("pure", 7, 12)] * 8),
    "grew": lambda: retro([("pure", 20 - 2 * k, 11) for k in range(8)]),
    "fall": lambda: retro([("pure", 6 + k, 10) for k in range(25)] + [("noise", 30, 8)] * 4),
    "crumble": lambda: retro([("noise", 20 + k // 4, max(0, 12 - k // 5)) for k in range(60)]),
}

PACKS = {"modern": MODERN, "retro": RETRO}

# Everything the speaker can play, by name.
SOUNDS: dict[str, Callable[[], list[float]]] = {
    "chime": chime,
    **{f"{pack}/{name}": make for pack, sounds in PACKS.items() for name, make in sounds.items()},
}
