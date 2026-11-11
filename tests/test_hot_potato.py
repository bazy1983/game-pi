import random
import unittest

from ledgames.colors import OFF
from ledgames.games.hot_potato import (
    BOOM_TIME,
    COUNTDOWN,
    DIFFICULTIES,
    DROP_TIME,
    JUDGE_DELAY,
    MAX_TAP_AGE,
    HotPotato,
)

DT = 1 / 30
N = 60


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


def make(players=3, difficulty="easy", computers="3", seed=1):
    ids = [f"p{i}" for i in range(players)]
    clock = Clock()
    g = HotPotato(N, difficulty, {"computers": computers}, players=ids, rng=random.Random(seed), clock=clock)
    g.test_clock = clock
    return g


def step(g, seconds):
    for _ in range(round(seconds / DT)):
        g.update(DT)
        g.test_clock.t += DT


def until(g, cond, limit=120):
    for _ in range(round(limit / DT)):
        if cond():
            return
        step(g, DT)
    raise AssertionError("condition never met")


def throw(g, i, ago=0.0):
    g.on_input(f"p{i}", {"throw": True, "at": g.test_clock.t - ago})


def ready(g):
    until(g, lambda: g.state()["ready"])


class RoundTest(unittest.TestCase):
    def test_countdown_then_the_potato_drops_in(self):
        g = make()
        self.assertEqual(g.state()["countdown"], 3)
        self.assertIsNone(g.state()["holder"])
        step(g, COUNTDOWN + DT)
        self.assertEqual(g.stage, "drop")
        self.assertTrue(g.state()["flying"])
        step(g, DROP_TIME + DT)
        self.assertEqual(g.stage, "play")
        self.assertFalse(g.state()["flying"])

    def test_cant_throw_until_caught(self):
        g = make()
        until(g, lambda: g.stage == "play")
        holder = g.holder
        throw(g, holder)  # still in the catch time
        self.assertEqual(g.holder, holder)
        ready(g)
        throw(g, holder)
        self.assertNotEqual(g.holder, holder)
        self.assertTrue(g.state()["flying"])

    def test_only_the_holder_can_throw(self):
        g = make()
        ready(g)
        holder = g.holder
        for i in range(3):
            if i != holder:
                throw(g, i)
        self.assertEqual(g.holder, holder)
        self.assertFalse(g.state()["flying"])

    def test_throws_go_to_random_players_still_in(self):
        targets = set()
        for seed in range(20):
            g = make(players=4, seed=seed)
            g.out = [3]
            ready(g)
            holder = g.holder
            throw(g, holder)
            self.assertNotIn(g.holder, (holder, 3))
            targets.add(g.holder)
        self.assertGreater(len(targets), 1)

    def test_the_fuse_puts_the_holder_out_and_play_continues(self):
        g = make()
        until(g, lambda: g.stage == "play")
        victim = g.holder
        g.boom_at = g.t + 0.5
        step(g, 0.5 + JUDGE_DELAY + DT)
        self.assertEqual((g.stage, g.victim), ("boom", victim))
        self.assertTrue(g.state()["players"][victim]["out"])
        step(g, BOOM_TIME + DT)
        self.assertEqual((g.stage, g.round), ("drop", 2))
        self.assertNotIn(victim, g.zones)
        self.assertEqual(len(g.zones), 2)

    def test_last_one_standing_wins(self):
        g = make(players=2)
        until(g, lambda: g.stage == "play")
        survivor = 1 - g.holder
        g.boom_at = g.t
        step(g, JUDGE_DELAY + BOOM_TIME + 2 * DT)
        self.assertEqual((g.status, g.winner), ("won", survivor))
        step(g, 10)
        self.assertTrue(g.finished)

    def test_rounds_get_faster(self):
        g = make(players=6)
        fuses = []
        for _ in range(4):
            until(g, lambda: g.stage == "drop")
            fuses.append(g.boom_at - g.round_start - DROP_TIME)
            until(g, lambda: g.stage == "boom", limit=200)
        lo, hi = DIFFICULTIES["easy"].fuse
        self.assertTrue(lo <= fuses[0] <= hi)
        self.assertLess(fuses[3], hi * 0.88**3 + 0.01)


class TimingTest(unittest.TestCase):
    def test_a_throw_that_was_on_its_way_still_counts(self):
        g = make()
        ready(g)
        holder = g.holder
        g.boom_at = g.t
        step(g, 0.2)  # the fuse ran out 0.2 s ago, but…
        throw(g, holder, ago=0.25)  # …the throw happened before that
        self.assertNotEqual(g.holder, holder)
        step(g, JUDGE_DELAY)
        self.assertNotEqual(g.victim, holder)  # in the air: it was the target's

    def test_a_throw_after_the_fuse_is_too_late(self):
        g = make()
        ready(g)
        holder = g.holder
        g.boom_at = g.t
        step(g, 0.2)
        throw(g, holder, ago=0.1)
        step(g, JUDGE_DELAY)
        self.assertEqual(g.victim, holder)

    def test_late_messages_only_count_back_so_far(self):
        g = make()
        ready(g)
        holder = g.holder
        g.boom_at = g.t
        step(g, 0.25)
        throw(g, holder, ago=5)  # claims long ago: only MAX_TAP_AGE counts
        self.assertGreater(MAX_TAP_AGE, 0.25 - DT)
        self.assertNotEqual(g.holder, holder)


class ComputerTest(unittest.TestCase):
    def test_solo_adds_computer_players(self):
        g = make(players=1, computers="5")
        players = g.state()["players"]
        self.assertEqual(len(players), 6)
        self.assertEqual([p["cpu"] for p in players], [False] + [True] * 5)
        self.assertEqual(len(make(players=2).state()["players"]), 2)  # not with friends

    def test_computers_throw_it_on(self):
        g = make(players=1, computers="2", seed=4)
        until(g, lambda: g.stage == "play" and g.holder != 0)
        cpu = g.holder
        until(g, lambda: g.holder != cpu, limit=5)

    def test_solo_ends_when_you_are_out(self):
        g = make(players=1, computers="3", seed=2)
        until(g, lambda: g.stage == "play")
        until(g, lambda: g.holder == 0 and not g.flight)
        g.boom_at = g.t
        step(g, JUDGE_DELAY + DT)
        self.assertEqual(g.status, "lost")
        self.assertIsNone(g.winner)

    def test_outlasting_the_computers_wins(self):
        for seed in range(30):
            g = make(players=1, computers="2", seed=seed)
            while g.status == "playing":
                if g.holder == 0 and g.state()["ready"]:
                    throw(g, 0)  # a fast player
                step(g, DT)
            if g.status == "won":
                self.assertEqual(g.winner, 0)
                return
        self.fail("never won")


class LeaveTest(unittest.TestCase):
    def test_leaving_with_the_potato_passes_it_on(self):
        g = make(players=3)
        until(g, lambda: g.stage == "play")
        holder = g.holder
        g.on_leave(f"p{holder}")
        self.assertNotEqual(g.holder, holder)
        self.assertTrue(g.state()["players"][holder]["left"])

    def test_everyone_else_leaving_ends_it(self):
        g = make(players=2)
        until(g, lambda: g.stage == "play")
        g.on_leave("p1")
        self.assertEqual((g.status, g.winner), ("won", 0))


class RenderTest(unittest.TestCase):
    def test_render_every_stage(self):
        for n in (3, 10, 60, 250):
            for players, computers in ((2, "2"), (6, "2"), (1, "5")):
                g = HotPotato(n, "hard", {"computers": computers}, players=[f"p{i}" for i in range(players)], rng=random.Random(1))
                pixels = [OFF] * n
                for _ in range(1500):
                    g.update(DT)
                    g.render(pixels)
                    if g.finished:
                        break
                self.assertEqual(len(pixels), n)
                self.assertTrue(all(len(p) == 3 and all(0 <= c <= 255 for c in p) for p in pixels))

    def test_the_potato_shows_in_the_holders_zone(self):
        g = make()
        until(g, lambda: g.stage == "play" and not g.flight)
        pixels = [OFF] * N
        g.render(pixels)
        start, end = g._zone(g.holder)
        mid = (start + end) // 2
        r, gr, b = pixels[mid]
        self.assertGreater(r, 100)  # orange-red
        self.assertEqual(b, 0)


if __name__ == "__main__":
    unittest.main()
