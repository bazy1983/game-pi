import random
import unittest

from ledgames.colors import OFF, WHITE
from ledgames.games.morse import (
    DIFFICULTIES,
    END_FLASH,
    INTRO_TIME,
    LAST_CHANCE,
    MORSE,
    WORDS,
    Morse,
    timeline,
)

DT = 1 / 30
N = 40


def make(players=1, difficulty="easy", seed=1, words=None):
    ids = [f"p{i}" for i in range(players)]
    return Morse(N, difficulty, {}, players=ids, rng=random.Random(seed), words=words)


def run(g, seconds):
    for _ in range(round(seconds / DT)):
        g.update(DT)


def guess(g, idx, word):
    g.on_input(f"p{idx}", {"guess": word})


def wrong_word(g):
    return "z" * len(g.word) if g.word != "z" * len(g.word) else "y" * len(g.word)


def frame(g):
    pixels = [OFF] * N
    g.render(pixels)
    return pixels


class WordsTest(unittest.TestCase):
    def test_word_list(self):
        self.assertEqual(len(WORDS), 200)
        self.assertEqual(len(set(WORDS)), 200)
        self.assertTrue(all(3 <= len(w) <= 6 and set(w) <= set(MORSE) for w in WORDS))

    def test_word_length_follows_difficulty(self):
        for difficulty, cfg in DIFFICULTIES.items():
            for seed in range(20):
                self.assertIn(len(make(difficulty=difficulty, seed=seed).word), cfg.lengths)


class TimelineTest(unittest.TestCase):
    def test_standard_timing(self):
        # e = ".", t = "-": dot (1), letter gap (3), dash (3), then 3 dark before the flash
        pulses, flash, total = timeline("et", 1.0)
        self.assertEqual(pulses, [(0.0, 1.0, 0), (4.0, 7.0, 1)])
        self.assertEqual(flash, 10.0)
        self.assertGreater(total, flash + END_FLASH)

    def test_gap_inside_a_letter_is_one_dot(self):
        pulses, _, _ = timeline("a", 1.0)  # .-
        self.assertEqual(pulses, [(0.0, 1.0, 0), (2.0, 5.0, 0)])


class PlaybackTest(unittest.TestCase):
    def test_strip_flashes_the_word_then_blue(self):
        g = make(words=["sos"])  # ... --- ...
        self.assertEqual(frame(g), [OFF] * N)  # dark during the intro
        run(g, INTRO_TIME + DT)
        self.assertEqual(g.stage, "play")
        self.assertEqual(frame(g), [WHITE] * N)  # the first dot
        self.assertEqual(g.state()["letter"], 0)
        g.timer = g.flash_at + 0.01
        px = frame(g)
        self.assertEqual(px[0], px[-1])
        self.assertGreater(px[0][2], px[0][0])  # blue
        self.assertIsNone(g.state()["letter"])

    def test_the_word_repeats_on_easy(self):
        g = make()
        run(g, INTRO_TIME + g.play_time * 3 + 0.5)
        self.assertEqual(g.play, 4)
        self.assertEqual(g.status, "playing")

    def test_word_is_secret_until_the_end(self):
        g = make()
        run(g, INTRO_TIME + 1)
        self.assertIsNone(g.state()["word"])
        guess(g, 0, g.word)
        self.assertEqual(g.state()["word"], g.word)


class GuessTest(unittest.TestCase):
    def test_right_guess_wins(self):
        g = make()
        run(g, INTRO_TIME + 1)
        guess(g, 0, g.word.upper() + " ")
        self.assertEqual(g.status, "won")
        self.assertEqual(g.winners, [0])

    def test_guesses_during_the_intro_are_ignored(self):
        g = make()
        guess(g, 0, g.word)
        self.assertEqual(g.status, "playing")

    def test_wrong_length_or_junk_costs_nothing(self):
        g = make()
        run(g, INTRO_TIME + 1)
        for junk in ("ab", "abcdefg", "a1c", 123, None):
            g.on_input("p0", {"guess": junk})
        self.assertEqual(g.attempts, [5])

    def test_running_out_of_attempts_loses(self):
        for difficulty, cfg in DIFFICULTIES.items():
            g = make(difficulty=difficulty)
            run(g, INTRO_TIME + 1)
            for k in range(cfg.attempts):
                self.assertEqual(g.status, "playing", (difficulty, k))
                guess(g, 0, wrong_word(g))
            self.assertEqual(g.status, "lost", difficulty)
            self.assertEqual(g.wrong, [cfg.attempts])

    def test_hard_plays_three_times_then_a_last_chance(self):
        g = make(difficulty="hard")
        run(g, INTRO_TIME + g.play_time * 3 - 0.1)
        self.assertEqual((g.stage, g.play), ("play", 3))
        run(g, 0.2)
        self.assertEqual(g.stage, "last")
        self.assertEqual(g.state()["last_chance"], 10)
        run(g, LAST_CHANCE - 0.5)
        guess(g, 0, g.word)  # still in time
        self.assertEqual(g.status, "won")

    def test_hard_loses_when_nobody_guesses_in_time(self):
        g = make(difficulty="hard")
        run(g, INTRO_TIME + g.play_time * 3 + LAST_CHANCE + 0.5)
        self.assertEqual(g.status, "lost")
        self.assertEqual(g.state()["word"], g.word)


class MultiplayerTest(unittest.TestCase):
    def test_first_right_guess_wins(self):
        g = make(players=3)
        run(g, INTRO_TIME + 1)
        guess(g, 1, wrong_word(g))
        guess(g, 2, g.word)
        guess(g, 0, g.word)  # too late
        self.assertEqual(g.winners, [2])

    def test_each_player_has_their_own_attempts(self):
        g = make(players=2, difficulty="hard")
        run(g, INTRO_TIME + 1)
        guess(g, 0, wrong_word(g))
        guess(g, 0, wrong_word(g))
        self.assertTrue(g.state()["players"][0]["out"])
        guess(g, 0, g.word)  # out: ignored
        self.assertEqual(g.status, "playing")
        self.assertEqual(g.state()["players"][1]["attempts"], 2)
        guess(g, 1, wrong_word(g))
        guess(g, 1, wrong_word(g))
        self.assertEqual(g.status, "lost")  # everyone's out

    def test_leaving_when_everyone_else_is_out_ends_it(self):
        g = make(players=2, difficulty="hard")
        run(g, INTRO_TIME + 1)
        guess(g, 0, wrong_word(g))
        guess(g, 0, wrong_word(g))
        g.on_leave("p1")
        self.assertEqual(g.status, "lost")

    def test_game_finishes_after_its_animation(self):
        g = make(players=2)
        run(g, INTRO_TIME + 1)
        guess(g, 0, g.word)
        run(g, 15)
        self.assertTrue(g.finished)


if __name__ == "__main__":
    unittest.main()
