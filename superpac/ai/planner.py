"""Anytime look-ahead planning under uncertainty (brief sections 18-20, 34-35).

Three ideas, layered:

**A beam per first action.**  A single shared beam collapses onto whichever
opening move looks best after one ply, leaving the alternatives with no
estimate at all - which is useless when the whole point is to *compare* them.
Each candidate opening therefore gets its own beam and its own deep value.

**Discrete scenarios for the immediate step.**  The threat map gives smooth
occupancy probabilities, which is right for valuing distant futures but wrong
for the next move: dying is all-or-nothing, and a move with a 25% chance of
death is far worse than its average suggests.  The next step is therefore
evaluated against concrete joint opponent assignments (section 19), producing
a distribution of outcomes rather than a mean.

**Risk-aware combination.**  Those outcomes are combined as a blend of
expected value and conditional value at risk - the average of the bad tail -
so the chosen move has to be good *and* survive being wrong (section 20).

The whole thing is anytime: a legal, sensible action exists before the search
starts and improves monotonically until the clock runs out.
"""

from __future__ import annotations

import math
import random
import time
from typing import Dict, List, Optional, Sequence, Tuple

from ..game.map_model import UNREACHABLE
from ..game.rules import ACTION_NAMES, STAY
from ..game.state import GameState
from ..opponents.model import OpponentRegistry
from .evaluator import TurnFields, Weights
from .territory import TerritoryAnalysis
from .threat import ThreatMap


class PlanResult:
    """The chosen action plus everything needed to explain it."""

    __slots__ = ("action", "scores", "depth_reached", "nodes", "elapsed",
                 "principal_variation", "risk", "scenarios", "info_values")

    def __init__(self) -> None:
        self.action: int = STAY
        self.scores: Dict[int, float] = {}
        self.depth_reached: int = 0
        self.nodes: int = 0
        self.elapsed: float = 0.0
        self.principal_variation: Dict[int, List[int]] = {}
        self.risk: Dict[int, float] = {}
        self.scenarios: List[Tuple[float, Dict[int, int]]] = []
        self.info_values: Dict[int, float] = {}


class Planner:
    """Owns the search.  Stateless between turns apart from its RNG."""

    def __init__(self, rng: Optional[random.Random] = None) -> None:
        self.rng = rng or random.Random(0xBEEF)

    # ------------------------------------------------------------------
    def plan(self, state: GameState, fields: TurnFields,
             territory: TerritoryAnalysis, threat: ThreatMap,
             registry: OpponentRegistry, weights: Weights,
             deadline: float, explore_scale: float = 1.0) -> PlanResult:
        result = PlanResult()
        start = time.perf_counter()
        graph = state.graph
        pos = state.my_position
        legal = list(state.legal_actions(state.me))
        if not legal:
            result.action = STAY
            return result

        # --- depth 0: an answer exists before we search at all ----------
        immediate = {a: self._shallow_score(state, fields, graph.step(pos, a))
                     for a in legal}
        result.scores = dict(immediate)
        result.action = max(legal, key=lambda a: immediate[a])

        scenarios = self._build_scenarios(state, registry, weights.scenario_count)
        result.scenarios = scenarios

        info = {a: self._information_value(state, registry, graph.step(pos, a))
                for a in legal} if weights.information > 0 else {a: 0.0 for a in legal}
        result.info_values = info

        # --- iterative deepening ---------------------------------------
        deep: Dict[int, float] = dict(immediate)
        for depth in range(2, weights.max_depth + 1):
            if time.perf_counter() >= deadline:
                break
            values, pv, nodes = self._beam(state, fields, weights, legal, depth,
                                           deadline)
            result.nodes += nodes
            if not values:
                break
            deep = values
            result.principal_variation = pv
            result.depth_reached = depth
            if time.perf_counter() >= deadline:
                break

        # --- risk-aware scenario combination ---------------------------
        final: Dict[int, float] = {}
        for action in legal:
            target = graph.step(pos, action)
            base = deep.get(action, immediate[action])
            base += weights.information * explore_scale * info[action]
            expected, cvar = self._scenario_outcomes(
                state, scenarios, pos, target, base, weights)
            lam = max(0.0, min(1.0, weights.risk_aversion))
            final[action] = (1.0 - lam) * expected + lam * cvar
            result.risk[action] = expected - cvar

        result.scores = final
        result.action = self._choose(final, legal, weights)
        result.elapsed = time.perf_counter() - start
        return result

    # ------------------------------------------------------------------
    def _shallow_score(self, state: GameState, fields: TurnFields,
                       cell: int) -> float:
        return fields.positional_score(cell, 0) + fields.step_reward(cell, frozenset())

    # ------------------------------------------------------------------
    def _beam(self, state: GameState, fields: TurnFields, weights: Weights,
              legal: Sequence[int], depth: int, deadline: float
              ) -> Tuple[Dict[int, float], Dict[int, List[int]], int]:
        """One beam per opening move, expanded to ``depth`` plies.

        Death at ``t = 0`` is deliberately *not* charged here - the scenario
        pass handles the immediate step discretely.  Deaths at ``t >= 1`` are
        charged as a survival-weighted expectation, which is the right
        treatment for outcomes far enough away to be avoidable.
        """
        graph = state.graph
        pos = state.my_position
        discount = weights.discount
        width = max(2, weights.beam_width)
        nodes = 0

        # node: (utility, cell, survival, eaten, path)
        beams: Dict[int, List[Tuple[float, int, float, tuple, tuple]]] = {}
        for action in legal:
            cell = graph.step(pos, action)
            reward = fields.step_reward(cell, ())
            eaten = (cell,) if reward > 0 else ()
            beams[action] = [(reward, cell, 1.0, eaten, (action,))]

        for ply in range(1, depth):
            if time.perf_counter() >= deadline:
                break
            for action in legal:
                frontier = beams[action]
                if not frontier:
                    continue
                expanded: List[Tuple[float, int, float, tuple, tuple]] = []
                for utility, cell, survival, eaten, path in frontier:
                    for step_action in graph.legal_actions(cell, state.rules.allow_stay):
                        target = graph.step(cell, step_action)
                        nodes += 1
                        p_death = fields.threat.death_probability(cell, target, ply)
                        new_survival = survival * (1.0 - p_death)
                        reward = fields.step_reward(target, eaten)
                        new_eaten = eaten + (target,) if reward > 0 else eaten
                        new_utility = utility + (discount ** ply) * new_survival * reward
                        expanded.append((new_utility, target, new_survival,
                                         new_eaten, path + (step_action,)))
                if not expanded:
                    continue
                horizon = discount ** ply
                expanded.sort(
                    key=lambda n: -(n[0] + horizon * n[2] * fields.positional_score(n[1], ply)))
                beams[action] = expanded[:width]

        values: Dict[int, float] = {}
        pv: Dict[int, List[int]] = {}
        for action in legal:
            best_value = None
            best_path: tuple = (action,)
            for utility, cell, survival, eaten, path in beams[action]:
                ply = len(path) - 1
                total = (utility
                         + (discount ** ply) * survival * fields.positional_score(cell, ply)
                         - weights.death * (1.0 - survival))
                if best_value is None or total > best_value:
                    best_value, best_path = total, path
            if best_value is not None:
                values[action] = best_value
                pv[action] = list(best_path)
        return values, pv, nodes

    # ------------------------------------------------------------------
    def _build_scenarios(self, state: GameState, registry: OpponentRegistry,
                         limit: int) -> List[Tuple[float, Dict[int, int]]]:
        """Top-``limit`` joint opponent next-positions with probabilities.

        Enumerated rather than sampled: with two or three plausible moves per
        rival the whole cross product is small, and enumeration is both
        deterministic (reproducible benchmarks) and free of sampling noise.
        """
        graph = state.graph
        opponents = state.opponents()
        if not opponents:
            return [(1.0, {})]

        per_player: List[List[Tuple[int, float]]] = []
        ids: List[int] = []
        for player in opponents:
            model = registry.model_for(player)
            distribution = model.last_prediction or model.predict(state)
            cell = state.positions[player]
            options: Dict[int, float] = {}
            for action in range(5):
                p = distribution[action]
                if p <= 0.02:
                    continue
                target = graph.step(cell, action)
                options[target] = options.get(target, 0.0) + p
            ranked = sorted(options.items(), key=lambda kv: -kv[1])[:3]
            total = sum(p for _, p in ranked) or 1.0
            per_player.append([(c, p / total) for c, p in ranked])
            ids.append(player)

        scenarios: List[Tuple[float, Dict[int, int]]] = [(1.0, {})]
        for player, options in zip(ids, per_player):
            grown: List[Tuple[float, Dict[int, int]]] = []
            for probability, assignment in scenarios:
                for cell, p in options:
                    merged = dict(assignment)
                    merged[player] = cell
                    grown.append((probability * p, merged))
            grown.sort(key=lambda s: -s[0])
            # Prune breadth-first so the cross product never explodes.
            scenarios = grown[: max(limit, 4) * 2]

        scenarios.sort(key=lambda s: -s[0])
        scenarios = scenarios[:limit]
        total = sum(p for p, _ in scenarios) or 1.0
        return [(p / total, assignment) for p, assignment in scenarios]

    # ------------------------------------------------------------------
    def _scenario_outcomes(self, state: GameState,
                           scenarios: Sequence[Tuple[float, Dict[int, int]]],
                           from_cell: int, to_cell: int, base_value: float,
                           weights: Weights) -> Tuple[float, float]:
        """``(expected value, conditional value at risk)`` for one move."""
        lethal = state.rules.contact_is_lethal
        outcomes: List[Tuple[float, float]] = []
        for probability, assignment in scenarios:
            value = base_value
            if lethal:
                for player, cell in assignment.items():
                    if cell == to_cell:
                        value = -weights.death
                        break
                    # Trading places is contact too, not a near miss.
                    if cell == from_cell and state.positions[player] == to_cell:
                        value = -weights.death
                        break
            outcomes.append((probability, value))

        expected = sum(p * v for p, v in outcomes)
        # CVaR: average of the worst outcomes covering the bottom tail.
        outcomes.sort(key=lambda pv: pv[1])
        tail_mass = 0.30
        collected = 0.0
        weighted = 0.0
        for probability, value in outcomes:
            take = min(probability, tail_mass - collected)
            if take <= 0:
                break
            weighted += take * value
            collected += take
        cvar = weighted / collected if collected > 0 else expected
        return expected, cvar

    # ------------------------------------------------------------------
    def _information_value(self, state: GameState, registry: OpponentRegistry,
                           cell: int) -> float:
        """Expected information gain from standing at ``cell`` (section 26).

        Concretely: standing at a distance that *splits* a rival's escape
        threshold posterior tells us which side of it we are on.  Binary
        entropy peaks exactly at the distance where the posterior is most
        divided, which is where the observation is most informative - and the
        term is scaled by how unsure we still are, so a solved rival stops
        attracting probes.
        """
        graph = state.graph
        total = 0.0
        for player in state.opponents():
            model = registry.model_for(player)
            confidence = model.confidence()
            if confidence > 0.80:
                continue
            hypothesis = model.ensemble.get("greedy_escape")
            if hypothesis is None:
                continue
            posterior = getattr(hypothesis, "posterior", None)
            candidates = getattr(hypothesis, "CANDIDATES", None)
            if not posterior or not candidates:
                continue
            distance = graph.distance(cell, state.positions[player])
            if distance >= UNREACHABLE or distance > 10:
                continue
            p_flee = sum(w for w, threshold in zip(posterior, candidates)
                         if threshold >= distance)
            p_flee = min(1.0 - 1e-6, max(1e-6, p_flee))
            entropy = -(p_flee * math.log2(p_flee)
                        + (1 - p_flee) * math.log2(1 - p_flee))
            # Close observations are more informative but also more dangerous;
            # the planner's own danger term prices that separately.
            total += entropy * (1.0 - confidence) / (1.0 + 0.25 * distance)
        return total

    # ------------------------------------------------------------------
    def _choose(self, scores: Dict[int, float], legal: Sequence[int],
                weights: Weights) -> int:
        """Argmax with controlled randomness among genuine ties (section 48).

        The tie band is relative to the spread of the options, so a 0.2 gap
        counts as a tie when the options span 200 points and as decisive when
        they span 1.  Never trades away real value for the sake of looking
        unpredictable.
        """
        best_action = max(legal, key=lambda a: scores[a])
        best = scores[best_action]
        if weights.explore_epsilon <= 0:
            return best_action
        worst = min(scores[a] for a in legal)
        spread = max(1e-6, best - worst)
        band = weights.explore_epsilon * spread
        tied = [a for a in legal if scores[a] >= best - band]
        if len(tied) <= 1:
            return best_action
        return self.rng.choice(tied)


__all__ = ["Planner", "PlanResult"]
