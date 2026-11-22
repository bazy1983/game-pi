"""Every game's sounds: each one it plays exists in every pack, and the
sounds that could change how a game plays follow its rules."""

import random
import unittest

from ledgames.games import GAMES
from ledgames.games.base import SOUND_SETTING
from ledgames.games.hot_potato import HotPotato
from ledgames.games.morse import DIFFICULTIES as MORSE_DIFFICULTIES
from ledgames.games.morse import Morse, timeline
from ledgames.games.red_light import RedLight
from ledgames.games.simon import Simon
from ledgames.sounds import PACKS, SOUNDS

DT = 1 / 30


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def actions(game, rng: random.Random) -> dict:
    """A random action of any game's kind: each game ignores the others'."""
    colors = [c.name for c in getattr(game, "colors", []) if hasattr(c, "name")]
    return rng.choice([
        {"tap": True, "at": game.clock(), "button": rng.randrange(3)},
        {"fire": rng.choice(colors or ["red"])},
        {"press": rng.choice(colors or ["red"])},
        {"guess": "".join(rng.choice("abcdefghij") for _ in range(len(getattr(game, "word", "abc"))))},
        {"hold": rng.random() < 0.6, "at": game.clock()},
        {"throw": True, "at": game.clock()},
        {"aim": rng.randrange(game.num_leds)},
        {"dig": rng.randrange(game.num_leds)},
    ])


def play_through(cls, players: int, pack: str, seed: int, seconds: float = 90.0) -> list[str]:
    clock = Clock()
    ids = [f"p{i}" for i in range(players)]
    info = cls.info
    settings = {s.id: s.default for s in info.settings} | {"sound": pack}
    game = cls(120, info.default_difficulty, settings, players=ids, rng=random.Random(seed), clock=clock)
    rng = random.Random(seed)
    heard = list(game.sounds)
    for _ in range(int(seconds / DT)):
        if game.finished:
            break
        clock.t += DT
        if rng.random() < 0.3:
            game.on_input(rng.choice(ids), actions(game, rng))
        game.update(DT)
        heard += game.sounds
        game.sounds.clear()
    return heard


class EveryGameTest(unittest.TestCase):
    def test_every_game_has_the_sound_setting(self):
        for cls in GAMES.values():
            self.assertIn(SOUND_SETTING, cls.info.settings, cls.info.id)

    def test_every_sound_played_exists_in_every_pack(self):
        for cls in GAMES.values():
            for players in (1, 2):
                if players > cls.info.max_players:
                    continue
                for pack in PACKS:
                    for seed in range(3):
                        heard = play_through(cls, players, pack, seed)
                        with self.subTest(game=cls.info.id, players=players, pack=pack, seed=seed):
                            self.assertTrue(heard, "no sound at all")
                            self.assertEqual([n for n in heard if n not in SOUNDS], [])
                            self.assertTrue(all(n.startswith(pack + "/") for n in heard))

    def test_off_is_silent(self):
        for cls in GAMES.values():
            self.assertEqual(play_through(cls, 1, "off", 0, seconds=20), [], cls.info.id)


class FairnessTest(unittest.TestCase):
    def test_morse_has_a_beep_for_every_dot_and_dash(self):
        for name, cfg in MORSE_DIFFICULTIES.items():
            pulses, _, _ = timeline("ab", cfg.unit)  # a: .-  b: -...
            for start, end, _ in pulses:
                self.assertIn(f"modern/beep_{round((end - start) * 1000)}", SOUNDS, name)

    def test_morse_beeps_each_pulse_once_per_playback(self):
        g = Morse(60, "easy", {"sound": "modern"}, players=["a"], rng=random.Random(1), words=["sos"])
        beeps = []
        while g.playback < 3:  # two whole playbacks
            beeps += [n for n in g.sounds if "beep_" in n]
            g.sounds.clear()
            g.update(DT)
        self.assertEqual(beeps, (["modern/beep_350"] * 3 + ["modern/beep_1050"] * 3 + ["modern/beep_350"] * 3) * 2)

    def test_simon_plays_each_steps_note_and_presses_only_when_shown(self):
        g = Simon(60, "easy", {"sound": "retro"}, players=["a"], rng=random.Random(2))
        notes = []
        while g.stage != "input":
            g.update(DT)
            notes += g.sounds
            g.sounds.clear()
        self.assertEqual(notes, [f"retro/note{c + 1}" for c in g.sequence])
        g.on_input("a", {"press": g.colors[g.sequence[0]].name})
        self.assertEqual(g.sounds[0], f"retro/note{g.sequence[0] + 1}")

        together = Simon(60, "easy", {"sound": "retro", "mode": "together"}, players=["a", "b"], rng=random.Random(2))
        while together.stage != "input":
            together.update(DT)
        together.sounds.clear()
        together.on_input("a", {"press": together.colors[together.sequence[0]].name})
        self.assertEqual(together.sounds, [])  # the others could copy it

    def test_red_light_fake_outs_sound_like_red(self):
        g = RedLight(60, "hard", {"sound": "modern"}, players=["a", "b"], rng=random.Random(3))
        calls = []
        saw_fake = False
        for _ in range(int(60 / DT)):
            g.update(DT)
            calls += g.sounds
            g.sounds.clear()
            if g.fake and g.fake[0] <= g.t < g.fake[1]:
                saw_fake = True
                self.assertEqual(calls[-1], "modern/light_red")
        self.assertTrue(saw_fake, "no fake-out to check")
        self.assertEqual(calls[:4], ["modern/count", "modern/count", "modern/count", "modern/light_green"])

    def test_hot_potato_fuse_ticks_faster_as_it_heats(self):
        g = HotPotato(60, "easy", {"sound": "modern", "computers": "2"}, players=["a"], rng=random.Random(4))
        ticks = []
        while g.stage != "boom":
            g.update(DT)
            if "modern/tick" in g.sounds:
                ticks.append(g.t)
            g.sounds.clear()
        gaps = [b - a for a, b in zip(ticks, ticks[1:])]
        self.assertGreater(len(gaps), 3)
        self.assertLess(gaps[-1], gaps[0])


if __name__ == "__main__":
    unittest.main()
