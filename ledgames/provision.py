"""Give a unit its identity and print its sticker (run once per unit, as root).

    sudo /opt/ledgames/.venv/bin/python -m ledgames.provision --hostname --sticker sticker.svg

Creates /var/lib/ledgames/device.json (id + hotspot password) if it doesn't
exist yet, renames the Pi to ledgames, and writes a printable sticker:
a QR code that joins the setup hotspot, plus the password in case a phone
can't scan it.
"""

import argparse
import html
import re
import subprocess
from pathlib import Path

from . import qr
from .device import PRODUCT, Device, load_or_create


def set_hostname(name: str) -> None:
    old = Path("/etc/hostname").read_text().strip()
    subprocess.run(["hostnamectl", "set-hostname", name], check=True)
    hosts = Path("/etc/hosts")
    text = hosts.read_text()
    line = f"127.0.1.1\t{name}"
    if re.search(r"^127\.0\.1\.1\s.*$", text, flags=re.M):
        text = re.sub(r"^127\.0\.1\.1\s.*$", line, text, flags=re.M)
    else:
        text += line + "\n"
    hosts.write_text(text)
    subprocess.run(["systemctl", "restart", "avahi-daemon"], check=False)  # announce the new .local name
    print(f"Hostname: {old} → {name}")


def sticker_svg(device: Device) -> str:
    """A 70 × 35 mm label."""
    e = html.escape
    lines = [
        (f"{PRODUCT} {device.id.upper()}", 4.2, "700"),
        ("Scan to set up Wi-Fi", 3.0, "400"),
        ("", 2.0, "400"),
        ("Or join the Wi-Fi network:", 2.4, "400"),
        (device.hotspot_ssid, 2.8, "700"),
        ("Password:", 2.4, "400"),
        (device.hotspot_password, 3.2, "700"),
    ]
    y, text = 6.5, []
    for content, size, weight in lines:
        if content:
            text.append(f'<text x="34" y="{y:.1f}" font-size="{size}" font-weight="{weight}">{e(content)}</text>')
        y += size + 1.6
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="70mm" height="35mm" viewBox="0 0 70 35" '
        'font-family="Helvetica, Arial, sans-serif" shape-rendering="crispEdges">'
        '<rect width="70" height="35" fill="#fff"/>'
        + qr.svg_from_matrix(qr.matrix(device.wifi_qr()), x=2, y=2, size=31)
        + "".join(text)
        + "</svg>\n"
    )


def main() -> None:
    p = argparse.ArgumentParser(prog="ledgames.provision", description=__doc__.split("\n")[0])
    p.add_argument("--hostname", action="store_true", help="rename the Pi to ledgames")
    p.add_argument("--sticker", type=Path, help="write the sticker SVG here")
    args = p.parse_args()

    device = load_or_create()
    print(f"Unit:     {device.id}")
    print(f"Hotspot:  {device.hotspot_ssid}")
    print(f"Password: {device.hotspot_password}")
    print(f"Address:  {device.local_url}")
    if args.hostname:
        set_hostname(device.hostname)
    if args.sticker:
        args.sticker.write_text(sticker_svg(device))
        print(f"Sticker:  {args.sticker}")


if __name__ == "__main__":
    main()
