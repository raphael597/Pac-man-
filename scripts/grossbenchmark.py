"""Grossbenchmark - viele Partien gegen viele Aufstellungen.

Warum es das gibt
-----------------
Alle bisherigen Zahlen kamen aus 24 bis 176 Partien.  Das Konfidenz-
intervall einer Quote aus 100 Partien ist rund +-10 Prozentpunkte.  Jede
Verbesserung, die kleiner ist als das, war fuer uns schlicht unsichtbar -
wir haben mehrfach Rauschen fuer Fortschritt gehalten und wieder
zuruecknehmen muessen.  Dieses Skript ist die Antwort darauf.

Warum 400 Zuege reichen
-----------------------
Die Engine kennt kein Zuglimit; ``PacmanGame.py`` laeuft, bis nur noch
einer lebt.  Gegen ausweichende Gegner passiert das nie: in einer Messung
ueber 48 Partien mit Limit 1500 waren nach 1500 Zuegen erst 44 Prozent
entschieden, der Median lag genau auf dem Limit.  Wer am Ende der
*staerkste* ist, stand dagegen schon nach 200 Zuegen fest - in 48 von 48
Partien war die Antwort bei Zug 200 dieselbe wie bei Zug 1500.  Deshalb:
Limit 400, und "staerkster" ist die Hauptzahl.  Das kostet an dieser
Stelle nichts und bringt rund die dreifache Zahl Partien pro Rechenzeit.

"Allein uebrig" wird trotzdem mitgezaehlt, aber ehrlich in drei Toepfen:
gewonnen, verloren, unentschieden (Limit erreicht).  Eine Partie, die
nicht zu Ende gespielt wurde, als Niederlage zu buchen waere gelogen.
Fuer die Aufstellung "lehrer" - die einzige, die zuverlaessig endet und
zugleich der Ernstfall ist - gibt es einen eigenen Lauf ohne Sparlimit.

Zwei Dinge werden getrennt gemessen:

1. **Die Tabelle.**  Wie gut ist der ausgelieferte Bot gegen jede
   Aufstellung?  Unabhaengige Partien, Wilson-Intervall.

2. **Das A/B.**  Bringt ein Gewicht etwas?  Hier laufen alle Varianten auf
   *denselben* Brettern (gleicher Seed = gleiche Startpositionen, gleiche
   Zugreihenfolge, gleiche Kampfwuerfe).  Das ist ein gepaarter Vergleich:
   die Brett-Varianz faellt heraus, und man braucht rund ein Viertel der
   Partien fuer dieselbe Aussage.  Ausgewertet wird mit McNemar, weil nur
   die Bretter zaehlen, auf denen sich die Varianten unterscheiden.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from multiprocessing import Pool
from typing import Dict, List, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


#: Die Aufstellungen ("Parteien"), gegen die gemessen wird.
#: Jede steht fuer eine andere Sorte Turnier-Gegner.
MIXES: Dict[str, Tuple[str, ...]] = {
    # Genau die Aufstellung aus PacmanGame.py - das ist der Ernstfall.
    "lehrer":      ("random", "random", "random", "trex", "trex"),
    # Was die meisten Mitschueler bauen werden: gerade Fresser.
    "fresser":     ("harvester", "harvester", "harvester", "trex", "random"),
    # Aggressive Runde - hier entscheidet die Kampfrechnung.
    "jaeger":      ("hunter", "hunter", "harvester", "trex", "random"),
    # Ausweich-Runde - hier entscheidet, wer schneller Kohl frisst.
    "feiglinge":   ("coward", "coward", "cautious", "harvester", "random"),
    # Gemischt und stark, keiner davon war im Training.
    "gemischt":    ("hunter", "sweeper", "cautious", "harvester", "trex"),
    # Nur unsere staerksten Sparringspartner.
    "hart":        ("sweeper", "sweeper", "hunter", "cautious", "harvester"),
    # --- 15 Spieler: die Groesse, die im Turnier zu erwarten ist ---------
    # Alle Zahlen dieses Projekts stammten lange aus Sechser-Runden. Bei 15
    # Spielern aendert sich das Spiel spuerbar: auf 197 begehbaren Feldern
    # kommen statt 32 nur noch 13 Kohl auf jeden, und future_value - der
    # Wert, der Angriff und Jagd steuert - faellt damit auf ein Drittel.
    # Der Bot wird also viel frueher mutig. Ob das richtig ist, muss
    # gemessen werden und nicht angenommen.
    "turnier15":   ("random", "random", "random", "trex", "trex",
                    "harvester", "harvester", "harvester", "sweeper",
                    "sweeper", "hunter", "hunter", "cautious", "coward"),
    "turnier15hart": ("harvester", "harvester", "sweeper", "sweeper",
                      "sweeper", "hunter", "hunter", "hunter", "cautious",
                      "cautious", "coward", "trex", "harvester", "sweeper"),
}

DEFAULT_WEIGHTS_FILE = "results/thorest_weights.json"


def load_weights(path: str = DEFAULT_WEIGHTS_FILE):
    from superpac.pacman.agent import Weights
    with open(path) as handle:
        return Weights(**json.load(handle)["weights"])


def variants(spec: Sequence[str]) -> Dict[str, object]:
    """Was gegeneinander antritt.

    Zwei Formen, weil zwei verschiedene Fragen dahinterstehen:

    ``name=feld:wert,...``
        Unser Bot mit geaenderten Gewichten.  Beantwortet "bringt dieses
        Gewicht etwas".
    ``name=@harvester``
        Ein anderer Bot als Spieler, auf denselben Brettern.  Beantwortet
        "ist unser Bot besser als die naheliegende einfache Strategie" -
        und das ist die Frage, die zaehlt, wenn Mitschueler antreten.
    """
    out: Dict[str, object] = {"basis": {}}
    for item in spec:
        name, _, rest = item.partition("=")
        if rest.startswith("@"):
            out[name] = rest            # Platzhalter-Bot, kein Gewicht
            continue
        changes = {}
        for pair in filter(None, rest.split(",")):
            field, _, value = pair.partition(":")
            changes[field] = float(value)
        out[name] = changes
    return out


def describe(entry) -> str:
    if isinstance(entry, str):
        return f"Spieler: {entry[1:]} (nicht unser Bot)"
    return str(entry) if entry else "(ausgelieferte Gewichte)"


# ----------------------------------------------------------------------
# Ein Arbeitspaket = eine Partie.  Die Worker importieren die Engine selbst,
# weil Klassen aus Pacman.py nicht ueber einen Prozess hinweg picklebar sind.
_STATE: dict = {}


def _init(weights_file: str, overrides: Dict[str, object], max_turns: int) -> None:
    import Pacman
    from superpac.pacman.opponents import build_opponents
    from superpac.pacman.thorest import build_thorest
    from superpac.pacman.tuning import build_mix

    base = load_weights(weights_file)
    catalogue = dict(build_opponents(Pacman.Pacman))
    catalogue["random"] = Pacman.Pacman
    try:
        from TRex import TRex
        catalogue["trex"] = TRex
    except Exception:
        catalogue["trex"] = Pacman.Pacman

    classes = {}
    for name, entry in overrides.items():
        if isinstance(entry, str):
            classes[name] = catalogue[entry[1:]]
        else:
            classes[name] = build_thorest(Pacman.Pacman,
                                          weights=base.with_(**entry))
    _STATE["classes"] = classes
    _STATE["mixes"] = {name: build_mix(names) for name, names in MIXES.items()}
    _STATE["max_turns"] = max_turns


def _one(job: Tuple[str, str, int]) -> dict:
    from superpac.pacman.arena import default_walls, play

    variant, mix, seed = job
    result = play(_STATE["classes"][variant], fillers=_STATE["mixes"][mix],
                  seed=seed, walls=default_walls(),
                  max_turns=_STATE["max_turns"])
    return {"variant": variant, "mix": mix, "seed": seed,
            "won": result.won, "strongest": result.subject_rank == 0,
            "alive": result.subject_alive, "strength": result.subject_strength,
            "turns": result.turns, "capped": result.hit_cap,
            "faults": result.faults, "ms": result.ms_per_turn}


# ----------------------------------------------------------------------
def wilson(hits: int, n: int) -> Tuple[float, float, float]:
    """Punktschaetzer und 95%-Wilson-Intervall.

    Wilson statt der Lehrbuch-Normalnaeherung, weil die bei Quoten nahe 0
    oder 1 - genau da, wo wir landen wollen - Intervalle ausgibt, die ueber
    die Grenzen hinausragen.
    """
    if n == 0:
        return 0.0, 0.0, 0.0
    z = 1.959963985
    p = hits / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, centre - half), min(1.0, centre + half)


def mcnemar(only_a: int, only_b: int) -> float:
    """Zweiseitiger p-Wert fuer gepaarte Ja/Nein-Ergebnisse.

    Nur die Bretter zaehlen, auf denen genau eine Variante gewonnen hat;
    die uebrigen tragen keine Information ueber den Unterschied.  Unter der
    Nullhypothese ist jedes dieser Bretter ein fairer Muenzwurf.

    Gerechnet wird im Logarithmus.  Die direkte Formel
    ``sum(comb(n, i)) / 2**n`` sieht harmlos aus, aber ``2.0 ** n`` sprengt
    ab n = 1024 den Float-Bereich - und genau dort landen wir, wenn der
    Benchmark endlich gross genug ist, um etwas zu sehen.  Zaehler und
    Nenner sind exakte Ganzzahlen; ``math.log`` nimmt die in voller Groesse,
    also faellt die Differenz der Logarithmen sauber heraus.
    """
    n = only_a + only_b
    if n == 0:
        return 1.0
    k = min(only_a, only_b)
    numerator = sum(math.comb(n, i) for i in range(k + 1))
    log_p = math.log(numerator) - n * math.log(2.0)
    return min(1.0, 2.0 * math.exp(log_p)) if log_p > -700 else 0.0


def paired_difference(only_a: int, only_b: int, pairs: int):
    """Unterschied in Prozentpunkten samt 95%-Intervall.

    Der p-Wert sagt nur, *ob* ein Unterschied da ist.  Bei 3600 gepaarten
    Brettern wird auch ein halber Prozentpunkt signifikant, und ein halber
    Prozentpunkt ist uns egal.  Deshalb immer die Groesse dazu.
    """
    if pairs == 0:
        return 0.0, 0.0, 0.0
    diff = (only_a - only_b) / pairs
    # Varianz der gepaarten Differenz: die uebereinstimmenden Bretter
    # tragen 0 bei, die abweichenden +1 bzw. -1.
    discordant = only_a + only_b
    var = (discordant - (only_a - only_b) ** 2 / pairs) / (pairs * pairs)
    half = 1.959963985 * math.sqrt(max(0.0, var))
    return diff, diff - half, diff + half


# ----------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=300,
                    help="Partien je Aufstellung und Variante")
    ap.add_argument("--mixes", default=",".join(MIXES))
    ap.add_argument("--variant", action="append", default=[],
                    help="Gewicht: name=feld:wert / Bot: name=@harvester")
    ap.add_argument("--max-turns", type=int, default=400)
    ap.add_argument("--seed", type=int, default=20000)
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--weights", default=DEFAULT_WEIGHTS_FILE)
    ap.add_argument("--out", default="results/grossbenchmark.json")
    ap.add_argument("--report-only", action="store_true",
                    help="nur auswerten, nicht neu spielen")
    args = ap.parse_args()

    if args.report_only:
        with open(args.out) as handle:
            saved = json.load(handle)
        report(saved["rows"], saved["mixes"], list(saved["variants"]))
        return 0

    mixes = [m.strip() for m in args.mixes.split(",") if m.strip()]
    unknown = set(mixes) - set(MIXES)
    if unknown:
        ap.error(f"unbekannte Aufstellung: {sorted(unknown)}")
    overrides = variants(args.variant)

    # Gemeinsame Zufallszahlen: dieselbe Seed-Liste fuer jede Variante.
    jobs = [(v, m, args.seed + i)
            for m in mixes for i in range(args.games) for v in overrides]

    print(f"{len(jobs)} Partien: {len(overrides)} Varianten x {len(mixes)} "
          f"Aufstellungen x {args.games}, {args.workers} Prozesse")
    for name, entry in overrides.items():
        print(f"  Variante {name:<16s} {describe(entry)}")
    sys.stdout.flush()

    started = time.time()
    rows: List[dict] = []
    with Pool(args.workers, initializer=_init,
              initargs=(args.weights, overrides, args.max_turns)) as pool:
        for n, row in enumerate(pool.imap_unordered(_one, jobs, chunksize=4), 1):
            rows.append(row)
            if n % 50 == 0 or n == len(jobs):
                done = time.time() - started
                left = done / n * (len(jobs) - n)
                print(f"  {n}/{len(jobs)}  {done/60:.1f} min gelaufen, "
                      f"noch ~{left/60:.1f} min", flush=True)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as handle:
        json.dump({"games": args.games, "mixes": mixes,
                   "variants": overrides, "seed": args.seed,
                   "max_turns": args.max_turns, "weights": args.weights,
                   "elapsed_s": round(time.time() - started, 1),
                   "rows": rows}, handle, indent=1)
    print(f"\n{len(rows)} Partien in {(time.time()-started)/60:.1f} min "
          f"-> {args.out}")
    report(rows, mixes, list(overrides))
    return 0


def report(rows: List[dict], mixes: Sequence[str],
           names: Sequence[str]) -> None:
    def cell(v, m):
        return [r for r in rows if r["variant"] == v and r["mix"] == m]

    def quote(got, metric, only_decided=False):
        if only_decided:
            got = [r for r in got if not r["capped"]]
        if not got:
            return "  --  ".center(26)
        p, lo, hi = wilson(sum(r[metric] for r in got), len(got))
        return f"{p:6.1%} [{lo:5.1%},{hi:5.1%}]".center(26)

    for metric, label, decided in (
            ("strongest", "staerkster (Hauptzahl)", False),
            ("won", "allein uebrig - alle Partien", False),
            ("won", "allein uebrig - nur entschiedene Partien", True)):
        print(f"\n=== {label} ===")
        print(f"{'Aufstellung':<12s} " + " ".join(f"{n:^26s}" for n in names))
        for m in mixes:
            print(f"{m:<12s} " + " ".join(
                quote(cell(v, m), metric, decided) for v in names))
        print(f"{'GESAMT':<12s} " + " ".join(
            quote([r for r in rows if r["variant"] == v], metric, decided)
            for v in names))

    print("\n=== unentschieden (Zuglimit erreicht) ===")
    print(f"{'Aufstellung':<12s} " + " ".join(f"{n:^26s}" for n in names))
    for m in mixes:
        parts = []
        for v in names:
            got = cell(v, m)
            parts.append(f"{sum(r['capped'] for r in got)/max(1,len(got)):6.1%}"
                         .center(26))
        print(f"{m:<12s} " + " ".join(parts))

    print("\n=== Kennzahlen ===")
    for v in names:
        got = [r for r in rows if r["variant"] == v]
        capped = sum(r["capped"] for r in got)
        print(f"{v:<16s} staerke={sum(r['strength'] for r in got)/len(got):6.1f}  "
              f"lebt={sum(r['alive'] for r in got)/len(got):5.1%}  "
              f"zuege={sum(r['turns'] for r in got)/len(got):6.0f}  "
              f"ms={sum(r['ms'] for r in got)/len(got):5.2f}  "
              f"Limit erreicht={capped/len(got):4.0%}  "
              f"Fehler={sum(r['faults'] for r in got)}")

    if len(names) < 2:
        return
    print("\n=== Gepaarter Vergleich gegen 'basis' (McNemar) ===")
    print("nur Bretter, auf denen sich die Varianten unterscheiden\n")
    base = {(r["mix"], r["seed"]): r for r in rows if r["variant"] == names[0]}
    for v in names[1:]:
        for metric, label in (("won", "allein uebrig"),
                              ("strongest", "staerkster")):
            a = b = 0
            for r in rows:
                if r["variant"] != v:
                    continue
                other = base.get((r["mix"], r["seed"]))
                if other is None or other[metric] == r[metric]:
                    continue
                if r[metric]:
                    a += 1
                else:
                    b += 1
            p = mcnemar(a, b)
            pairs = sum(1 for r in rows if r["variant"] == v
                        and (r["mix"], r["seed"]) in base)
            d, lo, hi = paired_difference(a, b, pairs)
            if p >= 0.05:
                verdict = "kein Unterschied"
            elif d > 0:
                verdict = "BESSER"
            else:
                verdict = "SCHLECHTER"
            print(f"  {v:<16s} {label:<14s} {a:4d} : {b:4d} Bretter  "
                  f"{d:+6.1%} [{lo:+5.1%},{hi:+5.1%}]  p={p:.2g}  {verdict}")


if __name__ == "__main__":
    raise SystemExit(main())
