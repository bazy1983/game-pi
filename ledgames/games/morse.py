"""Morse Code: read a word the strip flashes in Morse code, 1–6 phones.

The game picks a random word from morse_words.txt. The whole strip flashes
it letter by letter: short pulses are dots, long ones dashes (standard
timing: a dash is 3 dots, 1 dot of dark between pulses, 3 between letters).
At the end of the word the strip flashes blue, then the word plays again.

Players type their guess on the phone. Each has their own attempts; a
wrong guess costs one, and a player with none left is out. The first right
guess wins. If everyone is out, nobody wins.

Hard plays the word only PLAYS times. After the last one, players get
LAST_CHANCE seconds to guess, then everyone left loses.
"""

import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..colors import OFF, RGB, WHITE, GameColor, scale
from ..effects.confetti import Confetti
from ..effects.fireworks import Fireworks
from ..effects.red_fill import RedFill
from .base import Choice, Game, GameInfo

PLAYER_COLORS = [
    GameColor("blue", (0, 0, 255), "#2a5cff"),
    GameColor("yellow", (255, 160, 0), "#ffd21f"),
    GameColor("magenta", (220, 0, 255), "#c43cff"),
    GameColor("cyan", (0, 220, 255), "#22d3ff"),
    GameColor("white", (255, 255, 255), "#f2f4f8"),
    GameColor("orange", (255, 60, 0), "#ff7a1a"),
]

MORSE = {
    "a": ".-", "b": "-...", "c": "-.-.", "d": "-..", "e": ".", "f": "..-.", "g": "--.", "h": "....",
    "i": "..", "j": ".---", "k": "-.-", "l": ".-..", "m": "--", "n": "-.", "o": "---", "p": ".--.",
    "q": "--.-", "r": ".-.", "s": "...", "t": "-", "u": "..-", "v": "...-", "w": ".--", "x": "-..-",
    "y": "-.--", "z": "--..",
}  # fmt: skip

WORDS_FILE = Path(__file__).with_name("morse_words.txt")
INTRO_TIME = 2.0
END_COLOR: RGB = (0, 60, 255)  # the end-of-word flash
END_FLASH = 0.8
END_GAP = 1.5  # dark after the flash, before the word plays again
LAST_CHANCE = 10.0  # hard: seconds to guess after the last playback
LAST_CHANCE_COLOR: RGB = (255, 60, 0)
FINAL_TIME = 6.0


@dataclass(frozen=True)
class Difficulty:
    lengths: tuple[int, ...]  # word lengths
    unit: float  # seconds per dot
    attempts: int
    plays: int | None  # times the word is played; None = until someone gets it


DIFFICULTIES = {
    "easy": Difficulty(lengths=(3,), unit=0.35, attempts=5, plays=None),
    "medium": Difficulty(lengths=(4, 5), unit=0.25, attempts=3, plays=None),
    "hard": Difficulty(lengths=(5, 6), unit=0.18, attempts=2, plays=3),
}


def load_words(path: Path = WORDS_FILE) -> list[str]:
    words = []
    for line in path.read_text().splitlines():
        word = line.strip().lower()
        if word and not word.startswith("#") and word.isalpha() and word.isascii():
            words.append(word)
    return words


WORDS = load_words()


def timeline(word: str, unit: float) -> tuple[list[tuple[float, float, int]], float, float]:
    """One playback of `word`: its pulses as (start, end, letter index), when
    the end-of-word flash starts, and how long the whole playback takes."""
    pulses = []
    t = 0.0
    for i, letter in enumerate(word):
        if i:
            t += 2 * unit  # 3 dots between letters (1 already added after the last pulse)
        for symbol in MORSE[letter]:
            length = unit if symbol == "." else 3 * unit
            pulses.append((t, t + length, i))
            t += length + unit
    flash = t + 2 * unit
    return pulses, flash, flash + END_FLASH + END_GAP


class Morse(Game):
    info = GameInfo(
        id="morse",
        name="Morse Code",
        description="The strip flashes a word in Morse code: short and long pulses. Type it in before you run out of guesses!",
        difficulties=[
            Choice("easy", "Easy", "3-letter words, slow · 5 guesses"),
            Choice("medium", "Medium", "4–5 letters, faster · 3 guesses"),
            Choice("hard", "Hard", "5–6 letters, fast · 2 guesses, the word plays only 3 times"),
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
        words: list[str] | None = None,
        **kwargs,
    ):
        super().__init__(num_leds, difficulty, settings, players, **kwargs)
        self.cfg = DIFFICULTIES[difficulty]
        self.rng = rng or random.Random()
        self.pcolors = PLAYER_COLORS[: len(self.players)]
        choices = [w for w in (words or WORDS) if len(w) in self.cfg.lengths]
        self.word = self.rng.choice(choices)
        self.pulses, self.flash_at, self.play_time = timeline(self.word, self.cfg.unit)

        self.status = "playing"
        self.stage = "intro"  # intro → play → last (hard, after the last playback)
        self.timer = INTRO_TIME  # intro / last: time left; play: time into this playback
        self.play = 0  # playbacks started
        self.attempts = [self.cfg.attempts] * len(self.players)
        self.wrong = [0] * len(self.players)
        self.left: set[int] = set()
        self.winners: list[int] = []
        self.effect: Confetti | Fireworks | RedFill | None = None

    @property
    def solo(self) -> bool:
        return len(self.players) == 1

    def _in(self, idx: int) -> bool:
        """Still guessing: has attempts left and hasn't left."""
        return self.attempts[idx] > 0 and idx not in self.left

    # --- flow -------------------------------------------------------------------

    def update(self, dt: float) -> None:
        if self.status != "playing":
            self.effect.update(dt)
            self.finished = self.effect.done
            return
        if self.stage == "intro":
            self.timer -= dt
            if self.timer <= 0:
                self.stage, self.timer, self.play = "play", 0.0, 1
        elif self.stage == "play":
            self.timer += dt
            if self.timer >= self.play_time:
                if self.cfg.plays is not None and self.play >= self.cfg.plays:
                    self.stage, self.timer = "last", LAST_CHANCE
                else:
                    self.timer -= self.play_time
                    self.play += 1
        elif self.stage == "last":
            self.timer -= dt
            if self.timer <= 0:
                self._lose()

    def on_input(self, player: str, action: dict[str, Any]) -> None:
        if self.status != "playing" or self.stage == "intro" or player not in self.players:
            return
        idx = self.players.index(player)
        guess = action.get("guess")
        if not self._in(idx) or not isinstance(guess, str):
            return
        guess = guess.strip().lower()
        if len(guess) != len(self.word) or not guess.isalpha():
            return  # the phone only sends complete words
        if guess == self.word:
            self._win(idx)
            return
        self.attempts[idx] -= 1
        self.wrong[idx] += 1
        if not any(self._in(i) for i in range(len(self.players))):
            self._lose()

    def on_leave(self, player: str) -> None:
        if player not in self.players:
            return
        self.left.add(self.players.index(player))
        if self.status == "playing" and not any(self._in(i) for i in range(len(self.players))):
            self._lose()  # the others are all out of guesses

    def _win(self, idx: int) -> None:
        self.status = "won"
        self.winners = [idx]
        if self.solo:
            self.effect = Fireworks(self.num_leds, rng=self.rng)
        else:
            self.effect = Confetti(self.num_leds, self.pcolors[idx].led, FINAL_TIME, self.rng)

    def _lose(self) -> None:
        self.status = "lost"
        self.effect = RedFill(self.num_leds)

    # --- output -----------------------------------------------------------------

    def _now(self) -> tuple[bool, int | None]:
        """During playback: whether a pulse is lit, and which letter is playing."""
        t = self.timer
        letter = None
        for start, end, i in self.pulses:
            if t < start:
                break
            letter = i
            if t < end:
                return True, i
        return False, letter if t < self.flash_at else None

    def render(self, pixels: list[RGB]) -> None:
        n = self.num_leds
        if self.status != "playing":
            for i in range(n):
                pixels[i] = OFF
            self.effect.render(pixels)
            return
        color = OFF
        if self.stage == "play":
            lit, _ = self._now()
            since_flash = self.timer - self.flash_at
            if lit:
                color = WHITE
            elif 0 <= since_flash < END_FLASH:
                color = scale(END_COLOR, 1 - since_flash / END_FLASH * 0.7)
        pixels[:] = [color] * n
        if self.stage == "last":  # a bar that drains as time runs out
            bar = round(n * self.timer / LAST_CHANCE)
            pixels[:bar] = [scale(LAST_CHANCE_COLOR, 0.35)] * bar

    def state(self) -> dict[str, Any]:
        # The word is only sent once the game is over: players must read the strip.
        letter = self._now()[1] if self.stage == "play" else None
        return {
            "status": self.status,
            "stage": self.stage,
            "solo": self.solo,
            "length": len(self.word),
            "letter": letter,  # which letter is playing (None between playbacks)
            "play": self.play,
            "plays": self.cfg.plays,
            "last_chance": math.ceil(self.timer) if self.stage == "last" else None,
            "attempts": self.cfg.attempts,
            "players": [
                {
                    "color": c.name,
                    "hex": c.ui,
                    "attempts": self.attempts[i],
                    "wrong": self.wrong[i],
                    "out": self.attempts[i] == 0,
                    "left": i in self.left,
                }
                for i, c in enumerate(self.pcolors)
            ],
            "winners": self.winners,
            "word": self.word if self.status != "playing" else None,
        }
