#!/usr/bin/env python3
"""Final scoreboard: ThoresT against every opponent mix, on the real engine."""
from __future__ import annotations

import json
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SCENARIOS = [
    ("5x Zufallsbot (Lehrer)", ("random",) * 5),
    ("5x harvester", ("harvester",) * 5),
    ("5x sweeper", ("sweeper",) * 5),
    ("gemischt", ("harvester", "harvester", "hunter", "cautious", "sweeper")),
    ("5x hunter", ("hunter",) * 5),
]
PLAYERS = ("ThoresT", "harvester", "sweeper", "Stub")


def _job(args):
    scenario, player, games, seed = args
    import Pacman
    from superpac.pacman.agent import Weights
    from superpac.pacman.arena import evaluate
    from superpac.pacman.opponents import build_opponents
    from superpac.pacman.thorest import build_thorest
    from superpac.pacman.tuning import build_mix

    catalogue = dict(build_opponents(Pacman.Pacman))
    if player == "ThoresT":
        with open(os.path.join(ROOT, "results/thorest_weights.json")) as fh:
            weights = Weights.from_vector(json.load(fh)["vector"])
        subject = build_thorest(Pacman.Pacman, weights=weights)
    elif player == "Stub":
        class Stub(Pacman.Pacman):
            def TurnOrMoveOrStill(self):
                return
        subject = Stub
    else:
        subject = catalogue[player]

    mix = build_mix(SCENARIOS[scenario][1])
    report = evaluate(subject, games=games, fillers=mix, base_seed=seed,
                      label=player)
    return {
        "scenario": scenario, "player": player, "win": report.win_rate,
        "games": report.games, "strength": report.mean_strength,
        "rival": report.mean_best_rival, "rank": report.mean_rank,
        "survival": report.survival_rate,
        "ms": report.ms_sum / max(1, report.games), "faults": report.faults,
    }


def main() -> None:
    games = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    jobs = [(i, player, games, 31000)
            for i in range(len(SCENARIOS)) for player in PLAYERS]
    with ProcessPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(_job, jobs))

    print("ENDSTAND - ThoresT auf der echten Engine des Lehrers")
    print(f"({games} Spiele je Zeile, 15x15, 100 Zuege;")
    print(" bei sechs gleich starken Spielern waeren 16.7% fair)\n")
    header = (f"{'Gegner':<24s} {'Spieler':<11s} {'Sieg':>7s} {'+-':>6s} "
              f"{'Staerke':>8s} {'bester Geg':>11s} {'Rang':>6s} {'lebt':>6s} {'ms':>6s}")
    print(header)
    print("-" * len(header))
    for i, (name, _) in enumerate(SCENARIOS):
        for row in [r for r in rows if r["scenario"] == i]:
            p = row["win"]
            ci = 1.96 * math.sqrt(max(1e-9, p * (1 - p)) / max(1, row["games"]))
            label = name if row["player"] == "ThoresT" else ""
            print(f"{label:<24s} {row['player']:<11s} {p:>6.1%} {ci:>5.1%} "
                  f"{row['strength']:>8.1f} {row['rival']:>11.1f} "
                  f"{row['rank']:>6.2f} {row['survival']:>5.0%} {row['ms']:>6.2f}"
                  + ("  FEHLER" if row["faults"] else ""))
        print()

    with open(os.path.join(ROOT, "results/thorest_final.json"), "w") as fh:
        json.dump(rows, fh, indent=2)


if __name__ == "__main__":
    main()
