"""Measure the opponent-modelling layer on its own terms (brief section 8/14).

Game performance is a noisy, lagging proxy for prediction quality.  This
benchmark isolates the modelling layer: it runs real matches, has an observer
maintain the full :class:`OpponentRegistry`, and reports how well each rival
was predicted *by archetype*.  If the periodicity detector regresses, this
notices immediately; the tournament might not for thousands of games.
"""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Callable, Dict, List, Sequence, Tuple

from ..game.state import GameState
from ..opponents.model import OpponentRegistry
from ..simulation.scenario import Scenario, standard_scenarios
from ..simulation.tournament import run_game


class ObserverProbe:
    """Rides along in a match and models every other player."""

    def __init__(self) -> None:
        self.registry = OpponentRegistry()
        self.hits: Dict[int, int] = defaultdict(int)
        self.total: Dict[int, int] = defaultdict(int)
        self.logloss: Dict[int, float] = defaultdict(float)
        self.pending: Dict[int, List[float]] = {}

    def observe(self, state: GameState) -> None:
        import math
        # Score the predictions we made last turn against what happened.
        for player, dist in self.pending.items():
            prev = self.registry._last_positions.get(player)
            cur = state.positions[player]
            if prev is None or cur < 0 or prev < 0:
                continue
            action = 4 if prev == cur else state.graph.action_between(prev, cur)
            if prev != cur and action == 4:
                continue
            self.total[player] += 1
            if max(range(5), key=lambda a: dist[a]) == action:
                self.hits[player] += 1
            self.logloss[player] += -math.log(max(1e-9, dist[action]))
        self.registry.update(state)
        self.pending = {p: self.registry.model_for(p).predict(state)
                        for p in range(state.n_players)
                        if p != state.me and state.alive[p]}

    def accuracy(self, player: int) -> float:
        return self.hits[player] / self.total[player] if self.total[player] else 0.0

    def mean_logloss(self, player: int) -> float:
        return self.logloss[player] / self.total[player] if self.total[player] else 0.0


def benchmark_prediction(entries: Sequence[Tuple[str, Callable[[], object]]],
                         scenarios: Sequence[Scenario],
                         n_players: int = 4) -> Dict[str, Dict[str, float]]:
    """Return per-archetype accuracy, log loss and identified hypothesis."""
    stats: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {"acc": 0.0, "logloss": 0.0, "conf": 0.0, "n": 0.0})
    identified: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    # Every entry must occupy a *measured* seat (seat 0 is the observer and is
    # never scored), so rotate the whole roster rather than chunking it.
    for scenario in scenarios:
        for start in range(len(entries)):
            table = [entries[(start + i) % len(entries)] for i in range(n_players)]
            probe = ObserverProbe()
            run_game([t[1] for t in table],
                     Scenario(scenario.seed, scenario.spec, scenario.rules, n_players),
                     on_turn=lambda st, acts: probe.observe(st))
            for seat, (name, _) in enumerate(table):
                if seat == 0 or probe.total[seat] < 10:
                    continue
                row = stats[name]
                row["acc"] += probe.accuracy(seat)
                row["logloss"] += probe.mean_logloss(seat)
                model = probe.registry.model_for(seat)
                row["conf"] += model.confidence()
                row["n"] += 1
                identified[name][model.ensemble.best()[0]] += 1

    out: Dict[str, Dict[str, float]] = {}
    for name, row in stats.items():
        n = max(1.0, row["n"])
        top = max(identified[name].items(), key=lambda kv: kv[1]) if identified[name] else ("-", 0)
        out[name] = {
            "accuracy": row["acc"] / n,
            "logloss": row["logloss"] / n,
            "confidence": row["conf"] / n,
            "games": row["n"],
            "identified_as": top[0],
            "identified_share": top[1] / n,
        }
    return out


def render(results: Dict[str, Dict[str, float]]) -> str:
    header = (f"{'archetype':<16s} {'top-1 acc':>9s} {'logloss':>8s} "
              f"{'confidence':>11s} {'identified as':>16s} {'share':>6s}")
    lines = [header, "-" * len(header)]
    for name, row in sorted(results.items(), key=lambda kv: -kv[1]["accuracy"]):
        lines.append(
            f"{name:<16s} {row['accuracy']:>8.1%} {row['logloss']:>8.3f} "
            f"{row['confidence']:>11.2f} {str(row['identified_as']):>16s} "
            f"{row['identified_share']:>5.0%}")
    return "\n".join(lines)


__all__ = ["benchmark_prediction", "ObserverProbe", "render"]
