"""The comparison harness must be provably fair before it can prove anything.

This file exists because of a bug that produced a *wrong conclusion* rather
than a crash.  ``head_to_head`` originally rotated both entrants through every
seat, which looks like enough - but the other players end up arranged
differently around each entrant, and two byte-identical bots came out 10.9
percentage points apart.  Any version-vs-version measurement taken with that
harness was measuring seat luck.

A biased benchmark is worse than no benchmark: it is confidently wrong, and
every decision downstream of it inherits the error.  These tests are the
guard.
"""
from __future__ import annotations

import unittest

from superpac.bots.base import BotFactory
from superpac.bots.patterned import PeriodicBot
from superpac.bots.reactive import DefensiveBot, GreedyEscapeBot
from superpac.bots.simple import GreedyFoodBot, RandomBot
from superpac.simulation.scenario import standard_scenarios
from superpac.simulation.tournament import head_to_head, run_game


def _identical_pair():
    return (("A", BotFactory(GreedyFoodBot, "A", seed=1)),
            ("B", BotFactory(GreedyFoodBot, "B", seed=1)))


class TestHeadToHeadFairness(unittest.TestCase):
    def test_identical_bots_tie_exactly(self):
        a, b = _identical_pair()
        fillers = [("D", BotFactory(DefensiveBot, "D", seed=7)),
                   ("E", BotFactory(GreedyEscapeBot, "E", seed=8, threshold=3))]
        report = head_to_head(a, b, standard_scenarios(8, 4, base_seed=33000),
                              fillers=fillers)
        sa, sb = report.get("A"), report.get("B")
        self.assertEqual(sa.games, sb.games)
        self.assertEqual(sa.wins, sb.wins, "seat bias in the duel harness")
        self.assertEqual(sa.placement_sum, sb.placement_sum)
        self.assertAlmostEqual(sa.score_sum, sb.score_sum, places=9)

    def test_still_fair_with_asymmetric_fillers(self):
        # Distinct, differently-skilled fillers are what exposed the original
        # bug; four identical bots tie trivially and prove nothing.
        a, b = _identical_pair()
        fillers = [("R", BotFactory(RandomBot, "R", seed=3)),
                   ("P", BotFactory(PeriodicBot, "P", seed=4, period=9))]
        report = head_to_head(a, b, standard_scenarios(6, 4, base_seed=7700),
                              fillers=fillers)
        sa, sb = report.get("A"), report.get("B")
        self.assertEqual(sa.wins, sb.wins)
        self.assertEqual(sa.placement_sum, sb.placement_sum)

    def test_every_arrangement_is_played_mirrored(self):
        a, b = _identical_pair()
        scenarios = standard_scenarios(3, 4, base_seed=100)
        report = head_to_head(a, b, scenarios,
                              fillers=[("D", BotFactory(DefensiveBot, "D", seed=7))])
        # 3 scenarios x 4 seat pairs x 2 mirrored runs
        self.assertEqual(report.games_played, 3 * 4 * 2)
        self.assertEqual(report.get("A").games, 3 * 4 * 2)


class TestScenarioReproducibility(unittest.TestCase):
    def test_same_seed_gives_the_same_match(self):
        scenario = standard_scenarios(1, 4, base_seed=555)[0]
        table = [BotFactory(GreedyFoodBot, "g", seed=1),
                 BotFactory(DefensiveBot, "d", seed=2),
                 BotFactory(GreedyEscapeBot, "e", seed=3),
                 BotFactory(PeriodicBot, "p", seed=4, period=7)]
        first = run_game(table, scenario)
        second = run_game(table, scenario)
        self.assertEqual(first.scores, second.scores)
        self.assertEqual(first.placements, second.placements)
        self.assertEqual(first.turns, second.turns)

    def test_different_seeds_give_different_maps(self):
        a = standard_scenarios(1, 4, base_seed=1)[0].build()[0]
        b = standard_scenarios(1, 4, base_seed=2)[0].build()[0]
        self.assertNotEqual(a.graph.passable, b.graph.passable)


if __name__ == "__main__":
    unittest.main()
