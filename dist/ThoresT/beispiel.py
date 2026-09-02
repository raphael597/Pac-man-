"""Minimalbeispiel: eine Partie mit ThoresT auf der Engine des Lehrers."""

import random

from Pacman import Direction, Field, Pacman
from ThoresT import ThoresT

try:
    from TRex import TRex
except ImportError:
    TRex = Pacman

# Genau die Aufstellung und die Waende aus PacmanGame.py, plus uns.
PACMANS = [[Pacman, "Pacman1"], [Pacman, "Pacman2"], [Pacman, "Pacman3"],
           [TRex, "Trex1"], [TRex, "Trex2"], [ThoresT, "ThoresT"]]
WALLS = [[[5, 3], Direction.east, 8], [[5, 4], Direction.south, 3],
         [[12, 4], Direction.south, 3], [[2, 12], Direction.east, 8],
         [[2, 11], Direction.north, 3], [[9, 11], Direction.north, 3]]


def eine_partie(seed=1, groesse=15, max_zuege=600, zeige_brett=False):
    random.seed(seed)
    feld = Field(groesse, [list(p) for p in PACMANS], WALLS)
    ich = next(p for p in feld.pacmans if p.name == "ThoresT")

    zug = 0
    while sum(1 for p in feld.pacmans if p.alive) > 1 and zug < max_zuege:
        # Wie PacmanGame: die Reihenfolge wird jede Runde neu gewuerfelt.
        for spieler in random.sample(feld.pacmans, len(feld.pacmans)):
            if spieler.alive:
                spieler.TurnOrMoveOrStill()
        zug += 1
        if zeige_brett:
            print(feld)

    lebende = sum(1 for p in feld.pacmans if p.alive)
    print(f"--- Partie {seed}: {zug} Zuege, {lebende} noch am Leben ---")
    for spieler in sorted(feld.pacmans, key=lambda p: -p.strength):
        markierung = "   <-- wir" if spieler is ich else ""
        tot = "  (tot)" if not spieler.alive else ""
        print(f"  {spieler.name:<10s} {spieler.strength:6.0f}{tot}{markierung}")

    gegner = max(p.strength for p in feld.pacmans if p is not ich)
    staerkster = ich.strength > gegner
    allein = ich.alive and lebende == 1
    print(f"  -> {'ALLEIN UEBRIG' if allein else ('staerkster' if staerkster else 'verloren')}")
    return staerkster, allein


if __name__ == "__main__":
    ergebnisse = [eine_partie(seed) for seed in range(1, 11)]
    staerkster = sum(a for a, _ in ergebnisse)
    allein = sum(b for _, b in ergebnisse)
    print()
    print(f"staerkster in {staerkster} von 10 Partien, allein uebrig in {allein}")
    print("(bei sechs gleich starken Spielern waeren ~1.7 von 10 fair)")
