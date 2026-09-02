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
