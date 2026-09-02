#!/usr/bin/env python3
"""Compare two weight sets across all three opponent mixes.

Validation is where a champion gets *selected*, so validation improving is
not evidence. Train and holdout are the unbiased reads; they are independent
samples and pool legitimately, which is usually the only way to get a sample
large enough to resolve a few points in this game.
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
    label, vector, mix, games, seed, max_turns = args
    result = score(Weights.from_vector(vector), MIXES[mix], games=games,
                   base_seed=seed, max_turns=max_turns)
    result["label"] = label
    result["mix"] = mix
    return result


def _load(path: str) -> Weights:
    with open(os.path.join(ROOT, path)) as fh:
        return Weights.from_vector(json.load(fh)["vector"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="results/thorest_weights_v1_alt.json")
    ap.add_argument("--b", default="results/thorest_weights_v2.json")
    ap.add_argument("--name-a", default="v1 (alte Engine)")
    ap.add_argument("--name-b", default="v2 (neue Engine)")
    ap.add_argument("--games", type=int, default=24)
    ap.add_argument("--chunks", type=int, default=3)
    ap.add_argument("--max-turns", type=int, default=300)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    entrants = {args.name_a: _load(args.a).as_vector(),
                args.name_b: _load(args.b).as_vector()}

    jobs = []
    for chunk in range(args.chunks):
        for label, vector in entrants.items():
            for mix in MIXES:
                jobs.append((label, vector, mix, args.games,
                             77000 + chunk * 1013, args.max_turns))

    start = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(_job, jobs))
    elapsed = time.perf_counter() - start

    totals = {}
    for row in rows:
        acc = totals.setdefault((row["label"], row["mix"]),
                                {k: 0.0 for k in ("allein", "staerkster", "n",
                                                  "rank", "strength", "rival",
                                                  "surv")})
        n = args.games
        acc["n"] += n
        acc["allein"] += row["win_rate"] * n
        acc["staerkster"] += row["strongest"] * n
        acc["rank"] += row["rank"] * n
        acc["strength"] += row["strength"] * n
        acc["rival"] += row["best_rival"] * n
        acc["surv"] += row["survival"] * n

    print(f"{int(sum(a['n'] for a in totals.values()))} Partien in {elapsed:.0f}s\n")
    header = (f"{'Gewichte':<18s} {'Gegner':<12s} {'allein':>7s} {'staerkster':>11s} "
              f"{'95% KI':>15s} {'rang':>6s} {'staerke':>8s} {'bester':>8s} {'lebt':>6s}")
    print(header)
    print("-" * len(header))
    summary = {}
    for (label, mix), acc in sorted(totals.items()):
        n = acc["n"]
        p = acc["staerkster"] / n
        ci = 1.96 * math.sqrt(max(1e-9, p * (1 - p)) / n)
        summary[(label, mix)] = (acc["allein"] / n, p, n)
        print(f"{label:<18s} {mix:<12s} {acc['allein']/n:>6.1%} {p:>10.1%} "
              f"[{p-ci:>5.1%},{p+ci:>5.1%}] {acc['rank']/n:>6.2f} "
              f"{acc['strength']/n:>8.1f} {acc['rival']/n:>8.1f} {acc['surv']/n:>5.0%}")

    labels = list(entrants)
    print("\nZwei-Stichproben-z-Test (b - a), Kriterium 'allein uebrig':")
    for mix in MIXES:
        p1, _, n1 = summary[(labels[0], mix)]
        p2, _, n2 = summary[(labels[1], mix)]
        pooled = (p1 * n1 + p2 * n2) / (n1 + n2)
        se = math.sqrt(max(1e-12, pooled * (1 - pooled) * (1 / n1 + 1 / n2)))
        z = (p2 - p1) / se if se > 0 else 0.0
        call = ("b SIGNIFIKANT besser" if z > 1.96 else
                "b signifikant schlechter" if z < -1.96 else
                "kein signifikanter Unterschied")
        note = "  (Auswahlmenge)" if mix == "validation" else ""
        print(f"  {mix:<12s} {(p2-p1)*100:+5.1f} Punkte  z={z:+.2f}  -> {call}{note}")

    # train + holdout are independent of the selection, so they pool.
    a_wins = sum(summary[(labels[0], m)][0] * summary[(labels[0], m)][2]
                 for m in ("train", "holdout"))
    b_wins = sum(summary[(labels[1], m)][0] * summary[(labels[1], m)][2]
                 for m in ("train", "holdout"))
    n = sum(summary[(labels[0], m)][2] for m in ("train", "holdout"))
    p1, p2 = a_wins / n, b_wins / n
    pooled = (p1 + p2) / 2
    se = math.sqrt(max(1e-12, pooled * (1 - pooled) * 2 / n))
    z = (p2 - p1) / se if se > 0 else 0.0
    print(f"\ngepoolt ueber train + holdout ({int(n)} Partien je Seite):")
    print(f"  {labels[0]:<18s} {p1:6.1%}")
    print(f"  {labels[1]:<18s} {p2:6.1%}")
    print(f"  {(p2-p1)*100:+.1f} Punkte, z={z:+.2f}  -> "
          + ("SIGNIFIKANT" if abs(z) > 1.96 else "nicht signifikant"))

    with open(os.path.join(ROOT, "results/weights_compare.json"), "w") as fh:
        json.dump({f"{k[0]}|{k[1]}": {"allein": v[0], "staerkster": v[1],
                                      "games": v[2]}
                   for k, v in summary.items()}, fh, indent=2)


if __name__ == "__main__":
    main()
