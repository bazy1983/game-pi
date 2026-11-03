import random

from ..colors import OFF, RGB, WHITE, add, scale


class Confetti:
    """Twinkling sparkles of one color scattered over the whole strip, with
    the odd white glint. Starts with a full-strip flash, fades out at the end."""

    def __init__(self, num_leds: int, color: RGB, duration: float, rng: random.Random | None = None):
        self.n = num_leds
        self.color = color
        self.duration = duration
        self.rng = rng or random.Random()
        self.t = 0.0
        self.levels = [0.0] * num_leds  # brightness of each sparkle, decaying
        self.white = [False] * num_leds

    @property
    def done(self) -> bool:
        return self.t >= self.duration

    def update(self, dt: float) -> None:
        self.t += dt
        decay = max(0.0, 1 - 4.0 * dt)
        for i in range(self.n):
            self.levels[i] *= decay
        # Fewer new sparkles toward the end so it winds down.
        remaining = max(0.0, 1 - self.t / self.duration)
        for _ in range(int(self.n * 0.9 * dt * 10 * remaining) + 1):
            i = self.rng.randrange(self.n)
            self.levels[i] = self.rng.uniform(0.6, 1.0)
            self.white[i] = self.rng.random() < 0.08

    def render(self, pixels: list[RGB]) -> None:
        flash = max(0.0, 1 - self.t / 0.25) * 0.7  # opening flash
        base = scale(self.color, flash)
        for i in range(self.n):
            spark = scale(WHITE if self.white[i] else self.color, self.levels[i])
            pixels[i] = add(base, spark) if flash else spark
        if self.done:
            for i in range(self.n):
                pixels[i] = OFF
