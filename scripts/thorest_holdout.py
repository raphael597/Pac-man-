#!/usr/bin/env python3
"""Settle tuned-vs-default on the sets the champion was NOT selected on.

Validation is where the champion was picked, so validation improving proves
very little. Train and holdout are the unbiased reads, and at 30 games their
confidence intervals were 17 points wide - far too loose to decide anything.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from superpac.pacman.agent import Weights
from superpac.pacman.tuning import (HOLDOUT_MIX, TRAIN_MIX, VALIDATION_MIX,
                                    score)

MIXES = {"train": TRAIN_MIX, "validation": VALIDATION_MIX, "holdout": HOLDOUT_MIX}


def _job(args):
    vector, mix_name, games, seed = args
    result = score(Weights.from_vector(vector), MIXES[mix_name],
                   games=games, base_seed=seed)
    result["mix"] = mix_name
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=30, help="games per chunk")
    ap.add_argument("--chunks", type=int, default=4)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--weights", default="results/thorest_weights.json")
    args = ap.parse_args()

    with open(os.path.join(ROOT, args.weights)) as fh:
        tuned = Weights.from_vector(json.load(fh)["vector"])
    entrants = {"defaults": Weights().as_vector(), "tuned": tuned.as_vector()}

    jobs, labels = [], []
    for chunk in range(args.chunks):
        for name, vector in entrants.items():
            for mix in MIXES:
                jobs.append((vector, mix, args.games, 77000 + chunk * 1013))
                labels.append((name, mix))

    start = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(_job, jobs))
    elapsed = time.perf_counter() - start

    totals = {}
    for (name, mix), row in zip(labels, rows):
        acc = totals.setdefault((name, mix), {"wins": 0.0, "n": 0.0, "rank": 0.0,
                                              "strength": 0.0, "rival": 0.0,
                                              "surv": 0.0})
        acc["wins"] += row["win_rate"] * args.games
        acc["n"] += args.games
        acc["rank"] += row["rank"] * args.games
        acc["strength"] += row["strength"] * args.games
        acc["rival"] += row["best_rival"] * args.games
        acc["surv"] += row["survival"] * args.games

    total_games = sum(a["n"] for a in totals.values())
    print(f"{int(total_games)} Spiele in {elapsed:.0f}s\n")
    header = (f"{'weights':<10s} {'gegner':<12s} {'sieg':>7s} {'95% KI':>16s} "
              f"{'rang':>6s} {'staerke':>8s} {'bester geg':>11s} {'lebt':>6s} {'n':>5s}")
    print(header)
    print("-" * len(header))
    summary = {}
    for (name, mix), acc in sorted(totals.items()):
        n = acc["n"]
        p = acc["wins"] / n
        ci = 1.96 * math.sqrt(max(1e-9, p * (1 - p)) / n)
        summary[(name, mix)] = (p, n, acc["strength"] / n)
        print(f"{name:<10s} {mix:<12s} {p:>6.1%} [{p-ci:>5.1%},{p+ci:>5.1%}] "
              f"{acc['rank']/n:>6.2f} {acc['strength']/n:>8.1f} "
              f"{acc['rival']/n:>11.1f} {acc['surv']/n:>5.0%} {int(n):>5d}")

    print("\nZwei-Stichproben-z-Test (tuned - defaults):")
    for mix in MIXES:
        p1, n1, s1 = summary[("defaults", mix)]
        p2, n2, s2 = summary[("tuned", mix)]
        pooled = (p1 * n1 + p2 * n2) / (n1 + n2)
        se = math.sqrt(max(1e-12, pooled * (1 - pooled) * (1 / n1 + 1 / n2)))
        z = (p2 - p1) / se if se > 0 else 0.0
        if abs(z) < 1.96:
            call = "kein signifikanter Unterschied"
        elif z > 0:
            call = "TUNED signifikant besser"
        else:
            call = "TUNED signifikant SCHLECHTER"
        note = "  (Auswahlmenge - nicht unabhaengig)" if mix == "validation" else ""
        print(f"  {mix:<12s} {(p2-p1)*100:+5.1f} Punkte  Staerke {s2-s1:+6.1f}  "
              f"z={z:+.2f}  -> {call}{note}")

    with open(os.path.join(ROOT, "results/thorest_holdout.json"), "w") as fh:
        json.dump({f"{k[0]}/{k[1]}": {"win_rate": v[0], "games": v[1],
                                      "strength": v[2]}
                   for k, v in summary.items()}, fh, indent=2)


if __name__ == "__main__":
    main()
