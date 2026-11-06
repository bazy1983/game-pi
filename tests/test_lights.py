import random
import unittest

from ledgames.effects.ambient import EFFECTS
from ledgames.engine import Engine
from ledgames.lights import PALETTES, Lights, make_lut
from tests.test_engine import Clock, NullStrip


def valid(pixels):
    return all(
        isinstance(px, tuple) and len(px) == 3 and all(isinstance(c, int) and 0 <= c <= 255 for c in px) for px in pixels
    )


class EffectsTest(unittest.TestCase):
    def test_every_effect_and_palette_draws_valid_colors(self):
        for n in (1, 2, 60, 300):
            for effect in EFFECTS:
                for palette in PALETTES:
                    lights = Lights(random.Random(1))
                    lights.update({"on": True, "effect": effect, "palette": palette})
                    pixels = [(0, 0, 0)] * n
                    for speed in (0.0, 0.5, 1.0):
                        lights.update({"speed": speed})
                        for _ in range(40):
                            lights.render(pixels, 1 / 30)
                    self.assertEqual(len(pixels), n)
                    self.assertTrue(valid(pixels), (n, effect, palette))

    def test_effects_light_up_the_strip(self):
        for effect in EFFECTS:
            lights = Lights(random.Random(2))
            lights.update({"on": True, "effect": effect, "level": 1.0})
            pixels = [(0, 0, 0)] * 100
            lit = 0
            for _ in range(90):
                lights.render(pixels, 1 / 30)
                lit = max(lit, sum(px != (0, 0, 0) for px in pixels))
            self.assertGreater(lit, 0, effect)

    def test_lut_wraps_around(self):
        lut = make_lut(((255, 0, 0), (0, 0, 255)))
        self.assertEqual(len(lut), 256)
        self.assertEqual(lut[0], (255, 0, 0))
        self.assertEqual(lut[128], (0, 0, 255))
        self.assertGreater(lut[255][0], 200)  # nearly back to red
        self.assertEqual(make_lut(((1, 2, 3),)), [(1, 2, 3)] * 256)


class SettingsTest(unittest.TestCase):
    def test_invalid_changes_change_nothing(self):
        lights = Lights()
        for bad in ({"effect": "nope"}, {"speed": 2}, {"level": 0}, {"color": "red"}, {"on": 1}, {"speed": True}):
            before = lights.settings()
            self.assertIsNotNone(lights.update({"palette": "ocean", **bad}), bad)
            self.assertEqual(lights.settings(), before)

    def test_custom_color(self):
        lights = Lights()
        self.assertIsNone(lights.update({"on": True, "effect": "still", "palette": "custom", "color": "#FF8000", "level": 1.0}))
        self.assertEqual(lights.color, "#ff8000")
        pixels = [(0, 0, 0)] * 5
        for _ in range(40):  # past the fade-in
            lights.render(pixels, 1 / 30)
        self.assertEqual(pixels, [(255, 128, 0)] * 5)

    def test_load_skips_what_is_no_longer_valid(self):
        lights = Lights()
        lights.load({"on": True, "effect": "retired", "palette": "ice", "extra": 1})
        self.assertEqual((lights.on, lights.effect, lights.palette), (True, "flow", "ice"))


class EngineLightsTest(unittest.TestCase):
    def setUp(self):
        self.engine = Engine(NullStrip(40), clock=Clock())
        self.engine.lights.update({"on": True, "effect": "still", "level": 1.0})

    def lit(self):
        return sum(px != (0, 0, 0) for px in self.engine.pixels)

    def factor(self):
        """How bright the strip shows the last frame (brightness 0.5 × level)."""
        return self.engine.strip._last[1]

    def test_lights_play_when_idle_and_fade_in(self):
        self.engine.tick(1 / 30)
        self.assertAlmostEqual(self.factor(), 0.5 / 30)
        for _ in range(40):
            self.engine.tick(1 / 30)
        self.assertEqual(self.lit(), 40)
        self.assertEqual(self.factor(), 0.5)

    def test_a_game_takes_over_and_the_lights_come_back(self):
        for _ in range(40):
            self.engine.tick(1 / 30)
        self.engine.open("color_shooter", "easy", {}, "host")
        self.engine.tick(1 / 30)
        self.assertNotEqual(self.lit(), 40)  # the game's own picture
        self.engine.stop()
        self.engine.tick(1 / 30)
        self.assertEqual(self.lit(), 40)
        self.assertLess(self.factor(), 0.1)  # fading back in

    def test_off(self):
        self.engine.lights.update({"on": False})
        self.engine.tick(1 / 30)
        self.assertEqual(self.lit(), 0)


if __name__ == "__main__":
    unittest.main()
