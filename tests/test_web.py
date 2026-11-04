import unittest

from aiohttp.test_utils import TestClient, TestServer

from ledgames.device import Device
from ledgames.engine import Engine
from ledgames.leds import make_strip
from ledgames.server import build_app
from ledgames.wifi import Network, Wifi
from ledgames.wifi_fake import FakeHotspot, FakeNmcli

DEVICE = Device(id="93d5", hotspot_password="abcdefghjk")


class WebTest(unittest.IsolatedAsyncioTestCase):
    async def start(self, wifi: Wifi | None = None):
        self.engine = Engine(make_strip("sim", 50, 1.0, 0, 18))
        self.client = TestClient(TestServer(build_app(self.engine, DEVICE if wifi else None, wifi)))
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

    async def test_no_network_change_during_a_game(self):
        wifi = Wifi(DEVICE, run=(nm := FakeNmcli()), hotspot=FakeHotspot(nm))
        wifi.mode = "online"
        await self.start(wifi)
        self.engine.open("fast_tap", "easy", {}, "host")
        r = await self.client.post("/api/device/wifi-setup", json={})
        self.assertEqual(r.status, 409)
        self.assertEqual(wifi.mode, "online")


if __name__ == "__main__":
    unittest.main()
