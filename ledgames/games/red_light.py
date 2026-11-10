"""Red Light, Green Light: a race up the strip for 1–6 phones.

Each player is a dot of their color, starting at the bottom. Hold your
button to climb; let go to stop. The whole strip glows the light's color:
green, a yellow warning before red (shorter on medium, none on hard), then
red. Anyone still holding GRACE seconds after it turns red is caught: their
dot slides back down a chunk of the strip, and they can't move until the
next green. First to the top wins.

Hard also has fake-outs: the strip flickers red for a moment during green.
It isn't a real red, so nobody gets caught, but whoever let go lost time.

Playing alone, pick (setting "solo"): race a computer dot, or reach the top
before the clock runs out.

Phones send {"hold": true/false, "at": <server time>}. A release counts from
when it happened on the phone (at most MAX_TAP_AGE ago), so Wi-Fi delay
doesn't get a player caught; the catch is judged JUDGE_DELAY after the grace
period ends, once late releases have arrived.
"""

import math
import random
from dataclasses import dataclass
from typing import Any

from ..colors import OFF, RGB, GameColor, scale
from ..effects.confetti import Confetti
from ..effects.fireworks import Fireworks
from ..effects.red_fill import RedFill
from .base import Choice, Game, GameInfo, Setting

# No red or green (the light), yellow last (the warning).
PLAYER_COLORS = [
    GameColor("blue", (0, 0, 255), "#2a5cff"),
    GameColor("magenta", (220, 0, 255), "#c43cff"),
    GameColor("cyan", (0, 220, 255), "#22d3ff"),
    GameColor("white", (255, 255, 255), "#f2f4f8"),
    GameColor("orange", (255, 60, 0), "#ff7a1a"),
    GameColor("yellow", (255, 160, 0), "#ffd21f"),
]
LIGHTS: dict[str, RGB] = {"green": (0, 255, 0), "yellow": (255, 140, 0), "red": (255, 0, 0)}
BACKGROUND = 0.18  # how bright the light glows behind the dots

COUNTDOWN = 3.0
CLIMB_TIME = 14.0  # seconds of holding to climb the whole strip
RED_TIME = (2.0, 4.0)
MAX_TAP_AGE = 0.3
JUDGE_DELAY = 0.3  # wait for late releases before deciding who's caught
SLIDE_TIME = 0.5  # a caught dot slides back over this long
DOT = 3  # LEDs per player
FAKE_TIME = 0.3
FINAL_TIME = 6.0


@dataclass(frozen=True)
class Difficulty:
    green: tuple[float, float]  # seconds of green, random in this range
    warning: float  # yellow before red; 0 = none
    grace: float  # seconds to let go after red
    penalty: float  # fraction of the strip a caught player slides back
    fakes: float  # chance a green has a fake-out
    time_limit: float  # solo against the clock
    # The computer: how fast it lets go when it sees red, and how likely it
    # stops at the warning or falls for a fake-out.
    cpu_reaction: tuple[float, float]
    cpu_careful: float
    cpu_fooled: float


DIFFICULTIES = {
    "easy": Difficulty((3.0, 6.0), 1.0, 0.5, 0.20, 0.0, 60, (0.3, 0.9), 0.5, 0.0),
    "medium": Difficulty((2.0, 5.0), 0.5, 0.4, 0.25, 0.0, 45, (0.15, 0.5), 0.7, 0.0),
    "hard": Difficulty((1.5, 4.5), 0.0, 0.3, 0.30, 0.4, 40, (0.08, 0.32), 0.0, 0.3),
}


class RedLight(Game):
    info = GameInfo(
        id="red_light",
        name="Red Light, Green Light",
        description="Hold to climb the strip while it's green. Still moving when it turns red? Slide back down!",
        difficulties=[
            Choice("easy", "Easy", "Long greens, a yellow warning, time to stop"),
            Choice("medium", "Medium", "Shorter greens and warning, less time to stop"),
            Choice("hard", "Hard", "No warning, fake-outs, getting caught costs more"),
        ],
        default_difficulty="easy",
        settings=[
            Setting(
                "solo",
                "Playing alone",
                [
                    Choice("computer", "Race the computer", "Beat a computer dot to the top"),
                    Choice("clock", "Beat the clock", "Reach the top in time"),
                ],
                default="computer",
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
        solo = len(self.players) == 1
        self.mode = settings.get("solo", "computer") if solo else "race"
        self.cpu = 1 if self.mode == "computer" else None  # the computer's racer number
        racers = len(self.players) + (self.cpu is not None)
        self.colors = PLAYER_COLORS[:racers]

        self.t = 0.0
        self.status = "playing"
        self.stage = "countdown"
        self.light = "red"
        self.until = COUNTDOWN  # when the current light (or the countdown) ends
        self.fake: tuple[float, float] | None = None  # this green's fake-out: start, end
        self.fake_seen = False  # the computer has reacted to it
        self.red_at: float | None = None  # when the current red started
        self.judged = False

        self.pos = [0.0] * racers  # 0 = bottom, 1 = top
        self.holding = [False] * racers
        self.released = [-1.0] * racers  # when each last let go
        self.stunned = [False] * racers  # caught: can't move until the next green
        self.slide: list[tuple[float, float] | None] = [None] * racers  # caught: from, when
        self.caught = [0] * racers
        self.left: set[int] = set()
        self.cpu_plan: tuple[float, bool] | None = None  # when, hold or let go
        self.winner: int | None = None
        self.finish_time: float | None = None
        self.effect: Confetti | Fireworks | RedFill | None = None

    # --- lights ---------------------------------------------------------------

    @property
    def shown(self) -> str:
        """The light as players see it (a fake-out shows red)."""
        if self.fake and self.fake[0] <= self.t < self.fake[1]:
            return "red"
        return self.light

    def _set_light(self, light: str) -> None:
        self.light = light
        cfg = self.cfg
        if light == "green":
            length = self.rng.uniform(*cfg.green)
            self.until = self.t + length
            self.fake = None
            self.fake_seen = False
            if length > 1.5 and self.rng.random() < cfg.fakes:
                start = self.t + self.rng.uniform(0.6, length - 0.8)
                self.fake = (start, start + FAKE_TIME)
            self.red_at = None
            self.stunned = [False] * len(self.pos)
            self._cpu_plan(True, 0.2, 0.6)
        elif light == "yellow":
            self.until = self.t + cfg.warning
            if self.rng.random() < cfg.cpu_careful:
                self._cpu_plan(False, 0.1, 0.4)
        else:
            self.until = self.t + self.rng.uniform(*RED_TIME)
            self.red_at = self.t
            self.judged = False
            self._cpu_plan(False, *cfg.cpu_reaction)

    def _next_light(self) -> None:
        if self.light == "green" and self.cfg.warning:
            self._set_light("yellow")
        elif self.light in ("green", "yellow"):
            self._set_light("red")
        else:
            self._set_light("green")

    # --- the computer -----------------------------------------------------------

    def _cpu_plan(self, hold: bool, low: float, high: float) -> None:
        if self.cpu is not None:
            self.cpu_plan = (self.t + self.rng.uniform(low, high), hold)

    def _cpu_update(self) -> None:
        cpu = self.cpu
        if cpu is None:
            return
        if self.fake and not self.fake_seen and self.t >= self.fake[0]:
            self.fake_seen = True
            if self.holding[cpu] and self.rng.random() < self.cfg.cpu_fooled:
                self._cpu_plan(False, *self.cfg.cpu_reaction)  # falls for it
        if self.cpu_plan and self.t >= self.cpu_plan[0]:
            hold = self.cpu_plan[1]
            self.cpu_plan = None
            self._hold(cpu, hold, self.t)
        # Stopped for a fake-out: go again once it's really green.
        if self.light == "green" and self.shown == "green" and not self.holding[cpu] and self.cpu_plan is None:
            self._cpu_plan(True, 0.3, 0.6)

    # --- flow -------------------------------------------------------------------

    def update(self, dt: float) -> None:
        self.t += dt
        if self.status != "playing":
            self.effect.update(dt)
            self.finished = self.effect.done
            return
        if self.stage == "countdown":
            if self.t >= self.until:
                self.stage = "race"
                self._set_light("green")
            return
        if self.t >= self.until:
            self._next_light()
        self._cpu_update()

        rate = 1 / CLIMB_TIME
        for i in range(len(self.pos)):
            if self.holding[i] and not self.stunned[i] and i not in self.left:
                self.pos[i] = min(1.0, self.pos[i] + rate * dt)
                if self.pos[i] >= 1.0:
                    self._finish(i)
                    return

        if self.red_at is not None and not self.judged and self.t >= self.red_at + self.cfg.grace + JUDGE_DELAY:
            self.judged = True
            line = self.red_at + self.cfg.grace
            for i in range(len(self.pos)):
                if self.holding[i] or self.released[i] > line:
                    self._catch(i)

        if self.mode == "clock" and self.t - COUNTDOWN >= self.cfg.time_limit:
            self._end(won=False)

    def on_input(self, player: str, action: dict[str, Any]) -> None:
        if self.status != "playing" or player not in self.players:
            return
        hold = action.get("hold")
        if not isinstance(hold, bool):
            return
        at = action.get("at")
        back = 0.0 if not isinstance(at, (int, float)) else min(MAX_TAP_AGE, max(0.0, self.clock() - float(at)))
        self._hold(self.players.index(player), hold, self.t - back)

    def _hold(self, i: int, hold: bool, when: float) -> None:
        if hold == self.holding[i]:
            return
        self.holding[i] = hold
        if not hold:
            if not self.stunned[i] and self.stage == "race":
                # Take back the climb since they really let go.
                self.pos[i] = max(0.0, self.pos[i] - (self.t - when) / CLIMB_TIME)
            self.released[i] = when
        elif self.judged and self.light == "red" and self.stage == "race":
            self._catch(i)  # started moving during red

    def _catch(self, i: int) -> None:
        if self.stunned[i] or i in self.left:
            return
        self.stunned[i] = True
        self.caught[i] += 1
        self.slide[i] = (self.pos[i], self.t)
        self.pos[i] = max(0.0, self.pos[i] - self.cfg.penalty)

    def on_leave(self, player: str) -> None:
        if player in self.players:
            i = self.players.index(player)
            self.left.add(i)
            self.holding[i] = False

    def _finish(self, i: int) -> None:
        self.winner = i
        self.finish_time = self.t - COUNTDOWN
        self._end(won=i != self.cpu)

    def _end(self, won: bool) -> None:
        self.status = "won" if won else "lost"
        self.holding = [False] * len(self.pos)
        if not won:
            self.effect = RedFill(self.num_leds)
        elif len(self.players) == 1:
            self.effect = Fireworks(self.num_leds, rng=self.rng)
        else:
            self.effect = Confetti(self.num_leds, self.colors[self.winner].led, FINAL_TIME, self.rng)

    # --- output -----------------------------------------------------------------

    def _shown_pos(self, i: int) -> float:
        slide = self.slide[i]
        if slide is not None:
            start, at = slide
            k = (self.t - at) / SLIDE_TIME
            if k < 1:
                return start + (self.pos[i] - start) * k
            self.slide[i] = None
        return self.pos[i]

    def render(self, pixels: list[RGB]) -> None:
        n = self.num_leds
        if self.status != "playing":
            pixels[:] = [OFF] * n
            self.effect.render(pixels)
            return
        pixels[:] = [scale(LIGHTS[self.shown], BACKGROUND)] * n
        racers = [i for i in range(len(self.pos)) if i not in self.left]
        if not racers:
            return
        # Dots on the same spot take turns being drawn on top.
        k = int(self.t / 0.4) % len(racers)
        for i in reversed(racers[k:] + racers[:k]):
            if self.stunned[i] and int(self.t * 6) % 2:
                continue  # caught: blinks
            start = round(self._shown_pos(i) * (n - DOT))
            for p in range(max(0, start), min(n, start + DOT)):
                pixels[p] = self.colors[i].led

    def state(self) -> dict[str, Any]:
        names = len(self.players)
        return {
            "status": self.status,
            "stage": self.stage,
            "mode": self.mode,
            "light": self.shown,
            "countdown": math.ceil(self.until - self.t) if self.stage == "countdown" else 0,
            "time_left": max(0, round(self.cfg.time_limit - (self.t - COUNTDOWN)))
            if self.mode == "clock" and self.stage == "race"
            else None,
            "players": [
                {
                    "color": c.name,
                    "hex": c.ui,
                    "cpu": i >= names,
                    "progress": round(self.pos[i] * 50) * 2,  # percent, in steps of 2
                    "caught": self.stunned[i],
                    "times_caught": self.caught[i],
                    "left": i in self.left,
                }
                for i, c in enumerate(self.colors)
            ],
            "winner": self.winner,
            "finish_time": round(self.finish_time, 1) if self.finish_time is not None else None,
        }
