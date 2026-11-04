"""Gets the unit onto the customer's Wi-Fi, through NetworkManager (nmcli).

With no network to join, the unit runs its own hotspot ("LED Games 93D5",
password on the sticker) with hostapd and dnsmasq. Every web address resolves to the unit there, so
phones pop up the setup page by themselves (a captive portal). The customer
picks their network and types its password; if joining fails, the hotspot
comes back with an error.

Modes:
  starting    just booted (or retrying): saved networks get time to connect
  online      on a network (Wi-Fi or Ethernet)
  setup       running the setup hotspot
  connecting  trying the network the customer picked
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from .device import Device

log = logging.getLogger(__name__)

BOOT_WAIT = 45  # after boot, saved networks get this long to connect
OFFLINE_WAIT = 120  # once online, lose the network this long → setup hotspot
RETRY_EVERY = 300  # in setup mode, try the saved networks again this often…
SETUP_IDLE = 120  # …if nobody has had the setup page open for this long
CONNECT_WAIT = 30  # seconds to join the customer's network
POLL = 5
WIFI_PRIORITY = 10  # networks set up here win over older saved ones

HOTSPOT_CON = "ledgames-setup"  # NetworkManager hotspot of 0.2.0; removed if found
HOTSPOT_IP = "10.42.0.1"
HOSTAPD_CONF = Path("/run/ledgames/hostapd.conf")
WIFI_TYPE = "802-11-wireless"
ETHERNET_TYPE = "802-3-ethernet"

Runner = Callable[[list[str]], Awaitable[tuple[int, str]]]


async def run_cmd(args: list[str]) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    out, _ = await proc.communicate()
    return proc.returncode, out.decode(errors="replace")


@dataclass
class Network:
    ssid: str
    signal: int
    security: str

    @property
    def secure(self) -> bool:
        return bool(self.security.strip())

    @property
    def wpa3_only(self) -> bool:
        return "WPA3" in self.security and "WPA2" not in self.security and "WPA1" not in self.security


def split_terse(line: str) -> list[str]:
    """Split a line of `nmcli -t` output: fields are separated by ':', and
    ':' or '\\' inside a field are escaped with '\\'."""
    fields, cur, esc = [], [], False
    for ch in line:
        if esc:
            cur.append(ch)
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            fields.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    fields.append("".join(cur))
    return fields


def parse_scan(out: str, exclude: str = "") -> list[Network]:
    """`nmcli -t -f SSID,SIGNAL,SECURITY dev wifi list` → networks, strongest
    first, one entry per name."""
    best: dict[str, Network] = {}
    for line in out.splitlines():
        f = split_terse(line)
        if len(f) < 3 or not f[0] or f[0] == exclude:
            continue
        try:
            signal = int(f[1])
        except ValueError:
            continue
        if f[0] not in best or signal > best[f[0]].signal:
            best[f[0]] = Network(f[0], signal, f[2])
    return sorted(best.values(), key=lambda n: -n.signal)


class Hotspot:
    """The setup hotspot, run with hostapd and dnsmasq.

    NetworkManager can run a hotspot too, but on the Pi Zero W's Wi-Fi chip
    phones never finish the WPA2 handshake with it. So while this runs,
    NetworkManager lets go of the interface."""

    url = f"http://{HOTSPOT_IP}/setup"  # where the captive portal sends phones

    def __init__(self, iface: str = "wlan0", run: Runner = run_cmd, conf: Path = HOSTAPD_CONF):
        self.iface = iface
        self._run = run
        self.conf = conf
        self._procs: list[asyncio.subprocess.Process] = []
        self._tasks: set[asyncio.Task] = set()
        self._taken = False  # NetworkManager has let go of the interface

    async def start(self, ssid: str, password: str) -> str | None:
        """Returns an error message, or None once the hotspot is up."""
        await self.stop()
        self.conf.parent.mkdir(parents=True, exist_ok=True)
        self.conf.touch(mode=0o600)
        self.conf.write_text(
            f"interface={self.iface}\ndriver=nl80211\nssid2={_hex(ssid)}\nhw_mode=g\nchannel=6\n"
            f"wpa=2\nwpa_key_mgmt=WPA-PSK\nrsn_pairwise=CCMP\nwpa_passphrase={password}\n"
        )
        await self._run(["nmcli", "con", "delete", HOTSPOT_CON])
        self._taken = True
        await self._run(["nmcli", "dev", "set", self.iface, "managed", "no"])
        await asyncio.sleep(1)
        await self._run(["ip", "addr", "flush", "dev", self.iface])
        await self._run(["ip", "addr", "add", f"{HOTSPOT_IP}/24", "dev", self.iface])
        await self._run(["ip", "link", "set", self.iface, "up"])

        hostapd = await self._spawn(["hostapd", str(self.conf)])
        lines = []
        try:
            async with asyncio.timeout(15):
                while line := (await hostapd.stdout.readline()).decode(errors="replace"):
                    lines.append(line.strip())
                    if "AP-ENABLED" in line:
                        break
        except TimeoutError:
            pass
        if not lines or "AP-ENABLED" not in lines[-1]:
            await self.stop()
            return "hostapd: " + " / ".join(lines[-3:])
        self._drain(hostapd)
        # DHCP, and every DNS name answers with our address: phones then find
        # the setup page on their own (a captive portal).
        dnsmasq = await self._spawn(
            [
                "dnsmasq", "--keep-in-foreground", "--conf-file=/dev/null", "--pid-file=",
                f"--interface={self.iface}", "--bind-interfaces", "--except-interface=lo",
                "--no-resolv", "--no-hosts", "--dhcp-authoritative",
                "--dhcp-range=10.42.0.10,10.42.0.254,1h", f"--address=/#/{HOTSPOT_IP}",
            ]
        )  # fmt: skip
        self._drain(dnsmasq)
        return None

    async def stop(self) -> None:
        """Stop the hotspot (if any) and give the interface back to
        NetworkManager, which then rejoins saved networks by itself."""
        for proc in self._procs:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), 5)
                except TimeoutError:
                    proc.kill()
        self._procs.clear()
        if self._taken:
            await self._release()

    async def recover(self) -> None:
        """At startup: if the last run died with the hotspot up, give the
        interface back. (Never touch it otherwise: that would cut a working
        connection.)"""
        code, out = await self._run(["nmcli", "-g", "GENERAL.STATE", "dev", "show", self.iface])
        if code == 0 and "unmanaged" in out:
            log.info("%s was left unmanaged; handing it back to NetworkManager", self.iface)
            await self._release()

    async def _release(self) -> None:
        await self._run(["ip", "addr", "flush", "dev", self.iface])
        await self._run(["nmcli", "dev", "set", self.iface, "managed", "yes"])
        self._taken = False

    async def _spawn(self, args: list[str]) -> asyncio.subprocess.Process:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        self._procs.append(proc)
        return proc

    def _drain(self, proc: asyncio.subprocess.Process) -> None:
        """Read the output, or a full pipe would stall the program. (Both
        write to the system journal already.)"""

        async def read() -> None:
            while await proc.stdout.readline():
                pass

        task = asyncio.ensure_future(read())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


def _hex(s: str) -> str:
    return s.encode().hex()


class Wifi:
    def __init__(
        self,
        device: Device,
        run: Runner = run_cmd,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        iface: str = "wlan0",
        hotspot: "Hotspot | None" = None,
        boot_wait: float = BOOT_WAIT,
    ):
        self.device = device
        self._run = run
        self.clock = clock
        self.sleep = sleep
        self.iface = iface
        self.hotspot = hotspot or Hotspot(iface, run)
        self.boot_wait = boot_wait
        self.on_change: Callable[[], None] = lambda: None

        self.mode = "starting"
        self.ssid: str | None = None  # network we're on
        self.networks: list[Network] = []  # seen before the hotspot went up
        self.connecting_to: str | None = None
        self.error: str | None = None
        self._since = clock()  # when the current mode began
        self._offline_since: float | None = None
        self._last_seen = float("-inf")  # last setup page request
        self._lock = asyncio.Lock()  # one network change at a time

    def state(self) -> dict:
        return {
            "mode": self.mode,
            "ssid": self.ssid,
            "hotspot": self.device.hotspot_ssid,
            "networks": [{"ssid": n.ssid, "signal": n.signal, "secure": n.secure} for n in self.networks],
            "connecting_to": self.connecting_to,
            "error": self.error,
        }

    def touch(self) -> None:
        """Someone has the setup page open: don't drop the hotspot on them."""
        self._last_seen = self.clock()

    @property
    def captive(self) -> bool:
        return self.mode in ("setup", "connecting")

    # --- main loop ------------------------------------------------------------

    async def run(self) -> None:
        await self.hotspot.recover()
        while True:
            try:
                await self.step()
            except Exception:
                log.exception("wifi step failed")
            await self.sleep(POLL)

    async def step(self) -> None:
        if self._lock.locked():
            return  # a network change is in progress
        async with self._lock:
            now = self.clock()
            if self.mode in ("starting", "online"):
                if await self.online():
                    self._offline_since = None
                    ssid = await self.current_ssid()
                    if self.mode != "online" or ssid != self.ssid:
                        self.ssid = ssid
                        self._set_mode("online")
                    return
                if self._offline_since is None:
                    self._offline_since = now
                wait = self.boot_wait if self.mode == "starting" else OFFLINE_WAIT
                if now - self._offline_since >= wait:
                    await self._start_setup()
            elif self.mode == "setup":
                if (
                    now - self._since >= RETRY_EVERY
                    and now - self._last_seen >= SETUP_IDLE
                    and await self.saved_networks()
                ):
                    log.info("retrying saved networks")
                    self._offline_since = now
                    self._set_mode("starting")
                    await self.hotspot.stop()
                    await self.sleep(5)  # NetworkManager takes the interface back
                    await self._run(["nmcli", "dev", "wifi", "rescan", "ifname", self.iface])
                    await self.sleep(3)
                    for name in await self.saved_networks():
                        code, _ = await self._run(["nmcli", "--wait", str(CONNECT_WAIT), "con", "up", name])
                        if code == 0:
                            break

    def _set_mode(self, mode: str) -> None:
        log.info("wifi: %s", mode)
        self.mode = mode
        self._since = self.clock()
        self.on_change()

    # --- customer actions -----------------------------------------------------

    def connect(self, ssid: str, password: str) -> str | None:
        """Join the customer's network (runs in the background). Returns an
        error message, or None."""
        if self.mode != "setup":
            return "The unit isn't in setup mode."
        if not 1 <= len(ssid.encode()) <= 32:
            return "Pick a network."
        if password and not 8 <= len(password) <= 63:
            return "Wi-Fi passwords are 8 to 63 characters."
        self.connecting_to = ssid
        self.error = None
        self._set_mode("connecting")
        asyncio.ensure_future(self._connect(ssid, password))
        return None

    def enter_setup(self) -> str | None:
        """Start the setup hotspot to move the unit to another network. The
        current network stays saved and is retried if setup is abandoned."""
        if self.mode != "online":
            return "The unit isn't on a network."
        asyncio.ensure_future(self._locked(self._start_setup))
        return None

    async def _locked(self, fn: Callable[[], Awaitable[None]]) -> None:
        async with self._lock:
            await fn()

    # --- nmcli ----------------------------------------------------------------

    async def online(self) -> bool:
        code, out = await self._run(["nmcli", "-t", "-f", "NAME,TYPE", "con", "show", "--active"])
        if code != 0:
            return False
        for line in out.splitlines():
            f = split_terse(line)
            if len(f) >= 2 and f[0] != HOTSPOT_CON and f[1] in (WIFI_TYPE, ETHERNET_TYPE):
                return True
        return False

    async def current_ssid(self) -> str | None:
        code, out = await self._run(["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi", "list", "--rescan", "no"])
        for line in out.splitlines() if code == 0 else []:
            f = split_terse(line)
            if len(f) >= 2 and f[0] == "yes":
                return f[1]
        return None

    async def saved_networks(self) -> list[str]:
        code, out = await self._run(["nmcli", "-t", "-f", "NAME,TYPE", "con", "show"])
        names = []
        for line in out.splitlines() if code == 0 else []:
            f = split_terse(line)
            if len(f) >= 2 and f[1] == WIFI_TYPE and f[0] != HOTSPOT_CON:
                names.append(f[0])
        return names

    async def scan(self) -> list[Network]:
        code, out = await self._run(
            ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list", "ifname", self.iface, "--rescan", "yes"]
        )
        return parse_scan(out, exclude=self.device.hotspot_ssid) if code == 0 else []

    async def _start_setup(self) -> None:
        """Scan (the radio can't while it's a hotspot), then start the
        hotspot."""
        self.networks = await self.scan() or self.networks
        error = await self.hotspot.start(self.device.hotspot_ssid, self.device.hotspot_password)
        if error:
            log.error("couldn't start the setup hotspot: %s", error)
            self._offline_since = self.clock()
            self._set_mode("starting")  # try saved networks, then the hotspot again
            return
        self.ssid = None
        self._set_mode("setup")

    async def _connect(self, ssid: str, password: str) -> None:
        async with self._lock:
            await self.hotspot.stop()
            await self.sleep(5)  # NetworkManager takes the interface back
            await self._run(["nmcli", "dev", "wifi", "rescan", "ifname", self.iface])
            await self.sleep(3)  # let the scan find the network

            name = f"ledgames: {ssid}"
            seen = next((n for n in self.networks if n.ssid == ssid), None)
            args = [
                "nmcli", "con", "add", "type", "wifi", "ifname", self.iface, "con-name", name, "ssid", ssid,
                "connection.autoconnect-priority", str(WIFI_PRIORITY),
            ]  # fmt: skip
            if seen is None:
                args += ["802-11-wireless.hidden", "yes"]  # typed in by hand
            if password:
                key_mgmt = "sae" if seen and seen.wpa3_only else "wpa-psk"
                args += ["wifi-sec.key-mgmt", key_mgmt, "wifi-sec.psk", password]
            await self._run(["nmcli", "con", "delete", name])
            code, out = await self._run(args)
            if code == 0:
                code, out = await self._run(["nmcli", "--wait", str(CONNECT_WAIT), "con", "up", name])
            if code == 0 and await self.online():
                log.info("joined %s", ssid)
                self.ssid = ssid
                self.connecting_to = None
                self._offline_since = None
                self._set_mode("online")
                return

            log.warning("couldn't join %s: %s", ssid, out.strip())
            await self._run(["nmcli", "con", "delete", name])
            self.error = f"Couldn't join “{ssid}”. Check the password and try again."
            self.connecting_to = None
            await self._start_setup()
