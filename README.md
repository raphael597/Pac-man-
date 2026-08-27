# ThoresT — Pacman-Bot

Ein Bot für das Pacman-Spiel aus dem Unterricht. `Pacman.py` ist die Engine
des Lehrers, unverändert, plus unser `ThoresT`. Das Original-Notebook läuft
damit ohne Anpassung.

```bash
python Pacman.py                 # Selbsttest: eine Partie, Ergebnis, Rechenzeit
jupyter notebook PacmanTest.ipynb
python -m unittest discover -s superpac/tests -t .   # 128 Tests
```

## Was der Bot kann

40 Partien je Zeile auf der echten Engine. Bei sechs gleich starken Spielern
wären 16.7% fair.

| Gegner | ThoresT | harvester | sweeper |
|---|---|---|---|
| 5× Zufallsbot (Lehrer) | 90.0% · Stärke **93.9** | 92.5% · 76.5 | 80.0% · 73.5 |
| 5× harvester | **50.0%** · 67.8 | 12.5% · 36.6 | 27.5% · 44.0 |
| 5× sweeper | **37.5%** · 62.6 | 25.0% · 58.9 | 15.0% · 35.3 |
| gemischt | **25.0%** · 53.5 | 15.0% · 47.9 | 22.5% · 48.7 |
| 5× hunter | 27.5% · 56.3 | 30.0% · 54.9 | **50.0%** · 68.9 |

Gegen fünf Jäger ist der stumpfe `sweeper` besser als wir — das ist ein
gemessener Zielkonflikt, kein Versehen, und in `docs/ERGEBNISSE.md` mit den
Zahlen belegt.

## Die drei Regeln, die das Spiel entscheiden

Alles aus `Pacman._Move` gelesen, nicht angenommen.

**1. Drehen kostet einen ganzen Zug.** `TurnOrMoveOrStill` macht *entweder*
drehen *oder* gehen *oder* stehen. Eine lange gerade Strecke durch Kohl ist
darum die billigste Stärke auf dem Brett — der Bot plant in Bahnen, nicht in
Wegen. (Es gibt auch keine Wände: das Brett ist ein Torus, `Wall` wird nie
erzeugt.)

**2. Der Winkel entscheidet jeden Kampf.** `z = meine + seine Richtung` legt
fest, mit wieviel der Verteidiger zählt:

| Winkel | Verteidiger | Angreifer gewinnt (gleiche Stärke) |
|---|---|---|
| frontal | `s` | 50.0% |
| quer | `s/5` | 83.3% |
| **von hinten** | `s/10` | **90.9%** |

Also: von hinten angreifen. Und rückwärts gelesen ist es die Verteidigung —
die *eigene* Blickrichtung setzt die Chance des Angreifers, dem Angreifer
entgegenzuschauen drückt sie von 91% auf 50%.

**3. Sterben setzt den Punktestand nicht auf null.** Die Engine behält die
Stärke des Verlierers, sie beendet nur sein Mitspielen. Damit wird aus

```
angreifen = p·(a + s + F) + (1−p)·a        nicht = a + F
```

nach Einsetzen von `p = a/(a + s·f)` schlicht:

```
angreifen   ⟺   F < a / f
```

Die Stärke des Ziels **kürzt sich heraus** — der Winkel entscheidet *ob* man
zuschlägt, die Größe nur *wieviel* man gewinnt. Und `f = 1` (frontal) heißt
`F < a`: spät im Spiel, wenn kaum noch Ernte übrig ist, wird der frontale
Angriff richtig.

## Warum es zwei Spielhälften gibt

Sechs Spieler räumen ein 15×15-Brett bis etwa Zug 55 leer. Danach gibt es
keinen Kohl mehr — Stärke kommt nur noch von anderen Spielern.

Genau ein Ausdruck regelt den Übergang: `F`, die erwartete Resternte. Er
steuert die Angriffsschwelle *und* die Gewichtung des Jagdfelds. Die erste
Version hatte dieses Tor nur an der ersten Stelle und jagte ab Zug 1 — das
kostete ein Drittel der Siegrate.

## Aufbau

```
Pacman.py                  Engine des Lehrers + ThoresT (das Abgabefile)
teacher/                   Original-Dateien, unangetastet
superpac/pacman/
  rules.py                 Regeln, Zelle für Zelle gegen die Engine geprüft
  perception.py            Brett einlesen (0.03 ms)
  model.py                 Verhaltensmodell je Gegner
  agent.py                 Planer: Strahlsuche über Drehen/Gehen/Stehen
  opponents.py             vier Spar-Gegner, stärker als die Zufallsbots
  arena.py                 fährt die echte Field-Klasse
  tuning.py                Gewichtssuche
superpac/tests/            128 Tests
scripts/                   build_pacman.py, tune_thorest.py, final_bench.py,
                           thorest_holdout.py
docs/SPIEL.md              vollständige Regelanalyse
docs/ERGEBNISSE.md         alle Messungen, auch die Fehlschläge
```

## Ein Wort zur Messerei

Drei Fehler in diesem Bot wurden nicht durch Nachdenken gefunden, sondern
durch Messen — und zwei davon sahen beim Lesen des Codes völlig richtig aus:

* Der Bot stand **45 Züge lang still**, weil das Jagdfeld nur vier Felder
  weit reichte und das Brett ab Zug 55 leer ist.
* Die erste Korrektur machte es **schlechter** (33% → 21%), weil er nun ab
  Zug 1 jagte statt zu ernten.
* Ein Gewicht von 1.05 statt 1.0 machte **liegenden Kohl wertvoller als
  gegessenen**, um 0.05 Punkte. Der Bot schob das Essen vor sich her und
  verbrachte ein Viertel seiner Züge bewegungslos.

Deshalb steht in `docs/ERGEBNISSE.md` auch, was *nicht* funktioniert hat.

Ebenso bei der Gewichts-Optimierung: einzeln betrachtet war nur die Menge
signifikant, auf der der Champion *ausgewählt* wurde — was nichts beweist.
Erst das Zusammenfassen der beiden unabhängigen Mengen (240 Partien je Seite)
ergab +9.6 Punkte bei z = 2.17. Deshalb gehen die getunten Gewichte rein.

## Vorgeschichte

Das Repository war zu Projektbeginn leer — keine Engine, keine Regeln. Der
erste Teil des Projekts baute deshalb eine Spiel-Engine mit
Laufzeit-API-Erkennung und einem allgemeinen Gegnermodell für ein *unbekanntes*
Gitterspiel. Als die echten Dateien kamen, stellte sich das Spiel als
deutlich anders heraus (keine Wände, Drehen kostet einen Zug, Kämpfe sind
Wahrscheinlichkeiten statt beidseitigem Tod), also wurde `superpac/pacman/`
gezielt für das echte Spiel gebaut.

Der ältere Teil bleibt liegen: `docs/README_generic_engine.md`,
`docs/GAME_API.md`, `docs/RESULTS.md`, `docs/ROADMAP.md`. Die Messwerkzeuge
von dort — getrennte Gegnerpopulationen, faire Duellharnische, ehrliche
Konfidenzintervalle — sind genau die, mit denen dieser Bot getestet wurde.
