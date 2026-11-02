from ..colors import RGB
from .base import Strip


class SimStrip(Strip):
    """Keeps the last frame in memory so the web server can stream it to the
    /sim page. Shows full-brightness colors so they read well on a screen."""

    def __init__(self, num_leds: int, **_):
        super().__init__(num_leds, brightness=1.0)
        self.frame = bytes(num_leds * 3)

    def write(self, pixels: list[RGB]) -> None:
        self.frame = bytes(c for px in pixels for c in px)
