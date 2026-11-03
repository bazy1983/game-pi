import random
import unittest

from ledgames.colors import OFF, RED
from ledgames.games.fast_tap import GRACE, GREEN, INTRO_TIME, PLAYER_COLORS, FastTap

DT = 1 / 30


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(players=2, difficulty="easy", seed=1):
    clock = Clock()
    ids = [f"p{i}" for i in range(players)]
    g = FastTap(60, difficulty, {}, players=ids, rng=random.Random(seed), clock=clock)
    return g, clock


def step(g, clock, dt=DT):
    clock.t += dt
    g.update(dt)


def run_until(g, clock, pred, limit=120.0):
    t = 0.0
    while not pred():
        step(g, clock)
        t += DT
        if t > limit:
            raise AssertionError("timed out")


def tap(g, idx, at=None):
    g.on_input(f"p{idx}", {"tap": True, "at": g.clock() if at is None else at})


def win_round(g, clock, idx):
    run_until(g, clock, lambda: g.stage == "armed" and g.light == GREEN)
    tap(g, idx)
    run_until(g, clock, lambda: g.stage != "armed" or g.status != "playing")


def lose_round(g, clock):
    run_until(g, clock, lambda: g.stage == "armed")
    for i in range(len(g.players)):
        tap(g, i)


def next_round(g, clock):
    run_until(g, clock, lambda: g.stage == "intro" or g.status != "playing")


class FastTapTest(unittest.TestCase):
    def test_intro_shows_players_and_ignores_taps(self):
        g, clock = make(3)
        pixels = [OFF] * 60
        g.render(pixels)
        lit = {p for p in pixels if p != OFF}
        self.assertEqual(len(lit), 3)
        tap(g, 0)
        self.assertEqual(g.out, set())
        run_until(g, clock, lambda: g.stage == "armed")
        self.assertAlmostEqual(g.t, INTRO_TIME, delta=2 * DT)

    def test_easy_flashes_reds_then_green(self):
        for seed in range(10):
            g, clock = make(seed=seed)
            seen = []
            last = None
            run_until(g, clock, lambda: g.stage == "armed")
            while GREEN not in seen:
                step(g, clock)
                if g.light != last and g.light is not None:
                    seen.append(g.light)
                last = g.light
            self.assertTrue(1 <= len(seen) - 1 <= 5, seen)
            self.assertTrue(all(c == RED for c in seen[:-1]))

    def test_whole_strip_flashes(self):
        g, clock = make()
        run_until(g, clock, lambda: g.light == RED)
        pixels = [OFF] * 60
        g.render(pixels)
        self.assertEqual(pixels, [RED] * 60)

    def test_hard_has_fake_colors_and_short_green(self):
        g, clock = make(difficulty="hard", seed=3)
        colors = set()
        run_until(g, clock, lambda: (colors.add(g.light), len(colors - {None, RED, GREEN}) > 0)[1])
        run_until(g, clock, lambda: g.light == GREEN)
        self.assertAlmostEqual(g.green[1] - g.green[0], 0.3)

    def test_tap_when_not_green_knocks_you_out(self):
        g, clock = make(3)
        run_until(g, clock, lambda: g.stage == "armed")
        tap(g, 1)
        self.assertEqual(g.out, {1})
        self.assertTrue(g.state()["players"][1]["out"])
        tap(g, 1)  # can't do anything else this round
        self.assertEqual(g.out, {1})

    def test_fastest_tap_wins_even_if_its_message_arrives_later(self):
        g, clock = make(3)
        run_until(g, clock, lambda: g.light == GREEN)
        start = g.green[0]
        step(g, clock, 0.1)
        tap(g, 1, at=start + 0.09)  # arrives first
        step(g, clock, 0.1)
        tap(g, 0, at=start + 0.05)  # faster, but laggier Wi-Fi
        run_until(g, clock, lambda: g.stage != "armed")
        self.assertEqual(g.last_round, {"winner": 0, "reaction_ms": 50})
        self.assertEqual(g.wins, [1, 0, 0])

    def test_winner_decided_only_after_grace(self):
        g, clock = make()
        run_until(g, clock, lambda: g.light == GREEN)
        tap(g, 0)
        end = g.green[1]
        run_until(g, clock, lambda: clock.t >= end + GRACE - DT)
        self.assertEqual(g.stage, "armed")
        run_until(g, clock, lambda: g.stage != "armed")
        self.assertEqual(g.last_round["winner"], 0)

    def test_tap_just_after_green_is_out(self):
        g, clock = make()
        run_until(g, clock, lambda: g.light == GREEN)
        end = g.green[1]
        run_until(g, clock, lambda: clock.t > end)
        tap(g, 1)
        self.assertEqual(g.out, {1})

    def test_double_tap_after_valid_tap_is_fine(self):
        g, clock = make()
        run_until(g, clock, lambda: g.light == GREEN)
        tap(g, 0)
        run_until(g, clock, lambda: g.light is None)
        tap(g, 0)
        self.assertEqual(g.out, set())
        run_until(g, clock, lambda: g.stage != "armed")
        self.assertEqual(g.last_round["winner"], 0)

    def test_nobody_taps_green_keeps_going(self):
        g, clock = make()
        run_until(g, clock, lambda: g.light == GREEN)
        first = g.green
        run_until(g, clock, lambda: g.green != first)
        self.assertEqual(g.stage, "armed")
        self.assertEqual(g.round, 1)

    def test_everyone_out_ends_round_without_winner(self):
        g, clock = make(2)
        lose_round(g, clock)
        self.assertEqual(g.stage, "round_over")
        self.assertEqual(g.last_round["winner"], None)
        next_round(g, clock)
        self.assertEqual(g.round, 2)
        self.assertEqual(g.out, set())  # everyone back in

    def test_untrusted_timestamps_are_clamped(self):
        g, clock = make()
        run_until(g, clock, lambda: g.light == GREEN)
        tap(g, 0, at=clock.t + 5)  # from the future: treated as now
        self.assertIn(0, g.green_taps)
        tap(g, 1, at="soon")
        self.assertIn(1, g.green_taps)

    def test_leader_who_cant_be_caught_wins_early(self):
        g, clock = make(2)
        win_round(g, clock, 0)
        next_round(g, clock)
        win_round(g, clock, 0)
        self.assertEqual(g.status, "won")
        self.assertEqual(g.winner, 0)
        self.assertEqual(g.rounds_played, 2)
        run_until(g, clock, lambda: g.finished)

    def test_three_rounds_most_wins(self):
        g, clock = make(3)
        win_round(g, clock, 0)
        next_round(g, clock)
        win_round(g, clock, 2)
        next_round(g, clock)
        win_round(g, clock, 2)
        self.assertEqual(g.status, "won")
        self.assertEqual(g.winner, 2)

    def test_tie_goes_to_sudden_death_between_leaders(self):
        g, clock = make(3)
        win_round(g, clock, 0)
        next_round(g, clock)
        win_round(g, clock, 1)
        next_round(g, clock)
        lose_round(g, clock)
        next_round(g, clock)
        self.assertTrue(g.tiebreak)
        self.assertEqual(g.active, {0, 1})
        self.assertFalse(g.state()["players"][2]["active"])

        run_until(g, clock, lambda: g.light == GREEN)
        tap(g, 2)  # not in the tiebreak: ignored
        self.assertEqual(g.green_taps, {})
        tap(g, 1)
        run_until(g, clock, lambda: g.status != "playing")
        self.assertEqual(g.winner, 1)

    def test_solo_best_of_three(self):
        g, clock = make(1)
        win_round(g, clock, 0)
        next_round(g, clock)
        lose_round(g, clock)
        next_round(g, clock)
        self.assertEqual(g.status, "playing")
        win_round(g, clock, 0)
        self.assertEqual(g.status, "won")

        g, clock = make(1)
        lose_round(g, clock)
        next_round(g, clock)
        lose_round(g, clock)
        self.assertEqual(g.status, "lost")
        run_until(g, clock, lambda: g.finished)

    def test_state_never_reveals_the_flash(self):
        g, clock = make()
        run_until(g, clock, lambda: g.light == RED)
        red_state = g.state()
        run_until(g, clock, lambda: g.light is None)
        self.assertEqual(g.state(), red_state)

    def test_players_never_get_signal_colors(self):
        for c in PLAYER_COLORS:
            self.assertNotIn(c.led, (RED, GREEN))


if __name__ == "__main__":
    unittest.main()
