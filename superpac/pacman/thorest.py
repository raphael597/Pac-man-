"""``ThoresT`` - the tournament player, wired into the teacher's engine."""

from __future__ import annotations

from typing import Optional

from .agent import Brain, Weights
from .rules import MOVE, STILL, is_turn


def direction_objects():
    """The engine's ``Direction`` constants, indexed the way we index them."""
    from Pacman import Direction
    return (Direction.north, Direction.south, Direction.west, Direction.east)


def execute(me, action: int) -> None:
    """Carry out one decided action through the engine's own interface.

    Exactly the three things ``TurnOrMoveOrStill`` is allowed to do: set
    ``direction``, call ``_Move()``, or nothing at all.
    """
    if is_turn(action):
        me.direction = direction_objects()[action]
    elif action == MOVE:
        me._Move()


def build_thorest(base_class, weights: Optional[Weights] = None,
                  total_turns: Optional[int] = None, debug: bool = False,
                  icon: str = "icons/TRex.png"):
    """Make a ``ThoresT`` subclass of the engine's ``Pacman``.

    Built as a factory so the arena can produce variants (different weights,
    debug on or off) without four near-identical class definitions.
    """

    class ThoresT(base_class):
        def __init__(self, p, name, field):
            super().__init__(p, name, field)
            self.logo = "T"
            self.icon = icon      # PacmanRenderer draws this
            from Pacman import Direction
            self.direction = Direction.west
            self.brain = Brain(weights=weights, total_turns=total_turns,
                               debug=debug)

        def TurnOrMoveOrStill(self):
            # The engine calls this and ignores the return value, so anything
            # that escapes here would forfeit the turn - or the match.
            try:
                action = self.brain.decide(self)
            except Exception:
                self.brain.faults += 1
                action = MOVE
            try:
                execute(self, action)
            except Exception:
                self.brain.faults += 1

    ThoresT.__name__ = "ThoresT"
    ThoresT.__qualname__ = "ThoresT"
    return ThoresT


__all__ = ["build_thorest", "execute", "direction_objects"]
