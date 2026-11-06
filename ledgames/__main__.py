import argparse
import logging
import os

from aiohttp import web

from . import __version__
from .device import default_state_dir, load_or_create, load_settings
from .engine import Engine
from .leds import MAX_LEDS, make_strip
from .server import build_app
from .updater import RELEASE_DIR, RELEASES_URL, Updater, install_root, load_public_key
from .wifi import Wifi


def main() -> None:
    env = os.environ.get
    p = argparse.ArgumentParser(prog="ledgames", description="LED strip games server")
    p.add_argument(
        "--leds",
        type=int,
        help="number of LEDs on the strip (default: the count set on the device page, else LED_COUNT or 250)",
    )
    p.add_argument("--backend", choices=["sim", "ws281x"], default=env("LED_BACKEND", "sim"))
    p.add_argument("--pin", type=int, default=int(env("LED_PIN", 18)), help="GPIO pin (ws281x)")
    p.add_argument("--brightness", type=float, default=float(env("LED_BRIGHTNESS", 0.5)), help="0..1")
    p.add_argument(
        "--max-ma", type=int, default=int(env("LED_MAX_MA", 0)), help="power supply current budget in mA (0 = off)"
    )
    p.add_argument("--fps", type=int, default=int(env("FPS", 30)))
    p.add_argument("--host", default=env("HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=int(env("PORT", 8080)))
    p.add_argument(
        "--wifi",
        choices=["off", "nm", "fake"],
        default=env("WIFI", "off"),
        help="Wi-Fi setup hotspot: nm = NetworkManager (on the Pi), fake = pretend networks (simulator)",
    )
    p.add_argument(
        "--updates",
        choices=["auto", "manual", "off"],
        default=env("UPDATES", "auto"),
        help="over-the-air updates (only when installed from a release)",
    )
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)  # phones poll; don't log every request

    state_dir = default_state_dir()
    saved_settings = load_settings(state_dir)
    if args.leds is None:
        saved = saved_settings.get("leds")
        valid = isinstance(saved, int) and not isinstance(saved, bool) and 1 <= saved <= MAX_LEDS
        args.leds = saved if valid else int(env("LED_COUNT", 250))
    strip = make_strip(args.backend, args.leds, args.brightness, args.max_ma, args.pin)
    engine = Engine(strip, fps=args.fps)
    engine.lights.load(saved_settings.get("lights", {}))

    device = wifi = None
    if args.wifi != "off":
        device = load_or_create()
        if args.wifi == "nm":
            wifi = Wifi(device)
        else:
            from .wifi_fake import FakeHotspot, demo

            nm = demo()
            wifi = Wifi(device, run=nm, hotspot=FakeHotspot(nm), boot_wait=3)

    updater = None
    if args.updates != "off":
        updater = Updater(
            install_root(),
            __version__,
            load_public_key(),
            url=env("UPDATE_URL", RELEASES_URL),
            auto=args.updates == "auto",
            release=RELEASE_DIR.name,
        )

    print(f"LED Games {__version__}: {args.leds} LEDs, backend={args.backend}, wifi={args.wifi}")
    if device:
        print(f"Unit {device.hostname}, setup hotspot {device.hotspot_ssid!r}")
    if args.backend == "sim":
        print(f"Simulator: http://localhost:{args.port}/sim")
    web.run_app(build_app(engine, device, wifi, updater, state_dir), host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
