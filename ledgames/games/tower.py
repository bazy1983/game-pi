"""Tower Stack: build the tallest tower you can, 1–6 phones taking turns.

Your tower starts as a block of your color at the bottom of the strip. A
white block slides up and down over the top of it: tap to drop it. It should
land right on top of the tower. Any gap or overlap is cut off, so the next
block is that much shorter. Miss completely and the tower is finished. Every
block is a little faster than the last. Three perfect drops in a row grow
the block back by one LED. Reach the top of the strip to top out.

With more players, each builds a tower in turn (the strip shows the best one
so far as a blinking mark to beat). Setting "goal": the most blocks wins, or
the tallest tower (in LEDs) wins, so keeping your blocks big pays off.

Phones send {"tap": true, "at": <server time>}. A drop counts from where the
block was when the phone was tapped (at most MAX_TAP_AGE ago), so Wi-Fi
delay doesn't move it.
"""

import colorsys
import math
import random
from dataclasses import dataclass
from typing import Any

from ..colors import OFF, RED, RGB, WHITE, GameColor, scale
from ..effects.confetti import Confetti
from ..effects.fireworks import Fireworks
from .base import Choice, Game, GameInfo, Setting

# No red or white: those are the cuts and the sliding block.
PLAYER_COLORS = [
    GameColor("blue", (0, 0, 255), "#2a5cff"),
    GameColor("green", (0, 255, 0), "#22dd44"),
    GameColor("magenta", (220, 0, 255), "#c43cff"),
    GameColor("cyan", (0, 220, 255), "#22d3ff"),
    GameColor("orange", (255, 60, 0), "#ff7a1a"),
    GameColor("yellow", (255, 160, 0), "#ffd21f"),
]

COUNTDOWN = 3.0  # before each turn; the foundation blinks
CUT_TIME = 0.6  # the cut-off piece fades before the next block comes
FALL_TIME = 1.5  # a missed block blinks red
TOP_TIME = 2.5  # topped out: the tower shimmers
CRUMBLE_TIME = 1.5  # the finished tower drops away, top first
MAX_TAP_AGE = 0.3
PERFECT_STREAK = 3  # perfect drops in a row that grow the block by one LED
MAX_SPEEDUP = 2.5  # the blocks never get faster than this × the first one
TOWER = 0.55  # how bright the tower is (the newest block is full brightness)
HUE_STEP = 0.07  # each block's color on the rainbow, after the last one's
HUES = (0.1, 0.9)  # the rainbow skips red, which is for the cuts
FINAL_TIME = 6.0


@dataclass(frozen=True)
class Difficulty:
    block: float  # the first block, as a share of the strip
    speed: float  # how fast the first block slides, in strips per second
    speedup: float  # each block's speed, compared with the last


DIFFICULTIES = {
    "easy": Difficulty(0.06, 0.08, 1.04),
    "medium": Difficulty(0.045, 0.11, 1.05),
    "hard": Difficulty(0.03, 0.14, 1.06),
}


@dataclass
class Layer:
    bottom: int
    length: int
    color: RGB


@dataclass
class Score:
    blocks: int = 0
    height: int = 0
    perfects: int = 0
    topped: bool = False
    done: bool = False
    left: bool = False


def rainbow(k: int) -> RGB:
    lo, hi = HUES
    r, g, b = colorsys.hsv_to_rgb(lo + (k * HUE_STEP) % (hi - lo), 1.0, 1.0)
    return (int(r * 255), int(g * 255), int(b * 255))


class Tower(Game):
    info = GameInfo(
        id="tower",
        name="Tower Stack",
        description="Tap to drop each block right on top of your tower. Whatever hangs over is cut off. How high can you build?",
        difficulties=[
            Choice("easy", "Easy", "Big blocks that start slow"),
            Choice("medium", "Medium", "Smaller, faster blocks"),
            Choice("hard", "Hard", "Tiny blocks that speed up quickly"),
        ],
        default_difficulty="easy",
        settings=[
            Setting(
                "goal",
                "With more players",
                [
                    Choice("blocks", "Most blocks wins", "Stack as many blocks as you can"),
                    Choice("height", "Tallest tower wins", "Keep your blocks big to build high"),
                ],
                default="blocks",
            )
        ],
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
        self.start_len = max(2, round(num_leds * self.cfg.block))
        self.scores = [Score() for _ in self.players]
        self.goal = settings.get("goal", "blocks") if len(self.players) > 1 else "blocks"
        self.status = "playing"
        self.winners: list[int] = []
        self.t = 0.0
        self.effect: Confetti | Fireworks | None = None
        self.turn = 0
        self._start_turn(0)

    @property
    def solo(self) -> bool:
        return len(self.players) == 1

    @property
    def top(self) -> int:
        return self.layers[-1].bottom + self.layers[-1].length

    # --- flow -------------------------------------------------------------------

    def _start_turn(self, idx: int) -> None:
        self.turn = idx
        self.layers = [Layer(0, self.start_len, self.colors[idx].led)]
        self.length = self.start_len  # the sliding block
        self.speed = self.cfg.speed * self.num_leds  # LEDs per second
        self.streak = 0
        self.last: dict[str, Any] | None = None  # the last drop: cut, perfect, grew
        self.drops = 0
        self.cut: list[int] = []  # LEDs of the piece just cut off
        self.missed: list[int] = []
        self.stage, self.timer = "intro", COUNTDOWN

    def _spawn(self) -> None:
        self.stage = "moving"
        self.t0 = self.t

    def pos(self, at: float) -> float:
        """Where the sliding block's bottom is at time `at`: it starts a block
        above the tower and bounces between there and a block below it."""
        span = 2 * self.length
        u = (max(0.0, at - self.t0) * self.speed + span) % (2 * span)
        x = u if u <= span else 2 * span - u
        return self.top - self.length + x

    def update(self, dt: float) -> None:
        self.t += dt
        if self.effect:
            self.effect.update(dt)
            self.finished = self.effect.done
            return
        if self.stage == "over":
            self.finished = True
            return
        if self.stage == "moving":
            return
        self.timer -= dt
        if self.timer > 0:
            return
        if self.stage in ("intro", "cut"):
            self._spawn()
        elif self.stage in ("fall", "topped"):
            if self.solo and self.scores[0].topped:
                self._finish()
            else:
                self.stage, self.timer = "crumble", CRUMBLE_TIME
        elif self.stage == "crumble":
            nxt = self._next_turn()
            if nxt is None:
                self._finish()
            else:
                self._start_turn(nxt)

    def _next_turn(self) -> int | None:
        for j in range(self.turn + 1, len(self.players)):
            if not self.scores[j].left:
                return j
        return None

    def on_input(self, player: str, action: dict[str, Any]) -> None:
        if self.status != "playing" or self.stage != "moving" or action.get("tap") is not True:
            return
        if player not in self.players or self.players.index(player) != self.turn:
            return
        at = action.get("at")
        back = 0.0 if not isinstance(at, (int, float)) else min(MAX_TAP_AGE, max(0.0, self.clock() - float(at)))
        self._drop(self.t - back)

    def _drop(self, when: float) -> None:
        score = self.scores[self.turn]
        p = round(self.pos(when))
        top, length = self.top, self.length
        cut = abs(p - top)
        self.drops += 1
        if cut >= length:  # missed the tower
            self.last = {"cut": length, "perfect": False, "grew": False, "missed": True}
            self.missed = [i for i in range(p, p + length) if 0 <= i < self.num_leds]
            self._end_turn(topped=False)
            self.stage, self.timer = "fall", FALL_TIME
            return
        new_len = length - cut
        grew = False
        if cut == 0:
            self.streak += 1
            score.perfects += 1
            if self.streak % PERFECT_STREAK == 0 and new_len < self.start_len:
                new_len += 1
                grew = True
        else:
            self.streak = 0
        new_len = min(new_len, self.num_leds - top)
        self.layers.append(Layer(top, new_len, rainbow(len(self.layers) - 1)))
        # Too low: the part sunk into the tower is cut. Too high: the block
        # drops onto the tower and its top is cut (by the size of the gap).
        gone = range(p, top) if p < top else range(top + new_len, top + length)
        self.cut = [i for i in gone if 0 <= i < self.num_leds]
        self.last = {"cut": cut, "perfect": cut == 0, "grew": grew, "missed": False}
        self.length = new_len
        self.speed = min(self.speed * self.cfg.speedup, self.cfg.speed * self.num_leds * MAX_SPEEDUP)
        score.blocks, score.height = len(self.layers) - 1, self.top
        if self.top + self.length > self.num_leds:  # no room for another block
            self._end_turn(topped=True)
            self.stage, self.timer = "topped", TOP_TIME
        else:
            self.stage, self.timer = "cut", CUT_TIME

    def _end_turn(self, topped: bool) -> None:
        score = self.scores[self.turn]
        score.topped, score.done = topped, True
        score.blocks, score.height = len(self.layers) - 1, self.top

    def on_leave(self, player: str) -> None:
        if player not in self.players or self.status != "playing":
            return
        idx = self.players.index(player)
        self.scores[idx].left = True
        if idx == self.turn and self.stage in ("intro", "moving", "cut"):
            self._end_turn(topped=False)
            self.stage, self.timer = "crumble", CRUMBLE_TIME

    def _finish(self) -> None:
        if self.solo:
            topped = self.scores[0].topped
            self.status = "won" if topped else "lost"
            self.winners = [0] if topped else []
            if topped:
                self.effect = Fireworks(self.num_leds, rng=self.rng)
            else:
                self.stage = "over"  # the tower already crumbled away
            return
        self.status = "won"
        here = [i for i, s in enumerate(self.scores) if not s.left]
        best = max((self._rank(i) for i in here), default=(0, 0))
        self.winners = [i for i in here if self._rank(i) == best]
        if len(self.winners) == 1:
            self.effect = Confetti(self.num_leds, self.colors[self.winners[0]].led, FINAL_TIME, self.rng)
        else:
            self.effect = Fireworks(self.num_leds, rng=self.rng)

    def _rank(self, i: int) -> tuple[int, int]:
        """What decides the winner, then the tie-break."""
        s = self.scores[i]
        return (s.height, s.blocks) if self.goal == "height" else (s.blocks, s.height)

    def _leader(self) -> int | None:
        """The best finished tower before this turn, to beat."""
        done = [i for i in range(self.turn) if self.scores[i].done and not self.scores[i].left]
        if not done:
            return None
        return max(done, key=lambda i: (*self._rank(i), -i))

    # --- output -----------------------------------------------------------------

    def render(self, pixels: list[RGB]) -> None:
        n = self.num_leds
        if self.effect:
            pixels[:] = [OFF] * n
            self.effect.render(pixels)
            return
        out = [OFF] * n
        if self.stage == "over":
            pixels[:] = out
            return
        limit = n
        if self.stage == "crumble":
            limit = int(self.top * self.timer / CRUMBLE_TIME)
        for k, layer in enumerate(self.layers):
            if self.stage == "topped":
                color = rainbow(k + int(self.t * 12))
                bright = 0.4 + 0.6 * (0.5 + 0.5 * math.sin(self.t * 8 - k * 0.6))
            else:
                color = layer.color
                bright = 1.0 if k == len(self.layers) - 1 and k > 0 else TOWER
            if self.stage == "intro" and k == 0:
                bright = 1.0 if int(self.timer * 3) % 2 == 0 else 0.2
            for i in range(layer.bottom, min(limit, layer.bottom + layer.length, n)):
                out[i] = scale(color, bright)

        leader = None if self.solo else self._leader()
        if leader is not None and self.stage != "crumble":
            mark = self.scores[leader].height
            if self.top < mark <= n and int(self.t * 2.5) % 2 == 0:
                out[mark - 1] = self.colors[leader].led

        if self.stage == "moving":
            p = round(self.pos(self.t))
            for i in range(max(0, p), min(n, p + self.length)):
                out[i] = WHITE
        elif self.stage == "cut":
            fade = max(0.0, self.timer / CUT_TIME)
            for i in self.cut:
                out[i] = scale(RED, fade)
        elif self.stage == "fall":
            on = int(self.timer * 6) % 2 == 0
            for i in self.missed:
                out[i] = RED if on else scale(RED, 0.15)
        pixels[:] = out

    def state(self) -> dict[str, Any]:
        leader = None if self.solo else self._leader()
        return {
            "status": self.status,
            "stage": self.stage,
            "solo": self.solo,
            "goal": self.goal,
            "countdown": math.ceil(self.timer) if self.stage == "intro" else 0,
            "leds": self.num_leds,
            "turn": self.turn,
            "block": self.length,
            "start_block": self.start_len,
            "height": self.top,
            "blocks": len(self.layers) - 1,
            "streak": self.streak,
            "drops": self.drops,
            "last": self.last,
            "leader": leader,
            "winners": self.winners,
            "players": [
                {
                    "color": c.name,
                    "hex": c.ui,
                    "blocks": s.blocks,
                    "height": s.height,
                    "perfects": s.perfects,
                    "topped": s.topped,
                    "done": s.done,
                    "left": s.left,
                }
                for c, s in zip(self.colors, self.scores)
            ],
        }
