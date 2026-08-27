"""Tests for ``ThoresT`` itself - legality, robustness, and that it plays."""
from __future__ import annotations

import random
import sys
import unittest

sys.path.insert(0, ".")

from superpac.pacman.agent import Brain, Weights
from superpac.pacman.arena import evaluate, play
from superpac.pacman.opponents import build_opponents
from superpac.pacman.perception import observe
from superpac.pacman.rules import EAST, MOVE, N_ACTIONS, STILL, WEST, is_turn
from superpac.pacman.thorest import build_thorest, execute


def _thorest(**kwargs):
    import Pacman
    return build_thorest(Pacman.Pacman, **kwargs)


class TestLegality(unittest.TestCase):
    def test_only_ever_returns_a_real_action(self):
        import Pacman
        random.seed(2)
        board = Pacman.Field(15)
        me = board.pacmans[-1]
        brain = Brain()
        for _ in range(60):
            action = brain.decide(me)
            self.assertIn(action, range(N_ACTIONS))
            execute(me, action)
            for pacman in board.pacmans:
                if pacman is not me and pacman.alive:
                    pacman.TurnOrMoveOrStill()
        self.assertEqual(brain.faults, 0)

    def test_execute_does_exactly_one_engine_thing(self):
        import Pacman
        random.seed(3)
        board = Pacman.Field(15)
        me = board.pacmans[-1]
        before = (me.position._x, me.position._y)

        execute(me, EAST)  # a turn
        self.assertEqual((me.position._x, me.position._y), before,
                         "turning must not move us")
        self.assertEqual((me.direction._x, me.direction._y), (1, 0))

        execute(me, STILL)
        self.assertEqual((me.position._x, me.position._y), before)

        execute(me, MOVE)
        self.assertNotEqual((me.position._x, me.position._y), before)

    def test_turning_to_the_current_facing_is_never_chosen(self):
        # It would waste the whole turn for nothing; the search prunes it.
        import Pacman
        random.seed(5)
        board = Pacman.Field(15)
        me = board.pacmans[-1]
        brain = Brain()
        for _ in range(40):
            snapshot = observe(me, brain.turn)
            action = brain.decide(me)
            if is_turn(action):
                self.assertNotEqual(action, snapshot.direction)
            execute(me, action)


class TestRobustness(unittest.TestCase):
    def test_survives_a_broken_subsystem(self):
        import Pacman
        random.seed(6)
        board = Pacman.Field(15)
        me = board.pacmans[-1]
        brain = Brain()

        class Exploding:
            def update(self, *a, **k):
                raise RuntimeError("boom")

            def model_for(self, *a, **k):
                raise RuntimeError("boom")

            def predict_all(self, *a, **k):
                raise RuntimeError("boom")

        brain.registry = Exploding()
        action = brain.decide(me)
        self.assertIn(action, range(N_ACTIONS))
        self.assertEqual(brain.faults, 1)

    def test_thorest_never_raises_out_of_turn_or_move_or_still(self):
        import Pacman
        random.seed(7)
        ThoresT = _thorest()
        board = Pacman.Field(15)
        me = ThoresT(board.pacmans[-1].position, "T", board.field)
        board.field[me.position] = me
        board.pacmans[-1] = me

        # Feed it a deliberately broken brain.
        class Broken:
            faults = 0

            def decide(self, _me):
                raise RuntimeError("boom")

        me.brain = Broken()
        me.TurnOrMoveOrStill()  # must not propagate
        self.assertEqual(me.brain.faults, 1)

    def test_copes_with_a_field_of_one_survivor(self):
        import Pacman
        random.seed(8)
        board = Pacman.Field(15)
        me = board.pacmans[-1]
        for pacman in board.pacmans[:-1]:
            pacman.alive = False
            del board.field[pacman.position]
            board.field[pacman.position] = Pacman.Empty(pacman.position)
        brain = Brain()
        for _ in range(25):
            action = brain.decide(me)
            self.assertIn(action, range(N_ACTIONS))
            execute(me, action)
        self.assertEqual(brain.faults, 0)
        self.assertGreater(me.strength, 1, "should still be eating")

    def test_works_on_other_board_sizes(self):
        import Pacman
        for size in (8, 12, 20):
            random.seed(size)
            result = play(_thorest(), seed=size, fieldsize=size, turns=40)
            self.assertEqual(result.faults, 0)
            self.assertGreater(result.subject_strength, 1)


class TestPlaysWell(unittest.TestCase):
    def test_beats_the_engines_own_bots_convincingly(self):
        report = evaluate(_thorest(), games=12, label="thorest")
        self.assertEqual(report.faults, 0)
        self.assertGreater(report.win_rate, 0.6,
                           f"only {report.win_rate:.0%} against the default bots")
        self.assertGreater(report.mean_strength, 2.5 * report.mean_best_rival)

    def test_beats_a_straight_line_harvester(self):
        import Pacman
        harvester = dict(build_opponents(Pacman.Pacman))["harvester"]
        report = evaluate(_thorest(), games=12, label="thorest",
                          fillers=[harvester] * 5)
        self.assertEqual(report.faults, 0)
        # Six identical players would each win 1/6 of the time.
        self.assertGreater(report.win_rate, 1 / 6,
                           "no better than being one harvester among six")

    def test_the_do_nothing_stub_loses(self):
        # Guards the arena itself: if a player that never acts ever "wins",
        # the harness is measuring something other than the game.
        import Pacman

        class Stub(Pacman.Pacman):
            def TurnOrMoveOrStill(self):
                return

        report = evaluate(Stub, games=8, label="stub")
        self.assertEqual(report.wins, 0)
        self.assertLess(report.mean_strength, 10.0)


class TestWeights(unittest.TestCase):
    def test_vector_round_trip(self):
        w = Weights()
        self.assertEqual(Weights.from_vector(w.as_vector()), w)

    def test_wrong_length_is_rejected(self):
        with self.assertRaises(ValueError):
            Weights.from_vector([1.0] * 3)

    def test_bounds_only_name_real_weights(self):
        from superpac.pacman.tuning import BOUNDS, INT_BOUNDS
        known = set(Weights.names())
        self.assertEqual((set(BOUNDS) | set(INT_BOUNDS)) - known, set())


if __name__ == "__main__":
    unittest.main()
