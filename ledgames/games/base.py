"""The interface every game implements so the engine and web UI can run it."""

from dataclasses import dataclass, field
from typing import Any

from ..colors import RGB


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


class Game:
    """Base class for games.

    Lifecycle: the engine constructs the game, then calls update(dt) and
    render(pixels) every frame until `finished` is True. A game owns its own
    end-of-game animation (win/lose) and sets `finished` when it's done.
    """

    info: GameInfo

    def __init__(self, num_leds: int, difficulty: str, settings: dict[str, str]):
        self.num_leds = num_leds
        self.difficulty = difficulty
        self.settings = settings
        self.finished = False

    def update(self, dt: float) -> None:
        raise NotImplementedError

    def render(self, pixels: list[RGB]) -> None:
        """Write this frame's colors into `pixels` (index 0 = bottom LED)."""
        raise NotImplementedError

    def on_input(self, action: dict[str, Any]) -> None:
        pass

    def state(self) -> dict[str, Any]:
        """Game state sent to the phones. Must include `status`:
        'playing', 'won' or 'lost'."""
        raise NotImplementedError
