import random
import unittest

from ledgames.colors import OFF, RED, WHITE
from ledgames.games.tower import (
    COUNTDOWN,
    CRUMBLE_TIME,
    CUT_TIME,
    FALL_TIME,
    MAX_TAP_AGE,
    PERFECT_STREAK,
    TOP_TIME,
    Tower,
    rainbow,
)

DT = 1 / 30
N = 150


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make(players=1, difficulty="easy", n=N, goal="blocks"):
    clock = Clock()
    g = Tower(n, difficulty, {"goal": goal}, players=[f"p{i}" for i in range(players)], rng=random.Random(1), clock=clock)
    g.test_clock = clock
    return g


def step(g, seconds):
    for _ in range(round(seconds / DT)):
        g.update(DT)
        g.test_clock.now += DT


def ready(g):
    """Wait for the block to start sliding."""
    for _ in range(round(5 / DT)):
        if g.stage == "moving":
            return g
        step(g, DT)
    raise AssertionError(f"still {g.stage}")


def aim(g, offset):
    """Wait until the sliding block is `offset` LEDs from sitting on the tower."""
    ready(g)
    for _ in range(round(10 / DT)):
        if round(g.pos(g.t)) - g.top == offset:
            return
        step(g, DT)
    raise AssertionError(f"never reached {offset}")


def drop(g, i=0, offset=None):
    if offset is not None:
        aim(g, offset)
    g.on_input(f"p{i}", {"tap": True, "at": g.test_clock()})


def strip(g):
    pixels = [OFF] * g.num_leds
    g.render(pixels)
    return pixels


class StackTest(unittest.TestCase):
    def test_starts_with_a_foundation_then_slides(self):
        g = make()
        self.assertEqual(g.start_len, 9)
        self.assertEqual(g.stage, "intro")
        self.assertEqual(g.state()["countdown"], COUNTDOWN)
        drop(g)  # too early: ignored
        self.assertEqual(g.drops, 0)
        step(g, COUNTDOWN + DT)
        self.assertEqual(g.stage, "moving")
        self.assertEqual(round(g.pos(g.t)), g.top + g.length)  # starts a block above
        px = strip(g)
        self.assertTrue(all(px[i] != OFF for i in range(9)))  # the foundation
        self.assertEqual(px[g.top + g.length + 1], WHITE)

    def test_perfect_drop_keeps_the_block(self):
        g = make()
        drop(g, offset=0)
        self.assertEqual(g.state()["last"], {"cut": 0, "perfect": True, "grew": False, "missed": False})
        self.assertEqual((g.top, g.length, g.state()["blocks"]), (18, 9, 1))
        self.assertEqual(g.stage, "cut")
        step(g, CUT_TIME + DT)
        self.assertEqual(g.stage, "moving")

    def test_gap_is_cut_off(self):
        g = make()
        drop(g, offset=3)  # 3 LEDs above the tower
        self.assertEqual((g.top, g.length), (9 + 6, 6))
        self.assertEqual(g.layers[-1].bottom, 9)
        px = strip(g)
        self.assertEqual([i for i in range(N) if px[i] == RED], [15, 16, 17])  # what's cut is shown fading

    def test_overlap_is_cut_off(self):
        g = make()
        drop(g, offset=-4)  # sinks 4 LEDs into the tower
        self.assertEqual((g.top, g.length), (9 + 5, 5))
        self.assertEqual(g.cut, [5, 6, 7, 8])

    def test_blocks_speed_up(self):
        g = make()
        first = g.speed
        drop(g, offset=0)
        self.assertGreater(g.speed, first)

    def test_perfect_streak_grows_the_block_back(self):
        g = make()
        drop(g, offset=1)
        self.assertEqual(g.length, 8)
        for k in range(PERFECT_STREAK):
            drop(g, offset=0)
        self.assertTrue(g.last["grew"])
        self.assertEqual(g.length, 9)
        for k in range(PERFECT_STREAK):
            drop(g, offset=0)
        self.assertFalse(g.last["grew"])  # never bigger than the first block
        self.assertEqual(g.length, 9)

    def test_tap_counts_from_when_it_happened(self):
        g = make()
        aim(g, 0)
        when = g.test_clock()
        step(g, 0.2)  # the tap is on its way over Wi-Fi
        g.on_input("p0", {"tap": True, "at": when})
        self.assertTrue(g.last["perfect"])

        g = make()
        aim(g, 2)
        top = g.top
        expected = abs(round(g.pos(g.t - MAX_TAP_AGE)) - top)
        g.on_input("p0", {"tap": True, "at": g.test_clock() - 100})  # can't claim more than MAX_TAP_AGE ago
        self.assertEqual(g.last["cut"], expected)

    def test_a_miss_ends_solo(self):
        g = make()
        drop(g, offset=0)
        drop(g, offset=g.length)  # completely off
        st = g.state()
        self.assertTrue(st["last"]["missed"])
        self.assertEqual(st["stage"], "fall")
        self.assertEqual(st["players"][0]["blocks"], 1)
        step(g, FALL_TIME + CRUMBLE_TIME + DT)
        self.assertEqual(g.status, "lost")
        step(g, DT)
        self.assertTrue(g.finished)

    def test_topping_out_wins_solo(self):
        g = make(n=40)  # foundation of 2 LEDs (0.06 × 40)
        while g.stage != "topped":
            drop(g, offset=0)
        self.assertEqual(g.top, 40)
        self.assertTrue(g.scores[0].topped)
        step(g, TOP_TIME + DT)
        self.assertEqual(g.status, "won")
        step(g, 15)
        self.assertTrue(g.finished)

    def test_the_tower_is_never_cut_red(self):
        for k in range(100):
            r, g, b = rainbow(k)
            self.assertFalse(r > 200 and g < 80 and b < 80, (k, rainbow(k)))

    def test_taps_only_from_whoevers_turn_it_is(self):
        g = make(players=2)
        ready(g)
        drop(g, i=1)
        self.assertEqual(g.drops, 0)


class TurnsTest(unittest.TestCase):
    def test_each_builds_then_most_blocks_wins(self):
        g = make(players=3)
        for _ in range(3):
            drop(g, 0, offset=0)
        drop(g, 0, offset=g.length)  # miss: 3 blocks
        step(g, FALL_TIME + CRUMBLE_TIME + DT)
        self.assertEqual((g.turn, g.stage), (1, "intro"))
        self.assertEqual(len(g.layers), 1)  # a fresh tower
        self.assertEqual(g.state()["leader"], 0)

        for _ in range(5):
            drop(g, 1, offset=1)
        drop(g, 1, offset=-g.length)  # 5 blocks
        step(g, FALL_TIME + CRUMBLE_TIME + DT)
        self.assertEqual(g.state()["leader"], 1)

        drop(g, 2, offset=g.length)  # 0 blocks
        step(g, FALL_TIME + CRUMBLE_TIME + DT)
        self.assertEqual(g.status, "won")
        self.assertEqual(g.winners, [1])
        self.assertEqual([p["blocks"] for p in g.state()["players"]], [3, 5, 0])

    def test_tallest_tower_mode(self):
        g = make(players=2, goal="height")
        for _ in range(4):
            drop(g, 0, offset=2)  # 4 blocks, but they shrink: 9+7+5+3+1 = 25 LEDs
        drop(g, 0, offset=g.length)
        step(g, FALL_TIME + CRUMBLE_TIME + DT)
        for _ in range(3):
            drop(g, 1, offset=0)  # 3 full blocks: 9 × 4 = 36 LEDs
        drop(g, 1, offset=g.length)
        step(g, FALL_TIME + CRUMBLE_TIME + DT)
        self.assertEqual([(p["blocks"], p["height"]) for p in g.state()["players"]], [(4, 25), (3, 36)])
        self.assertEqual(g.winners, [1])
        self.assertEqual(g.state()["goal"], "height")

        g = make(players=2, goal="blocks")  # the same towers, counting blocks
        for _ in range(4):
            drop(g, 0, offset=2)
        drop(g, 0, offset=g.length)
        step(g, FALL_TIME + CRUMBLE_TIME + DT)
        for _ in range(3):
            drop(g, 1, offset=0)
        drop(g, 1, offset=g.length)
        step(g, FALL_TIME + CRUMBLE_TIME + DT)
        self.assertEqual(g.winners, [0])

    def test_alone_its_always_blocks(self):
        self.assertEqual(make(goal="height").goal, "blocks")

    def test_the_best_tower_shows_as_a_mark(self):
        g = make(players=2)
        for _ in range(3):
            drop(g, 0, offset=0)
        drop(g, 0, offset=g.length)
        step(g, FALL_TIME + CRUMBLE_TIME + DT)
        ready(g)
        mark = g.scores[0].height - 1
        seen = set()
        for _ in range(30):
            seen.add(strip(g)[mark])
            step(g, DT)
        self.assertIn(g.colors[0].led, seen)

    def test_leaving_on_your_turn_passes_it(self):
        g = make(players=2)
        drop(g, 0, offset=0)
        g.on_leave("p0")
        step(g, CRUMBLE_TIME + DT)
        self.assertEqual(g.turn, 1)
        drop(g, 1, offset=g.length)
        step(g, FALL_TIME + CRUMBLE_TIME + DT)
        self.assertEqual(g.winners, [1])  # the one who left doesn't win

    def test_registered(self):
        from ledgames.games import GAMES

        self.assertIs(GAMES["tower"], Tower)
        self.assertEqual(Tower.info.max_players, 6)


if __name__ == "__main__":
    unittest.main()
