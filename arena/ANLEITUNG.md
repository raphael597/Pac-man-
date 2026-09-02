# Freundschaftsarena

Eure Bots gegeneinander, auf der echten Engine des Lehrers, mit einer
Auswertung, aus der man etwas lernen kann.

## Loslegen

```bash
python arena/freundschaftsarena.py --partien 20 --fueller 3
```

Das lädt jede `.py`-Datei aus `arena/bots/`, sucht darin jede Klasse, die
von `Pacman` erbt, und lässt sie antreten. **Ihr müsst nichts anmelden** —
Datei hineinlegen genügt.

## Einen Bot beisteuern

Kopiert `arena/bots/beispiel_gerader_fresser.py` und schreibt eure eigene
Logik hinein. Die Regeln der Engine:

* Von `Pacman` erben.
* `TurnOrMoveOrStill` überschreiben. Pro Zug genau **eine** Sache:
  * `self.direction = Direction.north` — drehen
  * `self._Move()` — ziehen
  * gar nichts — stehenbleiben
* Der Rückgabewert wird ignoriert.

Wichtig: **Drehen kostet einen ganzen Zug.** Wer sich viel dreht, frisst
wenig. Das ist die zentrale Spannung im Spiel.

Euren eigenen ThoresT könnt ihr genauso hineinlegen:

```bash
cp dist/ThoresT/ThoresT.py arena/bots/
```

## Die Optionen

| | |
|---|---|
| `--partien 50` | wie viele Partien (Standard 20) |
| `--fueller 3` | zusätzliche Gegner dazu |
| `--saat 7` | anderer Zufallsstart; gleiche Saat = exakt gleiche Partien |
| `--grenze 400` | Zuglimit — die Engine selbst hat keines |
| `--ohne-waende` | ohne die Wände aus `PacmanGame.py` |
| `--feldgroesse 20` | anderes Brett |
| `--bericht datei.json` | jeden Zug jedes Spielers als JSON mitschreiben |
| `--nur-tabelle` | ohne die ausführliche Diagnose |

### Die Füllspieler

`--fueller N` erzeugt N Gegner, die **nicht** würfeln. Der Zufallsbot der
Engine trifft in der Hälfte seiner Züge gar keine Entscheidung; gegen den
zu gewinnen sagt fast nichts. Die Füller hier fressen, was vor ihnen
liegt, weichen Stärkeren aus und laufen nicht gegen Wände. Jeder bekommt
eine andere „Stufe" zwischen 0 und 1, die steuert, wie oft er sich die
längste Kohlbahn sucht statt einfach weiterzulaufen — so besteht das Feld
nicht aus einer Meinung in fünffacher Ausfertigung.

## Auf der Größe testen, die im Turnier kommt

Wenn im Turnier rund fünfzehn Bots antreten, sagt eine Sechser-Runde wenig:

```bash
python arena/freundschaftsarena.py --partien 200 --fueller 14
```

Bei 15 Spielern ist es ein anderes Spiel. Auf 197 begehbaren Feldern
kommen statt 32 nur noch **13 Kohl auf jeden**. Wer seine Strategie darauf
gebaut hat, in Ruhe lange Bahnen abzufressen, findet keine mehr — und wer
Kämpfe scheut, verhungert, weil ab der Mitte nur noch Gegner Stärke
bringen. Rechenzeit ist dabei kein Problem: gemessen kostet eine Runde mit
15 Spielern **6,99 ms je Zug**, eine mit sechs **7,95 ms**. Bei vollerem
Brett fallen mehr Möglichkeiten weg.

## Wie viele Partien braucht man?

Das ist die wichtigste Frage, und die Antwort ist unbequem:

| Partien | Genauigkeit einer Quote |
|---|---|
| 20 | ±21 Punkte |
| 100 | ±9 Punkte |
| 400 | ±5 Punkte |

Bei 20 Partien kann ein Bot mit 40% echter Stärke leicht als 60% erscheinen.
**Wer nach 20 Partien einen Sieger ausruft, misst Rauschen.** Für ein Duell
„ist meine Änderung besser?" solltet ihr bei 200 Partien anfangen — und mit
derselben `--saat` laufen lassen, damit beide Fassungen dieselben Bretter
sehen.

## Die Partie anschauen

```bash
python arena/freundschaftsarena.py --partien 20 --fueller 3 --replay partie.html
```

Schreibt **eine einzelne HTML-Datei**, die ihr euch gegenseitig schicken
könnt — kein Zubehör, keine zweite Datei. Darin könnt ihr die Partie
abspielen und scrubben (Leertaste, Pfeiltasten), seht den Stärkeverlauf
aller Spieler und darunter die Diagnose je Bot.

Auf dem Brett zeigt die **Größe** eines Punktes die Stärke und der Strich
die **Blickrichtung**. Die ist die wichtigste Einzelinformation im Spiel:
Drehen kostet einen ganzen Zug, und wer von hinten angegriffen wird,
verliert mit 91 %, von vorn nur mit 50 %.

Mit `--replay-saat 7` wählt ihr gezielt eine bestimmte Partie aus — zum
Beispiel die eine, die euer Bot verloren hat.

Der Stärkeverlauf ist der Teil, der am meisten verrät: Man sieht genau den
Zug, in dem eine Partie kippt, weil einer den anderen frisst und sich in
einem einzigen Zug verdoppelt.

## Die Auswertung lesen

Die Arena fasst eure Bots nicht an. Sie schaut vor und nach jedem Zug auf
das Brett und liest ab, was passiert ist — das geht, weil die Engine nur
drei Dinge zulässt und jedes eine andere Spur hinterlässt.

**`Leerlauf`** — Züge, in denen sich weder Position noch Blickrichtung
geändert haben: stehengeblieben, gegen eine Wand gelaufen, oder in die
Richtung gedreht, in die der Bot schon schaute. Jeder davon ist ein
geschenkter Zug. Das ist die Zahl, die am häufigsten einen echten Fehler
aufdeckt. Der Beispiel-Bot in diesem Ordner stand in seiner ersten Fassung
bei **94%** — er lief bis zum Partieende gegen eine Wand, weil `_Move()`
gegen eine Wand einfach nichts tut und er nur dann gedreht hat, wenn er
Kohl sah. Sichtbar wurde das erst hier.

**`davon X% aus Kämpfen`** — die zweite Spielhälfte hat keinen Kohl mehr.
Ein Bot, der hier bei 0% steht, hört ab der Mitte auf zu wachsen.

**`gewonnen`** — unter 50% heißt: zu oft von vorne angegriffen. Die Engine
rechnet `a / (a + b)`, wobei die Stärke des Verteidigers geteilt wird —
durch 1 von vorne, durch 5 von der Seite, durch 10 von hinten. Von hinten
gewinnt ihr also mit 91%, von vorne mit 50%.

**`verteidigt`** — überlebte Angriffe. Wer angegriffen wird und gewinnt,
erbt die **volle** Stärke des Angreifers. Das ist der schnellste Weg nach
oben im Spiel, und man kann ihn nicht planen — nur wahrscheinlicher
machen, indem man Stärkeren nicht den Rücken zudreht.

## Logs herausziehen, um mit einer KI zu verbessern

```bash
python arena/freundschaftsarena.py --partien 1 --saat 11 \
    --warum bericht.md --protokoll zuege.jsonl
```

Zwei Ausgaben, für zwei Zwecke:

**`--warum bericht.md`** ist der kuratierte Bericht — rund 7 KB, also klein
genug, um ihn komplett in eine KI zu kippen. Darin steht zu **jedem
Todesfall** die Vorgeschichte: die acht Züge davor, jeweils mit der Lage,
die vorlag. Dazu ein Satz, was auffällt, und am Ende die Fragen, die man
sinnvoll stellen kann.

**`--protokoll zuege.jsonl`** ist das vollständige Maschinen-Log, eine Zeile
je Zug je Bot, zum Auswerten mit eigenem Code.

### Was in einer Zeile steht

```
Zug 60 Fueller1 11,2 Blick S k=37 Bahn N0 S0 W0 O0
   -> gedreht/in Zug 61 gefressen von ThoresT
   | naechster ThoresT d=1 k=40 Blick S ich 0.90 er 0.92
```

`Bahn N4` heißt vier Kohl am Stück nach Norden. `ich` und `er` sind die
**echten Kampfwahrscheinlichkeiten der Engine** für den Fall, dass es jetzt
zum Kampf käme — sie sagen also, wie gefährlich die aktuelle Blickrichtung
ist. Genau daran liest man einen Tod ab: oben schauen beide nach Süden,
also steht ThoresT im Rücken von Fueller1 und gewinnt mit 92%.

Die Lage wird **von außen abgelesen**, das funktioniert also auch für den
Bot eines Freundes, in den ihr nicht hineinschauen könnt.

### Wenn euer Bot selbst erklären soll, warum

Freiwillig, zwei Formen werden erkannt:

```python
def begruendung(self):
    return "Bahn nach Osten ist 9 lang, Gegner zu schwach zum Ausweichen"
```

oder ein Attribut `brain.last_scores` — ein Dict `Handlung → Bewertung`.
ThoresT nutzt das zweite, im Bericht steht dann pro Zug:

```
| bewertung ziehen 383.71, stehen 363.58, dreh O 67.81
```

Damit sieht man nicht nur *was* der Bot getan hat, sondern wie knapp die
Entscheidung war. Ein Zug, bei dem die beiden besten Handlungen 20 Punkte
auseinander liegen, ist etwas anderes als einer mit 300 Punkten Abstand.

### Was man die KI dann fragt

Der Bericht endet mit vier Fragen, die sich aus den Daten beantworten
lassen — etwa „in welchem Zug war der Tod schon nicht mehr abwendbar" oder
„wurde ein Angriff mit unter 50% Siegchance begonnen". Legt den Bericht und
euren Bot-Quelltext zusammen vor; die Kausalkette steht dann in den Daten
und muss nicht geraten werden.

## Sicherheitshinweis

Die Bot-Dateien werden ganz normal ausgeführt, mit allen Rechten, die das
Skript hat. Legt nur Dateien hinein, deren Herkunft ihr kennt.

## Prüfen, dass die Zahlen stimmen

```bash
python -m unittest arena.tests.test_arena
```

Acht Tests, die die Buchhaltung schließen: jeder Tote hat genau eine
Ursache, jeder verlorene Angriff ist für genau einen anderen eine
erfolgreiche Verteidigung, und die Endstärke geht restlos in Kohl, Beute
und Erbe auf. Der letzte Test hat einen echten Fehler gefunden — die erste
Fassung verbuchte die geerbte Stärke nicht, weil sie im Zug des Angreifers
anfällt.
