#!/usr/bin/env python3
"""Build ``thorest.py``: the ThoresT class as one standalone file.

Unlike ``build_pacman.py``, which merges our player *into* the engine file,
this produces a module that sits **next to** the teacher's unmodified
``Pacman.py`` and imports from it.  That is what lets the class be handed in
on its own.

The one wrinkle worth knowing about: ``Field.__init__`` builds its last player
by looking up the name ``ThoresT`` in *Pacman.py's* module globals.  A class
defined in another file is therefore invisible to it, and ``Field(15)`` would
quietly go on using the empty stub.  The generated module registers itself on
import to close that gap.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

RUNTIME = [
    "superpac/pacman/rules.py",
    "superpac/pacman/perception.py",
    "superpac/pacman/model.py",
    "superpac/pacman/agent.py",
]


def strip_module(path: str):
    """Drop package-internal imports; keep and hoist the stdlib ones.

    ``from Pacman import ...`` is dropped here too - the standalone file
    imports those names once at the top instead of repeatedly inside
    functions, which is both clearer and marginally faster.
    """
    with open(os.path.join(ROOT, path)) as fh:
        source = fh.read()
    lines = source.splitlines()
    tree = ast.parse(source)

    drop, imports = set(), []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        module = getattr(node, "module", None) or ""
        level = getattr(node, "level", 0)
        internal = (level > 0 or module.startswith("superpac")
                    or module == "Pacman" or module == "__future__")
        if internal:
            for lineno in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                drop.add(lineno)
            continue
        if node.col_offset != 0:
            continue
        for lineno in range(node.lineno, (node.end_lineno or node.lineno) + 1):
            drop.add(lineno)
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(f"import {alias.name}"
                               + (f" as {alias.asname}" if alias.asname else ""))
        else:
            names = ", ".join(a.name + (f" as {a.asname}" if a.asname else "")
                              for a in node.names)
            imports.append(f"from {module} import {names}")

    for node in tree.body:
        if isinstance(node, ast.Assign):
            if [t.id for t in node.targets if isinstance(t, ast.Name)] == ["__all__"]:
                for lineno in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                    drop.add(lineno)

    body = "\n".join(l for i, l in enumerate(lines, 1) if i not in drop)
    return body.strip("\n"), imports


HEADER = '''"""ThoresT - ein Pacman-Bot.

Diese Datei enthaelt die Klasse ``ThoresT`` und alles, was sie zum Spielen
braucht. Sie liegt neben der unveraenderten ``Pacman.py`` und wird genauso
benutzt wie ``TRex.py``.

Benutzung
---------

    from Pacman import Direction, Field, Pacman
    from TRex import TRex
    from ThoresT import ThoresT

    pacmans = [[Pacman, "Pacman1"], [Pacman, "Pacman2"],
               [TRex, "Trex1"], [ThoresT, "ThoresT"]]
    walls = [[[5, 3], Direction.east, 8], [[5, 4], Direction.south, 3]]
    field = Field(15, pacmans, walls)

Fuer ``PacmanGame.py`` genuegt es, ``ThoresT`` zu importieren und in die
``pacmans``-Liste einzutragen.

Wie er spielt
-------------
Das Brett ist ein Torus, es startet voller Kohl, und es gibt Waende. Ein Zug
ist *entweder* drehen *oder* gehen *oder* stehen - nie beides. Eine lange
gerade Bahn durch Kohl ist deshalb die billigste Staerke auf dem Brett, und
der Bot plant in Bahnen statt in Wegen.

Irgendwann ist der Kohl weg. Danach gibt es Staerke nur noch von anderen
Spielern, also stellt er auf Jagen um. Wann genau, entscheidet ein einziger
Ausdruck: ``F``, die erwartete Resternte.

Kaempfe entscheidet der Winkel: wer in dieselbe Richtung laeuft wie ich,
verteidigt mit einem Zehntel seiner Staerke (90.9% statt 50% bei gleicher
Staerke). Also von hinten angreifen - und wenn man selbst angegriffen wird,
dem Angreifer entgegenschauen, das drueckt seine Chance von 91% auf 50%.

Von jedem Gegner fuehrt er ein eigenes Verhaltensmodell. Deren Aktion laesst
sich aus dem Brett exakt zurueckrechnen: Position geaendert -> gegangen,
Blickrichtung geaendert -> gedreht, nichts -> gestanden.

Erzeugt von scripts/build_standalone.py. Nur Standardbibliothek.
Gebaut: {built}
Gewichte: {weights_source}
"""

{imports}

from Pacman import Cabbage, Direction, Empty, Pacman, Position, Wall

'''

FOOTER = '''

# ==========================================================================
# Die Klasse
# ==========================================================================

#: Vom Optimierer gefunden (scripts/tune_thorest.py): evolutionaere Suche auf
#: der echten Engine gegen starke Gegner, Champion auf einer getrennten
#: Gegnermischung ausgewaehlt.
TUNED_WEIGHTS = {weights_dict}

THORES_WEIGHTS = Weights(**TUNED_WEIGHTS)

_DIRECTION_OBJECTS = (Direction.north, Direction.south,
                      Direction.west, Direction.east)


class ThoresT(Pacman):
    """Unser Spieler. Wird wie TRex in die pacmans-Liste eingetragen."""

    def __init__(self, p, name, field):
        super().__init__(p, name, field)
        self.logo = "T"
        self.icon = "icons/TRex.png"   # fuer PacmanRenderer
        self.direction = Direction.west
        # total_turns=None: die Engine hat kein Zuglimit, PacmanGame laeuft
        # bis nur noch einer lebt. Der Kohl auf dem Brett ist dann die
        # einzige ehrliche Uhr.
        self.brain = Brain(weights=THORES_WEIGHTS, total_turns=None)

    def TurnOrMoveOrStill(self):
        # Die Engine ignoriert den Rueckgabewert, also wuerde jede Exception,
        # die hier herauskommt, den Zug kosten - im Turnier die Partie.
        try:
            action = self.brain.decide(self)
        except Exception:
            self.brain.faults += 1
            action = MOVE
        try:
            if action < 4:
                self.direction = _DIRECTION_OBJECTS[action]
            elif action == MOVE:
                self._Move()
            # STILL: absichtlich nichts
        except Exception:
            self.brain.faults += 1


if __name__ == "__main__":
    import random as _random
    import time as _time

    from Pacman import Field as _Field

    try:
        from TRex import TRex as _TRex
    except Exception:
        _TRex = Pacman

    _walls = [[[5, 3], Direction.east, 8], [[5, 4], Direction.south, 3],
              [[12, 4], Direction.south, 3], [[2, 12], Direction.east, 8],
              [[2, 11], Direction.north, 3], [[9, 11], Direction.north, 3]]

    def _partie(seed):
        """Eine Partie wie in PacmanGame: Reihenfolge jede Runde neu
        gewuerfelt, laeuft bis nur noch einer lebt."""
        _random.seed(seed)
        pacmans = [[Pacman, "Pacman1"], [Pacman, "Pacman2"], [Pacman, "Pacman3"],
                   [_TRex, "Trex1"], [_TRex, "Trex2"], [ThoresT, "ThoresT"]]
        feld = _Field(15, pacmans, _walls)
        ich = next(p for p in feld.pacmans if p.name == "ThoresT")
        worst = 0.0
        zug = 0
        while sum(1 for p in feld.pacmans if p.alive) > 1 and zug < 600:
            for p in _random.sample(feld.pacmans, len(feld.pacmans)):
                if not p.alive:
                    continue
                if p is ich:
                    t0 = _time.perf_counter()
                    p.TurnOrMoveOrStill()
                    worst = max(worst, (_time.perf_counter() - t0) * 1000.0)
                else:
                    p.TurnOrMoveOrStill()
            zug += 1
        lebende = [p for p in feld.pacmans if p.alive]
        gegner = max(p.strength for p in feld.pacmans if p is not ich)
        return {"zug": zug, "staerke": ich.strength, "gegner": gegner,
                "allein": ich.alive and len(lebende) == 1,
                "staerkster": ich.strength > gegner, "lebt": ich.alive,
                "ms": ich.brain.total_ms / max(1, ich.brain.turn),
                "worst": worst, "faults": ich.brain.faults}

    print("ThoresT Selbsttest - laeuft die Datei sauber durch?")
    print("(15x15 mit Waenden, bis nur noch einer lebt)")
    print()
    print(f"  {'seed':>4s} {'Zuege':>6s} {'Staerke':>8s} {'bester Gegner':>14s}"
          f" {'Ergebnis':>16s}")
    print("  " + "-" * 54)
    # Eine einzelne Partie sagt hier fast nichts - die Kaempfe sind
    # Wuerfelwuerfe, und ein Selbsttest, der genau einen Seed zeigt, sagt
    # mehr ueber den Seed als ueber den Bot.
    _ergebnisse = [_partie(s) for s in range(1, 6)]
    for _seed, _r in enumerate(_ergebnisse, start=1):
        # Zwei Arten zu gewinnen, seit das Spiel laeuft bis einer uebrig ist.
        # Nur Staerken zu vergleichen wuerde einen Alleinueberlebenden als
        # Niederlage melden, blos weil ein toter Gegner mehr angesammelt hat.
        if _r["allein"]:
            _urteil = "ALLEIN UEBRIG"
        elif _r["staerkster"]:
            _urteil = "staerkster"
        elif _r["lebt"]:
            _urteil = "lebt noch"
        else:
            _urteil = "gestorben"
        print(f"  {_seed:>4d} {_r['zug']:>6d} {_r['staerke']:>8.0f}"
              f" {_r['gegner']:>14.0f} {_urteil:>16s}")

    _allein = sum(r["allein"] for r in _ergebnisse)
    _stark = sum(r["staerkster"] for r in _ergebnisse)
    _faults = sum(r["faults"] for r in _ergebnisse)
    print()
    print(f"  allein uebrig: {_allein}/5   staerkster: {_stark}/5")
    print("  Achtung: 5 Partien sagen ueber die Spielstaerke nichts - das")
    print("  Konfidenzintervall ist hier rund +-40 Punkte, und dieselbe")
    print("  Datei liefert je nach Seed 2/5 oder 4/5. Geprueft wird hier,")
    print("  ob die Datei laeuft und ohne Fehler entscheidet. Die belast-")
    print("  baren Zahlen stehen in docs/ERGEBNISSE.md (12.000 Partien).")
    print(f"  {sum(r['ms'] for r in _ergebnisse) / 5:.2f} ms/Zug im Schnitt,"
          f" maximal {max(r['worst'] for r in _ergebnisse):.2f} ms,"
          f" Fehler: {_faults}")
    assert _faults == 0, "die Notfall-Route wurde benutzt"
'''


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default="results/thorest_weights.json")
    ap.add_argument("--out", default="dist/ThoresT/ThoresT.py")
    ap.add_argument("--name", default="ThoresT",
                    help="wie die Klasse und der Spieler heissen sollen")
    args = ap.parse_args()
    if not args.name.isidentifier():
        ap.error(f"{args.name!r} ist kein gueltiger Klassenname")

    weights_path = os.path.join(ROOT, args.weights)
    if os.path.exists(weights_path):
        with open(weights_path) as fh:
            weights_dict = json.load(fh)["weights"]
        source = f"getunt ({args.weights})"
    else:
        from superpac.pacman.agent import Weights
        weights_dict = {n: getattr(Weights(), n) for n in Weights.names()}
        source = "Handwerte"

    bodies, all_imports = [], []
    for path in RUNTIME:
        body, imports = strip_module(path)
        all_imports.extend(imports)
        bodies.append(f"# {'-' * 70}\n# {path}\n# {'-' * 70}\n\n{body}")

    seen, ordered = set(), []
    for line in all_imports:
        if line not in seen:
            seen.add(line)
            ordered.append(line)
    ordered.sort(key=lambda l: (not l.startswith("import "), l))

    header = (HEADER.replace("{built}", time.strftime("%Y-%m-%d"))
                    .replace("{weights_source}", source)
                    .replace("{imports}", "\n".join(ordered)))
    footer = FOOTER.replace("{weights_dict}", json.dumps(weights_dict, indent=4))
    text = header + "\n\n".join(bodies) + footer

    # Umbenennen erst hier, auf dem fertigen Text: der Name kommt in der
    # Klassendefinition, im Kopfkommentar, im Selbsttest und in den
    # Beispielen vor, und alle sollen zusammenpassen. "ThoresT" ist im
    # uebrigen Quelltext kein Bezeichner, deshalb ist die Ersetzung
    # eindeutig - was der ast.parse darunter auch belegt.
    if args.name != "ThoresT":
        text = text.replace("ThoresT", args.name)

    ast.parse(text)

    # The header's import list is hand-written, so a new engine class used
    # deeper in the package would only surface as a NameError at play time -
    # every turn falling through to the fallback while the file still imports
    # cleanly. Check the names actually referenced instead of trusting it.
    engine_names = {"Cabbage", "Direction", "Empty", "Pacman", "Position", "Wall"}
    tree = ast.parse(text)
    # Read the *real* top-level import, not the example inside the docstring -
    # a textual search finds the docstring first and reports every class as
    # missing.
    imported = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "Pacman":
            imported.update(a.name for a in node.names)
    referenced = {node.id for node in ast.walk(tree)
                  if isinstance(node, ast.Name)} | {
                  node.attr for node in ast.walk(tree)
                  if isinstance(node, ast.Attribute)}
    missing = sorted((engine_names & referenced) - imported)
    if missing:
        raise SystemExit(
            f"engine classes used but not imported in the header: {missing}")

    out_path = os.path.join(ROOT, args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as fh:
        fh.write(text)
    print(f"wrote {args.out}: {text.count(chr(10)) + 1} Zeilen, {len(text) / 1024:.0f} KB")
    print(f"Gewichte: {source}")


if __name__ == "__main__":
    main()
