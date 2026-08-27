"""Exact rules of the teacher's Pacman game, transcribed from ``Pacman.py``.

Everything in this module is *derived from the engine source*, not assumed.
Where a constant appears here it is because ``Pacman._Move`` uses it.

The game, precisely
-------------------
* ``fieldsize x fieldsize`` torus.  ``Position._PeriodicBoundary`` wraps both
  axes, so there are no edges and no corners to be trapped in.
* **No walls.**  ``Field.__init__`` fills every cell with ``Cabbage`` and
  places the players; the ``Wall`` class exists but is never instantiated.
* One action per turn, and turning is one of them: ``TurnOrMoveOrStill``
  either changes ``self.direction``, **or** calls ``_Move()``, **or** does
  nothing.  You cannot turn and move in the same turn.
* Moving onto ``Cabbage`` adds its strength (1).  Moving onto ``Empty`` gains
  nothing.  Moving onto a ``Pacman`` starts a fight.
* Players act in a fixed order, ``for pacman in field.pacmans``, and our
  ``ThoresT`` is appended last - so when we act, every rival has already
  moved this round.

Combat
------
``a`` is the attacker's full strength.  The defender's effective strength
``b`` depends on the *relative directions*::

    z = attacker.direction + defender.direction

    z == (0, 0)          defender faces us head-on   b = s
    |z.x| == |z.y| == 1  perpendicular               b = s / 5
    otherwise            defender faces away         b = s / 10

``P(attacker wins) = a / (a + b)``, the winner absorbs the loser's *full*
strength, and the loser is removed.

Two consequences drive the whole strategy:

* Attacking something running the **same way you are** - i.e. from behind -
  is ten times easier than attacking it head-on.  At equal strength that is
  90.9% versus 50%.
* You cannot choose to defend, but your *facing* sets the attacker's ``b``.
  Turning to face an incoming attacker cuts their odds from 90.9% to 50%.
"""

from __future__ import annotations

from typing import Dict, Final, Iterable, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------
# Directions - indices match superpac.game.rules for consistency
# --------------------------------------------------------------------------
NORTH: Final[int] = 0
SOUTH: Final[int] = 1
WEST: Final[int] = 2
EAST: Final[int] = 3

#: ``(dx, dy)`` per direction, matching ``Direction`` in the engine.
DELTAS: Final[Tuple[Tuple[int, int], ...]] = ((0, -1), (0, 1), (-1, 0), (1, 0))
DIRECTION_NAMES: Final[Tuple[str, ...]] = ("north", "south", "west", "east")
OPPOSITE: Final[Tuple[int, ...]] = (SOUTH, NORTH, EAST, WEST)

#: Perpendicular pairs, precomputed.
PERPENDICULAR: Final[Tuple[Tuple[int, ...], ...]] = (
    (WEST, EAST), (WEST, EAST), (NORTH, SOUTH), (NORTH, SOUTH),
)

# --------------------------------------------------------------------------
# Actions - what TurnOrMoveOrStill may do
# --------------------------------------------------------------------------
TURN_NORTH: Final[int] = 0
TURN_SOUTH: Final[int] = 1
TURN_WEST: Final[int] = 2
TURN_EAST: Final[int] = 3
MOVE: Final[int] = 4
STILL: Final[int] = 5

N_ACTIONS: Final[int] = 6
ACTION_NAMES: Final[Tuple[str, ...]] = (
    "TURN_N", "TURN_S", "TURN_W", "TURN_E", "MOVE", "STILL")

#: The four turn actions, indexed by the direction they select.
TURN_TO: Final[Tuple[int, ...]] = (TURN_NORTH, TURN_SOUTH, TURN_WEST, TURN_EAST)


def is_turn(action: int) -> bool:
    return action < 4


# --------------------------------------------------------------------------
# Combat
# --------------------------------------------------------------------------
#: ``b`` multipliers, indexed ``[attacker_dir][defender_dir]``.  Built from the
#: engine's own ``z = d_attacker + d_defender`` test rather than restated.
def _build_defence_table() -> Tuple[Tuple[float, ...], ...]:
    table: List[Tuple[float, ...]] = []
    for attacker in range(4):
        row: List[float] = []
        ax, ay = DELTAS[attacker]
        for defender in range(4):
            dx, dy = DELTAS[defender]
            zx, zy = ax + dx, ay + dy
            if zx == 0 and zy == 0:
                row.append(1.0)          # head-on
            elif abs(zx) == 1 and abs(zy) == 1:
                row.append(0.2)          # perpendicular
            else:
                row.append(0.1)          # from behind
        table.append(tuple(row))
    return tuple(table)


DEFENCE_FACTOR: Final[Tuple[Tuple[float, ...], ...]] = _build_defence_table()

HEAD_ON: Final[float] = 1.0
PERPENDICULAR_FACTOR: Final[float] = 0.2
FROM_BEHIND: Final[float] = 0.1


def defence_factor(attacker_dir: int, defender_dir: int) -> float:
    """The multiplier applied to the defender's strength."""
    return DEFENCE_FACTOR[attacker_dir][defender_dir]


def win_probability(attacker_strength: float, defender_strength: float,
                    attacker_dir: int, defender_dir: int) -> float:
    """``P(attacker wins)`` exactly as the engine rolls it."""
    a = attacker_strength
    b = defender_strength * DEFENCE_FACTOR[attacker_dir][defender_dir]
    total = a + b
    return a / total if total > 0 else 1.0


def attack_is_worth_it(my_strength: float, target_strength: float,
                       my_dir: int, target_dir: int,
                       future_value: float) -> bool:
    """Should we take this fight?

    Read the engine carefully before deriving this, because the obvious
    reading is wrong.  Losing an attack does **not** zero our score::

        else:
            fieldentry.strength += self.strength
            self.alive = False

    We keep our strength value; what we lose is the ability to keep playing.
    So with ``F`` for the harvest we still expect to collect while alive::

        attack   = p * (a + s + F) + (1 - p) * a
        decline  = a + F

    which simplifies to ``p * s > F * (1 - p)``, and with
    ``p = a / (a + s*f)`` the target's strength cancels entirely::

        attack  <=>  F < a / f

    * ``f = 0.1`` (from behind):    attack whenever ``F < 10a``
    * ``f = 0.2`` (perpendicular):  attack whenever ``F <  5a``
    * ``f = 1.0`` (head-on):        attack whenever ``F <   a``

    The head-on case is the interesting one, and it is the opposite of what
    the "death costs everything" model predicts. Charging someone head-on is
    a *good* trade late in the match, once the remaining harvest is worth less
    than our current strength - because the downside is only forfeiting that
    remaining harvest, not the score already banked.

    That the target's strength drops out is also worth noticing: a favourable
    angle is favourable regardless of how big the target is. Size decides how
    much we *gain*, not whether to swing.
    """
    factor = DEFENCE_FACTOR[my_dir][target_dir]
    return future_value < my_strength / factor


def expected_strength_after_attack(my_strength: float, target_strength: float,
                                   my_dir: int, target_dir: int) -> float:
    """Expected strength immediately after the fight.

    A loss keeps our strength and ends our turn-taking, so the expectation is
    ``p * (a + s) + (1 - p) * a``, not ``p * (a + s)``.
    """
    p = win_probability(my_strength, target_strength, my_dir, target_dir)
    return p * (my_strength + target_strength) + (1.0 - p) * my_strength


# --------------------------------------------------------------------------
# Torus geometry
# --------------------------------------------------------------------------
def wrap(value: int, size: int) -> int:
    return value % size


def step(x: int, y: int, direction: int, size: int) -> Tuple[int, int]:
    dx, dy = DELTAS[direction]
    return (x + dx) % size, (y + dy) % size


def axis_delta(a: int, b: int, size: int) -> int:
    """Signed shortest offset from ``a`` to ``b`` around the ring."""
    d = (b - a) % size
    return d - size if d > size // 2 else d


def distance(ax: int, ay: int, bx: int, by: int, size: int) -> int:
    """Manhattan distance on the torus - the engine has no walls, so this is
    exact and no search is needed."""
    dx = (bx - ax) % size
    dy = (by - ay) % size
    return min(dx, size - dx) + min(dy, size - dy)


def direction_towards(ax: int, ay: int, bx: int, by: int, size: int) -> int:
    """The single direction that shortens the toroidal distance most."""
    dx = axis_delta(ax, bx, size)
    dy = axis_delta(ay, by, size)
    if abs(dx) >= abs(dy):
        return EAST if dx > 0 else WEST
    return SOUTH if dy > 0 else NORTH


__all__ = [
    "NORTH", "SOUTH", "WEST", "EAST", "DELTAS", "DIRECTION_NAMES", "OPPOSITE",
    "TURN_NORTH", "TURN_SOUTH", "TURN_WEST", "TURN_EAST", "MOVE", "STILL",
    "N_ACTIONS", "ACTION_NAMES", "TURN_TO", "is_turn",
    "DEFENCE_FACTOR", "HEAD_ON", "PERPENDICULAR_FACTOR", "FROM_BEHIND",
    "defence_factor", "win_probability", "attack_is_worth_it",
    "expected_strength_after_attack",
    "wrap", "step", "axis_delta", "distance", "direction_towards",
]
