import asyncio
import math
import random
import tempfile
import unittest
from pathlib import Path

from ledgames.audio import CHUNK, RATE, Loudness, find_device, sensitivity_range
from ledgames.effects.ambient import Level
from ledgames.lights import Lights, make_lut
from tests.test_lights import FakeMic

DT = CHUNK / RATE


def tone(db: float, rng: random.Random, offset: int = 50_000) -> list[int]:
    """CHUNK samples of noise about `db` below full scale, plus a DC offset like the mic's."""
    amp = 2**31 * 10 ** (db / 20) * math.sqrt(3)  # uniform noise: rms = amp / √3
    return [int(offset + rng.uniform(-amp, amp)) for _ in range(CHUNK)]


def feed(loud: Loudness, db: float, seconds: float, rng: random.Random) -> float:
    for _ in range(round(seconds / DT)):
        level = loud.feed(tone(db, rng), DT)
    return level


class LoudnessTest(unittest.TestCase):
    def test_a_quiet_room_stays_dark(self):
        rng = random.Random(1)
        loud = Loudness()
        self.assertLess(feed(loud, -55, 5, rng), 0.15)

    def test_sound_fills_the_meter_then_it_falls_back(self):
        rng = random.Random(2)
        loud = Loudness()
        feed(loud, -55, 3, rng)
        self.assertGreater(feed(loud, -20, 0.1, rng), 0.9)
        self.assertLess(feed(loud, -55, 1, rng), 0.15)

    def test_falls_smoothly(self):
        rng = random.Random(3)
        loud = Loudness()
        feed(loud, -55, 3, rng)
        feed(loud, -20, 0.1, rng)
        after = loud.feed(tone(-80, rng), DT)
        self.assertGreater(after, 0.9 - Loudness.FALL * DT - 0.01)

    def test_adapts_to_a_loud_room(self):
        rng = random.Random(4)
        loud = Loudness()
        feed(loud, -25, 20, rng)  # a loud party for a while
        self.assertLess(feed(loud, -25, 0.5, rng), 0.5)  # its usual noise no longer fills the strip
        self.assertGreater(feed(loud, -8, 0.1, rng), 0.5)  # but a louder moment shows

    def test_more_sensitive_fills_the_strip_with_less_sound(self):
        levels = []
        for sensitivity in (0.0, 0.5, 1.0):
            rng = random.Random(5)
            loud = Loudness()
            loud.min_range = sensitivity_range(sensitivity)
            feed(loud, -55, 3, rng)
            levels.append(feed(loud, -45, 0.1, rng))  # 10 dB over the quiet
        self.assertLess(levels[0], levels[1])
        self.assertLess(levels[1], levels[2])
        self.assertGreater(levels[2], 0.9)
        self.assertEqual(sensitivity_range(0.5), 20)

    def test_dc_offset_alone_is_silence(self):
        loud = Loudness()
        for _ in range(100):
            level = loud.feed([123_456] * CHUNK, DT)
        self.assertEqual(level, 0.0)


class FindDeviceTest(unittest.TestCase):
    def test_finds_the_capture_card(self):
        with tempfile.TemporaryDirectory() as d:
            pcm = Path(d) / "pcm"
            pcm.write_text(
                "00-00: MAI PCM i2s-hifi-0 : MAI PCM i2s-hifi-0 : playback 1\n"
                "01-00: Google voiceHAT SoundCard HiFi : voicehat-hifi-0 : playback 1 : capture 1\n"
            )
            self.assertEqual(find_device(pcm), "plughw:1,0")
            pcm.write_text("00-00: MAI PCM i2s-hifi-0 : MAI PCM i2s-hifi-0 : playback 1\n")
            self.assertIsNone(find_device(pcm))
            self.assertIsNone(find_device(Path(d) / "missing"))


class LevelEffectTest(unittest.TestCase):
    def draw(self, fx, level, seconds=0.0, n=100):
        lut = make_lut(((255, 0, 0), (0, 0, 255)))
        pixels = [(0, 0, 0)] * n
        fx.level = level
        for _ in range(max(1, round(seconds * 30))):
            fx.draw(pixels, 0, 1 / 30, lut)
        return pixels

    def test_bar_height_follows_the_level(self):
        fx = Level(100, random.Random(1))
        px = self.draw(fx, 0.5)
        self.assertTrue(all(p != (0, 0, 0) for p in px[:50]))
        self.assertTrue(all(p == (0, 0, 0) for p in px[51:]))

    def test_peak_dot_holds_then_falls(self):
        fx = Level(100, random.Random(1))
        self.draw(fx, 0.8)
        px = self.draw(fx, 0.2, seconds=Level.HOLD - 0.1)
        self.assertNotEqual(px[80], (0, 0, 0))  # the peak dot, still up
        self.assertEqual(px[60], (0, 0, 0))
        px = self.draw(fx, 0.2, seconds=2)
        self.assertTrue(all(p == (0, 0, 0) for p in px[21:]))  # fell back onto the bar

    def test_full_and_empty(self):
        fx = Level(10, random.Random(1))
        self.assertTrue(all(p != (0, 0, 0) for p in self.draw(fx, 1.0, n=10)))
        fx = Level(10, random.Random(1))
        self.assertEqual(self.draw(fx, 0.0, n=10), [(0, 0, 0)] * 10)


class LightsMicTest(unittest.TestCase):
    def test_listening_only_with_a_sound_effect_on(self):
        lights = Lights(random.Random(1))
        lights.update({"on": True, "effect": "flow"})
        self.assertFalse(lights.listening)
        lights.update({"effect": "level"})
        self.assertTrue(lights.listening)
        lights.update({"on": False})
        self.assertFalse(lights.listening)

    def test_the_mic_level_reaches_the_effect(self):
        lights = Lights(random.Random(1))
        lights.update({"on": True, "effect": "level"})
        lights.mic = FakeMic(0.3)
        pixels = [(0, 0, 0)] * 100
        lights.render(pixels, 1 / 30)
        self.assertEqual(sum(p != (0, 0, 0) for p in pixels), 30)
        lights.mic = None  # no microphone: dark, once the peak dot has fallen
        for _ in range(90):
            lights.render(pixels, 1 / 30)
        self.assertEqual(sum(p != (0, 0, 0) for p in pixels), 0)


if __name__ == "__main__":
    unittest.main()
