import random
import unittest

from ledgames.colors import OFF, PALETTE, scale
from ledgames.games.simon import BETWEEN_TIME, INTRO_TIME, PRESS_TIMEOUT, ZONE_DIM, Simon

DT = 1 / 30
N = 40


def make(players=1, difficulty="easy", mode="together", seed=1):
    ids = [f"p{i}" for i in range(players)]
    return Simon(N, difficulty, {"mode": mode}, players=ids, rng=random.Random(seed))


def run(g, seconds):
    for _ in range(round(seconds / DT)):
        g.update(DT)


def run_until(g, stage, limit=30):
    for _ in range(round(limit / DT)):
        if g.stage == stage or g.status != "playing":
            return
        g.update(DT)
    raise AssertionError(f"never reached {stage}")


def press(g, idx, color):
    g.on_input(f"p{idx}", {"press": g.colors[color].name})


def repeat(g, idx=0):
    for c in list(g.sequence):
        press(g, idx, c)


def wrong(g):
    """A color that isn't the next one in the sequence for a fresh player."""
    return (g.sequence[0] + 1) % len(g.colors)


def strip(g):
    pixels = [OFF] * N
    g.render(pixels)
    return pixels


class SoloTest(unittest.TestCase):
    def test_plays_the_sequence_then_waits_for_presses(self):
        g = make()
        self.assertEqual(g.state()["mode"], "solo")
        self.assertEqual(len(g.sequence), 1)
        press(g, 0, g.sequence[0])  # during the intro: ignored
        run_until(g, "show")
        first = g.sequence[0]
        g.update(DT)
        zone = list(g._zone(first))
        self.assertEqual(strip(g)[zone[0]], g.colors[first].led)  # the step's zone is lit
        other = (first + 1) % 4
        self.assertEqual(strip(g)[g._zone(other)[0]], scale(g.colors[other].led, ZONE_DIM))
        run_until(g, "input")
        for c, color in enumerate(g.colors):
            self.assertEqual(strip(g)[g._zone(c)[0]], scale(color.led, ZONE_DIM))

    def test_each_round_adds_a_color(self):
        g = make()
        for length in range(1, 4):
            run_until(g, "input")
            self.assertEqual(len(g.sequence), length)
            repeat(g)
            self.assertEqual(g.stage, "between")
            self.assertEqual(g.reached, length)
        self.assertEqual(len(g.sequence), 4)

    def test_press_lights_its_zone(self):
        g = make()
        run_until(g, "input")
        first = g.sequence[0]
        press(g, 0, first)
        self.assertEqual(strip(g)[g._zone(first)[0]], g.colors[first].led)

    def test_mistake_loses(self):
        g = make()
        run_until(g, "input")
        press(g, 0, wrong(g))
        self.assertEqual(g.status, "lost")
        run(g, 10)
        self.assertTrue(g.finished)

    def test_not_pressing_loses(self):
        g = make()
        run_until(g, "input")
        run(g, PRESS_TIMEOUT - 0.5)
        self.assertEqual(g.status, "playing")
        run(g, 1)
        self.assertEqual(g.status, "lost")

    def test_reaching_the_target_wins(self):
        g = make()
        for _ in range(8):
            run_until(g, "input")
            repeat(g)
        self.assertEqual(g.status, "won")
        self.assertEqual(g.reached, 8)
        self.assertEqual(g.winners, [0])

    def test_playback_speeds_up(self):
        g = make()
        start = g._step_time()
        g.sequence = [0] * 20
        self.assertLess(g._step_time(), start)
        self.assertAlmostEqual(g._step_time(), start * 0.6)

    def test_hard_flashes_the_whole_strip_and_shuffles(self):
        g = make(difficulty="hard", seed=3)
        self.assertEqual(len(g.colors), 5)
        orders = set()
        for _ in range(6):
            run_until(g, "show")
            orders.add(tuple(b["name"] for b in g.state()["buttons"]))
            g.update(DT)
            self.assertEqual(set(strip(g)), {g.colors[g.sequence[0]].led})
            run_until(g, "input")
            self.assertEqual(set(strip(g)), {OFF})
            repeat(g)
        self.assertGreater(len(orders), 1)

    def test_buttons_follow_the_zones_top_first(self):
        g = make()
        names = [b["name"] for b in g.state()["buttons"]]
        self.assertEqual(names, [c.name for c in reversed(PALETTE[:4])])

    def test_state_hides_the_sequence(self):
        g = make()
        self.assertNotIn("sequence", g.state())


class TogetherTest(unittest.TestCase):
    def test_presses_dont_show_on_the_strip(self):
        g = make(players=2)
        run_until(g, "input")
        before = strip(g)
        press(g, 0, g.sequence[0])
        self.assertEqual(strip(g), before)

    def test_a_mistake_knocks_you_out(self):
        g = make(players=3)
        run_until(g, "input")
        repeat(g, 0)
        self.assertEqual(g.stage, "input")  # waiting for the others
        press(g, 1, wrong(g))
        repeat(g, 2)
        self.assertEqual(g.stage, "between")
        self.assertEqual(g.last, {"out": [1], "replay": False})
        self.assertEqual(g.alive, {0, 2})
        run_until(g, "input")
        self.assertEqual(len(g.sequence), 2)
        press(g, 1, g.sequence[0])  # out: ignored
        self.assertEqual(g.progress[1], 0)
        self.assertTrue(g.state()["players"][1]["out"])

    def test_last_one_standing_wins(self):
        g = make(players=2)
        run_until(g, "input")
        repeat(g, 0)
        press(g, 1, wrong(g))
        self.assertEqual(g.status, "won")
        self.assertEqual(g.winners, [0])

    def test_everyone_missing_replays_with_a_new_last_color(self):
        g = make(players=2)
        run_until(g, "input")
        repeat(g, 0)
        repeat(g, 1)
        run_until(g, "input")
        first, last = g.sequence
        press(g, 0, wrong(g))
        press(g, 1, first)
        press(g, 1, (last + 1) % 4)
        self.assertEqual(g.last, {"out": [], "replay": True})
        self.assertEqual(g.alive, {0, 1})
        self.assertEqual(len(g.sequence), 2)
        self.assertEqual(g.sequence[0], first)
        self.assertNotEqual(g.sequence[1], last)

    def test_survivors_share_the_win_at_the_target(self):
        g = make(players=3)
        run_until(g, "input")
        repeat(g, 0)
        repeat(g, 1)
        press(g, 2, wrong(g))
        for _ in range(7):
            run_until(g, "input")
            repeat(g, 0)
            repeat(g, 1)
        self.assertEqual(g.status, "won")
        self.assertEqual(g.winners, [0, 1])

    def test_a_stalling_player_is_out(self):
        g = make(players=3)
        run_until(g, "input")
        repeat(g, 0)
        repeat(g, 1)
        run(g, PRESS_TIMEOUT + 0.1)
        self.assertEqual(g.alive, {0, 1})

    def test_leaving_finishes_the_round_without_them(self):
        g = make(players=3)
        run_until(g, "input")
        repeat(g, 0)
        repeat(g, 1)
        g.on_leave("p2")
        self.assertEqual(g.stage, "between")
        self.assertTrue(g.state()["players"][2]["left"])
        self.assertFalse(g.state()["players"][2]["out"])

    def test_last_player_present_wins_when_the_others_leave(self):
        g = make(players=2)
        run_until(g, "input")
        g.on_leave("p1")
        self.assertEqual(g.status, "won")
        self.assertEqual(g.winners, [0])


class TurnsTest(unittest.TestCase):
    def test_first_player_picks_the_first_color(self):
        g = make(players=2, mode="turns")
        self.assertEqual(g.sequence, [])
        run(g, INTRO_TIME + DT)
        self.assertEqual(g.stage, "input")  # no playback
        press(g, 1, 0)  # not their turn
        self.assertEqual(g.sequence, [])
        press(g, 0, 2)
        self.assertEqual(g.sequence, [2])
        self.assertEqual(g.last, {"out": [], "added": 0})
        self.assertEqual(g.turn, 1)

    def test_presses_light_the_strip(self):
        g = make(players=2, mode="turns")
        run_until(g, "input")
        press(g, 0, 2)
        self.assertEqual(strip(g)[g._zone(2)[0]], g.colors[2].led)
        run(g, 0.5)
        self.assertEqual(strip(g)[g._zone(2)[0]], scale(g.colors[2].led, ZONE_DIM))

    def test_same_color_twice_blinks(self):
        g = make(players=2, mode="turns")
        run_until(g, "input")
        press(g, 0, 2)
        run(g, BETWEEN_TIME + DT)
        press(g, 1, 2)
        g.update(DT)
        press(g, 1, 2)  # repeated while still lit: a dark moment first
        self.assertEqual(strip(g)[g._zone(2)[0]], scale(g.colors[2].led, ZONE_DIM))
        run(g, 0.1)
        self.assertEqual(strip(g)[g._zone(2)[0]], g.colors[2].led)

    def test_repeat_then_add(self):
        g = make(players=2, mode="turns")
        run_until(g, "input")
        press(g, 0, 1)
        run_until(g, "input")
        press(g, 1, 1)
        self.assertEqual(g.state()["entered"], 1)
        press(g, 1, 3)
        self.assertEqual(g.sequence, [1, 3])
        self.assertEqual(g.turn, 0)

    def test_a_mistake_knocks_you_out_and_the_next_player_gets_the_same_sequence(self):
        g = make(players=3, mode="turns")
        run_until(g, "input")
        press(g, 0, 1)
        run_until(g, "input")
        press(g, 1, 2)  # wrong: should be 1
        self.assertEqual(g.last, {"out": [1]})
        self.assertEqual(g.sequence, [1])
        self.assertEqual(g.turn, 2)
        run_until(g, "input")
        press(g, 2, 1)
        press(g, 2, 0)
        self.assertEqual(g.turn, 0)  # skips player 1

    def test_last_one_standing_wins(self):
        g = make(players=2, mode="turns")
        run_until(g, "input")
        press(g, 0, 1)
        run_until(g, "input")
        press(g, 1, 0)
        self.assertEqual(g.status, "won")
        self.assertEqual(g.winners, [0])

    def test_target_shares_the_win(self):
        g = make(players=2, mode="turns")
        for turn in range(8):
            run_until(g, "input")
            repeat(g, turn % 2)
            press(g, turn % 2, 0)
        self.assertEqual(g.status, "won")
        self.assertEqual(g.winners, [0, 1])

    def test_stalling_on_your_turn_is_out(self):
        g = make(players=3, mode="turns")
        run_until(g, "input")
        run(g, PRESS_TIMEOUT + 0.1)
        self.assertEqual(g.alive, {1, 2})
        self.assertEqual(g.turn, 1)

    def test_leaving_on_your_turn_passes_it_on(self):
        g = make(players=3, mode="turns")
        run_until(g, "input")
        g.on_leave("p0")
        self.assertEqual(g.turn, 1)
        self.assertEqual(g.last, {"out": [], "left": 0})
        run_until(g, "input")
        press(g, 1, 3)
        self.assertEqual(g.sequence, [3])
        self.assertEqual(g.turn, 2)

    def test_leaving_before_your_turn(self):
        g = make(players=3, mode="turns")
        run_until(g, "input")
        press(g, 0, 3)
        g.on_leave("p1")  # next up, during the pause
        self.assertEqual(g.turn, 2)
        run_until(g, "input")
        self.assertEqual(list(g.deadline), [2])


if __name__ == "__main__":
    unittest.main()
