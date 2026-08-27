"""State-conditioned opponent policy model (brief section 12).

Learning "opponent 2 usually goes EAST" is nearly useless: every interesting
bot conditions on the world.  This module learns
``P(action | discretised game situation)`` from a handful of cheap features
and backs off to coarser contexts when a specific one is thin on data.

The backoff ladder is what makes it work early: on turn 5 there is no data
for the full context, so the model answers from the coarse tables and quietly
sharpens as evidence accumulates.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from ..game.map_model import UNREACHABLE, MapGraph
from ..game.rules import ALL_ACTIONS, OPPOSITE
from ..game.state import GameState

#: Distance buckets: adjacent, close, medium, far.  Coarse on purpose - fine
#: buckets fragment the counts and slow learning far more than they help.
def bucket(distance: int) -> int:
    if distance <= 1:
        return 0
    if distance <= 3:
        return 1
    if distance <= 6:
        return 2
    return 3


class ObservationContext:
    """Everything the models need about one player at one instant.

    Built once per opponent per turn and reused by every hypothesis, which
    matters: the food and threat BFS calls in here are the single largest
    per-turn cost in the modelling layer.
    """

    __slots__ = ("state", "player", "pos", "turn", "legal", "food_action",
                 "food_dist", "enemy_action", "enemy_dist", "degree",
                 "last_action", "nearest_enemy", "in_dead_end", "score_rank",
                 "rival_dist", "flee_action")

    def __init__(self, state: GameState, player: int,
                 last_action: int = 4) -> None:
        graph = state.graph
        self.state = state
        self.player = player
        self.pos = state.positions[player]
        self.turn = state.turn
        self.last_action = last_action
        self.legal = graph.legal_actions(self.pos, state.rules.allow_stay) if self.pos >= 0 else (4,)

        if self.pos >= 0 and state.food:
            _, fd, fa = graph.nearest_target(self.pos, state.food)
            self.food_dist, self.food_action = fd, fa
        else:
            self.food_dist, self.food_action = UNREACHABLE, 4

        rivals = [state.positions[p] for p in range(state.n_players)
                  if p != player and state.alive[p] and state.positions[p] >= 0]
        if rivals and self.pos >= 0:
            # One multi-source BFS answers three questions at once: how close
            # the nearest rival is, which way it lies, and which legal move
            # runs furthest from all of them.  Cheaper than three searches and
            # the flee field is what the escape hypotheses need anyway.
            self.rival_dist = graph.multi_source_distances(rivals)
            self.enemy_dist = self.rival_dist[self.pos]
            best_towards, best_away = 4, 4
            towards_d, away_d = UNREACHABLE, -1
            for i, nb in enumerate(graph.neighbors[self.pos]):
                act = graph.neighbor_actions[self.pos][i]
                d = self.rival_dist[nb]
                if d < towards_d:
                    towards_d, best_towards = d, act
                # Ties on distance are broken by escape routes: running into a
                # corridor is not really running away.
                if (d > away_d) or (d == away_d and graph.degree[nb] > graph.degree[graph.step(self.pos, best_away)]):
                    away_d, best_away = d, act
            self.enemy_action = best_towards
            self.flee_action = best_away
            self.nearest_enemy = min(rivals, key=lambda r: graph.distance(self.pos, r))
        else:
            self.rival_dist = None
            self.enemy_dist, self.enemy_action, self.nearest_enemy = UNREACHABLE, 4, -1
            self.flee_action = 4

        self.degree = graph.degree[self.pos] if self.pos >= 0 else 0
        self.in_dead_end = bool(graph.is_dead_end[self.pos]) if self.pos >= 0 else False
        mine = state.scores[player]
        self.score_rank = sum(1 for p in range(state.n_players)
                              if p != player and state.alive[p] and state.scores[p] > mine)

    # -- discrete keys, coarse to fine ---------------------------------
    def key_full(self) -> Tuple[int, ...]:
        return (self.food_action, bucket(self.food_dist), self.enemy_action,
                bucket(self.enemy_dist), self.degree, self.last_action)

    def key_mid(self) -> Tuple[int, ...]:
        return (self.food_action, bucket(self.food_dist),
                self.enemy_action, bucket(self.enemy_dist))

    def key_small(self) -> Tuple[int, ...]:
        return (self.food_action, bucket(self.enemy_dist))

    def key_tiny(self) -> Tuple[int, ...]:
        return (self.food_action,)

    def keys(self) -> Tuple[Tuple[int, ...], ...]:
        return (self.key_full(), self.key_mid(), self.key_small(), self.key_tiny())


class ContextPolicyModel:
    """Backed-off frequency tables over ``P(action | context)``.

    Four tables of decreasing specificity are updated together.  Prediction
    walks from the most specific table that has enough evidence, blending in
    coarser levels so a single observation cannot produce a confident answer.
    """

    LEVELS = 4
    #: Evidence needed before a level is trusted on its own.
    CONFIDENT_AT = (6.0, 10.0, 16.0, 24.0)

    def __init__(self, decay: float = 0.992, prior: float = 0.35) -> None:
        self.tables: List[Dict[Tuple[int, ...], List[float]]] = [
            {} for _ in range(self.LEVELS)
        ]
        self.decay = decay
        self.prior = prior
        self.observations = 0

    # ------------------------------------------------------------------
    def observe(self, ctx: ObservationContext, action: int) -> None:
        self.observations += 1
        for level, key in enumerate(ctx.keys()):
            row = self.tables[level].get(key)
            if row is None:
                row = [0.0] * 5
                self.tables[level][key] = row
            # Exponential forgetting keeps the model responsive to a bot that
            # switches strategy mid-match instead of averaging it away.
            if self.decay < 1.0:
                for i in range(5):
                    row[i] *= self.decay
            row[action] += 1.0

    # ------------------------------------------------------------------
    def predict(self, ctx: ObservationContext) -> List[float]:
        legal = ctx.legal
        blended = [0.0] * 5
        weight_total = 0.0
        for level, key in enumerate(ctx.keys()):
            row = self.tables[level].get(key)
            if row is None:
                continue
            mass = sum(row)
            if mass <= 0.0:
                continue
            # A specific table with plenty of evidence dominates; a thin one
            # only nudges.  Specific levels are weighted up so they win once
            # they have earned it.
            trust = min(1.0, mass / self.CONFIDENT_AT[level])
            weight = trust * (self.LEVELS - level) ** 2
            for i in range(5):
                blended[i] += weight * row[i] / mass
            weight_total += weight

        out = [0.0] * 5
        prior = self.prior
        for action in legal:
            base = blended[action] / weight_total if weight_total > 0 else 0.0
            out[action] = base + prior / len(legal)
        total = sum(out)
        if total <= 0:
            share = 1.0 / len(legal)
            return [share if a in legal else 0.0 for a in range(5)]
        return [v / total for v in out]

    # ------------------------------------------------------------------
    def evidence(self, ctx: ObservationContext) -> float:
        """How much data backs the most specific matching context."""
        for level, key in enumerate(ctx.keys()):
            row = self.tables[level].get(key)
            if row:
                mass = sum(row)
                if mass >= self.CONFIDENT_AT[level]:
                    return mass
        return 0.0

    def size(self) -> int:
        return sum(len(t) for t in self.tables)

    def prune(self, max_rows: int = 900) -> None:
        """Drop the least-supported rows so memory stays bounded."""
        for level in range(self.LEVELS):
            table = self.tables[level]
            if len(table) <= max_rows:
                continue
            ordered = sorted(table.items(), key=lambda kv: sum(kv[1]))
            for key, _ in ordered[: len(table) - max_rows]:
                del table[key]


__all__ = ["ObservationContext", "ContextPolicyModel", "bucket"]
