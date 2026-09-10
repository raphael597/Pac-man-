# Pacman-Arena

Lasst eure selbstgebauten Pacman-Bots gegeneinander antreten — auf genau der
Spiel-Engine, die im Unterricht benutzt wird. Am Ende steht eine Tabelle, wer
gewonnen hat, und eine Auswertung, **warum**.

Diese Datei erklärt alles von null an. Wenn ihr noch nie ein Terminal geöffnet
habt, fangt bei „Schritt 1" an.

---

## Was ihr braucht

**Python 3.8 oder neuer.** Sonst nichts. Kein `pip install`, keine Anmeldung,
kein Internet.

Testen, ob Python da ist — Terminal öffnen (siehe Schritt 1) und eingeben:

```
python --version
```

Kommt so etwas wie `Python 3.10.11`, ist alles gut. Kommt eine Fehlermeldung,
probiert `python3 --version` und benutzt dann überall `python3` statt `python`.

---

## Schritt 1: Terminal im richtigen Ordner öffnen

Entpackt die ZIP-Datei irgendwohin. Ihr bekommt einen Ordner `PacmanArena`.

**Windows:** Öffnet den Ordner `PacmanArena` im Explorer. Klickt oben in die
Adressleiste, sodass der Pfad blau markiert ist, tippt `powershell` und drückt
Enter. Es öffnet sich ein blaues Fenster, das bereits im richtigen Ordner
steht.

**Mac:** Rechtsklick auf den Ordner `PacmanArena` → „Neuer Terminaltab im
Ordner". Falls das fehlt: Terminal öffnen, `cd ` eintippen (mit Leerzeichen am
Ende), den Ordner ins Fenster ziehen, Enter.

**Linux:** Rechtsklick in den Ordner → „Im Terminal öffnen".

Prüfen, ob ihr richtig steht:

```
python arena/freundschaftsarena.py --help
```

Kommt eine Liste von Optionen, seid ihr im richtigen Ordner. Kommt
`No such file or directory`, seid ihr es nicht.

---

## Schritt 2: Der erste Lauf

```
python arena/freundschaftsarena.py --partien 20 --fueller 4 --grafisch
```

Das spielt 20 Partien und öffnet danach eine Seite im Browser:

* oben die **Tabelle** über alle 20 Partien
* darunter **eine Partie zum Abspielen**, Zug für Zug, mit Schieberegler
* darunter der **Stärkeverlauf** und eine Karte je Bot

Es entsteht dabei die Datei `arena_turnier.html` im Ordner. Die könnt ihr
verschicken — sie funktioniert überall, auch ohne Python.

> Öffnet der Browser sich nicht von selbst, tippt `start arena_turnier.html`
> (Windows) bzw. `open arena_turnier.html` (Mac), oder klickt die Datei im
> Explorer doppelt an.

---

## Schritt 3: Euren eigenen Bot einbauen

Legt eure `.py`-Datei in den Ordner **`arena/bots/`**. Mehr nicht. Jede Klasse
darin, die von `Pacman` erbt, tritt beim nächsten Lauf automatisch an.

Zwei liegen schon drin:

| Datei | |
|---|---|
| `beispiel_gerader_fresser.py` | Kopiervorlage, einfache Strategie |
| `ClaudeEndboss.py` | ein sehr starker Bot, als Maßstab |

### Das kleinstmögliche Beispiel

```python
from Pacman import Pacman, Direction

class MeinBot(Pacman):
    def TurnOrMoveOrStill(self):
        self._Move()          # läuft immer geradeaus
```

Speichern als `arena/bots/mein_bot.py`, Arena starten — er ist dabei.

### Die drei Regeln der Engine

1. Eure Klasse muss von `Pacman` erben.
2. Ihr überschreibt `TurnOrMoveOrStill`. Pro Zug genau **eine** Sache:
   * `self.direction = Direction.north` — drehen
   * `self._Move()` — einen Schritt in Blickrichtung
   * gar nichts — stehenbleiben
3. Der Rückgabewert wird ignoriert.

**Drehen kostet einen ganzen Zug.** Das ist die wichtigste Regel im Spiel: Wer
sich viel dreht, frisst wenig.

### Was ihr abfragen könnt

```python
self.position._x, self.position._y    # wo ihr steht
self.direction                        # wohin ihr schaut
self.strength                         # eure Stärke
self._field[Position(x, y)]           # was auf einem Feld liegt
Position.fieldsize                    # Kantenlänge des Bretts
```

Was auf einem Feld liegen kann: `Cabbage` (Kohl, macht stärker), `Empty`,
`Wall`, oder ein `Pacman` (ein Gegner). Prüfen mit `isinstance`:

```python
from Pacman import Cabbage, Position
ziel = self._field[Position(x, y)]
if isinstance(ziel, Cabbage):
    ...
```

**Das Brett ist ein Torus** — wer rechts hinausläuft, kommt links wieder
herein. Rechnet Koordinaten deshalb immer mit `% Position.fieldsize`.

---

## Alle Befehle

### Turnier spielen

```
python arena/freundschaftsarena.py --partien 20 --fueller 4
```

Tabelle im Terminal, danach eine Diagnose je Bot.

```
python arena/freundschaftsarena.py --partien 20 --fueller 4 --grafisch
```

Dasselbe, zusätzlich als Seite im Browser.

```
python arena/freundschaftsarena.py --partien 200 --fueller 14
```

**Auf Turniergröße.** Wenn in der Klasse rund 15 Bots antreten, sagt eine
Sechser-Runde wenig: Auf dem Brett kommen dann statt 32 nur noch 13 Kohl auf
jeden Spieler. Wer auf lange Fressbahnen gebaut hat, findet keine mehr.

### Zuschauen

```
python arena/freundschaftsarena.py --partien 1 --replay partie.html
```

Schreibt eine HTML-Datei zum Abspielen — ohne den Browser zu öffnen.

```
python arena/freundschaftsarena.py --replay-saat 7 --grafisch
```

Zeigt unten gezielt Partie Nummer 7 statt der ersten. Nützlich, wenn ihr
sehen wollt, wie genau euer Bot in *der einen* Partie verloren hat.

```
python arena/freundschaftsarena.py --fenster --fueller 4 --fps 6
```

Live im Fenster, wie `PacmanGame.py`. Leertaste hält an, `+` und `-` ändern
das Tempo, Esc schließt. **Braucht `pygame`** — falls es fehlt:
`pip install pygame`.

### Herausfinden, warum ein Bot verloren hat

```
python arena/freundschaftsarena.py --partien 1 --warum bericht.md
```

Schreibt einen kurzen Bericht (~7 KB): zu **jedem Todesfall** die acht Züge
davor, mit der Lage, die jeweils vorlag. So sieht eine Zeile aus:

```
Zug 60 Fueller1 11,2 Blick S k=37 Bahn N0 S0 W0 O0
   -> gedreht/in Zug 61 gefressen von ClaudeEndboss
   | naechster ClaudeEndboss d=1 k=40 Blick S ich 0.90 er 0.92
```

`Bahn N4` heißt vier Kohl am Stück nach Norden. `ich` und `er` sind die
**echten Kampfchancen** der Engine. Oben schauen beide nach Süden — also steht
der Gegner im Rücken und gewinnt mit 92 %.

Der Bericht ist klein genug, um ihn samt eurem Bot-Quelltext einer KI
vorzulegen und zu fragen, was der Bot hätte tun sollen.

```
python arena/freundschaftsarena.py --partien 1 --protokoll zuege.jsonl
```

Dasselbe vollständig, eine Zeile je Zug je Bot, zum Auswerten mit eigenem
Code.

### Nachprüfen, dass die Arena richtig zählt

```
python -m unittest arena.tests.test_arena
```

16 Tests. Müssen alle grün sein.

---

## Die Ausgabe lesen

```
Spieler          staerkster   allein uebrig   lebt  Staerke  Leerlauf  ms/Zug
ClaudeEndboss   50.0% [30%,70%]      30.0%     60%     90.0        0%    6.40
```

| Spalte | Bedeutung |
|---|---|
| **stärkster** | Anteil der Partien, in denen der Bot am Ende die höchste Stärke hatte |
| `[30%,70%]` | Konfidenzintervall — dazu unten mehr, es ist wichtiger als die Zahl davor |
| **allein übrig** | Anteil der Partien, die er als Letzter überlebt hat. Das ist die eigentliche Siegbedingung |
| **lebt** | Anteil, in dem er das Ende erlebt hat |
| **Stärke** | Durchschnitt am Partieende |
| **Leerlauf** | Züge ohne jede Wirkung — **die wichtigste Zahl für die Fehlersuche** |
| **ms/Zug** | Rechenzeit je Entscheidung |

### Die drei Zahlen, die Fehler verraten

**`Leerlauf` über 15 %** — Züge, in denen sich weder Position noch
Blickrichtung geändert haben: stehengeblieben, gegen eine Wand gelaufen, oder
in die Richtung gedreht, in die der Bot schon schaute. Jeder davon ist ein
geschenkter Zug. Der Beispiel-Bot stand in seiner ersten Fassung bei **94 %** —
er lief bis zum Partieende gegen eine Wand, weil `_Move()` gegen eine Wand
einfach nichts tut. Ohne diese Spalte fällt so etwas nie auf.

**`Angriffe gewonnen` unter 50 %** — der Bot greift zu oft von vorne an. Die
Engine rechnet `a / (a + b)`, wobei die Stärke des Verteidigers geteilt wird:

| Angriff | Teiler | eure Chance bei gleicher Stärke |
|---|---|---|
| von hinten | 10 | **91 %** |
| von der Seite | 5 | 83 % |
| von vorne | 1 | 50 % |

**`davon aus Kämpfen` bei 0 %** — die zweite Spielhälfte hat keinen Kohl mehr.
Ein Bot, der dann nicht kämpft, hört ab der Mitte auf zu wachsen.

Und einer, den man leicht übersieht: **`verteidigt`**. Wer angegriffen wird und
gewinnt, erbt die **volle** Stärke des Angreifers. Das ist der schnellste Weg
nach oben — und man kann ihn nicht planen, nur wahrscheinlicher machen, indem
man Stärkeren nicht den Rücken zudreht.

---

## Wie viele Partien braucht man?

Die unbequemste Frage, und die wichtigste.

| Partien | Genauigkeit einer Quote |
|---|---|
| 20 | **±21 Punkte** |
| 100 | ±9 Punkte |
| 400 | ±5 Punkte |
| 2000 | ±2 Punkte |

Bei 20 Partien kann ein Bot mit 40 % echter Stärke leicht als 60 % erscheinen.
**Wer nach 20 Partien einen Sieger ausruft, misst Rauschen.**

Für „ist meine Änderung besser?" fangt bei **200 Partien** an — und lasst beide
Fassungen mit derselben `--saat` laufen, damit sie dieselben Bretter sehen. Das
allein macht den Vergleich rund viermal so aussagekräftig, weil die Unterschiede
zwischen den Brettern herausfallen.

---

## Wenn etwas nicht klappt

**`unrecognized arguments: --grafisch`**
Ihr habt eine ältere Fassung der Arena. Ersetzt den ganzen `PacmanArena`-Ordner
durch den neuen. Bis dahin tut es `--replay partie.html`.

**`No such file or directory: arena/freundschaftsarena.py`**
Das Terminal steht im falschen Ordner. Siehe Schritt 1. Mit `dir` (Windows)
bzw. `ls` (Mac/Linux) prüfen: Ihr müsst `arena` und `Pacman.py` sehen.

**`ModuleNotFoundError: No module named 'pygame'`**
Nur `--fenster` braucht pygame. Entweder `pip install pygame`, oder statt
dessen `--grafisch` benutzen — das braucht nichts.

**Mein Bot taucht nicht in der Tabelle auf**
Die Arena meldet beim Start, was sie gefunden hat („gefunden: MeinBot").
Fehlt er: Erbt die Klasse wirklich von `Pacman`? Liegt die Datei in
`arena/bots/`? Beginnt der Dateiname mit `_`? Solche werden übersprungen.

**`!! meinbot.py laesst sich nicht laden: ...`**
Ein Fehler in eurer Datei. Die Meldung dahinter sagt welcher. Das Turnier läuft
ohne euch weiter — eine kaputte Datei soll nicht alle anderen blockieren.

**Der Bot stürzt mitten im Spiel ab**
Dann steht `FEHLER` hinter ihm in der Tabelle. Die Arena fängt das ab und
zählt den Zug als verloren, damit die anderen weiterspielen können.

---

## Alle Optionen auf einen Blick

| Option | Standard | |
|---|---|---|
| `--partien N` | 20 | wie viele Partien |
| `--fueller N` | 0 | zusätzliche Gegner, die nicht würfeln |
| `--saat N` | 1 | Zufallsstart; gleiche Saat = exakt gleiche Partien |
| `--grenze N` | 1500 | Zuglimit (die Engine selbst hat keines) |
| `--feldgroesse N` | 15 | Kantenlänge des Bretts |
| `--ohne-waende` | | ohne die sechs Wände aus `PacmanGame.py` |
| `--ordner PFAD` | `arena/bots` | wo die Bot-Dateien liegen |
| `--grafisch` | | Turnier + Replay als HTML, öffnet den Browser |
| `--replay DATEI` | | dasselbe, ohne den Browser zu öffnen |
| `--replay-saat N` | `--saat` | welche Partie unten gezeigt wird |
| `--fenster` | | live im pygame-Fenster |
| `--fps N` | 12 | Tempo im Fenster |
| `--warum DATEI` | | Bericht zu jedem Todesfall (Markdown) |
| `--protokoll DATEI` | | jeder Zug jedes Bots (JSONL) |
| `--bericht DATEI` | | alle Partien als Rohdaten (JSON) |
| `--nur-tabelle` | | ohne die ausführliche Diagnose |

Jederzeit abrufbar mit:

```
python arena/freundschaftsarena.py --help
```

---

## Über die Füllspieler

`--fueller N` erzeugt N Gegner, die **nicht würfeln**. Das ist Absicht: Der
Zufallsbot der Engine trifft in der Hälfte seiner Züge gar keine Entscheidung,
und gegen den zu gewinnen sagt fast nichts über die eigene Strategie.

Die Füller hier fressen, was vor ihnen liegt, weichen Stärkeren aus und laufen
nicht gegen Wände. Jeder bekommt eine andere „Stufe" zwischen 0 und 1, die
steuert, wie oft er sich die längste Kohlbahn sucht statt einfach
weiterzulaufen — so besteht das Feld nicht aus einer Meinung in fünffacher
Ausfertigung.

---

## Ein Hinweis zur Sicherheit

Die Dateien in `arena/bots/` werden ganz normal ausgeführt, mit allen Rechten,
die das Skript hat. Legt nur Dateien hinein, deren Herkunft ihr kennt.

---

## Was noch im Ordner liegt

| | |
|---|---|
| `arena/ANLEITUNG.md` | die ausführliche Fassung, mit dem Format des Zugprotokolls |
| `arena/freundschaftsarena.py` | die Arena selbst |
| `arena/protokoll.py` | das Zugprotokoll und der Bericht |
| `arena/tests/` | 16 Tests, die die Buchhaltung prüfen |
| `Pacman.py`, `TRex.py`, `PacmanRenderer.py` | die Engine, unverändert |
| `icons/` | Bilder für die Fensteransicht |
