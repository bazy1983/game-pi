import random
import unittest

from ledgames.colors import OFF, PALETTE, WHITE
from ledgames.games.color_shooter import (
    COOLDOWN,
    POISON_DURATION,
    SHOOTER_SIZE,
    SHOT_TRAVEL_TIME,
    SPIT_INTERVAL,
    ColorShooter,
    Shot,
)

RED, GREEN, BLUE, YELLOW = PALETTE[:4]


def make(n=100, difficulty="normal", **settings):
    return ColorShooter(n, difficulty, settings, rng=random.Random(1))


def fly_to_head(game):
    """Advance just enough time for a fresh shot to reach the snake's head,
    without letting the snake spawn."""
    game.spawn_timer = -1e9
    distance = game.head - SHOOTER_SIZE
    game.update(distance / game.shot_speed + 0.001)


class ColorShooterTest(unittest.TestCase):
    def test_initial_snake_fills_15_percent_from_top(self):
        g = make(200)
        self.assertEqual(len(g.snake), 30)
        self.assertEqual(g.head, 170)
        pixels = [OFF] * 200
        g.render(pixels)
        self.assertEqual(pixels[:3], [WHITE] * 3)
        self.assertTrue(all(p == OFF for p in pixels[3:170]))
        self.assertTrue(all(p != OFF for p in pixels[170:]))

    def test_spawn_pushes_snake_down(self):
        g = make()
        before = list(g.snake)
        g.update(2.0)
        self.assertEqual(g.snake[: len(before)], before)
        self.assertEqual(len(g.snake), len(before) + 1)

    def test_matching_shot_removes_head_and_scores(self):
        g = make()
        g.snake = [RED, BLUE, GREEN]
        g.on_input("p", {"fire": "red"})
        fly_to_head(g)
        self.assertEqual(g.snake, [BLUE, GREEN])
        self.assertEqual(g.score, 1)

    def test_mismatch_joins_snake_and_costs_a_point(self):
        g = make()
        g.snake = [RED, BLUE, GREEN, RED, YELLOW, GREEN, GREEN, BLUE]
        g.on_input("p", {"fire": "blue"})
        fly_to_head(g)
        self.assertEqual(g.snake, [BLUE, RED, BLUE, GREEN, RED, YELLOW, GREEN, GREEN, BLUE])
        self.assertEqual(g.score, -1)

    def test_only_one_led_removed_per_hit(self):
        g = make()
        g.snake = [RED, RED, RED]
        g.on_input("p", {"fire": "red"})
        fly_to_head(g)
        self.assertEqual(g.snake, [RED, RED])

    def test_shots_in_flight_resolve_in_order(self):
        g = make()
        g.snake = [RED, BLUE]
        g.on_input("p", {"fire": "red"})
        g.update(0.1)
        g.on_input("p", {"fire": "blue"})
        g.spawn_timer = -1e9
        g.update(30)
        self.assertEqual(g.snake, [])
        self.assertEqual(g.score, 2)

    def test_win_at_goal(self):
        g = make(difficulty="easy")
        g.score = 99
        g.snake = [RED]
        g.on_input("p", {"fire": "red"})
        fly_to_head(g)
        self.assertEqual(g.state()["status"], "won")
        for _ in range(1000):
            g.update(0.05)
        self.assertTrue(g.finished)

    def test_lose_when_snake_reaches_shooter(self):
        g = make(20)
        g.snake = [RED] * (20 - SHOOTER_SIZE)
        g.update(2.0)
        self.assertEqual(g.state()["status"], "lost")
        self.assertEqual(len(g.snake), 20 - SHOOTER_SIZE)

    def test_mismatch_can_lose(self):
        g = make(20)
        g.snake = [RED] * (20 - SHOOTER_SIZE)  # head right above the shooter
        g.on_input("p", {"fire": "green"})
        fly_to_head(g)
        self.assertEqual(g.state()["status"], "lost")

    def test_shot_crosses_strip_in_travel_time(self):
        for n in (60, 250, 300):
            g = make(n)
            g.snake = []
            g.spawn_timer = -1e9
            g.on_input("p", {"fire": "red"})
            g.update(SHOT_TRAVEL_TIME * (n - SHOOTER_SIZE - 1) / n)
            self.assertEqual(len(g.shots), 1)  # still on the strip
            g.update(SHOT_TRAVEL_TIME * 2 / n)
            self.assertEqual(g.shots, [])  # flew off the top

    def test_cooldown_setting(self):
        rapid = make(fire_mode="rapid")
        rapid.on_input("p", {"fire": "red"})
        rapid.on_input("p", {"fire": "red"})
        self.assertEqual(len(rapid.shots), 2)

        cool = make(fire_mode="cooldown")
        cool.on_input("p", {"fire": "red"})
        cool.on_input("p", {"fire": "red"})
        self.assertEqual(len(cool.shots), 1)
        cool.update(COOLDOWN)
        cool.on_input("p", {"fire": "red"})
        self.assertEqual(len(cool.shots), 2)

    def test_rejects_colors_not_in_difficulty(self):
        g = make(difficulty="easy")  # red, green, blue
        g.on_input("p", {"fire": "yellow"})
        self.assertEqual(g.shots, [])

    def test_insane_hides_snake_colors(self):
        g = make(100, "insane")
        pixels = [OFF] * 100
        g.spawn_timer = -1e9
        g.update(0.5)
        g.render(pixels)
        self.assertTrue(all(p == WHITE for p in pixels[g.head :]))
        g.update(1.6)  # t = 2.1, inside the 0.3s reveal window
        g.render(pixels)
        self.assertEqual(pixels[g.head :], [c.led for c in g.snake])


class PoisonTest(unittest.TestCase):
    def setUp(self):
        self.g = make(100, "hard")
        self.g.spawn_timer = -1e9  # keep the snake still
        self.g.spit_timer = 1e9  # and only spit when a test says so

    def test_spits_every_5_to_10_seconds_on_hard_and_insane_only(self):
        for difficulty, spits in [("easy", False), ("normal", False), ("hard", True), ("insane", True)]:
            g = make(100, difficulty)
            g.spawn_timer = -1e9
            spit_times = []
            for _ in range(int(60 / 0.05)):
                before = len(g.poisons)
                g.update(0.05)
                if len(g.poisons) > before:
                    spit_times.append(g.t)
                    self.assertIn(g.poisons[-1].color, g.colors)
            if not spits:
                self.assertEqual(spit_times, [], difficulty)
                continue
            gaps = [b - a for a, b in zip([0.0] + spit_times, spit_times)]
            self.assertGreaterEqual(len(gaps), 6, difficulty)
            for gap in gaps:
                self.assertTrue(SPIT_INTERVAL[0] - 0.06 <= gap <= SPIT_INTERVAL[1] + 0.06, (difficulty, gap))

    def test_poison_is_slower_than_shots(self):
        self.assertLess(self.g.poison_speed, self.g.shot_speed)

    def test_matching_shot_destroys_poison(self):
        g = self.g
        snake = list(g.snake)
        g.poisons.append(Shot(50.0, RED))
        g.on_input("p", {"fire": "red"})
        g.update(1.0)
        self.assertEqual(g.poisons, [])
        self.assertEqual(g.shots, [])
        self.assertEqual(g.snake, snake)
        self.assertEqual(g.score, 0)

    def test_other_colors_pass_through(self):
        g = self.g
        g.snake = [GREEN]
        g.poisons.append(Shot(50.0, RED))
        g.on_input("p", {"fire": "green"})
        g.update(0.6)  # they've crossed by now
        self.assertEqual(len(g.poisons), 1)
        self.assertEqual(len(g.shots), 1)
        g.update(1.5)
        self.assertEqual(g.snake, [])  # shot still reached the snake
        self.assertEqual(g.score, 1)

    def test_only_one_matching_shot_used_per_poison(self):
        g = self.g
        g.snake = [RED]
        g.poisons.append(Shot(80.0, RED))
        g.on_input("p", {"fire": "red"})
        g.update(0.05)
        g.on_input("p", {"fire": "red"})
        g.update(2.0)
        self.assertEqual(g.poisons, [])
        self.assertEqual(g.snake, [])  # second shot got through
        self.assertEqual(g.score, 1)

    def test_poison_reaching_shooter_blocks_fire(self):
        g = self.g
        g.poisons.append(Shot(10.0, BLUE))
        g.update(0.5)
        self.assertEqual(g.poisons, [])
        self.assertTrue(g.state()["poisoned"])
        g.on_input("p", {"fire": "red"})
        self.assertEqual(g.shots, [])

        pixels = [OFF] * 100
        flashes = set()
        for _ in range(10):
            g.update(0.05)
            g.render(pixels)
            flashes.add(pixels[0])
        self.assertEqual(flashes, {BLUE.led, OFF})

        g.update(POISON_DURATION)
        self.assertFalse(g.state()["poisoned"])
        g.on_input("p", {"fire": "red"})
        self.assertEqual(len(g.shots), 1)

    def test_repeat_hit_restarts_poison_time(self):
        g = self.g
        g.poisons.append(Shot(4.0, BLUE))
        g.update(0.1)
        g.update(POISON_DURATION - 0.5)
        g.poisons.append(Shot(4.0, RED))
        g.update(0.1)
        self.assertEqual(g.state()["poison_hits"], 2)
        g.update(1.0)
        self.assertTrue(g.state()["poisoned"])


if __name__ == "__main__":
    unittest.main()
