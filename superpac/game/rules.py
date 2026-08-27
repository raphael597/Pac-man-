"""Game rules, actions and the parameterised :class:`RuleSet`.

No teacher/starter files were present in this repository, so the *exact*
rules of the tournament game are unknown.  Rather than inventing a single
ruleset and hard-coding it everywhere, every rule that could plausibly
differ is expressed as a field on :class:`RuleSet`.  Engine, simulator and
SUPERPAC all read their behaviour from that object, so re-targeting the
project at the real game is a matter of changing *one* dataclass instance
(see ``superpac/game/adapter.py``) instead of rewriting the AI.

Coordinate convention
---------------------
Cells live on a ``width x height`` grid, row-major, and are addressed by a
single integer ``index = y * width + x``.  ``y`` grows *downwards*, so
``NORTH`` is ``y - 1``.  Integer cell ids keep the hot loops allocation
free and let distance tables be flat arrays.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, Final, Sequence, Tuple

# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------
# Plain ints rather than an ``Enum``: these are compared and indexed millions
# of times per match and ``IntEnum`` attribute access is measurably slower.

NORTH: Final[int] = 0
SOUTH: Final[int] = 1
WEST: Final[int] = 2
EAST: Final[int] = 3
STAY: Final[int] = 4

#: All actions including ``STAY``.
ALL_ACTIONS: Final[Tuple[int, ...]] = (NORTH, SOUTH, WEST, EAST, STAY)
#: The four translating actions, in a stable order.
MOVE_ACTIONS: Final[Tuple[int, ...]] = (NORTH, SOUTH, WEST, EAST)

#: ``(dx, dy)`` per action.
DELTAS: Final[Tuple[Tuple[int, int], ...]] = ((0, -1), (0, 1), (-1, 0), (1, 0), (0, 0))

ACTION_NAMES: Final[Tuple[str, ...]] = ("NORTH", "SOUTH", "WEST", "EAST", "STAY")

OPPOSITE: Final[Tuple[int, ...]] = (SOUTH, NORTH, EAST, WEST, STAY)

#: Tolerant lookup used by the adapter when a host engine speaks strings.
NAME_TO_ACTION: Final[Dict[str, int]] = {
    "n": NORTH, "north": NORTH, "up": NORTH, "u": NORTH, "^": NORTH,
    "s": SOUTH, "south": SOUTH, "down": SOUTH, "d": SOUTH, "v": SOUTH,
    "w": WEST, "west": WEST, "left": WEST, "l": WEST, "<": WEST,
    "e": EAST, "east": EAST, "right": EAST, "r": EAST, ">": EAST,
    "stay": STAY, "still": STAY, "none": STAY, "stop": STAY, "wait": STAY,
    "hold": STAY, "pass": STAY, ".": STAY, "0": STAY,
}


def action_from_name(name: object, default: int = STAY) -> int:
    """Best-effort coercion of an arbitrary host action value to our ints."""
    if isinstance(name, bool):  # bool is an int subclass - reject explicitly
        return default
    if isinstance(name, int):
        return name if 0 <= name <= 4 else default
    if isinstance(name, str):
        return NAME_TO_ACTION.get(name.strip().lower(), default)
    if isinstance(name, (tuple, list)) and len(name) == 2:
        try:
            return DELTAS.index((int(name[0]), int(name[1])))
        except (ValueError, TypeError):
            return default
    return default


def delta_to_action(dx: int, dy: int, default: int = STAY) -> int:
    """Map a single-step displacement to an action id."""
    try:
        return DELTAS.index((dx, dy))
    except ValueError:
        return default


# --------------------------------------------------------------------------
# RuleSet
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class RuleSet:
    """Every rule the AI is allowed to depend on, in one place.

    Defaults describe the most common shape of this school exercise: a
    shared grid, simultaneous moves in randomised order, food worth one
    point, and player-player contact eliminating both parties ("Highlander":
    there can be only one).  Each field is independently switchable so a
    mis-guess costs a constructor argument, not a rewrite.
    """

    # --- movement -------------------------------------------------------
    allow_stay: bool = True
    """Whether ``STAY`` is a legal action."""

    wrap_x: bool = False
    wrap_y: bool = False
    """Toroidal wrap-around (Pac-Man style side tunnels)."""

    # --- turn structure -------------------------------------------------
    simultaneous: bool = True
    """All players commit a move, then the world resolves once."""

    turn_order_random: bool = True
    """If sequential, whether the acting order is reshuffled each turn.

    Also used when ``simultaneous`` is true to decide *food* ties: with a
    random order, two players arriving on the same pellet split it by
    coin-flip rather than by fixed seat index.
    """

    # --- collisions -----------------------------------------------------
    collision_mode: str = "elimination"
    """One of ``elimination`` | ``block`` | ``pass`` | ``swap_block``.

    ``elimination``  contact removes players (see ``head_on_resolution``)
    ``block``        a move into an occupied cell is refused, player stays
    ``pass``         players may share cells freely, nothing happens
    ``swap_block``   like ``pass`` but two players may not swap places
    """

    head_on_resolution: str = "both"
    """``both`` | ``none`` | ``higher_score`` | ``mover``.

    Who dies when two players meet.  ``higher_score`` keeps the leader,
    ``mover`` kills whoever entered an occupied cell.
    """

    respawn: bool = False
    """Eliminated players re-enter at their start cell instead of leaving."""

    # --- scoring --------------------------------------------------------
    food_value: float = 1.0
    food_respawn: bool = False
    kill_bonus: float = 0.0
    """Points awarded for eliminating another player, if any."""

    survival_bonus: float = 0.0
    """Points per turn survived - non-zero makes stalling viable."""

    step_cost: float = 0.0
    """Points deducted per move; non-zero punishes aimless travel."""

    # --- termination ----------------------------------------------------
    max_turns: int = 400
    end_on_last_food: bool = True
    end_on_one_survivor: bool = True
    """The 'Highlander' condition: the match stops once a single player is
    left standing."""

    highlander_wins: bool = True
    """A sole survivor wins outright regardless of score."""

    # --- engine limits --------------------------------------------------
    time_limit_ms: float = 100.0
    """Wall-clock budget the host allows per move request."""

    def with_(self, **kwargs) -> "RuleSet":
        """Return a copy with fields replaced (frozen dataclass helper)."""
        return replace(self, **kwargs)

    # -- derived conveniences -------------------------------------------
    @property
    def actions(self) -> Tuple[int, ...]:
        return ALL_ACTIONS if self.allow_stay else MOVE_ACTIONS

    @property
    def contact_is_lethal(self) -> bool:
        return self.collision_mode == "elimination" and self.head_on_resolution != "none"

    @property
    def cells_are_shareable(self) -> bool:
        return self.collision_mode in ("pass", "swap_block")


#: The working assumption used everywhere until teacher files arrive.
DEFAULT_RULES: Final[RuleSet] = RuleSet()

#: A handful of named variants, so benchmarks can prove SUPERPAC is not
#: silently overfitted to one interpretation of the rules.
RULE_VARIANTS: Final[Dict[str, RuleSet]] = {
    "default": DEFAULT_RULES,
    "highlander": DEFAULT_RULES.with_(collision_mode="elimination", head_on_resolution="both"),
    "survivor": DEFAULT_RULES.with_(collision_mode="elimination", head_on_resolution="higher_score"),
    "peaceful": DEFAULT_RULES.with_(collision_mode="pass", end_on_one_survivor=False),
    "blocking": DEFAULT_RULES.with_(collision_mode="block", end_on_one_survivor=False),
    "sequential": DEFAULT_RULES.with_(simultaneous=False, turn_order_random=True),
    "no_stay": DEFAULT_RULES.with_(allow_stay=False),
    "tunnels": DEFAULT_RULES.with_(wrap_x=True),
}


def turn_order_probabilities(n_players: int) -> float:
    """Probability that a given player acts before a given rival.

    With a uniformly random order over ``n_players`` the pairwise race is a
    coin flip, independent of how many others are in the game.  Kept as a
    function so the assumption is documented and testable rather than a bare
    ``0.5`` buried in the evaluator.
    """
    if n_players < 2:
        return 1.0
    return 0.5


def food_contest_share(n_contenders: int, random_order: bool) -> float:
    """Expected share of a pellet that ``n_contenders`` players arrive at."""
    if n_contenders <= 1:
        return 1.0
    return 1.0 / n_contenders if random_order else 0.0


__all__ = [
    "NORTH", "SOUTH", "WEST", "EAST", "STAY",
    "ALL_ACTIONS", "MOVE_ACTIONS", "DELTAS", "ACTION_NAMES", "OPPOSITE",
    "NAME_TO_ACTION", "action_from_name", "delta_to_action",
    "RuleSet", "DEFAULT_RULES", "RULE_VARIANTS",
    "turn_order_probabilities", "food_contest_share",
]
