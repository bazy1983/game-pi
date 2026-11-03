"""Fast Tap: a reaction game for 1–6 phones.

The strip flashes red (and, on hard, fake colors) at random moments, then
green. The first player to tap during green wins the round; tapping at any
other time knocks you out of that round. 3 rounds, most wins takes the game,
ties go to sudden-death rounds between the leaders. Solo: best of 3.

Phones and the Pi are on Wi-Fi with different delays, so a tap carries the
time it happened on the Pi's clock (phones keep their offset to it in sync)
and the round is only decided a moment after green ends, once late messages
have had time to arrive.
"""

import random
from dataclasses import dataclass
from typing import Any

from ..colors import OFF, RED, RGB, GameColor
from ..effects.confetti import Confetti
from ..effects.lineup import draw_lineup
from ..effects.red_fill import RedFill
from .base import Choice, Game, GameInfo

GREEN: RGB = (0, 255, 0)

# Red and green are the signals, so players never get them.
PLAYER_COLORS = [
    GameColor("blue", (0, 0, 255), "#2a5cff"),
    GameColor("yellow", (255, 160, 0), "#ffd21f"),
    GameColor("magenta", (220, 0, 255), "#c43cff"),
    GameColor("cyan", (0, 220, 255), "#22d3ff"),
    GameColor("white", (255, 255, 255), "#f2f4f8"),
    GameColor("orange", (255, 60, 0), "#ff7a1a"),
]

ROUNDS = 3
SOLO_WINS_NEEDED = 2  # best of 3
INTRO_TIME = 2.0  # players' colors on the strip before a round; taps ignored
FLASH_TIME = 0.5  # red / fake flashes
GAP = (1.0, 4.0)  # random dark time before each flash
RED_FLASHES = (1, 5)  # random number of flashes before each green
GRACE = 0.3  # wait this long after green for late taps before deciding
MAX_TAP_AGE = 1.0  # a tap's timestamp can't claim to be older than this
ROUND_OVER_TIME = 2.5
FINAL_TIME = 6.0

DECOY_CHANCE = 0.4  # hard: chance that a pre-green flash is a fake color
DECOYS: list[RGB] = [(255, 160, 0), (0, 0, 255), (255, 255, 255), (220, 0, 255)]


@dataclass(frozen=True)
class Difficulty:
    green_time: float
    decoys: bool


DIFFICULTIES = {
    "easy": Difficulty(green_time=0.5, decoys=False),
    "hard": Difficulty(green_time=0.3, decoys=True),
}


class FastTap(Game):
    info = GameInfo(
        id="fast_tap",
        name="Fast Tap",
        description="Watch the strip and tap the moment it flashes green. Tap on anything else and you're out!",
        difficulties=[
            Choice("easy", "Easy", "Red flashes only · green lasts 0.5s"),
            Choice("hard", "Hard", "Fake flashes in other colors · green lasts 0.3s"),
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

        self.t = 0.0
        self.status = "playing"
        self.wins = [0] * len(self.players)
        self.losses = 0  # solo only
        self.rounds_played = 0
        self.tiebreak = False
        self.active = set(range(len(self.players)))  # who plays this round
        self.left: set[int] = set()  # closed their browser; out for good
        self.winner: int | None = None
        self.last_round: dict[str, Any] | None = None
        self._start_round()

    @property
    def solo(self) -> bool:
        return len(self.players) == 1

    # --- round flow -----------------------------------------------------------

    def _start_round(self) -> None:
        self.round = self.rounds_played + 1
        self.stage = "intro"
        self.stage_timer = INTRO_TIME
        self.armed_at = float("inf")
        self.out: set[int] = set()
        self.light: RGB | None = None
        self.light_end = 0.0
        self.next_flash_in = 0.0
        self.reds_left = 0
        self.green: tuple[float, float] | None = None  # latest green window (clock time)
        self.green_taps: dict[int, float] = {}  # valid taps in that window
        self.green_decided = True
        self.effect: Confetti | RedFill | None = None

    def update(self, dt: float) -> None:
        self.t += dt
        if self.status != "playing":
            self.effect.update(dt)
            self.finished = self.effect.done
            return

        now = self.clock()
        if self.stage == "intro":
            self.stage_timer -= dt
            if self.stage_timer <= 0:
                self.stage = "armed"
                self.armed_at = now
                self.reds_left = self.rng.randint(*RED_FLASHES)
                self.next_flash_in = self.rng.uniform(*GAP)

        elif self.stage == "armed":
            if self.light and now >= self.light_end:
                self.light = None
            if self.green and not self.green_decided and now >= self.green[1] + GRACE:
                self.green_decided = True
                if self.green_taps:
                    self._round_won(min(self.green_taps, key=self.green_taps.get))
                    return
                # Nobody tapped: more flashes, then green again.
            if self.light is None:
                self.next_flash_in -= dt
                if self.next_flash_in <= 0:
                    self._flash(now)

        elif self.stage == "round_over":
            self.effect.update(dt)
            self.stage_timer -= dt
            if self.stage_timer <= 0:
                self._start_round()

    def _flash(self, now: float) -> None:
        if self.reds_left > 0:
            self.reds_left -= 1
            self.light = RED
            if self.cfg.decoys and self.rng.random() < DECOY_CHANCE:
                self.light = self.rng.choice(DECOYS)
            self.light_end = now + FLASH_TIME
        else:
            self.light = GREEN
            self.light_end = now + self.cfg.green_time
            self.green = (now, self.light_end)
            self.green_taps = {}
            self.green_decided = False
            self.reds_left = self.rng.randint(*RED_FLASHES)  # in case nobody taps
        self.next_flash_in = self.rng.uniform(*GAP)

    def on_input(self, player: str, action: dict[str, Any]) -> None:
        if self.status != "playing" or self.stage != "armed" or not action.get("tap"):
            return
        if player not in self.players:
            return
        idx = self.players.index(player)
        if idx not in self.active or idx in self.out or idx in self.green_taps:
            return  # watching, already out, or a double-tap after a valid tap

        now = self.clock()
        at = action.get("at")
        at = now if not isinstance(at, (int, float)) else min(now, max(now - MAX_TAP_AGE, float(at)))
        if at < self.armed_at:
            return  # tapped during the intro, before the round started

        if self.green and self.green[0] <= at <= self.green[1]:
            if self.green_decided:
                self._round_won(idx, at)  # very late message, but nobody else tapped
            else:
                self.green_taps[idx] = at
            return

        self.out.add(idx)
        if self.active <= self.out:
            self._round_lost()

    def on_leave(self, player: str) -> None:
        if player not in self.players:
            return
        idx = self.players.index(player)
        if idx in self.left:
            return
        self.left.add(idx)
        self.active.discard(idx)
        self.green_taps.pop(idx, None)
        if self.status != "playing":
            return
        present = self._present()
        if len(present) == 1 and not self.solo:
            self._finish(present[0])  # last one standing wins by forfeit
        elif self.tiebreak and len(self.active) == 1:
            self._finish(next(iter(self.active)))  # the other leader left
        elif self.tiebreak and not self.active:
            self.active = set(present)
        elif self.stage == "armed" and self.active <= self.out:
            self._round_lost()  # everyone still here is already out

    def _present(self) -> list[int]:
        return [i for i in range(len(self.players)) if i not in self.left]

    def _round_won(self, idx: int, at: float | None = None) -> None:
        at = self.green_taps.get(idx, at)
        self.wins[idx] += 1
        self.last_round = {"winner": idx, "reaction_ms": round((at - self.green[0]) * 1000)}
        self._end_round(Confetti(self.num_leds, self.colors[idx].led, ROUND_OVER_TIME, self.rng))

    def _round_lost(self) -> None:
        self.losses += 1
        self.last_round = {"winner": None, "reaction_ms": None}
        self._end_round(RedFill(self.num_leds, fill_time=0.5, hold_time=1.5))

    def _end_round(self, effect: Confetti | RedFill) -> None:
        self.rounds_played += 1
        self.light = None
        result = self._game_result()
        if result is None:
            self.stage = "round_over"
            self.stage_timer = ROUND_OVER_TIME
            self.effect = effect
        elif result == "lost":
            self.status = "lost"
            self.effect = RedFill(self.num_leds)
        else:
            self._finish(result)

    def _finish(self, winner: int) -> None:
        self.status = "won"
        self.winner = winner
        self.light = None
        self.effect = Confetti(self.num_leds, self.colors[winner].led, FINAL_TIME, self.rng)

    def _game_result(self) -> int | str | None:
        """Final winner's index, 'lost' (solo), or None to keep playing.
        Sets up a sudden-death round when the leaders are tied at the end."""
        if self.solo:
            if self.wins[0] >= SOLO_WINS_NEEDED:
                return 0
            if self.losses > ROUNDS - SOLO_WINS_NEEDED:
                return "lost"
            return None

        if self.tiebreak:
            return self.last_round["winner"]  # None: everyone out, go again

        # Players who left can't win, whatever their score.
        present = self._present()
        remaining = ROUNDS - self.rounds_played
        ranked = sorted((self.wins[i] for i in present), reverse=True)
        if ranked[0] - ranked[1] > remaining:
            return max(present, key=lambda i: self.wins[i])  # nobody can catch the leader
        if remaining == 0:
            self.tiebreak = True
            self.active = {i for i in present if self.wins[i] == ranked[0]}
        return None

    # --- output ---------------------------------------------------------------

    def render(self, pixels: list[RGB]) -> None:
        if self.status != "playing" or self.stage == "round_over":
            for i in range(self.num_leds):
                pixels[i] = OFF
            self.effect.render(pixels)
        elif self.stage == "intro":
            draw_lineup(pixels, [self.colors[i].led for i in sorted(self.active)], self.t)
        else:
            color = self.light or OFF
            for i in range(self.num_leds):
                pixels[i] = color

    def state(self) -> dict[str, Any]:
        # Never include the current flash: phones must watch the strip.
        return {
            "status": self.status,
            "stage": self.stage,
            "round": self.round,
            "rounds": ROUNDS,
            "tiebreak": self.tiebreak,
            "solo": self.solo,
            "players": [
                {
                    "color": c.name,
                    "hex": c.ui,
                    "wins": self.wins[i],
                    "out": i in self.out,
                    "active": i in self.active,
                    "left": i in self.left,
                }
                for i, c in enumerate(self.colors)
            ],
            "last_round": self.last_round,
            "winner": self.winner,
        }
