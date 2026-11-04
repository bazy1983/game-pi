import random
import unittest

from ledgames.colors import OFF
from ledgames.games.sumo import COUNTDOWN, CPU_TAP_EVERY, PLAYER_COLORS, Sumo

DT = 1 / 30
N = 40
RED, BLUE = PLAYER_COLORS[0].led, PLAYER_COLORS[1].led


def make(players=2, difficulty="easy"):
    ids = [f"p{i}" for i in range(players)]
    return Sumo(N, difficulty, {}, players=ids, rng=random.Random(1))


def run(g, seconds):
    for _ in range(round(seconds / DT)):
        g.update(DT)


def start(g):
    run(g, COUNTDOWN + DT)


def tap(g, idx, times=1):
    """Correct taps: follows the button sequence on medium and hard."""
    for _ in range(times):
        g.on_input(f"p{idx}", {"tap": True, "button": g.next_button[idx]})


def press(g, idx, button):
    g.on_input(f"p{idx}", {"tap": True, "button": button})


def strip(g):
    pixels = [OFF] * N
    g.render(pixels)
    return pixels


class SumoTest(unittest.TestCase):
    def test_starts_with_a_quarter_each(self):
        g = make()
        self.assertEqual(strip(g), [RED] * 10 + [OFF] * 20 + [BLUE] * 10)

    def test_taps_during_the_countdown_dont_count(self):
        g = make()
        tap(g, 0, 5)
        self.assertEqual(g.lights, [10, 10])
        self.assertEqual(g.state()["countdown"], 3)
        start(g)
        self.assertEqual(g.state()["countdown"], 0)
        tap(g, 0)
        self.assertEqual(g.lights, [11, 10])

    def test_fill_then_push(self):
        g = make()
        start(g)
        tap(g, 0, 12)
        tap(g, 1, 8)
        self.assertEqual(strip(g), [RED] * 22 + [BLUE] * 18)  # they've met
        tap(g, 1, 3)
        self.assertEqual(strip(g), [RED] * 19 + [BLUE] * 21)  # blue pushes red back
        self.assertEqual(g.status, "playing")

    def test_pushing_the_other_off_wins(self):
        g = make()
        start(g)
        tap(g, 1, 20)  # fill the gap
        tap(g, 1, 9)
        self.assertEqual(g.lights, [1, 39])
        self.assertEqual(g.status, "playing")
        tap(g, 1)
        self.assertEqual(g.status, "won")
        self.assertEqual(g.winner, 1)
        self.assertEqual(g.lights, [0, N])
        tap(g, 0)  # too late
        self.assertEqual(g.taps[0], 0)
        run(g, 10)
        self.assertTrue(g.finished)

    def test_solo_computer_taps_at_its_pace(self):
        g = make(players=1, difficulty="easy")
        start(g)
        run(g, 3)
        self.assertAlmostEqual(g.taps[1], 3 / CPU_TAP_EVERY["easy"], delta=1)
        self.assertTrue(g.state()["players"][1]["cpu"])

    def test_solo_win_and_loss(self):
        g = make(players=1)
        start(g)
        tap(g, 0, 60)  # far faster than the computer
        self.assertEqual(g.status, "won")
        self.assertEqual(g.winner, 0)

        g = make(players=1, difficulty="hard")
        start(g)
        run(g, 30)  # never tap
        self.assertEqual(g.status, "lost")
        self.assertEqual(g.winner, 1)

    def test_other_player_leaving_forfeits(self):
        g = make()
        start(g)
        g.on_leave("p0")
        self.assertEqual(g.winner, 1)
        self.assertTrue(g.state()["forfeit"])

    def test_buttons_per_difficulty(self):
        self.assertEqual([make(difficulty=d).buttons for d in ("easy", "medium", "hard")], [1, 2, 3])
        self.assertEqual(make(players=1, difficulty="hard").buttons, 1)  # solo: one button

    def test_buttons_must_be_tapped_in_order(self):
        g = make(difficulty="hard")
        start(g)
        press(g, 0, 0)
        press(g, 0, 0)  # 1 again: nothing
        press(g, 0, 2)  # skipped 2: nothing
        self.assertEqual(g.lights[0], 11)
        press(g, 0, 1)
        press(g, 0, 2)
        press(g, 0, 0)  # and round again
        self.assertEqual(g.lights[0], 14)
        self.assertEqual(g.state()["players"][0]["next"], 1)
        self.assertEqual(g.next_button[1], 0)  # each player has their own sequence

    def test_registered(self):
        from ledgames.games import GAMES

        self.assertIs(GAMES["sumo"], Sumo)
        self.assertEqual(Sumo.info.max_players, 2)


if __name__ == "__main__":
    unittest.main()
