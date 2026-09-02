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
braucht. Sie liegt **neben** der unveraenderten ``Pacman.py`` des Lehrers und
benutzt deren Klassen.

Benutzung
---------

    import Pacman
    import thorest          # <- registriert ThoresT automatisch

    feld = Pacman.Field(15)
    for zug in range(100):
        for spieler in feld.pacmans:
            if spieler.alive:
                spieler.TurnOrMoveOrStill()
    print(feld)

Warum der Import genuegt: ``Field.__init__`` sucht den Namen ``ThoresT`` in
den Modul-Globalen von *Pacman.py*. Eine Klasse aus einer anderen Datei sieht
sie dort nicht - ``Field(15)`` wuerde stillschweigend weiter den leeren Stub
benutzen. Der Import unten traegt die Klasse deshalb selbst ein. Wer das
lieber ausdruecklich macht, ruft ``thorest.install()`` auf; wer den Stub
zurueck will, ``thorest.uninstall()``.

Wie er spielt
-------------
Das Brett ist ein Torus ohne Waende und startet voller Kohl. Ein Zug ist
*entweder* drehen *oder* gehen *oder* stehen - nie beides. Eine lange gerade
Bahn durch Kohl ist deshalb die billigste Staerke auf dem Brett, und der Bot
plant in Bahnen statt in Wegen.

Sechs Spieler raeumen ein 15x15-Brett bis etwa Zug 55 leer. Danach gibt es
Staerke nur noch von anderen Spielern, also stellt er auf Jagen um.

Kaempfe entscheidet der Winkel: wer in dieselbe Richtung laeuft wie ich,
verteidigt mit einem Zehntel seiner Staerke (90.9% statt 50% bei gleicher
Staerke). Also von hinten angreifen - und wenn man selbst angegriffen wird,
dem Angreifer entgegenschauen, das drueckt seine Chance von 91% auf 50%.

Erzeugt von scripts/build_standalone.py. Nur Standardbibliothek.
Gebaut: {built}
Gewichte: {weights_source}
"""

{imports}

from Pacman import Cabbage, Direction, Empty, Pacman, Position

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

#: Spiellaenge aus dem Test-Notebook des Lehrers. Fliesst nur in die
#: Schaetzung "wieviel Ernte liegt noch vor mir" ein, die entscheidet, ab wann
#: Jagen mehr wert ist als Ernten. Ein falscher Wert kostet Schaerfe, nicht
#: Korrektheit.
TOTAL_TURNS = 100

_DIRECTION_OBJECTS = (Direction.north, Direction.south,
                      Direction.west, Direction.east)


class ThoresT(Pacman):
    """Unser Spieler."""

    def __init__(self, p, name, field):
        super().__init__(p, name, field)
        self.logo = "T"
        self.direction = Direction.west
        self.brain = Brain(weights=THORES_WEIGHTS, total_turns=TOTAL_TURNS)

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


# --------------------------------------------------------------------------
# Registrierung
# --------------------------------------------------------------------------
def install():
    """Traegt ThoresT in Pacman.py ein, damit ``Field()`` ihn benutzt."""
    import Pacman as _engine
    _engine.ThoresT = ThoresT
    return ThoresT


def uninstall():
    """Stellt den urspruenglichen ThoresT des Lehrers wieder her."""
    import Pacman as _engine
    if _ORIGINAL_THOREST is not None:
        _engine.ThoresT = _ORIGINAL_THOREST


def _remember_original():
    import Pacman as _engine
    return getattr(_engine, "ThoresT", None)


_ORIGINAL_THOREST = _remember_original()
install()


if __name__ == "__main__":
    import random as _random
    import time as _time

    _random.seed(1)
    from Pacman import Field as _Field

    _feld = _Field(15)
    _ich = _feld.pacmans[-1]
    assert isinstance(_ich, ThoresT), (
        "Field() hat nicht unsere Klasse benutzt - liegt Pacman.py daneben?")
    _worst = 0.0
    for _zug in range(TOTAL_TURNS):
        for _p in _feld.pacmans:
            if not _p.alive:
                continue
            if _p is _ich:
                _t0 = _time.perf_counter()
                _p.TurnOrMoveOrStill()
                _worst = max(_worst, (_time.perf_counter() - _t0) * 1000.0)
            else:
                _p.TurnOrMoveOrStill()

    print("ThoresT Selbsttest (15x15, 100 Zuege)")
    print()
    for _p in sorted(_feld.pacmans, key=lambda q: -q.strength):
        _mark = "   <-- wir" if _p is _ich else ""
        _tot = "  (tot)" if not _p.alive else ""
        print(f"  {_p.name:<10s} {_p.strength:6.0f}{_tot}{_mark}")
    _rivals = [_p.strength for _p in _feld.pacmans if _p is not _ich]
    print()
    print(f"  ThoresT {_ich.strength:.0f} gegen besten Gegner {max(_rivals):.0f}"
          f"  ->  {'SIEG' if _ich.strength > max(_rivals) else 'verloren'}")
    print(f"  {_ich.brain.total_ms / max(1, _ich.brain.turn):.2f} ms/Zug, "
          f"maximal {_worst:.2f} ms, Fehler: {_ich.brain.faults}")
    assert _ich.brain.faults == 0, "die Notfall-Route wurde benutzt"
'''


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default="results/thorest_weights.json")
    ap.add_argument("--out", default="dist/ThoresT/thorest.py")
    args = ap.parse_args()

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

    ast.parse(text)
    out_path = os.path.join(ROOT, args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as fh:
        fh.write(text)
    print(f"wrote {args.out}: {text.count(chr(10)) + 1} Zeilen, {len(text) / 1024:.0f} KB")
    print(f"Gewichte: {source}")


if __name__ == "__main__":
    main()
