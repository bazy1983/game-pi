from ..colors import RGB
from .base import Strip


class Ws281xStrip(Strip):
    """Real WS2812B strip on the Raspberry Pi via rpi_ws281x (requires root).

    Default pin is GPIO18 (PWM0). Note: PWM conflicts with the Pi's analog
    audio, which is fine on a Zero W (it has none)."""

    def __init__(self, num_leds: int, brightness: float, max_milliamps: int, pin: int = 18):
        super().__init__(num_leds, brightness, max_milliamps)
        from rpi_ws281x import PixelStrip  # only importable on the Pi

        self.strip = PixelStrip(num_leds, pin, freq_hz=800_000, dma=10, invert=False, brightness=255)
        self.strip.begin()

    def write(self, pixels: list[RGB]) -> None:
        for i, (r, g, b) in enumerate(pixels):
            self.strip.setPixelColorRGB(i, r, g, b)
        self.strip.show()
