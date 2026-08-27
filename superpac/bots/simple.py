"""Baseline opponents: random, fixed-priority, greedy and cluster bots.

These are the *training population*.  They exist to be diverse rather than
strong: SUPERPAC must not learn "beat one archetype", so the set deliberately
spans deterministic, periodic, stochastic, reactive and predictive styles.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from ..game.map_model import UNREACHABLE
from ..game.rules import EAST, MOVE_ACTIONS, NORTH, SOUTH, STAY, WEST
from ..game.state import GameState
from .base import Bot


class RandomBot(Bot):
    """Uniform over legal actions - the entropy floor of the population."""

    name = "random"

    def act(self, state: GameState) -> int:
        return self.random_legal(state)


class FixedPriorityBot(Bot):
    """Takes the first legal action from a fixed preference order.

    Perfectly deterministic and therefore the easiest possible exploit
    target: SUPERPAC's pattern detector should lock onto this within a
    handful of turns.
    """

    name = "fixed_priority"

    def __init__(self, seed: Optional[int] = None,
                 order: Sequence[int] = (EAST, SOUTH, WEST, NORTH)) -> None:
        super().__init__(seed)
        self.order = tuple(order)

    def act(self, state: GameState) -> int:
        legal = self.legal(state)
        for action in self.order:
            if action in legal:
                return action
        return STAY


class GreedyFoodBot(Bot):
    """Walks the shortest path to the nearest pellet.  Ignores everyone."""

    name = "greedy"

    def act(self, state: GameState) -> int:
        _, _, action = state.graph.nearest_target(state.my_position, state.food)
        legal = self.legal(state)
        return action if action in legal else self.random_legal(state)


class NoisyGreedyBot(Bot):
    """Greedy with a fixed chance of a random move - deliberately hard to
    predict *perfectly*, so SUPERPAC's confidence estimate must cap out below
    certainty rather than overfitting the noise."""

    name = "noisy_greedy"

    def __init__(self, seed: Optional[int] = None, noise: float = 0.10) -> None:
        super().__init__(seed)
        self.noise = noise

    def act(self, state: GameState) -> int:
        if self.rng.random() < self.noise:
            return self.random_legal(state)
        _, _, action = state.graph.nearest_target(state.my_position, state.food)
        legal = self.legal(state)
        return action if action in legal else self.random_legal(state)


class ClusterFoodBot(Bot):
    """Targets the densest reachable pocket of food rather than the closest
    single pellet - a genuinely stronger harvesting policy."""

    name = "cluster"

    def __init__(self, seed: Optional[int] = None, radius: int = 4) -> None:
        super().__init__(seed)
        self.radius = radius

    def act(self, state: GameState) -> int:
        graph = state.graph
        food = state.food
        if not food:
            return self.random_legal(state)
        dist = graph.distances_from(state.my_position)
        best_cell, best_value = -1, -1.0
        # Scanning every pellet is affordable because the distance row is
        # either a cached BFS or a slice of the all-pairs table.
        for cell in food:
            d = dist[cell]
            if d >= UNREACHABLE:
                continue
            local = graph.distances_from(cell)
            nearby = sum(1 for f in food if local[f] <= self.radius)
            value = nearby / (d + 1.0)
            if value > best_value:
                best_cell, best_value = cell, value
        if best_cell < 0:
            return self.random_legal(state)
        action = graph.first_step_towards(state.my_position, best_cell)
        legal = self.legal(state)
        return action if action in legal else self.random_legal(state)


__all__ = ["RandomBot", "FixedPriorityBot", "GreedyFoodBot", "NoisyGreedyBot",
           "ClusterFoodBot"]
