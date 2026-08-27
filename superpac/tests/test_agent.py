"""Agent-level tests: legality, timing, fallback, survival, adapter dialects."""
from __future__ import annotations

import random
import time
import unittest

from superpac.ai.evaluator import TurnFields, Weights
from superpac.ai.planner import Planner
from superpac.ai.strategy import Mode, StrategyManager
from superpac.ai.superpac import SuperPac
from superpac.ai.territory import TerritoryAnalysis
from superpac.ai.threat import ThreatMap
from superpac.game.adapter import StateExtractor
from superpac.game.map_model import graph_from_lines
from superpac.game.rules import DEFAULT_RULES, EAST, NORTH, SOUTH, STAY, WEST
from superpac.game.state import GameState
from superpac.opponents.model import OpponentRegistry
from superpac.simulation.scenario import MapSpec, generate_map, make_state, standard_scenarios
from superpac.simulation.tournament import run_game

ASCII_MAP = ["###########",
             "#....#....#",
             "#.##.#.##.#",
             "#....#....#",
             "#.##...##.#",
             "#.........#",
             "###########"]


def sample_state(seed: int = 5, players: int = 4) -> GameState:
    rng = random.Random(seed)
    graph = generate_map(MapSpec(21, 15), rng)
    return make_state(graph, players, rng)


class TestLegality(unittest.TestCase):
    def test_never_returns_an_illegal_action(self):
        for seed in range(6):
            state = sample_state(seed)
            agent = SuperPac(seed=seed)
            agent.reset(state, 0)
            for _ in range(25):
                action = agent.act(state)
                self.assertIn(action, state.legal_actions(state.me))
                state.positions[0] = state.graph.step(state.positions[0], action)
                state.food.discard(state.positions[0])
                state.turn += 1
                state._legal_cache = None

    def test_boxed_in_player_still_answers(self):
        graph = graph_from_lines(["###", "#.#", "###"])
        state = GameState(graph, [], [graph.index(1, 1)])
        agent = SuperPac(seed=1)
        agent.reset(state, 0)
        self.assertEqual(agent.act(state), STAY)

    def test_no_stay_variant_is_respected(self):
        rules = DEFAULT_RULES.with_(allow_stay=False)
        rng = random.Random(3)
        graph = generate_map(MapSpec(15, 11), rng, rules)
        state = make_state(graph, 3, rng, rules)
        agent = SuperPac(seed=1, rules=rules)
        agent.reset(state, 0)
        for _ in range(15):
            action = agent.act(state)
            self.assertNotEqual(action, STAY)
            self.assertIn(action, state.legal_actions(state.me))
            state.positions[0] = graph.step(state.positions[0], action)
            state.turn += 1
            state._legal_cache = None


class TestTiming(unittest.TestCase):
    def test_respects_a_tight_budget(self):
        state = sample_state(9)
        agent = SuperPac(seed=1, time_budget_ms=20.0)
        agent.reset(state, 0)
        for _ in range(30):
            start = time.perf_counter()
            agent.act(state)
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            # Generous ceiling: the point is that the anytime loop bounds the
            # search, not that a shared CI box hits an exact number.
            self.assertLess(elapsed_ms, 20.0 * 3)
            state.turn += 1

    def test_deeper_budget_searches_deeper(self):
        state = sample_state(4)
        shallow = SuperPac(seed=1, time_budget_ms=1.0)
        deep = SuperPac(seed=1, time_budget_ms=200.0)
        shallow.reset(state, 0); deep.reset(state, 0)
        shallow.act(state); deep.act(state)
        self.assertGreaterEqual(deep.last_plan.depth_reached,
                                shallow.last_plan.depth_reached)


class TestFallback(unittest.TestCase):
    def test_fallback_is_legal_and_prefers_food(self):
        graph = graph_from_lines(ASCII_MAP)
        state = GameState(graph, [graph.index(2, 1)],
                          [graph.index(1, 1), graph.index(9, 5)])
        agent = SuperPac(seed=1)
        agent.reset(state, 0)
        action = agent.fallback(state)
        self.assertIn(action, state.legal_actions(0))
        self.assertEqual(action, EAST, "an adjacent pellet should be taken")

    def test_fallback_avoids_an_adjacent_rival(self):
        graph = graph_from_lines(["#######", "#.....#", "#######"])
        state = GameState(graph, [], [graph.index(3, 1), graph.index(4, 1)])
        agent = SuperPac(seed=1)
        agent.reset(state, 0)
        self.assertEqual(agent.fallback(state), WEST,
                         "must not step onto a rival when contact is lethal")

    def test_agent_recovers_from_a_broken_subsystem(self):
        state = sample_state(2)
        agent = SuperPac(seed=1)
        agent.reset(state, 0)

        class Exploding:
            def update(self, *a, **k):
                raise RuntimeError("boom")

        agent.registry = Exploding()          # type: ignore[assignment]
        action = agent.act(state)
        self.assertIn(action, state.legal_actions(state.me))
        self.assertEqual(agent.faults, 1)


class TestSurvival(unittest.TestCase):
    def test_walks_away_from_a_lethal_pincer(self):
        # Corridor: rivals at both ends, one step away on the left.
        graph = graph_from_lines(["#########", "#.......#", "#########"])
        state = GameState(graph, [graph.index(1, 1)],
                          [graph.index(3, 1), graph.index(2, 1)])
        agent = SuperPac(seed=1)
        agent.reset(state, 0)
        agent.registry.update(state)
        action = agent.act(state)
        self.assertEqual(action, EAST,
                         "stepping toward the adjacent rival is suicide")

    # Ring on the left, three-cell tail running east off the junction (3,2).
    RING_AND_TAIL = ["########", "#...####", "#.#....#", "#...####", "########"]

    def _fields(self, state, agent):
        registry = OpponentRegistry()
        for _ in range(3):
            registry.update(state)
        threat = ThreatMap(state, registry.forecast_all(state, 4), 4)
        territory = TerritoryAnalysis(state)
        return TurnFields(state, territory, threat, Weights())

    def test_trap_risk_is_zero_on_a_cycle(self):
        graph = graph_from_lines(self.RING_AND_TAIL)
        state = GameState(graph, [graph.index(6, 2)],
                          [graph.index(3, 2), graph.index(2, 1)])
        fields = self._fields(state, None)
        for x, y in ((1, 1), (2, 1), (3, 1), (1, 3)):
            self.assertEqual(fields.trap_risk(graph.index(x, y)), 0.0,
                             "a cell on a loop commits you to nothing")

    def test_trap_risk_rises_as_a_rival_nears_the_mouth(self):
        graph = graph_from_lines(self.RING_AND_TAIL)
        tail = graph.index(4, 2)

        near = GameState(graph, [graph.index(6, 2)],
                         [graph.index(3, 2), graph.index(2, 1)])
        far = GameState(graph, [graph.index(6, 2)],
                        [graph.index(3, 2), graph.index(1, 3)])
        risk_near = self._fields(near, None).trap_risk(tail)
        risk_far = self._fields(far, None).trap_risk(tail)
        self.assertGreater(risk_near, 0.0)
        self.assertGreater(risk_near, risk_far,
                           "the danger of a pocket is the race for its mouth")

    def test_a_threatened_pocket_scores_worse_than_a_safe_one(self):
        graph = graph_from_lines(self.RING_AND_TAIL)
        tail = graph.index(4, 2)
        near = GameState(graph, [graph.index(6, 2)],
                         [graph.index(3, 2), graph.index(2, 1)])
        far = GameState(graph, [graph.index(6, 2)],
                        [graph.index(3, 2), graph.index(1, 3)])
        self.assertLess(self._fields(near, None).positional_score(tail),
                        self._fields(far, None).positional_score(tail))


class TestStrategy(unittest.TestCase):
    def test_survival_mode_needs_every_exit_to_be_bad(self):
        # Cornered: rivals on both sides in a corridor, so even standing
        # still can be walked into.
        graph = graph_from_lines(["#######", "#.....#", "#######"])
        state = GameState(graph, [],
                          [graph.index(3, 1), graph.index(2, 1), graph.index(4, 1)])
        registry = OpponentRegistry()
        registry.update(state)
        threat = ThreatMap(state, registry.forecast_all(state, 4), 4)
        territory = TerritoryAnalysis(state)
        manager = StrategyManager(Weights())
        mode = manager.select(state, territory, threat, 0.5)
        self.assertEqual(mode, Mode.SURVIVAL)

    def test_a_single_safe_exit_is_not_an_emergency(self):
        # Rivals two and three cells away: STAY is safe this turn, so
        # SURVIVAL must not fire and throw away the whole turn's value.
        graph = graph_from_lines(["#######", "#.....#", "#######"])
        state = GameState(graph, [graph.index(1, 1)],
                          [graph.index(1, 1), graph.index(3, 1), graph.index(4, 1)])
        registry = OpponentRegistry()
        registry.update(state)
        threat = ThreatMap(state, registry.forecast_all(state, 4), 4)
        manager = StrategyManager(Weights())
        mode = manager.select(state, TerritoryAnalysis(state), threat, 0.5)
        self.assertNotEqual(mode, Mode.SURVIVAL)

    def test_endgame_mode_follows_the_score(self):
        state = sample_state(1)
        state.turn = int(state.rules.max_turns * 0.9)
        registry = OpponentRegistry(); registry.update(state)
        threat = ThreatMap(state, registry.forecast_all(state, 2), 2)
        territory = TerritoryAnalysis(state)
        manager = StrategyManager(Weights())

        state.scores = [50.0, 1.0, 1.0, 1.0]
        self.assertEqual(manager.select(state, territory, threat, 0.5),
                         Mode.ENDGAME_LEADING)
        state.scores = [1.0, 50.0, 1.0, 1.0]
        self.assertEqual(manager.select(state, territory, threat, 0.5),
                         Mode.ENDGAME_TRAILING)

    def test_trailing_endgame_accepts_more_variance(self):
        manager = StrategyManager(Weights())
        leading = manager.weights_for(Mode.ENDGAME_LEADING)
        trailing = manager.weights_for(Mode.ENDGAME_TRAILING)
        self.assertGreater(leading.risk_aversion, trailing.risk_aversion)
        self.assertGreater(trailing.food, leading.food)


class TestPlanner(unittest.TestCase):
    def _context(self, state):
        registry = OpponentRegistry(); registry.update(state)
        threat = ThreatMap(state, registry.forecast_all(state, 4), 4)
        territory = TerritoryAnalysis(state)
        weights = Weights()
        fields = TurnFields(state, territory, threat, weights)
        return registry, threat, territory, weights, fields

    def test_scenarios_are_a_probability_distribution(self):
        state = sample_state(3)
        registry, threat, territory, weights, fields = self._context(state)
        planner = Planner(random.Random(0))
        scenarios = planner._build_scenarios(state, registry, 6)
        self.assertLessEqual(len(scenarios), 6)
        self.assertAlmostEqual(sum(p for p, _ in scenarios), 1.0, places=6)
        for _, assignment in scenarios:
            for cell in assignment.values():
                self.assertTrue(state.graph.passable[cell])

    def test_cvar_never_exceeds_the_mean(self):
        state = sample_state(3)
        registry, threat, territory, weights, fields = self._context(state)
        planner = Planner(random.Random(0))
        scenarios = planner._build_scenarios(state, registry, 6)
        pos = state.my_position
        for action in state.legal_actions(0):
            target = state.graph.step(pos, action)
            expected, cvar = planner._scenario_outcomes(
                state, scenarios, pos, target, 10.0, weights)
            self.assertLessEqual(cvar, expected + 1e-9)

    def test_plan_returns_a_legal_action_with_scores(self):
        state = sample_state(3)
        registry, threat, territory, weights, fields = self._context(state)
        planner = Planner(random.Random(0))
        plan = planner.plan(state, fields, territory, threat, registry, weights,
                            time.perf_counter() + 0.05)
        self.assertIn(plan.action, state.legal_actions(0))
        self.assertEqual(set(plan.scores), set(state.legal_actions(0)))

    def test_tie_breaking_does_not_trade_away_real_value(self):
        planner = Planner(random.Random(0))
        weights = Weights().with_(explore_epsilon=0.05)
        scores = {NORTH: 100.0, SOUTH: 40.0, EAST: 99.9}
        picks = {planner._choose(scores, list(scores), weights) for _ in range(200)}
        self.assertNotIn(SOUTH, picks, "a clearly worse action must never be chosen")


class TestAdapterDialects(unittest.TestCase):
    """The host API is unknown, so the sniffer is load-bearing."""

    WALLS = {(x, y) for y, row in enumerate(ASCII_MAP)
             for x, ch in enumerate(row) if ch == "#"}

    def _check(self, raw, expect_swap=False, expect_flat=False):
        extractor = StateExtractor()
        state = extractor.extract(raw)
        self.assertTrue(state.graph.passable[state.my_position])
        for cell in state.food:
            self.assertTrue(state.graph.passable[cell])
        self.assertEqual(extractor.schema.swap_axes, expect_swap)
        self.assertEqual(extractor.schema.flat_ids, expect_flat)
        return state

    def test_dict_with_ascii_grid_and_xy(self):
        state = self._check({"grid": ASCII_MAP, "food": [(1, 1), (2, 1)],
                             "my_position": (1, 3), "opponents": [(9, 5)],
                             "turn": 4, "score": 2})
        self.assertEqual(state.turn, 4)
        self.assertEqual(state.n_players, 2)
        self.assertEqual(state.my_score, 2.0)

    def test_numeric_grid_with_row_col_order(self):
        state = self._check({
            "board": [[1 if ch == "#" else 0 for ch in row] for row in ASCII_MAP],
            "pellets": [(1, 1), (3, 1)], "pos": (3, 1),
            "enemies": [(5, 9)], "step": 2}, expect_swap=True)
        self.assertEqual(state.graph.xy(state.my_position), (1, 3))

    def test_flat_cell_ids(self):
        width = len(ASCII_MAP[0])
        state = self._check({"maze": ASCII_MAP,
                             "food": [1 * width + 1, 1 * width + 2],
                             "position": 3 * width + 1,
                             "others": [5 * width + 9], "turn": 1},
                            expect_flat=True)
        self.assertEqual(state.graph.xy(state.my_position), (1, 3))

    def test_attribute_object_with_wall_set(self):
        outer = self

        class Player:
            def __init__(self, x, y, score):
                self.x, self.y, self.score = x, y, score

        class Host:
            width, height = len(ASCII_MAP[0]), len(ASCII_MAP)
            walls = outer.WALLS
            food = {(1, 1), (2, 1)}
            players = [Player(1, 3, 2), Player(9, 5, 4)]
            my_id = 1
            tick = 12

        state = self._check(Host)
        self.assertEqual(state.me, 1)
        self.assertEqual(state.my_score, 4.0)
        self.assertEqual(state.turn, 12)

    def test_alien_state_raises_rather_than_guessing(self):
        with self.assertRaises(ValueError):
            StateExtractor().extract({"nothing": "useful"})

    def test_action_encoding_follows_the_host_vocabulary(self):
        extractor = StateExtractor()
        self.assertEqual(extractor.encode_action(NORTH), NORTH)
        extractor.learn_action_style("EAST")
        self.assertEqual(extractor.encode_action(NORTH), "NORTH")
        extractor.learn_action_style("east")
        self.assertEqual(extractor.encode_action(NORTH), "north")
        extractor.learn_action_style((1, 0))
        self.assertEqual(extractor.encode_action(NORTH), (0, -1))


class TestFullMatch(unittest.TestCase):
    def test_plays_a_whole_match_without_faults_or_timeouts(self):
        from superpac.bots.simple import GreedyFoodBot, RandomBot
        from superpac.bots.reactive import GreedyEscapeBot

        holder = {}

        def make():
            agent = SuperPac(seed=3)
            holder["agent"] = agent
            return agent

        result = run_game([make,
                           lambda: GreedyFoodBot(1),
                           lambda: GreedyEscapeBot(2),
                           lambda: RandomBot(3)],
                          standard_scenarios(1, 4, base_seed=1234)[0])
        self.assertEqual(result.crashes[0], 0)
        self.assertEqual(result.timeouts[0], 0)
        self.assertEqual(holder["agent"].faults, 0)
        self.assertGreater(result.turns, 5)


if __name__ == "__main__":
    unittest.main()
