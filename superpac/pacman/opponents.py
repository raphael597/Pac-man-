"""Stronger sparring partners than the engine's random default.

The five bots the teacher ships choose uniformly among turn, move and stand
still, which makes them very weak - they walk into walls of their own making
and stand around a third of the time.  Beating them proves almost nothing
about a tournament full of other students' bots.

These are what those bots will plausibly look like: a straight-line harvester
(the obvious good idea, and a strong one), a hunter, a wall-hugging sweeper,
and a cautious bot that keeps its distance.  Each subclasses the engine's own
``Pacman``, so they play by exactly the same rules we do.
"""

from __future__ import annotations

import random
from typing import List, Optional, Tuple

from .rules import (DELTAS, EAST, NORTH, SOUTH, WEST, defence_factor,
                    distance, step, win_probability)


def _direction_objects():
    from Pacman import Direction
    return (Direction.north, Direction.south, Direction.west, Direction.east)


def _decode(direction) -> int:
    return {(0, -1): 0, (0, 1): 1, (-1, 0): 2, (1, 0): 3}.get(
        (direction._x, direction._y), 3)


def _scan(me, facing: int, size: int, cap: int = 12) -> int:
    """Unbroken cabbage in front of ``me`` along ``facing``."""
    from Pacman import Cabbage, Position
    count = 0
    x, y = me.position._x, me.position._y
    for _ in range(cap):
        x, y = step(x, y, facing, size)
        if not isinstance(me._field[Position(x, y)], Cabbage):
            break
        count += 1
    return count


def build_opponents(base_class):
    """Return ``(name, class)`` pairs of sparring bots."""
    from Pacman import Cabbage, Empty, Pacman, Position

    class StraightHarvester(base_class):
        """Eat what is ahead; when the line runs dry, face the longest one.

        The obvious strong strategy in this game, and the one most students
        will land on: turning costs a whole turn, so long straight runs are
        the cheapest strength available.
        """

        logo = "H"

        def __init__(self, p, name, field):
            super().__init__(p, name, field)
            self.logo = "H"

        def TurnOrMoveOrStill(self):
            size = Position.fieldsize
            facing = _decode(self.direction)
            ahead = step(self.position._x, self.position._y, facing, size)
            entry = self._field[Position(*ahead)]
            if isinstance(entry, Cabbage):
                self._Move()
                return
            best, best_run = facing, -1
            for direction in range(4):
                run = _scan(self, direction, size)
                if run > best_run:
                    best, best_run = direction, run
            if best != facing:
                self.direction = _direction_objects()[best]
            elif isinstance(entry, Empty):
                self._Move()

    class Hunter(base_class):
        """Harvest until something weaker is close, then chase it."""

        def __init__(self, p, name, field):
            super().__init__(p, name, field)
            self.logo = "J"

        def TurnOrMoveOrStill(self):
            size = Position.fieldsize
            facing = _decode(self.direction)
            target = None
            best = 99
            for entry in self._field.values():
                if not isinstance(entry, Pacman) or entry is self:
                    continue
                if not getattr(entry, "alive", True):
                    continue
                if entry.strength > self.strength:
                    continue
                d = distance(self.position._x, self.position._y,
                             entry.position._x, entry.position._y, size)
                if d < best:
                    target, best = entry, d
            if target is not None and best <= 5:
                want = _direction_towards(self, target, size)
                if want != facing:
                    self.direction = _direction_objects()[want]
                else:
                    self._Move()
                return
            ahead = step(self.position._x, self.position._y, facing, size)
            if isinstance(self._field[Position(*ahead)], Cabbage):
                self._Move()
            else:
                self.direction = _direction_objects()[random.randrange(4)]

    class Sweeper(base_class):
        """Serpentine: run a line, drop one row, run back.

        A hand-written sweep with no board awareness at all - the control for
        whether reading the board is worth anything.
        """

        def __init__(self, p, name, field):
            super().__init__(p, name, field)
            self.logo = "S"
            self._phase = 0
            self._steps = 0

        def TurnOrMoveOrStill(self):
            size = Position.fieldsize
            facing = _decode(self.direction)
            if self._phase == 0:
                if self._steps >= size - 1:
                    self._steps = 0
                    self._phase = 1
                    self.direction = _direction_objects()[SOUTH]
                    return
                self._steps += 1
                self._Move()
            elif self._phase == 1:
                self._phase = 2
                self._Move()
            else:
                self._phase = 0
                self.direction = _direction_objects()[
                    EAST if facing != EAST else WEST]

    class Cautious(base_class):
        """Harvest, but back off from anything stronger nearby."""

        def __init__(self, p, name, field):
            super().__init__(p, name, field)
            self.logo = "C"

        def TurnOrMoveOrStill(self):
            size = Position.fieldsize
            facing = _decode(self.direction)
            threat = None
            for entry in self._field.values():
                if not isinstance(entry, Pacman) or entry is self:
                    continue
                if not getattr(entry, "alive", True):
                    continue
                if entry.strength <= self.strength:
                    continue
                d = distance(self.position._x, self.position._y,
                             entry.position._x, entry.position._y, size)
                if d <= 3:
                    threat = entry
                    break
            if threat is not None:
                away = _direction_away(self, threat, size)
                if away != facing:
                    self.direction = _direction_objects()[away]
                else:
                    self._Move()
                return
            ahead = step(self.position._x, self.position._y, facing, size)
            if isinstance(self._field[Position(*ahead)], Cabbage):
                self._Move()
            else:
                best, best_run = facing, -1
                for direction in range(4):
                    run = _scan(self, direction, size)
                    if run > best_run:
                        best, best_run = direction, run
                self.direction = _direction_objects()[best]

    return [("harvester", StraightHarvester), ("hunter", Hunter),
            ("sweeper", Sweeper), ("cautious", Cautious)]


def _direction_towards(me, other, size: int) -> int:
    from .rules import direction_towards
    return direction_towards(me.position._x, me.position._y,
                             other.position._x, other.position._y, size)


def _direction_away(me, other, size: int) -> int:
    from .rules import OPPOSITE
    return OPPOSITE[_direction_towards(me, other, size)]


__all__ = ["build_opponents"]
