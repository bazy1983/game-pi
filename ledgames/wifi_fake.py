"""A pretend NetworkManager, so the Wi-Fi setup flow runs in tests and in
the simulator (`--wifi fake`) without a Pi."""

from dataclasses import dataclass, field

from .wifi import ETHERNET_TYPE, WIFI_TYPE


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace(":", "\\:")


@dataclass
class Profile:
    ssid: str
    psk: str = ""
    type: str = WIFI_TYPE


@dataclass
class FakeNmcli:
    # Networks in range: ssid → (signal, security, password)
    visible: dict[str, tuple[int, str, str]] = field(default_factory=dict)
    profiles: dict[str, Profile] = field(default_factory=dict)  # saved connections
    active: set[str] = field(default_factory=set)
    calls: list[list[str]] = field(default_factory=list)
    ap: tuple[str, str] | None = None  # (ssid, password) while FakeHotspot runs

    async def __call__(self, args: list[str]) -> tuple[int, str]:
        self.calls.append(args)
        a = [x for x in args[1:] if x not in ("-t",)]
        # Drop global options: -f FIELDS, --wait N
        while a and a[0] in ("-f", "--wait"):
            a = a[2:]

        if a[:2] == ["con", "show"]:
            names = self.active if "--active" in a else self.profiles
            return 0, "".join(f"{_esc(n)}:{self.profiles[n].type}\n" for n in names)
        if a[:3] == ["dev", "wifi", "list"]:
            if self._ap_up():
                return 10, "Error: scanning not allowed while in AP mode\n"
            if "ACTIVE,SSID" in args:
                ours = {self.profiles[n].ssid for n in self.active}
                return 0, "".join(f"{'yes' if s in ours else 'no'}:{_esc(s)}\n" for s in self.visible)
            return 0, "".join(f"{_esc(s)}:{sig}:{sec}\n" for s, (sig, sec, _) in self.visible.items())
        if a[:3] == ["dev", "wifi", "rescan"]:
            return 0, ""
        if a[:3] == ["dev", "set", "wlan0"]:
            return 0, ""
        if a[:2] == ["con", "add"]:
            opts = dict(zip(a[2::2], a[3::2]))
            self.profiles[opts["con-name"]] = Profile(ssid=opts["ssid"], psk=opts.get("wifi-sec.psk", ""))
            return 0, ""
        if a[:2] == ["con", "delete"]:
            self.active.discard(a[2])
            return (0, "") if self.profiles.pop(a[2], None) else (10, "Error: unknown connection\n")
        if a[:2] == ["con", "down"]:
            if a[2] not in self.active:
                return 10, "Error: not active\n"
            self.active.discard(a[2])
            return 0, ""
        if a[:2] == ["con", "up"]:
            p = self.profiles.get(a[2])
            if p is None:
                return 10, "Error: unknown connection\n"
            if self._ap_up():
                return 10, "Error: device wlan0 is not managed\n"
            self.active = {n for n in self.active if self.profiles[n].type == ETHERNET_TYPE}
            if self._can_join(p):
                self.active.add(a[2])
                return 0, ""
            return 4, "Error: Connection activation failed: Secrets were required, but not provided\n"
        if args[0] == "ip":
            return 0, ""
        return 1, f"Error: fake nmcli doesn't know {' '.join(args)}\n"

    def _ap_up(self) -> bool:
        return self.ap is not None

    def _can_join(self, p: Profile) -> bool:
        seen = self.visible.get(p.ssid)
        return seen is not None and seen[2] == p.psk


class FakeHotspot:
    """Stands in for hostapd: while it runs, NetworkManager has no Wi-Fi."""

    url = "/setup"

    def __init__(self, nm: FakeNmcli, fail: bool = False):
        self.nm = nm
        self.fail = fail

    async def start(self, ssid: str, password: str) -> str | None:
        if self.fail:
            return "hostapd: failed"
        self.nm.active = {n for n in self.nm.active if self.nm.profiles[n].type == ETHERNET_TYPE}
        self.nm.ap = (ssid, password)
        return None

    async def stop(self) -> None:
        self.nm.ap = None

    async def recover(self) -> None:
        pass


def demo() -> FakeNmcli:
    """Some neighbors' networks; "Home Wi-Fi" has the password "password123"."""
    return FakeNmcli(
        visible={
            "Home Wi-Fi": (82, "WPA2", "password123"),
            "Neighbor 5G": (54, "WPA1 WPA2", "nope-nope"),
            "Coffee Shop": (31, "", ""),
        }
    )
