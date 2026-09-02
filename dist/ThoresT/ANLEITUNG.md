# ThoresT

Mein Pacman-Bot als eigene Datei. `Pacman.py` in diesem Ordner ist die Engine
unverändert, so wie sie ausgeteilt wurde — daran ist nichts geändert.

## Sofort ausprobieren

```bash
python thorest.py
```

Spielt eine Partie und zeigt das Ergebnis:

```
ThoresT Selbsttest (15x15, 100 Zuege)

  T             103   <-- wir
  Pacman_4       22
  Pacman_3       19  (tot)
  ...
  ThoresT 103 gegen besten Gegner 22  ->  SIEG
  6.38 ms/Zug, maximal 10.34 ms, Fehler: 0
```

## Im eigenen Code benutzen

```python
import Pacman
import thorest          # <- diese Zeile genügt

feld = Pacman.Field(15)
for zug in range(100):
    for spieler in feld.pacmans:
        if spieler.alive:
            spieler.TurnOrMoveOrStill()
print(feld)
```

### Warum reicht der Import?

`Field.__init__` baut den letzten Spieler so:

```python
pacman = ThoresT(pos, f"T", self.field)
```

Diesen Namen sucht Python in den Globalen von **Pacman.py**. Eine Klasse aus
einer anderen Datei steht dort nicht — `Field(15)` würde also weiter den
leeren Stub nehmen, und man wundert sich, warum der Bot nichts tut. Deshalb
trägt `thorest.py` sich beim Import selbst ein.

Wer das lieber ausdrücklich schreibt:

```python
import Pacman, thorest
thorest.install()                    # dasselbe, nur sichtbar
Pacman.ThoresT = thorest.ThoresT     # oder direkt

thorest.uninstall()                  # zurück zum Stub des Lehrers
```

## Die Klasse in Pacman.py einbauen

Falls alles in einer Datei sein soll, liegt unter
`variante_alles_in_einer_datei/Pacman.py` die Engine mit bereits
eingebautem ThoresT. Einfach statt der eigenen `Pacman.py` benutzen — das
Notebook läuft unverändert damit.

## Dateien

| Datei | was drin ist |
|---|---|
| `thorest.py` | **die Klasse** — eigenständig, nur Standardbibliothek |
| `Pacman.py` | Engine des Lehrers, unverändert |
| `PacmanTest.ipynb` | Test-Notebook |
| `beispiel.py` | Minimalbeispiel |
| `variante_alles_in_einer_datei/Pacman.py` | Engine + ThoresT in einer Datei |

Keine Installation, keine Zusatzpakete, Python 3.8+.

---

## Wie der Bot spielt

Alles aus `Pacman._Move` gelesen.

### Drehen kostet einen ganzen Zug

`TurnOrMoveOrStill` macht *entweder* drehen *oder* gehen *oder* stehen. Eine
lange gerade Bahn durch Kohl ist darum die billigste Stärke auf dem Brett.
Der Bot plant in Bahnen, nicht in Wegen. Wände gibt es keine — das Feld ist
ein Torus, `Wall` wird nie erzeugt.

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
`F < a`: spät im Spiel, wenn kaum noch Ernte übrig ist, wird auch der
frontale Angriff richtig.

### Zwei Spielhälften

Sechs Spieler räumen ein 15×15-Brett bis etwa Zug 55 leer. Danach kommt
Stärke nur noch von anderen Spielern. Genau ein Ausdruck regelt den Übergang:
`F`, die erwartete Resternte. Er steuert die Angriffsschwelle *und* wie stark
das Jagdfeld zieht.

### Gegnermodell

Die Aktion eines Gegners lässt sich aus dem Brett exakt zurückrechnen:
Position geändert → gegangen, Blickrichtung geändert → gedreht, nichts →
gestanden. Der Bot führt für jeden Gegner ein eigenes Modell (Häufigkeiten,
Zweier-Folgen, Kontext) und sagt daraus vorher, wer sich als nächstes wohin
bewegt.

---

## Wie stark er ist

40 Partien je Zeile auf der echten Engine. Bei sechs gleich starken Spielern
wären 16.7% fair.

| Gegner | ThoresT | einfacher Ernte-Bot |
|---|---|---|
| 5× Zufallsbot (Original) | 90.0% · Stärke **93.9** | 92.5% · 76.5 |
| 5× Ernte-Bot | **50.0%** · 67.8 | 12.5% · 36.6 |
| 5× Serpentinen-Bot | **37.5%** · 62.6 | 25.0% · 58.9 |
| gemischt | **25.0%** · 53.5 | 15.0% · 47.9 |
| 5× Jäger | 27.5% · 56.3 | 30.0% · 54.9 |

Gegen fünf Jäger ist er nicht der Beste — dort überlebt er nur 28%. Das ist
ein gemessener Zielkonflikt: mehr Vorsicht kauft dort Überleben und kostet
überall sonst ein Sechstel der Ernte.

Rechenzeit: 6.4 ms pro Zug im Schnitt, maximal 11 ms.
