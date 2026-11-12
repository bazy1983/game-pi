import random
import unittest

from ledgames.colors import OFF
from ledgames.games.hot_cold import DIFFICULTIES, GLOW_TIME, HEATS, INTRO_TIME, REVEAL_TIME, HotCold, heat_of

DT = 1 / 30
N = 150


def make(players=1, difficulty="easy", seed=1):
    return HotCold(N, difficulty, {}, players=[f"p{i}" for i in range(players)], rng=random.Random(seed))


def step(g, seconds):
    for _ in range(round(seconds / DT)):
        g.update(DT)


def started(g):
    step(g, INTRO_TIME + DT)
    assert g.stage == "turn"
    return g


def miss(g):
    """A spot well away from the treasure."""
    return 0 if g.treasure > N // 2 else N - 1


def dig(g, i, led):
    g.on_input(f"p{i}", {"dig": led})


def valid(pixels):
    return all(isinstance(px, tuple) and len(px) == 3 and all(0 <= c <= 255 for c in px) for px in pixels)


class HeatTest(unittest.TestCase):
    def test_closer_is_hotter(self):
        ids = [heat_of(d, N).id for d in (100, 50, 30, 15, 10, 3)]
        self.assertEqual(ids, [h.id for h in HEATS])

    def test_the_treasure_fits_on_the_strip(self):
        for seed in range(50):
            g = make(seed=seed)
            self.assertTrue(g.zone <= g.treasure < N - g.zone)


class TurnTest(unittest.TestCase):
    def test_dig_glow_then_next_turn(self):
        g = started(make(players=2))
        self.assertEqual(g.state()["turn"], 0)
        dig(g, 1, 5)  # not their turn
        self.assertEqual(g.digs, [])
        dig(g, 0, miss(g))
        st = g.state()
        self.assertEqual(st["stage"], "glow")
        self.assertEqual(len(st["digs"]), 1)
        self.assertIsNone(st["treasure"])  # still secret
        dig(g, 0, miss(g))  # no digging while it glows
        self.assertEqual(len(g.digs), 1)
        step(g, GLOW_TIME + DT)
        self.assertEqual((g.stage, g.turn), ("turn", 1))

    def test_aim_moves_the_cursor_only_for_the_player_whose_turn_it_is(self):
        g = started(make(players=2))
        g.on_input("p0", {"aim": 42})
        self.assertEqual(g.state()["aim"], 42)
        g.on_input("p1", {"aim": 7})
        for bad in (-1, N, 3.5, True, "4"):
            g.on_input("p0", {"aim": bad})
        self.assertEqual(g.state()["aim"], 42)

    def test_finding_it_wins(self):
        g = started(make(players=3))
        dig(g, 0, miss(g))
        step(g, GLOW_TIME + DT)
        dig(g, 1, g.treasure + g.zone)  # the edge of the treasure counts
        st = g.state()
        self.assertEqual((st["status"], st["winner"], st["treasure"]), ("won", 1, g.treasure))
        self.assertEqual(st["digs"][-1]["heat"], "found")
        step(g, REVEAL_TIME + DT)
        self.assertIsNotNone(g.effect)
        step(g, 10)
        self.assertTrue(g.finished)

    def test_slow_turns_pass(self):
        g = started(make(players=2))
        step(g, DIFFICULTIES["easy"].turn_time + DT)
        self.assertEqual((g.stage, g.turn), ("turn", 1))

    def test_no_time_limit_alone(self):
        g = started(make())
        self.assertIsNone(g.state()["turn_left"])
        step(g, 120)
        self.assertEqual((g.stage, g.turn), ("turn", 0))

    def test_a_player_who_leaves_is_skipped(self):
        g = started(make(players=3))
        g.on_leave("p0")  # on their turn
        self.assertEqual(g.turn, 1)
        dig(g, 1, miss(g))
        step(g, GLOW_TIME + DT)
        self.assertEqual(g.turn, 2)
        dig(g, 2, miss(g))
        step(g, GLOW_TIME + DT)
        self.assertEqual(g.turn, 1)


class SoloTest(unittest.TestCase):
    def test_out_of_digs_reveals_it_and_loses(self):
        g = started(make(difficulty="hard"))
        for k in range(DIFFICULTIES["hard"].digs):
            self.assertEqual(g.state()["digs_left"], DIFFICULTIES["hard"].digs - k)
            dig(g, 0, miss(g))
            step(g, GLOW_TIME + DT)
        st = g.state()
        self.assertEqual((st["status"], st["stage"], st["treasure"]), ("lost", "reveal", g.treasure))
        step(g, REVEAL_TIME + 7)
        self.assertTrue(g.finished)


class RenderTest(unittest.TestCase):
    def test_every_stage_renders(self):
        for n in (1, 3, 60, 300):
            g = HotCold(n, "medium", {}, players=["a", "b"], rng=random.Random(n))
            pixels = [OFF] * n
            for k in range(600):
                if g.stage == "turn" and k % 40 == 0:
                    g.on_input(g.players[g.turn], {"dig": (k * 7) % n})
                g.update(DT)
                g.render(pixels)
                self.assertEqual(len(pixels), n)
                self.assertTrue(valid(pixels), (n, g.stage))

    def test_markers_stay_where_you_dug(self):
        g = started(make(players=2))
        led = miss(g)
        dig(g, 0, led)
        step(g, GLOW_TIME + DT)
        pixels = [OFF] * N
        g.on_input("p1", {"aim": N // 2})
        g.render(pixels)
        self.assertNotEqual(pixels[led], OFF)


if __name__ == "__main__":
    unittest.main()
