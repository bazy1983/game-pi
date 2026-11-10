import random
import unittest

from ledgames.colors import OFF
from ledgames.games.red_light import (
    CLIMB_TIME,
    COUNTDOWN,
    DIFFICULTIES,
    JUDGE_DELAY,
    MAX_TAP_AGE,
    RedLight,
)

DT = 1 / 30
N = 60


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


def make(players=1, difficulty="easy", solo="clock", seed=1):
    ids = [f"p{i}" for i in range(players)]
    clock = Clock()
    g = RedLight(N, difficulty, {"solo": solo}, players=ids, rng=random.Random(seed), clock=clock)
    g.test_clock = clock
    return g


def step(g, seconds):
    for _ in range(round(seconds / DT)):
        g.update(DT)
        g.test_clock.t += DT


def until(g, cond, limit=60):
    for _ in range(round(limit / DT)):
        if cond():
            return
        step(g, DT)
    raise AssertionError("condition never met")


def hold(g, i, on=True, ago=0.0):
    g.on_input(f"p{i}", {"hold": on, "at": g.test_clock.t - ago})


def to_red(g):
    """Run to the start of a real red, after the countdown."""
    until(g, lambda: g.stage == "race")
    until(g, lambda: g.light == "red")


class LightsTest(unittest.TestCase):
    def test_countdown_then_green(self):
        g = make()
        self.assertEqual(g.state()["countdown"], 3)
        self.assertEqual(g.state()["light"], "red")
        step(g, COUNTDOWN + DT)
        self.assertEqual((g.stage, g.light), ("race", "green"))

    def test_warning_only_on_easy_and_medium(self):
        for difficulty, cfg in DIFFICULTIES.items():
            g = make(difficulty=difficulty)
            seen = set()
            until(g, lambda: g.stage == "race")
            for _ in range(round(20 / DT)):
                seen.add(g.light)
                step(g, DT)
            self.assertEqual("yellow" in seen, cfg.warning > 0, difficulty)
            self.assertTrue({"green", "red"} <= seen)

    def test_hard_has_fake_outs_that_catch_nobody(self):
        g = make(players=2, difficulty="hard", seed=3)  # no clock to end it
        until(g, lambda: g.stage == "race")
        until(g, lambda: g.fake is not None and g.t >= g.fake[0], limit=120)
        self.assertEqual((g.light, g.shown), ("green", "red"))
        hold(g, 0)
        step(g, 0.25)
        self.assertFalse(g.stunned[0])


class ClimbTest(unittest.TestCase):
    def test_holding_climbs(self):
        g = make()
        until(g, lambda: g.stage == "race")
        hold(g, 0)
        step(g, 1.0)
        self.assertAlmostEqual(g.pos[0], 1 / CLIMB_TIME, delta=0.01)
        hold(g, 0, False)
        before = g.pos[0]
        step(g, 0.5)
        self.assertEqual(g.pos[0], before)

    def test_a_late_release_counts_from_when_it_happened(self):
        g = make()
        until(g, lambda: g.stage == "race")
        hold(g, 0)
        step(g, 1.0)
        hold(g, 0, False, ago=0.2)  # arrived 0.2 s late
        self.assertAlmostEqual(g.pos[0], 0.8 / CLIMB_TIME, delta=0.01)
        hold(g, 0)
        hold(g, 0, False, ago=5)  # can't go back further than MAX_TAP_AGE
        self.assertAlmostEqual(g.pos[0], 0.8 / CLIMB_TIME - MAX_TAP_AGE / CLIMB_TIME, delta=0.01)

    def test_reaching_the_top_wins(self):
        g = make()
        until(g, lambda: g.stage == "race")
        g.pos[0] = 0.99
        hold(g, 0)
        step(g, 0.5)
        self.assertEqual(g.status, "won")
        self.assertEqual(g.winner, 0)
        self.assertIsNotNone(g.state()["finish_time"])


class CaughtTest(unittest.TestCase):
    def test_holding_through_red_slides_back(self):
        g = make()
        to_red(g)
        g.pos[0] = 0.5
        hold(g, 0)
        cfg = DIFFICULTIES["easy"]
        step(g, cfg.grace + JUDGE_DELAY + DT)
        self.assertTrue(g.stunned[0])
        climbed = (cfg.grace + JUDGE_DELAY) / CLIMB_TIME  # still moving until judged
        self.assertAlmostEqual(g.pos[0], 0.5 + climbed - cfg.penalty, delta=0.02)
        self.assertTrue(g.state()["players"][0]["caught"])
        stuck = g.pos[0]
        step(g, 0.5)
        self.assertEqual(g.pos[0], stuck)  # can't move until green
        until(g, lambda: g.light == "green")
        self.assertFalse(g.stunned[0])

    def test_letting_go_within_the_grace_is_safe(self):
        g = make()
        to_red(g)
        g.pos[0] = 0.5
        hold(g, 0)
        step(g, 0.3)
        hold(g, 0, False)
        step(g, 1.0)
        self.assertFalse(g.stunned[0])

    def test_a_delayed_release_from_within_the_grace_is_safe(self):
        g = make()
        to_red(g)
        hold(g, 0)
        cfg = DIFFICULTIES["easy"]
        step(g, cfg.grace + 0.2)  # the release is still on its way…
        hold(g, 0, False, ago=0.25)  # …it happened before the grace ran out
        step(g, 0.5)
        self.assertFalse(g.stunned[0])

    def test_starting_to_move_during_red_is_caught(self):
        g = make()
        to_red(g)
        step(g, 1.5)
        hold(g, 0)
        self.assertTrue(g.stunned[0])

    def test_penalty_never_goes_below_the_start(self):
        g = make(difficulty="hard")
        to_red(g)
        g.pos[0] = 0.1
        hold(g, 0)
        step(g, 1.0)
        self.assertEqual(g.pos[0], 0.0)


class SoloTest(unittest.TestCase):
    def test_clock_runs_out(self):
        g = make(solo="clock")
        step(g, COUNTDOWN + DIFFICULTIES["easy"].time_limit + 0.5)
        self.assertEqual(g.status, "lost")

    def test_the_computer_races_and_can_win(self):
        g = make(solo="computer", difficulty="medium")
        self.assertEqual(len(g.state()["players"]), 2)
        self.assertTrue(g.state()["players"][1]["cpu"])
        until(g, lambda: g.status != "playing", limit=300)
        self.assertEqual((g.status, g.winner), ("lost", 1))

    def test_the_computer_gets_caught_sometimes(self):
        caught = 0
        for seed in range(10):
            g = make(solo="computer", difficulty="easy", seed=seed)
            until(g, lambda: g.status != "playing", limit=300)
            caught += g.caught[1]
        self.assertGreater(caught, 0)


class MultiplayerTest(unittest.TestCase):
    def test_first_to_the_top_wins(self):
        g = make(players=3)
        self.assertEqual(g.mode, "race")
        until(g, lambda: g.stage == "race")
        g.pos[2] = 0.99
        hold(g, 2)
        step(g, 0.5)
        self.assertEqual((g.status, g.winner), ("won", 2))

    def test_a_player_who_leaves_disappears(self):
        g = make(players=2)
        until(g, lambda: g.stage == "race")
        hold(g, 1)
        g.on_leave("p1")
        step(g, 1)
        self.assertEqual(g.pos[1], 0.0)
        self.assertTrue(g.state()["players"][1]["left"])

    def test_render(self):
        for n in (3, 10, 60):
            g = RedLight(n, "hard", {}, players=["a", "b"], rng=random.Random(1))
            pixels = [OFF] * n
            for _ in range(200):
                g.update(DT)
                g.render(pixels)
            self.assertEqual(len(pixels), n)


if __name__ == "__main__":
    unittest.main()
