# ClaudeEndboss

Mein Pacman-Bot als eigene Datei — genau wie `TRex.py`. Die Engine-Dateien in
diesem Ordner (`Pacman.py`, `PacmanGame.py`, `PacmanRenderer.py`, `TRex.py`,
`icons/`) sind unverändert.

## Sofort ausprobieren

```bash
python ClaudeEndboss.py      # eine Partie, nur Text
python beispiel.py     # zehn Partien mit Statistik
python PacmanGame.py   # grafisch (braucht pygame)
```

## Einbauen

`ClaudeEndboss` wird wie `TRex` in die Spielerliste eingetragen:

```python
from Pacman import Direction, Field, Pacman
from TRex import TRex
from ClaudeEndboss import ClaudeEndboss          # <- nur diese Zeile dazu

pacmans = [[Pacman, "Pacman1"], [Pacman, "Pacman2"], [Pacman, "Pacman3"],
           [TRex, "Trex1"], [ClaudeEndboss, "ClaudeEndboss"]]        # <- und hier
walls = [[[5, 3], Direction.east, 8], [[5, 4], Direction.south, 3]]
field = Field(15, pacmans, walls)
```

In `PacmanGame.py` sind das genau zwei geänderte Zeilen: der Import oben und
ein Eintrag in `pacmans`.

## Dateien

| Datei | was drin ist |
|---|---|
| `ClaudeEndboss.py` | **die Klasse** — eigenständig, nur Standardbibliothek |
| `Pacman.py`, `PacmanGame.py`, `PacmanRenderer.py`, `TRex.py` | Engine, unverändert |
| `icons/` | Sprites für den Renderer |
| `beispiel.py` | zehn Partien mit Statistik |

Keine Installation, keine Zusatzpakete (außer `pygame` für die grafische
Variante), Python 3.8+.

---

## Wie der Bot spielt

Alles aus `Pacman._Move` gelesen.

### Drehen kostet einen ganzen Zug

`TurnOrMoveOrStill` macht *entweder* drehen *oder* gehen *oder* stehen. Eine
lange gerade Bahn durch Kohl ist darum die billigste Stärke auf dem Brett.
Der Bot plant in Bahnen, nicht in Wegen. Das Feld ist ein Torus — links raus
heißt rechts rein.

### Der Winkel entscheidet jeden Kampf

`z = meine Richtung + seine Richtung` legt fest, mit wieviel der Verteidiger
zählt:

| Winkel | Verteidiger | Angreifer gewinnt bei gleicher Stärke |
|---|---|---|
| frontal (er schaut mich an) | `s` | 50.0% |
| quer | `s/5` | 83.3% |
| **von hinten** (er läuft weg) | `s/10` | **90.9%** |

Also von hinten angreifen. Und rückwärts gelesen ist das die Verteidigung:
die *eigene* Blickrichtung setzt die Chance des Angreifers. Ihm
entgegenzuschauen drückt sie von 91% auf 50% — der Bot dreht sich deshalb
einem Angreifer zu, statt wegzulaufen.

### Sterben kostet nicht alles

Die Engine behält die Stärke des Verlierers, sie beendet nur sein Mitspielen:

```python
else:
    fieldentry.strength += self.strength
    self.alive = False
```

Damit wird aus `angreifen = p·(a+s+F) + (1−p)·a` gegen `nicht = a + F`
nach Einsetzen von `p = a/(a+s·f)` schlicht:

```
angreifen   ⟺   F < a / f          (F = erwartete Resternte)
```

Die Stärke des Ziels **kürzt sich heraus**. Der Winkel entscheidet *ob* man
zuschlägt, die Größe nur *wieviel* man gewinnt. Und `f = 1` (frontal) heißt
`F < a`: wenn kaum noch Ernte übrig ist, wird auch der frontale Angriff
richtig.

### Zwei Spielhälften

Irgendwann ist der Kohl weg. Danach kommt Stärke nur noch von anderen
Spielern. Genau ein Ausdruck regelt den Übergang: `F`, die erwartete
Resternte. Er steuert die Angriffsschwelle *und* wie stark das Jagdfeld zieht.

Weil `PacmanGame` kein Zuglimit hat — es läuft, bis nur noch einer lebt —
ist `F` allein aus dem Brett geschätzt und nicht aus einer Rundenzahl.

### Gegnermodell

Die Aktion eines Gegners lässt sich aus dem Brett exakt zurückrechnen:
Position geändert → gegangen, Blickrichtung geändert → gedreht, nichts →
gestanden. Der Bot führt für jeden Gegner ein eigenes Modell (Häufigkeiten,
Zweier-Folgen, Kontext) und sagt daraus vorher, wer sich als nächstes wohin
bewegt.

Nebenbei: der Standard-Bot der Engine steht nie absichtlich still
(`random.choice(range(2))`), aber von außen sieht man ihn in etwa jedem
achten Zug stillstehen — weil ein Viertel seiner Drehungen die Richtung
wählt, in die er ohnehin schon schaut. Das Modell lernt genau das.

---

## Wie stark er ist

450 Partien auf der echten Engine, drei verschiedene Gegnermischungen:

| Gegnermischung | allein übrig | stärkster am Ende | Stärke |
|---|---|---|---|
| train | 33.3% | 68.0% | 107.7 (bester Gegner 63.1) |
| validation | 54.7% | 66.7% | 126.8 (72.8) |
| holdout *(nie fürs Tuning benutzt)* | 24.0% | 66.7% | 104.1 (65.0) |

Bei sechs gleich starken Spielern wären 16.7% fair.

Rechenzeit: rund 8 ms pro Zug. Die Engine hat kein Zeitlimit.

### Er ist nicht unschlagbar

Das ist wichtig genug, um es hinzuschreiben. Auf der Holdout-Menge steht er in
**24% der Partien allein am Ende** — also verliert er drei von vier. Er ist in
zwei Dritteln der Partien der Stärkste, aber "stärkster" und "überlebt" sind
nicht dasselbe.

Und es gibt Aufstellungen, gegen die ein viel dümmerer Bot besser abschneidet:
gegen fünf reine Jäger schlägt ihn ein Bot, der nichts tut außer stur
Serpentinen zu laufen (50% gegen 27.5%). Mehr Vorsicht würde das beheben und
überall sonst ein Sechstel der Ernte kosten — der Optimierer hat diese
Abwägung durchsucht und sich für die Ernte entschieden.

Der Grund liegt im Spiel selbst: **jeder Kampf ist ein Würfelwurf.** Selbst der
beste Angriff — von hinten, bei doppelter Stärke — geht in einem von zwanzig
Fällen schief, und ein verlorener Kampf beendet die Partie. Bei sechs Spielern
kann kein Bot zuverlässig gewinnen. Was Vorhersage und Planung leisten, ist
die Chancen zu verschieben, nicht die Würfel zu kontrollieren.

### Was die Gewichte gebracht haben

Neu getunt für diese Engine-Version, gemessen gegen die vorherigen Werte:

| | allein übrig |
|---|---|
| alte Gewichte | 12.7% |
| neu getunt | **28.7%** |

+16.0 Punkte über 300 unabhängige Partien, z = +3.42 — das ist deutlich mehr
als Rauschen. Interessant dabei: "stärkster am Ende" ging leicht *zurück*
(78.7% → 68.0% auf der train-Menge). Der Optimierer hat Stärke gegen Überleben
getauscht, und das ist richtig, weil das Spiel endet, wenn nur noch einer lebt.
