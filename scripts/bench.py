#!/usr/bin/env python3
"""Parallel benchmark driver.  Writes JSON to results/ so runs are comparable.

Usage:
    python scripts/bench.py baseline --games 40
    python scripts/bench.py rules    --games 20
    python scripts/bench.py compare  --games 40   # champion vs challenger
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from superpac.ai.evaluator import Weights
from superpac.ai.superpac import SuperPac
from superpac.bots.reactive import DefensiveBot, GreedyEscapeBot
from superpac.bots.simple import ClusterFoodBot, GreedyFoodBot
from superpac.game.rules import RULE_VARIANTS
from superpac.simulation.scenario import standard_scenarios
from superpac.training.benchmark import (evaluate, holdout_population,
                                         train_population, validation_population)

POPULATIONS = {
    "train": train_population,
    "validation": validation_population,
    "holdout": holdout_population,
}


def _subject(name: str, weights_json: str = ""):
    if name == "superpac":
        w = Weights.from_vector(json.loads(weights_json)) if weights_json else None
        return lambda: SuperPac(seed=7, weights=w)
    if name == "greedy":
        return lambda: GreedyFoodBot(99)
    if name == "cluster":
        return lambda: ClusterFoodBot(99)
    if name == "defensive":
        return lambda: DefensiveBot(99)
    if name == "greedy_escape":
        return lambda: GreedyEscapeBot(99, threshold=3)
    raise ValueError(name)


def _one(job) -> Dict:
    kind, subject_name, weights_json, pop_name, games, seed, rules_name = job
    rules = RULE_VARIANTS[rules_name]
    scenarios = standard_scenarios(games, 4, rules, base_seed=7000 + seed)
    result = evaluate(_subject(subject_name, weights_json), POPULATIONS[pop_name](),
                      scenarios, n_players=4, repeats=2,
                      label=subject_name, seed=seed)
    return {
        "kind": kind, "subject": subject_name, "population": pop_name,
        "rules": rules_name, "win_rate": result.win_rate,
        "avg_placement": result.avg_placement, "avg_score": result.avg_score,
        "survival_rate": result.survival_rate, "ms_per_move": result.ms_per_move,
        "games": result.games, "crashes": result.crashes,
        "timeouts": result.timeouts, "ci": result.win_rate_ci(),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["baseline", "rules", "weights"])
    ap.add_argument("--games", type=int, default=30)
    ap.add_argument("--weights", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    weights_json = ""
    if args.weights and os.path.exists(args.weights):
        with open(args.weights) as fh:
            weights_json = json.dumps(json.load(fh)["vector"])

    jobs: List = []
    if args.mode == "baseline":
        for subject in ("superpac", "greedy", "cluster", "defensive", "greedy_escape"):
            for pop in ("train", "validation", "holdout"):
                jobs.append(("baseline", subject,
                             weights_json if subject == "superpac" else "",
                             pop, args.games, 0, "default"))
    elif args.mode == "rules":
        for rules_name in RULE_VARIANTS:
            for subject in ("superpac", "greedy", "defensive"):
                jobs.append(("rules", subject,
                             weights_json if subject == "superpac" else "",
                             "validation", args.games, 0, rules_name))
    else:
        for pop in ("train", "validation", "holdout"):
            jobs.append(("weights", "superpac", weights_json, pop, args.games, 0, "default"))

    start = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(_one, jobs))
    elapsed = time.perf_counter() - start

    out_path = args.out or f"results/{args.mode}.json"
    with open(out_path, "w") as fh:
        json.dump({"elapsed": elapsed, "rows": rows}, fh, indent=2)

    print(f"{args.mode}: {len(jobs)} runs in {elapsed:.0f}s -> {out_path}\n")
    header = f"{'subject':<14s} {'pop/rules':<14s} {'win':>7s} {'+-':>6s} {'place':>6s} {'score':>7s} {'surv':>7s} {'ms/mv':>6s}"
    print(header); print("-" * len(header))
    for row in rows:
        tag = row["rules"] if args.mode == "rules" else row["population"]
        print(f"{row['subject']:<14s} {tag:<14s} {row['win_rate']:>6.1%} "
              f"{row['ci']:>5.1%} {row['avg_placement']:>6.3f} {row['avg_score']:>7.2f} "
              f"{row['survival_rate']:>6.1%} {row['ms_per_move']:>6.2f}"
              + ("  CRASH" if row["crashes"] else "")
              + ("  TIMEOUT" if row["timeouts"] else ""))


if __name__ == "__main__":
    main()
