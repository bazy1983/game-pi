"""Hot and Cold: find the hidden treasure on the strip, 1–6 phones.

One spot on the strip hides the treasure. Players take turns: slide to
aim (a white cursor moves on the strip), then dig. The strip glows in the
dig's heat, from icy (far away) through blue, cyan, yellow and orange to red
(very close), and a marker in that color stays where they dug, so everyone
can narrow it down. Whoever digs within ZONE of the treasure wins.

Playing alone, the difficulty gives a number of digs; run out and the
treasure is revealed. With more players there's no limit, but each turn
has a time limit; let it run out and the turn passes.

Phones send {"aim": led} while sliding and {"dig": led} to dig (LED 0 is
the bottom), only on their turn.
"""

import math
import random
from dataclasses import dataclass
from typing import Any

from ..colors import OFF, RGB, WHITE, GameColor, scale
from ..effects.confetti import Confetti
from ..effects.fireworks import Fireworks
from ..effects.red_fill import RedFill
from .base import Choice, Game, GameInfo

# Not used on the strip during play (that's the heat colors and the white cursor).
PLAYER_COLORS = [
    GameColor("green", (0, 255, 0), "#22dd44"),
    GameColor("magenta", (220, 0, 255), "#c43cff"),
    GameColor("pink", (255, 40, 120), "#ff5fa8"),
    GameColor("teal", (0, 200, 140), "#1fc9a0"),
    GameColor("purple", (110, 0, 255), "#8a4dff"),
    GameColor("white", (255, 255, 255), "#f2f4f8"),
]


@dataclass(frozen=True)
class Heat:
    id: str
    within: float  # distance as a share of the strip: this heat if closer than this
    led: RGB


# Coldest first. A dig gets the first one (from the hot end) it's within.
HEATS = [
    Heat("freezing", math.inf, (110, 150, 255)),
    Heat("cold", 0.40, (0, 30, 255)),
    Heat("cool", 0.25, (0, 200, 255)),
    Heat("warm", 0.15, (255, 170, 0)),
    Heat("hot", 0.08, (255, 60, 0)),
    Heat("burning", 0.04, (255, 0, 0)),
]
GOLD: RGB = (255, 180, 20)
FOUND = Heat("found", 0.0, GOLD)

INTRO_TIME = 2.0
GLOW_TIME = 1.8  # the strip glows in the heat after a dig
REVEAL_TIME = 2.5  # the treasure blinks before the ending
MARKER = 0.35  # how bright the dig markers are
GLOW = 0.3  # how bright the whole strip glows after a dig
FINAL_TIME = 6.0


@dataclass(frozen=True)
class Difficulty:
    zone: float  # how close a dig must be to find it, as a share of the strip
    digs: int  # playing alone
    turn_time: float  # seconds per turn, with more players


DIFFICULTIES = {
    "easy": Difficulty(0.03, 10, 30.0),
    "medium": Difficulty(0.015, 8, 25.0),
    "hard": Difficulty(0.006, 6, 20.0),
}


def heat_of(distance: int, num_leds: int) -> Heat:
    share = distance / num_leds
    for heat in reversed(HEATS):
        if share < heat.within:
            return heat
    return HEATS[0]


class HotCold(Game):
    info = GameInfo(
        id="hot_cold",
        name="Hot and Cold",
        description="A treasure is hidden on the strip. Dig, and the strip tells you how hot you are. Take turns; whoever finds it wins!",
        difficulties=[
            Choice("easy", "Easy", "A big treasure · alone: 10 digs"),
            Choice("medium", "Medium", "A smaller treasure · alone: 8 digs"),
            Choice("hard", "Hard", "A tiny treasure · alone: 6 digs"),
        ],
        default_difficulty="easy",
        max_players=len(PLAYER_COLORS),
        player_colors=PLAYER_COLORS,
    )

    def __init__(
        self,
        num_leds: int,
        difficulty: str,
        settings: dict[str, str],
        players: list[str] | None = None,
        rng: random.Random | None = None,
        **kwargs,
    ):
        super().__init__(num_leds, difficulty, settings, players, **kwargs)
        self.cfg = DIFFICULTIES[difficulty]
        self.rng = rng or random.Random()
        self.colors = PLAYER_COLORS[: len(self.players)]
        n = num_leds
        self.zone = max(0, round(n * self.cfg.zone))  # LEDs either side of the treasure
        margin = min(self.zone, (n - 1) // 2)
        self.treasure = self.rng.randint(margin, n - 1 - margin)  # the whole treasure fits on the strip

        self.status = "playing"
        self.stage = "intro"  # intro → turn ⇄ glow → reveal
        self.timer = INTRO_TIME  # time left in this stage
        self.turn = 0  # whose turn
        self.aim = n // 2
        self.digs: list[tuple[int, Heat, int]] = []  # (led, heat, player)
        self.left: set[int] = set()
        self.winner: int | None = None
        self.t = 0.0
        self.effect: Confetti | Fireworks | RedFill | None = None

    @property
    def solo(self) -> bool:
        return len(self.players) == 1

    @property
    def digs_left(self) -> int | None:
        return self.cfg.digs - len(self.digs) if self.solo else None

    # --- flow -------------------------------------------------------------------

    def update(self, dt: float) -> None:
        self.t += dt
        if self.effect:
            self.effect.update(dt)
            self.finished = self.effect.done
            return
        if self.stage == "turn" and self.solo:
            return  # no time limit alone
        self.timer -= dt
        if self.timer > 0:
            return
        if self.stage == "intro":
            self._start_turn(self.turn)
        elif self.stage == "glow":
            if self.solo and self.digs_left == 0:
                self._reveal("lost")
            else:
                self._start_turn(self._next(self.turn))
        elif self.stage == "turn":  # out of time: the turn passes
            self._start_turn(self._next(self.turn))
        elif self.stage == "reveal":
            self._finish()

    def _next(self, idx: int) -> int:
        """The next player still here after `idx`."""
        for k in range(1, len(self.players) + 1):
            j = (idx + k) % len(self.players)
            if j not in self.left:
                return j
        return idx

    def _start_turn(self, idx: int) -> None:
        self.stage, self.turn = "turn", idx
        self.timer = self.cfg.turn_time

    def on_input(self, player: str, action: dict[str, Any]) -> None:
        if self.status != "playing" or self.stage != "turn" or player not in self.players:
            return
        if self.players.index(player) != self.turn:
            return
        for key in ("aim", "dig"):
            led = action.get(key)
            if isinstance(led, int) and not isinstance(led, bool) and 0 <= led < self.num_leds:
                self.aim = led
                if key == "dig":
                    self._dig(led)
                return

    def _dig(self, led: int) -> None:
        distance = abs(led - self.treasure)
        if distance <= self.zone:
            self.digs.append((led, FOUND, self.turn))
            self.winner = self.turn
            self._reveal("won")
            return
        self.digs.append((led, heat_of(distance, self.num_leds), self.turn))
        self.stage, self.timer = "glow", GLOW_TIME

    def _reveal(self, status: str) -> None:
        self.status = status
        self.stage, self.timer = "reveal", REVEAL_TIME

    def _finish(self) -> None:
        if self.status == "lost":
            self.effect = RedFill(self.num_leds)
        elif self.solo:
            self.effect = Fireworks(self.num_leds, rng=self.rng)
        else:
            self.effect = Confetti(self.num_leds, self.colors[self.winner].led, FINAL_TIME, self.rng)

    def on_leave(self, player: str) -> None:
        if player not in self.players:
            return
        idx = self.players.index(player)
        self.left.add(idx)
        if self.status == "playing" and self.stage == "turn" and self.turn == idx:
            self._start_turn(self._next(idx))

    # --- output -----------------------------------------------------------------

    def _span(self, led: int) -> range:
        return range(max(0, led - self.zone), min(self.num_leds, led + self.zone + 1))

    def render(self, pixels: list[RGB]) -> None:
        n = self.num_leds
        if self.effect:
            pixels[:] = [OFF] * n
            self.effect.render(pixels)
            return
        out = [OFF] * n
        if self.stage == "intro":  # a sweep up the strip
            head = int(n * (1 - self.timer / INTRO_TIME))
            for i in range(max(0, head - 6), min(n, head + 1)):
                out[i] = scale(GOLD, 1 - (head - i) / 7)
            pixels[:] = out
            return
        if self.stage == "glow":
            # The whole strip breathes in the heat, twice, then fades.
            k = 1 - self.timer / GLOW_TIME
            level = GLOW * (0.5 - 0.5 * math.cos(k * 4 * math.pi)) * (1 - k * 0.5)
            out = [scale(self.digs[-1][1].led, level)] * n
        for k, (led, heat, _) in enumerate(self.digs):
            bright = 1.0 if k == len(self.digs) - 1 else MARKER
            for i in self._span(led):
                out[i] = scale(heat.led, bright)
        if self.stage == "turn":
            pulse = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(self.t * 2 * math.pi * 1.5))
            for i in self._span(self.aim):
                out[i] = scale(WHITE, pulse)
        elif self.stage == "reveal":
            on = int(self.timer * 4) % 2 == 0
            for i in self._span(self.treasure):
                out[i] = GOLD if on else scale(GOLD, 0.15)
        pixels[:] = out

    def state(self) -> dict[str, Any]:
        # The treasure is only sent once it's found (or the game is lost).
        return {
            "status": self.status,
            "stage": self.stage,
            "solo": self.solo,
            "leds": self.num_leds,
            "zone": self.zone,
            "turn": self.turn,
            "turn_left": math.ceil(self.timer) if self.stage == "turn" and not self.solo else None,
            "aim": self.aim,
            "digs": [{"led": led, "heat": heat.id, "player": p} for led, heat, p in self.digs],
            "digs_left": self.digs_left,
            "treasure": self.treasure if self.stage == "reveal" or self.effect else None,
            "winner": self.winner,
            "players": [
                {
                    "color": c.name,
                    "hex": c.ui,
                    "digs": sum(1 for d in self.digs if d[2] == i),
                    "left": i in self.left,
                }
                for i, c in enumerate(self.colors)
            ],
        }
