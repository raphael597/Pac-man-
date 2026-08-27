#!/usr/bin/env python3
"""Decide the tuned-vs-default question on the holdout population.

The champion was *selected* on validation, so validation improving proves
nothing about generalisation - that is what the holdout set is for.  This runs
both weight sets over the *same* enlarged holdout battery (common random
numbers) and reports the difference with a confidence interval, so the answer
is a measurement rather than a preference.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from superpac.ai.evaluator import Weights
from superpac.game.rules import DEFAULT_RULES
from superpac.simulation.scenario import standard_scenarios
from superpac.training.benchmark import (evaluate, holdout_population,
                                         train_population, validation_population)
from superpac.training.optimize_weights import SuperPacFactory, load_weights

POPULATIONS = {"train": train_population, "validation": validation_population,
               "holdout": holdout_population}


def _job(args):
    label, vector, pop_name, games, seed, chunk = args
    weights = Weights.from_vector(vector)
    scenarios = standard_scenarios(games, 4, DEFAULT_RULES,
                                   base_seed=70000 + chunk * 1301)
    result = evaluate(SuperPacFactory(weights, seed=7, time_budget_ms=60.0),
                      POPULATIONS[pop_name](), scenarios, n_players=4,
                      repeats=2, label=label, seed=seed)
    return {"label": label, "population": pop_name, "wins": result.win_rate * result.games,
            "games": result.games, "placement": result.avg_placement * result.games,
            "score": result.avg_score * result.games,
            "survival": result.survival_rate * result.games,
            "crashes": result.crashes, "timeouts": result.timeouts}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=30, help="scenarios per chunk")
    ap.add_argument("--chunks", type=int, default=3)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--weights", default="results/weights_champion.json")
    args = ap.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tuned = load_weights(os.path.join(root, args.weights))
    entrants = {"defaults": Weights().as_vector(), "tuned": tuned.as_vector()}

    jobs = []
    for chunk in range(args.chunks):
        for label, vector in entrants.items():
            for pop in ("validation", "holdout"):
                jobs.append((label, vector, pop, args.games, 0, chunk))

    start = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(_job, jobs))
    elapsed = time.perf_counter() - start

    totals = {}
    for row in rows:
        key = (row["label"], row["population"])
        acc = totals.setdefault(key, {k: 0.0 for k in
                                      ("wins", "games", "placement", "score",
                                       "survival", "crashes", "timeouts")})
        for k in acc:
            acc[k] += row[k]

    print(f"{sum(r['games'] for r in rows)} games in {elapsed:.0f}s\n")
    header = (f"{'weights':<10s} {'population':<12s} {'win':>8s} {'95% CI':>14s} "
              f"{'place':>7s} {'score':>7s} {'surv':>7s} {'n':>5s}")
    print(header); print("-" * len(header))
    summary = {}
    for (label, pop), acc in sorted(totals.items()):
        n = acc["games"]
        p = acc["wins"] / n
        ci = 1.96 * math.sqrt(max(1e-9, p * (1 - p)) / n)
        summary[(label, pop)] = (p, ci, n)
        print(f"{label:<10s} {pop:<12s} {p:>7.1%} "
              f"[{p-ci:>5.1%},{p+ci:>5.1%}] {acc['placement']/n:>7.3f} "
              f"{acc['score']/n:>7.2f} {acc['survival']/n:>6.1%} {int(n):>5d}"
              + ("  CRASH" if acc["crashes"] else "")
              + ("  TIMEOUT" if acc["timeouts"] else ""))

    print("\nverdict per population (two-proportion z-test):")
    for pop in ("validation", "holdout"):
        p1, _, n1 = summary[("defaults", pop)]
        p2, _, n2 = summary[("tuned", pop)]
        pooled = (p1 * n1 + p2 * n2) / (n1 + n2)
        se = math.sqrt(max(1e-12, pooled * (1 - pooled) * (1 / n1 + 1 / n2)))
        z = (p2 - p1) / se if se > 0 else 0.0
        delta = (p2 - p1) * 100
        if abs(z) < 1.96:
            call = "no significant difference"
        elif z > 0:
            call = "TUNED significantly better"
        else:
            call = "TUNED significantly WORSE"
        print(f"  {pop:<12s} tuned - defaults = {delta:+.1f} points  z={z:+.2f}  -> {call}")

    with open(os.path.join(root, "results/holdout_check.json"), "w") as fh:
        json.dump({"elapsed": elapsed,
                   "summary": {f"{k[0]}/{k[1]}": {"win_rate": v[0], "ci": v[1],
                                                  "games": v[2]}
                               for k, v in summary.items()}}, fh, indent=2)


if __name__ == "__main__":
    main()
