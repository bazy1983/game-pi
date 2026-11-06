"""Runs the current game at a fixed frame rate and pushes frames to the strip.

Session phases:
  idle     nothing running, strip off
  lobby    a multiplayer game is waiting for players to join
  playing  a game is running
  ended    the game is over (its end animation may still be playing)

The host (the phone that opened the game) is the only one who can start or
quit it. If the host leaves, the next player takes over.
"""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import trace
from .colors import OFF, RGB
from .effects.lineup import draw_lineup
from .effects.status import draw_flash, draw_status
from .effects.strip_test import TEST_TIME, draw_test
from .games import GAMES, Game
from .lights import Lights


@dataclass
class Lobby:
    cls: type[Game]
    difficulty: str
    settings: dict[str, str]
    players: list[str]  # client ids; players[0] is the host


class Engine:
    def __init__(self, strip, fps: int = 30, clock: Callable[[], float] = time.monotonic):
        self.strip = strip
        self.fps = fps
        self.clock = clock
        self.pixels = [OFF] * strip.num_leds
        self.lobby: Lobby | None = None
        self.game: Game | None = None
        self.host: str | None = None
        self.left: set[str] = set()  # players who dropped out of the running game
        self.on_change: Callable[[], None] = lambda: None
        # Shown while no game is running: "setup", "connecting", "updating".
        self.status: str | None = None
        self._flash: tuple[RGB, float, float] | None = None  # color, time left, duration
        self._test: float | None = None  # how far the strip test is
        self.lights = Lights()  # ambient effect while no game is running
        self._last_state: dict[str, Any] | None = None
        self._t = 0.0
        self._shown = 0.0  # when the last frame started going to the strip (for the trace)

    # --- commands from the web server ---------------------------------------

    def open(
        self, game_id: str, difficulty: str, settings: dict[str, str], host: str, players: list[str] = ()
    ) -> str | None:
        """Open a game: single-player games start right away, multiplayer
        games open a lobby. `players` are added to the lobby after the host
        (used by "Play again"). Returns an error message, or None."""
        if self.busy:
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

        self.game = None
        self.host = host
        self.left = set()
        self._test = None
        lobby = Lobby(cls, difficulty, clean, [host])
        if info.max_players == 1:
            self.lobby = lobby
            self.begin(host)
            return None
        for p in players:
            if p not in lobby.players and len(lobby.players) < info.max_players:
                lobby.players.append(p)
        self.lobby = lobby
        self._changed()
        return None

    def join(self, client_id: str) -> str | None:
        lobby = self.lobby
        if lobby is None:
            return "There's no game to join right now."
        if client_id in lobby.players:
            return None
        if len(lobby.players) >= lobby.cls.info.max_players:
            return "This game is full."
        lobby.players.append(client_id)
        self._changed()
        return None

    def drop(self, client_id: str) -> None:
        """A player leaves the lobby or the running game (tapped Leave, or
        closed their browser). The game stops when nobody is left."""
        lobby = self.lobby
        if lobby and client_id in lobby.players:
            lobby.players.remove(client_id)
            if not lobby.players:
                self.stop()
                return
            self.host = lobby.players[0]
            self._changed()
            return

        game = self.game
        if not self.playing or client_id not in game.players or client_id in self.left:
            return
        self.left.add(client_id)
        remaining = [p for p in game.players if p not in self.left]
        if not remaining or game.info.max_players == 1:
            self.stop()
            return
        game.on_leave(client_id)
        if client_id == self.host:
            self.host = remaining[0]
        self._changed()

    def begin(self, client_id: str) -> None:
        """Host starts the game with everyone in the lobby."""
        lobby = self.lobby
        if lobby is None or client_id != self.host:
            return
        self.game = lobby.cls(
            self.strip.num_leds, lobby.difficulty, lobby.settings, players=list(lobby.players), clock=self.clock
        )
        self.lobby = None
        self._changed()

    def input(self, client_id: str, action: dict[str, Any]) -> None:
        if self.playing and client_id in self.game.players and client_id not in self.left:
            self.game.on_input(client_id, action)

    def flash(self, color: RGB, duration: float = 2.0) -> None:
        """Light the whole strip briefly (when no game is running)."""
        self._flash = (color, duration, duration)

    def set_led_count(self, num_leds: int) -> str | None:
        """Change the number of LEDs (from the device page). Returns an error
        message, or None."""
        if not self.idle:
            return "Wait until the game is over."
        self.strip.resize(num_leds)
        self.pixels = [OFF] * num_leds
        return None

    def test_strip(self) -> str | None:
        """Play the wiring check pattern. Returns an error message, or None."""
        if not self.idle:
            return "Wait until the game is over."
        self._test = 0.0
        return None

    def stop(self) -> None:
        self.lobby = None
        self.game = None
        self.host = None
        self.left = set()
        self._changed()

    # --- state ---------------------------------------------------------------

    @property
    def playing(self) -> bool:
        return self.game is not None and self.game.state()["status"] == "playing"

    @property
    def idle(self) -> bool:
        """Nothing open and no end-of-game animation playing."""
        return self.lobby is None and (self.game is None or self.game.finished)

    @property
    def busy(self) -> bool:
        """A lobby is open or a game is running: nobody else can start one."""
        return self.lobby is not None or self.playing

    def players(self) -> list[str]:
        """Everyone who joined, in join order (index = player color)."""
        if self.lobby:
            return self.lobby.players
        return self.game.players if self.game else []

    def player_index(self, client_id: str) -> int | None:
        """This client's player number, or None if they're not (or no
        longer) playing."""
        players = self.players()
        if client_id not in players or client_id in self.left:
            return None
        return players.index(client_id)

    def session(self) -> dict[str, Any]:
        if self.lobby:
            info = self.lobby.cls.info
            return {
                "phase": "lobby",
                "game": {"id": info.id, "name": info.name, "max_players": info.max_players},
                "difficulty": self.lobby.difficulty,
                "players": [{"color": c.name, "hex": c.ui} for c in info.player_colors[: len(self.lobby.players)]],
            }
        if self.game is None:
            return {"phase": "idle"}
        state = self.game.state()
        info = self.game.info
        return {
            "phase": "playing" if state["status"] == "playing" else "ended",
            "game": {"id": info.id, "name": info.name, "max_players": info.max_players},
            "difficulty": self.game.difficulty,
            "state": state,
        }

    def _changed(self) -> None:
        state = (self.session(), self.host, tuple(self.players()), frozenset(self.left))
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
            gap = now - last
            last = now
            self.tick(dt)
            if trace.enabled:
                trace.event(
                    "frame",
                    gap=round(gap * 1000, 1),
                    work=round((self._shown - now) * 1000, 1),
                    show=round((time.monotonic() - self._shown) * 1000, 1),
                )
            await asyncio.sleep(max(0.0, frame_time - (time.monotonic() - now)))

    def tick(self, dt: float) -> None:
        self._t += dt
        level = 0.0  # the lights' brightness, if they're on the strip
        if self._test is not None:
            self._test += dt
            if self._test >= TEST_TIME:
                self._test = None
        game = self.game
        if self.lobby:
            colors = self.lobby.cls.info.player_colors[: len(self.lobby.players)]
            draw_lineup(self.pixels, [c.led for c in colors], self._t)
        elif game is not None and not game.finished:
            game.update(dt)
            game.render(self.pixels)
        elif self._test is not None:
            draw_test(self.pixels, self._test)
        elif self._flash:
            color, left, duration = self._flash
            left -= dt
            self._flash = (color, left, duration) if left > 0 else None
            draw_flash(self.pixels, color, left, duration)
        elif self.status:
            draw_status(self.pixels, self.status, self._t)
        elif self.lights.on:
            level = self.lights.render(self.pixels, dt)
        else:
            for i in range(len(self.pixels)):
                self.pixels[i] = OFF
        if not level:
            self.lights.pause()  # fades back in afterwards
        self._shown = time.monotonic()
        self.strip.show(self.pixels, level or 1.0)
        self._changed()
