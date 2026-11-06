from .base import Strip

MAX_LEDS = 1000  # past this, one frame takes longer to send than the game has


def make_strip(backend: str, num_leds: int, brightness: float, max_milliamps: int, pin: int) -> Strip:
    if backend == "ws281x":
        from .ws281x import Ws281xStrip

        return Ws281xStrip(num_leds, brightness, max_milliamps, pin)
    from .sim import SimStrip

    return SimStrip(num_leds)
