"""The mutable world model handed to the AI and stepped by the simulator."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .map_model import MapGraph, UNREACHABLE
from .rules import DEFAULT_RULES, RuleSet


class GameState:
    """A complete, compact snapshot of one turn.

    Static structure lives on :attr:`graph` and is *shared* between every
    clone; only the small dynamic parts (food set, positions, scores) are
    copied.  A clone therefore costs one set copy and three list copies,
    which is what makes forward simulation inside the planner affordable.
    """

    __slots__ = ("turn", "graph", "rules", "food", "positions", "scores",
                 "alive", "me", "n_players", "spawns", "_legal_cache")

    def __init__(
        self,
        graph: MapGraph,
        food: Iterable[int],
        positions: Sequence[int],
        me: int = 0,
        turn: int = 0,
        scores: Optional[Sequence[float]] = None,
        alive: Optional[Sequence[bool]] = None,
        rules: Optional[RuleSet] = None,
        spawns: Optional[Sequence[int]] = None,
    ) -> None:
        self.graph = graph
        self.rules = rules or DEFAULT_RULES
        self.food: Set[int] = set(food)
        self.positions: List[int] = list(positions)
        self.n_players = len(self.positions)
        self.scores: List[float] = list(scores) if scores is not None else [0.0] * self.n_players
        self.alive: List[bool] = list(alive) if alive is not None else [True] * self.n_players
        self.me = me
        self.turn = turn
        self.spawns: Tuple[int, ...] = tuple(spawns) if spawns is not None else tuple(self.positions)
        self._legal_cache: Optional[Tuple[int, ...]] = None

    # ------------------------------------------------------------------
    def clone(self) -> "GameState":
        new = GameState.__new__(GameState)
        new.graph = self.graph
        new.rules = self.rules
        new.food = set(self.food)
        new.positions = self.positions[:]
        new.scores = self.scores[:]
        new.alive = self.alive[:]
        new.me = self.me
        new.turn = self.turn
        new.n_players = self.n_players
        new.spawns = self.spawns
        new._legal_cache = None
        return new

    # ------------------------------------------------------------------
    @property
    def my_position(self) -> int:
        return self.positions[self.me]

    @property
    def my_score(self) -> float:
        return self.scores[self.me]

    @property
    def am_alive(self) -> bool:
        return self.alive[self.me]

    def opponents(self) -> List[int]:
        """Indices of every *living* player that is not us."""
        me = self.me
        return [p for p in range(self.n_players) if p != me and self.alive[p]]

    def opponent_positions(self) -> List[int]:
        me = self.me
        return [self.positions[p] for p in range(self.n_players)
                if p != me and self.alive[p]]

    def legal_actions(self, player: Optional[int] = None) -> Tuple[int, ...]:
        """Actions that do not walk into a wall.

        Collision legality is deliberately *not* enforced here: whether a
        move into an occupied cell is illegal, fatal or fine depends on
        :attr:`RuleSet.collision_mode`, and the planner wants to reason about
        those outcomes rather than have them silently pruned.
        """
        if player is None:
            player = self.me
            if self._legal_cache is not None:
                return self._legal_cache
        pos = self.positions[player]
        if pos < 0:
            return (4,) if self.rules.allow_stay else ()
        acts = self.graph.legal_actions(pos, self.rules.allow_stay)
        if not acts:  # fully walled in - STAY is the only thing left
            acts = (4,)
        if player == self.me:
            self._legal_cache = acts
        return acts

    def leader(self) -> int:
        """Player index with the highest score (ties -> lowest index)."""
        best, best_score = 0, float("-inf")
        for p in range(self.n_players):
            if self.alive[p] and self.scores[p] > best_score:
                best, best_score = p, self.scores[p]
        return best

    def my_rank(self) -> int:
        """0 = leading.  Counts living players strictly ahead of us."""
        mine = self.scores[self.me]
        return sum(1 for p in range(self.n_players)
                   if p != self.me and self.alive[p] and self.scores[p] > mine)

    def score_gap(self) -> float:
        """Our score minus the best *other* living score (negative = behind)."""
        others = [self.scores[p] for p in range(self.n_players)
                  if p != self.me and self.alive[p]]
        if not others:
            return self.scores[self.me]
        return self.scores[self.me] - max(others)

    def living_count(self) -> int:
        return sum(1 for a in self.alive if a)

    def is_terminal(self) -> bool:
        r = self.rules
        if self.turn >= r.max_turns:
            return True
        if r.end_on_last_food and not self.food:
            return True
        if r.end_on_one_survivor and self.living_count() <= 1:
            return True
        return False

    def progress(self) -> float:
        """0.0 at kickoff, 1.0 at the projected end of the match.

        Uses whichever of the two clocks (turns burnt, food eaten) is further
        along, so a fast-clearing map correctly reads as 'late game' even on
        turn 40.
        """
        by_turn = self.turn / max(1, self.rules.max_turns)
        total = len(self.food) + sum(self.scores) / max(1e-9, self.rules.food_value)
        by_food = 1.0 - len(self.food) / total if total > 0 else 1.0
        return max(0.0, min(1.0, max(by_turn, by_food)))

    # ------------------------------------------------------------------
    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        gx = self.graph.xy
        return (
            f"<GameState t={self.turn} me={self.me}@{gx(self.my_position)} "
            f"food={len(self.food)} scores={[round(s, 1) for s in self.scores]} "
            f"alive={self.alive}>"
        )

    def render(self, marks: Optional[Dict[int, str]] = None) -> str:
        """ASCII dump for debugging and test failure messages."""
        g = self.graph
        rows: List[str] = []
        marks = marks or {}
        for y in range(g.height):
            row: List[str] = []
            for x in range(g.width):
                idx = y * g.width + x
                if idx in marks:
                    row.append(marks[idx])
                elif not g.passable[idx]:
                    row.append("#")
                elif idx in self.positions and self.alive[self.positions.index(idx)]:
                    row.append(str(self.positions.index(idx)))
                elif idx in self.food:
                    row.append(".")
                else:
                    row.append(" ")
            rows.append("".join(row))
        return "\n".join(rows)


__all__ = ["GameState"]
