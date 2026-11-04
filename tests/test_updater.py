import asyncio
import base64
import io
import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ledgames import updater as u
from ledgames.updater import Updater, load_public_key, parse_version

API = "https://example.test/releases/latest"


def make_tar(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def release_files(version: str) -> dict[str, str]:
    return {"ledgames/__init__.py": f'__version__ = "{version}"\n', "web/index.html": "<html></html>"}


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class Stop(Exception):
    pass


class UpdaterTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "releases" / "0.2.0").mkdir(parents=True)
        (self.root / "releases" / "0.1.0").mkdir()
        os.symlink("releases/0.2.0", self.root / "current")
        os.symlink("releases/0.1.0", self.root / "previous")

        self.key = Ed25519PrivateKey.generate()
        self.pub = self.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.files: dict[str, bytes] = {}
        self.restarts = 0
        self.clock = Clock()

    def tearDown(self):
        self.tmp.cleanup()

    def publish(self, version: str, data: bytes | None = None, sig: bytes | None = None, assets: bool = True):
        data = data if data is not None else make_tar(release_files(version))
        name = f"ledgames-{version}.tar.gz"
        self.files[f"https://dl.test/{name}"] = data
        self.files[f"https://dl.test/{name}.sig"] = sig if sig is not None else self.key.sign(data)
        listed = [name, name + ".sig"] if assets else [name]
        release = {
            "tag_name": f"v{version}",
            "assets": [{"name": n, "browser_download_url": f"https://dl.test/{n}"} for n in listed],
        }
        self.files[API] = json.dumps(release).encode()

    async def fetch(self, url: str) -> bytes:
        if url not in self.files:
            raise OSError("not found")
        return self.files[url]

    def restart(self):
        self.restarts += 1

    def make(self, root: Path | None = None, **kw) -> Updater:
        return Updater(
            root if root is not None else self.root,
            "0.2.0",
            self.pub,
            fetch=self.fetch,
            restart=self.restart,
            url=API,
            clock=self.clock,
            **kw,
        )

    def current(self) -> str:
        return os.readlink(self.root / "current")

    def test_parse_version(self):
        self.assertEqual(parse_version("v1.10.2"), (1, 10, 2))
        self.assertGreater(parse_version("0.10.0"), parse_version("0.9.9"))
        self.assertIsNone(parse_version("latest"))

    def test_bundled_public_key_loads(self):
        self.assertEqual(len(load_public_key()), 32)

    async def test_check_finds_a_newer_release(self):
        self.publish("0.3.0")
        up = self.make()
        await up.check()
        self.assertEqual(up.status, "available")
        self.assertEqual(up.latest, "0.3.0")

    async def test_check_ignores_older_or_incomplete_releases(self):
        up = self.make()
        self.publish("0.2.0")
        await up.check()
        self.assertEqual(up.status, "up_to_date")
        self.publish("0.1.5")
        await up.check()
        self.assertEqual(up.status, "up_to_date")
        self.publish("0.3.0", assets=False)  # no signature attached
        await up.check()
        self.assertEqual(up.status, "up_to_date")

    async def test_no_releases_published_yet(self):
        class NotFound(Exception):
            status = 404

        async def fetch(url):
            raise NotFound()

        up = self.make()
        up.fetch = fetch
        await up.check()
        self.assertEqual(up.status, "up_to_date")

    async def test_check_offline(self):
        up = self.make()
        await up.check()
        self.assertEqual(up.status, "error")

    async def test_install(self):
        self.publish("0.3.0")
        up = self.make()
        await up.check()
        await up.install()
        self.assertEqual(up.status, "restarting")
        self.assertEqual(self.restarts, 1)
        self.assertEqual(self.current(), "releases/0.3.0")
        self.assertEqual(os.readlink(self.root / "previous"), "releases/0.2.0")
        self.assertTrue((self.root / "releases/0.3.0/web/index.html").exists())
        # Only the running and previous releases are kept.
        self.assertEqual(sorted(p.name for p in (self.root / "releases").iterdir()), ["0.2.0", "0.3.0"])

    async def test_bad_signature_is_refused(self):
        other = Ed25519PrivateKey.generate()
        data = make_tar(release_files("0.3.0"))
        self.publish("0.3.0", data=data, sig=other.sign(data))
        up = self.make()
        await up.check()
        await up.install()
        self.assertEqual(up.status, "error")
        self.assertIn("security check", up.error)
        self.assertEqual(self.current(), "releases/0.2.0")
        self.assertEqual(self.restarts, 0)
        self.assertFalse((self.root / "releases/0.3.0").exists())

    async def test_wrong_version_inside_is_refused(self):
        self.publish("0.3.0", data=make_tar(release_files("0.2.5")))
        up = self.make()
        await up.check()
        await up.install()
        self.assertEqual(up.status, "error")
        self.assertEqual(self.current(), "releases/0.2.0")

    async def test_files_outside_the_release_are_refused(self):
        files = release_files("0.3.0") | {"../../evil.txt": "x"}
        self.publish("0.3.0", data=make_tar(files))
        up = self.make()
        await up.check()
        await up.install()
        self.assertEqual(up.status, "error")
        self.assertFalse((self.root.parent / "evil.txt").exists())
        self.assertEqual(self.current(), "releases/0.2.0")

    async def test_development_checkouts_never_update(self):
        up = Updater(None, "0.2.0", self.pub, fetch=self.fetch)
        self.publish("0.3.0")
        await up.check()
        self.assertEqual(up.status, "off")

    async def test_auto_install_waits_until_nobody_is_playing(self):
        self.publish("0.3.0")
        idle = {"value": False}
        sleeps = []

        async def sleep(seconds):
            sleeps.append(seconds)
            self.clock.t += seconds
            if self.restarts or len(sleeps) > 200:
                raise Stop
            await asyncio.sleep(0)

        up = self.make(sleep=sleep)
        task = asyncio.ensure_future(up.run(lambda: idle["value"]))
        while self.clock.t < u.HEALTHY_AFTER + 5 * u.POLL:
            await asyncio.sleep(0)
        self.assertEqual((self.root / "confirmed").read_text(), "0.2.0\n")
        self.assertEqual(up.status, "available")
        self.assertEqual(self.restarts, 0)  # a game is on

        idle["value"] = True
        idle_from = self.clock.t
        with self.assertRaises(Stop):
            await task
        self.assertEqual(self.restarts, 1)
        self.assertGreaterEqual(self.clock.t - idle_from, u.IDLE_BEFORE_INSTALL)

    async def test_rolled_back_version_is_not_reinstalled(self):
        self.publish("0.3.0")
        (self.root / "failed").write_text("0.3.0\n")
        calls = []

        async def sleep(seconds):
            calls.append(seconds)
            self.clock.t += seconds
            if len(calls) > 100:
                raise Stop
            await asyncio.sleep(0)

        up = self.make(sleep=sleep)
        with self.assertRaises(Stop):
            await up.run(lambda: True)
        self.assertEqual(self.restarts, 0)
        self.assertEqual(up.status, "available")  # still shown; installable by hand


class DownloadTest(unittest.IsolatedAsyncioTestCase):
    async def test_downloads_the_whole_file(self):
        from aiohttp import web
        from aiohttp.test_utils import TestServer

        payload = os.urandom(3 * 1024 * 1024)  # arrives in many chunks

        async def handler(_):
            return web.Response(body=payload)

        app = web.Application()
        app.router.add_get("/big", handler)
        async with TestServer(app) as server:
            data = await u.http_get(str(server.make_url("/big")))
        self.assertEqual(data, payload)


class KeyFileTest(unittest.TestCase):
    def test_public_key_file_format(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "k.pub"
            p.write_text(base64.b64encode(b"\1" * 32).decode() + "\n")
            self.assertEqual(load_public_key(p), b"\1" * 32)


if __name__ == "__main__":
    unittest.main()
