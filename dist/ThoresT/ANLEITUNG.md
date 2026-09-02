# ThoresT

Mein Pacman-Bot als eigene Datei — genau wie `TRex.py`. Die Engine-Dateien in
diesem Ordner (`Pacman.py`, `PacmanGame.py`, `PacmanRenderer.py`, `TRex.py`,
`icons/`) sind unverändert.

## Sofort ausprobieren

```bash
python ThoresT.py      # eine Partie, nur Text
python beispiel.py     # zehn Partien mit Statistik
python PacmanGame.py   # grafisch (braucht pygame)
```

## Einbauen

`ThoresT` wird wie `TRex` in die Spielerliste eingetragen:

```python
from Pacman import Direction, Field, Pacman
from TRex import TRex
from ThoresT import ThoresT          # <- nur diese Zeile dazu

pacmans = [[Pacman, "Pacman1"], [Pacman, "Pacman2"], [Pacman, "Pacman3"],
           [TRex, "Trex1"], [ThoresT, "ThoresT"]]        # <- und hier
walls = [[[5, 3], Direction.east, 8], [[5, 4], Direction.south, 3]]
field = Field(15, pacmans, walls)
```

In `PacmanGame.py` sind das genau zwei geänderte Zeilen: der Import oben und
ein Eintrag in `pacmans`.

## Dateien

| Datei | was drin ist |
|---|---|
| `ThoresT.py` | **die Klasse** — eigenständig, nur Standardbibliothek |
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

40 Partien je Zeile auf der echten Engine, 15×15 mit Wänden, bis nur noch
einer lebt (oder 400 Züge). Bei sechs gleich starken Spielern wären **16.7%**
fair. „Allein übrig" ist die Siegbedingung von `PacmanGame`; „stärkster"
zählt, wenn die Partie nicht aufgelöst wird.

| Gegner | | allein übrig | stärkster | Stärke |
|---|---|---|---|---|
| **Aufstellung aus PacmanGame.py** | ThoresT | **52.5%** | **52.5%** | **109.5** |
| (3× Pacman, 2× TRex) | Ernte-Bot | 0.0% | 12.5% | 52.0 |
| | Serpentinen-Bot | 0.0% | 17.5% | 36.0 |
| **5× Zufallsbot** | ThoresT | **72.5%** | **72.5%** | **139.8** |
| | Ernte-Bot | 5.0% | 20.0% | 59.2 |
| **5× TRex** | ThoresT | **35.0%** | **60.0%** | **114.5** |
| | Ernte-Bot | 2.5% | 27.5% | 56.4 |
| **5× Ernte-Bot** | ThoresT | **15.0%** | **62.5%** | **89.7** |
| | Ernte-Bot | 0.0% | 10.0% | 27.5 |
| **gemischt stark** | ThoresT | **22.5%** | **65.0%** | **105.2** |
| | Ernte-Bot | 2.5% | 32.5% | 46.9 |

Bester in allen fünf Szenarien, auf beiden Kriterien.

Rechenzeit: rund 7 ms pro Zug.

### Die Gewichte wurden für diese Engine neu gesucht

Die vorherige Version war für die alte Engine getunt (100 Züge, keine Wände,
feste Reihenfolge). Auf der neuen ist der Unterschied groß — gemessen über
288 Partien auf zwei Gegnermengen, die die Optimierung nicht zur Auswahl
benutzt hat:

| Gewichte | allein übrig |
|---|---|
| alte (für 100-Zug-Spiel) | 3.5% |
| **neue** | **29.9%** |

+26.4 Punkte, z = 6.0.

Bemerkenswert: die neuen Gewichte sind im Schnitt *schwächer* (125 statt 134)
und seltener der Stärkste (68% statt 71%) — sie tauschen genau das gegen
Überleben ein. Weil das Spiel endet, sobald einer übrig ist, ist das der
richtige Tausch. Nach dem alten Kriterium optimiert hätte man einen Bot
behalten, der gut erntet und dann stirbt.
