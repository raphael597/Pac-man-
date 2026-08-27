"""Engine rule-resolution tests - collisions, food, termination, turn order."""
from __future__ import annotations

import random
import unittest

from superpac.game.map_model import graph_from_lines
from superpac.game.rules import DEFAULT_RULES, EAST, NORTH, SOUTH, STAY, WEST
from superpac.game.state import GameState
from superpac.simulation.engine import Engine

CORRIDOR = ["#######", "#.....#", "#######"]
ROOM = ["#####", "#...#", "#...#", "#...#", "#####"]


def corridor_state(rules=None, positions=(1, 5), food=()):
    g = graph_from_lines(CORRIDOR)
    cells = [g.index(x, 1) for x in positions]
    return GameState(g, [g.index(x, 1) for x in food], cells,
                     rules=rules or DEFAULT_RULES)


class TestCollisions(unittest.TestCase):
    def test_head_on_kills_both_by_default(self):
        # Players at x=2 and x=4 both step to x=3.
        st = corridor_state(positions=(2, 4))
        Engine(st.rules, random.Random(0)).step(st, [EAST, WEST])
        self.assertEqual(st.alive, [False, False])

    def test_swap_counts_as_contact(self):
        st = corridor_state(positions=(2, 3))
        Engine(st.rules, random.Random(0)).step(st, [EAST, WEST])
        self.assertEqual(st.alive, [False, False],
                         "players trading cells pass through each other")

    def test_higher_score_survives_when_configured(self):
        rules = DEFAULT_RULES.with_(head_on_resolution="higher_score")
        st = corridor_state(rules, positions=(2, 4))
        st.scores = [5.0, 1.0]
        Engine(rules, random.Random(0)).step(st, [EAST, WEST])
        self.assertEqual(st.alive, [True, False])

    def test_none_resolution_is_harmless(self):
        rules = DEFAULT_RULES.with_(head_on_resolution="none")
        st = corridor_state(rules, positions=(2, 4))
        Engine(rules, random.Random(0)).step(st, [EAST, WEST])
        self.assertEqual(st.alive, [True, True])

    def test_blocking_refuses_the_move(self):
        rules = DEFAULT_RULES.with_(collision_mode="block")
        g = graph_from_lines(CORRIDOR)
        st = GameState(g, [], [g.index(2, 1), g.index(3, 1)], rules=rules)
        Engine(rules, random.Random(0)).step(st, [EAST, STAY])
        self.assertEqual(st.positions[0], g.index(2, 1),
                         "standing your ground beats walking in")
        self.assertEqual(st.alive, [True, True])

    def test_blocking_allows_a_moving_chain(self):
        rules = DEFAULT_RULES.with_(collision_mode="block")
        g = graph_from_lines(CORRIDOR)
        st = GameState(g, [], [g.index(2, 1), g.index(3, 1), g.index(4, 1)],
                       rules=rules)
        Engine(rules, random.Random(0)).step(st, [EAST, EAST, EAST])
        self.assertEqual([st.positions[i] for i in range(3)],
                         [g.index(3, 1), g.index(4, 1), g.index(5, 1)])

    def test_pass_mode_lets_players_share_a_cell(self):
        rules = DEFAULT_RULES.with_(collision_mode="pass",
                                    end_on_one_survivor=False)
        st = corridor_state(rules, positions=(2, 4))
        Engine(rules, random.Random(0)).step(st, [EAST, WEST])
        self.assertEqual(st.alive, [True, True])
        self.assertEqual(st.positions[0], st.positions[1])

    def test_swap_block_refuses_only_swaps(self):
        rules = DEFAULT_RULES.with_(collision_mode="swap_block",
                                    end_on_one_survivor=False)
        g = graph_from_lines(CORRIDOR)
        st = GameState(g, [], [g.index(2, 1), g.index(3, 1)], rules=rules)
        Engine(rules, random.Random(0)).step(st, [EAST, WEST])
        self.assertEqual(st.positions[0], g.index(2, 1))
        self.assertEqual(st.positions[1], g.index(3, 1))


class TestFood(unittest.TestCase):
    def test_eating_scores_and_removes(self):
        g = graph_from_lines(CORRIDOR)
        st = GameState(g, [g.index(3, 1)], [g.index(2, 1), g.index(5, 1)])
        Engine(st.rules, random.Random(0)).step(st, [EAST, STAY])
        self.assertEqual(st.scores[0], 1.0)
        self.assertNotIn(g.index(3, 1), st.food)

    def test_contested_pellet_goes_to_exactly_one_player(self):
        rules = DEFAULT_RULES.with_(collision_mode="pass",
                                    end_on_one_survivor=False)
        g = graph_from_lines(CORRIDOR)
        st = GameState(g, [g.index(3, 1)], [g.index(2, 1), g.index(4, 1)],
                       rules=rules)
        Engine(rules, random.Random(1)).step(st, [EAST, WEST])
        self.assertEqual(sum(st.scores), 1.0, "a pellet is never double-paid")

    def test_respawning_food_is_not_consumed(self):
        rules = DEFAULT_RULES.with_(food_respawn=True)
        g = graph_from_lines(CORRIDOR)
        st = GameState(g, [g.index(3, 1)], [g.index(2, 1), g.index(5, 1)],
                       rules=rules)
        Engine(rules, random.Random(0)).step(st, [EAST, STAY])
        self.assertIn(g.index(3, 1), st.food)


class TestTermination(unittest.TestCase):
    def test_ends_when_food_is_gone(self):
        st = corridor_state()
        self.assertTrue(st.is_terminal())

    def test_ends_on_one_survivor(self):
        g = graph_from_lines(CORRIDOR)
        st = GameState(g, [g.index(3, 1)], [g.index(1, 1), g.index(5, 1)])
        st.alive = [True, False]
        self.assertTrue(st.is_terminal())

    def test_ends_at_turn_limit(self):
        rules = DEFAULT_RULES.with_(max_turns=5)
        g = graph_from_lines(CORRIDOR)
        st = GameState(g, [g.index(3, 1)], [g.index(1, 1), g.index(5, 1)],
                       rules=rules, turn=5)
        self.assertTrue(st.is_terminal())

    def test_highlander_survivor_outranks_higher_score(self):
        g = graph_from_lines(CORRIDOR)
        st = GameState(g, [], [g.index(1, 1), -1])
        st.alive = [True, False]
        st.scores = [1.0, 99.0]
        result = Engine(st.rules, random.Random(0)).finalise(st, 0)
        self.assertEqual(result.winner, 0)

    def test_score_decides_when_contact_is_not_lethal(self):
        rules = DEFAULT_RULES.with_(collision_mode="pass")
        g = graph_from_lines(CORRIDOR)
        st = GameState(g, [], [g.index(1, 1), g.index(5, 1)], rules=rules)
        st.scores = [1.0, 99.0]
        result = Engine(rules, random.Random(0)).finalise(st, 0)
        self.assertEqual(result.winner, 1)


class TestSequential(unittest.TestCase):
    def test_sequential_moves_resolve_one_at_a_time(self):
        rules = DEFAULT_RULES.with_(simultaneous=False, turn_order_random=False)
        g = graph_from_lines(CORRIDOR)
        st = GameState(g, [g.index(3, 1)], [g.index(2, 1), g.index(4, 1)],
                       rules=rules)
        Engine(rules, random.Random(0)).step(st, [EAST, WEST])
        # Player 0 arrives first and takes the pellet; the collision follows.
        self.assertEqual(sum(st.scores), 1.0)


class TestEconomy(unittest.TestCase):
    def test_step_cost_and_survival_bonus_apply(self):
        rules = DEFAULT_RULES.with_(step_cost=0.1, survival_bonus=0.5,
                                    end_on_last_food=False)
        g = graph_from_lines(ROOM)
        st = GameState(g, [], [g.index(1, 1), g.index(3, 3)], rules=rules)
        Engine(rules, random.Random(0)).step(st, [EAST, STAY])
        self.assertAlmostEqual(st.scores[0], 0.4)   # moved: -0.1 +0.5
        self.assertAlmostEqual(st.scores[1], 0.5)   # stood still: +0.5


if __name__ == "__main__":
    unittest.main()
