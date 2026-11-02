import math

from ..colors import RED, RGB, scale


class RedFill:
    """Paints red over the current frame from the top LED down to the bottom,
    then pulses for a moment before reporting `done`."""

    def __init__(self, num_leds: int, fill_time: float = 3.0, hold_time: float = 3.0):
        self.n = num_leds
        self.fill_time = fill_time
        self.hold_time = hold_time
        self.t = 0.0

    @property
    def done(self) -> bool:
        return self.t >= self.fill_time + self.hold_time

    def update(self, dt: float) -> None:
        self.t += dt

    def render(self, pixels: list[RGB]) -> None:
        filled = min(self.n, int(self.n * self.t / self.fill_time))
        if self.t < self.fill_time:
            color = RED
        else:
            pulse = 0.55 + 0.45 * math.cos((self.t - self.fill_time) * math.tau)
            color = scale(RED, pulse)
        for i in range(self.n - filled, self.n):
            pixels[i] = color
