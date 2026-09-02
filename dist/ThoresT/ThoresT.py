"""ThoresT - ein Pacman-Bot.

Diese Datei enthaelt die Klasse ``ThoresT`` und alles, was sie zum Spielen
braucht. Sie liegt neben der unveraenderten ``Pacman.py`` und wird genauso
benutzt wie ``TRex.py``.

Benutzung
---------

    from Pacman import Direction, Field, Pacman
    from TRex import TRex
    from ThoresT import ThoresT

    pacmans = [[Pacman, "Pacman1"], [Pacman, "Pacman2"],
               [TRex, "Trex1"], [ThoresT, "ThoresT"]]
    walls = [[[5, 3], Direction.east, 8], [[5, 4], Direction.south, 3]]
    field = Field(15, pacmans, walls)

Fuer ``PacmanGame.py`` genuegt es, ``ThoresT`` zu importieren und in die
``pacmans``-Liste einzutragen.

Wie er spielt
-------------
Das Brett ist ein Torus, es startet voller Kohl, und es gibt Waende. Ein Zug
ist *entweder* drehen *oder* gehen *oder* stehen - nie beides. Eine lange
gerade Bahn durch Kohl ist deshalb die billigste Staerke auf dem Brett, und
der Bot plant in Bahnen statt in Wegen.

Irgendwann ist der Kohl weg. Danach gibt es Staerke nur noch von anderen
Spielern, also stellt er auf Jagen um. Wann genau, entscheidet ein einziger
Ausdruck: ``F``, die erwartete Resternte.

Kaempfe entscheidet der Winkel: wer in dieselbe Richtung laeuft wie ich,
verteidigt mit einem Zehntel seiner Staerke (90.9% statt 50% bei gleicher
Staerke). Also von hinten angreifen - und wenn man selbst angegriffen wird,
dem Angreifer entgegenschauen, das drueckt seine Chance von 91% auf 50%.

Von jedem Gegner fuehrt er ein eigenes Verhaltensmodell. Deren Aktion laesst
sich aus dem Brett exakt zurueckrechnen: Position geaendert -> gegangen,
Blickrichtung geaendert -> gedreht, nichts -> gestanden.

Erzeugt von scripts/build_standalone.py. Nur Standardbibliothek.
Gebaut: 2026-09-02
Gewichte: getunt (results/thorest_weights.json)
"""

import math
import time
from collections import deque
from dataclasses import dataclass, fields, replace
from typing import Deque, Dict, List, Optional, Sequence, Tuple
from typing import Dict, Final, Iterable, List, Optional, Sequence, Tuple
from typing import Dict, List, Optional, Sequence, Tuple

from Pacman import Cabbage, Direction, Empty, Pacman, Position, Wall

# ----------------------------------------------------------------------
# superpac/pacman/rules.py
# ----------------------------------------------------------------------

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

# ----------------------------------------------------------------------
# superpac/pacman/perception.py
# ----------------------------------------------------------------------

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
        return (f"<{self.name} at ({self.x},{self.y}) "
                f"{DIRECTION_NAMES[self.direction]} s={self.strength:g}>")


class Snapshot:
    """Everything we can see, in a form the planner can use cheaply."""

    __slots__ = ("size", "cabbage", "rivals", "x", "y", "direction",
                 "strength", "turn", "occupied", "n_cabbage", "blocked",
                 "has_walls")

    def __init__(self, size: int, cabbage: bytearray, rivals: List[RivalView],
                 x: int, y: int, direction: int, strength: float,
                 turn: int, blocked: Optional[bytearray] = None) -> None:
        self.size = size
        self.cabbage = cabbage
        # ``Field`` never places a Wall today, but the class exists in the
        # engine, so a later version of the exercise plausibly will. Tracking
        # it costs one byte per cell and keeps the planner's model of a move
        # identical to what ``_Move`` actually does.
        self.blocked = blocked if blocked is not None else bytearray(size * size)
        self.has_walls = any(self.blocked)
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

    def is_blocked(self, x: int, y: int) -> bool:
        """A wall refuses the move entirely - ``_Move`` returns without acting."""
        return bool(self.blocked[y * self.size + x])

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
        return (f"<Snapshot t={self.turn} me=({self.x},{self.y}) "
                f"{DIRECTION_NAMES[self.direction]} s={self.strength:g} "
                f"cabbage={self.n_cabbage} rivals={len(self.rivals)}>")


def observe(me, turn: int = 0) -> Snapshot:
    """Build a :class:`Snapshot` from ``me._field``.

    One pass over the field dictionary.  On a 20x20 board that is 400 lookups,
    which is nothing next to the search that follows.
    """

    field = me._field
    size = _field_size(me)
    cabbage = bytearray(size * size)
    blocked = bytearray(size * size)
    rivals: List[RivalView] = []
    index = 0

    for position, entry in field.items():
        if isinstance(entry, Cabbage):
            cabbage[position._y * size + position._x] = 1
        elif isinstance(entry, Wall):
            blocked[position._y * size + position._x] = 1
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
                    strength=float(me.strength), turn=turn, blocked=blocked)


def _field_size(me) -> int:
    """The board edge length.

    ``Position.fieldsize`` is a *class* attribute the engine sets in
    ``Field.__init__``, so it is authoritative and shared.  Falling back to
    the field's own size keeps us working if that ever stops being true.
    """
    try:
        size = int(Position.fieldsize)
        if size > 0:
            return size
    except Exception:
        pass
    count = len(me._field)
    size = int(round(count ** 0.5))
    return max(1, size)

# ----------------------------------------------------------------------
# superpac/pacman/model.py
# ----------------------------------------------------------------------

"""Per-rival behaviour models for the real game's action space.

The engine gives us something unusually good: **a rival's action is exactly
recoverable from the board.** Each player takes one action per round, and the
three kinds leave distinguishable traces:

* position changed  -> it called ``_Move``
* facing changed    -> it turned
* neither           -> it stood still

A surviving Pacman is never displaced by anyone else (the loser of a fight
dies, the winner advances), so a position change can only be its own move.
That makes the observation exact rather than inferred, which is a much better
starting point than the position-only observations the general engine had.

Three models are mixed by fixed-share weighting, so a rival that changes
strategy mid-match can be tracked instead of averaged away:

``FrequencyModel``   what it does overall
``SequenceModel``    what it does given its last two actions
``ContextModel``     what it does given the situation in front of it

The teacher's own ``Pacman`` is uniform 1/3 turn, 1/3 move, 1/3 still, and
the frequency model locks onto that within a couple of dozen turns.  Other
students' bots will not be, which is the point of keeping the other two.
"""




EPS = 1e-9


def infer_action(previous: RivalView, current: RivalView) -> int:
    """Which of the six actions turned ``previous`` into ``current``?"""
    if (current.x, current.y) != (previous.x, previous.y):
        return MOVE
    if current.direction != previous.direction:
        return TURN_TO[current.direction]
    return STILL


def _normalise(weights: Sequence[float]) -> List[float]:
    total = sum(weights)
    if total <= 0:
        return [1.0 / N_ACTIONS] * N_ACTIONS
    return [w / total for w in weights]


class FrequencyModel:
    """Decayed marginal over the six actions."""

    name = "frequency"

    def __init__(self, decay: float = 0.985, prior: float = 0.6) -> None:
        self.counts = [prior] * N_ACTIONS
        self.decay = decay
        self.observations = 0

    def observe(self, snapshot: Snapshot, rival: RivalView, action: int) -> None:
        for i in range(N_ACTIONS):
            self.counts[i] *= self.decay
        self.counts[action] += 1.0
        self.observations += 1

    def predict(self, snapshot: Snapshot, rival: RivalView) -> Optional[List[float]]:
        if self.observations < 3:
            return None
        return _normalise(self.counts)

    def describe(self) -> str:
        p = _normalise(self.counts)
        return " ".join(f"{ACTION_NAMES[i]}={p[i]:.2f}" for i in range(N_ACTIONS))


class SequenceModel:
    """Order-1/2 n-gram over the rival's own action stream."""

    name = "sequence"

    def __init__(self, decay: float = 0.99, prior: float = 0.4) -> None:
        self.tables: List[Dict[Tuple[int, ...], List[float]]] = [{}, {}, {}]
        self.history: Deque[int] = deque(maxlen=2)
        self.prior = prior
        self.decay = decay
        self.observations = 0

    def observe(self, snapshot: Snapshot, rival: RivalView, action: int) -> None:
        history = tuple(self.history)
        for order in range(min(len(history), 2) + 1):
            key = history[len(history) - order:] if order else ()
            row = self.tables[order].setdefault(key, [self.prior] * N_ACTIONS)
            for i in range(N_ACTIONS):
                row[i] *= self.decay
            row[action] += 1.0
        self.history.append(action)
        self.observations += 1

    def predict(self, snapshot: Snapshot, rival: RivalView) -> Optional[List[float]]:
        if self.observations < 6:
            return None
        history = tuple(self.history)
        blended = [0.0] * N_ACTIONS
        total_weight = 0.0
        for order in range(min(len(history), 2), -1, -1):
            key = history[len(history) - order:] if order else ()
            row = self.tables[order].get(key)
            if not row:
                continue
            mass = sum(row)
            trust = min(1.0, mass / (3.0 + 2.0 * order))
            weight = trust * (5.0 ** order)
            for i in range(N_ACTIONS):
                blended[i] += weight * row[i] / mass
            total_weight += weight
        if total_weight <= 0:
            return None
        return _normalise(blended)

    def determinism(self) -> float:
        table = self.tables[2]
        if not table:
            return 0.0
        peak = mass = 0.0
        for row in table.values():
            row_mass = sum(row)
            if row_mass < 2.0:
                continue
            mass += row_mass
            peak += max(row)
        return peak / mass if mass > 0 else 0.0

    def describe(self) -> str:
        return f"order-2 determinism {self.determinism():.2f}"


class ContextModel:
    """What it does given what is in front of it.

    Discretised as ``(cabbage ahead?, player ahead?, cabbage under foot?)``,
    which is coarse on purpose - a fine context fragments the counts far more
    than it sharpens the prediction over a hundred-turn match.
    """

    name = "context"

    def __init__(self, decay: float = 0.99, prior: float = 0.5) -> None:
        self.table: Dict[Tuple[int, int, int], List[float]] = {}
        self.decay = decay
        self.prior = prior
        self.observations = 0

    @staticmethod
    def key(snapshot: Snapshot, rival: RivalView) -> Tuple[int, int, int]:
        ax, ay = step(rival.x, rival.y, rival.direction, snapshot.size)
        ahead_rival = snapshot.rival_at(ax, ay)
        return (1 if snapshot.has_cabbage(ax, ay) else 0,
                1 if ahead_rival is not None else 0,
                1 if snapshot.has_cabbage(rival.x, rival.y) else 0)

    def observe(self, snapshot: Snapshot, rival: RivalView, action: int) -> None:
        row = self.table.setdefault(self.key(snapshot, rival),
                                    [self.prior] * N_ACTIONS)
        for i in range(N_ACTIONS):
            row[i] *= self.decay
        row[action] += 1.0
        self.observations += 1

    def predict(self, snapshot: Snapshot, rival: RivalView) -> Optional[List[float]]:
        row = self.table.get(self.key(snapshot, rival))
        if not row or sum(row) < 3.0:
            return None
        return _normalise(row)

    def describe(self) -> str:
        return f"{len(self.table)} contexts"


class RivalModel:
    """One rival's ensemble, its accuracy record, and its forecast."""

    def __init__(self, name: str, share: float = 0.04, floor: float = 0.005) -> None:
        self.name = name
        self.models = [FrequencyModel(), SequenceModel(), ContextModel()]
        self.weights = [1.0 / len(self.models)] * len(self.models)
        self.share = share
        self.floor = floor
        self.previous: Optional[RivalView] = None
        self.last_prediction: Optional[List[float]] = None
        self.hits: Deque[int] = deque(maxlen=40)
        self.log_losses: Deque[float] = deque(maxlen=60)
        self.observations = 0
        self.actions: Deque[int] = deque(maxlen=120)

    # ------------------------------------------------------------------
    def predict(self, snapshot: Snapshot, rival: RivalView) -> List[float]:
        blended = [0.0] * N_ACTIONS
        total = 0.0
        cache: List[Optional[List[float]]] = []
        for model, weight in zip(self.models, self.weights):
            try:
                distribution = model.predict(snapshot, rival)
            except Exception:
                distribution = None
            cache.append(distribution)
            if distribution is None:
                continue
            for i in range(N_ACTIONS):
                blended[i] += weight * distribution[i]
            total += weight
        self._cache = cache
        if total <= 0:
            # Before any evidence, assume the engine's own default bot: it is
            # what five of the six players on the board actually run.
            prior = [1.0 / 12.0] * 4 + [1.0 / 3.0, 1.0 / 3.0]
            self.last_prediction = prior
            return prior
        prediction = _normalise(blended)
        self.last_prediction = prediction
        return prediction

    # ------------------------------------------------------------------
    def observe(self, snapshot: Snapshot, rival: RivalView, action: int) -> None:
        cache = getattr(self, "_cache", None)
        if cache is None:
            cache = [m.predict(snapshot, rival) for m in self.models]

        if self.last_prediction is not None:
            top = max(range(N_ACTIONS), key=lambda a: self.last_prediction[a])
            self.hits.append(1 if top == action else 0)
            self.log_losses.append(-math.log(max(EPS, self.last_prediction[action])))

        total = 0.0
        for i, distribution in enumerate(cache):
            likelihood = (distribution[action] if distribution is not None
                          else 1.0 / N_ACTIONS)
            self.weights[i] *= (likelihood + self.floor)
            total += self.weights[i]
        n = len(self.models)
        if total <= 0:
            self.weights = [1.0 / n] * n
        else:
            # Fixed share: any model can climb back after a strategy change.
            self.weights = [(1.0 - self.share) * w / total + self.share / n
                            for w in self.weights]

        for model in self.models:
            try:
                model.observe(snapshot, rival, action)
            except Exception:
                pass
        self.actions.append(action)
        self.observations += 1
        self._cache = None

    # ------------------------------------------------------------------
    @property
    def accuracy(self) -> float:
        return sum(self.hits) / len(self.hits) if self.hits else 0.0

    @property
    def log_loss(self) -> float:
        return (sum(self.log_losses) / len(self.log_losses)
                if self.log_losses else math.log(N_ACTIONS))

    def confidence(self) -> float:
        """How much the planner should trust this model."""
        if self.observations < 4:
            return 0.0
        sample = min(1.0, self.observations / 15.0)
        calibration = max(0.0, 1.0 - self.log_loss / math.log(N_ACTIONS))
        return max(0.0, min(1.0, (0.55 * self.accuracy + 0.45 * calibration) * sample))

    def move_probability(self) -> float:
        """``P(this rival advances next turn)`` - the number the threat map needs."""
        if self.last_prediction is None:
            return 1.0 / 3.0
        return self.last_prediction[MOVE]

    def describe(self) -> str:  # pragma: no cover - diagnostics
        best = max(range(len(self.models)), key=lambda i: self.weights[i])
        prediction = self.last_prediction or [0.0] * N_ACTIONS
        top = sorted(range(N_ACTIONS), key=lambda a: -prediction[a])[:3]
        return (f"{self.name}: {self.models[best].name} (w={self.weights[best]:.2f}) "
                f"acc={self.accuracy:.0%} logloss={self.log_loss:.2f} "
                f"conf={self.confidence():.2f} | "
                + ", ".join(f"{ACTION_NAMES[a]} {prediction[a]:.0%}" for a in top))


class RivalRegistry:
    """One :class:`RivalModel` per rival, updated from consecutive snapshots."""

    def __init__(self) -> None:
        self.models: Dict[str, RivalModel] = {}
        self._previous: Dict[str, RivalView] = {}
        self._previous_snapshot: Optional[Snapshot] = None

    def model_for(self, name: str) -> RivalModel:
        model = self.models.get(name)
        if model is None:
            model = RivalModel(name)
            self.models[name] = model
        return model

    # ------------------------------------------------------------------
    def update(self, snapshot: Snapshot) -> None:
        """Learn from what every rival did since our last turn."""
        previous_snapshot = self._previous_snapshot
        seen = set()
        for rival in snapshot.rivals:
            seen.add(rival.name)
            before = self._previous.get(rival.name)
            if before is not None and previous_snapshot is not None:
                action = infer_action(before, rival)
                self.model_for(rival.name).observe(previous_snapshot, before, action)
            self._previous[rival.name] = rival
        for gone in set(self._previous) - seen:
            del self._previous[gone]
        self._previous_snapshot = snapshot

    def predict_all(self, snapshot: Snapshot) -> Dict[str, List[float]]:
        return {r.name: self.model_for(r.name).predict(snapshot, r)
                for r in snapshot.rivals}

    def mean_confidence(self, snapshot: Snapshot) -> float:
        if not snapshot.rivals:
            return 1.0
        return sum(self.model_for(r.name).confidence()
                   for r in snapshot.rivals) / len(snapshot.rivals)

    def describe(self, snapshot: Snapshot) -> str:  # pragma: no cover
        return "\n".join("  " + self.model_for(r.name).describe()
                         for r in snapshot.rivals)

# ----------------------------------------------------------------------
# superpac/pacman/agent.py
# ----------------------------------------------------------------------

"""The brain behind ``ThoresT``.

Per turn: read the board, learn what every rival just did, predict what they
will do next, then search our own action sequences and play the best one.

The search is a beam over ``(position, facing, strength)`` states.  Three
things make this game's search different from a normal grid bot's:

* **Turning costs a whole turn.**  ``TurnOrMoveOrStill`` turns *or* moves, so
  facing is part of the state and a change of heading is a real expense.  A
  long straight run through cabbage is worth far more than the shortest path
  to anywhere.
* **There are no walls**, so there is no pathfinding.  Distances are
  toroidal Manhattan, and the search is about *sequencing*, not routing.
* **Fights are probabilistic and the angle decides them.**  Nodes therefore
  carry ``P(alive)`` and an expected strength, and a branch that dies still
  contributes the score it had banked - because in this engine dying keeps
  your strength, it only stops you earning more.
"""





@dataclass
class Weights:
    """Everything tunable, in one place so the optimiser can search it."""

    run_ahead: float = 1.0
    """Weight on the cabbage lying in an unbroken line in front of us.

    Scaled so it trades against realised strength, and *discounted by how many
    turns away each cabbage is* - see ``run_discount``. Getting this wrong is
    subtle and expensive: with a flat weight above 1.0, a cabbage still on the
    ground was worth more than the same cabbage eaten, so standing still
    outscored moving forward by a hair and the bot procrastinated. It spent a
    quarter of its turns motionless."""
    run_discount: float = 0.88
    """Per-step discount inside the run.

    The ``i``-th cabbage ahead is ``i`` turns away, so it is worth
    ``run_discount ** i``. This is what makes eating now strictly better than
    planning to eat later."""
    density: float = 0.09
    """Cabbage in the neighbourhood - a tie-break when no run is available."""
    hunt: float = 0.85
    """Weight on expected strength from a kill.

    In strength units, so it trades directly against cabbage: 1.0 would mean
    "a kill worth 30 strength is exactly as attractive as 30 cabbages"."""
    hunt_decay: float = 0.86
    """Per-step decay of a distant target's pull.

    Must be gentle. The first version used 0.45 over a four-cell radius, which
    made anything further than a couple of steps worth nothing and left the
    bot with no reason to move at all once the cabbage ran out."""
    exposure: float = 6.0
    """Penalty for standing where a rival can profitably hit us."""
    survival_bonus: float = 8.0
    """Flat bonus for still being alive at the horizon.

    Insurance: the engine prints dead players' strengths, so death may not
    zero the score, but a ranking that puts survivors first is just as
    plausible. This keeps us from trading life for a marginal pellet under
    either reading."""
    discount: float = 0.97
    beam_width: int = 26
    depth: int = 9
    attack_margin: float = 1.0
    """Scales the ``F < a/f`` attack threshold. Above 1 is bolder."""
    harvest_rate: float = 0.85
    """Cabbage per turn we expect to collect while alive - feeds ``F``."""

    def as_vector(self) -> List[float]:
        return [float(getattr(self, f.name)) for f in fields(self)]

    @classmethod
    def from_vector(cls, vector: Sequence[float]) -> "Weights":
        names = [f.name for f in fields(cls)]
        if len(vector) != len(names):
            raise ValueError(f"expected {len(names)} weights, got {len(vector)}")
        kwargs = {}
        for name, value in zip(names, vector):
            declared = cls.__dataclass_fields__[name].type
            kwargs[name] = int(round(value)) if declared == "int" else float(value)
        return cls(**kwargs)

    @classmethod
    def names(cls) -> List[str]:
        return [f.name for f in fields(cls)]

    def with_(self, **kwargs) -> "Weights":
        return replace(self, **kwargs)


DEFAULT_WEIGHTS = Weights()

#: How far ahead the run-length scan looks.  Beyond this the discount has
#: made further cabbage irrelevant anyway.
RUN_CAP = 12


class TurnFields:
    """Per-turn lookup tables.

    Profiling the first working version put 80% of the run time in four
    helpers that were being called once per search node - roughly a thousand
    times a turn - even though every one of them depends only on the board,
    which does not change while we think.  Computing them once and reading
    them back turns the inner loop into array indexing.
    """

    __slots__ = ("size", "density", "pressure", "hunt", "_run", "snapshot",
                 "run_value")

    def __init__(self, snapshot: Snapshot, weights: "Weights",
                 move_probability: Dict[str, float],
                 future: float = 0.0) -> None:
        size = snapshot.size
        self.size = size
        self.snapshot = snapshot
        n = size * size
        cabbage = snapshot.cabbage

        # --- cabbage density, radius 3 diamond -------------------------
        density = [0.0] * n
        offsets = [(dx, dy) for dx in range(-3, 4)
                   for dy in range(abs(dx) - 3, 4 - abs(dx))]
        for y in range(size):
            base = y * size
            for x in range(size):
                total = 0
                for dx, dy in offsets:
                    if cabbage[((y + dy) % size) * size + ((x + dx) % size)]:
                        total += 1
                density[base + x] = float(total)
        self.density = density

        # --- proximity pressure: stamped outward from each rival -------
        pressure = [0.0] * n
        for rival in snapshot.rivals:
            weight = min(3.0, rival.strength / 4.0 + 0.5)
            for dx in range(-3, 4):
                for dy in range(abs(dx) - 3, 4 - abs(dx)):
                    d = abs(dx) + abs(dy)
                    cell = ((rival.y + dy) % size) * size + ((rival.x + dx) % size)
                    pressure[cell] += (0.45 ** d) * weight
        self.pressure = pressure

        # --- hunting value per (facing, cell) --------------------------
        # This is the half of the game that a harvest-only bot loses.  On a
        # 15x15 board six players strip all 225 cabbages by about turn 55,
        # and from then on the *only* source of strength is killing someone.
        # A trace of a real match showed our first version parked at 25 for
        # the last 45 turns while a rival ate its way from 37 to 69.
        #
        # So the field has to reach across the whole board, not just the four
        # cells the first version covered: at 0.45 per step a target eight
        # cells away was worth 0.001 and produced no gradient at all.  Values
        # are in strength units so they trade directly against cabbage.
        strength = snapshot.strength
        decay = weights.hunt_decay

        # Gate the whole field by the same economics as the attack rule.
        # Chasing someone is only free once there is nothing left to harvest;
        # early on it costs every cabbage we do not collect while manoeuvring.
        # Ungated, this field pulled the bot into hunting from turn one and
        # cost it a third of its win rate against strong opponents - worse
        # than having no hunting at all.
        hunt_scale = 1.0 / (1.0 + future / max(1.0, strength))

        hunt = [[0.0] * n for _ in range(4)]
        for rival in snapshot.rivals:
            best_gain = 0.0
            for facing in range(4):
                p = win_probability(strength, rival.strength, facing,
                                    rival.direction)
                # Losing keeps the strength we already banked, so the downside
                # is the harvest we forfeit - which late in the match is near
                # nothing.  That is what makes hunting correct then and wrong
                # early, and the search gets the same trade from ``future``.
                gain = p * rival.strength
                if gain > best_gain:
                    best_gain = gain
            if best_gain <= 0.0:
                continue
            best_gain *= hunt_scale
            for facing in range(4):
                row = hunt[facing]
                factor = defence_factor(facing, rival.direction)
                p = win_probability(strength, rival.strength, facing,
                                    rival.direction)
                immediate = p * rival.strength * hunt_scale
                for y in range(size):
                    dy = abs(((y - rival.y) % size + size // 2) % size - size // 2)
                    for x in range(size):
                        dx = abs(((x - rival.x) % size + size // 2) % size - size // 2)
                        d = dx + dy
                        ax, ay = step(x, y, facing, size)
                        if (ax, ay) == (rival.x, rival.y):
                            value = immediate       # we can strike right now
                        else:
                            value = best_gain * (decay ** d)
                        cell = y * size + x
                        if value > row[cell]:
                            row[cell] = value
        self.hunt = hunt

        # --- run-ahead, memoised lazily per (facing, cell) -------------
        self._run: Dict[int, int] = {}
        # Geometric sums, so a run of length k is worth
        # ``gamma + gamma^2 + ... + gamma^k`` rather than k flat.
        gamma = weights.run_discount
        sums = [0.0] * (RUN_CAP + 1)
        for i in range(1, RUN_CAP + 1):
            sums[i] = sums[i - 1] + gamma ** i
        self.run_value = sums

    # ------------------------------------------------------------------
    def run_ahead(self, x: int, y: int, facing: int,
                  eaten: Tuple[Tuple[int, int], ...]) -> int:
        """Unbroken cabbage straight ahead.

        Memoised on ``(facing, cell)``.  ``eaten`` is handled by truncating at
        the first cell this branch has already taken, which is exact whenever
        the branch has not doubled back on itself - and a branch that doubles
        back is one the search is about to discard anyway.
        """
        key = facing * self.size * self.size + y * self.size + x
        cached = self._run.get(key)
        if cached is None:
            cached = self._compute_run(x, y, facing)
            self._run[key] = cached
        if not eaten or cached == 0:
            return cached
        snapshot = self.snapshot
        cx, cy = x, y
        for i in range(cached):
            cx, cy = step(cx, cy, facing, self.size)
            if (cx, cy) in eaten:
                return i
        return cached

    def _compute_run(self, x: int, y: int, facing: int) -> int:
        snapshot = self.snapshot
        size = self.size
        count = 0
        cx, cy = x, y
        for _ in range(RUN_CAP):
            cx, cy = step(cx, cy, facing, size)
            if not snapshot.cabbage[cy * size + cx]:
                break
            if (cx, cy) in snapshot.occupied or snapshot.blocked[cy * size + cx]:
                break
            count += 1
        return count


class Brain:
    """Chooses one action per turn.  One instance lives for a whole match."""

    def __init__(self, weights: Optional[Weights] = None,
                 total_turns: Optional[int] = None, debug: bool = False) -> None:
        self.weights = weights or DEFAULT_WEIGHTS
        self.registry = RivalRegistry()
        self.total_turns = total_turns
        self.debug = debug
        self.turn = 0
        self.faults = 0
        self.slowest_ms = 0.0
        self.total_ms = 0.0
        self.last_action: int = STILL
        self.last_scores: Dict[int, float] = {}
        self.log: List[str] = []
        self._snapshot: Optional[Snapshot] = None
        self._move_probability: Dict[str, float] = {}

    # ------------------------------------------------------------------
    def decide(self, me) -> int:
        """Return the action to take.  Never raises."""
        start = time.perf_counter()
        try:
            snapshot = observe(me, self.turn)
            self._snapshot = snapshot
            self.registry.update(snapshot)
            self.registry.predict_all(snapshot)
            self._move_probability = {
                r.name: self.registry.model_for(r.name).move_probability()
                for r in snapshot.rivals}
            action = self._search(snapshot)
        except Exception:
            self.faults += 1
            action = self._fallback(me)
        self.turn += 1
        elapsed = (time.perf_counter() - start) * 1000.0
        self.total_ms += elapsed
        self.slowest_ms = max(self.slowest_ms, elapsed)
        self.last_action = action
        return action

    # ------------------------------------------------------------------
    # threat
    # ------------------------------------------------------------------
    def danger(self, snapshot: Snapshot, x: int, y: int, facing: int,
               strength: float, ignore: Optional[str] = None) -> float:
        """``P(we are killed)`` if we end our turn at ``(x, y)`` facing ``facing``.

        Only rivals already lined up on us can strike next turn, since they
        must spend a turn to change heading.  Our own facing is what sets
        their odds - turning to meet an attacker cuts them from 91% to 50% -
        so this is a function of ``facing``, not just of position.
        """
        risk = 0.0
        for rival in snapshot.rivals:
            if ignore is not None and rival.name == ignore:
                continue
            ahead = step(rival.x, rival.y, rival.direction, snapshot.size)
            if ahead != (x, y):
                continue
            p_move = self._move_probability.get(rival.name, 1.0 / 3.0)
            p_win = win_probability(rival.strength, strength,
                                    rival.direction, facing)
            risk = risk + p_move * p_win - risk * p_move * p_win
        return min(1.0, risk)

    def _proximity_pressure(self, snapshot: Snapshot, x: int, y: int) -> float:
        """Soft danger from rivals that are close but not yet aimed at us."""
        total = 0.0
        for rival in snapshot.rivals:
            d = distance(x, y, rival.x, rival.y, snapshot.size)
            if d <= 3:
                total += (0.45 ** d) * min(3.0, rival.strength / 4.0 + 0.5)
        return total

    # ------------------------------------------------------------------
    # positional value
    # ------------------------------------------------------------------
    def _scan_run(self, snapshot: Snapshot, x: int, y: int, facing: int) -> int:
        """Unbroken cabbage ahead - the direct scan, for the fallback path.

        The search uses :meth:`TurnFields.run_ahead` instead, which memoises
        this; the fallback must not depend on the field cache existing.
        """
        count = 0
        cx, cy = x, y
        for _ in range(RUN_CAP):
            cx, cy = step(cx, cy, facing, snapshot.size)
            if not snapshot.has_cabbage(cx, cy) or (cx, cy) in snapshot.occupied:
                break
            if snapshot.is_blocked(cx, cy):
                break
            count += 1
        return count

    # ------------------------------------------------------------------
    # search
    # ------------------------------------------------------------------
    def future_value(self, snapshot: Snapshot) -> float:
        """``F``: strength we still expect to harvest if we stay alive.

        Feeds the ``F < a / f`` attack rule, so it is what decides whether a
        fight is worth taking. It shrinks as the board is stripped, which is
        exactly why the bot grows bolder as the match wears on.

        ``total_turns`` is ``None`` by default because the current engine has
        **no turn limit** - ``PacmanGame`` loops until one player is left. The
        board is then the only honest clock: what is left to harvest is the
        cabbage still on it, divided by how many of us are chasing it.

        A number may still be passed for a host that does cap the match, in
        which case the tighter of the two clocks wins. Even then we fall back
        on the board once the count runs out, rather than letting ``F`` pin to
        zero and make ``F < a/f`` true for every angle - which would send the
        bot charging into head-on fights with the board still covered.
        """
        available = snapshot.n_cabbage / max(1.0, 1.0 + len(snapshot.rivals))
        if self.total_turns is None:
            return available
        remaining = self.total_turns - snapshot.turn
        if remaining <= 0:
            return available
        return min(remaining * self.weights.harvest_rate, available)

    def _search(self, snapshot: Snapshot) -> int:
        w = self.weights
        size = snapshot.size
        future = self.future_value(snapshot)

        fields = TurnFields(snapshot, w, self._move_probability, future)

        # node: (score, x, y, facing, strength, alive, banked, eaten, first)
        start = (0.0, snapshot.x, snapshot.y, snapshot.direction,
                 snapshot.strength, 1.0, 0.0, (), -1)
        frontier = [start]
        best_by_action: Dict[int, float] = {}

        for ply in range(w.depth):
            expanded: List[tuple] = []
            for (_, x, y, facing, strength, alive, banked, eaten, first) in frontier:
                for action in range(N_ACTIONS):
                    node = self._apply(snapshot, action, x, y, facing, strength,
                                       alive, banked, eaten, future)
                    if node is None:
                        continue
                    nx, ny, nfacing, nstrength, nalive, nbanked, neaten = node
                    node_first = first if first >= 0 else action
                    value = self._evaluate(fields, nx, ny, nfacing, nstrength,
                                           nalive, nbanked, neaten, ply)
                    expanded.append((value, nx, ny, nfacing, nstrength, nalive,
                                     nbanked, neaten, node_first))
            if not expanded:
                break
            expanded.sort(key=lambda n: -n[0])
            frontier = expanded[:w.beam_width]
            for node in frontier:
                first = node[8]
                if node[0] > best_by_action.get(first, float("-inf")):
                    best_by_action[first] = node[0]

        if not best_by_action:
            return self._greedy_action(snapshot)
        self.last_scores = best_by_action
        action = max(best_by_action, key=lambda a: best_by_action[a])
        if self.debug:
            self.log.append(self._explain(snapshot, action, best_by_action))
        return action

    # ------------------------------------------------------------------
    def _apply(self, snapshot: Snapshot, action: int, x: int, y: int,
               facing: int, strength: float, alive: float, banked: float,
               eaten: Tuple[Tuple[int, int], ...], future: float):
        """One action, then the rivals' reply.  ``None`` prunes the branch."""
        w = self.weights
        size = snapshot.size

        if is_turn(action):
            new_facing = action
            if new_facing == facing:
                return None  # turning to where we already look wastes the turn
            nx, ny = x, y
            nstrength = strength
            neaten = eaten
            nalive, nbanked = alive, banked
        elif action == STILL:
            new_facing = facing
            nx, ny = x, y
            nstrength = strength
            neaten = eaten
            nalive, nbanked = alive, banked
        else:  # MOVE
            new_facing = facing
            nx, ny = step(x, y, facing, size)
            neaten = eaten
            nstrength = strength
            nalive, nbanked = alive, banked
            if snapshot.has_walls and snapshot.is_blocked(nx, ny):
                # ``_Move`` returns without doing anything, so the turn is
                # simply lost. Modelling it as a move would leave the planner
                # believing it is somewhere it never went.
                nx, ny = x, y
            target = snapshot.rival_at(nx, ny)
            if target is not None:
                factor = defence_factor(facing, target.direction)
                if future >= strength / factor * w.attack_margin:
                    return None  # the F < a/f rule says decline this fight
                p = win_probability(strength, target.strength, facing,
                                    target.direction)
                # A loss keeps the strength we had and ends our participation.
                nbanked = banked + alive * (1.0 - p) * strength
                nalive = alive * p
                nstrength = strength + target.strength
            elif snapshot.has_cabbage(nx, ny) and (nx, ny) not in eaten:
                nstrength = strength + 1.0
                neaten = eaten + ((nx, ny),)

        # Now every rival takes its turn before we act again.
        risk = self.danger(snapshot, nx, ny, new_facing, nstrength)
        if risk > 0:
            nbanked = nbanked + nalive * risk * nstrength
            nalive = nalive * (1.0 - risk)
        return nx, ny, new_facing, nstrength, nalive, nbanked, neaten

    # ------------------------------------------------------------------
    def _evaluate(self, fields: "TurnFields", x: int, y: int, facing: int,
                  strength: float, alive: float, banked: float,
                  eaten: Tuple[Tuple[int, int], ...], ply: int) -> float:
        w = self.weights
        horizon = w.discount ** ply
        cell = y * fields.size + x

        positional = w.run_ahead * fields.run_value[
            fields.run_ahead(x, y, facing, eaten)]
        positional += w.density * fields.density[cell]
        positional += w.hunt * fields.hunt[facing][cell]
        positional -= w.exposure * fields.pressure[cell]
        positional += w.survival_bonus

        return banked + alive * (strength + horizon * positional)

    # ------------------------------------------------------------------
    def _greedy_action(self, snapshot: Snapshot) -> int:
        """Cheap, always-sane policy: eat what is in front, else face the
        longest clear run."""
        ahead = step(snapshot.x, snapshot.y, snapshot.direction, snapshot.size)
        if snapshot.rival_at(ahead) is None and snapshot.has_cabbage(*ahead):
            return MOVE
        best_direction, best_run = snapshot.direction, -1
        for direction in range(4):
            run = self._scan_run(snapshot, snapshot.x, snapshot.y, direction)
            if run > best_run:
                best_direction, best_run = direction, run
        if best_direction == snapshot.direction:
            return MOVE if best_run > 0 else STILL
        return TURN_TO[best_direction]

    def _fallback(self, me) -> int:
        """Last resort - needs nothing but the engine objects themselves."""
        try:
            snapshot = observe(me, self.turn)
            return self._greedy_action(snapshot)
        except Exception:
            return MOVE

    # ------------------------------------------------------------------
    def _explain(self, snapshot: Snapshot, chosen: int,
                 scores: Dict[int, float]) -> str:  # pragma: no cover
        lines = [
            f"TURN {snapshot.turn}  ({snapshot.x},{snapshot.y}) "
            f"{DIRECTION_NAMES[snapshot.direction]}  strength={snapshot.strength:g}  "
            f"rank={snapshot.rank()}  cabbage={snapshot.n_cabbage}  F={self.future_value(snapshot):.0f}",
            "  actions:",
        ]
        for action in sorted(scores, key=lambda a: -scores[a]):
            mark = "  <-- chosen" if action == chosen else ""
            lines.append(f"    {ACTION_NAMES[action]:<7s} {scores[action]:9.2f}{mark}")
        risk = self.danger(snapshot, snapshot.x, snapshot.y, snapshot.direction,
                           snapshot.strength)
        lines.append(f"  danger where we stand: {risk:.1%}")
        lines.append("  rivals:")
        lines.append(self.registry.describe(snapshot))
        return "\n".join(lines)

    def timing_report(self) -> str:
        mean = self.total_ms / max(1, self.turn)
        return (f"turns={self.turn} mean={mean:.2f} ms "
                f"slowest={self.slowest_ms:.2f} ms faults={self.faults}")

# ==========================================================================
# Die Klasse
# ==========================================================================

#: Vom Optimierer gefunden (scripts/tune_thorest.py): evolutionaere Suche auf
#: der echten Engine gegen starke Gegner, Champion auf einer getrennten
#: Gegnermischung ausgewaehlt.
TUNED_WEIGHTS = {
    "run_ahead": 1.458919989675242,
    "run_discount": 0.7,
    "density": 0.129959944896416,
    "hunt": 0.3636903463335021,
    "hunt_decay": 0.7511205861003043,
    "exposure": 5.815493413032783,
    "survival_bonus": 15.160453512590712,
    "discount": 0.999,
    "beam_width": 22,
    "depth": 10,
    "attack_margin": 1.056967676909363,
    "harvest_rate": 0.8457841890125624
}

THORES_WEIGHTS = Weights(**TUNED_WEIGHTS)

_DIRECTION_OBJECTS = (Direction.north, Direction.south,
                      Direction.west, Direction.east)


class ThoresT(Pacman):
    """Unser Spieler. Wird wie TRex in die pacmans-Liste eingetragen."""

    def __init__(self, p, name, field):
        super().__init__(p, name, field)
        self.logo = "T"
        self.icon = "icons/TRex.png"   # fuer PacmanRenderer
        self.direction = Direction.west
        # total_turns=None: die Engine hat kein Zuglimit, PacmanGame laeuft
        # bis nur noch einer lebt. Der Kohl auf dem Brett ist dann die
        # einzige ehrliche Uhr.
        self.brain = Brain(weights=THORES_WEIGHTS, total_turns=None)

    def TurnOrMoveOrStill(self):
        # Die Engine ignoriert den Rueckgabewert, also wuerde jede Exception,
        # die hier herauskommt, den Zug kosten - im Turnier die Partie.
        try:
            action = self.brain.decide(self)
        except Exception:
            self.brain.faults += 1
            action = MOVE
        try:
            if action < 4:
                self.direction = _DIRECTION_OBJECTS[action]
            elif action == MOVE:
                self._Move()
            # STILL: absichtlich nichts
        except Exception:
            self.brain.faults += 1


if __name__ == "__main__":
    import random as _random
    import time as _time

    from Pacman import Field as _Field

    try:
        from TRex import TRex as _TRex
    except Exception:
        _TRex = Pacman

    _random.seed(1)
    _pacmans = [[Pacman, "Pacman1"], [Pacman, "Pacman2"], [Pacman, "Pacman3"],
                [_TRex, "Trex1"], [_TRex, "Trex2"], [ThoresT, "ThoresT"]]
    _walls = [[[5, 3], Direction.east, 8], [[5, 4], Direction.south, 3],
              [[12, 4], Direction.south, 3], [[2, 12], Direction.east, 8],
              [[2, 11], Direction.north, 3], [[9, 11], Direction.north, 3]]
    _feld = _Field(15, _pacmans, _walls)
    _ich = next(p for p in _feld.pacmans if p.name == "ThoresT")

    _worst = 0.0
    _zug = 0
    while sum(1 for p in _feld.pacmans if p.alive) > 1 and _zug < 1500:
        for _p in _random.sample(_feld.pacmans, len(_feld.pacmans)):
            if not _p.alive:
                continue
            if _p is _ich:
                _t0 = _time.perf_counter()
                _p.TurnOrMoveOrStill()
                _worst = max(_worst, (_time.perf_counter() - _t0) * 1000.0)
            else:
                _p.TurnOrMoveOrStill()
        _zug += 1

    print("ThoresT Selbsttest (15x15 mit Waenden, bis nur noch einer lebt)")
    print()
    for _p in sorted(_feld.pacmans, key=lambda q: -q.strength):
        _mark = "   <-- wir" if _p is _ich else ""
        _tot = "  (tot)" if not _p.alive else ""
        print(f"  {_p.name:<10s} {_p.strength:6.0f}{_tot}{_mark}")
    _rivals = [_p.strength for _p in _feld.pacmans if _p is not _ich]
    _lebende = sum(1 for p in _feld.pacmans if p.alive)
    print()
    print(f"  nach {_zug} Zuegen, {_lebende} Spieler noch am Leben")
    print(f"  ThoresT {_ich.strength:.0f} gegen besten Gegner {max(_rivals):.0f}"
          f"  ->  {'SIEG' if _ich.strength > max(_rivals) and _ich.alive else 'verloren'}")
    print(f"  {_ich.brain.total_ms / max(1, _ich.brain.turn):.2f} ms/Zug, "
          f"maximal {_worst:.2f} ms, Fehler: {_ich.brain.faults}")
    assert _ich.brain.faults == 0, "die Notfall-Route wurde benutzt"
