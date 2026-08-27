#!/usr/bin/env python3
"""Search for counter-strategies that beat the current champion."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from superpac.ai.evaluator import Weights
from superpac.training.adversarial import (score_adversary, search_counter_bots,
                                           seed_league)
from superpac.training.optimize_weights import load_weights


def _job(args):
    return score_adversary(args)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=32)
    ap.add_argument("--games", type=int, default=10)
    ap.add_argument("--threshold", type=float, default=0.55)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--weights", default="results/weights_champion.json")
    ap.add_argument("--out", default="results/adversarial.json")
    args = ap.parse_args()

    weights = (load_weights(args.weights)
               if os.path.exists(args.weights) else Weights())
    print(f"searching {args.rounds} adversary configurations "
          f"({args.games} games each, {args.games * 4} matches total)...\n", flush=True)

    start = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        counters = search_counter_bots(
            weights, rounds=args.rounds, games=args.games,
            threshold=args.threshold,
            mapper=lambda jobs: pool.map(_job, jobs),
            log=lambda msg: print(msg, flush=True))

    league = seed_league()
    added = 0
    for member in counters:
        member.added_round = 1
        if league.add(member):
            added += 1

    elapsed = time.perf_counter() - start
    print(f"\nfound {len(counters)} counter-strategies in {elapsed:.0f}s "
          f"({added} new league members)")
    print(league.summary())

    with open(args.out, "w") as fh:
        json.dump({
            "elapsed": elapsed, "threshold": args.threshold,
            "counters": [{"name": m.name, "superpac_win_rate": m.superpac_win_rate}
                         for m in counters],
        }, fh, indent=2)
    print(f"\nwritten to {args.out}")


if __name__ == "__main__":
    main()
