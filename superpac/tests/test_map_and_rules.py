"""Map graph, distance, topology and rules tests."""
from __future__ import annotations

import unittest

from superpac.game.map_model import UNREACHABLE, MapGraph, graph_from_lines
from superpac.game.rules import (DEFAULT_RULES, DELTAS, EAST, NORTH, SOUTH,
                                 STAY, WEST, action_from_name, delta_to_action)

RING_AND_TAIL = [
    "########",
    "#...####",
    "#.#....#",
    "#...####",
    "########",
]


class TestActions(unittest.TestCase):
    def test_deltas_match_action_ids(self):
        self.assertEqual(DELTAS[NORTH], (0, -1))
        self.assertEqual(DELTAS[SOUTH], (0, 1))
        self.assertEqual(DELTAS[WEST], (-1, 0))
        self.assertEqual(DELTAS[EAST], (1, 0))
        self.assertEqual(DELTAS[STAY], (0, 0))

    def test_name_coercion_is_tolerant(self):
        for name in ("N", "north", "UP", " Up "):
            self.assertEqual(action_from_name(name), NORTH)
        self.assertEqual(action_from_name((1, 0)), EAST)
        self.assertEqual(action_from_name("garbage"), STAY)
        # bool is an int subclass - must not be read as an action id
        self.assertEqual(action_from_name(True), STAY)

    def test_delta_to_action_roundtrip(self):
        for action in range(5):
            self.assertEqual(delta_to_action(*DELTAS[action]), action)


class TestMapGraph(unittest.TestCase):
    def setUp(self):
        self.g = graph_from_lines(RING_AND_TAIL)

    def test_walkable_and_walls(self):
        self.assertEqual(len(self.g.cells), 11)
        self.assertFalse(self.g.passable[self.g.index(0, 0)])
        self.assertTrue(self.g.passable[self.g.index(1, 1)])

    def test_neighbors_never_cross_walls(self):
        for cell in self.g.cells:
            for nb in self.g.neighbors[cell]:
                self.assertTrue(self.g.passable[nb])
                ax, ay = self.g.xy(cell)
                bx, by = self.g.xy(nb)
                self.assertEqual(abs(ax - bx) + abs(ay - by), 1)

    def test_distances_are_symmetric_and_correct(self):
        a, b = self.g.index(1, 1), self.g.index(6, 2)
        self.assertEqual(self.g.distance(a, b), self.g.distance(b, a))
        self.assertEqual(self.g.distance(a, a), 0)
        # (1,1)->(2,1)->(3,1)->(3,2)->(4,2)->(5,2)->(6,2)
        self.assertEqual(self.g.distance(a, b), 6)

    def test_apsp_matches_fresh_bfs(self):
        for source in self.g.cells:
            fresh = self.g.bfs(source)
            for target in self.g.cells:
                self.assertEqual(self.g.distance(source, target), fresh[target])

    def test_dead_end_tail_measured(self):
        # The tail hangs off the junction at (3,2) and is three cells long.
        self.assertEqual(self.g.dead_end_depth[self.g.index(4, 2)], 3)
        self.assertEqual(self.g.dead_end_depth[self.g.index(6, 2)], 1)
        self.assertEqual(self.g.pocket_size[self.g.index(4, 2)], 3)
        # Ring cells commit you to nothing.
        self.assertEqual(self.g.dead_end_depth[self.g.index(1, 1)], 0)

    def test_junction_and_escape_distance(self):
        junction = self.g.index(3, 2)
        self.assertTrue(self.g.is_junction[junction])
        self.assertEqual(self.g.escape_distance[junction], 0)
        self.assertEqual(self.g.escape_distance[self.g.index(6, 2)], 3)

    def test_articulation_points_found(self):
        # Every tail cell except the last one separates the map when removed.
        self.assertTrue(self.g.articulation[self.g.index(4, 2)])
        self.assertTrue(self.g.articulation[self.g.index(3, 2)])
        self.assertFalse(self.g.articulation[self.g.index(1, 1)])

    def test_step_refuses_illegal_moves(self):
        corner = self.g.index(1, 1)
        self.assertEqual(self.g.step(corner, NORTH), corner)  # wall above
        self.assertEqual(self.g.step(corner, EAST), self.g.index(2, 1))
        self.assertEqual(self.g.step(corner, STAY), corner)

    def test_nearest_target_agrees_with_distance(self):
        src = self.g.index(1, 1)
        targets = {self.g.index(6, 2), self.g.index(1, 3)}
        cell, dist, action = self.g.nearest_target(src, targets)
        self.assertEqual(cell, self.g.index(1, 3))
        self.assertEqual(dist, self.g.distance(src, cell))
        self.assertEqual(self.g.step(src, action), self.g.index(1, 2))

    def test_nearest_target_handles_empty_and_unreachable(self):
        src = self.g.index(1, 1)
        self.assertEqual(self.g.nearest_target(src, set())[1], UNREACHABLE)
        self.assertEqual(self.g.nearest_target(src, {src})[1], 0)

    def test_multi_source_is_min_over_sources(self):
        sources = [self.g.index(1, 1), self.g.index(6, 2)]
        rows = [self.g.distances_from(s) for s in sources]
        combined = self.g.multi_source_distances(sources)
        for cell in self.g.cells:
            self.assertEqual(combined[cell], min(r[cell] for r in rows))

    def test_first_step_towards_reduces_distance(self):
        src, dst = self.g.index(1, 1), self.g.index(6, 2)
        action = self.g.first_step_towards(src, dst)
        self.assertEqual(self.g.distance(self.g.step(src, action), dst),
                         self.g.distance(src, dst) - 1)


class TestDisconnectedMap(unittest.TestCase):
    def test_regions_and_unreachable(self):
        g = graph_from_lines(["#####", "#.#.#", "#.#.#", "#####"])
        self.assertEqual(len(g.region_sizes), 2)
        a, b = g.index(1, 1), g.index(3, 1)
        self.assertGreaterEqual(g.distance(a, b), UNREACHABLE)


class TestWrapAround(unittest.TestCase):
    def test_tunnels_connect_edges(self):
        rules = DEFAULT_RULES.with_(wrap_x=True)
        g = graph_from_lines(["#####", ".....", "#####"], rules=rules)
        left, right = g.index(0, 1), g.index(4, 1)
        self.assertIn(right, g.neighbors[left])
        self.assertEqual(g.distance(left, right), 1)


if __name__ == "__main__":
    unittest.main()
