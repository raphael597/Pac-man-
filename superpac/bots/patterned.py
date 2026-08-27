"""Opponents with temporal structure: periodic, scripted and mode-switching.

These are the bots section 11 of the brief singles out.  Each one is
*predictable in a way a naive frequency model cannot see*, which is exactly
what the periodicity and sequence detectors are for.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence

from ..game.rules import EAST, MOVE_ACTIONS, NORTH, SOUTH, STAY, WEST
from ..game.state import GameState
from .base import Bot
from .reactive import GreedyEscapeBot
from .simple import GreedyFoodBot


class PeriodicBot(Bot):
    """``if turn % period == 0: random() else: preferred()``.

    Verbatim from the brief.  A frequency model sees "mostly EAST"; only a
    periodicity detector sees the every-``period`` anomaly coming.
    """

    name = "periodic"

    def __init__(self, seed: Optional[int] = None, period: int = 15,
                 preferred: int = EAST, jitter: int = 0) -> None:
        super().__init__(seed)
        self.period = period
        self.preferred = preferred
        self.jitter = jitter
        self._next_anomaly = period

    def act(self, state: GameState) -> int:
        legal = self.legal(state)
        if state.turn >= self._next_anomaly:
            step = self.period
            if self.jitter:
                step += self.rng.randint(-self.jitter, self.jitter)
            self._next_anomaly = state.turn + max(1, step)
            return self.rng.choice(legal)
        if self.preferred in legal:
            return self.preferred
        for action in (EAST, SOUTH, WEST, NORTH):
            if action in legal:
                return action
        return STAY


class PatternBot(Bot):
    """Cycles a fixed action script such as ``R R U R R U``.

    Invisible to an order-1 model, trivial to an order-2/3 n-gram.
    """

    name = "pattern"

    def __init__(self, seed: Optional[int] = None,
                 script: Sequence[int] = (EAST, EAST, NORTH, EAST, EAST, SOUTH)) -> None:
        super().__init__(seed)
        self.script = tuple(script)
        self.ptr = 0

    def act(self, state: GameState) -> int:
        legal = self.legal(state)
        for _ in range(len(self.script)):
            action = self.script[self.ptr % len(self.script)]
            self.ptr += 1
            if action in legal:
                return action
        return self.random_legal(state)


class ModeSwitchBot(Bot):
    """Greedy, then aggressive, then defensive at fixed turn boundaries.

    Its long-run statistics are a meaningless blend of three policies, so a
    bot that only keeps lifetime averages will mispredict it constantly.
    That is precisely what the short/long-memory split (section 15) is for.
    """

    name = "mode_switch"

    def __init__(self, seed: Optional[int] = None,
                 boundaries: Sequence[int] = (40, 60)) -> None:
        super().__init__(seed)
        self.boundaries = tuple(boundaries)
        self._greedy = GreedyFoodBot(seed)
        self._escape = GreedyEscapeBot(seed, threshold=6)

    def reset(self, state: GameState, player_id: int) -> None:
        super().reset(state, player_id)
        self._greedy.reset(state, player_id)
        self._escape.reset(state, player_id)

    def act(self, state: GameState) -> int:
        if state.turn < self.boundaries[0]:
            return self._greedy.act(state)
        if state.turn < self.boundaries[1]:
            from .reactive import AggressiveBot
            if not hasattr(self, "_aggro"):
                self._aggro = AggressiveBot(None, engage=10)
            return self._aggro.act(state)
        return self._escape.act(state)


class StochasticBot(Bot):
    """Softmax over a simple heuristic - genuinely stochastic, never
    deterministic, and therefore the bot SUPERPAC must *decline* to predict."""

    name = "stochastic"

    def __init__(self, seed: Optional[int] = None, temperature: float = 1.2) -> None:
        super().__init__(seed)
        self.temperature = temperature

    def act(self, state: GameState) -> int:
        graph = state.graph
        pos = state.my_position
        legal = self.legal(state)
        enemies = state.opponent_positions()
        threat = graph.multi_source_distances(enemies) if enemies else None

        scores: List[float] = []
        for action in legal:
            cell = graph.step(pos, action)
            value = 2.0 if cell in state.food else 0.0
            value += 0.25 * graph.degree[cell]
            if threat is not None:
                value += 0.20 * min(threat[cell], 12)
            scores.append(value)
        top = max(scores)
        weights = [math.exp((s - top) / self.temperature) for s in scores]
        total = sum(weights)
        pick = self.rng.random() * total
        acc = 0.0
        for action, weight in zip(legal, weights):
            acc += weight
            if pick <= acc:
                return action
        return legal[-1]


__all__ = ["PeriodicBot", "PatternBot", "ModeSwitchBot", "StochasticBot"]
