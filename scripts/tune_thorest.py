#!/usr/bin/env python3
"""Evolutionary tuning for ThoresT on the teacher's engine."""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from superpac.pacman.agent import Weights
from superpac.pacman.tuning import (HOLDOUT_MIX, TRAIN_MIX, VALIDATION_MIX,
                                    clamp, crossover, mutate, random_weights,
                                    score)


def _job(args):
    vector, mix, games, seed = args
    return score(Weights.from_vector(vector), mix, games=games, base_seed=seed)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--generations", type=int, default=8)
    ap.add_argument("--population", type=int, default=12)
    ap.add_argument("--games", type=int, default=18)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="results/thorest_weights.json")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    base = clamp(Weights())
    population = [base]
    population += [mutate(base, rng, 0.35) for _ in range(args.population // 2 - 1)]
    population += [random_weights(rng, base)
                   for _ in range(args.population - len(population))]

    history = []
    start = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for generation in range(args.generations):
            # Fresh seeds per generation so the search cannot overfit one
            # board set; identical within it so candidates compare fairly.
            batch_seed = 4000 + generation * 733
            jobs = [(ind.as_vector(), TRAIN_MIX, args.games, batch_seed)
                    for ind in population]
            results = list(pool.map(_job, jobs))
            paired = sorted(zip(population, results),
                            key=lambda pr: -pr[1]["fitness"])
            best_w, best_s = paired[0]
            print(f"gen {generation}: fitness={best_s['fitness']:.4f} "
                  f"win={best_s['win_rate']:.1%} rank={best_s['rank']:.2f} "
                  f"str={best_s['strength']:.1f} vs {best_s['best_rival']:.1f} "
                  f"surv={best_s['survival']:.0%} ms={best_s['ms']:.1f}", flush=True)
            for w, s in paired[:3]:
                history.append((generation, w, s["fitness"]))

            elite = [w for w, _ in paired[:4]]
            children = []
            sigma = 0.32 * (1.0 - generation / max(1, args.generations))
            while len(children) < args.population - len(elite):
                a, b = rng.sample(elite, 2) if len(elite) > 1 else (elite[0], elite[0])
                children.append(mutate(crossover(a, b, rng), rng, max(0.08, sigma)))
            population = elite + children

        print("\nre-scoring finalists on the VALIDATION mix...", flush=True)
        seen, finalists = set(), []
        by_generation = {}
        for generation, w, fitness in history:
            key = tuple(round(v, 4) for v in w.as_vector())
            if key in seen:
                continue
            seen.add(key)
            by_generation.setdefault(generation, []).append((w, fitness))
        for group in by_generation.values():
            group.sort(key=lambda p: -p[1])
        rank = 0
        while len(finalists) < 8 and any(len(g) > rank for g in by_generation.values()):
            for generation in sorted(by_generation):
                group = by_generation[generation]
                if len(group) > rank and len(finalists) < 8:
                    finalists.append(group[rank][0])
            rank += 1
        if not any(f == base for f in finalists):
            finalists.append(base)

        jobs = [(f.as_vector(), VALIDATION_MIX, max(24, args.games * 2), 91000)
                for f in finalists]
        validation = list(pool.map(_job, jobs))

    best_index = max(range(len(finalists)), key=lambda i: validation[i]["fitness"])
    for i, (f, v) in enumerate(zip(finalists, validation)):
        tag = "  (hand-set baseline)" if f == base else ""
        mark = "  <-- champion" if i == best_index else ""
        print(f"  candidate {i}: val_fitness={v['fitness']:.4f} "
              f"win={v['win_rate']:.1%} rank={v['rank']:.2f} "
              f"str={v['strength']:.1f} vs {v['best_rival']:.1f}{tag}{mark}", flush=True)

    champion = finalists[best_index]
    os.makedirs(os.path.dirname(os.path.join(ROOT, args.out)), exist_ok=True)
    with open(os.path.join(ROOT, args.out), "w") as fh:
        json.dump({"vector": champion.as_vector(), "names": Weights.names(),
                   "weights": {n: getattr(champion, n) for n in Weights.names()},
                   "validation": validation[best_index],
                   "elapsed_s": round(time.perf_counter() - start, 1)}, fh, indent=2)
    print(f"\nchampion -> {args.out} after {time.perf_counter() - start:.0f}s")
    print(json.dumps({n: getattr(champion, n) for n in Weights.names()}, indent=2))


if __name__ == "__main__":
    main()
