"""Hot Potato: throw the potato on before it blows up, 1–6 phones.

The strip is split into one zone per player, bottom to top, glowing in
their color. The potato sits in someone's zone: they tap to throw it to a
random other player who's still in, and it flies along the strip. After it
lands there's a short catch time before it can be thrown again.

A hidden fuse burns down: the potato gets redder and flickers faster as it
does (on medium and hard that's only a rough hint). Whoever has it when the
fuse runs out is out: their zone bursts and the others spread out over the
strip. Every round is a little faster. The last player left wins.

A potato in the air belongs to whoever it's flying to.

Playing alone, computer players join in (setting "computers").

Phones send {"throw": true, "at": <server time>}. A throw counts from when it
happened on the phone (at most MAX_TAP_AGE ago), and the explosion is judged
JUDGE_DELAY after the fuse runs out, so a throw that was on its way when the
fuse ran out still counts.
"""

import math
import random
from dataclasses import dataclass
from typing import Any

from ..colors import OFF, RGB, WHITE, GameColor, scale
from ..effects.confetti import Confetti
from ..effects.fireworks import Fireworks
from ..effects.red_fill import RedFill
from .base import Choice, Game, GameInfo, Setting

# No red or orange: those are the potato and the explosion. Yellow last.
PLAYER_COLORS = [
    GameColor("blue", (0, 0, 255), "#2a5cff"),
    GameColor("green", (0, 255, 0), "#22dd44"),
    GameColor("magenta", (220, 0, 255), "#c43cff"),
    GameColor("cyan", (0, 220, 255), "#22d3ff"),
    GameColor("white", (255, 255, 255), "#f2f4f8"),
    GameColor("yellow", (255, 160, 0), "#ffd21f"),
]
ZONE = 0.1  # how bright the zones glow
HOLDER_ZONE = 0.28  # the zone with the potato, once it can be thrown

COUNTDOWN = 3.0
DROP_TIME = 1.0  # the potato falls in from the top at the start of a round
BOOM_TIME = 2.0
SPEEDUP = 0.88  # each round's fuse and flights, compared with the last
MIN_FLIGHT = 0.3
MAX_TAP_AGE = 0.3
JUDGE_DELAY = 0.3  # wait for late throws before deciding who's out
FINAL_TIME = 6.0


@dataclass(frozen=True)
class Difficulty:
    fuse: tuple[float, float]  # seconds, random in this range (first round)
    catch: float  # seconds after landing before it can be thrown again
    flight: float  # seconds to fly the whole strip (first round)
    lie: float  # how far off the potato's heat can be: 0 = honest
    cpu_reaction: tuple[float, float]  # how long a computer player holds it


DIFFICULTIES = {
    "easy": Difficulty((15.0, 25.0), 0.3, 1.2, 0.0, (0.5, 1.6)),
    "medium": Difficulty((10.0, 20.0), 0.5, 1.0, 0.15, (0.35, 1.2)),
    "hard": Difficulty((6.0, 15.0), 0.7, 0.8, 0.35, (0.25, 0.9)),
}


class HotPotato(Game):
    info = GameInfo(
        id="hot_potato",
        name="Hot Potato",
        description="Tap to throw the potato on before it blows up! Last one standing wins.",
        difficulties=[
            Choice("easy", "Easy", "A long fuse, and the potato's heat tells the truth"),
            Choice("medium", "Medium", "A shorter fuse; its heat is only a rough hint"),
            Choice("hard", "Hard", "A short fuse, a long catch, and the heat lies"),
        ],
        default_difficulty="easy",
        settings=[
            Setting(
                "computers",
                "Computer players (playing alone)",
                [
                    Choice("2", "2 computers"),
                    Choice("3", "3 computers"),
                    Choice("5", "5 computers"),
                ],
                default="3",
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
        computers = int(settings.get("computers", "3")) if len(self.players) == 1 else 0
        racers = len(self.players) + computers
        self.colors = PLAYER_COLORS[:racers]
        self.humans = len(self.players)  # racers from here on are computers

        self.t = 0.0
        self.status = "playing"
        self.stage = "countdown"  # countdown → drop → play → judging → boom → drop …
        self.until = COUNTDOWN  # when this stage ends (countdown, drop, boom)
        self.round = 0
        self.out: list[int] = []  # in the order they went out
        self.left: set[int] = set()
        self.zones: list[int] = list(range(racers))  # this round's players, bottom to top

        self.holder: int | None = None  # whose it is (in the air: whoever it's flying to)
        self.flight: tuple[float, float, float, float] | None = None  # from, to (LED), start, end
        self.ready_at = 0.0  # when the holder can throw it
        self.boom_at = math.inf  # when the fuse runs out
        self.round_start = 0.0
        self.heat_fuse = 1.0  # the fuse the potato's heat shows (off by up to cfg.lie)
        self.cpu_throw: float | None = None  # when the computer holding it throws
        self.victim: int | None = None
        self.winner: int | None = None
        self.effect: Confetti | Fireworks | RedFill | None = None

    def _cpu(self, i: int) -> bool:
        return i >= self.humans

    def _alive(self) -> list[int]:
        return [i for i in range(len(self.colors)) if i not in self.out and i not in self.left]

    # --- the strip layout --------------------------------------------------------

    def _zone(self, i: int) -> tuple[int, int]:
        """The LEDs of player i's zone this round: start, end."""
        k = len(self.zones)
        j = self.zones.index(i)
        return j * self.num_leds // k, (j + 1) * self.num_leds // k

    def _center(self, i: int) -> float:
        start, end = self._zone(i)
        return (start + end - 1) / 2

    # --- flow ----------------------------------------------------------------------

    @property
    def heat(self) -> float:
        """How hot the potato looks, 0–1."""
        if self.stage not in ("drop", "play", "judging"):
            return 0.0
        return min(1.0, max(0.0, (self.t - self.round_start) / self.heat_fuse))

    def _new_round(self) -> None:
        self.round += 1
        self.zones = self._alive()
        speed = SPEEDUP ** (self.round - 1)
        fuse = self.rng.uniform(*self.cfg.fuse) * speed
        self.round_start = self.t
        self.boom_at = self.t + DROP_TIME + fuse
        self.heat_fuse = DROP_TIME + fuse * self.rng.uniform(1 - self.cfg.lie, 1 + self.cfg.lie)
        self.stage, self.until = "drop", self.t + DROP_TIME
        self.victim = None
        holder = self.rng.choice(self.zones)
        self._fly(holder, self.num_leds - 1, self.t, DROP_TIME)

    def _fly(self, to: int, start_led: float, when: float, duration: float) -> None:
        self.holder = to
        self.flight = (start_led, self._center(to), when, when + duration)
        self.ready_at = when + duration + self.cfg.catch
        self.cpu_throw = None
        if self._cpu(to):
            low, high = self.cfg.cpu_reaction
            self.cpu_throw = self.ready_at + self.rng.uniform(low, high)

    def _throw(self, when: float) -> None:
        """The holder throws it at `when` to a random other player who's still in."""
        others = [i for i in self._alive() if i != self.holder and i in self.zones]
        if not others:
            return
        to = self.rng.choice(others)
        start = self._center(self.holder)
        speed = SPEEDUP ** (self.round - 1)
        distance = abs(self._center(to) - start) / max(1, self.num_leds)
        self._fly(to, start, when, max(MIN_FLIGHT, distance * self.cfg.flight * speed))

    def update(self, dt: float) -> None:
        self.t += dt
        if self.status != "playing":
            self.effect.update(dt)
            self.finished = self.effect.done
            return
        if self.flight and self.t >= self.flight[3]:
            self.flight = None  # landed
        if self.stage == "countdown":
            if self.t >= self.until:
                self._new_round()
        elif self.stage == "drop":
            if self.t >= self.until:
                self.stage = "play"
        if self.stage == "play":
            if self.cpu_throw is not None and self.t >= self.cpu_throw and self.cpu_throw < self.boom_at:
                self._throw(self.cpu_throw)
            if self.t >= self.boom_at:
                self.stage = "judging"
        if self.stage == "judging" and self.t >= self.boom_at + JUDGE_DELAY:
            self._boom()
        elif self.stage == "boom" and self.t >= self.until:
            self._after_boom()

    def _boom(self) -> None:
        self.stage, self.until = "boom", self.t + BOOM_TIME
        self.victim = self.holder
        self.out.append(self.holder)
        self.holder = self.flight = self.cpu_throw = None
        if self.humans == 1 and self.victim == 0:
            self._end(winner=None)  # alone and out: no point watching the computers

    def _after_boom(self) -> None:
        alive = self._alive()
        if len(alive) <= 1:
            self._end(winner=alive[0] if alive else None)
        else:
            self._new_round()

    def on_input(self, player: str, action: dict[str, Any]) -> None:
        if self.status != "playing" or player not in self.players or action.get("throw") is not True:
            return
        i = self.players.index(player)
        if i != self.holder or self.t < self.ready_at:
            return
        at = action.get("at")
        back = 0.0 if not isinstance(at, (int, float)) else min(MAX_TAP_AGE, max(0.0, self.clock() - float(at)))
        when = max(self.t - back, self.ready_at)
        if self.stage == "play" or (self.stage == "judging" and when < self.boom_at):
            self._throw(when)

    def on_leave(self, player: str) -> None:
        if player not in self.players or self.status != "playing":
            return
        i = self.players.index(player)
        self.left.add(i)
        alive = self._alive()
        if len(alive) <= 1 or not any(not self._cpu(j) for j in alive):
            self._end(winner=alive[0] if len(alive) == 1 else None)
        elif self.holder == i and self.stage in ("drop", "play", "judging"):
            self._throw(self.t)  # it bounces on to someone else

    def _end(self, winner: int | None) -> None:
        self.winner = winner
        won = winner is not None and not self._cpu(winner)
        self.status = "won" if won else "lost"
        if not won:
            self.effect = RedFill(self.num_leds)
        elif self.humans == 1:
            self.effect = Fireworks(self.num_leds, rng=self.rng)
        else:
            self.effect = Confetti(self.num_leds, self.colors[winner].led, FINAL_TIME, self.rng)

    # --- output -------------------------------------------------------------------

    def _potato_at(self) -> float | None:
        if self.holder is None:
            return None
        if self.flight is None:
            return self._center(self.holder)
        a, b, start, end = self.flight
        k = min(1.0, max(0.0, (self.t - start) / (end - start)))
        k = k * k * (3 - 2 * k)  # ease in and out
        return a + (b - a) * k

    def render(self, pixels: list[RGB]) -> None:
        n = self.num_leds
        if self.status != "playing":
            pixels[:] = [OFF] * n
            self.effect.render(pixels)
            return
        out = [OFF] * n
        for i in self.zones:
            start, end = self._zone(i)
            if i in self.left or (i in self.out and i != self.victim):
                continue
            ready = i == self.holder and self.flight is None and self.t >= self.ready_at
            color = scale(self.colors[i].led, HOLDER_ZONE if ready else ZONE)
            out[start : max(start + 1, end - 1)] = [color] * max(1, end - 1 - start)  # a dark gap above
        if self.stage == "boom" and self.victim is not None:
            self._draw_boom(out)
        pos = self._potato_at()
        if pos is not None:
            self._draw_potato(out, pos)
        pixels[:] = out

    def _draw_potato(self, out: list[RGB], pos: float) -> None:
        n = self.num_leds
        h = self.heat
        color = (255, int(110 * (1 - h)), 0)
        flicker = 0.75 + 0.25 * math.sin(self.t * (6 + 30 * h))
        radius = max(1.0, n / 60)
        for p in range(max(0, int(pos - radius)), min(n, int(pos + radius) + 2)):
            f = 1 - abs(p - pos) / (radius + 1)
            if f > 0:
                out[p] = scale(color, f * flicker)
        if h > 0.5 and self.flight is None:  # sparks
            for _ in range(int(h * 4 * self.rng.random())):
                p = int(pos + self.rng.uniform(-3, 3) * radius)
                if 0 <= p < n:
                    out[p] = scale((255, 180, 60), self.rng.uniform(0.4, 1))

    def _draw_boom(self, out: list[RGB]) -> None:
        start, end = self._zone(self.victim)
        k = 1 - (self.until - self.t) / BOOM_TIME  # 0 → 1
        if k < 0.15:
            color = WHITE
        else:
            fade = (1 - k) ** 1.5
            color = scale((255, int(120 * fade), 0), fade)
        end = max(start + 1, end - 1)  # keep the gap above dark
        out[start:end] = [color] * (end - start)

    def state(self) -> dict[str, Any]:
        holder = self.holder
        return {
            "status": self.status,
            "stage": self.stage,
            "mode": "computer" if self.humans == 1 else "party",
            "round": self.round,
            "countdown": math.ceil(self.until - self.t) if self.stage == "countdown" else 0,
            "holder": holder,
            "flying": self.flight is not None,
            "ready": holder is not None and self.flight is None and self.t >= self.ready_at,
            "heat": round(self.heat, 1),
            "victim": self.victim,
            "winner": self.winner,
            "players": [
                {
                    "color": c.name,
                    "hex": c.ui,
                    "cpu": self._cpu(i),
                    "out": i in self.out,
                    "left": i in self.left,
                }
                for i, c in enumerate(self.colors)
            ],
        }
