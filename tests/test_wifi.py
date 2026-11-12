import asyncio
import tempfile
import unittest
from pathlib import Path

from ledgames import wifi as w
from ledgames.device import Device
from ledgames.wifi import Wifi, parse_scan, signal_dbm, signal_quality, split_terse
from ledgames.wifi_fake import FakeHotspot, FakeNmcli, Profile

DEVICE = Device(id="93d5", hotspot_password="abcdefghjk")


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


async def no_sleep(_):
    await asyncio.sleep(0)


async def settle():
    for _ in range(50):
        await asyncio.sleep(0)


class ParseTest(unittest.TestCase):
    def test_split_terse_handles_escapes(self):
        self.assertEqual(split_terse(r"My\:Net:72:WPA2"), ["My:Net", "72", "WPA2"])
        self.assertEqual(split_terse(r"back\\slash:1:"), ["back\\slash", "1", ""])

    def test_parse_scan(self):
        out = "Home:40:WPA2\nHome:80:WPA2\n:90:WPA2\nCafe:30:\nLED Games 93D5:99:WPA2\nbad line\n"
        nets = parse_scan(out, exclude="LED Games 93D5")
        self.assertEqual([(n.ssid, n.signal, n.secure) for n in nets], [("Home", 80, True), ("Cafe", 30, False)])


WIRELESS = """Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE
 face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22
 wlan0: 0000   58.  -52.  -256        0      0      0    566      0        0
"""


class SignalTest(unittest.TestCase):
    def test_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            stats = Path(tmp) / "wireless"
            self.assertIsNone(signal_dbm(stats=stats))  # no such file
            stats.write_text(WIRELESS)
            self.assertEqual(signal_dbm(stats=stats), -52)
            self.assertIsNone(signal_dbm("wlan1", stats=stats))
            stats.write_text(WIRELESS.splitlines(keepends=True)[0] + WIRELESS.splitlines(keepends=True)[1])
            self.assertIsNone(signal_dbm(stats=stats))  # not connected: no line
        self.assertEqual([signal_quality(d) for d in (-40, -60, -70, -85)], ["excellent", "good", "fair", "weak"])


class WifiTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = Clock()
        self.nm = FakeNmcli(
            visible={
                "Home": (80, "WPA2", "password123"),
                "Cafe": (30, "", ""),
                "Modern": (60, "WPA3", "sae-password"),
            }
        )
        self.hotspot = FakeHotspot(self.nm)
        self.changes = []

    def make(self) -> Wifi:
        wifi = Wifi(DEVICE, run=self.nm, clock=self.clock, sleep=no_sleep, hotspot=self.hotspot)
        wifi.on_change = lambda: self.changes.append(wifi.mode)
        return wifi

    async def boot_into_setup(self) -> Wifi:
        wifi = self.make()
        await wifi.step()
        self.clock.t = w.BOOT_WAIT
        await wifi.step()
        self.assertEqual(wifi.mode, "setup")
        return wifi

    async def test_boot_on_a_saved_network(self):
        self.nm.profiles["home"] = Profile("Home", "password123")
        self.nm.active.add("home")
        wifi = self.make()
        await wifi.step()
        self.assertEqual(wifi.mode, "online")
        self.assertEqual(wifi.ssid, "Home")
        self.assertIsNone(self.nm.ap)

    async def test_no_network_starts_the_hotspot_after_boot_wait(self):
        wifi = self.make()
        await wifi.step()
        self.clock.t = w.BOOT_WAIT - 1
        await wifi.step()
        self.assertEqual(wifi.mode, "starting")
        self.clock.t = w.BOOT_WAIT
        await wifi.step()
        self.assertEqual(wifi.mode, "setup")
        self.assertTrue(wifi.captive)

        self.assertEqual(self.nm.ap, ("LED Games 93D5", "abcdefghjk"))
        self.assertEqual(self.nm.active, set())
        # Scanned before the hotspot went up (it can't scan afterwards).
        self.assertEqual([n.ssid for n in wifi.networks], ["Home", "Modern", "Cafe"])

    async def test_joining_with_the_right_password(self):
        wifi = await self.boot_into_setup()
        self.assertIsNone(wifi.connect("Home", "password123"))
        self.assertEqual(wifi.mode, "connecting")
        await settle()
        self.assertEqual(wifi.mode, "online")
        self.assertEqual(wifi.ssid, "Home")
        self.assertEqual(self.nm.active, {"ledgames: Home"})
        self.assertIsNone(self.nm.ap)
        add = next(c for c in self.nm.calls if c[:3] == ["nmcli", "con", "add"] and "ledgames: Home" in c)
        self.assertIn("connection.autoconnect-priority", add)
        self.assertEqual(self.changes[-2:], ["connecting", "online"])

    async def test_wrong_password_brings_the_hotspot_back(self):
        wifi = await self.boot_into_setup()
        wifi.connect("Home", "wrong-password")
        await settle()
        self.assertEqual(wifi.mode, "setup")
        self.assertIn("Home", wifi.error)
        self.assertIsNotNone(self.nm.ap)
        self.assertNotIn("ledgames: Home", self.nm.profiles)  # no broken profile left behind

        wifi.connect("Home", "password123")  # retry clears the error
        self.assertIsNone(wifi.error)
        await settle()
        self.assertEqual(wifi.mode, "online")

    async def test_open_and_wpa3_networks(self):
        wifi = await self.boot_into_setup()
        wifi.connect("Modern", "sae-password")
        await settle()
        add = next(c for c in self.nm.calls if "ledgames: Modern" in c and c[2] == "add")
        self.assertEqual(add[add.index("wifi-sec.key-mgmt") + 1], "sae")

        self.nm.active.clear()
        self.nm.ap = None
        self.clock.t = 0
        wifi = await self.boot_into_setup()
        wifi.connect("Cafe", "")
        await settle()
        self.assertEqual(wifi.mode, "online")
        add = next(c for c in self.nm.calls if "ledgames: Cafe" in c and c[2] == "add")
        self.assertNotIn("wifi-sec.psk", add)

    async def test_hidden_network_typed_by_hand(self):
        wifi = await self.boot_into_setup()
        wifi.connect("Secret", "password123")
        await settle()
        add = next(c for c in self.nm.calls if "ledgames: Secret" in c and c[2] == "add")
        self.assertIn("802-11-wireless.hidden", add)
        self.assertEqual(wifi.mode, "setup")  # not in range

    async def test_connect_checks_its_input(self):
        wifi = self.make()
        self.assertIsNotNone(wifi.connect("Home", "password123"))  # not in setup mode
        wifi = await self.boot_into_setup()
        self.assertIsNotNone(wifi.connect("", "password123"))
        self.assertIsNotNone(wifi.connect("Home", "short"))
        self.assertIsNotNone(wifi.connect("x" * 33, "password123"))
        self.assertEqual(wifi.mode, "setup")

    async def test_retries_saved_networks_when_nobody_is_setting_up(self):
        # The router was off at boot, so the unit went into setup mode.
        self.nm.profiles["home"] = Profile("Home", "password123")
        router = self.nm.visible.pop("Home")
        wifi = await self.boot_into_setup()
        self.nm.visible["Home"] = router  # router's back

        self.clock.t += w.RETRY_EVERY - 1
        await wifi.step()
        self.assertEqual(wifi.mode, "setup")
        self.clock.t += 1
        await wifi.step()
        self.assertEqual(self.nm.active, {"home"})
        self.assertIsNone(self.nm.ap)
        await wifi.step()
        self.assertEqual(wifi.mode, "online")
        self.assertEqual(wifi.ssid, "Home")

    async def test_no_retry_while_someone_is_on_the_setup_page(self):
        self.nm.profiles["home"] = Profile("Home", "password123")
        wifi = await self.boot_into_setup()
        self.clock.t += w.RETRY_EVERY
        wifi.touch()
        await wifi.step()
        self.assertEqual(wifi.mode, "setup")

    async def test_no_retry_without_saved_networks(self):
        wifi = await self.boot_into_setup()
        self.clock.t += w.RETRY_EVERY + w.SETUP_IDLE
        await wifi.step()
        self.assertEqual(wifi.mode, "setup")

    async def test_losing_the_network_later(self):
        self.nm.profiles["home"] = Profile("Home", "password123")
        self.nm.active.add("home")
        wifi = self.make()
        await wifi.step()
        self.nm.active.clear()
        self.clock.t = 10
        await wifi.step()
        self.clock.t = 10 + w.OFFLINE_WAIT - 1
        await wifi.step()
        self.assertEqual(wifi.mode, "online")  # brief outages don't matter
        self.clock.t = 10 + w.OFFLINE_WAIT
        await wifi.step()
        self.assertEqual(wifi.mode, "setup")

    async def test_change_network_from_the_device_page(self):
        self.nm.profiles["home"] = Profile("Home", "password123")
        self.nm.active.add("home")
        wifi = self.make()
        self.assertIsNotNone(wifi.enter_setup())  # not online yet
        await wifi.step()
        self.assertIsNone(wifi.enter_setup())
        await settle()
        self.assertEqual(wifi.mode, "setup")
        self.assertIn("home", self.nm.profiles)  # kept as a fallback

    async def test_hotspot_that_wont_start(self):
        self.nm.profiles["home"] = Profile("Home", "password123")
        self.hotspot.fail = True
        wifi = self.make()
        await wifi.step()
        self.clock.t = w.BOOT_WAIT
        await wifi.step()
        self.assertEqual(wifi.mode, "starting")  # tries saved networks again first


class HotspotTest(unittest.IsolatedAsyncioTestCase):
    """The real hostapd hotspot's dealings with NetworkManager."""

    def setUp(self):
        self.calls = []
        self.state = "100 (connected)"

    async def run_cmd(self, args):
        self.calls.append(args)
        if args[:3] == ["nmcli", "-g", "GENERAL.STATE"]:
            return 0, self.state + "\n"
        return 0, ""

    async def test_startup_leaves_a_working_connection_alone(self):
        hs = w.Hotspot(run=self.run_cmd)
        await hs.recover()
        await hs.stop()
        self.assertFalse(any(c[0] == "ip" or "managed" in c for c in self.calls))

    async def test_startup_after_a_crash_in_setup_mode(self):
        self.state = "10 (unmanaged)"
        hs = w.Hotspot(run=self.run_cmd)
        await hs.recover()
        self.assertIn(["ip", "addr", "flush", "dev", "wlan0"], self.calls)
        self.assertIn(["nmcli", "dev", "set", "wlan0", "managed", "yes"], self.calls)


if __name__ == "__main__":
    unittest.main()
