"""Simon Says: a memory game for 1–6 phones.

The strip plays a sequence of colors, then you repeat it with the color
buttons on your phone. Each round the sequence gets one color longer; reach
the target length to win. Solo, one mistake ends the game.

Easy and normal split the strip into one zone per color (bottom to top, dimly
lit) and a step flashes its zone; the phone's buttons are stacked in the same
order. Hard flashes the whole strip, adds a fifth color and shuffles the
buttons every round, so only the colors help.

With friends there are two modes (setting "mode"):
  together  everyone repeats the same sequence on their own phone at once.
            A mistake knocks you out. If everyone still in gets the round
            wrong, nobody is out and the round is replayed with a new last
            color. Presses don't show on the strip, so nobody can copy.
  turns     no playback: on your turn, repeat the sequence from memory, then
            add a color of your choice. Every press lights the strip so the
            others can learn it. A mistake knocks you out and the next player
            gets the same sequence.
Last one standing wins. Everyone still in when the sequence reaches the
target shares the win.

Not pressing for PRESS_TIMEOUT counts as a mistake, so nobody can stall a game.
"""

import random
from dataclasses import dataclass
from typing import Any

from ..colors import OFF, PALETTE, RGB, GameColor, scale
from ..effects.confetti import Confetti
from ..effects.fireworks import Fireworks
from ..effects.red_fill import RedFill
from .base import Choice, Game, GameInfo, Setting

PLAYER_COLORS = [
    GameColor("blue", (0, 0, 255), "#2a5cff"),
    GameColor("yellow", (255, 160, 0), "#ffd21f"),
    GameColor("magenta", (220, 0, 255), "#c43cff"),
    GameColor("cyan", (0, 220, 255), "#22d3ff"),
    GameColor("white", (255, 255, 255), "#f2f4f8"),
    GameColor("orange", (255, 60, 0), "#ff7a1a"),
]

INTRO_TIME = 1.5
BETWEEN_TIME = 1.5  # pause after a round (or turn) before the next one
GAP_RATIO = 0.4  # dark time between playback steps, relative to the step time
SPEEDUP = 0.05  # each extra step shortens playback steps by this fraction…
MIN_SPEED = 0.6  # …down to this fraction of the starting step time
PRESS_TIME = 0.35  # a press shown on the strip stays lit this long
PRESS_BLINK = 0.06  # dark moment when the same color is pressed again
PRESS_TIMEOUT = 10.0
ZONE_DIM = 0.08  # brightness of the zones between flashes
ZONE_GAP = 2  # dark LEDs at the top of each zone
FINAL_TIME = 6.0


@dataclass(frozen=True)
class Difficulty:
    colors: int
    step_time: float  # seconds each playback step is lit, at the start
    target: int
    zones: bool  # False: the whole strip flashes
    shuffle: bool  # shuffle the phone's buttons every round


DIFFICULTIES = {
    "easy": Difficulty(colors=4, step_time=0.7, target=8, zones=True, shuffle=False),
    "normal": Difficulty(colors=4, step_time=0.5, target=12, zones=True, shuffle=False),
    "hard": Difficulty(colors=5, step_time=0.4, target=16, zones=False, shuffle=True),
}


class Simon(Game):
    info = GameInfo(
        id="simon",
        name="Simon Says",
        description="Watch the strip play a sequence of colors, then repeat it. It gets one color longer every round!",
        difficulties=[
            Choice("easy", "Easy", "4 colors in their own spot on the strip · reach 8"),
            Choice("normal", "Normal", "4 colors, faster · reach 12"),
            Choice("hard", "Hard", "5 colors, the whole strip flashes, buttons shuffle · reach 16"),
        ],
        default_difficulty="easy",
        settings=[
            Setting(
                "mode",
                "With friends",
                [
                    Choice("together", "All at once", "Everyone repeats the strip's sequence"),
                    Choice("turns", "Take turns", "Repeat it from memory, then add a color"),
                ],
                default="together",
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
        self.colors = PALETTE[: self.cfg.colors]
        self.pcolors = PLAYER_COLORS[: len(self.players)]
        self.mode = "solo" if self.solo else settings.get("mode", "together")
        # Phone button order, top to bottom: the zones' order, top zone first.
        self.buttons = list(reversed(range(len(self.colors))))

        self.t = 0.0
        self.status = "playing"
        self.stage = "intro"
        self.timer = INTRO_TIME
        self.sequence: list[int] = [] if self.mode == "turns" else [self._random_color()]
        self.reached = 0  # longest sequence someone repeated
        self.alive = set(range(len(self.players)))  # not out, not left
        self.left: set[int] = set()
        self.winners: list[int] = []
        self.last: dict[str, Any] | None = None  # what happened in the last round
        self.lit: tuple[int, float, float] | None = None  # pressed color, when, dark start
        self.deadline: dict[int, float] = {}  # player → time their next press is due
        # together: each player's correct presses this round, who's done, who missed
        self.progress = [0] * len(self.players)
        self.done: set[int] = set()
        self.failed: set[int] = set()
        # turns: whose turn it is and how many presses they've made
        self.turn = 0
        self.entered = 0
        self.effect: Confetti | Fireworks | RedFill | None = None

    @property
    def solo(self) -> bool:
        return len(self.players) == 1

    def _random_color(self, avoid: int | None = None) -> int:
        return self.rng.choice([c for c in range(len(self.colors)) if c != avoid])

    # --- flow -----------------------------------------------------------------

    def update(self, dt: float) -> None:
        self.t += dt
        if self.status != "playing":
            self.effect.update(dt)
            self.finished = self.effect.done
            return

        if self.stage in ("intro", "between"):
            self.timer -= dt
            if self.timer <= 0:
                self._next()
        elif self.stage == "show":
            self.timer += dt  # time since playback started
            if self.timer >= len(self.sequence) * self._period():
                self._start_input()
        elif self.stage == "input":
            late = [i for i, due in self.deadline.items() if self.t >= due]
            for i in late:
                if self.stage != "input" or self.status != "playing":
                    break  # the round already ended
                self._mistake(i)

    def _next(self) -> None:
        if self.cfg.shuffle:
            self.rng.shuffle(self.buttons)
        if self.mode == "turns":
            self._start_input()
        else:
            self.stage = "show"
            self.timer = 0.0

    def _start_input(self) -> None:
        self.stage = "input"
        self.lit = None
        if self.mode == "turns":
            self.entered = 0
            self.deadline = {self.turn: self.t + PRESS_TIMEOUT}
        else:
            self.progress = [0] * len(self.players)
            self.done = set()
            self.failed = set()
            self.deadline = {i: self.t + PRESS_TIMEOUT for i in self.alive}

    def _step_time(self) -> float:
        return self.cfg.step_time * max(MIN_SPEED, 1 - SPEEDUP * (len(self.sequence) - 1))

    def _period(self) -> float:
        return self._step_time() * (1 + GAP_RATIO)

    def on_input(self, player: str, action: dict[str, Any]) -> None:
        if self.status != "playing" or self.stage != "input" or player not in self.players:
            return
        color = action.get("press")
        if color not in [c.name for c in self.colors]:
            return
        color = [c.name for c in self.colors].index(color)
        idx = self.players.index(player)
        if idx not in self.deadline:
            return  # out, not their turn, or already finished this round

        if self.mode != "together":  # the strip shows presses unless others could copy them
            same = self.lit is not None and self.lit[0] == color and self.t - self.lit[1] < PRESS_TIME
            self.lit = (color, self.t, PRESS_BLINK if same else 0.0)

        if self.mode == "turns":
            if self.entered == len(self.sequence):
                self.sequence.append(color)  # their new color
                self._turn_done()
            elif color == self.sequence[self.entered]:
                self.entered += 1
                self.deadline[idx] = self.t + PRESS_TIMEOUT
            else:
                self._mistake(idx)
            return

        if color != self.sequence[self.progress[idx]]:
            self._mistake(idx)
            return
        self.progress[idx] += 1
        self.deadline[idx] = self.t + PRESS_TIMEOUT
        if self.progress[idx] == len(self.sequence):
            del self.deadline[idx]
            self.done.add(idx)
            self._check_round()

    def _mistake(self, idx: int) -> None:
        self.deadline.pop(idx, None)
        if self.mode == "solo":
            self.status = "lost"
            self.effect = RedFill(self.num_leds)
        elif self.mode == "turns":
            self.alive.discard(idx)
            self.last = {"out": [idx]}
            self._after_turn()
        else:
            self.failed.add(idx)
            self._check_round()

    # --- together / solo --------------------------------------------------------

    def _check_round(self) -> None:
        """Once every player still in has finished or missed, knock out who
        missed and move on."""
        if self.deadline:
            return
        missed = self.failed & self.alive
        if missed and missed == self.alive:
            # Everyone missed: nobody's out, same round with a new last color.
            self.sequence[-1] = self._random_color(avoid=self.sequence[-1])
            self.last = {"out": [], "replay": True}
            self._between()
            return
        self.alive -= missed
        self.reached = len(self.sequence)
        self.last = {"out": sorted(missed), "replay": False}
        if len(self.alive) == 1 and not self.solo:
            self._finish(sorted(self.alive))
        elif len(self.sequence) >= self.cfg.target:
            self._finish(sorted(self.alive))
        else:
            self.sequence.append(self._random_color())
            self._between()

    # --- turns ----------------------------------------------------------------

    def _turn_done(self) -> None:
        self.reached = len(self.sequence)
        self.last = {"out": [], "added": self.turn}
        if len(self.sequence) >= self.cfg.target:
            self._finish(sorted(self.alive))
        else:
            self._after_turn()

    def _after_turn(self) -> None:
        self.deadline = {}
        if len(self.alive) == 1:
            self._finish(sorted(self.alive))
            return
        self.turn = self._next_alive(self.turn)
        self._between()

    def _next_alive(self, after: int) -> int:
        n = len(self.players)
        return next(j for j in ((after + k) % n for k in range(1, n + 1)) if j in self.alive)

    # --- endings ----------------------------------------------------------------

    def _between(self) -> None:
        self.stage = "between"
        self.timer = BETWEEN_TIME

    def on_leave(self, player: str) -> None:
        if player not in self.players:
            return
        idx = self.players.index(player)
        if idx in self.left:
            return
        self.left.add(idx)
        was_alive = idx in self.alive
        self.alive.discard(idx)
        had_turn = self.deadline.pop(idx, None) is not None
        if self.status != "playing" or not was_alive:
            return
        if len(self.alive) == 1:
            self._finish(sorted(self.alive))  # last one standing wins by forfeit
        elif self.mode == "turns":
            if self.turn == idx:
                if had_turn:
                    self.last = {"out": [], "left": idx}
                self.turn = self._next_alive(idx)
                if had_turn:
                    self._between()
        elif self.stage == "input":
            self._check_round()

    def _finish(self, winners: list[int]) -> None:
        self.status = "won"
        self.winners = winners
        self.lit = None
        if len(winners) == 1 and not self.solo:
            self.effect = Confetti(self.num_leds, self.pcolors[winners[0]].led, FINAL_TIME, self.rng)
        else:
            self.effect = Fireworks(self.num_leds, rng=self.rng)

    # --- output ---------------------------------------------------------------

    def _zone(self, color: int) -> range:
        size = self.num_leds / len(self.colors)
        start = round(color * size)
        end = round((color + 1) * size)
        return range(start, max(start + 1, end - ZONE_GAP))

    def _lit_color(self) -> int | None:
        if self.stage == "show":
            period = self._period()
            step = int(self.timer // period)
            if step < len(self.sequence) and self.timer - step * period < self._step_time():
                return self.sequence[step]
        elif self.lit is not None:
            color, at, dark = self.lit
            if at + dark <= self.t < at + PRESS_TIME:
                return color
        return None

    def render(self, pixels: list[RGB]) -> None:
        for i in range(self.num_leds):
            pixels[i] = OFF
        if self.status != "playing":
            self.effect.render(pixels)
            return
        lit = self._lit_color()
        if not self.cfg.zones:
            if lit is not None:
                for i in range(self.num_leds):
                    pixels[i] = self.colors[lit].led
            return
        for c, color in enumerate(self.colors):
            led = color.led if c == lit else scale(color.led, ZONE_DIM)
            for i in self._zone(c):
                pixels[i] = led

    def state(self) -> dict[str, Any]:
        # Never include the sequence: players must watch the strip.
        return {
            "status": self.status,
            "mode": self.mode,
            "stage": self.stage,
            "length": len(self.sequence),
            "target": self.cfg.target,
            "reached": self.reached,
            "buttons": [{"name": self.colors[c].name, "hex": self.colors[c].ui} for c in self.buttons],
            "turn": self.turn if self.mode == "turns" else None,
            "entered": self.entered,
            "players": [
                {
                    "color": c.name,
                    "hex": c.ui,
                    "out": i not in self.alive and i not in self.left,
                    "left": i in self.left,
                    "progress": self.progress[i],
                    "done": i in self.done,
                    "failed": i in self.failed,
                }
                for i, c in enumerate(self.pcolors)
            ],
            "last": self.last,
            "winners": self.winners,
        }
