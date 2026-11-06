import unittest

from ledgames.leds.base import Strip
from ledgames.leds.sim import SimStrip


class Recorder(Strip):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.writes = []

    def write(self, pixels, factor):
        self.writes.append((list(pixels), factor))


class StripTest(unittest.TestCase):
    def test_unchanged_frames_are_not_written(self):
        strip = Recorder(3, brightness=0.5)
        pixels = [(0, 0, 0)] * 3
        strip.show(pixels)
        strip.show(pixels)
        self.assertEqual(len(strip.writes), 1)
        pixels[1] = (255, 0, 0)  # the engine reuses one list
        strip.show(pixels)
        strip.show(pixels)
        self.assertEqual(strip.writes, [([(0, 0, 0)] * 3, 0.5), ([(0, 0, 0), (255, 0, 0), (0, 0, 0)], 0.5)])

    def test_brightness_change_is_written(self):
        strip = Recorder(1, brightness=0.5)
        strip.show([(10, 10, 10)])
        strip.brightness = 0.25
        strip.show([(10, 10, 10)])
        self.assertEqual([f for _, f in strip.writes], [0.5, 0.25])

    def test_current_limit_dims_bright_frames(self):
        # 10 white LEDs at half brightness: 10 × 3 × 20 mA × 0.5 + 10 mA idle = 310 mA
        strip = Recorder(10, brightness=0.5, max_milliamps=155)
        strip.show([(255, 255, 255)] * 10)
        self.assertAlmostEqual(strip.writes[0][1], 0.5 * 155 / 310)
        strip.show([(255, 0, 0)] + [(0, 0, 0)] * 9)  # well under budget
        self.assertEqual(strip.writes[1][1], 0.5)

    def test_sim_applies_the_factor(self):
        strip = SimStrip(2)
        strip.show([(200, 100, 0), (0, 0, 0)])
        self.assertEqual(strip.frame, bytes([200, 100, 0, 0, 0, 0]))
        strip.write([(200, 100, 0), (0, 0, 0)], 0.5)
        self.assertEqual(strip.frame, bytes([100, 50, 0, 0, 0, 0]))

    def test_resize_turns_the_old_strip_off(self):
        strip = Recorder(3)
        strip.show([(255, 0, 0)] * 3)
        strip.resize(2)
        self.assertEqual(strip.writes[-1], ([(0, 0, 0)] * 3, 0.0))
        strip.show([(255, 0, 0)] * 2)  # same colors, but a new strip: written
        self.assertEqual(strip.writes[-1], ([(255, 0, 0)] * 2, 0.5))

    def test_sim_resize(self):
        strip = SimStrip(2)
        strip.resize(4)
        self.assertEqual(strip.frame, bytes(12))


if __name__ == "__main__":
    unittest.main()
