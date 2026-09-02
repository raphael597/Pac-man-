#!/usr/bin/env python3
"""Tuned-vs-previous on the mixes the champion was NOT selected on."""
from __future__ import annotations

import json, math, os, sys, time
from concurrent.futures import ProcessPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from superpac.pacman.agent import Weights
from superpac.pacman.tuning import HOLDOUT_MIX, TRAIN_MIX, VALIDATION_MIX, score

MIXES = {"train": TRAIN_MIX, "validation": VALIDATION_MIX, "holdout": HOLDOUT_MIX}


def _job(args):
    label, vector, mix, games, seed = args
    row = score(Weights.from_vector(vector), MIXES[mix], games=games,
                base_seed=seed, max_turns=400)
    row["label"], row["mix"] = label, mix
    return row


def main() -> None:
    games = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    chunks = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    entrants = {}
    for name, path in (("v1_alt", "results/thorest_weights_v1_alt.json"),
                       ("v2_neu", "results/thorest_weights_v2.json")):
        with open(os.path.join(ROOT, path)) as fh:
            entrants[name] = json.load(fh)["vector"]

    jobs = [(name, vec, mix, games, 88000 + c * 977)
            for c in range(chunks) for name, vec in entrants.items()
            for mix in MIXES]
    start = time.perf_counter()
    with ProcessPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(_job, jobs))

    tot = {}
    for r in rows:
        acc = tot.setdefault((r["label"], r["mix"]),
                             {k: 0.0 for k in ("allein", "staerkster", "n",
                                               "rank", "str", "riv", "surv")})
        acc["allein"] += r["win_rate"] * games
        acc["staerkster"] += r["strongest"] * games
        acc["n"] += games
        acc["rank"] += r["rank"] * games
        acc["str"] += r["strength"] * games
        acc["riv"] += r["best_rival"] * games
        acc["surv"] += r["survival"] * games

    print(f"{int(sum(a['n'] for a in tot.values()))} Partien in "
          f"{time.perf_counter()-start:.0f}s\n")
    h = (f"{'Gewichte':<9s} {'Gegner':<11s} {'allein':>8s} {'95% KI':>15s} "
         f"{'staerkster':>11s} {'rang':>6s} {'staerke':>8s} {'bester':>7s} {'lebt':>6s}")
    print(h); print("-" * len(h))
    summary = {}
    for (label, mix), a in sorted(tot.items()):
        n, p = a["n"], a["allein"] / a["n"]
        ci = 1.96 * math.sqrt(max(1e-9, p * (1 - p)) / n)
        summary[(label, mix)] = (p, a["staerkster"] / n, n)
        print(f"{label:<9s} {mix:<11s} {p:>7.1%} [{p-ci:>5.1%},{p+ci:>5.1%}] "
              f"{a['staerkster']/n:>10.1%} {a['rank']/n:>6.2f} {a['str']/n:>8.1f} "
              f"{a['riv']/n:>7.1f} {a['surv']/n:>5.0%}")

    print("\nz-Test (v2 - v1), 'allein uebrig':")
    for mix in MIXES:
        p1, s1, n1 = summary[("v1_alt", mix)]
        p2, s2, n2 = summary[("v2_neu", mix)]
        pooled = (p1 * n1 + p2 * n2) / (n1 + n2)
        se = math.sqrt(max(1e-12, pooled * (1 - pooled) * (1 / n1 + 1 / n2)))
        z = (p2 - p1) / se if se else 0.0
        call = ("v2 SIGNIFIKANT besser" if z > 1.96 else
                "v2 signifikant schlechter" if z < -1.96 else "kein Unterschied")
        note = "  (Auswahlmenge)" if mix == "validation" else ""
        print(f"  {mix:<11s} {(p2-p1)*100:+6.1f} Pkt  staerkster {(s2-s1)*100:+6.1f} Pkt"
              f"  z={z:+.2f}  -> {call}{note}")

    # Pool the two unbiased mixes - independent samples, so this is legitimate
    # and it is the only read with enough games to resolve a few points.
    for key in ("v1_alt", "v2_neu"):
        w = sum(summary[(key, m)][0] * summary[(key, m)][2] for m in ("train", "holdout"))
        n = sum(summary[(key, m)][2] for m in ("train", "holdout"))
        summary[(key, "pool")] = (w / n, 0, n)
    p1, _, n1 = summary[("v1_alt", "pool")]
    p2, _, n2 = summary[("v2_neu", "pool")]
    pooled = (p1 * n1 + p2 * n2) / (n1 + n2)
    se = math.sqrt(max(1e-12, pooled * (1 - pooled) * (1 / n1 + 1 / n2)))
    z = (p2 - p1) / se if se else 0.0
    print(f"\n  gepoolt (train+holdout, je {int(n1)} Partien): "
          f"{p1:.1%} -> {p2:.1%}  ({(p2-p1)*100:+.1f} Pkt)  z={z:+.2f}"
          + ("  -> SIGNIFIKANT" if abs(z) > 1.96 else "  -> nicht signifikant"))

    with open(os.path.join(ROOT, "results/thorest_holdout_v2.json"), "w") as fh:
        json.dump({f"{k[0]}/{k[1]}": v for k, v in summary.items()}, fh, indent=2)


if __name__ == "__main__":
    main()
