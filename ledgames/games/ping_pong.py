"""Ping Pong: hit the ball back and forth along the strip, for 1 or 2 phones.

Red's racket is the bottom 3 LEDs, blue's the top 3. A tap swings the racket:
it grows to 6 LEDs over 0.3 s, then shrinks back over 0.3 s, and you can't tap
again until it's back. The ball only bounces off a racket while it's growing;
let it past your end and the other player scores. First to 5 wins.

The ball starts each point at 100 LEDs per second and gets 10% faster every
10 hits. After a point the strip flashes the scorer's color and shows the
score as dots at each end, then the ball is served from the middle toward
whoever lost the point.

Solo, you're red and the computer plays blue: it returns the ball 70%, 80% or
93% of the time depending on the difficulty.

Taps carry the time they happened on the Pi's clock (see Fast Tap), so the
swing starts when the player tapped, not when the message arrived.
"""

import random
from typing import Any

from ..colors import OFF, RGB, WHITE, GameColor, scale
from ..effects.confetti import Confetti
from .base import Choice, Game, GameInfo

PLAYER_COLORS = [
    GameColor("red", (255, 0, 0), "#ff2a2a"),  # bottom of the strip
    GameColor("blue", (0, 0, 255), "#2a5cff"),  # top
]

RACKET = 3  # LEDs at rest
REACH = 6  # LEDs at full swing
EXTEND_TIME = 0.3  # the ball can only be hit during this part of the swing
RETRACT_TIME = 0.3
COOLDOWN = EXTEND_TIME + RETRACT_TIME  # no new swing until the racket is back
MAX_TAP_AGE = 0.15  # how far back a tap's timestamp can start the swing

BALL_SPEED = 100.0  # LEDs per second at the start of each point
SPEEDUP = 1.1  # ×1.1 …
SPEEDUP_EVERY = 10  # … every 10 hits in a point
TRAIL_TIME = 0.04  # the fading trail shows where the ball was this long ago (as Color Shooter's shots)

WIN_SCORE = 5
SERVE_TIME = 1.5  # pause before each serve
FLASH_TIME = 0.5  # the scorer's color fades out over the start of that pause
DOT_SPACING = 2  # score dots: every other LED, starting just past the racket
FINAL_TIME = 6.0

# Solo: chance the computer returns the ball.
CPU_HIT_CHANCE = {"easy": 0.7, "medium": 0.8, "hard": 0.93}
# When the computer means to hit, it swings as the ball comes this many
# seconds' travel from its racket; when it means to miss, much too early.
CPU_HIT_LEAD = 0.1
CPU_MISS_LEAD = 0.45


class PingPong(Game):
    info = GameInfo(
        id="ping_pong",
        name="Ping Pong",
        description="Tap to swing your racket and hit the ball back. Miss it and the other side scores. First to 5!",
        difficulties=[
            Choice("easy", "Easy", "Solo: the computer returns 70% of balls"),
            Choice("medium", "Medium", "Solo: the computer returns 80% of balls"),
            Choice("hard", "Hard", "Solo: the computer returns 93% of balls"),
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
        self.cpu_chance = CPU_HIT_CHANCE[difficulty]
        self.t = 0.0
        self.status = "playing"
        self.scores = [0, 0]
        self.swings = [-COOLDOWN, -COOLDOWN]  # when each racket's last swing started (self.t)
        self.winner: int | None = None
        self.forfeit = False
        self.last_point: int | None = None  # who scored it
        self.effect: Confetti | None = None
        # The ball: position in LEDs from the bottom, direction (+1 up, -1 down).
        self.pos = 0.0
        self.dir = 1
        self.hits = 0  # this point
        self.stage = "serve"  # pause before a serve; "play" while the ball is moving
        self.timer = SERVE_TIME
        self.serve_to = self.rng.randrange(2)
        self.cpu_lead: float | None = None  # computer's plan for the incoming ball

    @property
    def solo(self) -> bool:
        return len(self.players) == 1

    @property
    def speed(self) -> float:
        return BALL_SPEED * SPEEDUP ** (self.hits // SPEEDUP_EVERY)

    # --- rackets --------------------------------------------------------------

    def _age(self, side: int) -> float:
        return self.t - self.swings[side]

    def _extending(self, side: int) -> bool:
        return 0 <= self._age(side) < EXTEND_TIME

    def _length(self, side: int) -> int:
        age = self._age(side)
        if age < 0 or age >= COOLDOWN:
            return RACKET
        if age < EXTEND_TIME:
            grow = age / EXTEND_TIME
        else:
            grow = 1 - (age - EXTEND_TIME) / RETRACT_TIME
        return RACKET + round((REACH - RACKET) * grow)

    def _swing(self, side: int, at: float) -> None:
        if self.t - self.swings[side] >= COOLDOWN:
            self.swings[side] = at

    def _distance(self, side: int) -> float:
        """How far the ball is from this player's end of the strip
        (negative: it got past)."""
        return self.pos if side == 0 else self.num_leds - self.pos

    # --- flow -------------------------------------------------------------------

    def update(self, dt: float) -> None:
        self.t += dt
        if self.status != "playing":
            self.effect.update(dt)
            self.finished = self.effect.done
            return

        if self.stage == "serve":
            self.timer -= dt
            if self.timer <= 0:
                self._serve()
            return

        self.pos += self.dir * self.speed * dt
        side = 0 if self.dir < 0 else 1  # who the ball is heading for
        if self.solo and side == 1:
            self._cpu_play()
        d = self._distance(side)
        if self._extending(side) and d < self._length(side):
            self._hit(side, d)
        elif d < 0:
            self._point(1 - side)

    def _serve(self) -> None:
        self.stage = "play"
        self.pos = self.num_leds / 2
        self.dir = -1 if self.serve_to == 0 else 1
        self.hits = 0
        self._plan_cpu()

    def _hit(self, side: int, d: float) -> None:
        if d < 0:  # it got past between frames: bounce it back in
            self.pos = -d if side == 0 else self.num_leds + d
        self.dir = -self.dir
        self.hits += 1
        self._plan_cpu()

    def _point(self, scorer: int) -> None:
        self.scores[scorer] += 1
        self.last_point = scorer
        if self.scores[scorer] >= WIN_SCORE:
            self._finish(scorer)
            return
        self.stage = "serve"
        self.timer = SERVE_TIME
        self.serve_to = 1 - scorer

    def _plan_cpu(self) -> None:
        """When the ball heads for the computer, decide now whether it returns it."""
        self.cpu_lead = None
        if self.solo and self.dir > 0:
            self.cpu_lead = CPU_HIT_LEAD if self.rng.random() < self.cpu_chance else CPU_MISS_LEAD

    def _cpu_play(self) -> None:
        if self.cpu_lead is None:
            return
        d = self._distance(1)
        if self.cpu_lead == CPU_MISS_LEAD and d < REACH + self.speed * EXTEND_TIME:
            self.cpu_lead = None  # too close to swing early and still miss: don't swing
            return
        # Swing when the ball is this far from the racket.
        if d <= RACKET + self.speed * self.cpu_lead:
            self._swing(1, self.t)
            self.cpu_lead = None

    def on_input(self, player: str, action: dict[str, Any]) -> None:
        if self.status != "playing" or not action.get("tap") or player not in self.players:
            return
        side = self.players.index(player)
        if self.solo and side == 1:
            return
        # Start the swing when they tapped, at most MAX_TAP_AGE ago.
        now = self.clock()
        at = action.get("at")
        back = 0.0 if not isinstance(at, (int, float)) else min(MAX_TAP_AGE, max(0.0, now - float(at)))
        self._swing(side, self.t - back)

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
        for i in range(n):
            pixels[i] = OFF
        if self.status != "playing":
            self.effect.render(pixels)
            return

        if self.stage == "serve":
            # Flash the scorer's color, then the score as dots at each end.
            since = SERVE_TIME - self.timer
            if self.last_point is not None and since < FLASH_TIME:
                color = scale(PLAYER_COLORS[self.last_point].led, 0.6 * (1 - since / FLASH_TIME))
                for i in range(n):
                    pixels[i] = color
            for side in (0, 1):
                for k in range(self.scores[side]):
                    i = REACH + 1 + k * DOT_SPACING
                    pixels[i if side == 0 else n - 1 - i] = PLAYER_COLORS[side].led

        for side in (0, 1):
            color = PLAYER_COLORS[side].led
            for k in range(self._length(side)):
                pixels[k if side == 0 else n - 1 - k] = color

        if self.stage == "play":
            # The ball moves several LEDs per frame: a fading trail behind it
            # keeps the motion smooth instead of a jumping dot.
            head = int(self.pos)
            trail = max(1, round(self.speed * TRAIL_TIME))
            for k in range(trail, -1, -1):
                i = head - k * self.dir
                if 0 <= i < n and (k == 0 or pixels[i] == OFF):
                    pixels[i] = scale(WHITE, (1 - k / (trail + 1)) ** 2)

    def state(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "solo": self.solo,
            "stage": self.stage,
            "target": WIN_SCORE,
            "cooldown": COOLDOWN,
            "last_point": self.last_point,
            "players": [
                {"color": c.name, "hex": c.ui, "score": self.scores[i], "cpu": self.solo and i == 1}
                for i, c in enumerate(PLAYER_COLORS)
            ],
            "winner": self.winner,
            "forfeit": self.forfeit,
        }
