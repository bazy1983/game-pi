import unittest

from ledgames.engine import Engine
from ledgames.layout import Grid, Layout
from ledgames.leds.base import Strip

OFF = (0, 0, 0)


class NullStrip(Strip):
    last = None

    def write(self, pixels, factor):
        self.last = list(pixels)


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


def make():
    clock = Clock()
    return Engine(NullStrip(60), clock=clock), clock


def run(engine, clock, seconds):
    for _ in range(int(seconds * 30)):
        clock.t += 1 / 30
        engine.tick(1 / 30)


class LobbyTest(unittest.TestCase):
    def setUp(self):
        self.e, self.clock = make()
        self.e.open("fast_tap", "easy", {}, "A")
        self.e.join("B")
        self.e.join("C")

    def test_dropped_player_leaves_lobby(self):
        self.e.drop("B")
        self.assertEqual(self.e.players(), ["A", "C"])
        self.assertIsNone(self.e.player_index("B"))

    def test_host_leaving_lobby_hands_over(self):
        self.e.drop("A")
        self.assertEqual(self.e.host, "B")
        self.assertEqual(self.e.session()["phase"], "lobby")
        self.e.drop("B")
        self.e.drop("C")
        self.assertEqual(self.e.session()["phase"], "idle")

    def test_lobby_is_capped_at_six(self):
        for p in "DEF":
            self.assertIsNone(self.e.join(p))
        self.assertEqual(self.e.join("G"), "This game is full.")


class DropMidGameTest(unittest.TestCase):
    def setUp(self):
        self.e, self.clock = make()
        self.e.open("fast_tap", "easy", {}, "A")
        self.e.join("B")
        self.e.join("C")
        self.e.begin("A")
        self.game = self.e.game

    def test_dropped_player_is_out_for_good(self):
        self.e.drop("B")
        self.assertIsNone(self.e.player_index("B"))
        self.assertEqual(self.e.player_index("C"), 2)  # colors don't shift
        players = self.e.session()["state"]["players"]
        self.assertTrue(players[1]["left"])
        self.assertFalse(players[1]["active"])
        run(self.e, self.clock, 3)  # into the round
        self.e.input("B", {"tap": True})
        self.assertNotIn(1, self.game.out)

    def test_host_dropping_hands_over(self):
        self.e.drop("A")
        self.assertEqual(self.e.host, "B")
        self.assertEqual(self.e.session()["phase"], "playing")

    def test_last_player_standing_wins_by_forfeit(self):
        self.e.drop("A")
        self.e.drop("C")
        state = self.e.session()["state"]
        self.assertEqual(state["status"], "won")
        self.assertEqual(state["winner"], 1)

    def test_everyone_remaining_already_out_ends_round(self):
        run(self.e, self.clock, 3)
        self.e.input("A", {"tap": True})
        self.e.input("B", {"tap": True})
        self.assertEqual(self.game.stage, "armed")
        self.e.drop("C")
        self.assertEqual(self.game.stage, "round_over")
        self.assertIsNone(self.game.last_round["winner"])

    def test_player_who_left_cant_win_on_points(self):
        g = self.game
        g.wins = [0, 2, 0]  # B was leading
        self.e.drop("B")
        g.rounds_played = 2
        g.wins[0] = 1
        self.assertEqual(g._game_result(), None)  # A vs C, 1 round left
        g.rounds_played = 3
        self.assertEqual(g._game_result(), 0)

    def test_tied_leader_leaving_sudden_death_gives_other_the_win(self):
        g = self.game
        g.tiebreak = True
        g.active = {0, 2}
        self.e.drop("C")
        self.assertEqual(g.status, "won")
        self.assertEqual(g.winner, 0)

    def test_everyone_dropping_stops_the_game(self):
        for p in "ABC":
            self.e.drop(p)
        self.assertEqual(self.e.session()["phase"], "ended")  # forfeit win for C first
        self.assertEqual(self.e.session()["state"]["winner"], 2)


class StripSettingsTest(unittest.TestCase):
    def setUp(self):
        self.engine = Engine(NullStrip(50), clock=Clock())

    def test_led_count_changes_when_idle(self):
        self.assertIsNone(self.engine.set_layout(Layout.strip(80)))
        self.assertEqual(self.engine.strip.num_leds, 80)
        self.engine.tick(0.1)
        self.assertEqual(len(self.engine.pixels), 80)
        self.engine.open("fast_tap", "easy", {}, "host")
        self.assertIsNotNone(self.engine.set_layout(Layout.strip(60)))
        self.assertIsNotNone(self.engine.test_strip())
        self.assertEqual(self.engine.strip.num_leds, 80)

    def test_strip_test_plays_and_ends(self):
        engine = self.engine
        engine.test_strip()
        engine.tick(0.1)
        lit = [i for i, p in enumerate(engine.pixels) if p != (0, 0, 0)]
        self.assertEqual(lit, [1])  # a dot near the bottom…
        engine.tick(2.85)
        self.assertEqual(engine.pixels[49], (255, 0, 0))  # …climbs to the top
        engine.tick(0.6)
        self.assertTrue(all(p == (255, 0, 0) for p in engine.pixels))  # then the whole strip
        engine.tick(4.0)
        self.assertEqual(engine.pixels[0], engine.pixels[-1])  # then the ends blink
        engine.tick(3.0)
        self.assertTrue(all(p == (0, 0, 0) for p in engine.pixels))

    def test_a_game_cancels_the_test(self):
        self.engine.test_strip()
        self.engine.open("fast_tap", "easy", {}, "host")
        self.engine.stop()
        self.engine.tick(0.1)
        self.assertTrue(all(p == (0, 0, 0) for p in self.engine.pixels))


class GridTest(unittest.TestCase):
    """A 3 × 2 grid: columns from the top left, zigzag, one dark LED at each turn."""

    def setUp(self):
        self.engine = Engine(NullStrip(50), clock=Clock())
        self.grid = Grid(width=3, height=2, start="top-left", skip=1)
        self.assertIsNone(self.engine.set_layout(Layout.of_grid(self.grid)))

    def test_switching_resizes_the_chain(self):
        self.assertEqual(self.engine.strip.num_leds, 8)  # 6 LEDs and 2 dark ones
        self.assertEqual(len(self.engine.pixels), 6)
        self.assertEqual(self.engine.lights.kind, "grid")

    def test_frames_go_out_in_chain_order(self):
        engine = self.engine
        engine.show_pattern("check")  # frame, so every pixel is lit; red top left
        engine.tick(0.1)
        chain = engine.strip.last
        self.assertEqual(chain[0], (255, 0, 0))  # the first LED is the top left
        self.assertEqual([chain[2], chain[5]], [OFF, OFF])  # the dark LEDs at the turns

    def test_first_leds_skip_the_layout(self):
        engine = self.engine
        engine.show_pattern("first")
        engine.tick(0.1)
        self.assertEqual(engine.strip.last, [(255, 255, 255)] + [(0, 255, 0)] * 4 + [OFF] * 3)
        engine.show_pattern(None)
        engine.tick(0.1)
        self.assertEqual(engine.strip.last, [OFF] * 8)

    def test_patterns_end_by_themselves(self):
        engine = self.engine
        engine.show_pattern("red")
        engine.tick(0.1)
        self.assertNotEqual(engine.strip.last, [OFF] * 8)
        for _ in range(121):
            engine.tick(1.0)
        self.assertEqual(engine.strip.last, [OFF] * 8)

    def test_check_is_only_for_grids(self):
        self.engine.set_layout(Layout.strip(20))
        self.assertIsNotNone(self.engine.show_pattern("check"))
        self.assertIsNone(self.engine.show_pattern("first"))
        self.assertIsNotNone(self.engine.show_pattern("blue"))

    def test_strip_games_dont_open_on_a_grid(self):
        self.assertEqual(self.engine.open("fast_tap", "easy", {}, "host"), "That game is for the LED strip.")
        self.assertEqual(self.engine.session()["phase"], "idle")

    def test_strip_lights_stay_off_on_a_grid(self):
        engine = self.engine
        engine.lights.update({"on": True, "effect": "flow"})
        self.assertFalse(engine.lights.active)
        engine.tick(0.1)
        self.assertEqual(engine.strip.last, [OFF] * 8)
        engine.set_layout(Layout.strip(20))
        self.assertTrue(engine.lights.active)  # back on the strip, the effect is still picked


class SpeakerTest(unittest.TestCase):
    def test_game_sounds_go_to_the_speaker_once(self):
        played = []
        engine, clock = make()
        engine.speaker = type("Speaker", (), {"play": lambda self, name: played.append(name)})()
        engine.open("color_shooter", "normal", {"sound": "retro"}, "A")
        engine.input("A", {"fire": engine.game.colors[0].name})
        engine.tick(1 / 30)
        self.assertEqual(played, ["retro/shoot"])
        self.assertEqual(engine.game.sounds, [])
        engine.tick(1 / 30)
        self.assertEqual(played, ["retro/shoot"])

    def test_no_speaker_still_clears_them(self):
        engine, clock = make()
        engine.open("color_shooter", "normal", {"sound": "modern"}, "A")
        engine.input("A", {"fire": engine.game.colors[0].name})
        engine.tick(1 / 30)
        self.assertEqual(engine.game.sounds, [])


class SinglePlayerTest(unittest.TestCase):
    def test_color_shooter_stops_when_player_drops(self):
        e, _ = make()
        e.open("color_shooter", "normal", {}, "A")
        self.assertEqual(e.session()["phase"], "playing")
        e.drop("B")  # spectator: nothing happens
        self.assertEqual(e.session()["phase"], "playing")
        e.drop("A")
        self.assertEqual(e.session()["phase"], "idle")


if __name__ == "__main__":
    unittest.main()
