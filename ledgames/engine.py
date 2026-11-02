"""Runs the current game at a fixed frame rate and pushes frames to the strip."""

import asyncio
import time
from collections.abc import Callable
from typing import Any

from .colors import OFF
from .games import GAMES, Game
from .leds import Strip


class Engine:
    def __init__(self, strip: Strip, fps: int = 30):
        self.strip = strip
        self.fps = fps
        self.pixels = [OFF] * strip.num_leds
        self.game: Game | None = None
        self.owner: str | None = None  # client id of the player controlling the game
        self.on_change: Callable[[], None] = lambda: None
        self._last_state: dict[str, Any] | None = None

    # --- commands from the web server ---------------------------------------

    def start(self, game_id: str, difficulty: str, settings: dict[str, str], owner: str) -> str | None:
        """Start a game. Returns an error message, or None on success."""
        if self.playing:
            return "A game is already in progress."
        cls = GAMES.get(game_id)
        if cls is None:
            return "Unknown game."
        info = cls.info
        if difficulty not in {d.id for d in info.difficulties}:
            return "Unknown difficulty."
        clean = {}
        for s in info.settings:
            value = settings.get(s.id, s.default)
            clean[s.id] = value if value in {o.id for o in s.options} else s.default
        self.game = cls(self.strip.num_leds, difficulty, clean)
        self.owner = owner
        self._changed()
        return None

    def input(self, client_id: str, action: dict[str, Any]) -> None:
        if self.playing and client_id == self.owner:
            self.game.on_input(action)

    def stop(self) -> None:
        self.game = None
        self.owner = None
        self._changed()

    # --- state ---------------------------------------------------------------

    @property
    def playing(self) -> bool:
        return self.game is not None and self.game.state()["status"] == "playing"

    def session(self) -> dict[str, Any]:
        if self.game is None:
            return {"phase": "idle"}
        state = self.game.state()
        return {
            "phase": "playing" if state["status"] == "playing" else "ended",
            "game": {"id": self.game.info.id, "name": self.game.info.name},
            "difficulty": self.game.difficulty,
            "owner": self.owner,
            "state": state,
        }

    def _changed(self) -> None:
        state = self.session()
        if state != self._last_state:
            self._last_state = state
            self.on_change()

    # --- loop ----------------------------------------------------------------

    async def run(self) -> None:
        frame_time = 1 / self.fps
        last = time.monotonic()
        while True:
            now = time.monotonic()
            dt = min(now - last, 0.1)  # don't jump ahead after a stall
            last = now
            self.tick(dt)
            await asyncio.sleep(max(0.0, frame_time - (time.monotonic() - now)))

    def tick(self, dt: float) -> None:
        game = self.game
        if game is not None and not game.finished:
            game.update(dt)
            game.render(self.pixels)
        else:
            for i in range(len(self.pixels)):
                self.pixels[i] = OFF
        self.strip.show(self.pixels)
        self._changed()
