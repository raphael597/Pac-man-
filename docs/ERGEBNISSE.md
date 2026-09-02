# Messungen — echtes Spiel

Alle Zahlen stammen aus Skripten in diesem Repository und laufen auf der
**echten Engine des Lehrers** (`Pacman.py` importiert, kein Nachbau).

## Endstand

`python scripts/grossbenchmark.py --games 400 --variant harvester=@harvester …`
— 12 000 Partien, fünf Spieler auf **identischen Brettern**, sechs
Aufstellungen, 400 Partien je Zelle. Bei sechs gleich starken Spielern wären
16.7% fair.

| über alle sechs Aufstellungen (2400 Partien je Spieler) | ThoresT | sweeper | harvester | hunter | cautious |
|---|---|---|---|---|---|
| stärkster | **65.4%** | 24.2% | 20.1% | 12.4% | 8.2% |
| allein übrig, alle Partien | **32.7%** | 2.4% | 0.3% | 4.4% | 0.1% |
| allein übrig, nur entschiedene | **80.6%** | 22.8% | 3.1% | 29.7% | 1.5% |
| mittlere Stärke | **110.0** | 41.6 | 44.1 | 25.3 | 33.0 |

Weil alle fünf dieselben Bretter spielen, lässt sich das gepaart auswerten:
jede einfache Strategie ist um 28 bis 57 Punkte schlechter, alle p unter
10⁻¹⁵⁰. ThoresT ist in **allen sechs** Aufstellungen der Beste.

### Die Aufstellung des Lehrers, ohne Sparlimit

`PacmanGame.py` ist der Ernstfall und zugleich die einzige der sechs
Aufstellungen, die zuverlässig zu Ende gespielt wird. Eigener Lauf über
1200 Partien mit dem echten Spielende statt eines Zuglimits:

| | ThoresT | fair wären |
|---|---|---|
| stärkster | **68.0%** [65.3, 70.6] | 16.7% |
| allein übrig, alle Partien | **61.7%** [58.9, 64.4] | 16.7% |
| allein übrig, nur entschiedene | **70.9%** [68.1, 73.6] | — |
| unentschieden | 13.0% | — |

### Was diese Messung widerlegt hat

Die vorige Fassung dieser Seite stand auf 40 Partien je Zeile, und zwei ihrer
Aussagen halten nicht:

**„Gegen die Zufallsbots liegt der simple `harvester` nominell vorn"**
(92.5% gegen 90.0%). Mit 400 statt 40 Partien in genau dieser Aufstellung:
ThoresT 65.5%, harvester 20.2%. Der Vorsprung war Rauschen, und er zeigte in
die falsche Richtung.

**„Gegen fünf Jäger ist der stumpfe `sweeper` besser"** (50.0% gegen 27.5%).
In der Jäger-Aufstellung mit 400 Partien: ThoresT 65.8%, sweeper 22.0%.

Beide Behauptungen kamen aus Stichproben, deren Konfidenzintervall breiter
war als der behauptete Unterschied. Das ist kein Ausrutscher gewesen, sondern
der Normalfall bei 40 Partien — siehe unten.

## Wie groß muss eine Messung sein?

Das Konfidenzintervall einer Quote aus 100 Partien ist rund ±10 Punkte. Alle
Zahlen dieses Projekts kamen lange aus 24 bis 176 Partien. Verbesserungen
unter 10 Punkten waren damit schlicht **unsichtbar**, und mehrfach wurde
Rauschen für Fortschritt gehalten und wieder zurückgenommen.

| Partien je Zelle | halbe Intervallbreite bei p ≈ 0.65 |
|---|---|
| 40 | ±14.8 Punkte |
| 100 | ±9.3 |
| 400 | ±4.7 |
| 2400 | ±1.9 |

Zwei Entwurfsentscheidungen des Grossbenchmarks folgen aus Messungen, nicht
aus Bequemlichkeit:

**Gepaarte Bretter.** Alle Varianten spielen dieselben Seeds — gleiche
Startpositionen, gleiche Zugreihenfolge, gleiche Kampfwürfe. Die
Brett-Varianz fällt heraus, ausgewertet wird mit McNemar über die Bretter,
auf denen sich die Varianten unterscheiden. Das kostet rund ein Viertel der
Partien für dieselbe Aussage.

**400 Züge Limit, „stärkster" als Hauptzahl.** Die Engine hat kein Zuglimit;
`PacmanGame.py` läuft, bis nur noch einer lebt. Gegen ausweichende Gegner
passiert das faktisch nie:

| | |
|---|---|
| nach 1500 Zügen entschieden | 44% der Partien |
| Median-Länge | 1500 (= das Limit) |
| Antwort auf „wer ist der stärkste" bei Zug 200 | in **48 von 48** Partien dieselbe wie bei Zug 1500 |

Wer gewinnt, ist also oft gar nicht definiert; wer der stärkste ist, steht
nach 200 Zügen fest. Deshalb ist „stärkster" die Hauptzahl, 400 Züge reichen
dafür, und das bringt die dreifache Zahl Partien pro Rechenzeit. „Allein
übrig" wird trotzdem berichtet, aber in drei Töpfen — gewonnen, verloren,
unentschieden. Eine Partie, die nicht zu Ende gespielt wurde, als Niederlage
zu buchen wäre gelogen.

## Eine Idee, die gemessen und verworfen wurde

`facing_discipline` sollte bestrafen, einem nahen Gegner den Rücken
zuzudrehen: `danger` bepreist nur Gegner, die *schon* auf uns zielen, aber
einer zwei Schritte entfernt braucht einen Zug zum Zielen und einen zum
Ziehen — und unsere Blickrichtung entscheidet dann über seine Chancen (91%
statt 50%). Klingt zwingend.

10 800 Partien, gepaart, zwei Dosierungen:

| | allein übrig | stärkster | unentschieden |
|---|---|---|---|
| ohne | **32.2%** | **65.8%** | 60% |
| Gewicht 6 | 28.7% (−3.6, p = 10⁻⁴) | 65.6% (kein Unterschied) | 64% |
| Gewicht 12 | 26.0% (−6.2, p = 6·10⁻¹¹) | 64.0% (kein Unterschied) | 67% |

Es hilft nicht nur nicht, es **schadet** — und zwar dosisabhängig. Der
Mechanismus steht in der letzten Spalte: der Bot verbringt Züge mit
Umdrehen, mehr Partien laufen ins Limit, und die Stärke bleibt dabei flach
(109.4 / 111.4 / 110.1). Er kauft sich nichts für die verlorene Zeit.

Bei 100 Partien wäre −3.6 Punkte unsichtbar gewesen. Das Gewicht existiert
weiter, steht auf 0.0, und diese Tabelle ist der Grund.

## Fünf Vorwürfe, geprüft

Eine Analyse listete fünf angebliche Schwachstellen. Drei hielten stand,
zwei nicht — und die zwei sind lehrreich, weil sie plausibel klangen.

### Was nicht stimmte

**„Das Gegner-Modell kollabiert bei zufälligem Verhalten, `confidence()`
fällt und der Bot wird defensiv."** `confidence()` existiert, wird vom
ausgelieferten Planer aber **nie aufgerufen** — die einzigen Fundstellen
sind `describe()` (Diagnose) und ein `mean_confidence()`, das nirgends
verwendet wird. Der Planer liest `move_probability()`, eine
Randwahrscheinlichkeit, die gegen einen Zufallsgegner korrekt bei ~1/3
landet.

**„Bei `depth 14` und `beam_width 27` droht ein Timeout, dann fällt er auf
`_greedy_action` zurück."** Gezählt über 4800 Partien: **0 Fehler**, 8.5 ms
im Schnitt, 23 ms Spitze. Die Notfall-Route wurde kein einziges Mal
erreicht.

### Was stimmte: Entfernungen quer durch Wände

Der Bot maß alles in Manhattan-Distanz auf dem Torus. Das war exakt, als
die erste Engine keine Wände hatte; die zweite hat sechs Segmente, 28 von
225 Feldern. Auf einem Brett mit Wänden lügt Manhattan immer in dieselbe
Richtung — zu nah, nie zu weit:

```
(3,4) -> (3,6) mit einer Wand dazwischen:  Manhattan 2, tatsächlich 8
```

Betroffen waren alle drei Wertfelder: Bedrohungsdruck (Flucht vor Gegnern,
die vier Züge brauchten), Jagd-Gradient (zeigte in die Wand) und
Kohl-Dichte (Futter hinter der Wand zählte als Nachbar). Ersetzt durch
Breitensuche über die begehbaren Felder; ohne Wände liefert sie
nachweislich dieselben Zahlen wie vorher.

12 000 Partien, gepaart:

| | allein übrig | stärkster | unentschieden |
|---|---|---|---|
| echte Wege | **41.7%** [39.9, 43.5] | 65.9% | 51% |
| durch die Wand | 32.1% [30.5, 33.8] | 65.8% | 61% |
| | **−9.6 Punkte**, p = 2.5·10⁻²² | kein Unterschied | |

Die größte Einzelverbesserung des Projekts. Nebenbei ein Beleg für den
Messaufbau: der alte Stand landet hier bei 32.1%, ein früherer Lauf mit
völlig anderen Seeds hatte 32.2%.

### Was stimmte, aber nichts brachte

**`facing_trust`** — der Suchbaum hält die Blickrichtung eines Gegners über
14 Plies fest, obwohl der sich einfach umdrehen kann. Der Einwand ist
richtig; die Korrektur bringt nichts: kein Unterschied auf beiden Metriken
(p = 0.63 und 0.10), Punktschätzer leicht negativ. Bleibt auf 1.0.

**`attack_margin`** — der interessanteste Fall. Im ersten Lauf sah
vorsichtigeres Angreifen nach +0.9 Punkten aus, p = 0.036. Aber in dem Lauf
wurden **sechs** Vergleiche gerechnet (3 Varianten × 2 Metriken), und bei
sechs Tests ist ein p von 0.036 genau das, was der Zufall liefert; die
korrigierte Schwelle liegt bei 0.008. Also nicht übernommen, sondern eigens
nachgemessen — 10 800 Partien, Hauptmetrik vorher festgelegt, zwei
Dosierungen:

| | allein übrig | stärkster |
|---|---|---|
| `attack_margin` 0.5 | +0.5% (p = 0.27) | +0.6% (p = 0.14) |
| `attack_margin` 0.7 | +0.2% (p = 0.55) | +0.0% (p = 1.0) |

Nichts davon replizierte. Der p-Wert von 0.036 war ein Artefakt des
Mehrfachvergleichs, wie vermutet. `attack_margin` bleibt bei 0.997.

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
| Auslieferungsstand, gemessen über 4800 Partien | **8.5** (max 23.2) |

Die Profilierung zeigte 280 000 Aufrufe von vier Hilfsfunktionen pro drei
Partien — alle hingen nur vom Brett ab, das sich während des Nachdenkens
nicht ändert. Einmal pro Zug vorberechnet statt einmal pro Suchknoten.

### Wird die Notfall-Route je benutzt?

`Brain.decide` fängt jede Exception ab und fällt auf `_greedy_action`
zurück, eine sehr einfache Logik. Ein naheliegender Verdacht ist, dass der
Bot bei `depth = 14` und `beam_width = 27` unter Last dort landet. Gezählt
über zwei unabhängige Läufe:

| Lauf | Partien | Fehler | ms/Zug ⌀ | max |
|---|---|---|---|---|
| Grossbenchmark | 3600 | **0** | 8.47 | 23.18 |
| Lehrer-Aufstellung | 1200 | **0** | 9.10 | 20.52 |

Kein einziges Mal in 4800 Partien. Bei 23 ms Spitze ist auch kein
plausibles Zeitlimit in Reichweite.
