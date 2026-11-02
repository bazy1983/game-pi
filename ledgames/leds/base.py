from ..colors import RGB

MA_PER_CHANNEL = 20.0  # WS2812B draws ~20 mA per fully-lit channel
MA_IDLE = 1.0  # ~1 mA per LED even when off


class Strip:
    """Pushes frames to LEDs. Applies a global brightness and an estimated
    current limit so the strip never asks more of the power supply than it
    can deliver (e.g. during fireworks or the red fill)."""

    def __init__(self, num_leds: int, brightness: float = 0.5, max_milliamps: int = 0):
        self.num_leds = num_leds
        self.brightness = brightness
        self.max_milliamps = max_milliamps  # 0 = no limit

    def show(self, pixels: list[RGB]) -> None:
        factor = self.brightness
        if self.max_milliamps:
            total = sum(r + g + b for r, g, b in pixels)
            drawn = total / 255 * MA_PER_CHANNEL * factor + MA_IDLE * self.num_leds
            if drawn > self.max_milliamps:
                factor *= self.max_milliamps / drawn
        self.write([(int(r * factor), int(g * factor), int(b * factor)) for r, g, b in pixels])

    def write(self, pixels: list[RGB]) -> None:
        raise NotImplementedError
