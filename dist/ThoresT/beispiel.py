"""Minimalbeispiel: eine Partie mit ThoresT."""

import random

import Pacman
import thorest          # registriert ThoresT automatisch


def eine_partie(seed=1, groesse=15, zuege=100, zeige_brett=False):
    random.seed(seed)
    feld = Pacman.Field(groesse)
    ich = feld.pacmans[-1]

    for zug in range(zuege):
        for spieler in feld.pacmans:
            if spieler.alive:
                spieler.TurnOrMoveOrStill()
        if zeige_brett:
            print(feld)

    print(f"--- Partie {seed} ---")
    for spieler in sorted(feld.pacmans, key=lambda p: -p.strength):
        markierung = "   <-- wir" if spieler is ich else ""
        tot = "  (tot)" if not spieler.alive else ""
        print(f"  {spieler.name:<10s} {spieler.strength:6.0f}{tot}{markierung}")

    gegner = [p.strength for p in feld.pacmans if p is not ich]
    gewonnen = ich.strength > max(gegner)
    print(f"  -> {'SIEG' if gewonnen else 'verloren'}"
          f"  ({ich.strength:.0f} gegen {max(gegner):.0f})")
    return gewonnen


if __name__ == "__main__":
    siege = sum(eine_partie(seed) for seed in range(1, 11))
    print()
    print(f"{siege} von 10 Partien gewonnen")
    print("(bei sechs gleich starken Spielern waeren ~1.7 von 10 fair)")
