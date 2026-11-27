import asyncio
import math
import random
import tempfile
import unittest
from pathlib import Path

from ledgames.audio import BANDS, CHUNK, LISTEN_RATE, RATE, STEP, Loudness, Microphone, find_device, sensitivity_range
from ledgames.effects.ambient import Level
from ledgames.lights import Lights, make_lut
from tests.test_lights import FakeMic

DT = CHUNK / RATE
N = CHUNK // STEP  # samples per chunk, at LISTEN_RATE


def tone(db: float, rng: random.Random, offset: int = 50_000) -> list[int]:
    """A chunk of noise about `db` below full scale, plus a DC offset like the mic's."""
    amp = 2**31 * 10 ** (db / 20) * math.sqrt(3)  # uniform noise: rms = amp / √3
    return [int(offset + rng.uniform(-amp, amp)) for _ in range(N)]


def wobble(t: float, db: float, hz: float) -> list[int]:
    """A chunk of a slow wave like the one the mic picks up, starting at time t."""
    amp = 2**31 * 10 ** (db / 20) * math.sqrt(2)
    return [int(amp * math.sin(2 * math.pi * hz * (t + i / LISTEN_RATE))) for i in range(N)]


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
            level = loud.feed([123_456] * N, DT)
        self.assertEqual(level, 0.0)

    def test_a_slow_wobble_is_not_sound(self):
        """The mic's wobble, far below hearing and louder than the room's
        hiss (as measured on the unit), doesn't light the strip."""
        rng = random.Random(6)
        loud = Loudness()
        t = 0.0
        levels = []
        for _ in range(round(5 / DT)):
            hiss = tone(-75, rng)
            levels.append(loud.feed([a + b + c for a, b, c in zip(hiss, wobble(t, -40, 7), wobble(t, -45, 30))], DT))
            t += DT
        self.assertLess(max(levels[25:]), 0.15)
        self.assertLess(loud.db, -70)  # it hears just the hiss

    def test_the_room_hiss_stays_dark_at_the_most_sensitive(self):
        rng = random.Random(7)
        loud = Loudness()
        loud.min_range = sensitivity_range(1)
        feed(loud, -75, 8, rng)
        self.assertLess(max(loud.feed(tone(-75, rng), DT) for _ in range(100)), 0.1)
        self.assertGreater(feed(loud, -60, 0.1, rng), 0.9)

    def test_the_bands_show_where_the_sound_is(self):
        loud = Loudness()
        for i in range(3):
            high = [int(2**31 * 0.1 * math.sin(2 * math.pi * 4800 * (i * N + j) / LISTEN_RATE)) for j in range(N)]
            loud.feed(high, DT)
        self.assertEqual(len(loud.bands), BANDS)
        self.assertEqual(max(range(BANDS), key=loud.bands.__getitem__), BANDS - 2)  # 4.8 kHz: next to the top
        self.assertAlmostEqual(loud.db, -23, delta=0.5)  # a sine at 0.1 of full scale: -23 dB


class ReadingTest(unittest.TestCase):
    def test_nothing_until_it_listens(self):
        self.assertEqual(Microphone("plughw:9,0").reading(), {"listening": False})

    def test_what_it_hears(self):
        mic = Microphone("plughw:9,0")
        mic._loudness = loud = Loudness()
        feed(loud, -60, 1, random.Random(8))
        r = mic.reading()
        self.assertTrue(r["listening"])
        self.assertAlmostEqual(r["db"], -60, delta=1.5)
        self.assertLess(r["quiet"], r["full"])
        self.assertEqual(len(r["bands"]), BANDS)


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
