"""Sumo: a tapping tug-of-war for 1 or 2 phones.

Red starts with the bottom quarter of the strip, blue with the top quarter.
Every tap lights one more LED of your color at your front. Once the two
colors meet, a tap pushes the other player back one LED instead. Push them
off the strip (your color fills it) to win. Solo, you're red and the computer
taps for blue at a steady pace set by the difficulty.

Two players on medium or hard get 2 or 3 numbered buttons and must tap them
in order (1, 2, 1, 2… or 1, 2, 3, 1…): only the next button in the sequence
lights an LED, so hammering one button does nothing.
"""

import random
from typing import Any

from ..colors import OFF, RGB, GameColor
from ..effects.confetti import Confetti
from .base import Choice, Game, GameInfo

PLAYER_COLORS = [
    GameColor("red", (255, 0, 0), "#ff2a2a"),  # bottom of the strip
    GameColor("blue", (0, 0, 255), "#2a5cff"),  # top
]

COUNTDOWN = 3.0  # starting positions on the strip; taps don't count yet
FINAL_TIME = 6.0

# Seconds between the computer's taps, solo.
CPU_TAP_EVERY = {"easy": 1 / 3, "medium": 1 / 5, "hard": 1 / 7}
# Buttons to tap in sequence, two players.
BUTTONS = {"easy": 1, "medium": 2, "hard": 3}


class Sumo(Game):
    info = GameInfo(
        id="sumo",
        name="Sumo",
        description="Tap as fast as you can to grow your color and push the other one off the strip!",
        difficulties=[
            Choice("easy", "Easy", "Solo: the computer taps 3 times a second · 2 players: one button"),
            Choice("medium", "Medium", "Solo: the computer taps 5 times a second · 2 players: tap buttons 1, 2 in turn"),
            Choice("hard", "Hard", "Solo: the computer taps 7 times a second · 2 players: tap buttons 1, 2, 3 in turn"),
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
        self.rng = rng or random.Random()
        self.cpu_every = CPU_TAP_EVERY[difficulty]
        self.cpu_timer = self.cpu_every
        self.buttons = 1 if self.solo else BUTTONS[difficulty]
        self.next_button = [0, 0]  # which button each player must tap next
        # LEDs held from each end: lights[0] from the bottom (red),
        # lights[1] from the top (blue).
        start = num_leds // 4
        self.lights = [start, start]
        self.taps = [0, 0]
        self.t = 0.0
        self.countdown = COUNTDOWN
        self.status = "playing"
        self.winner: int | None = None
        self.forfeit = False
        self.effect: Confetti | None = None

    @property
    def solo(self) -> bool:
        return len(self.players) == 1

    @property
    def started(self) -> bool:
        return self.countdown <= 0

    def update(self, dt: float) -> None:
        self.t += dt
        if self.status != "playing":
            self.effect.update(dt)
            self.finished = self.effect.done
            return
        if not self.started:
            self.countdown -= dt
            return
        if self.solo:
            self.cpu_timer -= dt
            while self.cpu_timer <= 0 and self.status == "playing":
                self.cpu_timer += self.cpu_every
                self._push(1)

    def on_input(self, player: str, action: dict[str, Any]) -> None:
        if self.status != "playing" or not self.started or not action.get("tap"):
            return
        if player not in self.players:
            return
        idx = self.players.index(player)
        if action.get("button", 0) != self.next_button[idx]:
            return  # out of sequence
        self.next_button[idx] = (self.next_button[idx] + 1) % self.buttons
        self._push(idx)

    def _push(self, side: int) -> None:
        other = 1 - side
        self.taps[side] += 1
        self.lights[side] += 1
        if sum(self.lights) > self.num_leds:  # the fronts touch: shove
            self.lights[other] -= 1
        if self.lights[other] <= 0:
            self.lights = [0, 0]
            self.lights[side] = self.num_leds
            self._finish(side)

    def on_leave(self, player: str) -> None:
        if self.status == "playing" and player in self.players and not self.solo:
            self.forfeit = True
            self._finish(1 - self.players.index(player))

    def _finish(self, winner: int) -> None:
        self.winner = winner
        self.status = "lost" if self.solo and winner == 1 else "won"
        self.effect = Confetti(self.num_leds, PLAYER_COLORS[winner].led, FINAL_TIME, self.rng)

    # --- output ---------------------------------------------------------------

    def render(self, pixels: list[RGB]) -> None:
        n = self.num_leds
        if self.status != "playing":
            for i in range(n):
                pixels[i] = OFF
            self.effect.render(pixels)
            return
        red, blue = PLAYER_COLORS[0].led, PLAYER_COLORS[1].led
        top = n - self.lights[1]
        for i in range(n):
            pixels[i] = red if i < self.lights[0] else blue if i >= top else OFF

    def state(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "solo": self.solo,
            "countdown": max(0, int(-(-self.countdown // 1))),  # whole seconds left, rounded up
            "leds": self.num_leds,
            "buttons": self.buttons,
            "players": [
                {
                    "color": c.name,
                    "hex": c.ui,
                    "lights": self.lights[i],
                    "taps": self.taps[i],
                    "next": self.next_button[i],
                    "cpu": self.solo and i == 1,
                }
                for i, c in enumerate(PLAYER_COLORS)
            ],
            "winner": self.winner,
            "forfeit": self.forfeit,
        }
