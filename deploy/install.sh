#!/bin/sh
# Install the code in this directory on a Pi as the running release.
#
#   sudo sh deploy/install.sh                     # as version <__version__>
#   sudo RELEASE_NAME=dev sh deploy/install.sh    # development builds
#
# First run also installs packages, the Python environment and the service.
set -e
SRC=$(cd "$(dirname "$0")/.." && pwd)
ROOT=/opt/ledgames
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC/ledgames/__init__.py")
NAME=${RELEASE_NAME:-$VERSION}

missing=""
for pkg in python3-venv python3-aiohttp python3-qrcode python3-cryptography rsync hostapd dnsmasq-base; do
  dpkg -s "$pkg" >/dev/null 2>&1 || missing="$missing $pkg"
done
[ -z "$missing" ] || apt-get install -y $missing
# The setup hotspot runs hostapd itself; its own service must stay off.
systemctl mask -q hostapd
# Left over from 0.2.0, which ran the hotspot through NetworkManager.
rm -f /etc/NetworkManager/dnsmasq-shared.d/ledgames-captive.conf
nmcli con delete ledgames-setup >/dev/null 2>&1 || true

# Wi-Fi power saving holds packets for the Pi back by up to a second, so taps
# arrive late and in bursts. Off for every connection (2 = disable), and
# right away for the current one.
mkdir -p /etc/NetworkManager/conf.d
printf '[connection]\nwifi.powersave = 2\n' > /etc/NetworkManager/conf.d/ledgames-wifi.conf
iw dev wlan0 set power_save off 2>/dev/null || true

mkdir -p "$ROOT/releases" /var/lib/ledgames
chmod 700 /var/lib/ledgames
if [ ! -x "$ROOT/.venv/bin/python" ]; then
  python3 -m venv --system-site-packages "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" install -q rpi_ws281x
fi

rsync -a --delete --exclude .venv --exclude __pycache__ --exclude .git --exclude dist \
  "$SRC/" "$ROOT/releases/$NAME/"

old=$(readlink "$ROOT/current" 2>/dev/null || true)
if [ -n "$old" ] && [ "$old" != "releases/$NAME" ]; then
  ln -sfn "$old" "$ROOT/previous"
fi
ln -sfn "releases/$NAME" "$ROOT/current.tmp"
mv -T "$ROOT/current.tmp" "$ROOT/current"
rm -f "$ROOT/failed"

install -m 755 "$SRC/deploy/rollback.sh" "$ROOT/rollback.sh"
install -m 644 "$SRC/deploy/ledgames.service" "$SRC/deploy/ledgames-rollback.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable ledgames >/dev/null 2>&1
systemctl restart ledgames
echo "Installed $NAME ($VERSION)"
