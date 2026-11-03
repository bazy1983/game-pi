"""Web server: serves the phone UI and talks to it over a WebSocket.

Protocol (JSON over /ws):
  client → server
    {"type": "hello", "clientId": "..."}
    {"type": "ping", "t0": <client ms>}            clock sync, any time
    {"type": "start", "game": "...", "difficulty": "...", "settings": {...}, "again": bool}
    {"type": "join"} / {"type": "leave"}           multiplayer lobby
    {"type": "begin"}                              host starts the lobby's game
    {"type": "input", "action": {...}}
    {"type": "stop"}                               host quits
  server → client
    {"type": "games", "games": [...]}              once, after hello
    {"type": "session", "role", "you", "host", ...}  whenever the session changes
    {"type": "pong", "t0": ..., "server": <s>}     server clock (time.monotonic)
    {"type": "error", "message": "..."}

/ws/sim streams raw RGB frames (3 bytes per LED, bottom first) for the
simulator page.
"""

import asyncio
import json
import time
import weakref
from dataclasses import asdict
from pathlib import Path

from aiohttp import WSMsgType, web

from .engine import Engine
from .games import GAMES
from .leds.sim import SimStrip

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
# A closed browser and a network blip look the same to the server, so a
# player who disconnects is dropped only if they don't reconnect in time.
# Long enough to survive a page reload.
DROP_AFTER = 10


class Server:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.clients: dict[web.WebSocketResponse, str] = {}  # socket → client id
        self.away: dict[str, asyncio.Task] = {}  # client id → pending abandon
        self.last_players: list[str] = []  # for "Play again"
        engine.on_change = self.broadcast

    # --- messages --------------------------------------------------------------

    def session_for(self, client_id: str) -> dict:
        session = self.engine.session()
        you = self.engine.player_index(client_id)
        if session["phase"] == "idle":
            role = "none"
        elif you is not None:
            role = "player"
        else:
            role = "spectator"
        return {"type": "session", "role": role, "you": you, "host": client_id == self.engine.host, **session}

    def broadcast(self) -> None:
        if self.engine.players():
            self.last_players = list(self.engine.players())
        for ws, client_id in list(self.clients.items()):
            asyncio.ensure_future(self._send(ws, self.session_for(client_id)))

    @staticmethod
    async def _send(ws: web.WebSocketResponse, data: dict) -> None:
        try:
            await ws.send_json(data)
        except (ConnectionError, RuntimeError):
            pass  # client went away; ws_handler cleans up

    async def handle_message(self, ws: web.WebSocketResponse, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "ping":
            await ws.send_json({"type": "pong", "t0": msg.get("t0"), "server": time.monotonic()})
            return
        if kind == "hello":
            client_id = str(msg.get("clientId", ""))[:64]
            self.clients[ws] = client_id
            task = self.away.pop(client_id, None)
            if task:
                task.cancel()  # reconnected in time
            games = [asdict(cls.info) for cls in GAMES.values()]
            await ws.send_json({"type": "games", "games": games})
            await ws.send_json(self.session_for(client_id))
            return

        client_id = self.clients.get(ws)
        if client_id is None:
            return
        engine = self.engine
        error = None
        if kind == "start":
            players = []
            if msg.get("again"):
                connected = set(self.clients.values())
                players = [p for p in self.last_players if p in connected and p != client_id]
            error = engine.open(
                str(msg.get("game")),
                str(msg.get("difficulty")),
                {str(k): str(v) for k, v in (msg.get("settings") or {}).items()},
                client_id,
                players,
            )
        elif kind == "join":
            error = engine.join(client_id)
        elif kind == "leave":
            engine.drop(client_id)
        elif kind == "begin":
            engine.begin(client_id)
        elif kind == "input":
            engine.input(client_id, msg.get("action") or {})
        elif kind == "stop":
            if client_id == engine.host or not engine.busy:
                engine.stop()
        if error:
            await ws.send_json({"type": "error", "message": error})

    def on_disconnect(self, client_id: str) -> None:
        if client_id in self.clients.values():
            return  # still connected from another tab
        if self.engine.busy and self.engine.player_index(client_id) is not None:
            self.away[client_id] = asyncio.ensure_future(self._drop_later(client_id))

    async def _drop_later(self, client_id: str) -> None:
        await asyncio.sleep(DROP_AFTER)
        self.away.pop(client_id, None)
        if client_id not in self.clients.values():
            self.engine.drop(client_id)

    # --- handlers --------------------------------------------------------------

    async def ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=10)
        await ws.prepare(request)
        request.app["sockets"].add(ws)
        try:
            async for raw in ws:
                if raw.type != WSMsgType.TEXT:
                    continue
                try:
                    msg = json.loads(raw.data)
                except ValueError:
                    continue
                if isinstance(msg, dict):
                    await self.handle_message(ws, msg)
        finally:
            client_id = self.clients.pop(ws, None)
            if client_id is not None:
                self.on_disconnect(client_id)
        return ws

    async def sim_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=10)
        await ws.prepare(request)
        request.app["sockets"].add(ws)
        strip = self.engine.strip
        await ws.send_json({"numLeds": strip.num_leds})
        try:
            while not ws.closed:
                await ws.send_bytes(strip.frame)
                await asyncio.sleep(1 / self.engine.fps)
        except ConnectionError:
            pass  # viewer closed the page
        return ws


def build_app(engine: Engine) -> web.Application:
    server = Server(engine)
    app = web.Application()
    app["sockets"] = weakref.WeakSet()

    async def index(_):
        return web.FileResponse(WEB_DIR / "index.html")

    async def sim(_):
        return web.FileResponse(WEB_DIR / "sim.html")

    async def start_engine(app):
        app["engine_task"] = asyncio.create_task(engine.run())

    async def shutdown(app):
        app["engine_task"].cancel()
        for ws in set(app["sockets"]):
            await ws.close()
        engine.stop()
        engine.tick(0)  # turn the strip off

    app.router.add_get("/", index)
    app.router.add_get("/ws", server.ws_handler)
    if isinstance(engine.strip, SimStrip):
        app.router.add_get("/sim", sim)
        app.router.add_get("/ws/sim", server.sim_handler)
    app.router.add_static("/static", WEB_DIR)
    app.on_startup.append(start_engine)
    app.on_shutdown.append(shutdown)
    return app
