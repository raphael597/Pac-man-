#!/usr/bin/env python3
"""Where does a SUPERPAC turn actually go?  Profile before optimising."""
from __future__ import annotations

import cProfile
import io
import os
import pstats
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from superpac.ai.superpac import SuperPac
from superpac.bots.reactive import GreedyEscapeBot
from superpac.bots.simple import GreedyFoodBot, RandomBot
from superpac.simulation.scenario import standard_scenarios
from superpac.simulation.tournament import run_game

HOLDER = {}


def _make():
    agent = SuperPac(seed=3)
    HOLDER["agent"] = agent
    return agent


def play(n_games: int = 6) -> None:
    for scenario in standard_scenarios(n_games, 4, base_seed=90000):
        run_game([_make, lambda: GreedyFoodBot(1),
                  lambda: GreedyEscapeBot(2), lambda: RandomBot(3)], scenario)


def phase_timings(turns: int = 120) -> None:
    """Time each stage of the pipeline separately."""
    import random

    from superpac.ai.evaluator import TurnFields, Weights
    from superpac.ai.planner import Planner
    from superpac.ai.strategy import StrategyManager
    from superpac.ai.territory import TerritoryAnalysis
    from superpac.ai.threat import ThreatMap
    from superpac.opponents.model import OpponentRegistry
    from superpac.simulation.scenario import MapSpec, generate_map, make_state

    rng = random.Random(11)
    graph = generate_map(MapSpec(21, 15), rng)
    state = make_state(graph, 4, rng)
    registry = OpponentRegistry()
    weights = Weights()
    planner = Planner(random.Random(0))
    manager = StrategyManager(weights)

    totals = {k: 0.0 for k in
              ("model update", "forecast+threat", "territory", "turn fields",
               "strategy", "search")}
    for _ in range(turns):
        t = time.perf_counter(); registry.update(state)
        totals["model update"] += time.perf_counter() - t

        t = time.perf_counter()
        threat = ThreatMap(state, registry.forecast_all(state, 4), 4)
        totals["forecast+threat"] += time.perf_counter() - t

        t = time.perf_counter(); territory = TerritoryAnalysis(state)
        totals["territory"] += time.perf_counter() - t

        t = time.perf_counter()
        confidence = registry.mean_confidence(state)
        mode = manager.select(state, territory, threat, confidence)
        active = manager.weights_for(mode)
        totals["strategy"] += time.perf_counter() - t

        t = time.perf_counter()
        fields = TurnFields(state, territory, threat, active)
        totals["turn fields"] += time.perf_counter() - t

        t = time.perf_counter()
        planner.plan(state, fields, territory, threat, registry, active,
                     time.perf_counter() + 0.062)
        totals["search"] += time.perf_counter() - t

        # advance the world a little so the models keep learning
        for pid in range(state.n_players):
            legal = graph.legal_actions(state.positions[pid], True)
            state.positions[pid] = graph.step(state.positions[pid],
                                              rng.choice(legal))
            state.food.discard(state.positions[pid])
        state.turn += 1
        state._legal_cache = None

    grand = sum(totals.values())
    print(f"\nper-turn phase breakdown ({turns} turns, 21x15 map, 4 players)")
    print("-" * 58)
    for name, total in sorted(totals.items(), key=lambda kv: -kv[1]):
        ms = total / turns * 1000
        print(f"  {name:<18s} {ms:7.3f} ms   {total / grand:6.1%}")
    print(f"  {'TOTAL':<18s} {grand / turns * 1000:7.3f} ms")


def main() -> None:
    print("=" * 58)
    print("SUPERPAC profiling report")
    print("=" * 58)

    phase_timings()

    profiler = cProfile.Profile()
    profiler.enable()
    play()
    profiler.disable()

    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream).sort_stats("tottime")
    stats.print_stats(18)
    print("\n\ncumulative hot spots (6 full matches)")
    print("-" * 58)
    for line in stream.getvalue().splitlines():
        if line.strip() and not line.startswith("   Ordered"):
            print(line)

    agent = HOLDER.get("agent")
    if agent is not None:
        print(f"\nlast agent: {agent.timing_report()}")


if __name__ == "__main__":
    main()
