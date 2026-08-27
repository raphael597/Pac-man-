"""SUPERPAC: the agent.

Per-turn pipeline:

    observe rivals  ->  update models  ->  predict + forecast
                    ->  territory / threat / potential fields
                    ->  pick strategy  ->  anytime robust search
                    ->  act  ->  measure prediction error  ->  repeat

Two guarantees hold no matter what:

1. **A legal action is always returned.**  Every subsystem call is guarded and
   degrades to a simpler layer, ending at a fallback that only needs the map.
2. **The clock is respected.**  The budget is a fraction of the host's limit,
   the search is anytime, and the fallback path is microseconds.

A crashed or timed-out turn is worth strictly less than a mediocre move, so
sophistication is always the thing that gets sacrificed first.
"""

from __future__ import annotations

import random
import time
from typing import Dict, List, Optional, Sequence, Tuple

from ..game.map_model import UNREACHABLE
from ..game.rules import ACTION_NAMES, DEFAULT_RULES, RuleSet, STAY
from ..game.state import GameState
from ..opponents.model import OpponentRegistry
from .evaluator import DEFAULT_WEIGHTS, TurnFields, Weights
from .planner import Planner, PlanResult
from .strategy import Mode, StrategyManager
from .territory import TerritoryAnalysis
from .threat import ThreatMap

#: Fraction of the host's per-move limit we are willing to spend.  The rest is
#: headroom for interpreter jitter, GC pauses and a slower tournament machine.
#: Section 35 suggests 65-80%; benchmarking put the safe value at the low end.
TIME_SAFETY = 0.62


class SuperPac:
    """The tournament agent."""

    name = "superpac"

    def __init__(self, seed: Optional[int] = None,
                 weights: Optional[Weights] = None,
                 rules: Optional[RuleSet] = None,
                 debug: bool = False,
                 time_budget_ms: Optional[float] = None) -> None:
        self.rng = random.Random(20260827 if seed is None else seed)
        self.weights = weights or DEFAULT_WEIGHTS
        self.rules = rules or DEFAULT_RULES
        self.debug = debug
        self.time_budget_ms = time_budget_ms

        self.registry = OpponentRegistry()
        self.strategy = StrategyManager(self.weights)
        self.planner = Planner(self.rng)

        self.player_id = 0
        self.turn_count = 0
        self.recent: Dict[int, int] = {}
        self.last_plan: Optional[PlanResult] = None
        self.last_mode: Mode = Mode.EXPANSION
        self.faults = 0
        self.slowest_ms = 0.0
        self.total_ms = 0.0
        self._log: List[str] = []

    # ------------------------------------------------------------------
    def reset(self, state: GameState, player_id: int) -> None:
        self.player_id = player_id
        self.registry = OpponentRegistry()
        self.strategy = StrategyManager(self.weights)
        self.recent.clear()
        self.turn_count = 0
        self.faults = 0
        self.slowest_ms = 0.0
        self.total_ms = 0.0
        self._log.clear()

    # ------------------------------------------------------------------
    def act(self, state: GameState) -> int:
        """Choose a move.  Never raises, never overruns, never returns an
        illegal action."""
        start = time.perf_counter()
        limit_ms = self.time_budget_ms or state.rules.time_limit_ms
        deadline = start + (limit_ms / 1000.0) * TIME_SAFETY

        try:
            action = self._think(state, deadline)
        except Exception:
            self.faults += 1
            action = self.fallback(state)

        legal = state.legal_actions(state.me)
        if action not in legal:
            self.faults += 1
            action = self.fallback(state)

        self._remember(state, action)
        self.turn_count += 1
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        self.total_ms += elapsed_ms
        if elapsed_ms > self.slowest_ms:
            self.slowest_ms = elapsed_ms
        return action

    # ------------------------------------------------------------------
    def _think(self, state: GameState, deadline: float) -> int:
        # 1. learn from what the rivals just did
        self.registry.update(state)

        # 2. predict, then forecast forward
        horizon = max(2, self.weights.forecast_horizon)
        forecasts = self.registry.forecast_all(state, horizon)
        threat = ThreatMap(state, forecasts, horizon)

        # 3. strategic fields
        territory = TerritoryAnalysis(state, softness=self.weights.territory_softness)
        confidence = self.registry.mean_confidence(state)

        # 4. what kind of game is this right now?
        mode = self.strategy.select(state, territory, threat, confidence)
        self.last_mode = mode
        weights = self.strategy.weights_for(mode)

        fields = TurnFields(state, territory, threat, weights, self.recent)

        # 5. search, annealing exploration as the game becomes decisive
        explore_scale = max(0.0, 1.0 - state.progress() / 0.65)
        plan = self.planner.plan(state, fields, territory, threat,
                                 self.registry, weights, deadline, explore_scale)
        self.last_plan = plan

        if self.debug:
            self._log.append(self.explain(state, plan, mode, territory, threat))
        return plan.action

    # ------------------------------------------------------------------
    def fallback(self, state: GameState) -> int:
        """Legal, safe, food-positive, mobility-positive - in that order.

        Deliberately depends on nothing but the map and the rivals' current
        cells, so it still works when every model above it has failed.
        """
        try:
            graph = state.graph
            pos = state.my_position
            legal = state.legal_actions(state.me)
            if not legal:
                return STAY

            rivals = [c for c in state.opponent_positions() if c >= 0]
            occupied = set(rivals)
            adjacent = set()
            for cell in rivals:
                adjacent.update(graph.neighbors[cell])

            lethal = state.rules.contact_is_lethal
            best_action, best_key = legal[0], None
            for action in legal:
                target = graph.step(pos, action)
                danger = 0
                if lethal:
                    if target in occupied:
                        danger = 2
                    elif target in adjacent:
                        danger = 1
                key = (
                    -danger,
                    1 if target in state.food else 0,
                    graph.degree[target],
                    -graph.dead_end_depth[target],
                    -self.recent.get(target, 0),
                )
                if best_key is None or key > best_key:
                    best_action, best_key = action, key
            return best_action
        except Exception:
            try:
                legal = state.legal_actions(state.me)
                return legal[0] if legal else STAY
            except Exception:
                return STAY

    # ------------------------------------------------------------------
    def _remember(self, state: GameState, action: int) -> None:
        """Decaying memory of where we have been - breaks oscillation."""
        for cell in list(self.recent):
            value = self.recent[cell] - 1
            if value <= 0:
                del self.recent[cell]
            else:
                self.recent[cell] = value
        try:
            self.recent[state.my_position] = 6
        except Exception:
            pass

    # ------------------------------------------------------------------
    # diagnostics (development only - never called in the tournament build)
    # ------------------------------------------------------------------
    def explain(self, state: GameState, plan: PlanResult, mode: Mode,
                territory: TerritoryAnalysis, threat: ThreatMap) -> str:
        graph = state.graph
        lines = [
            f"TURN {state.turn}  me={graph.xy(state.my_position)} "
            f"score={state.my_score:.0f} gap={state.score_gap():+.0f} "
            f"food={len(state.food)} progress={state.progress():.0%}",
            f"strategy: {self.strategy.describe()}",
            f"search  : depth={plan.depth_reached} nodes={plan.nodes} "
            f"{plan.elapsed * 1000:.1f} ms  scenarios={len(plan.scenarios)}",
            f"territory: share={territory.my_food_share:.0%} "
            f"contested={territory.contested_food} denied={territory.denied_food} "
            f"cells={territory.my_cells}",
            "actions :",
        ]
        for action in sorted(plan.scores, key=lambda a: -plan.scores[a]):
            marker = " <-- chosen" if action == plan.action else ""
            pv = plan.principal_variation.get(action, [])
            pv_text = ">".join(ACTION_NAMES[a][0] for a in pv) if pv else "-"
            lines.append(
                f"   {ACTION_NAMES[action]:<6s} {plan.scores[action]:9.2f} "
                f"risk={plan.risk.get(action, 0.0):7.2f} "
                f"info={plan.info_values.get(action, 0.0):.2f} pv={pv_text}{marker}")
        lines.append(threat.describe())
        lines.append(self.registry.describe(state))
        return "\n".join(lines)

    def diagnostics(self) -> str:  # pragma: no cover - development aid
        return "\n\n".join(self._log[-3:])

    def timing_report(self) -> str:
        mean = self.total_ms / max(1, self.turn_count)
        return (f"turns={self.turn_count} mean={mean:.2f} ms "
                f"slowest={self.slowest_ms:.2f} ms faults={self.faults}")


__all__ = ["SuperPac", "TIME_SAFETY"]
