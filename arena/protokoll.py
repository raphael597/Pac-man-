"""Zugprotokoll mit Begruendung - Rohstoff fuer die Fehlersuche.

Warum es das gibt
-----------------
Die Tabelle sagt, *dass* ein Bot verloren hat. Zum Verbessern braucht man
aber, *warum* er in Zug 61 nach Norden gedreht hat, obwohl ein doppelt so
starker Gegner zwei Felder hinter ihm stand - und dass genau das drei Zuege
spaeter sein Tod war.

Deshalb schreibt dieses Modul zu jedem Zug die **Lage** mit, nicht nur die
Handlung: was in jede der vier Richtungen zeigt, wie lang die Kohlbahnen
sind, welche Gegner in Reichweite stehen, und - das ist der Kern - die
tatsaechlichen Kampfchancen in beide Richtungen, gerechnet mit der Formel
der Engine. Damit laesst sich jeder Tod zurueckverfolgen, auch bei einem
fremden Bot, in den man nicht hineinschauen kann.

Zwei Ausgaben
-------------
``.jsonl``  Eine Zeile je Zug je Bot. Vollstaendig, zum Auswerten mit
            eigenem Code.
``.md``     Der kuratierte Bericht: jeder Tod mit seiner Vorgeschichte,
            die groessten Staerkespruenge, die verschenkten Zuege. Kurz
            genug, um ihn einer KI vorzulegen und zu fragen, was der Bot
            haette tun sollen.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Sequence

#: Die Verteidigungsfaktoren der Engine. Aus Pacman.py:
#: entgegengesetzte Richtungen -> volle Staerke, quer -> ein Fuenftel,
#: gleiche Richtung (von hinten) -> ein Zehntel.
_DELTA = {"N": (0, -1), "S": (0, 1), "W": (-1, 0), "O": (1, 0)}
_GEGEN = {"N": "S", "S": "N", "W": "O", "O": "W"}


def verteidigungsfaktor(angreifer: str, verteidiger: str) -> float:
    """Womit die Staerke des Verteidigers multipliziert wird."""
    if verteidiger == _GEGEN[angreifer]:
        return 1.0          # frontal, volle Verteidigung
    if verteidiger == angreifer:
        return 0.1          # von hinten
    return 0.2              # von der Seite


def siegchance(kraft_a: float, kraft_v: float,
               blick_a: str, blick_v: str) -> float:
    """``P(Angreifer gewinnt)``, genau wie die Engine wuerfelt."""
    b = kraft_v * verteidigungsfaktor(blick_a, blick_v)
    gesamt = kraft_a + b
    return kraft_a / gesamt if gesamt > 0 else 1.0


def abstand(ax: int, ay: int, bx: int, by: int, groesse: int) -> int:
    """Manhattan auf dem Torus - die Engine hat keine Diagonalen."""
    dx = (bx - ax) % groesse
    dy = (by - ay) % groesse
    return min(dx, groesse - dx) + min(dy, groesse - dy)


class Mitschrift:
    """Sammelt die Zeilen und schreibt am Ende beide Ausgaben."""

    def __init__(self, reichweite: int = 4) -> None:
        self.zeilen: List[dict] = []
        self.reichweite = reichweite

    # ------------------------------------------------------------------
    def lage(self, brett, spieler, groesse: int, zug: int) -> dict:
        """Die Situation vor dem Zug, so wie der Bot sie haette sehen koennen."""
        import Pacman
        from Pacman import Pacman as Basis, Position

        blick = {(0, -1): "N", (0, 1): "S", (-1, 0): "W", (1, 0): "O"}.get(
            (spieler.direction._x, spieler.direction._y), "O")
        x, y = spieler.position._x, spieler.position._y

        sicht, bahn = {}, {}
        for richtung, (dx, dy) in _DELTA.items():
            feld = brett.field[Position((x + dx) % groesse, (y + dy) % groesse)]
            if isinstance(feld, Pacman.Wall):
                sicht[richtung] = "wand"
            elif isinstance(feld, Basis):
                sicht[richtung] = f"gegner:{feld.name}"
            elif isinstance(feld, Pacman.Cabbage):
                sicht[richtung] = "kohl"
            else:
                sicht[richtung] = "leer"
            # Wie viel Kohl am Stueck in diese Richtung liegt.
            laenge, cx, cy = 0, x, y
            for _ in range(10):
                cx, cy = (cx + dx) % groesse, (cy + dy) % groesse
                if not isinstance(brett.field[Position(cx, cy)], Pacman.Cabbage):
                    break
                laenge += 1
            bahn[richtung] = laenge

        gegner = []
        for anderer in brett.pacmans:
            if anderer is spieler or not anderer.alive:
                continue
            d = abstand(x, y, anderer.position._x, anderer.position._y, groesse)
            if d > self.reichweite:
                continue
            sein_blick = {(0, -1): "N", (0, 1): "S", (-1, 0): "W",
                          (1, 0): "O"}.get(
                (anderer.direction._x, anderer.direction._y), "O")
            gegner.append({
                "name": anderer.name, "abstand": d,
                "kraft": float(anderer.strength), "blick": sein_blick,
                # Beide Richtungen, denn beide entscheiden ueber Leben und Tod.
                "meine_chance": round(siegchance(
                    spieler.strength, anderer.strength, blick, sein_blick), 3),
                "seine_chance": round(siegchance(
                    anderer.strength, spieler.strength, sein_blick, blick), 3),
            })
        gegner.sort(key=lambda g: (g["abstand"], -g["seine_chance"]))

        return {"zug": zug, "bot": spieler.name, "pos": [x, y], "blick": blick,
                "kraft": float(spieler.strength), "sicht": sicht, "bahn": bahn,
                "gegner": gegner}

    # ------------------------------------------------------------------
    @staticmethod
    def begruendung(spieler) -> Optional[dict]:
        """Die Eigenauskunft des Bots, falls er eine anbietet.

        Freiwillig und ohne Pflicht: wer nichts anbietet, wird trotzdem
        vollstaendig protokolliert - nur eben von aussen. Zwei Formen
        werden erkannt:

          ``bot.begruendung()``    -> ein Text
          ``bot.brain.last_scores``-> Bewertung je moeglicher Handlung
        """
        try:
            if hasattr(spieler, "begruendung"):
                return {"text": str(spieler.begruendung())}
            werte = getattr(getattr(spieler, "brain", None), "last_scores", None)
            if werte:
                namen = {0: "dreh N", 1: "dreh S", 2: "dreh W", 3: "dreh O",
                         4: "ziehen", 5: "stehen"}
                geordnet = sorted(werte.items(), key=lambda kv: -kv[1])
                return {"bewertung": [[namen.get(a, str(a)), round(w, 2)]
                                      for a, w in geordnet]}
        except Exception:
            pass
        return None

    def anfuegen(self, zeile: dict) -> None:
        self.zeilen.append(zeile)

    def markiere_tod(self, opfer: str, durch: str, zug: int) -> None:
        """Ein Bot wurde im Zug eines anderen gefressen.

        Markiert wird sein *letzter eigener* Zug, denn dort steht die Lage,
        die er sich eingebrockt hat - typischerweise ein Ruecken, den er
        einem Staerkeren zugedreht hat. Ohne diese Markierung fehlte im
        Bericht der haeufigste Todesfall ueberhaupt: die meisten Bots
        sterben nicht am eigenen Angriff, sondern werden gefressen.
        """
        for zeile in reversed(self.zeilen):
            if zeile["bot"] == opfer:
                zeile["tod"] = {"durch": durch, "zug": zug,
                                "art": "gefressen"}
                zeile["ergebnis"] = (zeile.get("ergebnis", "")
                                     + f" | in Zug {zug} gefressen von {durch}"
                                     ).strip(" |")
                return

    # ------------------------------------------------------------------
    def schreibe_jsonl(self, pfad: str) -> None:
        with open(pfad, "w") as datei:
            for zeile in self.zeilen:
                datei.write(json.dumps(zeile, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------
    def bericht(self, pfad: str, vorlauf: int = 8,
                nur: Optional[Sequence[str]] = None) -> None:
        """Der kuratierte Bericht - kurz genug fuer eine KI-Anfrage."""
        namen = sorted({z["bot"] for z in self.zeilen})
        if nur:
            namen = [n for n in namen if n in nur]
        teile: List[str] = [
            "# Zugbericht",
            "",
            "Aus der Freundschaftsarena. Jede Zeile ist eine Lage vor dem Zug,",
            "abgelesen vom Brett - nicht aus dem Bot heraus. `meine_chance` und",
            "`seine_chance` sind die echten Kampfwahrscheinlichkeiten der Engine:",
            "`a / (a + b)`, wobei die Staerke des Verteidigers durch 1 geteilt",
            "wird (frontal), durch 5 (von der Seite) oder durch 10 (von hinten).",
            "",
        ]

        for name in namen:
            zeilen = [z for z in self.zeilen if z["bot"] == name]
            if not zeilen:
                continue
            teile += [f"## {name}", ""]

            tod = next((z for z in zeilen if "tod" in z), None)
            if tod:
                t = tod["tod"]
                teile += [
                    f"### Tot in Zug {t['zug']} — {t['art']}, "
                    f"durch {t['durch']}",
                    "",
                    "Die Zuege davor, mit der Lage, die jeweils vorlag:",
                    "", "```",
                ]
                anfang = max(0, tod["zug"] - vorlauf)
                for z in [q for q in zeilen if anfang <= q["zug"] <= tod["zug"]]:
                    teile.append(_zeile_lesbar(z))
                teile += ["```", ""]
                schuld = _diagnose(zeilen, tod, vorlauf)
                if schuld:
                    teile += ["**Was auffaellt:** " + schuld, ""]

            spruenge = _spruenge(zeilen)
            if spruenge:
                teile += ["### Groesste Staerkespruenge", "", "```"]
                teile += [_zeile_lesbar(z) for z in spruenge]
                teile += ["```", ""]

            leer = [z for z in zeilen if z.get("ergebnis") == "ohne Wirkung"]
            if leer:
                anteil = len(leer) / len(zeilen)
                teile += [
                    f"### Verschenkte Zuege: {len(leer)} von {len(zeilen)} "
                    f"({anteil:.0%})", "",
                ]
                if anteil > 0.05:
                    teile += ["```"] + [_zeile_lesbar(z) for z in leer[:6]]
                    teile += ["```", ""]
                else:
                    teile += ["Unauffaellig.", ""]

        teile += [
            "## Fragen, die sich damit stellen lassen", "",
            "* In welchem Zug war der Tod schon nicht mehr abwendbar, und",
            "  welche Handlung haette ihn dort noch verhindert?",
            "* Wurde ein Angriff mit `meine_chance` unter 0.5 begonnen?",
            "  Frontal anzugreifen ist fast immer der schlechtere Handel.",
            "* Stand `seine_chance` ueber mehrere Zuege ueber 0.8, ohne dass",
            "  der Bot reagiert hat? Dann fehlt ihm die Gefahrenwahrnehmung.",
            "* Gab es Zuege mit langer Kohlbahn voraus, in denen er trotzdem",
            "  gedreht hat? Drehen kostet einen ganzen Zug.",
            "",
        ]
        with open(pfad, "w") as datei:
            datei.write("\n".join(teile))


# --------------------------------------------------------------------------
def _zeile_lesbar(z: dict) -> str:
    g = ""
    if z["gegner"]:
        n = z["gegner"][0]
        g = (f"  | naechster {n['name']} d={n['abstand']} k={n['kraft']:.0f} "
             f"Blick {n['blick']} ich {n['meine_chance']:.2f} "
             f"er {n['seine_chance']:.2f}")
    w = ""
    warum = z.get("warum") or {}
    if "bewertung" in warum:
        w = "  | bewertung " + ", ".join(
            f"{name} {wert}" for name, wert in warum["bewertung"][:3])
    elif "text" in warum:
        w = "  | " + warum["text"][:90]
    bahn = " ".join(f"{r}{z['bahn'][r]}" for r in "NSWO")
    return (f"Zug {z['zug']:>4} {z['bot'][:12]:<12} {z['pos'][0]:>2},"
            f"{z['pos'][1]:<2} Blick {z['blick']} k={z['kraft']:>5.0f} "
            f"Bahn {bahn}  -> {z.get('aktion','?')}"
            f"{'/' + z['ergebnis'] if z.get('ergebnis') else ''}{g}{w}")


def _spruenge(zeilen: List[dict], wie_viele: int = 3) -> List[dict]:
    mit_delta = []
    for vorher, nachher in zip(zeilen, zeilen[1:]):
        mit_delta.append((nachher["kraft"] - vorher["kraft"], vorher))
    mit_delta.sort(key=lambda p: -p[0])
    return [z for d, z in mit_delta[:wie_viele] if d > 1]


def _diagnose(zeilen: List[dict], tod: dict, vorlauf: int) -> str:
    """Der eine Satz, der die Suche abkuerzt."""
    anfang = max(0, tod["zug"] - vorlauf)
    fenster = [z for z in zeilen if anfang <= z["zug"] <= tod["zug"]]
    hinweise = []

    if tod.get("tod", {}).get("art") == "gefressen":
        letzte = fenster[-1] if fenster else None
        if letzte and letzte["gegner"]:
            g = letzte["gegner"][0]
            if g["blick"] == letzte["blick"] and g["abstand"] <= 2:
                hinweise.append(
                    f"im letzten eigenen Zug ({letzte['zug']}) schaute der Bot "
                    f"in dieselbe Richtung wie {g['name']} auf Abstand "
                    f"{g['abstand']} - das ist der Ruecken, und {g['name']} "
                    f"gewann damit mit {g['seine_chance']:.0%}")

    eigener = [z for z in fenster if z.get("aktion") == "gezogen"
               and z["gegner"] and z["gegner"][0]["abstand"] == 1
               and z["gegner"][0]["meine_chance"] < 0.5]
    if eigener:
        z = eigener[-1]
        hinweise.append(
            f"in Zug {z['zug']} wurde ein Angriff mit nur "
            f"{z['gegner'][0]['meine_chance']:.0%} Siegchance begonnen")

    bedroht = [z for z in fenster
               if z["gegner"] and z["gegner"][0]["seine_chance"] > 0.8]
    if len(bedroht) >= 2:
        hinweise.append(
            f"die Gefahr war {len(bedroht)} Zuege lang sichtbar "
            f"(der Gegner haette mit ueber 80 % gewonnen), bevor es passierte")

    ruecken = [z for z in fenster if z["gegner"]
               and z["gegner"][0]["abstand"] <= 2
               and z["gegner"][0]["blick"] == z["blick"]]
    if ruecken:
        zug_wort = "Zug" if len(ruecken) == 1 else "Zuegen"
        hinweise.append(
            f"in {len(ruecken)} {zug_wort} zeigte der Bot einem nahen Gegner "
            f"den Ruecken - das druckt dessen Chance auf ueber 90 %")

    return "; ".join(hinweise) + "." if hinweise else ""
