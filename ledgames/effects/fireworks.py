import random
from dataclasses import dataclass

from ..colors import OFF, PALETTE, RGB, WHITE, add, scale


@dataclass
class _Rocket:
    pos: float
    target: float
    speed: float
    color: RGB


@dataclass
class _Spark:
    pos: float
    vel: float
    color: RGB
    age: float
    life: float


class Fireworks:
    """Rockets launch from the bottom, burst into sparks that spread up and
    down, slow down, fall and fade. Runs for `duration` seconds, then lets the
    remaining sparks die out before reporting `done`."""

    GRAVITY = 25.0  # LEDs/s², scaled by strip length
    DRAG = 1.8

    def __init__(self, num_leds: int, duration: float = 8.0, rng: random.Random | None = None):
        self.n = num_leds
        self.duration = duration
        self.rng = rng or random.Random()
        self.size = num_leds / 150  # tuned on 150 LEDs, scale for other lengths
        self.t = 0.0
        self.next_launch = 0.0
        self.rockets: list[_Rocket] = []
        self.sparks: list[_Spark] = []

    @property
    def done(self) -> bool:
        return self.t >= self.duration and not self.rockets and not self.sparks

    def update(self, dt: float) -> None:
        self.t += dt
        if self.t < self.duration and self.t >= self.next_launch:
            self._launch()
            self.next_launch = self.t + self.rng.uniform(0.25, 0.7)

        for r in self.rockets[:]:
            r.pos += r.speed * dt
            if r.pos >= r.target:
                self.rockets.remove(r)
                self._burst(r)

        for s in self.sparks[:]:
            s.age += dt
            if s.age >= s.life:
                self.sparks.remove(s)
                continue
            s.vel -= s.vel * self.DRAG * dt
            s.vel -= self.GRAVITY * self.size * dt
            s.pos += s.vel * dt

    def _launch(self) -> None:
        target = self.rng.uniform(0.45, 0.92) * self.n
        speed = target / self.rng.uniform(0.7, 1.1)
        color = self.rng.choice(PALETTE).led
        self.rockets.append(_Rocket(0.0, target, speed, color))

    def _burst(self, rocket: _Rocket) -> None:
        colors = [rocket.color, self.rng.choice(PALETTE).led]
        for _ in range(self.rng.randint(10, 16)):
            vel = self.rng.uniform(-1, 1) * 45 * self.size
            life = self.rng.uniform(0.8, 1.6)
            self.sparks.append(_Spark(rocket.pos, vel, self.rng.choice(colors), 0.0, life))

    def render(self, pixels: list[RGB]) -> None:
        for i in range(self.n):
            pixels[i] = OFF
        for r in self.rockets:
            head = int(r.pos)
            for k in range(4):  # head plus a fading tail
                i = head - k
                if 0 <= i < self.n:
                    pixels[i] = add(pixels[i], scale(WHITE if k == 0 else r.color, 0.6 / (k + 1)))
        for s in self.sparks:
            i = int(s.pos)
            if 0 <= i < self.n:
                fade = 1 - s.age / s.life
                # Sparks flash white right after the burst, then show their color.
                color = WHITE if s.age < 0.06 else s.color
                pixels[i] = add(pixels[i], scale(color, fade * fade))
