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

HTTP (JSON):
  GET  /api/setup              Wi-Fi setup page state (nearby networks, errors)
  POST /api/setup/connect      {"ssid", "password"}: join the customer's network
  GET  /api/device             name, version, network, update status
  POST /api/device/update      {"action": "check" | "install"}
  POST /api/device/wifi-setup  start the setup hotspot to change networks
  POST /api/device/leds        {"count": n}: set (and save) the number of LEDs
  POST /api/device/test-leds   play the wiring check pattern on the strip
  POST /api/device/mic         microphone sensitivity, 0–1: {sensitivity}
  GET  /api/lights             ambient lights settings, effects and palettes
  POST /api/lights             change some of those settings (see lights.py)
  GET  /api/invite             {"url", "host_url"}: link other phones can open
  GET  /invite.svg             that link as a QR code

While the unit is running its setup hotspot, every other page redirects to
/setup, so phones show it as soon as they join (a captive portal).
"""

import asyncio
import json
import time
import weakref
from dataclasses import asdict
from pathlib import Path

from aiohttp import WSMsgType, web

from . import __version__, qr, trace
from .colors import RGB
from .device import PRODUCT, Device, load_settings, save_settings
from .effects.ambient import EFFECTS
from .engine import Engine
from .games import GAMES
from .leds import MAX_LEDS
from .leds.sim import SimStrip
from .lights import PALETTES, palette_gradient
from .updater import Updater
from .wifi import Wifi, signal_dbm, signal_quality

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
# A closed browser and a network blip look the same to the server, so a
# player who disconnects is dropped only if they don't reconnect in time.
# Long enough to survive a page reload.
DROP_AFTER = 10
GREEN: RGB = (0, 255, 0)
RED: RGB = (255, 0, 0)


class Server:
    def __init__(
        self,
        engine: Engine,
        device: Device | None = None,
        wifi: Wifi | None = None,
        updater: Updater | None = None,
        state_dir: Path | None = None,
    ):
        self.engine = engine
        self.device = device
        self.wifi = wifi
        self.updater = updater
        self.state_dir = state_dir  # where device page settings are saved (None: not saved)
        self.wireless_stats = Path("/proc/net/wireless")  # the Wi-Fi signal (tests point it elsewhere)
        self._save_lights: asyncio.TimerHandle | None = None
        self._save_mic: asyncio.TimerHandle | None = None
        self.clients: dict[web.WebSocketResponse, str] = {}  # socket → client id
        self.away: dict[str, asyncio.Task] = {}  # client id → pending abandon
        self.last_players: list[str] = []  # for "Play again"
        self._wifi_mode = wifi.mode if wifi else None
        engine.on_change = self.broadcast
        if wifi:
            wifi.on_change = self._status_changed
        if updater:
            updater.on_change = self._status_changed

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
        start = time.monotonic()
        if self.engine.players():
            self.last_players = list(self.engine.players())
        for ws, client_id in list(self.clients.items()):
            asyncio.ensure_future(self._send(ws, self.session_for(client_id)))
        if trace.enabled:
            trace.event("send", clients=len(self.clients), ms=round((time.monotonic() - start) * 1000, 1))

    @staticmethod
    async def _send(ws: web.WebSocketResponse, data: dict) -> None:
        try:
            await ws.send_json(data)
        except (ConnectionError, RuntimeError):
            pass  # client went away; ws_handler cleans up

    async def handle_message(self, ws: web.WebSocketResponse, msg: dict) -> None:
        kind = msg.get("type")
        if trace.enabled and kind in ("input", "ping"):
            action = msg.get("action") if isinstance(msg.get("action"), dict) else {}
            trace.event("msg", type=kind, client=self.clients.get(ws), at=action.get("at"), rtt=msg.get("rtt"))
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

    def _status_changed(self) -> None:
        """Show Wi-Fi setup and updates on the strip."""
        if self.wifi:
            was, now = self._wifi_mode, self.wifi.mode
            self._wifi_mode = now
            if was == "connecting" and now == "online":
                self.engine.flash(GREEN)
            elif was == "connecting" and now == "setup":
                self.engine.flash(RED)
        status = None
        if self.updater and self.updater.status in ("installing", "restarting"):
            status = "updating"
        elif self.wifi and self.wifi.mode in ("setup", "connecting"):
            status = self.wifi.mode
        self.engine.status = status

    def is_idle(self) -> bool:
        """Safe to restart for an update: no game and no Wi-Fi setup."""
        return self.engine.idle and not (self.wifi and self.wifi.captive)

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
        num_leds = None
        try:
            while not ws.closed:
                if strip.num_leds != num_leds:  # also after a change on the device page
                    num_leds = strip.num_leds
                    await ws.send_json({"numLeds": num_leds})
                await ws.send_bytes(strip.frame)
                await asyncio.sleep(1 / self.engine.fps)
        except ConnectionError:
            pass  # viewer closed the page
        return ws


    # --- Wi-Fi setup, device info, invites -------------------------------------

    def device_name(self) -> str:
        return self.device.hotspot_ssid if self.device else f"{PRODUCT} (simulator)"

    async def setup_state(self, _: web.Request) -> web.Response:
        if self.wifi is None:
            return web.json_response({"mode": "online", "name": self.device_name()})
        self.wifi.touch()
        return web.json_response(
            {"name": self.device_name(), "local_url": self.device.local_url, **self.wifi.state()}
        )

    async def setup_connect(self, request: web.Request) -> web.Response:
        body = await _json_body(request)
        if self.wifi is None:
            raise web.HTTPNotFound()
        error = self.wifi.connect(str(body.get("ssid", "")), str(body.get("password", "")))
        return web.json_response({"error": error}, status=400 if error else 200)

    def signal(self) -> dict | None:
        """The unit's Wi-Fi signal, while it's on the customer's network."""
        if self.wifi and self.wifi.mode != "online":
            return None  # running the setup hotspot, or still joining
        dbm = signal_dbm(stats=self.wireless_stats)
        return {"dbm": dbm, "quality": signal_quality(dbm)} if dbm is not None else None

    async def device_state(self, _: web.Request) -> web.Response:
        return web.json_response(
            {
                "name": self.device_name(),
                "local_url": self.device.local_url if self.device else None,
                "version": __version__,
                "leds": self.engine.strip.num_leds,
                "max_leds": MAX_LEDS,
                "mic": self.mic_state(),
                "wifi": {k: v for k, v in self.wifi.state().items() if k != "networks"} if self.wifi else None,
                "signal": self.signal(),
                "update": self.updater.state() if self.updater else {"version": __version__, "status": "off"},
                "busy": self.engine.busy,
            }
        )

    async def device_update(self, request: web.Request) -> web.Response:
        body = await _json_body(request)
        if self.updater is None or self.updater.status == "off":
            return web.json_response({"error": "Updates are off on this unit."}, status=400)
        action = body.get("action")
        if action == "check":
            asyncio.ensure_future(self.updater.check())
        elif action == "install":
            if self.engine.busy:
                return web.json_response({"error": "Wait until the game is over."}, status=409)
            asyncio.ensure_future(self.updater.install())
        return web.json_response({"error": None})

    async def device_wifi_setup(self, request: web.Request) -> web.Response:
        await _json_body(request)
        if self.wifi is None:
            return web.json_response({"error": "Wi-Fi setup is off on this unit."}, status=400)
        if self.engine.busy:
            return web.json_response({"error": "Wait until the game is over."}, status=409)
        error = self.wifi.enter_setup()
        return web.json_response({"error": error}, status=400 if error else 200)

    async def device_leds(self, request: web.Request) -> web.Response:
        body = await _json_body(request)
        count = body.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= MAX_LEDS:
            return web.json_response({"error": f"Enter a number of LEDs from 1 to {MAX_LEDS}."}, status=400)
        if count != self.engine.strip.num_leds:
            error = self.engine.set_led_count(count)
            if error:
                return web.json_response({"error": error}, status=409)
        if self.state_dir:
            settings = load_settings(self.state_dir)
            settings["leds"] = count
            save_settings(settings, self.state_dir)
        self.engine.test_strip()  # shows where the new end is
        return web.json_response({"error": None})

    def mic_state(self) -> dict | None:
        mic = self.engine.lights.mic
        return {"available": mic.available, "sensitivity": mic.sensitivity} if mic else None

    async def device_mic(self, request: web.Request) -> web.Response:
        body = await _json_body(request)
        mic = self.engine.lights.mic
        value = body.get("sensitivity")
        if mic is None:
            return web.json_response({"error": "The microphone is turned off."}, status=409)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
            return web.json_response({"error": "Invalid sensitivity."}, status=400)
        mic.sensitivity = float(value)
        if self.state_dir:
            # The slider sends a stream of changes; write the card once they stop.
            if self._save_mic:
                self._save_mic.cancel()
            self._save_mic = asyncio.get_running_loop().call_later(2, self.save_mic)
        return web.json_response({"error": None, "mic": self.mic_state()})

    def save_mic(self) -> None:
        if self._save_mic:
            self._save_mic.cancel()
            self._save_mic = None
        settings = load_settings(self.state_dir)
        settings["mic_sensitivity"] = self.engine.lights.mic.sensitivity
        save_settings(settings, self.state_dir)

    async def device_test_leds(self, request: web.Request) -> web.Response:
        await _json_body(request)
        error = self.engine.test_strip()
        return web.json_response({"error": error}, status=409 if error else 200)

    def lights_state(self) -> dict:
        lights = self.engine.lights
        return {
            **lights.settings(),
            "effects": [{"id": k, "name": cls.name, "sound": cls.sound} for k, cls in EFFECTS.items()],
            "mic": bool(lights.mic and lights.mic.available),
            "palettes": [{"id": k, "name": p.name, "stops": palette_gradient(p) if p.stops else None} for k, p in PALETTES.items()],
        }

    async def lights_get(self, _: web.Request) -> web.Response:
        return web.json_response(self.lights_state())

    async def lights_post(self, request: web.Request) -> web.Response:
        body = await _json_body(request)
        error = self.engine.lights.update(body)
        if error:
            return web.json_response({"error": error}, status=400)
        if self.state_dir:
            # Sliders send a stream of changes; write the card once they stop.
            if self._save_lights:
                self._save_lights.cancel()
            self._save_lights = asyncio.get_running_loop().call_later(2, self.save_lights)
        return web.json_response({"error": None, **self.lights_state()})

    def save_lights(self) -> None:
        if self._save_lights:
            self._save_lights.cancel()
            self._save_lights = None
        settings = load_settings(self.state_dir)
        settings["lights"] = self.engine.lights.settings()
        save_settings(settings, self.state_dir)

    def invite_urls(self, request: web.Request) -> dict:
        """The unit's address as the asking phone reached it. The IP address
        works on every phone; names ending in .local don't on some Androids."""
        sock = request.transport.get_extra_info("sockname") if request.transport else None
        ip, port = (sock[0], sock[1]) if sock else (request.host, 80)
        ip = ip.removeprefix("::ffff:")
        if ":" in ip:
            ip = f"[{ip}]"
        suffix = "" if port == 80 else f":{port}"
        return {"url": f"http://{ip}{suffix}/", "host_url": f"http://{request.host}/"}

    async def invite(self, request: web.Request) -> web.Response:
        return web.json_response(self.invite_urls(request))

    async def invite_qr(self, request: web.Request) -> web.Response:
        svg = qr.svg(self.invite_urls(request)["url"])
        return web.Response(text=svg, content_type="image/svg+xml", headers={"Cache-Control": "no-store"})


async def _json_body(request: web.Request) -> dict:
    # Requiring a JSON body keeps other web sites from submitting these
    # requests through a visitor's browser (browsers won't send a cross-site
    # JSON POST without the unit's permission, which it never gives).
    if request.content_type != "application/json":
        raise web.HTTPUnsupportedMediaType()
    try:
        body = await request.json()
    except ValueError:
        raise web.HTTPBadRequest() from None
    return body if isinstance(body, dict) else {}


def build_app(
    engine: Engine,
    device: Device | None = None,
    wifi: Wifi | None = None,
    updater: Updater | None = None,
    state_dir: Path | None = None,
) -> web.Application:
    server = Server(engine, device, wifi, updater, state_dir)
    # A real unit's hotspot sends phones to its own address; the simulator
    # stays on whatever address it was opened at.
    setup_url = wifi.hotspot.url if wifi else "/setup"

    @web.middleware
    async def captive_portal(request: web.Request, handler):
        if wifi and wifi.captive and not (
            request.path == "/setup" or request.path.startswith(("/api/setup", "/static/"))
        ):
            raise web.HTTPFound(setup_url)
        return await handler(request)

    @web.middleware
    async def revalidate(request: web.Request, handler):
        # Phones would otherwise keep running an old app.js after an update.
        response = await handler(request)
        if request.path == "/" or request.path.startswith("/static/"):
            response.headers.setdefault("Cache-Control", "no-cache")
        return response

    app = web.Application(middlewares=[captive_portal, revalidate])
    app["sockets"] = weakref.WeakSet()
    app["server"] = server

    async def index(_):
        return web.FileResponse(WEB_DIR / "index.html")

    async def sim(_):
        return web.FileResponse(WEB_DIR / "sim.html")

    async def setup_page(_):
        return web.FileResponse(WEB_DIR / "setup.html", headers={"Cache-Control": "no-store"})

    async def start_engine(app):
        app["tasks"] = [asyncio.create_task(engine.run())]
        if wifi:
            app["tasks"].append(asyncio.create_task(wifi.run()))
        if updater:
            app["tasks"].append(asyncio.create_task(updater.run(server.is_idle)))
        mic = engine.lights.mic
        if mic and mic.available:
            app["tasks"].append(asyncio.create_task(mic.run(lambda: engine.lights.listening)))

    async def shutdown(app):
        if server._save_lights:
            server.save_lights()
        if server._save_mic:
            server.save_mic()
        for task in app["tasks"]:
            task.cancel()
        for ws in set(app["sockets"]):
            await ws.close()
        engine.stop()
        engine.tick(0)  # turn the strip off

    app.router.add_get("/", index)
    app.router.add_get("/ws", server.ws_handler)
    app.router.add_get("/setup", setup_page)
    app.router.add_get("/api/setup", server.setup_state)
    app.router.add_post("/api/setup/connect", server.setup_connect)
    app.router.add_get("/api/device", server.device_state)
    app.router.add_post("/api/device/update", server.device_update)
    app.router.add_post("/api/device/wifi-setup", server.device_wifi_setup)
    app.router.add_post("/api/device/leds", server.device_leds)
    app.router.add_post("/api/device/test-leds", server.device_test_leds)
    app.router.add_post("/api/device/mic", server.device_mic)
    app.router.add_get("/api/lights", server.lights_get)
    app.router.add_post("/api/lights", server.lights_post)
    app.router.add_get("/api/invite", server.invite)
    app.router.add_get("/invite.svg", server.invite_qr)
    if isinstance(engine.strip, SimStrip):
        app.router.add_get("/sim", sim)
        app.router.add_get("/ws/sim", server.sim_handler)
    app.router.add_static("/static", WEB_DIR)
    app.on_startup.append(start_engine)
    app.on_shutdown.append(shutdown)
    return app
