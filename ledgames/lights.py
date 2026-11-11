"""Lights: an ambient effect that plays on the strip whenever no game is
running. Picked on the phone's Lights page and saved on the unit.

Settings:
  on       bool
  effect   an id from effects/ambient.py
  palette  an id from PALETTES; "custom" is a gradient of your own
  gradient the custom gradient: 1–12 stops {"at": 0–1, "color": "#rrggbb"},
           in any order (the phone keeps its order while you drag stops)
  presets  saved gradients: up to 24 {"name", "stops": a gradient}
  speed    0–1 (0.5 = normal; each end is 4× slower / faster)
  level    brightness, 0.05–1 (on top of the strip's own brightness)

Sound effects (like Sound level) read `mic.level`; see audio.py.
"""

import random
import re
from dataclasses import dataclass

from .colors import RGB
from .effects.ambient import EFFECTS, Effect

FADE_IN = 1.0  # s, when the lights come back after a game


@dataclass(frozen=True)
class Palette:
    name: str
    stops: tuple[RGB, ...]  # spread evenly, the last blends back into the first


# LED colors (WS2812B yellow needs less green than a screen). For Fire, the
# first half of a palette is cool to hot.
PALETTES: dict[str, Palette] = {
    "rainbow": Palette("Rainbow", ((255, 0, 0), (255, 160, 0), (0, 255, 0), (0, 255, 255), (0, 0, 255), (220, 0, 255))),
    "fire": Palette("Fire", ((255, 0, 0), (255, 50, 0), (255, 140, 0), (255, 200, 40), (255, 90, 0), (255, 20, 0))),
    "ocean": Palette("Ocean", ((0, 0, 140), (0, 50, 255), (0, 180, 255), (0, 255, 200), (0, 120, 255), (0, 20, 200))),
    "forest": Palette("Forest", ((0, 90, 0), (30, 180, 0), (140, 255, 0), (255, 200, 0), (60, 220, 20), (0, 140, 40))),
    "sunset": Palette("Sunset", ((140, 0, 90), (255, 0, 50), (255, 70, 0), (255, 160, 0), (255, 40, 30), (180, 0, 140))),
    "party": Palette("Party", ((255, 0, 140), (255, 120, 0), (255, 220, 0), (0, 255, 120), (0, 120, 255), (160, 0, 255))),
    "ice": Palette("Ice", ((0, 30, 255), (60, 140, 255), (160, 220, 255), (255, 255, 255), (100, 180, 255), (20, 80, 255))),
    "custom": Palette("Your gradient", ()),
}

MAX_STOPS = 12
MAX_PRESETS = 24
MAX_NAME = 24

DEFAULTS = {
    "on": False,
    "effect": "flow",
    "palette": "rainbow",
    "gradient": [{"at": 0.0, "color": "#ff6000"}, {"at": 1.0, "color": "#8000ff"}],
    "speed": 0.5,
    "level": 0.7,
    "presets": [],
}


def make_lut(stops: tuple[RGB, ...]) -> list[RGB]:
    """The palette as 256 colors, blending around from the last stop back to the first."""
    if len(stops) == 1:
        return [stops[0]] * 256
    lut = []
    for k in range(256):
        pos = k * len(stops) / 256
        a, b = stops[int(pos)], stops[(int(pos) + 1) % len(stops)]
        f = pos - int(pos)
        lut.append(tuple(int(a[c] + (b[c] - a[c]) * f) for c in range(3)))
    return lut


def gradient_lut(gradient: list[dict]) -> list[RGB]:
    """A custom gradient as 256 colors, from 0 to 1 without wrapping around:
    the first stop's color before it, the last one's after it."""
    # Stops at the same place keep their order: a hard edge between them.
    stops = sorted(((s["at"], _hex_rgb(s["color"])) for s in gradient), key=lambda s: s[0])
    lut = []
    j = 0
    for k in range(256):
        x = k / 255
        while j < len(stops) - 1 and stops[j + 1][0] < x:
            j += 1
        (a_at, a), (b_at, b) = stops[j], stops[min(j + 1, len(stops) - 1)]
        f = 0.0 if b_at <= a_at else min(1.0, max(0.0, (x - a_at) / (b_at - a_at)))
        lut.append(tuple(int(a[c] + (b[c] - a[c]) * f + 0.5) for c in range(3)))
    return lut


def palette_gradient(palette: Palette) -> list[dict]:
    """A built-in palette as a gradient (for the phone's gradient editor and
    its swatch), its first color repeated at the end as it wraps around."""
    stops = palette.stops + palette.stops[:1]
    return [{"at": round(k / (len(stops) - 1), 4), "color": _rgb_hex(c)} for k, c in enumerate(stops)]


def _hex_rgb(color: str) -> RGB:
    return (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16))


def _rgb_hex(color: RGB) -> str:
    return "#%02x%02x%02x" % color


def _valid_gradient(value) -> bool:
    return (
        isinstance(value, list)
        and 1 <= len(value) <= MAX_STOPS
        and all(
            isinstance(s, dict)
            and _number(s.get("at"))
            and 0 <= s["at"] <= 1
            and isinstance(s.get("color"), str)
            and re.fullmatch(r"#[0-9a-fA-F]{6}", s["color"])
            for s in value
        )
    )


def _clean_gradient(value: list[dict]) -> list[dict]:
    return [{"at": float(s["at"]), "color": s["color"].lower()} for s in value]


def _valid_presets(value) -> bool:
    return (
        isinstance(value, list)
        and len(value) <= MAX_PRESETS
        and all(
            isinstance(p, dict)
            and isinstance(p.get("name"), str)
            and 1 <= len(p["name"].strip()) <= MAX_NAME
            and _valid_gradient(p.get("stops"))
            for p in value
        )
    )


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class Lights:
    def __init__(self, rng: random.Random | None = None):
        self.rng = rng or random.Random()
        self.on = DEFAULTS["on"]
        self.effect = DEFAULTS["effect"]
        self.palette = DEFAULTS["palette"]
        self.gradient = DEFAULTS["gradient"]
        self.speed = DEFAULTS["speed"]
        self.level = DEFAULTS["level"]
        self.presets = DEFAULTS["presets"]
        self._fx: Effect | None = None
        self._lut: list[RGB] | None = None
        self._t = 0.0
        self._fade = 0.0
        self.mic = None  # an audio.Microphone, if the unit has one

    @property
    def listening(self) -> bool:
        """A sound effect is on, so the microphone should listen."""
        return self.on and EFFECTS[self.effect].sound

    def settings(self) -> dict:
        return {k: getattr(self, k) for k in DEFAULTS}

    def update(self, changes: dict) -> str | None:
        """Apply some settings. Returns an error message (and changes
        nothing) if any of them is invalid."""
        checks = {
            "on": lambda v: isinstance(v, bool),
            "effect": lambda v: v in EFFECTS,
            "palette": lambda v: v in PALETTES,
            "gradient": _valid_gradient,
            "speed": lambda v: _number(v) and 0 <= v <= 1,
            "level": lambda v: _number(v) and 0.05 <= v <= 1,
            "presets": _valid_presets,
        }
        changes = {k: v for k, v in changes.items() if k in checks}
        for key, value in changes.items():
            if not checks[key](value):
                return f"Invalid {key}."
        if changes.get("on") and not self.on:
            self._fade = 0.0
        if "effect" in changes and changes["effect"] != self.effect:
            self._fx = None
        if "palette" in changes or "gradient" in changes:
            self._lut = None
        if "gradient" in changes:
            changes["gradient"] = _clean_gradient(changes["gradient"])
        if "presets" in changes:
            changes["presets"] = [{"name": p["name"].strip(), "stops": _clean_gradient(p["stops"])} for p in changes["presets"]]
        for key, value in changes.items():
            setattr(self, key, value)
        return None

    def load(self, saved: dict) -> None:
        """Saved settings, skipping any that are no longer valid."""
        if isinstance(saved, dict) and "color" in saved and "gradient" not in saved:
            # Before gradients, "Your color" was one color.
            saved = {**saved, "gradient": [{"at": 0.0, "color": saved["color"]}]}
        for key, value in saved.items() if isinstance(saved, dict) else ():
            self.update({key: value})

    def pause(self) -> None:
        """Something else is on the strip; fade back in when it's done."""
        self._fade = 0.0

    def render(self, pixels: list[RGB], dt: float) -> float:
        """Draw a frame. Returns how bright to show it (0–1)."""
        n = len(pixels)
        if self._fx is None or self._fx.n != n:
            self._fx = EFFECTS[self.effect](n, self.rng)
        if self._lut is None:
            stops = PALETTES[self.palette].stops
            self._lut = make_lut(stops) if stops else gradient_lut(self.gradient)
        rate = 4 ** (2 * self.speed - 1)
        self._t += dt * rate
        if self._fx.sound:
            self._fx.level = self.mic.level if self.mic else 0.0
        self._fx.draw(pixels, self._t, dt * rate, self._lut)
        self._fade = min(1.0, self._fade + dt / FADE_IN)
        return self.level * self._fade
