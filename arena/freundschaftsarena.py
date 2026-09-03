"""Freundschaftsarena - eure Bots gegeneinander, mit Auswertung.

Aufruf::

    python arena/freundschaftsarena.py                 # alles aus arena/bots/
    python arena/freundschaftsarena.py --partien 50
    python arena/freundschaftsarena.py --fueller 3     # 3 zusaetzliche Gegner
    python arena/freundschaftsarena.py --bericht auswertung.json

Wie sie an eure Bots kommt
--------------------------
Jede ``.py``-Datei in ``arena/bots/`` wird geladen, und jede Klasse darin,
die von ``Pacman`` erbt, tritt an.  Ihr muesst nichts anmelden und nichts
importieren - Datei hineinlegen genuegt.

Wie die Auswertung entsteht
---------------------------
Die Arena fasst eure Bots **nicht** an.  Sie schaut vor und nach jedem Zug
auf das Brett und liest ab, was passiert ist.  Das geht, weil die Engine
nur drei Dinge zulaesst und jedes eine andere Spur hinterlaesst:

  Position anders                 -> gezogen (und was dabei gefressen wurde,
                                     steht in der Staerkedifferenz)
  Position gleich, Richtung anders-> gedreht
  beides gleich, noch am Leben    -> nichts erreicht: stehengeblieben, gegen
                                     eine Wand gelaufen, oder in die Richtung
                                     gedreht, in die man schon schaute
  vorher lebendig, jetzt tot      -> angegriffen und verloren

Der letzte Fall ist der wichtigste beim Verbessern: die Engine wertet einen
verlorenen Angriff nicht als Zug, sondern als Spielende.

Achtung: die Bot-Dateien werden ganz normal ausgefuehrt, mit allen Rechten,
die dieses Skript hat.  Legt nur Dateien hinein, deren Herkunft ihr kennt.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import random
import sys
import time
from collections import Counter
from typing import Dict, List, Optional, Sequence, Tuple

HIER = os.path.dirname(os.path.abspath(__file__))
WURZEL = os.path.dirname(HIER)
for pfad in (WURZEL, HIER):
    if pfad not in sys.path:
        sys.path.insert(0, pfad)

import Pacman  # noqa: E402  - erst nach dem sys.path-Eintrag moeglich
from Pacman import Direction, Pacman as PacmanBasis, Position  # noqa: E402

#: Die Wandaufstellung aus PacmanGame.py.
WAENDE = [[[5, 3], Direction.east, 8], [[5, 4], Direction.south, 3],
          [[12, 4], Direction.south, 3], [[2, 12], Direction.east, 8],
          [[2, 11], Direction.north, 3], [[9, 11], Direction.north, 3]]

RICHTUNGSNAME = {(0, -1): "N", (0, 1): "S", (-1, 0): "W", (1, 0): "O"}


# ==========================================================================
# Bots einsammeln
# ==========================================================================
def lade_bots(ordner: str) -> List[Tuple[str, type]]:
    """Jede Pacman-Unterklasse aus jeder ``.py`` in ``ordner``.

    Fehlerhafte Dateien werden gemeldet und uebersprungen - eine kaputte
    Datei eines Freundes soll nicht das ganze Turnier verhindern.
    """
    gefunden: List[Tuple[str, type]] = []
    if not os.path.isdir(ordner):
        return gefunden
    for datei in sorted(os.listdir(ordner)):
        if not datei.endswith(".py") or datei.startswith("_"):
            continue
        pfad = os.path.join(ordner, datei)
        modulname = "arenabot_" + os.path.splitext(datei)[0]
        try:
            spez = importlib.util.spec_from_file_location(modulname, pfad)
            modul = importlib.util.module_from_spec(spez)
            sys.modules[modulname] = modul
            spez.loader.exec_module(modul)
        except Exception as fehler:
            print(f"  !! {datei} laesst sich nicht laden: {fehler}")
            continue
        for name in dir(modul):
            wert = getattr(modul, name)
            if (isinstance(wert, type) and issubclass(wert, PacmanBasis)
                    and wert is not PacmanBasis
                    and wert.__module__ == modulname):
                gefunden.append((name, wert))
    return gefunden


# ==========================================================================
# Fuellspieler, die nicht dumm sind
# ==========================================================================
def _blick(pacman) -> int:
    d = pacman.direction
    return {(0, -1): 0, (0, 1): 1, (-1, 0): 2, (1, 0): 3}.get((d._x, d._y), 3)


_DELTA = ((0, -1), (0, 1), (-1, 0), (1, 0))
_RICHTUNGEN = (Direction.north, Direction.south, Direction.west, Direction.east)


def _bahn(pacman, richtung: int, weite: int = 10) -> int:
    """Wieviel Kohl am Stueck vor uns liegt."""
    x, y = pacman.position._x, pacman.position._y
    dx, dy = _DELTA[richtung]
    groesse = Position.fieldsize
    zaehler = 0
    for _ in range(weite):
        x, y = (x + dx) % groesse, (y + dy) % groesse
        if not isinstance(pacman._field[Position(x, y)], Pacman.Cabbage):
            break
        zaehler += 1
    return zaehler


def baue_fueller(stufe: float, saat: int) -> type:
    """Ein Fuellspieler mit zufaelligem, aber vernuenftigem Charakter.

    ``stufe`` zwischen 0 und 1 mischt zwischen "frisst, was vor ihm liegt"
    und "sucht sich die laengste Bahn und meidet Staerkere".  Kein
    Wuerfelbot: der Zufallsbot der Engine trifft in der Haelfte der Zuege
    gar keine Entscheidung, und gegen den zu gewinnen sagt wenig.
    """
    class Fueller(PacmanBasis):
        def __init__(self, p, name, field):
            super().__init__(p, name, field)
            self.logo = "F"
            self.icon = "icons/Pacman.png"
            self._wuerfel = random.Random(saat)
            self.direction = self._wuerfel.choice(_RICHTUNGEN)

        def TurnOrMoveOrStill(self):
            blick = _blick(self)
            groesse = Position.fieldsize
            # Wer staerker ist und direkt vor uns steht, ist eine schlechte
            # Idee - unabhaengig von der Stufe.
            dx, dy = _DELTA[blick]
            vorne = self._field[Position((self.position._x + dx) % groesse,
                                         (self.position._y + dy) % groesse)]
            if isinstance(vorne, PacmanBasis) and vorne.strength > self.strength:
                self.direction = _RICHTUNGEN[(blick + 1) % 4]
                return
            if isinstance(vorne, Pacman.Wall):
                self.direction = _RICHTUNGEN[(blick + 1) % 4]
                return
            if _bahn(self, blick) > 0:
                self._Move()
                return
            # Bahn leer: mit Wahrscheinlichkeit "stufe" die beste suchen,
            # sonst einfach weiterlaufen.
            if self._wuerfel.random() < stufe:
                beste = max(range(4), key=lambda r: _bahn(self, r))
                if beste != blick:
                    self.direction = _RICHTUNGEN[beste]
                    return
            self._Move()

    Fueller.__name__ = "Fueller"
    return Fueller


# ==========================================================================
# Eine Partie, beobachtet
# ==========================================================================
class Protokoll:
    """Was ein Spieler in einer Partie getan hat."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.zuege = 0
        self.gezogen = 0
        self.gedreht = 0
        self.blockiert = 0          # nichts erreicht
        self.kohl = 0
        self.kaempfe_gewonnen = 0
        self.kaempfe_verloren = 0
        self.verteidigt = 0         # angegriffen worden und ueberlebt
        self.beute = 0.0            # Staerke aus eigenen Angriffen
        self.verteidigungsbeute = 0.0
        self.getoetet: List[str] = []
        self.gestorben_gegen: Optional[str] = None
        self.gestorben_in_zug: Optional[int] = None
        self.ms = 0.0
        self.langsamster_ms = 0.0
        self.fehler = 0
        self.verlauf: List[float] = []
        self.endstaerke = 0.0
        self.lebt = True

    def als_dict(self) -> dict:
        entscheidungen = max(1, self.zuege)
        return {
            "name": self.name, "zuege": self.zuege,
            "gezogen": self.gezogen, "gedreht": self.gedreht,
            "blockiert": self.blockiert,
            "leerlauf_anteil": self.blockiert / entscheidungen,
            "kohl": self.kohl, "beute": self.beute,
            "verteidigungsbeute": self.verteidigungsbeute,
            "kaempfe_gewonnen": self.kaempfe_gewonnen,
            "kaempfe_verloren": self.kaempfe_verloren,
            "verteidigt": self.verteidigt,
            "getoetet": self.getoetet,
            "gestorben_gegen": self.gestorben_gegen,
            "gestorben_in_zug": self.gestorben_in_zug,
            "endstaerke": self.endstaerke, "lebt": self.lebt,
            "ms_schnitt": self.ms / entscheidungen,
            "ms_maximum": self.langsamster_ms,
            "fehler": self.fehler,
            "verlauf": self.verlauf,
        }


def _kohlfelder(brett, groesse: int) -> set:
    return {y * groesse + x for y in range(groesse) for x in range(groesse)
            if isinstance(brett.field[Position(x, y)], Pacman.Cabbage)}


def spiele(aufstellung: Sequence[Tuple[type, str]], saat: int,
           groesse: int = 15, waende: Optional[list] = None,
           grenze: int = 1500,
           aufzeichnung: Optional[dict] = None,
           mitschrift=None) -> Tuple[Dict[str, Protokoll], int]:
    """Eine Partie auf der echten Engine, Zug fuer Zug mitgeschrieben.

    Wird ``aufzeichnung`` uebergeben, wird sie mit dem Verlauf gefuellt:
    einmal das feste Brett, dann je Zug die Spieler und welcher Kohl in
    diesem Zug verschwunden ist. Nicht der ganze Kohl je Bild - das waeren
    bei 400 Zuegen 90 000 Zahlen fuer eine Information, die sich pro Zug um
    hoechstens eine Handvoll Felder aendert.
    """
    random.seed(saat)
    if waende is None:
        waende = WAENDE
    brett = Pacman.Field(groesse, [[k, n] for k, n in aufstellung], waende)
    protokolle = {p.name: Protokoll(p.name) for p in brett.pacmans}

    if aufzeichnung is not None:
        kohl_vorher = _kohlfelder(brett, groesse)
        aufzeichnung.update({
            "groesse": groesse,
            "waende": sorted(
                y * groesse + x for y in range(groesse) for x in range(groesse)
                if isinstance(brett.field[Position(x, y)], Pacman.Wall)),
            "kohl": sorted(kohl_vorher),
            "spieler": [p.name for p in brett.pacmans],
            "bilder": [],
        })

    zug = 0
    lebend = sum(1 for p in brett.pacmans if p.alive)
    while lebend > 1 and zug < grenze:
        for spieler in random.sample(brett.pacmans, len(brett.pacmans)):
            if not spieler.alive:
                continue
            protokoll = protokolle[spieler.name]
            vor_pos = (spieler.position._x, spieler.position._y)
            vor_ric = (spieler.direction._x, spieler.direction._y)
            vor_kraft = spieler.strength
            vor_lebend = {p.name for p in brett.pacmans if p.alive}

            zeile = (mitschrift.lage(brett, spieler, groesse, zug)
                     if mitschrift is not None else None)

            start = time.perf_counter()
            try:
                spieler.TurnOrMoveOrStill()
            except Exception:
                protokoll.fehler += 1
                if zeile is not None:
                    zeile["fehler"] = True
            gedauert = (time.perf_counter() - start) * 1000.0
            protokoll.ms += gedauert
            protokoll.langsamster_ms = max(protokoll.langsamster_ms, gedauert)

            nach_pos = (spieler.position._x, spieler.position._y)
            nach_ric = (spieler.direction._x, spieler.direction._y)
            zuwachs = spieler.strength - vor_kraft
            protokoll.zuege += 1

            if zeile is not None:
                grund = mitschrift.begruendung(spieler)
                if grund:
                    zeile["warum"] = grund

            if not spieler.alive:
                # Nur ein selbst begonnener Angriff kann uns im eigenen Zug
                # toeten; die Engine setzt dabei alive = False.
                protokoll.kaempfe_verloren += 1
                protokoll.lebt = False
                protokoll.gestorben_in_zug = zug
                # Wer uns geschlagen hat, steht auf dem Feld, das wir
                # angegriffen haben - dort ist er geblieben, denn die
                # Engine bewegt den Verteidiger nicht.
                gegner = brett.field[Position(
                    (vor_pos[0] + vor_ric[0]) % groesse,
                    (vor_pos[1] + vor_ric[1]) % groesse)]
                if isinstance(gegner, PacmanBasis):
                    protokoll.gestorben_gegen = gegner.name
                    protokolle[gegner.name].verteidigt += 1
                    # Die Engine schenkt dem Verteidiger unsere volle
                    # Staerke. Ohne diese Zeile fehlt sie in der Bilanz.
                    protokolle[gegner.name].verteidigungsbeute += vor_kraft
            elif nach_pos != vor_pos:
                protokoll.gezogen += 1
                gefallen = vor_lebend - {p.name for p in brett.pacmans if p.alive}
                if gefallen:
                    protokoll.kaempfe_gewonnen += 1
                    protokoll.beute += zuwachs
                    for name in gefallen:
                        protokoll.getoetet.append(name)
                        protokolle[name].lebt = False
                        protokolle[name].gestorben_gegen = spieler.name
                        protokolle[name].gestorben_in_zug = zug
                        if mitschrift is not None:
                            mitschrift.markiere_tod(name, spieler.name, zug)
                elif zuwachs > 0:
                    protokoll.kohl += int(zuwachs)
            elif nach_ric != vor_ric:
                protokoll.gedreht += 1
            else:
                protokoll.blockiert += 1

            if zeile is not None:
                if not spieler.alive:
                    zeile["aktion"] = "angegriffen"
                    zeile["ergebnis"] = ("gestorben gegen "
                                         + str(protokoll.gestorben_gegen))
                    zeile["tod"] = {"durch": protokoll.gestorben_gegen,
                                    "zug": zug, "art": "Angriff verloren"}
                elif nach_pos != vor_pos:
                    zeile["aktion"] = "gezogen"
                    if zuwachs > 1:
                        zeile["ergebnis"] = f"Gegner gefressen (+{zuwachs:.0f})"
                    elif zuwachs > 0:
                        zeile["ergebnis"] = "Kohl"
                elif nach_ric != vor_ric:
                    zeile["aktion"] = "gedreht"
                else:
                    zeile["aktion"] = "nichts"
                    zeile["ergebnis"] = "ohne Wirkung"
                mitschrift.anfuegen(zeile)

        for p in brett.pacmans:
            protokolle[p.name].verlauf.append(float(p.strength))
        if aufzeichnung is not None:
            kohl_jetzt = _kohlfelder(brett, groesse)
            aufzeichnung["bilder"].append({
                "p": [[p.position._x, p.position._y,
                       RICHTUNGSNAME.get((p.direction._x, p.direction._y), "O"),
                       float(p.strength), 1 if p.alive else 0]
                      for p in brett.pacmans],
                "weg": sorted(kohl_vorher - kohl_jetzt),
            })
            kohl_vorher = kohl_jetzt
        lebend = sum(1 for p in brett.pacmans if p.alive)
        zug += 1

    for p in brett.pacmans:
        protokolle[p.name].endstaerke = float(p.strength)
        protokolle[p.name].lebt = bool(p.alive)
    return protokolle, zug


# ==========================================================================
# Turnier und Auswertung
# ==========================================================================
class Bilanz:
    """Alles, was ein Spieler ueber das ganze Turnier getan hat."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.partien = 0
        self.allein_uebrig = 0
        self.staerkster = 0
        self.ueberlebt = 0
        self.unentschieden = 0
        self.staerke = 0.0
        self.kohl = 0
        self.beute = 0.0
        self.verteidigungsbeute = 0.0
        self.gewonnen = 0
        self.verloren = 0
        self.verteidigt = 0
        self.zuege = 0
        self.gezogen = 0
        self.gedreht = 0
        self.blockiert = 0
        self.ms = 0.0
        self.ms_maximum = 0.0
        self.fehler = 0
        self.opfer: Counter = Counter()
        self.bezwinger: Counter = Counter()

    @property
    def quote(self) -> float:
        return self.allein_uebrig / self.partien if self.partien else 0.0

    @property
    def staerkster_quote(self) -> float:
        return self.staerkster / self.partien if self.partien else 0.0

    @property
    def leerlauf(self) -> float:
        return self.blockiert / self.zuege if self.zuege else 0.0


def wilson(treffer: int, n: int) -> Tuple[float, float]:
    """95%-Intervall nach Wilson - traegt auch Quoten nahe 0 und 1."""
    if n == 0:
        return 0.0, 0.0
    z = 1.96
    p = treffer / n
    nenner = 1 + z * z / n
    mitte = (p + z * z / (2 * n)) / nenner
    halb = z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5 / nenner
    return max(0.0, mitte - halb), min(1.0, mitte + halb)


def turnier(aufstellung: Sequence[Tuple[type, str]], partien: int,
            saat: int, groesse: int, waende: Optional[list],
            grenze: int) -> Tuple[Dict[str, Bilanz], List[dict]]:
    bilanzen = {name: Bilanz(name) for _, name in aufstellung}
    rohdaten: List[dict] = []
    for i in range(partien):
        protokolle, zuege = spiele(aufstellung, saat + i, groesse, waende, grenze)
        lebende = [p for p in protokolle.values() if p.lebt]
        hoechste = max(p.endstaerke for p in protokolle.values())
        for protokoll in protokolle.values():
            b = bilanzen[protokoll.name]
            b.partien += 1
            b.staerke += protokoll.endstaerke
            b.kohl += protokoll.kohl
            b.beute += protokoll.beute
            b.verteidigungsbeute += protokoll.verteidigungsbeute
            b.gewonnen += protokoll.kaempfe_gewonnen
            b.verloren += protokoll.kaempfe_verloren
            b.verteidigt += protokoll.verteidigt
            b.zuege += protokoll.zuege
            b.gezogen += protokoll.gezogen
            b.gedreht += protokoll.gedreht
            b.blockiert += protokoll.blockiert
            b.ms += protokoll.ms
            b.ms_maximum = max(b.ms_maximum, protokoll.langsamster_ms)
            b.fehler += protokoll.fehler
            if protokoll.lebt:
                b.ueberlebt += 1
            if protokoll.lebt and len(lebende) == 1:
                b.allein_uebrig += 1
            if len(lebende) > 1:
                b.unentschieden += 1
            if protokoll.endstaerke >= hoechste:
                b.staerkster += 1
            for opfer in protokoll.getoetet:
                b.opfer[opfer] += 1
            if protokoll.gestorben_gegen:
                b.bezwinger[protokoll.gestorben_gegen] += 1
        rohdaten.append({"saat": saat + i, "zuege": zuege,
                         "spieler": {n: p.als_dict()
                                     for n, p in protokolle.items()}})
        if partien > 5 and (i + 1) % max(1, partien // 10) == 0:
            print(f"  {i + 1}/{partien} Partien", flush=True)
    return bilanzen, rohdaten


def tabelle(bilanzen: Dict[str, Bilanz], partien: int) -> None:
    reihen = sorted(bilanzen.values(),
                    key=lambda b: (-b.staerkster_quote, -b.quote))
    fair = 1.0 / max(1, len(bilanzen))
    print(f"\n{'Spieler':<18s} {'staerkster':>18s} {'allein uebrig':>16s} "
          f"{'lebt':>6s} {'Staerke':>8s} {'Leerlauf':>9s} {'ms/Zug':>7s}")
    print("-" * 90)
    for b in reihen:
        lo, hi = wilson(b.staerkster, b.partien)
        print(f"{b.name:<18s} {b.staerkster_quote:6.1%} [{lo:4.0%},{hi:4.0%}] "
              f"{b.quote:15.1%} {b.ueberlebt / max(1, b.partien):6.0%} "
              f"{b.staerke / max(1, b.partien):8.1f} {b.leerlauf:8.0%} "
              f"{b.ms / max(1, b.zuege):7.2f}"
              + (f"   FEHLER {b.fehler}" if b.fehler else ""))
    print(f"\nBei {len(bilanzen)} Spielern waeren {fair:.1%} fair. "
          f"{partien} Partien je Spieler.")


def diagnose(bilanzen: Dict[str, Bilanz]) -> None:
    """Der Teil, aus dem man etwas fuer den eigenen Bot lernt."""
    print("\n" + "=" * 90)
    print("Woher die Staerke kam, und was die Zuege gekostet hat")
    print("=" * 90)
    for b in sorted(bilanzen.values(), key=lambda b: -b.staerke):
        gesamt = b.kohl + b.beute + b.verteidigungsbeute
        anteil = (b.beute + b.verteidigungsbeute) / gesamt if gesamt else 0.0
        kaempfe = b.gewonnen + b.verloren
        print(f"\n{b.name}")
        print(f"  Staerke je Partie   {b.staerke / max(1, b.partien):6.1f}  "
              f"davon {anteil:.0%} aus Kaempfen, {1 - anteil:.0%} aus Kohl")
        print(f"  Zuege               {b.gezogen / max(1, b.zuege):5.0%} gezogen, "
              f"{b.gedreht / max(1, b.zuege):.0%} gedreht, "
              f"{b.leerlauf:.0%} ohne Wirkung")
        if kaempfe:
            print(f"  Kaempfe             {kaempfe} begonnen, "
                  f"{b.gewonnen / kaempfe:.0%} gewonnen "
                  f"({b.gewonnen} zu {b.verloren})")
        else:
            print("  Kaempfe             keine begonnen")
        if b.verteidigt:
            print(f"  verteidigt          {b.verteidigt} Angriffe ueberlebt, "
                  f"dabei {b.verteidigungsbeute:.0f} Staerke geerbt")
        if b.opfer:
            print("  gefressen           " + ", ".join(
                f"{n} x{c}" for n, c in b.opfer.most_common(4)))
        if b.bezwinger:
            print("  gestorben gegen     " + ", ".join(
                f"{n} x{c}" for n, c in b.bezwinger.most_common(4)))
    print("""
Was die Zahlen bedeuten
  "ohne Wirkung"  Zuege, in denen sich weder Position noch Blickrichtung
                  geaendert haben: stehengeblieben, gegen eine Wand
                  gelaufen, oder in die Richtung gedreht, in die der Bot
                  schon schaute. Jeder davon ist ein geschenkter Zug.
  "aus Kaempfen"  Die zweite Spielhaelfte hat keinen Kohl mehr. Ein Bot,
                  der hier bei 0% steht, hoert ab der Mitte auf zu wachsen.
  "gewonnen"      Unter 50% heisst: der Bot greift zu oft von vorne an.
                  Von hinten steht die Chance bei 91%, von der Seite bei
                  83%, von vorne bei 50%.""")


def zeige_partie(aufstellung: Sequence[Tuple[type, str]], saat: int,
                 groesse: int, waende: Optional[list], grenze: int,
                 fps: int) -> Optional[Dict[str, Protokoll]]:
    """Eine Partie im Fenster, mit dem Renderer des Lehrers.

    Derselbe Ablauf wie ``PacmanGame.py``, nur mit eurer Aufstellung statt
    der festen. Mitgeschrieben wird trotzdem, sodass nach dem Schliessen
    des Fensters dieselbe Auswertung dasteht wie beim Textlauf.
    """
    try:
        import pygame
        from PacmanRenderer import Renderer
    except ImportError as fehler:
        print(f"\nFuer die grafische Anzeige fehlt etwas: {fehler}")
        print("  pygame installieren:  pip install pygame")
        print("  oder ohne Fenster:    --replay partie.html")
        return None

    random.seed(saat)
    if waende is None:
        waende = WAENDE
    brett = Pacman.Field(groesse, [[k, n] for k, n in aufstellung], waende)
    protokolle = {p.name: Protokoll(p.name) for p in brett.pacmans}

    pygame.init()
    renderer = Renderer(brett)
    uhr = pygame.time.Clock()
    pygame.display.set_caption(
        f"Freundschaftsarena - {len(aufstellung)} Spieler, Saat {saat}")

    laeuft = True
    zug = 0
    pause = False
    while laeuft:
        for ereignis in pygame.event.get():
            if ereignis.type == pygame.QUIT:
                laeuft = False
            elif ereignis.type == pygame.KEYDOWN:
                if ereignis.key == pygame.K_ESCAPE:
                    laeuft = False
                elif ereignis.key == pygame.K_SPACE:
                    pause = not pause      # Leertaste haelt an
                elif ereignis.key == pygame.K_PLUS or ereignis.key == pygame.K_EQUALS:
                    fps = min(240, fps * 2)
                elif ereignis.key == pygame.K_MINUS:
                    fps = max(1, fps // 2)

        lebend = sum(1 for p in brett.pacmans if p.alive)
        if lebend > 1 and not pause and zug < grenze:
            for spieler in random.sample(brett.pacmans, len(brett.pacmans)):
                if not spieler.alive:
                    continue
                protokoll = protokolle[spieler.name]
                vor_pos = (spieler.position._x, spieler.position._y)
                vor_ric = (spieler.direction._x, spieler.direction._y)
                vor_kraft = spieler.strength
                vor_lebend = {p.name for p in brett.pacmans if p.alive}
                start = time.perf_counter()
                try:
                    spieler.TurnOrMoveOrStill()
                except Exception:
                    protokoll.fehler += 1
                gedauert = (time.perf_counter() - start) * 1000.0
                protokoll.ms += gedauert
                protokoll.langsamster_ms = max(protokoll.langsamster_ms, gedauert)
                protokoll.zuege += 1
                nach_pos = (spieler.position._x, spieler.position._y)
                nach_ric = (spieler.direction._x, spieler.direction._y)
                zuwachs = spieler.strength - vor_kraft
                if not spieler.alive:
                    protokoll.kaempfe_verloren += 1
                    protokoll.gestorben_in_zug = zug
                    gegner = brett.field[Position(
                        (vor_pos[0] + vor_ric[0]) % groesse,
                        (vor_pos[1] + vor_ric[1]) % groesse)]
                    if isinstance(gegner, PacmanBasis):
                        protokoll.gestorben_gegen = gegner.name
                        protokolle[gegner.name].verteidigt += 1
                        protokolle[gegner.name].verteidigungsbeute += vor_kraft
                elif nach_pos != vor_pos:
                    protokoll.gezogen += 1
                    gefallen = vor_lebend - {p.name for p in brett.pacmans
                                             if p.alive}
                    if gefallen:
                        protokoll.kaempfe_gewonnen += 1
                        protokoll.beute += zuwachs
                        for name in gefallen:
                            protokoll.getoetet.append(name)
                            protokolle[name].gestorben_gegen = spieler.name
                            protokolle[name].gestorben_in_zug = zug
                    elif zuwachs > 0:
                        protokoll.kohl += int(zuwachs)
                elif nach_ric != vor_ric:
                    protokoll.gedreht += 1
                else:
                    protokoll.blockiert += 1
            zug += 1

        renderer.draw_field()
        uhr.tick(fps)

    for p in brett.pacmans:
        protokolle[p.name].endstaerke = float(p.strength)
        protokolle[p.name].lebt = bool(p.alive)
    pygame.quit()
    print(f"\nFenster geschlossen nach {zug} Zuegen.")
    return protokolle


def turnier_fuer_viewer(bilanzen: Dict[str, "Bilanz"], partien: int) -> dict:
    """Die Bilanz in die schlanke Form bringen, die der Viewer liest."""
    zeilen = sorted(
        ({"name": b.name, "staerkster": b.staerkster_quote,
          "allein": b.quote, "lebt": b.ueberlebt / max(1, b.partien),
          "staerke": b.staerke / max(1, b.partien),
          "leerlauf": b.leerlauf, "ms": b.ms / max(1, b.zuege)}
         for b in bilanzen.values()),
        key=lambda z: (-z["staerkster"], -z["allein"]))
    return {"partien": partien, "zeilen": zeilen}


def schreibe_replay(pfad: str, daten: dict) -> None:
    """Eine Partie als HTML zum Anschauen - eine Datei, ohne Zubehoer.

    Die Aufzeichnung wird in die Vorlage eingesetzt, statt sie danebenzu-
    legen: die Datei soll man weiterschicken koennen, und ein Browser laedt
    aus einer lokalen HTML-Datei ohnehin keine zweite Datei nach.
    """
    vorlage = os.path.join(HIER, "replay_vorlage.html")
    with open(vorlage) as datei:
        html = datei.read()
    # Kein </script> im JSON, sonst endet das Skript mitten in den Daten.
    roh = json.dumps(daten, separators=(",", ":")).replace("</", "<\\/")
    with open(pfad, "w") as datei:
        datei.write(html.replace("__DATEN__", roh))


# ==========================================================================
def main() -> int:
    ap = argparse.ArgumentParser(
        description="Eure Bots gegeneinander, auf der Engine des Lehrers.")
    ap.add_argument("--ordner", default=os.path.join(HIER, "bots"),
                    help="wo die Bot-Dateien liegen")
    ap.add_argument("--partien", type=int, default=20)
    ap.add_argument("--fueller", type=int, default=0,
                    help="zusaetzliche Gegner, die nicht dumm sind")
    ap.add_argument("--feldgroesse", type=int, default=15)
    ap.add_argument("--ohne-waende", action="store_true")
    ap.add_argument("--grenze", type=int, default=1500,
                    help="Zuglimit; die Engine selbst hat keines")
    ap.add_argument("--saat", type=int, default=1)
    ap.add_argument("--bericht", help="Rohdaten als JSON hierhin schreiben")
    ap.add_argument("--replay",
                    help="eine Partie als HTML zum Anschauen hierhin schreiben")
    ap.add_argument("--replay-saat", type=int,
                    help="welche Partie ins Replay soll (Standard: --saat)")
    ap.add_argument("--protokoll",
                    help="Zugprotokoll als JSONL (eine Zeile je Zug je Bot)")
    ap.add_argument("--warum",
                    help="kuratierter Bericht als Markdown - der Text, den man "
                         "einer KI vorlegt")
    ap.add_argument("--nur-tabelle", action="store_true")
    ap.add_argument("--grafisch", action="store_true",
                    help="Turnier plus Replay als HTML, oeffnet den Browser")
    ap.add_argument("--fenster", action="store_true",
                    help="live zuschauen im pygame-Fenster")
    ap.add_argument("--fps", type=int, default=12,
                    help="Zuege je Sekunde in der grafischen Anzeige")
    args = ap.parse_args()

    print(f"Bots aus {args.ordner}")
    bots = lade_bots(args.ordner)
    for name, _ in bots:
        print(f"  gefunden: {name}")
    if not bots:
        print("  (keiner) - legt .py-Dateien mit einer Pacman-Unterklasse hinein")

    aufstellung: List[Tuple[type, str]] = []
    benutzt: Counter = Counter()
    for name, klasse in bots:
        benutzt[name] += 1
        anzeige = name if benutzt[name] == 1 else f"{name}{benutzt[name]}"
        aufstellung.append((klasse, anzeige))

    for i in range(args.fueller):
        # Jeder Fueller bekommt einen anderen Charakter, damit das Feld
        # nicht aus einer Meinung in fuenffacher Ausfertigung besteht.
        stufe = (i + 1) / (args.fueller + 1)
        aufstellung.append((baue_fueller(stufe, args.saat * 1000 + i),
                            f"Fueller{i + 1}"))
        print(f"  dazu: Fueller{i + 1} (Stufe {stufe:.2f})")

    if len(aufstellung) < 2:
        print("\nMindestens zwei Spieler noetig. Mehr Bots hineinlegen, "
              "oder --fueller benutzen.")
        return 1

    waende = None if args.ohne_waende else WAENDE
    print(f"\n{len(aufstellung)} Spieler, {args.partien} Partien, "
          f"{args.feldgroesse}x{args.feldgroesse}"
          f"{' ohne Waende' if args.ohne_waende else ' mit Waenden'}, "
          f"Zuglimit {args.grenze}\n")

    if args.fenster:
        print("Leertaste haelt an, + und - aendern das Tempo, Esc beendet.\n")
        protokolle = zeige_partie(aufstellung, args.saat, args.feldgroesse,
                                  waende, args.grenze, args.fps)
        if protokolle is None:
            return 1
        for name, p in sorted(protokolle.items(),
                              key=lambda kv: -kv[1].endstaerke):
            print(f"  {name:<18s} Staerke {p.endstaerke:6.0f}  "
                  f"{'lebt' if p.lebt else 'gefressen von ' + str(p.gestorben_gegen)}"
                  f"   {p.blockiert / max(1, p.zuege):3.0%} ohne Wirkung"
                  + (f"   FEHLER {p.fehler}" if p.fehler else ""))
        return 0

    begonnen = time.time()
    bilanzen, rohdaten = turnier(aufstellung, args.partien, args.saat,
                                 args.feldgroesse, waende, args.grenze)
    tabelle(bilanzen, args.partien)
    if not args.nur_tabelle:
        diagnose(bilanzen)

    if args.bericht:
        with open(args.bericht, "w") as datei:
            json.dump({"partien": args.partien, "saat": args.saat,
                       "spieler": [n for _, n in aufstellung],
                       "rohdaten": rohdaten}, datei, indent=1)
        print(f"\nRohdaten (jeder Zug jedes Spielers): {args.bericht}")
    ziel_html = args.replay
    if args.grafisch and not ziel_html:
        ziel_html = os.path.join(os.getcwd(), "arena_turnier.html")

    if ziel_html or args.protokoll or args.warum:
        from arena.protokoll import Mitschrift

        saat = args.replay_saat if args.replay_saat is not None else args.saat
        daten: dict = {}
        mit = Mitschrift() if (args.protokoll or args.warum) else None
        protokolle, zuege = spiele(
            aufstellung, saat, args.feldgroesse, waende, args.grenze,
            aufzeichnung=daten if ziel_html else None, mitschrift=mit)
        if ziel_html:
            # Die Turniertabelle mit in die Seite: eine Partie zeigt, *wie*
            # gespielt wurde, viele zeigen, *wer* besser ist. Beides gehoert
            # auf dieselbe Seite, sonst vergleicht man am Ende doch wieder
            # zwei Bots anhand einer einzigen Partie.
            daten["turnier"] = turnier_fuer_viewer(bilanzen, args.partien)
            daten["saat"] = saat
            daten["auswertung"] = {n: p.als_dict()
                                   for n, p in protokolle.items()}
            schreibe_replay(ziel_html, daten)
            print(f"\nHTML ({args.partien} Partien plus Replay von Saat "
                  f"{saat}, {zuege} Zuege): {ziel_html}")
            if args.grafisch:
                import webbrowser
                if webbrowser.open("file://" + os.path.abspath(ziel_html)):
                    print("Im Browser geoeffnet.")
                else:
                    print("Datei im Browser oeffnen.")
        if mit is not None:
            if args.protokoll:
                mit.schreibe_jsonl(args.protokoll)
                print(f"Zugprotokoll ({len(mit.zeilen)} Zeilen): "
                      f"{args.protokoll}")
            if args.warum:
                mit.bericht(args.warum)
                print(f"Bericht fuer die KI-Anfrage: {args.warum}")

    print(f"\n{args.partien} Partien in {time.time() - begonnen:.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
