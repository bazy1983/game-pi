import unittest

from ledgames.engine import Engine
from ledgames.leds.base import Strip


class NullStrip(Strip):
    def write(self, pixels):
        pass


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
