"""Over-the-air updates from GitHub Releases.

Install layout on a unit:
  /opt/ledgames/
    .venv/                      Python environment, shared by all releases
    releases/0.3.0/             one directory per release
    current -> releases/0.3.0   what the service runs
    previous -> releases/0.2.0  where rollback.sh goes back to
    confirmed                   newest version that ran healthily
    failed                      version that was rolled back; never auto-installed again
    rollback.sh                 run by systemd when the service keeps crashing

A release is ledgames-<version>.tar.gz plus ledgames-<version>.tar.gz.sig,
an Ed25519 signature made with the release key (tools/release.py). Units
only install releases signed with that key; its public half is
release_key.pub in this package.

Updates carry code only. A release that needs new system packages has to be
installed by hand.
"""

import asyncio
import base64
import io
import json
import logging
import os
import shutil
import subprocess
import tarfile
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

log = logging.getLogger(__name__)

RELEASES_URL = "https://api.github.com/repos/bazy1983/game-pi/releases/latest"
PUBLIC_KEY_FILE = Path(__file__).with_name("release_key.pub")
HEALTHY_AFTER = 60  # a new release that runs this long is kept
CHECK_EVERY = 6 * 3600
RETRY_AFTER_ERROR = 30 * 60
IDLE_BEFORE_INSTALL = 10 * 60  # don't restart on people about to play
POLL = 30
MAX_DOWNLOAD = 20 * 1024 * 1024

Fetch = Callable[[str], Awaitable[bytes]]


def parse_version(s: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(p) for p in s.strip().removeprefix("v").split("."))
    except ValueError:
        return None


RELEASE_DIR = Path(__file__).resolve().parent.parent


def install_root() -> Path | None:
    """/opt/ledgames when running from an installed release, else None
    (a development checkout, which never updates itself)."""
    return RELEASE_DIR.parent.parent if RELEASE_DIR.parent.name == "releases" else None


def load_public_key(path: Path = PUBLIC_KEY_FILE) -> bytes:
    return base64.b64decode(path.read_text().strip())


async def http_get(url: str) -> bytes:
    import aiohttp  # only needed on a unit that's online

    timeout = aiohttp.ClientTimeout(total=120)
    headers = {"User-Agent": "ledgames-updater", "Accept": "application/vnd.github+json, */*"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            data = bytearray()
            async for chunk in resp.content.iter_chunked(64 * 1024):
                data += chunk
                if len(data) > MAX_DOWNLOAD:
                    raise ValueError("download too large")
            return bytes(data)


def restart_service() -> None:
    # --no-block: systemd stops this process after we return.
    subprocess.Popen(["systemctl", "restart", "--no-block", "ledgames"])


class Updater:
    def __init__(
        self,
        root: Path | None,
        version: str,
        public_key: bytes,
        fetch: Fetch = http_get,
        restart: Callable[[], None] = restart_service,
        url: str = RELEASES_URL,
        auto: bool = True,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        release: str | None = None,
    ):
        self.root = root
        self.version = version
        self.release = release or version  # directory name under releases/
        self.key = Ed25519PublicKey.from_public_bytes(public_key)
        self.fetch = fetch
        self.restart = restart
        self.url = url
        self.auto = auto
        self.clock = clock
        self.sleep = sleep
        self.on_change: Callable[[], None] = lambda: None

        self.status = "idle" if root else "off"
        self.latest: str | None = None
        self.error: str | None = None
        self._assets: dict[str, str] = {}

    def state(self) -> dict:
        return {
            "version": self.version,
            "status": self.status,
            "latest": self.latest,
            "auto": self.auto,
            "error": self.error,
        }

    def _set(self, status: str, error: str | None = None) -> None:
        self.status = status
        self.error = error
        self.on_change()

    # --- background loop -------------------------------------------------------

    async def run(self, is_idle: Callable[[], bool]) -> None:
        if self.root is None:
            return
        await self.sleep(HEALTHY_AFTER)
        self.confirm()
        next_check = self.clock()
        idle_since = None
        while True:
            now = self.clock()
            if now >= next_check:
                await self.check()
                next_check = now + (RETRY_AFTER_ERROR if self.status == "error" else CHECK_EVERY)
            if self.auto and self.status == "available" and self.latest != self.failed_version():
                if not is_idle():
                    idle_since = None
                elif idle_since is None:
                    idle_since = now
                elif now - idle_since >= IDLE_BEFORE_INSTALL:
                    await self.install()
            await self.sleep(POLL)

    # --- steps -------------------------------------------------------------------

    async def check(self) -> None:
        if self.root is None or self.status == "installing":
            return
        self._set("checking")
        try:
            release = json.loads(await self.fetch(self.url))
            latest = str(release["tag_name"]).removeprefix("v")
            assets = {a["name"]: a["browser_download_url"] for a in release.get("assets", [])}
        except Exception as e:
            if getattr(e, "status", None) == 404:  # nothing published yet
                self.latest = None
                self._set("up_to_date")
                return
            log.warning("update check failed: %s", e)
            self._set("error", "Couldn't reach the update server.")
            return
        mine, theirs = parse_version(self.version), parse_version(latest)
        name = f"ledgames-{latest}.tar.gz"
        if theirs and mine and theirs > mine and name in assets and name + ".sig" in assets:
            self.latest = latest
            self._assets = {"tar": assets[name], "sig": assets[name + ".sig"]}
            self._set("available")
        else:
            self.latest = None
            self._set("up_to_date")

    async def install(self) -> None:
        if self.status != "available" or self.latest is None:
            return
        version = self.latest
        self._set("installing")
        try:
            data = await self.fetch(self._assets["tar"])
            sig = await self.fetch(self._assets["sig"])
            self.key.verify(sig, data)
            self.unpack(version, data)
            self.activate(version)
        except InvalidSignature:
            log.error("update %s has a bad signature", version)
            self._set("error", "The update failed its security check and wasn't installed.")
            return
        except Exception as e:
            log.exception("update %s failed", version)
            self._set("error", f"The update couldn't be installed ({e}).")
            return
        log.info("installed %s, restarting", version)
        self._set("restarting")
        self.restart()

    def unpack(self, version: str, data: bytes) -> Path:
        releases = self.root / "releases"
        releases.mkdir(parents=True, exist_ok=True)
        tmp = releases / f".{version}.tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            tar.extractall(tmp, filter="data")  # refuses paths outside tmp
        init = tmp / "ledgames" / "__init__.py"
        if not init.exists() or f'__version__ = "{version}"' not in init.read_text():
            shutil.rmtree(tmp, ignore_errors=True)
            raise ValueError("the download doesn't contain this version")
        dest = releases / version
        if dest.resolve() == (self.root / "current").resolve():
            shutil.rmtree(tmp, ignore_errors=True)
            raise ValueError("this version is already running")
        shutil.rmtree(dest, ignore_errors=True)
        tmp.rename(dest)
        return dest

    def activate(self, version: str) -> None:
        """Point `current` at the new release, keep the old one as
        `previous`, and delete anything older."""
        current = self.root / "current"
        if current.is_symlink():
            _symlink(self.root / "previous", os.readlink(current))
        _symlink(current, f"releases/{version}")
        keep = {(self.root / link).resolve() for link in ("current", "previous")}
        for d in (self.root / "releases").iterdir():
            if d.is_dir() and d.resolve() not in keep and not d.name.startswith("."):
                shutil.rmtree(d, ignore_errors=True)

    def confirm(self) -> None:
        """This version ran long enough: rollback.sh leaves it alone."""
        if self.root:
            (self.root / "confirmed").write_text(self.release + "\n")

    def failed_version(self) -> str | None:
        try:
            return (self.root / "failed").read_text().strip() or None
        except OSError:
            return None


def _symlink(link: Path, target: str) -> None:
    tmp = link.with_name(link.name + ".tmp")
    tmp.unlink(missing_ok=True)
    os.symlink(target, tmp)
    os.replace(tmp, link)  # atomic: the link is never missing
