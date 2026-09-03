"""Beispiel-Bot. Kopiervorlage fuer eigene Spieler.

Regeln fuer die Arena:
  * Von ``Pacman`` erben.
  * ``TurnOrMoveOrStill`` ueberschreiben - pro Zug genau *eine* Sache:
    entweder ``self.direction`` setzen (drehen), oder ``self._Move()``
    aufrufen (ziehen), oder nichts tun.
  * Der Rueckgabewert wird ignoriert.

Diese Strategie ist die naheliegende: friss, was vor dir liegt, und wenn
die Bahn leer ist, dreh dich zur laengsten. Sie ist ein ordentlicher
Gegner - und ein guter Massstab dafuer, ob der eigene Bot sein Extra an
Aufwand wert ist.
"""
from Pacman import Cabbage, Direction, Pacman, Position, Wall

RICHTUNGEN = (Direction.north, Direction.south, Direction.west, Direction.east)
DELTA = ((0, -1), (0, 1), (-1, 0), (1, 0))


class GeraderFresser(Pacman):
    def __init__(self, p, name, field):
        super().__init__(p, name, field)
        self.logo = "G"
        self.icon = "icons/Pacman.png"

    def _bahn(self, richtung, weite=10):
        """Wieviel Kohl ununterbrochen in dieser Richtung liegt."""
        x, y = self.position._x, self.position._y
        dx, dy = DELTA[richtung]
        groesse = Position.fieldsize
        zaehler = 0
        for _ in range(weite):
            x, y = (x + dx) % groesse, (y + dy) % groesse
            if not isinstance(self._field[Position(x, y)], Cabbage):
                break
            zaehler += 1
        return zaehler

    def _frei(self, richtung):
        """Steht in dieser Richtung eine Wand?"""
        dx, dy = DELTA[richtung]
        groesse = Position.fieldsize
        ziel = self._field[Position((self.position._x + dx) % groesse,
                                    (self.position._y + dy) % groesse)]
        return not isinstance(ziel, Wall)

    def TurnOrMoveOrStill(self):
        blick = {(0, -1): 0, (0, 1): 1, (-1, 0): 2, (1, 0): 3}[
            (self.direction._x, self.direction._y)]
        if self._bahn(blick) > 0:
            self._Move()
            return
        beste = max(range(4), key=self._bahn)
        if beste != blick and self._bahn(beste) > 0:
            self.direction = RICHTUNGEN[beste]
            return
        # Kein Kohl in Sicht. Die erste Fassung dieses Bots ist hier stur
        # weitergelaufen - und stand damit bis zum Partieende gegen eine
        # Wand, weil _Move gegen eine Wand einfach nichts tut. Die Arena
        # hat das als "94% ohne Wirkung" angezeigt.
        if self._frei(blick):
            self._Move()
        else:
            self.direction = RICHTUNGEN[(blick + 1) % 4]
