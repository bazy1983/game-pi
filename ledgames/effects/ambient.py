"""Ambient effects for the Lights mode (see lights.py). LED 0 is the bottom.

Each effect is made for a strip length, then draws a frame with
`draw(pixels, t, dt, lut)`. `t` and `dt` are effect time, sped up or slowed
down by the speed setting; `lut` is the chosen palette as 256 colors that
wrap around (index with `& 255`).

A Pi Zero has about 33 ms per frame for everything, so the per-LED loops are
list comprehensions over precomputed tables: a plain loop with a function
call per LED takes 20–30 ms for 250 LEDs there.
"""

import math
import random

from ..colors import OFF, RGB, WHITE, add, scale


def _count(expected: float, rng: random.Random) -> int:
    """How many random events happen this frame, `expected` on average."""
    whole = int(expected)
    return whole + (rng.random() < expected - whole)


def _mix(a: RGB, b: RGB, f: float) -> RGB:
    return (int(a[0] + (b[0] - a[0]) * f), int(a[1] + (b[1] - a[1]) * f), int(a[2] + (b[2] - a[2]) * f))


class Effect:
    name = ""
    sound = False  # reacts to the microphone: the lights set `level` before each frame

    def __init__(self, num_leds: int, rng: random.Random):
        self.n = num_leds
        self.rng = rng

    def draw(self, pixels: list[RGB], t: float, dt: float, lut: list[RGB]) -> None:
        raise NotImplementedError


class Still(Effect):
    """The palette spread over the strip, not moving (one color: solid)."""

    name = "Still"

    def draw(self, pixels, t, dt, lut):
        n = self.n
        pixels[:] = [lut[i * 256 // n] for i in range(n)]


class Flow(Effect):
    """The palette scrolls up the strip, twice along its length."""

    name = "Flow"

    def __init__(self, num_leds, rng):
        super().__init__(num_leds, rng)
        self.pos = [i * 512 // num_leds for i in range(num_leds)]

    def draw(self, pixels, t, dt, lut):
        shift = int(t * 40)
        pixels[:] = [lut[(p - shift) & 255] for p in self.pos]


class Breathe(Effect):
    """The whole strip slowly brightens and dims, drifting through the palette."""

    name = "Breathe"

    def draw(self, pixels, t, dt, lut):
        level = 0.08 + 0.92 * (0.5 - 0.5 * math.cos(t * 2 * math.pi / 5))
        pixels[:] = [scale(lut[int(t * 6) & 255], level)] * self.n


class Aurora(Effect):
    """Slow overlapping waves of light and color, like northern lights."""

    name = "Aurora"
    # Sines from a table: math.sin per LED is too slow for a Pi Zero.
    SIN = [math.sin(k * 2 * math.pi / 1024) for k in range(1024)]
    K = 1024 / (2 * math.pi)

    LEVELS = 42  # brightness steps; the waves add up to at most 2.4

    def __init__(self, num_leds, rng):
        super().__init__(num_leds, rng)
        # The waves are wide, so every other LED is worked out and copied to
        # its neighbor. Per point: its place in each wave and in the palette.
        k = self.K
        self.points = [(i / num_leds * k, i * 180 / num_leds) for i in range(0, num_leds, 2)]
        self.lut: list[RGB] | None = None
        self.table: list[RGB] = []  # palette index × LEVELS + brightness step → color

    def draw(self, pixels, t, dt, lut):
        if lut is not self.lut:
            self.lut = lut
            steps = [0.06 + 0.94 * min(1.0, step / 31) ** 2 for step in range(self.LEVELS)]
            self.table = [scale(c, f) for c in lut for f in steps]
        sin, k, table, levels = self.SIN, self.K, self.table, self.LEVELS
        a, b, c, d, e = t * 0.6 * k, t * 0.9 * k, t * 0.3 * k, t * 0.25 * k, t * 5
        waves = [
            sin[int(x * 9 + a) & 1023] + 0.6 * sin[int(x * 23 - b) & 1023] + 0.8 * sin[int(x * 4 - c) & 1023]
            for x, _ in self.points
        ]
        colors = [
            table[(int(p + e + 30 * sin[int(x * 5 + d) & 1023]) & 255) * levels + (int(w * 17.2) if w > 0 else 0)]
            for (x, p), w in zip(self.points, waves)
        ]
        pixels[:] = [colors[i >> 1] for i in range(self.n)]


class Fire(Effect):
    """Flames rise from the bottom of the strip. Low heat takes the start of
    the palette, the hottest tips its middle."""

    name = "Fire"
    STEP = 1 / 60  # the simulation runs at a fixed rate, whatever the speed

    def __init__(self, num_leds, rng):
        super().__init__(num_leds, rng)
        self.heat = [0.0] * num_leds
        self.acc = 0.0
        self.base = min(num_leds, max(3, num_leds // 30))  # where sparks start
        self.cooling = (3 + 800 / num_leds) / 255  # flames reach about half way up
        self.colors: list[RGB] = []  # heat (0–255) → color, for this palette
        self.lut: list[RGB] | None = None

    def _step(self):
        heat, rnd, cooling = self.heat, self.rng.random, self.cooling
        heat[:] = [h - rnd() * cooling if h > cooling else 0.0 for h in heat]
        heat[2:] = [(a + 2 * b) / 3 for a, b in zip(heat[1:-1], heat[:-2])]  # heat drifts up and spreads
        for _ in range(_count(0.7, self.rng)):
            y = self.rng.randrange(self.base)
            heat[y] = min(1.0, heat[y] + self.rng.uniform(0.6, 1.0))

    def draw(self, pixels, t, dt, lut):
        if lut is not self.lut:
            self.lut = lut
            self.colors = [scale(lut[h // 2], min(1.0, h / 255 * 1.6)) if h > 5 else OFF for h in range(256)]
        self.acc = min(self.acc + dt, 3 * self.STEP)  # fast speeds would cost too much
        while self.acc >= self.STEP:
            self.acc -= self.STEP
            self._step()
        colors = self.colors
        pixels[:] = [colors[int(h * 255)] if h > 0 else OFF for h in self.heat]


class Twinkle(Effect):
    """LEDs light up here and there in palette colors and fade away."""

    name = "Twinkle"

    def __init__(self, num_leds, rng):
        super().__init__(num_leds, rng)
        self.lit: dict[int, list] = {}  # LED → [level, rising, color]

    def draw(self, pixels, t, dt, lut):
        rng, lit = self.rng, self.lit
        for _ in range(_count(self.n * 0.4 * dt, rng)):
            i = rng.randrange(self.n)
            if i not in lit:
                lit[i] = [0.0, True, lut[rng.randrange(256)]]
        up, down = dt * 2.5, dt * 1.0
        pixels[:] = [OFF] * self.n
        for i, tw in list(lit.items()):
            if tw[1]:
                tw[0] += up
                if tw[0] >= 1:
                    tw[0], tw[1] = 1.0, False
            else:
                tw[0] -= down
                if tw[0] <= 0:
                    del lit[i]
                    continue
            pixels[i] = scale(tw[2], tw[0] * tw[0])


class Meteor(Effect):
    """Meteors fall from the top, leaving sparkling trails."""

    name = "Meteor"
    SPEED = 90  # LEDs per second

    def __init__(self, num_leds, rng):
        super().__init__(num_leds, rng)
        self.trail = [0.0] * num_leds
        self.tcolor = [OFF] * num_leds
        self.heads: list[list] = []  # [position, color]
        self.next = 0.0

    def draw(self, pixels, t, dt, lut):
        n, rng, trail, tcolor = self.n, self.rng, self.trail, self.tcolor
        self.next -= dt
        if self.next <= 0:
            self.heads.append([float(n), lut[rng.randrange(256)]])
            self.next = rng.uniform(0.5, 1.5) * max(1.0, n / 150)
        rnd = rng.random
        trail[:] = [x * (1 - dt * (1.5 + 4.5 * rnd())) if x > 0.03 else 0.0 for x in trail]  # uneven fade: sparkles
        for head in self.heads:
            old = head[0]
            head[0] -= self.SPEED * dt
            for p in range(max(0, int(head[0])), min(n, int(old) + 1)):
                trail[p], tcolor[p] = 1.0, head[1]
        self.heads = [h for h in self.heads if h[0] > -1]
        pixels[:] = [scale(c, x) if x else OFF for c, x in zip(tcolor, trail)]
        for pos, c in self.heads:
            if 0 <= pos < n:
                pixels[int(pos)] = _mix(c, WHITE, 0.6)


class Ripples(Effect):
    """Drops land at random spots and send rings out both ways."""

    name = "Ripples"
    LIFE = 2.0
    SPEED = 25  # LEDs per second

    def __init__(self, num_leds, rng):
        super().__init__(num_leds, rng)
        self.drops: list[list] = []  # [center, age, color]
        self.next = 0.0

    def draw(self, pixels, t, dt, lut):
        n, rng = self.n, self.rng
        self.next -= dt
        if self.next <= 0:
            self.drops.append([rng.uniform(0, n - 1), 0.0, lut[rng.randrange(256)]])
            self.next = rng.uniform(0.3, 1.0) * max(0.5, 150 / n)
        for d in self.drops:
            d[1] += dt
        self.drops = [d for d in self.drops if d[1] < self.LIFE]
        pixels[:] = [OFF] * n
        for center, age, color in self.drops:
            fade = (1 - age / self.LIFE) ** 2
            r = age * self.SPEED
            for ring in {center - r, center + r}:
                for p in range(int(ring) - 2, int(ring) + 4):
                    if 0 <= p < n:
                        w = 1 - abs(p - ring) / 2.5
                        if w > 0:
                            pixels[p] = add(pixels[p], scale(color, w * fade))


class Chase(Effect):
    """Bands of light march up the strip, each a palette color."""

    name = "Chase"
    BAND = 6

    def draw(self, pixels, t, dt, lut):
        band, half = self.BAND, self.BAND // 2
        shift = math.ceil(t * 12)  # LED i is k = floor(i - offset) = i - ceil(offset) along the bands
        pixels[:] = [lut[(k // band * 24) & 255] if k % band < half else OFF for k in range(-shift, self.n - shift)]


class Bounce(Effect):
    """Balls in palette colors drop and bounce on the bottom of the strip."""

    name = "Bouncing balls"
    BALLS = 4

    def __init__(self, num_leds, rng):
        super().__init__(num_leds, rng)
        self.g = max(20.0, num_leds * 0.9)  # a full-height bounce takes ~1.5 s
        self.balls = [[(num_leds - 1) * (1 - k * 0.15), 0.0] for k in range(self.BALLS)]  # [height, velocity]
        self.trail = [0.0] * num_leds
        self.tcolor = [OFF] * num_leds

    def draw(self, pixels, t, dt, lut):
        n, g, trail, tcolor = self.n, self.g, self.trail, self.tcolor
        top = n - 1
        decay = max(0.0, 1 - dt * 10)
        trail[:] = [x * decay if x > 0.03 else 0.0 for x in trail]
        for k, ball in enumerate(self.balls):
            ball[1] -= g * dt
            ball[0] += ball[1] * dt
            if ball[0] <= 0:
                ball[0] = 0.0
                ball[1] = -ball[1] * 0.85
                if ball[1] < math.sqrt(2 * g * top * 0.08):  # nearly stopped: throw it up again
                    ball[1] = math.sqrt(2 * g * top * self.rng.uniform(0.5, 0.95))
            ball[0] = min(ball[0], float(top))
            p = int(ball[0])
            trail[p], tcolor[p] = 1.0, lut[(k * 64 + 16) & 255]
        pixels[:] = [scale(c, x) if x else OFF for c, x in zip(tcolor, trail)]


class Level(Effect):
    """A sound level meter: a bar rises up the strip with the sound, colored
    along the palette, and a dot marks the recent peak, then falls (faster
    with more speed)."""

    name = "Sound level"
    sound = True
    HOLD = 0.6  # s the peak dot waits before falling
    FALL = 0.6  # strips per second

    def __init__(self, num_leds, rng):
        super().__init__(num_leds, rng)
        self.level = 0.0  # 0–1, set by the lights from the microphone
        self.peak = 0.0  # LEDs
        self.held = 0.0
        self._lut: list[RGB] | None = None
        self._colors: list[RGB] = []

    def draw(self, pixels, t, dt, lut):
        n = self.n
        if lut is not self._lut:
            # Most of the palette from bottom to top, without wrapping back to the start.
            self._lut, self._colors = lut, [lut[i * 224 // n] for i in range(n)]
        colors = self._colors
        height = self.level * n
        if height >= self.peak:
            self.peak, self.held = height, 0.0
        else:
            self.held += dt
            if self.held > self.HOLD:
                self.peak = max(height, self.peak - n * self.FALL * dt)
        full = min(n, int(height))
        out = colors[:full] + [OFF] * (n - full)
        if full < n:
            out[full] = scale(colors[full], height - full)
        top = min(n - 1, int(self.peak))
        if top > full:  # the peak, above the bar
            out[top] = colors[top]
        pixels[:] = out


EFFECTS: dict[str, type[Effect]] = {
    "flow": Flow,
    "aurora": Aurora,
    "fire": Fire,
    "twinkle": Twinkle,
    "meteor": Meteor,
    "ripples": Ripples,
    "bounce": Bounce,
    "chase": Chase,
    "breathe": Breathe,
    "still": Still,
    "level": Level,
}
