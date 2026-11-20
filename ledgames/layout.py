"""What kind of lights are connected: an LED strip, or an LED grid.

Either way the Pi drives one chain of LEDs on one pin. Games and effects
draw on a canvas, and the layout turns it into the chain's order:

  strip  the canvas is the strip, index 0 = the bottom LED
  grid   the canvas is width × height, row by row from the top left:
         index = y * width + x, (0, 0) = top left

A grid is built from strips laid in columns or rows, one after the other.
Each strip ("line") is joined to the next at its end: the same way in a
zigzag (down, up, down, …), or back at the far side when every strip runs
the same way. LEDs between one line and the next (a string bent round at
the turn, say) stay dark.
"""

from dataclasses import asdict, dataclass

from .colors import OFF, RGB

STARTS = ("top-left", "top-right", "bottom-left", "bottom-right")
RUNS = ("columns", "rows")
MIN_SIDE, MAX_SIDE = 2, 64
MAX_SKIP = 10


@dataclass(frozen=True)
class Grid:
    width: int = 16
    height: int = 16
    runs: str = "columns"  # the strips run up and down (columns) or across (rows)
    zigzag: bool = True  # every other strip runs back the other way
    start: str = "top-left"  # where the first LED is, looking at the grid
    skip: int = 0  # dark LEDs between one strip and the next

    @property
    def lines(self) -> int:
        return self.width if self.runs == "columns" else self.height

    @property
    def num_leds(self) -> int:
        """LEDs on the whole chain, the dark ones at the turns too."""
        return self.width * self.height + self.skip * (self.lines - 1)

    def order(self) -> list[int]:
        """For each LED on the chain, its pixel on the canvas (width × height
        for the dark ones)."""
        w, h = self.width, self.height
        columns = self.runs == "columns"
        along = h if columns else w
        top, left = self.start.startswith("top"), self.start.endswith("left")
        order = []
        for line in range(self.lines):
            if line:
                order += [w * h] * self.skip
            back = self.zigzag and line % 2
            for k in range(along):
                pos = along - 1 - k if back else k
                x, y = (line, pos) if columns else (pos, line)
                if not left:
                    x = w - 1 - x
                if not top:
                    y = h - 1 - y
                order.append(y * w + x)
        return order

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def parse(cls, value, max_leds: int) -> "tuple[Grid | None, str | None]":
        """A grid from the phone or the settings file, or an error message."""
        if not isinstance(value, dict):
            return None, "Invalid grid."
        g = {**asdict(cls()), **value}

        def whole(v, lo, hi):
            return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi

        if not (whole(g["width"], MIN_SIDE, MAX_SIDE) and whole(g["height"], MIN_SIDE, MAX_SIDE)):
            return None, f"Width and height go from {MIN_SIDE} to {MAX_SIDE} LEDs."
        if g["runs"] not in RUNS or g["start"] not in STARTS or not isinstance(g["zigzag"], bool):
            return None, "Invalid grid."
        if not whole(g["skip"], 0, MAX_SKIP):
            return None, f"Dark LEDs between strips go from 0 to {MAX_SKIP}."
        grid = cls(**{k: g[k] for k in asdict(cls())})
        if grid.num_leds > max_leds:
            return None, f"That's {grid.num_leds} LEDs; the most is {max_leds}."
        return grid, None


class Layout:
    """The connected lights. `size` is the canvas games draw on; `num_leds`
    the LEDs on the chain."""

    def __init__(self, kind: str, size: int, grid: Grid | None = None):
        self.kind = kind
        self.size = size
        self.grid = grid
        self.num_leds = grid.num_leds if grid else size
        self._order = grid.order() if grid else None

    @classmethod
    def strip(cls, num_leds: int) -> "Layout":
        return cls("strip", num_leds)

    @classmethod
    def of_grid(cls, grid: Grid) -> "Layout":
        return cls("grid", grid.width * grid.height, grid)

    @property
    def width(self) -> int:
        return self.grid.width if self.grid else 1

    @property
    def height(self) -> int:
        return self.grid.height if self.grid else self.size

    def positions(self) -> list[int]:
        """For each LED on the chain, its canvas pixel, or -1 if it's dark
        (for the simulator)."""
        if self._order is None:
            return list(range(self.size))
        return [-1 if i == self.size else i for i in self._order]

    def to_chain(self, pixels: list[RGB]) -> list[RGB]:
        """The canvas in the order the LEDs are wired."""
        if self._order is None:
            return pixels
        src = pixels + [OFF]  # the dark LEDs' pixel
        return [src[i] for i in self._order]

    def describe(self) -> dict:
        if self.grid:
            return {"kind": "grid", "width": self.width, "height": self.height}
        return {"kind": "strip", "leds": self.size}


def from_settings(settings: dict, strip_leds: int, max_leds: int) -> Layout:
    """The lights saved on the device page: a grid if one was picked, else
    the strip with `strip_leds`."""
    if settings.get("layout") == "grid":
        grid, _ = Grid.parse(settings.get("grid"), max_leds)
        if grid:
            return Layout.of_grid(grid)
    return Layout.strip(strip_leds)
