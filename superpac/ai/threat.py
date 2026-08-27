"""Time-aware threat maps built from opponent forecasts (brief section 21).

``P(some rival occupies cell c at time t)`` under an independence
approximation:

    P(any) = 1 - prod_i (1 - P_i)

The independence assumption is wrong in detail - rivals converging on the same
pellet are positively correlated, and rivals that would collide are negatively
correlated - but it is cheap, it errs toward *over*-estimating danger in
crowded areas, and measuring it against the alternatives showed no benefit
worth the cost.  The bias direction is the point: an approximation that
overstates risk is a safe one to plan against.

Turn-order uncertainty (section 23) is handled explicitly rather than assumed
away: under simultaneous resolution, walking into a cell a rival also enters
is fatal regardless of who "moved first", and swapping places is fatal too.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from ..game.rules import RuleSet
from ..game.state import GameState


class ThreatMap:
    """Occupancy probabilities over a short horizon, plus the risk queries
    the evaluator and planner actually ask."""

    __slots__ = ("horizon", "frames", "state", "rules", "_pressure",
                 "immediate", "opponent_frames", "current_cells")

    def __init__(self, state: GameState,
                 forecasts: Dict[int, List[Dict[int, float]]],
                 horizon: int = 4) -> None:
        self.state = state
        self.rules = state.rules
        self.horizon = horizon
        self.opponent_frames = forecasts
        self.current_cells = {p: state.positions[p] for p in state.opponents()}

        frames: List[Dict[int, float]] = []
        for t in range(horizon):
            combined: Dict[int, float] = {}
            for per_opponent in forecasts.values():
                if t >= len(per_opponent):
                    continue
                for cell, p in per_opponent[t].items():
                    prior = combined.get(cell, 0.0)
                    # 1 - (1-a)(1-b), accumulated pairwise.
                    combined[cell] = prior + p - prior * p
            frames.append(combined)
        self.frames = frames
        self.immediate = frames[0] if frames else {}
        self._pressure: Optional[Dict[int, float]] = None

    # ------------------------------------------------------------------
    def at(self, cell: int, t: int = 0) -> float:
        """``P(any rival occupies ``cell`` at ``t`` steps from now)``."""
        if t < 0 or t >= len(self.frames):
            return 0.0
        return self.frames[t].get(cell, 0.0)

    # ------------------------------------------------------------------
    def death_probability(self, from_cell: int, to_cell: int, t: int = 0) -> float:
        """Chance that stepping ``from_cell -> to_cell`` kills us.

        Two independent ways to die under simultaneous resolution:

        * a rival enters the same destination cell as us;
        * a rival and we trade places, passing through each other.

        Under non-lethal rule variants this collapses to zero and the planner
        stops paying for collision avoidance it does not need.
        """
        if not self.rules.contact_is_lethal:
            return 0.0
        same_cell = self.at(to_cell, t)
        swap = 0.0
        if t == 0 and to_cell != from_cell:
            for player, frames in self.opponent_frames.items():
                if not frames:
                    continue
                # The rival must be standing on our destination now and moving
                # onto the cell we are leaving.
                if self.current_cells.get(player) != to_cell:
                    continue
                p_swap = frames[0].get(from_cell, 0.0)
                swap = swap + p_swap - swap * p_swap
        return min(1.0, same_cell + swap - same_cell * swap)

    # ------------------------------------------------------------------
    def pressure(self, cell: int, decay: float = 0.6) -> float:
        """Time-discounted danger: near-term threat counts for more."""
        if self._pressure is None:
            table: Dict[int, float] = {}
            weight = 1.0
            for frame in self.frames:
                for c, p in frame.items():
                    table[c] = table.get(c, 0.0) + weight * p
                weight *= decay
            self._pressure = table
        return self._pressure.get(cell, 0.0)

    # ------------------------------------------------------------------
    def safe_exits(self, cell: int, graph, threshold: float = 0.25) -> int:
        """How many ways out of ``cell`` are not obviously lethal.

        This is the mobility number that matters: four exits into a wall of
        threat is worse than two clear ones.
        """
        count = 0
        for nb in graph.neighbors[cell]:
            if self.death_probability(cell, nb, 0) < threshold:
                count += 1
        return count

    def total_threat(self) -> float:
        return sum(self.immediate.values())

    def describe(self, top: int = 5) -> str:  # pragma: no cover - diagnostics
        graph = self.state.graph
        hottest = sorted(self.immediate.items(), key=lambda kv: -kv[1])[:top]
        return "threat t+1: " + ", ".join(
            f"{graph.xy(c)}={p:.2f}" for c, p in hottest)


__all__ = ["ThreatMap"]
