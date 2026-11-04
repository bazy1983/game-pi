import json
import tempfile
import unittest
from pathlib import Path

from ledgames.device import PASSWORD_ALPHABET, Device, load_or_create
from ledgames.provision import sticker_svg


class DeviceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_id_comes_from_the_serial_number(self):
        d = load_or_create(self.dir, serial="0000000087b293d5")
        self.assertEqual(d.id, "93d5")
        self.assertEqual(d.hostname, "ledgames")
        self.assertEqual(d.hotspot_ssid, "LED Games 93D5")
        self.assertEqual(d.local_url, "http://ledgames.local")

    def test_password_is_easy_to_type(self):
        d = load_or_create(self.dir, serial="abcd")
        self.assertEqual(len(d.hotspot_password), 10)
        self.assertTrue(set(d.hotspot_password) <= set(PASSWORD_ALPHABET))

    def test_identity_is_kept(self):
        first = load_or_create(self.dir, serial="1111")
        again = load_or_create(self.dir, serial="2222")
        self.assertEqual(first, again)  # the sticker stays valid
        path = self.dir / "device.json"
        self.assertEqual(json.loads(path.read_text())["id"], "1111")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_random_id_without_a_serial(self):
        d = load_or_create(self.dir, serial="")
        self.assertRegex(d.id, r"^[0-9a-f]{4}$")

    def test_wifi_qr_escapes_special_characters(self):
        d = Device(id="93d5", hotspot_password='a;b:c"d')
        self.assertEqual(d.wifi_qr(), 'WIFI:T:WPA;S:LED Games 93D5;P:a\\;b\\:c\\"d;;')

    def test_sticker(self):
        svg = sticker_svg(Device(id="93d5", hotspot_password="abcdefghjk"))
        self.assertIn("LED Games 93D5", svg)
        self.assertIn("abcdefghjk", svg)
        self.assertIn('width="70mm"', svg)


if __name__ == "__main__":
    unittest.main()
