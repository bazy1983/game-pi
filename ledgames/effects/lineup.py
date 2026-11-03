import math

from ..colors import OFF, RGB, scale


def draw_lineup(pixels: list[RGB], colors: list[RGB], t: float) -> None:
    """Show each player's color as its own block, spread evenly up the strip
    and gently breathing, so everyone can see who's playing."""
    n = len(pixels)
    for i in range(n):
        pixels[i] = OFF
    if not colors:
        return
    slot = n / len(colors)
    size = max(1, min(int(slot * 0.6), 20))
    level = 0.6 + 0.4 * math.sin(t * 2.5)
    for k, color in enumerate(colors):
        start = int(slot * k + (slot - size) / 2)
        for i in range(start, min(n, start + size)):
            pixels[i] = scale(color, level)
