#!/usr/bin/env python3
"""Run evolutionary weight optimisation and pick a champion on validation."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from superpac.ai.evaluator import Weights
from superpac.game.rules import DEFAULT_RULES
from superpac.simulation.scenario import standard_scenarios
from superpac.training.benchmark import validation_population
from superpac.training.optimize_weights import (Individual, evolve, fitness_of,
                                                load_weights, save_weights)

_POOL = None


def _job(args):
    return fitness_of(*args)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--generations", type=int, default=8)
    ap.add_argument("--population", type=int, default=12)
    ap.add_argument("--games", type=int, default=14)
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--start", default="")
    ap.add_argument("--out", default="results/weights_champion.json")
    args = ap.parse_args()

    base = load_weights(args.start) if args.start and os.path.exists(args.start) else Weights()
    start = time.perf_counter()

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        champion, history = evolve(
            generations=args.generations, population_size=args.population,
            games=args.games, repeats=args.repeats, seed=args.seed, base=base,
            mapper=lambda jobs: pool.map(_job, jobs),
            log=lambda msg: print(msg, flush=True),
        )

        # Selection happens on VALIDATION, not on the fitness the search
        # optimised - otherwise we would just be picking the luckiest
        # overfit (brief section 46).
        print("\nre-scoring elites on the validation population...", flush=True)
        seen, unique = set(), []
        for ind in history:
            key = tuple(round(v, 4) for v in ind.weights.as_vector())
            if key not in seen:
                seen.add(key)
                unique.append(ind)
        # Round-robin across generations rather than a global fitness sort,
        # for the same reason: cross-generation fitness is not comparable.
        by_generation: dict = {}
        for ind in unique:
            by_generation.setdefault(ind.generation, []).append(ind)
        for group in by_generation.values():
            group.sort(key=lambda i: -i.fitness)
        finalists = []
        rank = 0
        while len(finalists) < 8 and any(len(g) > rank for g in by_generation.values()):
            for generation in sorted(by_generation):
                group = by_generation[generation]
                if len(group) > rank and len(finalists) < 8:
                    finalists.append(group[rank])
            rank += 1
        if not any(f.weights == base for f in finalists):
            finalists.append(Individual(base, {"fitness": 0.0}))

        scenarios = standard_scenarios(max(20, args.games * 2), 4, DEFAULT_RULES,
                                       base_seed=61000)
        jobs = [(f.weights, validation_population(), scenarios, 2, 500)
                for f in finalists]
        scores = list(pool.map(_job, jobs))

    best_index, best_score = 0, None
    for i, (finalist, score) in enumerate(zip(finalists, scores)):
        finalist.validation = score
        tag = " (hand-set baseline)" if finalist.weights == base else ""
        print(f"  candidate {i}: train={finalist.fitness:.4f} "
              f"val_fitness={score['fitness']:.4f} val_win={score['win_rate']:.1%} "
              f"place={score['placement']:.2f} ms={score['ms']:.2f}{tag}", flush=True)
        if best_score is None or score["fitness"] > best_score:
            best_index, best_score = i, score["fitness"]

    champion = finalists[best_index].weights
    elapsed = time.perf_counter() - start
    save_weights(champion, args.out, meta={
        "generations": args.generations, "population": args.population,
        "games": args.games, "elapsed_s": round(elapsed, 1),
        "validation": finalists[best_index].validation,
        "train": finalists[best_index].train,
        "selected_baseline": champion == base,
    })
    print(f"\nchampion saved to {args.out} after {elapsed:.0f}s")
    print(json.dumps(champion.to_dict(), indent=2))


if __name__ == "__main__":
    main()
