"""Shared color definitions.

`led` is the RGB value sent to the strip (tuned for WS2812B, where e.g. yellow
needs less green than on a screen). `ui` is the CSS color shown on the phone.
"""

from dataclasses import dataclass

RGB = tuple[int, int, int]

OFF: RGB = (0, 0, 0)
WHITE: RGB = (255, 255, 255)
RED: RGB = (255, 0, 0)


@dataclass(frozen=True)
class GameColor:
    name: str
    led: RGB
    ui: str


# Ordered by how distinguishable they are on a WS2812B strip: a game using N
# colors takes the first N. White is reserved for the shooter.
PALETTE: list[GameColor] = [
    GameColor("red", (255, 0, 0), "#ff2a2a"),
    GameColor("green", (0, 255, 0), "#22dd44"),
    GameColor("blue", (0, 0, 255), "#2a5cff"),
    GameColor("yellow", (255, 160, 0), "#ffd21f"),
    GameColor("magenta", (220, 0, 255), "#c43cff"),
]


def scale(color: RGB, factor: float) -> RGB:
    return (int(color[0] * factor), int(color[1] * factor), int(color[2] * factor))


def add(a: RGB, b: RGB) -> RGB:
    return (min(255, a[0] + b[0]), min(255, a[1] + b[1]), min(255, a[2] + b[2]))
