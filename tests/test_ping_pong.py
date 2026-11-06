import random
import unittest

from ledgames.colors import OFF, WHITE
from ledgames.games.ping_pong import (
    BALL_SPEED,
    COOLDOWN,
    CPU_HIT_LEAD,
    CPU_MISS_LEAD,
    EXTEND_TIME,
    PLAYER_COLORS,
    SERVE_TIME,
    PingPong,
)

DT = 1 / 30
N = 60
RED, BLUE = PLAYER_COLORS[0].led, PLAYER_COLORS[1].led


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def make(players=2, difficulty="easy", seed=1):
    ids = [f"p{i}" for i in range(players)]
    clock = Clock()
    g = PingPong(N, difficulty, {}, players=ids, rng=random.Random(seed), clock=clock)
    g.test_clock = clock
    return g


def step(g, frames=1):
    for _ in range(frames):
        g.update(DT)
        g.test_clock.now += DT


def run(g, seconds):
    step(g, round(seconds / DT))


def tap(g, side, **extra):
    g.on_input(f"p{side}", {"tap": True, **extra})


def serve(g, to):
    g.serve_to = to
    run(g, SERVE_TIME + DT / 2)
    assert g.stage == "play"


def run_until_near(g, side, distance):
    """Until the ball heading for `side` is within `distance` LEDs of its end."""
    while g._distance(side) > distance:
        step(g)
        assert g.stage == "play"


def strip(g):
    pixels = [OFF] * N
    g.render(pixels)
    return pixels


class PingPongTest(unittest.TestCase):
    def test_rackets_at_each_end(self):
        g = make()
        s = strip(g)
        self.assertEqual(s[:3], [RED] * 3)
        self.assertEqual(s[-3:], [BLUE] * 3)
        self.assertEqual(s[3], OFF)

    def test_swing_grows_then_shrinks(self):
        g = make()
        tap(g, 0)
        self.assertEqual(g._length(0), 3)
        run(g, EXTEND_TIME / 2)
        self.assertIn(g._length(0), (4, 5))
        run(g, EXTEND_TIME / 2)
        self.assertEqual(g._length(0), 6)
        run(g, EXTEND_TIME / 2)
        self.assertIn(g._length(0), (4, 5))
        run(g, EXTEND_TIME / 2 + DT)
        self.assertEqual(g._length(0), 3)

    def test_no_new_swing_during_cooldown(self):
        g = make()
        tap(g, 0)
        start = g.swings[0]
        run(g, COOLDOWN - 0.1)
        tap(g, 0)
        self.assertEqual(g.swings[0], start)
        run(g, 0.15)
        tap(g, 0)
        self.assertGreater(g.swings[0], start)

    def test_serve_from_the_middle_toward_a_player(self):
        g = make()
        serve(g, 0)
        self.assertEqual(g.dir, -1)
        self.assertLess(abs(g.pos - N / 2), BALL_SPEED * DT)
        self.assertIn(WHITE, strip(g))

    def test_hitting_sends_it_back(self):
        g = make()
        serve(g, 0)
        run_until_near(g, 0, 8)
        tap(g, 0)
        run(g, 0.2)
        self.assertEqual(g.dir, 1)
        self.assertEqual(g.hits, 1)
        self.assertEqual(g.scores, [0, 0])

    def test_missing_gives_the_other_player_a_point(self):
        g = make()
        serve(g, 0)
        run(g, 1)
        self.assertEqual(g.scores, [0, 1])
        self.assertEqual(g.stage, "serve")
        self.assertEqual(g.serve_to, 0)  # served to whoever lost the point

    def test_only_the_growing_racket_hits(self):
        g = make()
        serve(g, 0)
        g.pos = N - 5
        # Swing early: the racket is shrinking (still long) when the ball arrives.
        run_until_near(g, 0, 3 + BALL_SPEED * (EXTEND_TIME + 0.1))
        tap(g, 0)
        run(g, 1)
        self.assertEqual(g.scores, [0, 1])

    def test_a_fast_ball_cant_skip_past_a_swinging_racket(self):
        g = make()
        g.hits = 50  # 100 × 1.1⁵ ≈ 161 LEDs/s, over 5 LEDs a frame
        serve(g, 0)
        g.hits = 50
        run_until_near(g, 0, 7)
        tap(g, 0)
        run(g, 0.3)
        self.assertEqual(g.dir, 1)
        self.assertGreaterEqual(g.pos, 0)

    def test_speeds_up_every_10_hits_and_resets_each_point(self):
        g = make()
        self.assertEqual(g.speed, BALL_SPEED)
        g.hits = 9
        self.assertEqual(g.speed, BALL_SPEED)
        g.hits = 10
        self.assertAlmostEqual(g.speed, BALL_SPEED * 1.1)
        g.hits = 25
        self.assertAlmostEqual(g.speed, BALL_SPEED * 1.21)
        serve(g, 0)
        self.assertEqual(g.hits, 0)

    def test_score_dots_between_points(self):
        g = make()
        g.scores = [2, 1]
        g.last_point = 0
        run(g, SERVE_TIME - 0.3)  # past the flash
        s = strip(g)
        self.assertEqual([s[7], s[9], s[11]], [RED, RED, OFF])
        self.assertEqual([s[N - 8], s[N - 10]], [BLUE, OFF])

    def test_first_to_5_wins(self):
        g = make()
        g.scores = [0, 4]
        serve(g, 0)
        run(g, 1)
        self.assertEqual(g.status, "won")
        self.assertEqual(g.winner, 1)
        tap(g, 0)  # too late
        run(g, 10)
        self.assertTrue(g.finished)

    def test_leaving_forfeits(self):
        g = make()
        g.on_leave("p1")
        self.assertEqual(g.status, "won")
        self.assertEqual(g.winner, 0)
        self.assertTrue(g.state()["forfeit"])

    def test_tap_time_starts_the_swing_earlier(self):
        g = make()
        run(g, 1)
        tap(g, 0, at=g.test_clock.now - 0.1)
        self.assertAlmostEqual(g.swings[0], g.t - 0.1)
        g = make()
        run(g, 1)
        tap(g, 0, at=g.test_clock.now - 5)  # capped
        self.assertAlmostEqual(g.swings[0], g.t - 0.15)

    def test_ball_has_a_fading_trail_behind_it(self):
        g = make()
        serve(g, 0)
        step(g, 3)
        s = strip(g)
        head = int(g.pos)
        self.assertEqual(s[head], WHITE)
        self.assertNotEqual(s[head + 1], OFF)  # moving down: trail above
        self.assertLess(s[head + 2][0], s[head + 1][0])
        self.assertEqual(s[head - 1], OFF)


class ComputerTest(unittest.TestCase):
    def outcome(self, lead, hits=0):
        g = make(players=1)
        g.hits = hits
        serve(g, 1)
        g.hits = hits
        g.pos = 5  # the far end: the computer has the whole strip to react
        g.cpu_lead = lead
        run(g, 1)
        return "hit" if g.hits > hits else "miss"

    def test_hits_and_misses_at_any_speed(self):
        for hits in (0, 20, 50, 80):
            self.assertEqual(self.outcome(CPU_HIT_LEAD, hits), "hit", hits)
            self.assertEqual(self.outcome(CPU_MISS_LEAD, hits), "miss", hits)

    def test_hit_chance_follows_the_difficulty(self):
        for difficulty, chance in (("easy", 0.7), ("hard", 0.93)):
            g = make(players=1, difficulty=difficulty, seed=7)
            leads = []
            for _ in range(2000):
                g.dir = 1
                g._plan_cpu()
                leads.append(g.cpu_lead)
            self.assertAlmostEqual(leads.count(CPU_HIT_LEAD) / 2000, chance, delta=0.03)

    def test_no_early_whiff_when_the_ball_is_already_close(self):
        g = make(players=1)
        serve(g, 1)
        g.pos = N - 10
        g.cpu_lead = CPU_MISS_LEAD
        run(g, 1)
        self.assertEqual(g.hits, 0)
        self.assertEqual(g.scores, [1, 0])

    def test_solo_player_cant_swing_the_computer(self):
        g = make(players=1)
        g.on_input("p1", {"tap": True})
        self.assertLess(g.swings[1], 0)

    def test_computer_winning_is_a_loss(self):
        g = make(players=1)
        g.scores = [0, 4]
        serve(g, 0)
        run(g, 1)
        self.assertEqual(g.status, "lost")


if __name__ == "__main__":
    unittest.main()
