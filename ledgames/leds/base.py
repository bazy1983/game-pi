from ..colors import OFF, RGB

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
        self._last: tuple[list[RGB], float] | None = None

    def show(self, pixels: list[RGB], level: float = 1.0) -> None:
        """`level` dims this frame on top of the brightness (the library
        scales in C; much cheaper than scaling every pixel in Python)."""
        factor = self.brightness * level
        if self.max_milliamps:
            total = sum(r + g + b for r, g, b in pixels)
            drawn = total / 255 * MA_PER_CHANNEL * factor + MA_IDLE * self.num_leds
            if drawn > self.max_milliamps:
                factor *= self.max_milliamps / drawn
        # The LEDs keep their colors, so an unchanged frame needs no write
        # (most frames, in most games: a big saving on a Pi Zero).
        frame = (list(pixels), factor)
        if frame == self._last:
            return
        self._last = frame
        self.write(frame[0], factor)

    def resize(self, num_leds: int) -> None:
        """Change the number of LEDs. The current ones are turned off first,
        so none stay lit past a shorter strip's end."""
        self.write([OFF] * self.num_leds, 0.0)
        self.num_leds = num_leds
        self._last = None

    def write(self, pixels: list[RGB], factor: float) -> None:
        """Send a frame, every color scaled by `factor` (0–1)."""
        raise NotImplementedError
