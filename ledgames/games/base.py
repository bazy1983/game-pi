"""The interface every game implements so the engine and web UI can run it."""

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..colors import RGB, GameColor
from ..sounds import PACKS


@dataclass
class Choice:
    id: str
    label: str
    description: str = ""


@dataclass
class Setting:
    """A user-selectable option shown before the game starts."""

    id: str
    label: str
    options: list[Choice]
    default: str


# Add to a game's settings to give it sound: it then calls self.play(name)
# with the names in sounds.py's packs.
SOUND_SETTING = Setting(
    "sound",
    "Sound",
    [
        Choice("modern", "Modern", "Smooth sweeps, chimes and chords"),
        Choice("retro", "Retro", "Chunky beeps and buzzes, like an early home game console"),
        Choice("off", "Off", "Play without sound"),
    ],
    default="modern",
)


@dataclass
class GameInfo:
    id: str
    name: str
    description: str
    difficulties: list[Choice]
    default_difficulty: str
    settings: list[Setting] = field(default_factory=list)
    # 1 = single player (others watch). More = the host opens a lobby and up
    # to this many phones join; each gets the next color in player_colors.
    max_players: int = 1
    player_colors: list[GameColor] = field(default_factory=list)
    layout: str = "strip"  # the lights it's played on: "strip" or "grid" (see layout.py)


class Game:
    """Base class for games.

    Lifecycle: the engine constructs the game, then calls update(dt) and
    render(pixels) every frame until `finished` is True. A game owns its own
    end-of-game animation (win/lose) and sets `finished` when it's done.

    `players` are client ids in join order; player i has player_colors[i].
    """

    info: GameInfo

    def __init__(
        self,
        num_leds: int,
        difficulty: str,
        settings: dict[str, str],
        players: list[str] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.num_leds = num_leds
        self.difficulty = difficulty
        self.settings = settings
        self.players = players or []
        self.clock = clock  # same clock the server uses to timestamp messages
        self.finished = False
        self.sounds: list[str] = []  # to play this frame; the engine sends them to the speaker

    def play(self, name: str) -> None:
        """Play a sound from the pack picked in SOUND_SETTING (if any)."""
        pack = self.settings.get("sound")
        if pack in PACKS:
            self.sounds.append(f"{pack}/{name}")

    def count_down(self, before: float, now: float, go: str | None = "go") -> None:
        """Countdown beeps, from the seconds left before and after a frame:
        "count" as each whole second starts, `go` when it runs out. (Play
        "count" once when the countdown starts, for its first second.)"""
        if now <= 0 < before:
            if go:
                self.play(go)
        elif 0 < now and math.ceil(now) < math.ceil(before):
            self.play("count")

    def update(self, dt: float) -> None:
        raise NotImplementedError

    def render(self, pixels: list[RGB]) -> None:
        """Write this frame's colors into `pixels` (index 0 = bottom LED)."""
        raise NotImplementedError

    def on_input(self, player: str, action: dict[str, Any]) -> None:
        pass

    def on_leave(self, player: str) -> None:
        """A player closed their browser mid-game. Called only while at
        least one player is still in; the engine stops the game otherwise."""

    def state(self) -> dict[str, Any]:
        """Game state sent to every phone. Must include `status`:
        'playing', 'won' or 'lost'."""
        raise NotImplementedError
