"""Multiplayer territory, contest and food-cluster analysis.

The core idea (brief section 6) is that a pellet is not worth its distance -
it is worth *the probability we actually get it*.  A pellet three steps away
that a rival reaches in two is worth almost nothing; a pellet eight steps
away that nobody else is near is worth almost all of it.

Everything here is derived from one distance row per living player, which is
an O(1) slice when the all-pairs table exists and a single BFS otherwise.
"""

from __future__ import annotations

import math
from array import array
from typing import Dict, List, Optional, Sequence, Tuple

from ..game.map_model import UNREACHABLE, MapGraph
from ..game.state import GameState

#: Contested pellets are worth this share each when arrival times tie and the
#: engine breaks ties at random.  Derived in :func:`rules.food_contest_share`.
TIE_SHARE = 0.5


class TerritoryAnalysis:
    """Who owns what, and how strongly, for one turn."""

    __slots__ = ("state", "graph", "my_dist", "opp_dists", "opp_min",
                 "owner", "my_food_share", "my_food_value", "contested_food",
                 "denied_food", "my_cells", "contested_cells", "softness",
                 "discount", "_cluster_cache")

    def __init__(self, state: GameState, softness: float = 1.4,
                 discount: float = 0.94,
                 my_dist: Optional[array] = None,
                 opp_dists: Optional[Dict[int, array]] = None) -> None:
        self.state = state
        self.graph = state.graph
        self.softness = softness
        self.discount = discount
        self._cluster_cache: Optional[List["FoodCluster"]] = None

        graph = state.graph
        self.my_dist = my_dist if my_dist is not None else graph.distances_from(state.my_position)
        if opp_dists is None:
            opp_dists = {p: graph.distances_from(state.positions[p])
                         for p in state.opponents()}
        self.opp_dists = opp_dists

        n = graph.n_cells
        if opp_dists:
            rows = list(opp_dists.values())
            if len(rows) == 1:
                self.opp_min = rows[0]
            else:
                opp_min = array("i", [UNREACHABLE]) * n
                for cell in graph.cells:
                    best = UNREACHABLE
                    for row in rows:
                        d = row[cell]
                        if d < best:
                            best = d
                    opp_min[cell] = best
                self.opp_min = opp_min
        else:
            self.opp_min = array("i", [UNREACHABLE]) * n

        self._score_territory()

    # ------------------------------------------------------------------
    def win_probability(self, cell: int) -> float:
        """Soft estimate that *we* reach ``cell`` before any rival does.

        A hard ``d_me < d_opp`` comparison assumes rivals beeline for the same
        pellet, which none of them reliably do.  The logistic keeps ties near
        one half, decays gracefully either side, and never claims certainty -
        which is what makes the territory term robust when prediction is off.
        """
        mine = self.my_dist[cell]
        if mine >= UNREACHABLE:
            return 0.0
        theirs = self.opp_min[cell]
        if theirs >= UNREACHABLE:
            return 1.0
        edge = (theirs - mine) / self.softness
        if edge > 12.0:
            return 1.0
        if edge < -12.0:
            return 0.0
        return 1.0 / (1.0 + math.exp(-edge))

    # ------------------------------------------------------------------
    def _score_territory(self) -> None:
        state = self.state
        graph = self.graph
        my_dist, opp_min = self.my_dist, self.opp_min
        discount = self.discount

        mine = contested = denied = 0
        value = 0.0
        for cell in state.food:
            d = my_dist[cell]
            if d >= UNREACHABLE:
                denied += 1
                continue
            other = opp_min[cell]
            if d < other:
                mine += 1
            elif d == other:
                contested += 1
            else:
                denied += 1
            # Discounting by distance is what stops the metric from valuing a
            # pellet forty steps away the same as one underfoot.
            value += self.win_probability(cell) * (discount ** min(d, 60))

        total = max(1, len(state.food))
        self.my_food_share = mine / total
        self.contested_food = contested
        self.denied_food = denied
        self.my_food_value = value

        my_cells = contested_cells = 0
        for cell in graph.cells:
            d, other = my_dist[cell], opp_min[cell]
            if d >= UNREACHABLE:
                continue
            if d < other:
                my_cells += 1
            elif d == other:
                contested_cells += 1
        self.my_cells = my_cells
        self.contested_cells = contested_cells

    # ------------------------------------------------------------------
    def contest_score(self, cell: int) -> float:
        """0 = uncontested, 1 = a rival gets there strictly sooner.

        Feeds the "a slightly worse but uncontested pellet is better" rule.
        """
        mine, theirs = self.my_dist[cell], self.opp_min[cell]
        if theirs >= UNREACHABLE:
            return 0.0
        if mine >= UNREACHABLE:
            return 1.0
        return 1.0 - self.win_probability(cell)

    def pressure(self, cell: int) -> float:
        """How many rivals are breathing down this cell's neck (decayed)."""
        total = 0.0
        for row in self.opp_dists.values():
            d = row[cell]
            if d < UNREACHABLE:
                total += 0.82 ** d
        return total

    def opponent_crowding(self) -> float:
        """How much the *rivals* are stepping on each other's toes.

        High crowding is an invitation to harvest elsewhere in peace, which is
        the multiplayer insight from section 32: not every interaction is
        about us.
        """
        rows = list(self.opp_dists.values())
        if len(rows) < 2:
            return 0.0
        near = 0
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                pos_j = self.state.positions[list(self.opp_dists.keys())[j]]
                d = rows[i][pos_j]
                if d < UNREACHABLE:
                    near += 1.0 / (1.0 + d)
        return near / max(1, len(rows) * (len(rows) - 1) / 2)

    # ------------------------------------------------------------------
    def clusters(self, radius: int = 3, limit: int = 14) -> List["FoodCluster"]:
        """Group nearby pellets and score each pocket as a single objective."""
        if self._cluster_cache is not None:
            return self._cluster_cache
        self._cluster_cache = build_clusters(self, radius=radius, limit=limit)
        return self._cluster_cache


class FoodCluster:
    """A pocket of food treated as one strategic objective."""

    __slots__ = ("cells", "centre", "size", "travel", "control", "value")

    def __init__(self, cells: List[int], centre: int, travel: int,
                 control: float) -> None:
        self.cells = cells
        self.centre = centre
        self.size = len(cells)
        self.travel = travel
        self.control = control
        # Section 7's formula: food per unit of travel, discounted by how
        # likely we are to keep the pocket once we get there.
        self.value = self.size / (travel + 1.0) * control

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Cluster n={self.size} travel={self.travel} ctl={self.control:.2f} v={self.value:.2f}>"


def build_clusters(analysis: TerritoryAnalysis, radius: int = 3,
                   limit: int = 14) -> List[FoodCluster]:
    """Single-link clustering of the food set by walking distance.

    Uses a BFS flood limited to ``radius`` from each unassigned pellet, so the
    cost is bounded by the food count rather than the map size.
    """
    graph = analysis.graph
    food = analysis.state.food
    if not food:
        return []
    unassigned = set(food)
    clusters: List[FoodCluster] = []
    neighbors = graph.neighbors

    while unassigned and len(clusters) < limit * 3:
        seed = min(unassigned, key=lambda c: analysis.my_dist[c])
        members: List[int] = []
        seen = {seed}
        frontier = [(seed, 0)]
        while frontier:
            cell, depth = frontier.pop()
            if cell in unassigned:
                members.append(cell)
                unassigned.discard(cell)
            if depth >= radius:
                continue
            for nb in neighbors[cell]:
                if nb not in seen:
                    seen.add(nb)
                    frontier.append((nb, depth + 1))
        if not members:
            continue
        travel = min(analysis.my_dist[c] for c in members)
        if travel >= UNREACHABLE:
            continue
        control = sum(analysis.win_probability(c) for c in members) / len(members)
        centre = min(members, key=lambda c: analysis.my_dist[c])
        clusters.append(FoodCluster(members, centre, travel, control))

    clusters.sort(key=lambda c: -c.value)
    return clusters[:limit]


__all__ = ["TerritoryAnalysis", "FoodCluster", "build_clusters"]
