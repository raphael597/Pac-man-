"""Opponents whose behaviour depends on where everyone else is."""

from __future__ import annotations

from typing import Optional

from ..game.map_model import UNREACHABLE
from ..game.rules import STAY
from ..game.state import GameState
from .base import Bot


class DefensiveBot(Bot):
    """Maximises distance from the nearest rival, collecting food only when
    nobody is close.  Exists to punish a bot that assumes everyone chases."""

    name = "defensive"

    def __init__(self, seed: Optional[int] = None, panic: int = 5) -> None:
        super().__init__(seed)
        self.panic = panic

    def act(self, state: GameState) -> int:
        graph = state.graph
        pos = state.my_position
        enemies = state.opponent_positions()
        if enemies:
            threat = graph.multi_source_distances(enemies)
            if threat[pos] <= self.panic:
                best, best_key = STAY, (-1, 0)
                for action in self.legal(state):
                    cell = graph.step(pos, action)
                    key = (min(threat[cell], 99), graph.degree[cell])
                    if key > best_key:
                        best, best_key = action, key
                return best
        _, _, action = graph.nearest_target(pos, state.food)
        legal = self.legal(state)
        return action if action in legal else self.random_legal(state)


class GreedyEscapeBot(Bot):
    """Nearest food, but flees when a rival is within ``threshold``.

    The canonical 'has a hidden parameter' opponent from the brief: SUPERPAC
    should be able to *infer* ``threshold`` from observed behaviour.
    """

    name = "greedy_escape"

    def __init__(self, seed: Optional[int] = None, threshold: int = 3) -> None:
        super().__init__(seed)
        self.threshold = threshold

    def act(self, state: GameState) -> int:
        graph = state.graph
        pos = state.my_position
        enemies = state.opponent_positions()
        legal = self.legal(state)
        if enemies:
            threat = graph.multi_source_distances(enemies)
            if threat[pos] <= self.threshold:
                best, best_val = legal[0], -1
                for action in legal:
                    cell = graph.step(pos, action)
                    val = min(threat[cell], 99) * 4 + graph.degree[cell]
                    if val > best_val:
                        best, best_val = action, val
                return best
        _, _, action = graph.nearest_target(pos, state.food)
        return action if action in legal else self.random_legal(state)


class AggressiveBot(Bot):
    """Hunts the nearest rival when close, harvests otherwise."""

    name = "aggressive"

    def __init__(self, seed: Optional[int] = None, engage: int = 7) -> None:
        super().__init__(seed)
        self.engage = engage

    def act(self, state: GameState) -> int:
        graph = state.graph
        pos = state.my_position
        enemies = state.opponent_positions()
        legal = self.legal(state)
        if enemies:
            target, dist, action = graph.nearest_target(pos, set(enemies))
            if dist <= self.engage and action in legal:
                return action
        _, _, action = graph.nearest_target(pos, state.food)
        return action if action in legal else self.random_legal(state)


class InterceptBot(Bot):
    """Aims at where a rival will be, not where it is.

    Extrapolates the target's last displacement a few steps forward and heads
    for that cell - a cheap but genuinely effective interception heuristic.
    """

    name = "intercept"

    def __init__(self, seed: Optional[int] = None, lead: int = 3) -> None:
        super().__init__(seed)
        self.lead = lead
        self.last_seen: dict = {}

    def act(self, state: GameState) -> int:
        graph = state.graph
        pos = state.my_position
        legal = self.legal(state)
        enemies = [p for p in range(state.n_players)
                   if p != state.me and state.alive[p]]

        best_action, best_dist = None, UNREACHABLE
        for p in enemies:
            here = state.positions[p]
            prev = self.last_seen.get(p, here)
            dx = (here % graph.width) - (prev % graph.width)
            dy = (here // graph.width) - (prev // graph.width)
            fx = min(graph.width - 1, max(0, here % graph.width + dx * self.lead))
            fy = min(graph.height - 1, max(0, here // graph.width + dy * self.lead))
            guess = fy * graph.width + fx
            if not graph.passable[guess]:
                guess = here
            d = graph.distance(pos, guess)
            if d < best_dist:
                best_dist = d
                best_action = graph.first_step_towards(pos, guess)
        for p in enemies:
            self.last_seen[p] = state.positions[p]

        if best_action is not None and best_dist <= 8 and best_action in legal:
            return best_action
        _, _, action = graph.nearest_target(pos, state.food)
        return action if action in legal else self.random_legal(state)


__all__ = ["DefensiveBot", "GreedyEscapeBot", "AggressiveBot", "InterceptBot"]
