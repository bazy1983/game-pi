from ..colors import RGB
from .base import Strip


class Ws281xStrip(Strip):
    """Real WS2812B strip on the Raspberry Pi via rpi_ws281x (requires root).

    Default pin is GPIO12 (PWM0), which leaves GPIO18–20 free for the I2S
    microphone; GPIO13 (PWM1) also works. Note: PWM conflicts with the Pi's analog audio, which is fine
    on a Zero W (it has none)."""

    def __init__(self, num_leds: int, brightness: float, max_milliamps: int, pin: int = 12):
        super().__init__(num_leds, brightness, max_milliamps)
        self.pin = pin
        self._open()

    def _open(self) -> None:
        from rpi_ws281x import PixelStrip, ws  # only importable on the Pi

        channel = 1 if self.pin in (13, 19, 41, 45, 53) else 0  # the PWM1 pins
        self.strip = PixelStrip(
            self.num_leds, self.pin, freq_hz=800_000, dma=10, invert=False, brightness=255, channel=channel
        )
        self.strip.begin()
        self._set = ws.ws2811_led_set
        self._channel = self.strip._channel

    def resize(self, num_leds: int) -> None:
        super().resize(num_leds)
        self.strip._cleanup()  # frees the DMA channel for the new strip
        self._open()

    def write(self, pixels: list[RGB], factor: float) -> None:
        # On a Pi Zero, setPixelColorRGB takes ~12 ms for 195 LEDs; the
        # low-level setter takes ~1 ms, and the library scales brightness in C.
        self.strip.setBrightness(round(255 * factor))
        set_led, channel = self._set, self._channel
        for i, (r, g, b) in enumerate(pixels):
            set_led(channel, i, (r << 16) | (g << 8) | b)
        self.strip.show()
