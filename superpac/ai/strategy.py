"""High-level strategy selection (brief section 28).

The evaluator's weights describe *how* to value a position; the strategy layer
decides *which* valuation the current situation calls for.  A bot that plays
the endgame with its opening priorities loses winnable games, and a bot that
plays the opening defensively never gets ahead in the first place.

Modes are chosen from a small set of situational features and applied as
multipliers on the base weights, so the optimiser still only tunes one vector
while the behaviour it produces stays situation-dependent.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, Optional, Tuple

from ..game.state import GameState
from .evaluator import Weights
from .territory import TerritoryAnalysis
from .threat import ThreatMap


class Mode(Enum):
    EXPANSION = "EXPANSION"
    HARVEST = "HARVEST"
    TERRITORY = "TERRITORY"
    DENIAL = "DENIAL"
    INTERCEPT = "INTERCEPT"
    SURVIVAL = "SURVIVAL"
    ENDGAME_LEADING = "ENDGAME_LEADING"
    ENDGAME_TRAILING = "ENDGAME_TRAILING"


#: Multipliers applied to the base weights per mode.  Only the fields that
#: actually differ are listed; everything else keeps its tuned value.
MODE_WEIGHTS: Dict[Mode, Dict[str, float]] = {
    Mode.EXPANSION: {
        "food_potential": 1.15, "territory": 1.30, "mobility": 1.10,
        "information": 1.80, "food": 0.90,
    },
    Mode.HARVEST: {
        "food": 1.25, "food_potential": 1.20, "danger": 0.90,
        "information": 0.60, "territory": 0.85,
    },
    Mode.TERRITORY: {
        "territory": 1.45, "contest": 1.35, "denial": 1.30,
        "cluster": 1.25, "food": 0.95,
    },
    Mode.DENIAL: {
        "denial": 1.90, "contest": 1.50, "territory": 1.25, "food": 1.10,
    },
    Mode.INTERCEPT: {
        "intercept": 2.20, "danger": 0.80, "mobility": 0.90, "death": 0.90,
    },
    Mode.SURVIVAL: {
        # Survival is an override, not a preference: food stops mattering.
        "death": 1.60, "danger": 2.40, "mobility": 2.60, "dead_end": 2.30,
        "trap": 2.20, "food": 0.35, "food_potential": 0.45,
        "information": 0.0, "territory": 0.30,
    },
    Mode.ENDGAME_LEADING: {
        # Ahead and nearly finished: protect the lead, take zero risk.
        "death": 1.45, "danger": 1.55, "mobility": 1.40, "dead_end": 1.50,
        "risk_aversion": 1.50, "food": 0.85, "information": 0.0,
    },
    Mode.ENDGAME_TRAILING: {
        # Behind and out of time: variance is now our friend.
        "food": 1.45, "food_potential": 1.30, "denial": 1.50,
        "danger": 0.65, "death": 0.80, "risk_aversion": 0.45,
        "intercept": 1.60, "information": 0.0,
    },
}


class StrategyManager:
    """Picks a :class:`Mode` each turn and produces the weights to plan with."""

    def __init__(self, base: Weights, survival_threshold: float = 0.30,
                 endgame_at: float = 0.72) -> None:
        self.base = base
        self.survival_threshold = survival_threshold
        self.endgame_at = endgame_at
        self.mode: Mode = Mode.EXPANSION
        self.previous_mode: Mode = Mode.EXPANSION
        self.reason: str = "opening"

    # ------------------------------------------------------------------
    def select(self, state: GameState, territory: TerritoryAnalysis,
               threat: ThreatMap, confidence: float) -> Mode:
        graph = state.graph
        pos = state.my_position
        progress = state.progress()
        gap = state.score_gap()

        # --- danger override ------------------------------------------
        # Worst-case over the moves actually available to us, not the average:
        # three safe exits do not help if we are about to be forced into the
        # fourth.
        exits = graph.legal_actions(pos, state.rules.allow_stay)
        risks = [threat.death_probability(pos, graph.step(pos, a)) for a in exits]
        best_escape = min(risks) if risks else 1.0
        local_threat = threat.pressure(pos)

        if best_escape >= self.survival_threshold or (
            local_threat > 1.1 and threat.safe_exits(pos, graph) <= 1
        ):
            self.reason = f"best escape risk {best_escape:.2f}, pressure {local_threat:.2f}"
            return self._settle(Mode.SURVIVAL)

        # --- endgame ---------------------------------------------------
        if progress >= self.endgame_at:
            if gap > 0:
                self.reason = f"ahead by {gap:.1f} at {progress:.0%}"
                return self._settle(Mode.ENDGAME_LEADING)
            self.reason = f"behind by {-gap:.1f} at {progress:.0%}"
            return self._settle(Mode.ENDGAME_TRAILING)

        # --- opening ---------------------------------------------------
        if progress < 0.18:
            self.reason = "opening: learn and claim ground"
            return self._settle(Mode.EXPANSION)

        # --- midgame ---------------------------------------------------
        contested = territory.contested_food + territory.denied_food
        share_of_contest = contested / max(1, len(state.food))

        # A confidently modelled rival is an exploitable one.  This is the
        # one place prediction confidence changes strategy rather than just
        # sharpening it (brief section 57).
        if confidence > 0.62 and gap < 0 and share_of_contest > 0.30:
            self.reason = f"rivals predictable ({confidence:.2f}) and we trail"
            return self._settle(Mode.DENIAL)

        if share_of_contest > 0.55:
            self.reason = f"{share_of_contest:.0%} of food contested"
            return self._settle(Mode.TERRITORY)

        if territory.my_food_share > 0.42:
            self.reason = f"own {territory.my_food_share:.0%} of remaining food"
            return self._settle(Mode.HARVEST)

        self.reason = "balanced midgame"
        return self._settle(Mode.TERRITORY)

    def _settle(self, mode: Mode) -> Mode:
        self.previous_mode, self.mode = self.mode, mode
        return mode

    # ------------------------------------------------------------------
    def weights_for(self, mode: Mode) -> Weights:
        multipliers = MODE_WEIGHTS.get(mode)
        if not multipliers:
            return self.base
        updates = {}
        for name, factor in multipliers.items():
            current = getattr(self.base, name)
            updates[name] = type(current)(current * factor) if isinstance(current, int) else current * factor
        return self.base.with_(**updates)

    def describe(self) -> str:  # pragma: no cover - diagnostics
        return f"{self.mode.value} ({self.reason})"


__all__ = ["Mode", "StrategyManager", "MODE_WEIGHTS"]
