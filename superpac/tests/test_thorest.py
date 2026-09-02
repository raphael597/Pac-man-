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
from superpac.tests.helpers import make_board, step_rivals, teacher_walls, wall_off


def _thorest(**kwargs):
    import Pacman
    return build_thorest(Pacman.Pacman, **kwargs)


class TestLegality(unittest.TestCase):
    def test_only_ever_returns_a_real_action(self):
        board, me = make_board(seed=2)
        brain = Brain()
        for _ in range(60):
            action = brain.decide(me)
            self.assertIn(action, range(N_ACTIONS))
            execute(me, action)
            step_rivals(board, me)
        self.assertEqual(brain.faults, 0)

    def test_execute_does_exactly_one_engine_thing(self):
        board, me = make_board(seed=3)
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
        board, me = make_board(seed=5)
        brain = Brain()
        for _ in range(40):
            snapshot = observe(me, brain.turn)
            action = brain.decide(me)
            if is_turn(action):
                self.assertNotEqual(action, snapshot.direction)
            execute(me, action)


class TestRobustness(unittest.TestCase):
    def test_survives_a_broken_subsystem(self):
        board, me = make_board(seed=6)
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
        board, me = make_board(seed=7, subject=_thorest(), subject_name="T")

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
        board, me = make_board(seed=8)
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
        for size in (8, 12, 20, 25):
            result = play(_thorest(), seed=size, fieldsize=size,
                          walls=[], max_turns=60)
            self.assertEqual(result.faults, 0, f"faults on a {size}x{size} board")
            self.assertGreater(result.subject_strength, 1)

    def test_works_with_the_teachers_wall_layout(self):
        result = play(_thorest(), seed=3, walls=teacher_walls(), max_turns=200)
        self.assertEqual(result.faults, 0)
        self.assertGreater(result.subject_strength, 10)


class TestPlaysWell(unittest.TestCase):
    def test_beats_the_engines_own_bots_convincingly(self):
        """The teacher's own line-up: three default Pacmen and two TRex.

        The bar is "clearly better than one of six", not a specific number.
        With six players, chance is 16.7%; a flat 60% was inherited from the
        previous engine, where matches were 100 turns and nobody hunted. Here
        matches run until one player is left and the TRex bots snowball, so
        the same bot legitimately lands lower while still dominating.
        """
        report = evaluate(_thorest(), games=12, label="thorest", max_turns=300)
        self.assertEqual(report.faults, 0)
        self.assertGreater(report.strongest_rate, 0.40,
                           f"strongest in only {report.strongest_rate:.0%} "
                           f"of games (chance would be 17%)")
        self.assertGreater(report.mean_strength, 1.5 * report.mean_best_rival)

    def test_beats_a_straight_line_harvester(self):
        import Pacman
        harvester = dict(build_opponents(Pacman.Pacman))["harvester"]
        report = evaluate(_thorest(), games=12, label="thorest", max_turns=300,
                          fillers=[(harvester, f"H{i}") for i in range(5)])
        self.assertEqual(report.faults, 0)
        # Six identical players would each end strongest 1/6 of the time.
        self.assertGreater(report.strongest_rate, 1 / 6,
                           "no better than being one harvester among six")

    def test_the_do_nothing_stub_loses(self):
        # Guards the arena itself: if a player that never acts ever comes out
        # strongest, the harness is measuring something other than the game.
        import Pacman

        class Stub(Pacman.Pacman):
            def TurnOrMoveOrStill(self):
                return

        report = evaluate(Stub, games=8, label="stub", max_turns=300)
        self.assertEqual(report.strongest, 0)
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

    def test_float_counts_are_coerced_to_int(self):
        """A tuning run writes its JSON from a float vector, so ``beam_width``
        and ``depth`` can arrive as ``27.0``.  They are handed to ``range()``,
        where a float raises - and the fault handler turns that into a silent
        fallback move every single turn.  The bot keeps playing, badly, and
        nothing in the output says so.  Coercion has to happen in the class."""
        w = Weights(beam_width=27.0, depth=14.0)
        self.assertIsInstance(w.beam_width, int)
        self.assertIsInstance(w.depth, int)
        self.assertEqual(range(w.depth), range(14))

    def test_the_shipped_weights_file_drives_a_working_brain(self):
        """Guards the file we actually ship with, not just the defaults."""
        import json
        import os
        path = os.path.join(os.path.dirname(__file__),
                            "..", "..", "results", "thorest_weights.json")
        if not os.path.exists(path):
            self.skipTest("no tuned weights checked in")
        with open(path) as handle:
            weights = Weights(**json.load(handle)["weights"])
        result = play(_thorest(weights=weights), seed=4,
                      walls=teacher_walls(), max_turns=120)
        self.assertEqual(result.faults, 0,
                         "the shipped weights put the bot on the fallback route")


if __name__ == "__main__":
    unittest.main()


class TestRuleChangeRobustness(unittest.TestCase):
    """Guards against the two most likely ways the exercise could change.

    Neither is speculative decoration: a hard-coded match length silently
    broke the attack rule past turn 100, and the engine already ships a
    ``Wall`` class that ``Field`` merely happens not to use yet.
    """

    def test_future_value_survives_outliving_the_assumed_match_length(self):
        board, me = make_board(seed=5)
        brain = Brain(total_turns=100)

        early = brain.future_value(observe(me, 0))
        self.assertGreater(early, 1.0)

        # Past the assumed end, with the board still untouched, the turn
        # budget carries no information - falling back on it would pin F to 0
        # and make "attack anything" true for every angle.
        for turn in (100, 150, 300):
            late = brain.future_value(observe(me, turn))
            self.assertAlmostEqual(late, early, delta=0.01,
                                   msg=f"F collapsed at turn {turn}")

    def test_future_value_still_falls_as_the_board_empties(self):
        import Pacman
        board, me = make_board(seed=6)
        brain = Brain(total_turns=100)
        full = brain.future_value(observe(me, 0))

        for position, entry in list(board.field.items()):
            if isinstance(entry, Pacman.Cabbage):
                del board.field[position]
                board.field[position] = Pacman.Empty(position)
        self.assertLess(brain.future_value(observe(me, 0)), 0.1 * full)

    def test_walls_are_seen_and_never_walked_into(self):
        board, me = make_board(seed=11)

        walls = wall_off(board)
        self.assertGreater(walls, 10)

        snapshot = observe(me)
        self.assertTrue(snapshot.has_walls)
        self.assertEqual(sum(snapshot.blocked), walls)
        self.assertTrue(snapshot.is_blocked(1, 1))
        self.assertFalse(snapshot.is_blocked(0, 0))

        brain = Brain()
        for _ in range(60):
            snapshot = observe(me, brain.turn)
            action = brain.decide(me)
            if action == MOVE:
                from superpac.pacman.rules import step
                target = step(snapshot.x, snapshot.y, snapshot.direction,
                              snapshot.size)
                self.assertFalse(snapshot.is_blocked(*target),
                                 "planned a move straight into a wall")
            execute(me, action)
            step_rivals(board, me)
        self.assertEqual(brain.faults, 0)

    def test_a_walled_board_still_gets_played(self):
        board, me = make_board(seed=12)
        wall_off(board)
        brain = Brain()
        for _ in range(100):
            execute(me, brain.decide(me))
            step_rivals(board, me)
        self.assertEqual(brain.faults, 0)
        self.assertGreater(me.strength, 30, "barely harvested around the walls")
