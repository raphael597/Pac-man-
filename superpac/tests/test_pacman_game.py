"""Tests against the teacher's real ``Pacman.py``.

Everything here imports the actual engine.  If a rule is asserted below, it
was read out of ``Pacman._Move`` and then checked against the engine itself,
not assumed.
"""
from __future__ import annotations

import random
import sys
import unittest

sys.path.insert(0, ".")

from superpac.pacman import rules
from superpac.pacman.model import RivalRegistry, infer_action
from superpac.pacman.perception import decode_direction, observe
from superpac.pacman.rules import (EAST, MOVE, NORTH, SOUTH, STILL, TURN_TO,
                                   WEST, attack_is_worth_it, defence_factor,
                                   distance, step, win_probability)
from superpac.tests.helpers import make_board, step_rivals


class TestRulesMatchTheEngine(unittest.TestCase):
    """The rules module is a transcription; this proves it stayed one."""

    def test_defence_table_matches_engine_arithmetic(self):
        from Pacman import Direction
        engine = (Direction.north, Direction.south, Direction.west, Direction.east)
        for i in range(4):
            for j in range(4):
                z = engine[i] + engine[j]
                if z._x == 0 and z._y == 0:
                    expected = 1.0
                elif abs(z._x) == 1 and abs(z._y) == 1:
                    expected = 0.2
                else:
                    expected = 0.1
                self.assertAlmostEqual(defence_factor(i, j), expected, places=9,
                                       msg=f"direction pair {i},{j}")

    def test_direction_decoding_round_trips(self):
        from Pacman import Direction
        engine = (Direction.north, Direction.south, Direction.west, Direction.east)
        for index, direction in enumerate(engine):
            self.assertEqual(decode_direction(direction), index)

    def test_attacking_from_behind_is_ten_times_easier(self):
        # Equal strength: 50% head-on, 90.9% from behind.
        self.assertAlmostEqual(win_probability(10, 10, EAST, WEST), 0.5, places=6)
        self.assertAlmostEqual(win_probability(10, 10, EAST, EAST), 10 / 11, places=6)
        self.assertAlmostEqual(win_probability(10, 10, EAST, NORTH), 10 / 12, places=6)

    def test_facing_an_attacker_is_the_best_defence(self):
        # Their odds against us, as a function of *our* facing.
        facing_them = win_probability(10, 10, EAST, WEST)     # we look back at them
        sideways = win_probability(10, 10, EAST, NORTH)
        facing_away = win_probability(10, 10, EAST, EAST)
        self.assertLess(facing_them, sideways)
        self.assertLess(sideways, facing_away)

    def test_attack_rule_thresholds(self):
        # attack  <=>  F < a / f
        self.assertTrue(attack_is_worth_it(10, 5, EAST, EAST, 99.0))    # f=0.1 -> F<100
        self.assertFalse(attack_is_worth_it(10, 5, EAST, EAST, 101.0))
        self.assertTrue(attack_is_worth_it(10, 5, EAST, NORTH, 49.0))   # f=0.2 -> F<50
        self.assertFalse(attack_is_worth_it(10, 5, EAST, NORTH, 51.0))
        self.assertTrue(attack_is_worth_it(10, 5, EAST, WEST, 9.0))     # f=1.0 -> F<10
        self.assertFalse(attack_is_worth_it(10, 5, EAST, WEST, 11.0))

    def test_target_strength_does_not_change_whether_to_swing(self):
        # It cancels out of the derivation; it decides the size of the prize,
        # not whether the angle is favourable.
        for target in (1, 10, 100):
            self.assertEqual(attack_is_worth_it(20, target, EAST, EAST, 50.0),
                             attack_is_worth_it(20, 1, EAST, EAST, 50.0))


class TestTorusGeometry(unittest.TestCase):
    def test_step_wraps_both_axes(self):
        self.assertEqual(step(0, 0, WEST, 15), (14, 0))
        self.assertEqual(step(14, 14, EAST, 15), (0, 14))
        self.assertEqual(step(0, 0, NORTH, 15), (0, 14))

    def test_distance_uses_the_short_way_round(self):
        self.assertEqual(distance(0, 0, 14, 0, 15), 1)
        self.assertEqual(distance(0, 0, 14, 14, 15), 2)
        self.assertEqual(distance(0, 0, 7, 7, 15), 14)

    def test_step_agrees_with_the_engine(self):
        from Pacman import Direction, Position
        Position.fieldsize = 15
        engine = (Direction.north, Direction.south, Direction.west, Direction.east)
        for x in (0, 7, 14):
            for y in (0, 7, 14):
                for index, direction in enumerate(engine):
                    expected = Position(x, y) + direction
                    self.assertEqual(step(x, y, index, 15),
                                     (expected._x, expected._y))


class TestPerception(unittest.TestCase):
    def setUp(self):
        self.board, self.me = make_board(seed=4)

    def test_sees_the_whole_board(self):
        snapshot = observe(self.me)
        self.assertEqual(snapshot.size, 15)
        self.assertEqual(len(snapshot.rivals), 5)
        # 225 cells, six players standing on six of them.
        self.assertEqual(snapshot.n_cabbage, 225 - 6)
        self.assertFalse(snapshot.has_walls, "no walls were requested")

    def test_rival_views_match_the_engine_objects(self):
        snapshot = observe(self.me)
        by_name = {r.name: r for r in snapshot.rivals}
        for pacman in self.board.pacmans:
            if pacman is self.me:
                continue
            view = by_name[pacman.name]
            self.assertEqual((view.x, view.y),
                             (pacman.position._x, pacman.position._y))
            self.assertEqual(view.strength, pacman.strength)
            self.assertEqual(view.direction, decode_direction(pacman.direction))

    def test_dead_rivals_disappear(self):
        victim = self.board.pacmans[0]
        victim.alive = False
        self.assertEqual(len(observe(self.me).rivals), 4)


class TestActionInference(unittest.TestCase):
    """A rival's action is exactly recoverable, which the models rely on."""

    def test_move_turn_and_still_are_distinguishable(self):
        from superpac.pacman.perception import RivalView
        before = RivalView("r", 3, 4, EAST, 5.0, 0)
        self.assertEqual(infer_action(before, RivalView("r", 4, 4, EAST, 5.0, 0)), MOVE)
        self.assertEqual(infer_action(before, RivalView("r", 3, 4, NORTH, 5.0, 0)),
                         TURN_TO[NORTH])
        self.assertEqual(infer_action(before, RivalView("r", 3, 4, EAST, 5.0, 0)), STILL)

    def test_model_learns_the_engine_default_bot(self):
        board, me = make_board(seed=9)
        registry = RivalRegistry()
        for turn in range(150):
            snapshot = observe(me, turn)
            registry.update(snapshot)
            registry.predict_all(snapshot)
            step_rivals(board, me)
        snapshot = observe(me, 150)
        registry.update(snapshot)
        predictions = registry.predict_all(snapshot)
        self.assertTrue(predictions, "no rivals survived to model")
        # This engine version uses random.choice(range(2)), so the bot never
        # *chooses* to stand still - but standing still is still observed
        # about an eighth of the time, because a quarter of its turns pick the
        # direction it is already facing and nothing happens. From the board
        # that is indistinguishable from standing still, which is exactly what
        # the model should learn.
        for distribution in predictions.values():
            self.assertGreater(distribution[MOVE], 0.30,
                               "MOVE should dominate at roughly one half")
            self.assertGreater(sum(distribution[a] for a in range(4)), 0.20,
                               "real direction changes should be visible")
            self.assertLess(distribution[STILL], 0.30,
                            "STILL is only reachable as a no-op turn")


if __name__ == "__main__":
    unittest.main()
