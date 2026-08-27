# Das echte Spiel — Regelanalyse

Alles hier ist aus `teacher/Pacman_original.py` **gelesen**, nicht angenommen.
Jede Konstante steht hier, weil `Pacman._Move` sie benutzt.

## Was das Spiel ist

* **Ein Torus, keine Wände.** `Position._PeriodicBoundary` wickelt beide
  Achsen. Die Klasse `Wall` existiert, aber `Field.__init__` erzeugt nie eine.
  Es gibt also keine Wegfindung — Entfernungen sind toroidales Manhattan.
* **Jedes Feld startet als Kohl.** 15×15 = 225 Kohl, sechs Spieler.
* **Ein Zug ist Drehen ODER Gehen ODER Stehen.** `TurnOrMoveOrStill` macht
  genau eins davon. Eine Drehung kostet einen ganzen Zug und bringt nichts.
  Deshalb ist eine lange gerade Strecke durch Kohl die billigste Stärke auf
  dem Brett, und deshalb ist die Blickrichtung Teil des Zustands.
* **Feste Zugreihenfolge**, `for pacman in field.pacmans`, und `ThoresT` steht
  als letztes in der Liste. Wenn wir dran sind, haben alle anderen ihren Zug
  in dieser Runde schon gemacht.
* **Punkte = `strength`.** Kohl gibt +1. Ein Sieg im Kampf gibt die volle
  Stärke des Verlierers.

## Die Regel, die alles entscheidet

```python
z = self.direction + fieldentry.direction
if   z == (0,0):                    b = s        # frontal
elif abs(z.x)==1 and abs(z.y)==1:   b = s/5      # quer
else:                               b = s/10     # von hinten
P(Angreifer gewinnt) = a / (a + b)
```

Bei gleicher Stärke:

| Winkel | Verteidiger zählt als | Angreifer gewinnt |
|---|---|---|
| frontal (Ziel schaut mich an) | `s` | **50.0%** |
| quer | `s/5` | 83.3% |
| von hinten (Ziel läuft weg) | `s/10` | **90.9%** |

Zwei Folgerungen, und beide sind die halbe Strategie:

**Angriff.** Wer in dieselbe Richtung läuft wie ich — den greife ich von
hinten an — verteidigt mit einem Zehntel seiner Stärke.

**Verteidigung.** Man kann sich nicht wehren, aber die *eigene Blickrichtung*
setzt das `b` des Angreifers. Dem Angreifer entgegenzuschauen drückt seine
Chance von 91% auf 50%. Wegschauen ist der schlimmste Fehler im Spiel.

## Wann lohnt ein Kampf?

Hier ist die naheliegende Herleitung falsch. Verlieren setzt den Punktestand
**nicht** auf null:

```python
else:
    fieldentry.strength += self.strength
    self.alive = False
```

Die eigene Stärke bleibt stehen — verloren geht nur die Fähigkeit,
weiterzuspielen. Mit `F` für die Ernte, die noch vor uns liegt:

```
angreifen   = p * (a + s + F) + (1 - p) * a
nicht       = a + F
```

Das vereinfacht sich zu `p * s > F * (1 - p)`, und mit `p = a/(a + s·f)`
**kürzt sich die Stärke des Ziels vollständig heraus**:

```
angreifen   <=>   F < a / f
```

| Winkel | Schwelle |
|---|---|
| von hinten (`f`=0.1) | `F < 10·a` — praktisch immer |
| quer (`f`=0.2) | `F < 5·a` |
| frontal (`f`=1.0) | `F < 1·a` |

Der frontale Fall ist das Gegenteil dessen, was das „Tod kostet alles"-Modell
sagt: **spät im Spiel ist ein frontaler Angriff richtig**, sobald die
Resternte weniger wert ist als das bereits Gesammelte. Und dass die Stärke des
Ziels herausfällt, heißt: der Winkel entscheidet *ob* man zuschlägt, die
Größe des Ziels nur *wie viel* man gewinnt.

## Die Ökonomie

Serpentine auf 15×15: 14 gerade Züge + Drehung + Zug + Drehung = 17 Züge für
15 Kohl, also 0.88 Kohl/Zug. In 100 Zügen wären das ~88 Stärke.

Aber sechs Spieler holen zusammen mehr als 225 Kohl. Eine echte Partie:

| Zug | Kohl übrig | ThoresT | stärkster Gegner |
|---|---|---|---|
| 0 | 219 | 1 | 1 |
| 20 | 112 | 17 | 20 |
| 40 | 35 | 23 | 37 |
| **55** | **~5** | 25 | 63 |
| 100 | 1 | 25 | 69 |

**Das Brett ist bei Zug ~55 leer.** Die zweite Spielhälfte ist reines Jagen.
Die erste Version des Bots stand dort 45 Züge lang bei Stärke 25, während ein
Gegner sich von 37 auf 69 hochfraß — das war der teuerste Fehler im Projekt
und ist in `docs/ERGEBNISSE.md` festgehalten.

## Was das für den Bot heißt

1. **Früh ernten, gerade laufen.** Drehungen sind teuer.
2. **Ab etwa Zug 50 jagen.** Kohl ist weg, Stärke gibt es nur noch von
   anderen Spielern.
3. **Nie frontal angreifen, solange noch Ernte übrig ist.**
4. **Von hinten angreifen, wo es geht.**
5. **Angreifern entgegenschauen** — halbiert ihre Chance.

Punkte 1 und 2 stehen in Spannung zueinander, und das Verhältnis regelt genau
ein Ausdruck: `F`, die erwartete Resternte. Er steuert sowohl die
Angriffsschwelle als auch die Gewichtung des Jagdfelds. Ohne dieses Tor jagte
der Bot ab Zug 1 und verlor ein Drittel seiner Siegrate.
