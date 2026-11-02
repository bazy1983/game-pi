import argparse
import os

from aiohttp import web

from .engine import Engine
from .leds import make_strip
from .server import build_app


def main() -> None:
    env = os.environ.get
    p = argparse.ArgumentParser(prog="ledgames", description="LED strip games server")
    p.add_argument("--leds", type=int, default=int(env("LED_COUNT", 250)), help="number of LEDs on the strip")
    p.add_argument("--backend", choices=["sim", "ws281x"], default=env("LED_BACKEND", "sim"))
    p.add_argument("--pin", type=int, default=int(env("LED_PIN", 18)), help="GPIO pin (ws281x)")
    p.add_argument("--brightness", type=float, default=float(env("LED_BRIGHTNESS", 0.5)), help="0..1")
    p.add_argument(
        "--max-ma", type=int, default=int(env("LED_MAX_MA", 0)), help="power supply current budget in mA (0 = off)"
    )
    p.add_argument("--fps", type=int, default=int(env("FPS", 30)))
    p.add_argument("--host", default=env("HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=int(env("PORT", 8080)))
    args = p.parse_args()

    strip = make_strip(args.backend, args.leds, args.brightness, args.max_ma, args.pin)
    engine = Engine(strip, fps=args.fps)
    print(f"{args.leds} LEDs, backend={args.backend}")
    if args.backend == "sim":
        print(f"Simulator: http://localhost:{args.port}/sim")
    web.run_app(build_app(engine), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
