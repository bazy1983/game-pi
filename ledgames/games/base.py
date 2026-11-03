"""The interface every game implements so the engine and web UI can run it."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..colors import RGB, GameColor


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
