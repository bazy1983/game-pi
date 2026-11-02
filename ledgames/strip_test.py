"""Wiring check for the real strip. Run on the Pi (as root):

    sudo .venv/bin/python -m ledgames.strip_test --leds 195

1. A red dot climbs from the bottom LED to the top (checks direction).
2. The whole strip shows each game color, then white (checks color order).
3. The bottom 3 LEDs stay white for a few seconds (the shooter), then off.
"""

import argparse
import time

from .colors import OFF, PALETTE, RED, WHITE
from .leds import make_strip


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--leds", type=int, required=True)
    p.add_argument("--pin", type=int, default=18)
    p.add_argument("--brightness", type=float, default=0.2)
    p.add_argument("--max-ma", type=int, default=0)
    args = p.parse_args()

    strip = make_strip("ws281x", args.leds, args.brightness, args.max_ma, args.pin)
    n = args.leds
    try:
        print("1. red dot climbing bottom → top")
        for i in range(n):
            px = [OFF] * n
            px[i] = RED
            strip.show(px)
            time.sleep(4 / n)

        for c in PALETTE:
            print(f"2. all {c.name}")
            strip.show([c.led] * n)
            time.sleep(1.5)
        print("2. all white")
        strip.show([WHITE] * n)
        time.sleep(1.5)

        print("3. shooter (bottom 3 white)")
        strip.show([WHITE] * 3 + [OFF] * (n - 3))
        time.sleep(3)
    finally:
        strip.show([OFF] * n)
        print("done, strip off")


if __name__ == "__main__":
    main()
