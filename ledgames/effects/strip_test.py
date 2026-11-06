from ..colors import OFF, RGB, WHITE

TEST_TIME = 10.0
CLIMB_TIME = 3.0
COLOR_TIME = 1.5
COLORS: list[RGB] = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]


def draw_test(pixels: list[RGB], t: float) -> None:
    """Wiring check from the device page, TEST_TIME long:
    0–3 s     a red dot climbs from the bottom LED to the top (direction)
    3–7.5 s   the whole strip red, green, then blue (color order)
    7.5–10 s  the first and last LED blink white: if the top of the strip
              isn't the one blinking, the LED count is wrong"""
    n = len(pixels)
    for i in range(n):
        pixels[i] = OFF
    if t < CLIMB_TIME:
        pixels[min(n - 1, int(t / CLIMB_TIME * n))] = COLORS[0]
    elif t < CLIMB_TIME + COLOR_TIME * len(COLORS):
        color = COLORS[int((t - CLIMB_TIME) / COLOR_TIME)]
        for i in range(n):
            pixels[i] = color
    elif int(t * 4) % 2 == 0:
        pixels[0] = pixels[-1] = WHITE
