"""Color Shooter: a colored snake creeps down from the top of the strip toward
the white shooter at the bottom. Shoot matching colors at its head to eat it.

Strip layout (index 0 = bottom):

    [0..2]            shooter (white)
    [3..head-1]       empty space where shots travel
    [head..n-1]       snake; snake[0] is the head (bottom), snake[-1] the top

New snake segments enter at the top and push the whole snake down by one LED,
so the head only ever moves down when the snake grows.
"""

import random
from dataclasses import dataclass
from typing import Any

from ..colors import OFF, PALETTE, RGB, WHITE, GameColor, scale
from ..effects.fireworks import Fireworks
from ..effects.red_fill import RedFill
from .base import Choice, Game, GameInfo, Setting

SHOOTER_SIZE = 3
INITIAL_FILL = 0.15  # fraction of the strip covered by the snake at start
SHOT_TRAVEL_TIME = 2.0  # seconds for a shot to cross the whole strip
SHOT_TAIL_TIME = 0.04  # the fading tail shows where the shot was this long ago
COOLDOWN = 0.3  # seconds between shots when fire mode is "cooldown"

# Insane mode: the snake shows white, then flashes its real colors briefly.
BLINK_HIDDEN = 2.0
BLINK_SHOWN = 0.3


@dataclass(frozen=True)
class Difficulty:
    colors: int
    spawn_interval: float
    goal: int
    blink: bool = False


DIFFICULTIES = {
    "easy": Difficulty(colors=3, spawn_interval=2.5, goal=100),
    "normal": Difficulty(colors=4, spawn_interval=2.0, goal=150),
    "hard": Difficulty(colors=5, spawn_interval=1.5, goal=200),
    "insane": Difficulty(colors=5, spawn_interval=1.5, goal=250, blink=True),
}


@dataclass
class Shot:
    pos: float
    color: GameColor


class ColorShooter(Game):
    info = GameInfo(
        id="color_shooter",
        name="Color Shooter",
        description="Shoot matching colors at the snake before it reaches you.",
        difficulties=[
            Choice("easy", "Easy", "3 colors · slow snake · 100 points"),
            Choice("normal", "Normal", "4 colors · 150 points"),
            Choice("hard", "Hard", "5 colors · fast snake · 200 points"),
            Choice("insane", "Insane", "The snake hides its colors · 250 points"),
        ],
        default_difficulty="normal",
        settings=[
            Setting(
                "fire_mode",
                "Fire mode",
                [
                    Choice("rapid", "Rapid fire", "Shoot as fast as you can tap"),
                    Choice("cooldown", "Cooldown", f"{COOLDOWN:g}s between shots"),
                ],
                default="rapid",
            )
        ],
    )

    def __init__(
        self,
        num_leds: int,
        difficulty: str,
        settings: dict[str, str],
        rng: random.Random | None = None,
    ):
        super().__init__(num_leds, difficulty, settings)
        self.cfg = DIFFICULTIES[difficulty]
        self.colors = PALETTE[: self.cfg.colors]
        self.cooldown = COOLDOWN if settings.get("fire_mode") == "cooldown" else 0.0
        self.rng = rng or random.Random()
        self.shot_speed = num_leds / SHOT_TRAVEL_TIME  # LEDs per second

        self.t = 0.0
        self.score = 0
        self.status = "playing"
        self.shots: list[Shot] = []
        self.last_fire = -1e9
        self.spawn_timer = 0.0
        self.effect: Fireworks | RedFill | None = None

        start_len = max(1, round(num_leds * INITIAL_FILL))
        self.snake: list[GameColor] = [self._random_color() for _ in range(start_len)]

    # --- geometry -----------------------------------------------------------

    @property
    def head(self) -> int:
        """LED index of the snake's bottom segment (== num_leds if empty)."""
        return self.num_leds - len(self.snake)

    @property
    def max_length(self) -> int:
        """Longest the snake can be without touching the shooter."""
        return self.num_leds - SHOOTER_SIZE

    # --- game loop ----------------------------------------------------------

    def update(self, dt: float) -> None:
        self.t += dt
        if self.status != "playing":
            if self.effect:
                self.effect.update(dt)
                self.finished = self.effect.done
            return

        self.spawn_timer += dt
        while self.spawn_timer >= self.cfg.spawn_interval:
            self.spawn_timer -= self.cfg.spawn_interval
            self.snake.append(self._random_color())
            if self._check_lost():
                return

        # Move shots highest-first so a shot that grows the snake is resolved
        # before the shots behind it.
        self.shots.sort(key=lambda s: s.pos, reverse=True)
        for shot in self.shots[:]:
            shot.pos += self.shot_speed * dt
            if self.snake and int(shot.pos) >= self.head:
                self.shots.remove(shot)
                self._hit(shot)
                if self.status != "playing":
                    return
            elif shot.pos >= self.num_leds:
                self.shots.remove(shot)  # flew off the top of an empty strip

    def _hit(self, shot: Shot) -> None:
        if shot.color == self.snake[0]:
            self.snake.pop(0)
            self.score += 1
            if self.score >= self.cfg.goal:
                self.status = "won"
                self.shots.clear()
                self.effect = Fireworks(self.num_leds, rng=self.rng)
        else:
            self.snake.insert(0, shot.color)
            self.score -= 1
            self._check_lost()

    def _check_lost(self) -> bool:
        if len(self.snake) <= self.max_length:
            return False
        self.snake = self.snake[: self.max_length]
        self.status = "lost"
        self.shots.clear()
        self.effect = RedFill(self.num_leds)
        return True

    def on_input(self, action: dict[str, Any]) -> None:
        if self.status != "playing":
            return
        color = next((c for c in self.colors if c.name == action.get("fire")), None)
        if color is None or self.t - self.last_fire < self.cooldown:
            return
        self.last_fire = self.t
        self.shots.append(Shot(float(SHOOTER_SIZE), color))

    def _random_color(self) -> GameColor:
        return self.rng.choice(self.colors)

    # --- output -------------------------------------------------------------

    def _snake_hidden(self) -> bool:
        if not self.cfg.blink or self.status != "playing":
            return False
        return self.t % (BLINK_HIDDEN + BLINK_SHOWN) < BLINK_HIDDEN

    def render(self, pixels: list[RGB]) -> None:
        if isinstance(self.effect, Fireworks):
            self.effect.render(pixels)
            return

        for i in range(self.num_leds):
            pixels[i] = OFF
        for i in range(SHOOTER_SIZE):
            pixels[i] = WHITE

        hidden = self._snake_hidden()
        head = self.head
        for k, color in enumerate(self.snake):
            pixels[head + k] = WHITE if hidden else color.led

        # Shots move several LEDs per frame, so draw a fading tail behind
        # each one to keep the motion smooth instead of a jumping dot.
        tail = max(1, round(self.shot_speed * SHOT_TAIL_TIME))
        for shot in self.shots:
            top = int(shot.pos)
            for k in range(tail + 1):
                i = top - k
                if SHOOTER_SIZE <= i < head and pixels[i] == OFF:
                    pixels[i] = scale(shot.color.led, (1 - k / (tail + 1)) ** 2)

        if self.effect:
            self.effect.render(pixels)

    def state(self) -> dict[str, Any]:
        space = max(1, self.max_length - round(self.num_leds * INITIAL_FILL))
        return {
            "status": self.status,
            "score": self.score,
            "goal": self.cfg.goal,
            "colors": [{"name": c.name, "hex": c.ui} for c in self.colors],
            "cooldown": self.cooldown,
            # 0 = snake at its starting length, 1 = touching the shooter.
            "danger": round(max(0.0, min(1.0, 1 - (self.max_length - len(self.snake)) / space)), 2),
        }
