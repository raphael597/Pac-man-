"""Read the engine's ``field`` dict into a compact snapshot.

The engine hands every Pacman the live ``field`` dictionary, so the board is
fully observable: cell contents, and every rival's position, facing and
strength.  All of that is public game state - it is what ``Pacman._Move``
itself reads to resolve a fight - so using it is playing the game, not
peeking behind it.

What we deliberately do *not* touch: any attribute belonging to another
student's subclass rather than to the engine's ``Pacman``.  Reading a rival's
planner internals would be inspecting their program, which is a different
thing from observing the board.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from .rules import DELTAS, EAST, NORTH, SOUTH, WEST

#: ``(dx, dy) -> direction index``, for decoding the engine's ``Direction``.
_DELTA_TO_DIR: Dict[Tuple[int, int], int] = {d: i for i, d in enumerate(DELTAS)}


def decode_direction(direction: object, default: int = EAST) -> int:
    """Turn the engine's ``Koordinaten`` direction into our index."""
    try:
        return _DELTA_TO_DIR.get((direction._x, direction._y), default)  # type: ignore[attr-defined]
    except AttributeError:
        return default


class RivalView:
    """One rival as seen from the board this turn."""

    __slots__ = ("name", "x", "y", "direction", "strength", "index")

    def __init__(self, name: str, x: int, y: int, direction: int,
                 strength: float, index: int) -> None:
        self.name = name
        self.x = x
        self.y = y
        self.direction = direction
        self.strength = strength
        self.index = index

    @property
    def cell(self) -> Tuple[int, int]:
        return self.x, self.y

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        from .rules import DIRECTION_NAMES
        return (f"<{self.name} at ({self.x},{self.y}) "
                f"{DIRECTION_NAMES[self.direction]} s={self.strength:g}>")


class Snapshot:
    """Everything we can see, in a form the planner can use cheaply."""

    __slots__ = ("size", "cabbage", "rivals", "x", "y", "direction",
                 "strength", "turn", "occupied", "n_cabbage")

    def __init__(self, size: int, cabbage: bytearray, rivals: List[RivalView],
                 x: int, y: int, direction: int, strength: float,
                 turn: int) -> None:
        self.size = size
        self.cabbage = cabbage
        self.rivals = rivals
        self.x = x
        self.y = y
        self.direction = direction
        self.strength = strength
        self.turn = turn
        self.occupied: Dict[Tuple[int, int], RivalView] = {
            (r.x, r.y): r for r in rivals}
        self.n_cabbage = sum(cabbage)

    # ------------------------------------------------------------------
    def has_cabbage(self, x: int, y: int) -> bool:
        return bool(self.cabbage[y * self.size + x])

    def rival_at(self, x: int, y: int) -> Optional[RivalView]:
        return self.occupied.get((x, y))

    @property
    def cell(self) -> Tuple[int, int]:
        return self.x, self.y

    def strongest_rival(self) -> Optional[RivalView]:
        return max(self.rivals, key=lambda r: r.strength) if self.rivals else None

    def rank(self) -> int:
        """0 = we are the strongest player on the board."""
        return sum(1 for r in self.rivals if r.strength > self.strength)

    def __repr__(self) -> str:  # pragma: no cover
        from .rules import DIRECTION_NAMES
        return (f"<Snapshot t={self.turn} me=({self.x},{self.y}) "
                f"{DIRECTION_NAMES[self.direction]} s={self.strength:g} "
                f"cabbage={self.n_cabbage} rivals={len(self.rivals)}>")


def observe(me, turn: int = 0) -> Snapshot:
    """Build a :class:`Snapshot` from ``me._field``.

    One pass over the field dictionary.  On a 20x20 board that is 400 lookups,
    which is nothing next to the search that follows.
    """
    from Pacman import Cabbage, Pacman  # engine classes, resolved at call time

    field = me._field
    size = _field_size(me)
    cabbage = bytearray(size * size)
    rivals: List[RivalView] = []
    index = 0

    for position, entry in field.items():
        if isinstance(entry, Cabbage):
            cabbage[position._y * size + position._x] = 1
        elif isinstance(entry, Pacman) and entry is not me:
            if not getattr(entry, "alive", True):
                continue
            rivals.append(RivalView(
                name=getattr(entry, "name", f"rival_{index}"),
                x=position._x, y=position._y,
                direction=decode_direction(entry.direction),
                strength=float(entry.strength),
                index=index))
            index += 1

    return Snapshot(size=size, cabbage=cabbage, rivals=rivals,
                    x=me.position._x, y=me.position._y,
                    direction=decode_direction(me.direction),
                    strength=float(me.strength), turn=turn)


def _field_size(me) -> int:
    """The board edge length.

    ``Position.fieldsize`` is a *class* attribute the engine sets in
    ``Field.__init__``, so it is authoritative and shared.  Falling back to
    the field's own size keeps us working if that ever stops being true.
    """
    try:
        from Pacman import Position
        size = int(Position.fieldsize)
        if size > 0:
            return size
    except Exception:
        pass
    count = len(me._field)
    size = int(round(count ** 0.5))
    return max(1, size)


__all__ = ["Snapshot", "RivalView", "observe", "decode_direction"]
