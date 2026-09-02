#!/usr/bin/env python3
"""Final scoreboard on the teacher's engine, version 2."""
from __future__ import annotations

import json
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SCENARIOS = [
    ("Aufstellung des Lehrers", ("random", "random", "random", "trex", "trex")),
    ("5x Zufallsbot", ("random",) * 5),
    ("5x TRex", ("trex",) * 5),
    ("5x Ernte-Bot", ("harvester",) * 5),
    ("gemischt stark", ("harvester", "trex", "hunter", "cautious", "sweeper")),
]
PLAYERS = ("ThoresT", "harvester", "sweeper", "Stub")


def _job(args):
    scenario, player, games, seed, max_turns = args
    import Pacman
    from superpac.pacman.agent import Weights
    from superpac.pacman.arena import default_walls, evaluate
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

    report = evaluate(subject, games=games, fillers=build_mix(SCENARIOS[scenario][1]),
                      base_seed=seed, label=player, walls=default_walls(),
                      max_turns=max_turns)
    return {"scenario": scenario, "player": player, "allein": report.win_rate,
            "staerkster": report.strongest_rate, "games": report.games,
            "strength": report.mean_strength, "rival": report.mean_best_rival,
            "rank": report.mean_rank, "surv": report.survival_rate,
            "turns": report.turn_sum / max(1, report.games),
            "ms": report.ms_sum / max(1, report.games), "faults": report.faults}


def main() -> None:
    games = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    jobs = [(i, p, games, 31000, 400)
            for i in range(len(SCENARIOS)) for p in PLAYERS]
    with ProcessPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(_job, jobs))

    print("ENDSTAND - ThoresT auf der Engine des Lehrers (Version 2)")
    print(f"({games} Partien je Zeile, 15x15 mit Waenden, bis nur noch einer lebt")
    print(" oder 400 Zuege erreicht sind; bei sechs gleich starken Spielern")
    print(" waeren 16.7% fair)\n")
    header = (f"{'Gegner':<24s} {'Spieler':<11s} {'allein':>7s} {'staerkster':>11s} "
              f"{'+-':>6s} {'staerke':>8s} {'bester':>8s} {'rang':>6s} {'lebt':>6s} {'ms':>6s}")
    print(header)
    print("-" * len(header))
    for i, (name, _) in enumerate(SCENARIOS):
        for row in [r for r in rows if r["scenario"] == i]:
            p = row["staerkster"]
            ci = 1.96 * math.sqrt(max(1e-9, p * (1 - p)) / max(1, row["games"]))
            label = name if row["player"] == "ThoresT" else ""
            print(f"{label:<24s} {row['player']:<11s} {row['allein']:>6.1%} "
                  f"{p:>10.1%} {ci:>5.1%} {row['strength']:>8.1f} "
                  f"{row['rival']:>8.1f} {row['rank']:>6.2f} {row['surv']:>5.0%} "
                  f"{row['ms']:>6.2f}" + ("  FEHLER" if row["faults"] else ""))
        print()

    with open(os.path.join(ROOT, "results/thorest_final.json"), "w") as fh:
        json.dump(rows, fh, indent=2)


if __name__ == "__main__":
    main()
