import tempfile
import unittest
from array import array
from pathlib import Path

from ledgames.sounds import PEAK, RATE, SOUNDS, chime, mix, retro, tone
from ledgames import speaker as speaker_module
from ledgames.speaker import Speaker, find_device, made_sounds, to_pcm, volume_level

PCM = """00-00: MAI PCM i2s-hifi-0 : MAI PCM i2s-hifi-0 : playback 1
01-00: Google voiceHAT SoundCard HiFi voicehat-hifi-0 : Google voiceHAT SoundCard HiFi voicehat-hifi-0 : playback 1 : capture 1
"""
CARDS = """ 0 [vc4hdmi        ]: vc4-hdmi - vc4-hdmi
                      vc4-hdmi
 1 [sndrpigooglevoi]: RPi-simple - snd_rpi_googlevoicehat_soundcar
                      snd_rpi_googlevoicehat_soundcard
"""


class FindDeviceTest(unittest.TestCase):
    def find(self, pcm: str, cards: str) -> str | None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "pcm").write_text(pcm)
            (Path(tmp) / "cards").write_text(cards)
            return find_device(Path(tmp) / "pcm", Path(tmp) / "cards")

    def test_skips_hdmi(self):
        self.assertEqual(self.find(PCM, CARDS), "plughw:1,0")

    def test_only_hdmi(self):
        self.assertIsNone(self.find(PCM.splitlines()[0] + "\n", CARDS))

    def test_no_sound_cards(self):
        self.assertIsNone(find_device(Path("/nonexistent/pcm")))


class SoundTest(unittest.TestCase):
    def test_pcm_leaves_headroom(self):
        self.assertEqual(list(array("h", to_pcm([1.0, -1.0, 0.0]))), [29490, -29490, 0])

    def test_volume_is_squared(self):
        self.assertEqual([volume_level(v) for v in (0, 0.5, 1)], [0, 0.25, 1])

    def test_chime_stays_in_range(self):
        sound = chime()
        self.assertEqual(len(sound), int(RATE * 0.9))
        self.assertLessEqual(max(abs(s) for s in sound), 1.0)

    def test_every_sound_is_short_and_in_range(self):
        for name, make in SOUNDS.items():
            sound = make()
            self.assertTrue(0 < len(sound) <= 2.5 * RATE, name)
            self.assertLessEqual(max(abs(v) for v in sound), 1.0, name)

    def test_mix_lines_up_and_limits(self):
        out = mix((0, [0.6, 0.6]), (1 / RATE, [0.6]))
        self.assertEqual(len(out), 2)
        self.assertAlmostEqual(out[0], 0.6 * PEAK / 1.2)
        self.assertAlmostEqual(out[1], PEAK)

    def test_tone_starts_and_ends_quietly(self):
        t = tone(0.1, 440, vol=0.5)
        self.assertLess(abs(t[0]), 0.01)
        self.assertLess(abs(t[-1]), 0.01)

    def test_retro_is_frames_of_fixed_levels(self):
        out = retro([("pure", 31, 15), ("", 0, 0), ("low", 0, 0)])
        self.assertEqual(len(out), 3 * RATE // 60)
        frame = RATE // 60
        self.assertEqual({abs(v) for v in out[:frame]}, {0.6})  # a square wave at full volume
        self.assertEqual(set(out[frame:]), {0.0})


class SettingsTest(unittest.TestCase):
    def test_update(self):
        sp = Speaker(device=None)
        self.assertFalse(sp.available)
        self.assertIsNone(sp.update({"volume": 0.8, "on": False}))
        self.assertEqual(sp.settings(), {"on": False, "volume": 0.8})
        for bad in ({"volume": 1.5}, {"volume": "1"}, {"volume": True}, {"on": "yes"}):
            self.assertTrue(sp.update(bad), bad)
        self.assertEqual(sp.settings(), {"on": False, "volume": 0.8})


class FakeSound:
    def __init__(self, buffer):
        self.length = len(buffer)
        self.volume = None
        self.plays = 0
        self.stops = 0

    def stop(self):
        self.stops += 1

    def set_volume(self, v):
        self.volume = v

    def play(self):
        self.plays += 1


class FakeMixer:
    Sound = FakeSound

    def __init__(self):
        self.stops = 0
        self.closed = False

    def get_busy(self):
        return False

    def set_num_channels(self, n):
        pass

    def stop(self):
        self.stops += 1

    def quit(self):
        self.closed = True


class PlayTest(unittest.IsolatedAsyncioTestCase):
    async def test_opens_once_and_plays(self):
        opened = []
        mixer = FakeMixer()
        sp = Speaker(device="plughw:1,0", opener=lambda dev: opened.append(dev) or mixer)
        self.assertFalse(sp.play("chime"))  # not open yet
        await sp.start()
        self.assertEqual(opened, ["plughw:1,0"])
        sp.volume = 0.5
        self.assertTrue(sp.play("chime"))
        self.assertTrue(sp.play("chime"))
        sound = sp._sounds["chime"]
        self.assertEqual((sound.plays, sound.volume, sound.length), (2, 0.25, int(RATE * 0.9) * 2))
        self.assertEqual(sound.stops, 2)  # the same sound starts over
        self.assertEqual(mixer.stops, 0)
        self.assertTrue(sp.play("retro/hit", alone=True))
        self.assertEqual(mixer.stops, 1)  # cuts off everything
        self.assertFalse(sp.play("retro/nope"))
        sp.update({"on": False})
        self.assertFalse(sp.play("chime"))
        sp.close()
        self.assertTrue(mixer.closed)

    async def test_a_sound_card_that_wont_open(self):
        def fail(dev):
            raise RuntimeError("ALSA: no such device")

        sp = Speaker(device="plughw:9,9", opener=fail)
        with self.assertLogs("ledgames.speaker", "WARNING"):
            await sp.start()
        self.assertIsNone(sp.mixer)
        self.assertFalse(sp.play("chime"))

    async def test_no_speaker_doesnt_open(self):
        sp = Speaker(device=None, opener=lambda dev: self.fail("opened"))
        await sp.start()
        self.assertFalse(sp.play("chime"))



class CacheTest(unittest.TestCase):
    def test_made_once_then_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "sounds.cache"
            first = made_sounds(cache)
            self.assertTrue(cache.exists())
            self.assertEqual(set(first), set(SOUNDS))
            self.assertEqual(first["chime"], to_pcm(chime()))
            real = speaker_module.to_pcm
            speaker_module.to_pcm = lambda s: self.fail("made again")
            try:
                self.assertEqual(made_sounds(cache), first)
            finally:
                speaker_module.to_pcm = real

    def test_a_bad_cache_is_remade(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "sounds.cache"
            cache.write_bytes(b"not a cache")
            self.assertEqual(set(made_sounds(cache)), set(SOUNDS))
            self.assertEqual(set(made_sounds(cache)), set(SOUNDS))


if __name__ == "__main__":
    unittest.main()
