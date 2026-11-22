import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from ledgames.audio import Microphone
from ledgames.device import Device, load_settings
from ledgames.engine import Engine
from ledgames.leds import make_strip
from ledgames.server import build_app
from ledgames.speaker import Speaker
from ledgames.wifi import Network, Wifi
from ledgames.wifi_fake import FakeHotspot, FakeNmcli

DEVICE = Device(id="93d5", hotspot_password="abcdefghjk")


class WebTest(unittest.IsolatedAsyncioTestCase):
    async def start(self, wifi: Wifi | None = None, state_dir: Path | None = None):
        self.engine = Engine(make_strip("sim", 50, 1.0, 0, 18))
        self.client = TestClient(TestServer(build_app(self.engine, DEVICE if wifi else None, wifi, None, state_dir)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    def setup_wifi(self) -> Wifi:
        wifi = Wifi(DEVICE, run=(nm := FakeNmcli()), hotspot=FakeHotspot(nm))
        wifi.mode = "setup"
        wifi.networks = [Network("Home", 80, "WPA2")]
        return wifi

    async def test_captive_portal_sends_everything_to_setup(self):
        await self.start(self.setup_wifi())
        for path in ("/", "/hotspot-detect.html", "/generate_204", "/api/device"):
            r = await self.client.get(path, allow_redirects=False)
            self.assertEqual(r.status, 302, path)
            self.assertEqual(r.headers["Location"], "/setup")
        r = await self.client.get("/setup")
        self.assertEqual(r.status, 200)
        self.assertIn("Wi-Fi setup", await r.text())

    async def test_setup_api(self):
        await self.start(self.setup_wifi())
        body = await (await self.client.get("/api/setup")).json()
        self.assertEqual(body["mode"], "setup")
        self.assertEqual(body["name"], "LED Games 93D5")
        self.assertEqual(body["local_url"], "http://ledgames.local")
        self.assertEqual(body["networks"], [{"ssid": "Home", "signal": 80, "secure": True}])

        r = await self.client.post("/api/setup/connect", json={"ssid": "Home", "password": "short"})
        self.assertEqual(r.status, 400)
        self.assertIn("8 to 63", (await r.json())["error"])

    async def test_posts_must_be_json(self):
        # A form post from another web site can't trigger these.
        await self.start(self.setup_wifi())
        r = await self.client.post("/api/setup/connect", data={"ssid": "Home", "password": "password123"})
        self.assertEqual(r.status, 415)

    async def test_phones_revalidate_the_ui(self):
        # Otherwise a phone keeps an old app.js after an update.
        await self.start()
        for path in ("/", "/static/app.js", "/static/style.css"):
            r = await self.client.get(path)
            self.assertEqual(r.status, 200, path)
            self.assertEqual(r.headers.get("Cache-Control"), "no-cache", path)

    async def test_home_screen_app(self):
        await self.start()
        page = await (await self.client.get("/")).text()
        self.assertIn('<link rel="manifest" href="/static/manifest.json">', page)
        manifest = await (await self.client.get("/static/manifest.json")).json(content_type=None)
        self.assertEqual(manifest["display"], "standalone")
        paths = {icon["src"] for icon in manifest["icons"]} | {"/static/icons/apple-touch-icon.png"}
        for path in paths:
            r = await self.client.get(path)
            self.assertEqual((r.status, r.content_type), (200, "image/png"), path)

    async def test_no_redirect_when_online(self):
        await self.start()
        r = await self.client.get("/", allow_redirects=False)
        self.assertEqual(r.status, 200)

    async def test_invite(self):
        await self.start()
        body = await (await self.client.get("/api/invite")).json()
        port = self.client.port
        self.assertEqual(body["url"], f"http://127.0.0.1:{port}/")
        r = await self.client.get("/invite.svg")
        self.assertEqual(r.content_type, "image/svg+xml")
        self.assertTrue((await r.text()).startswith("<svg"))

    async def test_device_info(self):
        await self.start()
        body = await (await self.client.get("/api/device")).json()
        self.assertEqual(body["update"]["status"], "off")
        self.assertIsNone(body["wifi"])
        r = await self.client.post("/api/device/wifi-setup", json={})
        self.assertEqual(r.status, 400)

    async def test_signal(self):
        await self.start()
        server = self.client.app["server"]
        with tempfile.TemporaryDirectory() as tmp:
            server.wireless_stats = Path(tmp) / "wireless"
            self.assertIsNone((await (await self.client.get("/api/device")).json())["signal"])
            server.wireless_stats.write_text("header\nheader\n wlan0: 0000   58.  -52.  -256  0 0 0 0 0 0\n")
            body = await (await self.client.get("/api/device")).json()
            self.assertEqual(body["signal"], {"dbm": -52, "quality": "excellent"})

    async def test_no_network_change_during_a_game(self):
        wifi = Wifi(DEVICE, run=(nm := FakeNmcli()), hotspot=FakeHotspot(nm))
        wifi.mode = "online"
        await self.start(wifi)
        self.engine.open("fast_tap", "easy", {}, "host")
        r = await self.client.post("/api/device/wifi-setup", json={})
        self.assertEqual(r.status, 409)
        self.assertEqual(wifi.mode, "online")

    async def test_led_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            await self.start(state_dir=Path(tmp))
            self.assertEqual((await (await self.client.get("/api/device")).json())["leds"], 50)
            for bad in (0, 1001, "80", 80.5, True):
                r = await self.client.post("/api/device/leds", json={"count": bad})
                self.assertEqual(r.status, 400, bad)
            r = await self.client.post("/api/device/leds", json={"count": 80})
            self.assertEqual(r.status, 200)
            self.assertEqual(self.engine.strip.num_leds, 80)
            self.assertEqual(load_settings(Path(tmp)), {"leds": 80})
            self.assertEqual((await (await self.client.get("/api/device")).json())["leds"], 80)

    async def test_switching_to_a_grid_and_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            await self.start(state_dir=Path(tmp))
            ws = await self.client.ws_connect("/ws")
            await ws.send_json({"type": "hello", "clientId": "a"})
            games = await ws.receive_json()
            self.assertEqual(games["layout"], {"kind": "strip", "leds": 50})
            self.assertTrue(games["games"])
            await ws.receive_json()  # session

            grid = {"width": 8, "height": 4, "runs": "columns", "zigzag": True, "start": "top-left", "skip": 0}
            r = await self.client.post("/api/device/layout", json={"layout": "grid", "grid": grid})
            self.assertEqual(r.status, 200)
            self.assertEqual(self.engine.strip.num_leds, 32)
            games = await ws.receive_json()  # the phones hear about it
            self.assertEqual(games["layout"], {"kind": "grid", "width": 8, "height": 4})
            self.assertEqual(games["games"], [])  # no grid games yet
            self.assertEqual(self.engine._pattern[0], "check")  # shows the check pattern
            body = await (await self.client.get("/api/device")).json()
            self.assertEqual((body["layout"], body["grid"], body["leds"]), ("grid", grid, 50))
            self.assertEqual((await (await self.client.get("/api/lights")).json())["effects"], [])
            r = await self.client.post("/api/device/leds", json={"count": 80})
            self.assertEqual(r.status, 409)  # that's the strip's

            r = await self.client.post("/api/device/layout", json={"layout": "strip"})
            self.assertEqual(r.status, 200)
            self.assertEqual(self.engine.strip.num_leds, 50)
            self.assertEqual((await ws.receive_json())["layout"]["kind"], "strip")
            saved = load_settings(Path(tmp))
            self.assertEqual((saved["layout"], saved["grid"]), ("strip", grid))  # the grid is kept
            await ws.close()

    async def test_bad_layouts(self):
        await self.start()
        for body in ({}, {"layout": "ring"}, {"layout": "grid", "grid": {"width": 99}}):
            r = await self.client.post("/api/device/layout", json=body)
            self.assertEqual(r.status, 400, body)
        self.engine.open("fast_tap", "easy", {}, "host")
        r = await self.client.post("/api/device/layout", json={"layout": "grid", "grid": {}})
        self.assertEqual(r.status, 409)
        self.assertEqual(self.engine.layout.kind, "strip")

    async def test_color_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            await self.start(state_dir=Path(tmp))
            self.assertEqual((await (await self.client.get("/api/device")).json())["color_order"], "grb")
            r = await self.client.post("/api/device/color-order", json={"order": "xyz"})
            self.assertEqual(r.status, 400)
            r = await self.client.post("/api/device/color-order", json={"order": "rgb"})
            self.assertEqual(r.status, 200)
            self.assertEqual(self.engine.strip.order, "rgb")
            self.assertEqual(load_settings(Path(tmp))["color_order"], "rgb")

    async def test_patterns(self):
        await self.start()
        r = await self.client.post("/api/device/pattern", json={"pattern": "first"})
        self.assertEqual(r.status, 200)
        self.assertEqual(self.engine._pattern[0], "first")
        r = await self.client.post("/api/device/pattern", json={"pattern": "check"})
        self.assertEqual(r.status, 409)  # only on a grid
        r = await self.client.post("/api/device/pattern", json={"pattern": None})
        self.assertEqual(r.status, 200)
        self.assertIsNone(self.engine._pattern)

    async def test_simulator_pages(self):
        await self.start()
        for path, title in (("/sim", "LED Strip Simulator"), ("/grid", "LED Grid Simulator")):
            r = await self.client.get(path)
            self.assertEqual(r.status, 200, path)
            self.assertIn(f"<title>{title}</title>", await r.text())

    async def test_sim_gets_the_layout(self):
        await self.start()
        ws = await self.client.ws_connect("/ws/sim")
        head = await ws.receive_json()
        self.assertEqual((head["numLeds"], head["layout"]["kind"]), (50, "strip"))
        self.assertEqual(len(await ws.receive_bytes()), 150)
        await ws.close()

    async def test_no_strip_changes_during_a_game(self):
        await self.start()
        self.engine.open("fast_tap", "easy", {}, "host")
        r = await self.client.post("/api/device/leds", json={"count": 80})
        self.assertEqual(r.status, 409)
        self.assertEqual(self.engine.strip.num_leds, 50)
        r = await self.client.post("/api/device/test-leds", json={})
        self.assertEqual(r.status, 409)
        self.engine.stop()
        r = await self.client.post("/api/device/test-leds", json={})
        self.assertEqual(r.status, 200)

    async def test_lights(self):
        with tempfile.TemporaryDirectory() as tmp:
            await self.start(state_dir=Path(tmp))
            body = await (await self.client.get("/api/lights")).json()
            self.assertFalse(body["on"])
            self.assertIn({"id": "fire", "name": "Fire", "sound": False}, body["effects"])
            self.assertFalse(body["mic"])
            self.assertIn({"id": "custom", "name": "Your gradient", "stops": None}, body["palettes"])
            self.assertEqual(len(body["gradient"]), 2)
            r = await self.client.post("/api/lights", json={"on": True, "effect": "fire", "speed": 7})
            self.assertEqual(r.status, 400)
            self.assertFalse(self.engine.lights.on)
            r = await self.client.post("/api/lights", json={"on": True, "effect": "fire"})
            self.assertEqual(r.status, 200)
            self.assertEqual((await r.json())["effect"], "fire")
            self.assertTrue(self.engine.lights.on)
            self.client.app["server"].save_lights()  # normally 2 s after the last change
            self.assertEqual(load_settings(Path(tmp))["lights"]["effect"], "fire")

    async def test_speaker(self):
        with tempfile.TemporaryDirectory() as tmp:
            await self.start(state_dir=Path(tmp))
            self.assertIsNone((await (await self.client.get("/api/device")).json())["speaker"])
            r = await self.client.post("/api/device/speaker", json={"volume": 0.5})
            self.assertEqual(r.status, 409)  # turned off

            speaker = self.engine.speaker = Speaker(device="plughw:1,0")
            played = []
            r = await self.client.post("/api/device/speaker/test", json={})
            self.assertEqual(r.status, 409)  # still starting
            speaker.mixer = type("Mixer", (), {"stop": lambda self: None, "quit": lambda self: None})()
            speaker.play = lambda name, alone=False: played.append((name, alone, speaker.volume)) or True
            body = await (await self.client.get("/api/device")).json()
            self.assertEqual(body["speaker"], {"available": True, "on": True, "volume": 0.5})
            for bad in ({"volume": 2}, {"on": "no"}):
                r = await self.client.post("/api/device/speaker", json=bad)
                self.assertEqual(r.status, 400, bad)
            r = await self.client.post("/api/device/speaker", json={"volume": 0.8})
            self.assertEqual((await r.json())["speaker"]["volume"], 0.8)
            r = await self.client.post("/api/device/speaker/test", json={})
            self.assertEqual(r.status, 200)
            self.assertEqual(played, [("chime", True, 0.8)])  # cuts off any other sound
            await self.client.post("/api/device/speaker", json={"on": False})
            r = await self.client.post("/api/device/speaker/test", json={})
            self.assertEqual(r.status, 409)
            self.client.app["server"].save_speaker()  # normally 2 s after the last change
            self.assertEqual(load_settings(Path(tmp))["speaker"], {"on": False, "volume": 0.8})

    async def test_no_speaker_found(self):
        await self.start()
        self.engine.speaker = Speaker(device=None)
        body = await (await self.client.get("/api/device")).json()
        self.assertFalse(body["speaker"]["available"])
        r = await self.client.post("/api/device/speaker/test", json={})
        self.assertEqual(r.status, 409)

    async def test_mic_sensitivity(self):
        with tempfile.TemporaryDirectory() as tmp:
            await self.start(state_dir=Path(tmp))
            self.assertIsNone((await (await self.client.get("/api/device")).json())["mic"])
            r = await self.client.post("/api/device/mic", json={"sensitivity": 0.5})
            self.assertEqual(r.status, 409)  # no microphone

            self.engine.lights.mic = Microphone("plughw:9,0")  # not listening: the lights are off
            body = await (await self.client.get("/api/device")).json()
            self.assertEqual(body["mic"], {"available": True, "sensitivity": 0.5})
            for bad in (-0.1, 1.5, "0.5", True, None):
                r = await self.client.post("/api/device/mic", json={"sensitivity": bad})
                self.assertEqual(r.status, 400, bad)
            r = await self.client.post("/api/device/mic", json={"sensitivity": 0.8})
            self.assertEqual(r.status, 200)
            self.assertEqual(self.engine.lights.mic.sensitivity, 0.8)
            self.client.app["server"].save_mic()  # normally 2 s after the last change
            self.assertEqual(load_settings(Path(tmp))["mic_sensitivity"], 0.8)


if __name__ == "__main__":
    unittest.main()
