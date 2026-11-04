"""This unit's identity: a short id, its name on the network, and the
password of its setup hotspot.

Created once ("provisioning", normally at the factory) and kept in the state
directory, so the sticker printed for the unit stays valid for its lifetime.
"""

import json
import os
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path

PRODUCT = "LED Games"
# Easy to type. A second unit on the same network is renamed ledgames-2.local
# by the Pi's mDNS (avahi); invite links use the IP address, so they still work.
HOSTNAME = "ledgames"
# No 0/o, 1/l/i: the password is typed from a sticker when the QR code fails.
PASSWORD_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
PASSWORD_LENGTH = 10


@dataclass
class Device:
    id: str  # 4 hex digits, e.g. "93d5"
    hotspot_password: str

    @property
    def hostname(self) -> str:
        return HOSTNAME

    @property
    def hotspot_ssid(self) -> str:
        return f"{PRODUCT} {self.id.upper()}"

    @property
    def local_url(self) -> str:
        return f"http://{self.hostname}.local"

    def wifi_qr(self) -> str:
        """Text for a QR code that joins the setup hotspot when scanned with
        a phone camera."""
        return f"WIFI:T:WPA;S:{_qr_escape(self.hotspot_ssid)};P:{_qr_escape(self.hotspot_password)};;"


def _qr_escape(s: str) -> str:
    for ch in '\\;,:"':
        s = s.replace(ch, "\\" + ch)
    return s


def default_state_dir() -> Path:
    if env := os.environ.get("LEDGAMES_STATE"):
        return Path(env)
    return Path("/var/lib/ledgames") if os.geteuid() == 0 else Path.home() / ".ledgames"


def cpu_serial() -> str | None:
    """The Pi's serial number (unique per board), or None off a Pi."""
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("Serial"):
                serial = line.split(":", 1)[1].strip().lower()
                return serial if serial.strip("0") else None
    except OSError:
        pass
    return None


def load_or_create(state_dir: Path | None = None, serial: str | None = None) -> Device:
    path = (state_dir or default_state_dir()) / "device.json"
    try:
        return Device(**json.loads(path.read_text()))
    except (OSError, ValueError, TypeError):
        pass
    serial = serial if serial is not None else cpu_serial()
    device = Device(
        id=serial[-4:] if serial else secrets.token_hex(2),
        hotspot_password="".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(PASSWORD_LENGTH)),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(device), indent=2) + "\n")
    path.chmod(0o600)  # holds the hotspot password
    return device
