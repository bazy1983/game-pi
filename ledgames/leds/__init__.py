from .base import Strip


def make_strip(backend: str, num_leds: int, brightness: float, max_milliamps: int, pin: int) -> Strip:
    if backend == "ws281x":
        from .ws281x import Ws281xStrip

        return Ws281xStrip(num_leds, brightness, max_milliamps, pin)
    from .sim import SimStrip

    return SimStrip(num_leds)
