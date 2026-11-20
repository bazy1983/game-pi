"""Patterns for the guided wiring check on the device page. Each stays on
until the phone moves on (or PATTERN_TIME passes):

  red, green  the whole canvas in that color: the phone asks which color
              shows, which gives the color order
  first       the first 5 LEDs of the chain, whatever the layout: the first
              white, the next ones green. Which corner is white, and which
              way the green goes, give where the grid starts and how its
              strips run (see first_leds)
  check       on a grid: a frame round the edge, an arrow pointing up and a
              red dot in the top left corner. If the grid shows that, the
              grid settings match the wiring
"""

from ..colors import OFF, RGB, WHITE, scale

PATTERNS = ("red", "green", "first", "check")
PATTERN_TIME = 120.0  # s
LEVEL = 0.4  # the color patterns light every LED: not at full power
RED: RGB = (255, 0, 0)
GREEN: RGB = (0, 255, 0)
FRAME: RGB = (90, 90, 90)


def draw_color(pixels: list[RGB], color: RGB) -> None:
    pixels[:] = [scale(color, LEVEL)] * len(pixels)


def first_leds(num_leds: int) -> list[RGB]:
    """The chain itself, not through the layout."""
    chain = [OFF] * num_leds
    chain[0] = WHITE
    for i in range(1, min(5, num_leds)):
        chain[i] = GREEN
    return chain


def draw_check(pixels: list[RGB], w: int, h: int) -> None:
    pixels[:] = [OFF] * (w * h)

    def put(x: int, y: int, color: RGB) -> None:
        if 0 <= x < w and 0 <= y < h:
            pixels[y * w + x] = color

    for x in range(w):
        put(x, 0, FRAME)
        put(x, h - 1, FRAME)
    for y in range(h):
        put(0, y, FRAME)
        put(w - 1, y, FRAME)
    cx = w // 2
    tip = 2 if h >= 8 else 1
    for y in range(tip, h - 2):
        put(cx, y, GREEN)
    for d in range(1, min(4, (w - 1) // 2)):
        put(cx - d, tip + d, GREEN)
        put(cx + d, tip + d, GREEN)
    put(0, 0, RED)
