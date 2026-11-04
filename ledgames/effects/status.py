import math

from ..colors import OFF, RGB, scale

BLUE: RGB = (0, 60, 255)
PURPLE: RGB = (160, 0, 255)


def draw_status(pixels: list[RGB], status: str, t: float) -> None:
    """What the strip shows while the unit is busy with itself:
    setup       the bottom slowly breathes blue (join the setup hotspot)
    connecting  blue dots climb the strip
    updating    purple dots climb the strip"""
    n = len(pixels)
    for i in range(n):
        pixels[i] = OFF
    if status == "setup":
        level = 0.1 + 0.5 * (0.5 - 0.5 * math.cos(t * 2 * math.pi / 3))
        for i in range(min(n, 12)):
            pixels[i] = scale(BLUE, level)
    elif status in ("connecting", "updating"):
        color = BLUE if status == "connecting" else PURPLE
        gap = 24
        head = t * 40
        for i in range(n):
            behind = (head - i) % gap  # how far this LED is behind a dot
            if behind < 6:
                pixels[i] = scale(color, 1 - behind / 6)


def draw_flash(pixels: list[RGB], color: RGB, left: float, duration: float) -> None:
    """The whole strip lights up and fades out (e.g. green: Wi-Fi joined)."""
    level = 0.6 * max(0.0, left / duration)
    for i in range(len(pixels)):
        pixels[i] = scale(color, level)
