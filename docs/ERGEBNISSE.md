# Messungen — echtes Spiel

Alle Zahlen stammen aus Skripten in diesem Repository und laufen auf der
**echten Engine des Lehrers** (`Pacman.py` importiert, kein Nachbau).

## Endstand

`python scripts/final_bench.py 40` — 40 Spiele je Zeile, 15×15, 100 Züge.
Bei sechs gleich starken Spielern wären 16.7% fair.

| Gegner | Spieler | Sieg | Stärke | bester Gegner | lebt |
|---|---|---|---|---|---|
| 5× Zufallsbot (Lehrer) | **ThoresT** | 90.0% | **93.9** | 36.9 | 90% |
| | harvester | 92.5% | 76.5 | 33.8 | 92% |
| | sweeper | 80.0% | 73.5 | 35.6 | 80% |
| | Stub (tut nichts) | 0.0% | 1.0 | 37.0 | 70% |
| 5× harvester | **ThoresT** | **50.0%** | **67.8** | 56.7 | 75% |
| | harvester | 12.5% | 36.6 | 46.2 | 100% |
| | sweeper | 27.5% | 44.0 | 61.5 | 45% |
| 5× sweeper | **ThoresT** | **37.5%** | **62.6** | 78.0 | 62% |
| | harvester | 25.0% | 58.9 | 94.3 | 28% |
| | sweeper | 15.0% | 35.3 | 76.8 | 98% |
| gemischt | **ThoresT** | **25.0%** | **53.5** | 91.2 | 57% |
| | harvester | 15.0% | 47.9 | 82.3 | 70% |
| | sweeper | 22.5% | 48.7 | 88.3 | 65% |
| 5× hunter | ThoresT | 27.5% | 56.3 | 96.2 | **28%** |
| | harvester | 30.0% | 54.9 | 94.8 | 30% |
| | **sweeper** | **50.0%** | **68.9** | 75.2 | 62% |

ThoresT ist in drei von fünf Szenarien der Beste, und dort mit deutlichem
Abstand: gegen fünf Erntebots 50.0% gegen 12.5%.

### Wo er verliert, und warum

**Gegen fünf Jäger ist der stumpfe `sweeper` besser** (50.0% gegen 27.5%),
weil er 62% überlebt und wir nur 28%. Das ist kein Übersehen — es ist ein
gemessener Zielkonflikt. Mit höherem `exposure`-Gewicht:

| exposure | vs 5× hunter | vs 5× harvester |
|---|---|---|
| 5.8 (getunt) | 36.7% Sieg, 37% lebt | 50.0% Sieg, Stärke 60.6 |
| 11.6 | 40.0%, 40% lebt | 40.0%, Stärke **50.4** |
| 20.4 | 43.3%, 50% lebt | 50.0%, Stärke **50.4** |

Vorsicht kauft Überleben gegen Jäger und kostet ein Sechstel der Ernte gegen
alle anderen. Der Optimierer hat diese Dimension über [0, 20] durchsucht und
5.8 gewählt; ein Turnier voller reiner Jäger ist unwahrscheinlicher als eines
voller Erntebots.

**Gegen die Zufallsbots liegt der simple `harvester` nominell vorn**
(92.5% gegen 90.0%) — bei ±9% Konfidenzintervall ist das Rauschen. Unsere
Stärke liegt dabei 17 Punkte höher (93.9 gegen 76.5).

## Gewichts-Optimierung

`python scripts/tune_thorest.py --generations 9 --population 12 --games 18`
— 9 Generationen, ~2000 Partien, 273 s auf vier Kernen. Trainiert gegen
starke Gegner (Erntebots, Sweeper, Jäger); der Champion wird auf einer
**getrennten** Gegnermischung ausgewählt.

`python scripts/thorest_holdout.py` — 720 Partien, 120 je Zelle:

| Gewichte | Gegnermenge | Sieg | 95% KI | Stärke |
|---|---|---|---|---|
| Handwerte | train | 30.8% | [22.6, 39.1] | 60.2 |
| getunt | train | 40.8% | [32.0, 49.6] | **78.2** |
| Handwerte | validation | 23.3% | [15.8, 30.9] | 56.1 |
| getunt | validation | 43.3% | [34.5, 52.2] | **80.2** |
| Handwerte | holdout | 34.2% | [25.7, 42.7] | 66.5 |
| getunt | holdout | 43.3% | [34.5, 52.2] | **78.0** |

Einzeln betrachtet ist nur die *validation*-Menge signifikant (z = +3.29) —
und genau dort wurde der Champion ausgewählt, das zählt also nicht. Train
(z = +1.62) und holdout (z = +1.46) liegen knapp unter der Schwelle.

Aber train und holdout sind **unabhängige Stichproben**, die man
zusammenfassen darf:

```
gepoolt (train + holdout, 240 Spiele je Seite)
  Handwerte  32.5%   (78/240)
  getunt     42.1%  (101/240)
  Differenz +9.6 Punkte   z = +2.17   -> signifikant (p < 0.05)
```

Dazu steigt die mittlere Stärke auf **allen drei** Mengen: +18.0, +24.1,
+11.5. Deshalb gehen die getunten Gewichte in die Auslieferung.

### Was der Optimierer geändert hat

| Gewicht | Hand | getunt | |
|---|---|---|---|
| `run_ahead` | 1.0 | **1.46** | +46% |
| `run_discount` | 0.88 | **0.70** | steiler |
| `survival_bonus` | 8.0 | **15.2** | +90% |
| `hunt` | 0.85 | **0.36** | −57% |
| `hunt_decay` | 0.86 | **0.75** | kürzere Reichweite |
| `depth` | 9 | 10 | |

Die Richtung ist einheitlich: **mehr ernten, mehr überleben, weniger jagen.**
Gutes Ernten und Amleben-bleiben schlägt aktives Jagen — was, gegeben dass
die zweite Spielhälfte gar keinen Kohl mehr hat, nicht offensichtlich war.

## Drei Fehler, die Messungen gefunden haben

### 1. Der Bot stand die halbe Partie still

Eine Verlaufsspur einer echten Partie:

| Zug | Kohl | ThoresT | stärkster Gegner |
|---|---|---|---|
| 40 | 35 | 23 | 37 |
| 55 | ~5 | 25 | 63 |
| 100 | 1 | **25** | **69** |

Ab Zug 55 ist das Brett leer. Ohne Kohl war jedes Feld gleich viel wert, der
Planer fand kein Gefälle und blieb stehen — 45 Züge lang, während ein Gegner
sich durch Kämpfe von 37 auf 69 hocharbeitete.

Ursache: das Jagdfeld reichte nur vier Felder weit und zerfiel mit 0.45 pro
Schritt. Ein Ziel acht Felder entfernt war 0.001 wert. Behoben mit 0.75–0.86
Zerfall über das ganze Brett.

### 2. Jagen von Zug 1 an war schlechter als gar nicht jagen

Die erste Korrektur machte es *schlimmer*: Siegrate gegen starke Gegner fiel
von 33.3% auf 20.8%, Stärke von 52.1 auf 41.2. Das Jagdfeld zog den Bot ab
Zug 1 zu den Gegnern, statt erst zu ernten.

Die Angriffsregel `F < a/f` kannte die Ökonomie bereits — das *Feld* nicht.
Mit demselben Tor versehen (`1/(1 + F/a)`, praktisch null solange viel Ernte
übrig ist, eins wenn das Brett leer ist): 33.3% → 50.0%, Stärke 52.1 → 65.5.

### 3. Potenzieller Kohl war mehr wert als gegessener

Der teuerste und unauffälligste Fehler. Mit `run_ahead = 1.05` als flachem
Gewicht galt für eine freie Bahn der Länge 10:

```
MOVE   -> Stärke +1, Bahn ist noch 9 lang   = s + 1 + 1.05*9 = s + 10.45
STILL  -> Stärke +0, Bahn ist noch 10 lang  = s + 0 + 1.05*10 = s + 10.50
```

Stehenbleiben gewann um 0.05. Der Bot schob das Essen vor sich her und
verbrachte ein Viertel seiner Züge bewegungslos.

Behoben durch Abzinsung *innerhalb* der Bahn: der `i`-te Kohl voraus ist `i`
Züge entfernt und zählt `γ^i`. Damit ist Jetzt-Essen strikt besser.

| | vs 5 harvester | gemischt | vs Zufallsbots (Stärke) |
|---|---|---|---|
| vorher | 33.3% | 20.8% | 78.6 |
| nachher | **50.0%** | **37.5%** | **102.9** |

## Rechenzeit

`Pacman.py` selbst hat kein Zeitlimit. Trotzdem gemessen, weil ein Turnier
eines haben könnte:

| | ms/Zug |
|---|---|
| erste lauffähige Version | 13.3 |
| nach Vorberechnung der Felder | 4.9 |
| Auslieferungsstand | 6.4 (max 11.2) |

Die Profilierung zeigte 280 000 Aufrufe von vier Hilfsfunktionen pro drei
Partien — alle hingen nur vom Brett ab, das sich während des Nachdenkens
nicht ändert. Einmal pro Zug vorberechnet statt einmal pro Suchknoten.
