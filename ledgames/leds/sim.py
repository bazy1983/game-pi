from ..colors import RGB
from .base import Strip


class SimStrip(Strip):
    """Keeps the last frame in memory so the web server can stream it to the
    /sim page. Shows full-brightness colors so they read well on a screen.

    The simulated LEDs take their colors in `wired` order (GRB, like most
    strips), so a wrong color order setting swaps colors here too."""

    def __init__(self, num_leds: int, order: str = "grb", wired: str = "grb", **_):
        super().__init__(num_leds, brightness=1.0, order=order)
        self.wired = wired
        self.frame = bytes(num_leds * 3)
        self._swap()

    def _swap(self) -> None:
        # Channel c on the LED gets what was sent at its place in `wired`,
        # which is the color at that place in `order`.
        self._src = ["rgb".index(self.order[self.wired.index(c)]) for c in "rgb"]

    def set_order(self, order: str) -> None:
        super().set_order(order)
        self._swap()

    def resize(self, num_leds: int) -> None:
        super().resize(num_leds)
        self.frame = bytes(num_leds * 3)

    def write(self, pixels: list[RGB], factor: float) -> None:
        r, g, b = self._src
        self.frame = bytes(int(c * factor) for px in pixels for c in (px[r], px[g], px[b]))
